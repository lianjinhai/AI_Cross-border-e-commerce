"""AI Action 的租户内查看、人工审批与幂等执行。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user, is_impersonating_user
from ..db import get_db
from ..models import User
from ..services import action_queue
from ..services.action_identity import require_action_permission
from ..services.action_policy import POLICIES
from ..services.action_system import HANDLERS, decide_action, execute_action
from ..services.ai_actions import (
    ActionError,
    action_dict,
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
def list_actions(status: str = "PENDING_APPROVAL", limit: int = 50,
                 action_type: str = "ADJUST_AD_BUDGET",
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx = _ctx(db, user)
    if action_type not in HANDLERS:
        raise HTTPException(status_code=400, detail="Action 类型无效")
    try:
        require_action_permission(db, ctx, POLICIES[action_type].permission)
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if status not in action_queue.VALID_STATUS:
        raise HTTPException(status_code=400, detail="Action 状态无效")
    try:
        rows = action_queue.list_actions(db, ctx, action_type, status, limit)
    except StoreScopeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"items": [action_dict(row) for row in rows]}


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
