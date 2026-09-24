"""平台服务商（superadmin）路由：租户管理 / 服务授权 / 代客访问 / 审计。"""
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import create_token, get_current_user, hash_password
from ..db import get_db
from ..models import (
    AdCampaign,
    AiLog,
    Listing,
    Order,
    Product,
    Tenant,
    TenantAccessLog,
    User,
    utcnow,
)
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict
from ..services.membership_service import ensure_workspace_profile, sync_membership

router = APIRouter(prefix="/admin", tags=["platform-admin"])

_ROLES = {"admin", "operator", "viewer"}


def _require_superadmin(user=Depends(get_current_user)) -> User:
    if getattr(user, "role", "") != "superadmin":
        raise HTTPException(status_code=403, detail="需要平台服务商(superadmin)权限")
    return user


def _tenant_stats(db: Session, tenant_id: int) -> dict:
    return {
        "users": db.query(func.count(User.id)).filter(User.tenant_id == tenant_id).scalar() or 0,
        "products": db.query(func.count(Product.id)).filter(Product.tenant_id == tenant_id).scalar() or 0,
        "orders": db.query(func.count(Order.id)).filter(Order.tenant_id == tenant_id).scalar() or 0,
        "listings": db.query(func.count(Listing.id)).filter(Listing.tenant_id == tenant_id).scalar() or 0,
        "ads": db.query(func.count(AdCampaign.id)).filter(AdCampaign.tenant_id == tenant_id).scalar() or 0,
    }


class TenantIn(BaseModel):
    name: str
    plan: str = "pro"                 # trial/pro/enterprise
    license_days: int = 365
    admin_username: str = ""
    admin_password: str = ""          # 缺省自动生成（响应中一次性返回）


class TenantUpdate(BaseModel):
    name: str | None = None
    plan: str | None = None
    status: str | None = None         # active/suspended
    license_days: int | None = None   # 续期天数
    license_note: str | None = None


@router.get("/tenants")
def list_tenants(page_num: int = PageNum, page_size: int = PageSize,
                 user: User = Depends(_require_superadmin), db: Session = Depends(get_db)):
    q = db.query(Tenant).order_by(Tenant.id)
    total = q.count()
    rows = q.offset((page_num - 1) * page_size).limit(page_size).all()
    items = []
    for t in rows:
        d = to_dict(t)
        d["stats"] = _tenant_stats(db, t.id)
        items.append(d)
    return page(items, total, page_num, page_size)


@router.post("/tenants")
def create_tenant(body: TenantIn, user: User = Depends(_require_superadmin),
                  db: Session = Depends(get_db)):
    """开通客户公司租户：建租户 + 初始管理员账号（密码一次性返回）。"""
    if body.plan not in ("trial", "pro", "enterprise"):
        raise HTTPException(status_code=400, detail="plan 必须是 trial/pro/enterprise")
    t = Tenant(name=body.name, plan=body.plan, status="active",
               license_until=utcnow() + timedelta(days=body.license_days),
               license_note=f"由 {user.display_name} 开通")
    db.add(t)
    db.flush()
    password = body.admin_password or secrets.token_urlsafe(9)
    username = body.admin_username or f"admin{t.id}"
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="管理员用户名已存在")
    admin = User(tenant_id=t.id, username=username,
                 password_hash=hash_password(password),
                 display_name=f"{body.name} 管理员", role="admin")
    db.add(admin)
    db.flush()
    # 身份表写入：不建 profile 时该租户永远拿不到 MEMBERSHIP Context，
    # Phase 1.8 删旧入口后新租户会失去身份来源（实测过 source=LEGACY_FALLBACK）。
    ensure_workspace_profile(db, t.id, t.name)
    sync_membership(db, admin, workspace_name=t.name)
    db.commit()
    return {**to_dict(t), "admin_username": username, "admin_password": password}


@router.put("/tenants/{tenant_id}")
def update_tenant(tenant_id: int, body: TenantUpdate,
                  user: User = Depends(_require_superadmin), db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="租户不存在")
    if body.name is not None:
        t.name = body.name
    if body.plan is not None:
        if body.plan not in ("trial", "pro", "enterprise"):
            raise HTTPException(status_code=400, detail="plan 不合法")
        t.plan = body.plan
    if body.status is not None:
        if body.status not in ("active", "suspended"):
            raise HTTPException(status_code=400, detail="status 必须是 active/suspended")
        t.status = body.status
    if body.license_days is not None:
        base = t.license_until if (t.license_until and t.license_until > utcnow()) else utcnow()
        t.license_until = base + timedelta(days=body.license_days)
        t.license_note = f"{user.display_name} 续期 {body.license_days} 天"
    if body.license_note is not None:
        t.license_note = body.license_note
    db.commit()
    return {**to_dict(t), "stats": _tenant_stats(db, t.id)}


@router.post("/tenants/{tenant_id}/enter")
def enter_tenant(tenant_id: int, user: User = Depends(_require_superadmin),
                 db: Session = Depends(get_db)):
    """代客访问：签发目标租户上下文 token（业务操作按该租户执行，全程留审计）。"""
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="租户不存在")
    if t.status != "active":
        raise HTTPException(status_code=400, detail="租户已停用，无法进入")
    if t.license_until and t.license_until < utcnow():
        raise HTTPException(status_code=400,
                            detail="该租户服务授权已到期，请续期后再代客访问")
    token = create_token(user, tenant_override=t.id)
    db.add(TenantAccessLog(operator_id=user.id, operator_name=user.display_name,
                           tenant_id=t.id, action="enter"))
    db.commit()
    return {"token": token, "tenant": to_dict(t),
            "hint": "前端将以此 token 进入该租户工作台，操作即该租户业务操作（已记录审计）"}


@router.get("/access_logs")
def access_logs(limit: int = 50, user: User = Depends(_require_superadmin),
                db: Session = Depends(get_db)):
    rows = (db.query(TenantAccessLog)
            .order_by(TenantAccessLog.id.desc())
            .limit(max(1, min(200, limit))).all())
    items = [to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.get("/ai_logs")
def ai_logs(limit: int = 100, user: User = Depends(_require_superadmin),
            db: Session = Depends(get_db)):
    """全平台 AI 调用日志（跨租户），供平台服务商监控系统级 AI 用量与故障。"""
    rows = (db.query(AiLog).order_by(AiLog.created_at.desc().nullslast(), AiLog.id.desc())
            .limit(max(1, min(500, limit))).all())
    items = [to_dict(r, exclude=["prompt"]) for r in rows]
    return {"items": items, "total": len(items)}


@router.get("/overview")
def overview(user: User = Depends(_require_superadmin), db: Session = Depends(get_db)):
    """平台运营总览：租户数/用户数/数据量/授权情况。"""
    tenants = db.query(Tenant).all()
    expiring = [t for t in tenants
                if t.license_until and t.license_until < utcnow() + timedelta(days=30)]
    return {"tenants": len(tenants),
            "active": len([t for t in tenants if t.status == "active"]),
            "suspended": len([t for t in tenants if t.status != "active"]),
            "expiring_in_30d": len(expiring),
            "users": db.query(func.count(User.id)).scalar(),
            "orders_total": db.query(func.count(Order.id)).scalar() or 0}
