"""AI Action 的租户内查看、人工审批与幂等执行。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user, is_impersonating_user
from ..db import get_db
from ..models import User
from ..services import action_queue
from ..services.action_identity import (
    requester_context,
    require_publish_action_scope,
)
from ..services.action_policy import POLICIES
from ..services.action_system import HANDLERS, decide_action, execute_action
from ..services.ai_actions import (
    ActionError,
    action_dict,
    owned_action,
)
from ..services.store_scope import StoreScopeError
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/actions", tags=["actions"])


class DecisionIn(BaseModel):
    note: str


def _ctx(db: Session, user: User):
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    return ctx


def _operation_ctx(db, user, approval=False):
    ctx = _ctx(db, user)
    permissions = {POLICIES[key].permission for key in HANDLERS
                   if not approval or POLICIES[key].approval}
    if not any(ctx.has(permission) for permission in permissions):
        raise HTTPException(status_code=403, detail="没有此类 Action 操作权限")
    return ctx


def _call(func, *args):
    try:
        return action_dict(func(*args))
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("")
def list_actions(status: str | None = None, action_type: str | None = None,
                 page_num: int = 1, page_size: int = 50, limit: int | None = None,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Action 列表（S3：支持「全部」类型/状态、分页与总数）。

    - ``action_type`` 省略或 ``ALL`` → 全部**已注册**类型；给出未知类型 → 400。
    - ``status`` 省略或 ``ALL`` → 全部状态；给出未知状态 → 400。
    - ``page_size`` 主口径；``limit`` 仅作旧调用兼容（等价于 page_size）。
    """
    ctx = _ctx(db, user)
    type_filter = None if action_type in (None, "", "ALL", "all") else action_type
    if type_filter is not None and type_filter not in HANDLERS:
        raise HTTPException(status_code=400, detail="Action 类型无效")
    status_filter = None if status in (None, "", "ALL", "all") else status
    if status_filter is not None and status_filter not in action_queue.VALID_STATUS:
        raise HTTPException(status_code=400, detail="Action 状态无效")
    # 权限：单类型看该类型权限；「全部」= 本人持有权限的类型集合（队列里每条都能动）。
    if type_filter:
        if not ctx.has(POLICIES[type_filter].permission):
            raise HTTPException(status_code=403, detail="没有此类 Action 操作权限")
        allowed_types = None
    else:
        allowed_types = [key for key in HANDLERS if ctx.has(POLICIES[key].permission)]
        if not allowed_types:
            raise HTTPException(status_code=403, detail="没有此类 Action 操作权限")
    size = limit if limit is not None and page_size == 50 else page_size
    try:
        rows, total = action_queue.query_actions(
            db, ctx, type_filter, status_filter, page_num, size, allowed_types)
    except StoreScopeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    page, size = action_queue._normalize_paging(page_num, size)
    return {"items": [action_dict(row) for row in rows], "total": total,
            "page_num": page, "page_size": size}


@router.get("/{action_id}")
def get_action(action_id: int, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    """单条 Action 详情（含证据、预期影响、执行结果）——列表之外的可恢复入口。"""
    ctx = _ctx(db, user)
    action = _owned(db, ctx, action_id)
    return action_dict(action)


@router.get("/{action_id}/result")
def get_action_result(action_id: int, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """执行回执：只返回终态与 outcome（无结果时 outcome 为空对象，不伪造成功）。"""
    ctx = _ctx(db, user)
    action = _owned(db, ctx, action_id)
    return {"id": action.id, "action_type": action.action_type, "status": action.status,
            "outcome": action.outcome or {}, "executed_by": action.executed_by,
            "executed_at": action.executed_at, "updated_at": action.updated_at,
            "terminal": action.status in ("SUCCESS", "FAILED", "REJECTED")}


def _owned(db, ctx, action_id):
    """按工作空间/租户取 Action，并复核发布类店铺范围（与列表同一收窄口径）。"""
    try:
        action = owned_action(db, ctx, action_id)
        require_publish_action_scope(db, ctx, action, requester_context(db, action))
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except StoreScopeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return action


@router.post("/{action_id}/approve")
def approve(action_id: int, body: DecisionIn,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx = _operation_ctx(db, user, approval=True)
    return _call(decide_action, db, ctx, action_id, True, body.note)


@router.post("/{action_id}/reject")
def reject(action_id: int, body: DecisionIn,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx = _operation_ctx(db, user, approval=True)
    return _call(decide_action, db, ctx, action_id, False, body.note)


@router.post("/{action_id}/execute")
def execute(action_id: int, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    ctx = _operation_ctx(db, user)
    return _call(execute_action, db, ctx, action_id)
