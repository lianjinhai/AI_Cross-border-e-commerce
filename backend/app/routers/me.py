"""Workspace Context API（P1-09）：身份快照查询 + 活动 Workspace 切换校验。

契约见 `docs/phase1_interfaces.md` 第 8 节（FROZEN）。
本模块不建表、不写库、不改 JWT：切换语义当前是"校验 + 审计"，
真正的持久化留给 P1-06（Membership 落地后）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user, is_impersonating_user
from ..db import get_db
from ..models import User
from ..services.workspace_context import WorkspaceContext, resolve_workspace_context

logger = logging.getLogger("erp.workspace_context_api")

router = APIRouter(prefix="/me", tags=["me"])


def _workspace_item(context: WorkspaceContext) -> dict:
    """Context → 列表项（字段冻结：id/name/kind/role/source/is_active）。"""
    return {
        "id": context.workspace_id,
        "name": context.workspace_name,
        "kind": context.workspace_kind,
        "role": context.role,
        "source": context.source,
        "is_active": True,   # 当前阶段只有一个活动 Workspace
    }


def _current_context(db: Session, user: User) -> WorkspaceContext:
    """解析当前请求的 Workspace Context（**所有** /api/me/* 端点必须走这里）。

    为什么收敛成一个 helper：代客标记此前由三个端点各自 ``getattr`` 读取，
    历史上就漏过（``/workspaces``、``/switch`` 未透传，导致代客态被误判为
    Platform 身份、返回空集合）。把「读哪个标记、叫什么名字」的唯一知识
    放在这里（判定函数在 ``app.auth.is_impersonating_user``），
    新增端点时不可能再漏。
    """
    return resolve_workspace_context(
        db, user, is_impersonating=is_impersonating_user(user)
    )


def _accessible_workspaces(context: WorkspaceContext) -> list[dict]:
    """当前可访问集合 = Context 自身那一个 Workspace。

    - Platform Identity（source=PLATFORM，workspace_id=None）：空集合，不报错；
    - Factory Collaborator：已绑定工厂时返回其 Factory Workspace；
      未绑定（workspace_id=None）时同样为空集合，不臆造 id；
    - Legacy fallback：返回其 tenant 对应的唯一 Workspace。
    """
    if context.workspace_id is None:
        return []
    return [_workspace_item(context)]


def _audit_switch(context: WorkspaceContext, target_workspace_id: int, result: str) -> None:
    """切换审计：只写 trace_id / user_id / workspace_id / result，禁止 PII。"""
    logger.info("workspace switch audited", extra={
        "trace_id": context.trace_id,
        "user_id": context.user_id,
        "workspace_id": target_workspace_id,
        "result": result,
    })


@router.get("/workspaces")
def list_workspaces(user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    context = _current_context(db, user)
    items = _accessible_workspaces(context)
    return {"items": items, "total": len(items)}


@router.get("/workspace-context")
def get_workspace_context(user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    return _current_context(db, user).to_public_dict()


@router.post("/workspaces/{workspace_id}/switch")
def switch_workspace(workspace_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    context = _current_context(db, user)
    # Platform Identity 优先判定：它没有业务 Workspace，不能落进"不可访问"分支
    if context.is_platform_identity():
        _audit_switch(context, workspace_id, "forbidden_platform_identity")
        raise HTTPException(status_code=403, detail="平台身份无业务 Workspace，无法切换")
    if context.workspace_id is None or workspace_id != context.workspace_id:
        # 404 语义依据：Phase 1 可访问集合只有 Context 自身一个 Workspace。
        # 要区分"存在但无权限(403)"必须先查 Workspace 注册表（P1-06 Membership），
        # 该表当前未落地；且 403/404 的差异会泄露其他租户 Workspace 是否存在。
        # 因此统一按"不在可访问集合即不存在"返回 404，禁止静默回退到旧 Workspace。
        _audit_switch(context, workspace_id, "not_accessible")
        raise HTTPException(status_code=404, detail="Workspace 不存在或不可访问")
    # 幂等成功：目标就是当前 Context 的 Workspace，无需变更任何状态。
    # TODO(P1-06): Membership 落地后在此校验 ACTIVE Membership，并持久化活动 Workspace。
    _audit_switch(context, workspace_id, "ok")
    return {"ok": True, "workspace_id": workspace_id,
            "role": context.role, "source": context.source}
