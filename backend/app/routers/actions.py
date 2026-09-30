"""AI Action 的租户内查看、人工审批与幂等执行。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import AiAction, User
from ..services.ai_actions import (
    ActionError,
    action_dict,
    decide_budget_action,
    execute_budget_action,
    finance_scope,
)
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/actions", tags=["actions"])


class DecisionIn(BaseModel):
    note: str


def _ctx(db: Session, user: User):
    ctx = resolve_workspace_context(db, user)
    try:
        finance_scope(db, ctx)
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return ctx


def _call(func, *args):
    try:
        return action_dict(func(*args))
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("")
def list_actions(status: str = "PENDING_APPROVAL", limit: int = 50,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx = _ctx(db, user)
    if status not in {"PENDING_APPROVAL", "APPROVED", "SUCCESS", "FAILED", "REJECTED"}:
        raise HTTPException(status_code=400, detail="Action 状态无效")
    rows = (db.query(AiAction).filter(AiAction.workspace_id == ctx.workspace_id,
                                     AiAction.tenant_id == ctx.legacy_tenant_id,
                                     AiAction.action_type == "ADJUST_AD_BUDGET",
                                     AiAction.status == status)
            .order_by(AiAction.id.desc()).limit(max(1, min(limit, 200))).all())
    return {"items": [action_dict(row) for row in rows]}


@router.post("/{action_id}/approve")
def approve(action_id: int, body: DecisionIn,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(decide_budget_action, db, _ctx(db, user), action_id, True, body.note)


@router.post("/{action_id}/reject")
def reject(action_id: int, body: DecisionIn,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(decide_budget_action, db, _ctx(db, user), action_id, False, body.note)


@router.post("/{action_id}/execute")
def execute(action_id: int, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    return _call(execute_budget_action, db, _ctx(db, user), action_id)
