"""AI 设置路由：模型配置 / 平台参数 / Orchestrator 对话 / 调用日志。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.capabilities import capability_matrix
from ..agents.orchestrator import OrchestratorAgent
from ..ai.llm import get_llm_config, set_llm_config
from ..auth import (
    get_current_user,
    is_impersonating_user,
    require_admin_or_platform_admin,
    require_write,
)
from ..db import get_db
from ..models import AiLog, User
from ..serialize import to_dict
from ..services import settings_service
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/ai", tags=["ai"])

# 配置默认值与三级回退统一由 services/settings_service.py 提供（P1-10 作用域隔离）


class ChatIn(BaseModel):
    message: str


@router.get("/capabilities")
def get_capabilities(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """AI 能力矩阵（只读）：能用哪些 Action、为什么不能用、各 Agent 注册了哪些 Action。

    以注册表为准（POLICIES / HANDLERS / CONTRACTS），前端不得自行推断能力边界。
    """
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    return capability_matrix(db, ctx)


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    llm = get_llm_config(db)
    from ..services import open_1688

    api_cfg = open_1688.get_config(db)
    return {"llm": {**llm, "api_key": "", "has_key": bool(llm.get("api_key"))},
            "platform_fees": settings_service.get_setting(db, user.tenant_id, "platform_fees"),
            "fx": settings_service.get_setting(db, user.tenant_id, "fx"),
            "rules": settings_service.get_setting(db, user.tenant_id, "rules"),
            "open_1688": {**api_cfg, "app_secret": "",
                          "has_key": bool(api_cfg.get("app_key") and api_cfg.get("app_secret"))}}


@router.put("/settings")
def put_settings(body: dict, user: User = Depends(require_admin_or_platform_admin),
                 db: Session = Depends(get_db)):
    """按 key 分流写入，防止租户管理员改写平台级配置。

    平台级 key（llm / open_1688）：仅平台服务商（superadmin）可写；
    租户级 key（platform_fees / fx / rules）：写入当前租户的 tenant_settings，
    不影响其他租户。
    """
    is_platform_admin = user.role == "superadmin"

    if "llm" in body:
        if not is_platform_admin:
            raise HTTPException(status_code=403,
                                detail="大模型密钥属平台级配置，仅平台服务商可修改")
        llm_in = dict(body["llm"])
        if llm_in.get("api_key") == "":
            llm_in.pop("api_key")  # 空串表示不修改密钥
        set_llm_config(db, llm_in)
    if "open_1688" in body:
        if not is_platform_admin:
            raise HTTPException(status_code=403,
                                detail="1688 开放平台密钥属平台级配置，仅平台服务商可修改")
        from ..services import open_1688

        open_1688.set_config(db, body["open_1688"] or {})

    for key in settings_service.TENANT_KEYS:
        if key not in body:
            continue
        if is_platform_admin:
            # 平台服务商改写的是「平台默认值」，租户未覆盖时生效
            settings_service.set_platform_default(db, key, body[key] or {})
        else:
            settings_service.set_tenant_setting(db, user.tenant_id, key, body[key] or {})
    db.commit()
    return get_settings(user, db)


@router.post("/chat")
def chat(body: ChatIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    with OrchestratorAgent(user.tenant_id, context=ctx) as a:
        return a.chat(body.message)


@router.get("/decisions")
def decisions(subject_type: str = "", subject_id: int | None = None,
              agent: str = "", limit: int = 50,
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """AI 决策解释（M6）：查某对象的决策依据链，回答"为什么这么判"。

    示例：GET /api/ai/decisions?subject_type=product&subject_id=12
    返回该商品的评分/定价等决策，每条含 decision 与 evidence（数据引用）。
    """
    from ..models import AiDecision

    q = db.query(AiDecision).filter(AiDecision.tenant_id == user.tenant_id)
    if subject_type:
        q = q.filter(AiDecision.subject_type == subject_type)
    if subject_id is not None:
        q = q.filter(AiDecision.subject_id == subject_id)
    if agent:
        q = q.filter(AiDecision.agent == agent)
    rows = q.order_by(AiDecision.created_at.desc()).limit(max(1, min(200, limit))).all()
    return {"items": [to_dict(r) for r in rows], "total": len(rows)}


@router.get("/logs")
def logs(limit: int = 50, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(AiLog).filter(AiLog.tenant_id == user.tenant_id)
            .order_by(AiLog.created_at.desc().nullslast(), AiLog.id.desc())
            .limit(max(1, min(200, limit))).all())
    return {"items": [to_dict(r, exclude=["prompt"]) for r in rows]}
