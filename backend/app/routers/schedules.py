"""自主经营调度任务路由：定时自动运行工作流/趋势扫描。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..auth import get_current_user, is_impersonating_user, require_permission
from ..db import get_db
from ..models import Schedule, User, WorkflowTemplate, utcnow
from ..serialize import to_dict
from ..services.action_identity import require_action_permission
from ..services.ai_actions import ActionError
from ..services.schedule_identity import bind_schedule
from ..services.scheduler import run_task
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/schedules", tags=["schedules"])
schedule_write = require_permission("ai:write", ("admin", "operator"))


class ScheduleIn(BaseModel):
    name: str
    kind: str = "workflow"          # workflow / trend_scan / alert_scan
    workflow_key: str = ""
    interval_minutes: int = 1440
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = None
    interval_minutes: int | None = None
    enabled: bool | None = None


@router.get("")
def list_schedules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(Schedule).filter(Schedule.tenant_id == user.tenant_id)
            .order_by(Schedule.id).all())
    return {"items": [to_dict(r) for r in rows]}


@router.post("")
def create_schedule(body: ScheduleIn, user: User = Depends(schedule_write),
                    db: Session = Depends(get_db)):
    if body.kind not in ("workflow", "trend_scan", "alert_scan"):
        raise HTTPException(status_code=400,
                            detail="kind 必须是 workflow / trend_scan / alert_scan")
    if body.kind == "workflow":
        tpl = (db.query(WorkflowTemplate)
               .filter(WorkflowTemplate.tenant_id == user.tenant_id,
                       WorkflowTemplate.key == body.workflow_key).first())
        if not tpl:
            raise HTTPException(status_code=404, detail=f"工作流模板 {body.workflow_key} 不存在")
    if not 5 <= body.interval_minutes <= 60 * 24 * 30:
        raise HTTPException(status_code=400, detail="间隔需在 5 分钟 ~ 30 天之间")
    s = Schedule(tenant_id=user.tenant_id, **body.model_dump())
    _bind(db, s, user)
    db.add(s)
    db.commit()
    return to_dict(s)


@router.put("/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleUpdate,
                    user: User = Depends(schedule_write), db: Session = Depends(get_db)):
    s = _owned(db, user.tenant_id, schedule_id)
    if body.name is not None:
        s.name = body.name
    if body.interval_minutes is not None:
        if not 5 <= body.interval_minutes <= 60 * 24 * 30:
            raise HTTPException(status_code=400, detail="间隔需在 5 分钟 ~ 30 天之间")
        s.interval_minutes = body.interval_minutes
    if body.enabled is not None:
        if body.enabled:
            if s.last_status == "running":
                raise HTTPException(status_code=409, detail="调度正在执行，请等待完成后重新绑定")
            _bind(db, s, user)
        s.enabled = body.enabled
    db.commit()
    return to_dict(s)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, user: User = Depends(schedule_write),
                    db: Session = Depends(get_db)):
    s = _owned(db, user.tenant_id, schedule_id)
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/{schedule_id}/run")
def trigger_now(schedule_id: int, user: User = Depends(schedule_write),
                db: Session = Depends(get_db)):
    """立即手动执行一次（不等待调度周期）。"""
    s = _owned(db, user.tenant_id, schedule_id)
    _authorize_execution(db, s, user)
    claimed = db.execute(update(Schedule).where(
        Schedule.id == s.id, Schedule.last_status != "running").values(last_status="running"))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="调度任务正在执行")
    db.commit()
    ok, detail = run_task(s.tenant_id, s.kind, s.workflow_key, schedule=s)
    s.last_run_at = utcnow()
    s.run_count += 1
    s.last_status = ("dispatched" if ok and s.kind == "workflow" and
                     ("(running)" in detail or "(queued)" in detail) else "success" if ok else "failed")
    db.commit()
    return {"ok": ok, "detail": detail, "schedule": to_dict(s)}


def _owned(db: Session, tenant_id: int, schedule_id: int) -> Schedule:
    s = db.get(Schedule, schedule_id)
    if not s or s.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="调度任务不存在")
    return s


def _bind(db, task, user):
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        bind_schedule(db, task, ctx)
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _authorize_execution(db, task, user):
    """手动触发同样检查当前身份，不能借其他发起人的绑定提升权限。"""
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        if ctx.is_impersonating:
            raise ActionError(403, "代客访问不能执行自主调度")
        require_action_permission(db, ctx, "product:write" if task.kind == "trend_scan" else "ai:write")
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
