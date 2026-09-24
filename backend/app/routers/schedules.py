"""自主经营调度任务路由：定时自动运行工作流/趋势扫描。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import Schedule, User, WorkflowTemplate, utcnow
from ..serialize import to_dict
from ..services.scheduler import run_task

router = APIRouter(prefix="/schedules", tags=["schedules"])


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
def create_schedule(body: ScheduleIn, user: User = Depends(require_write),
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
    db.add(s)
    db.commit()
    return to_dict(s)


@router.put("/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleUpdate,
                    user: User = Depends(require_write), db: Session = Depends(get_db)):
    s = _owned(db, user.tenant_id, schedule_id)
    if body.name is not None:
        s.name = body.name
    if body.interval_minutes is not None:
        if not 5 <= body.interval_minutes <= 60 * 24 * 30:
            raise HTTPException(status_code=400, detail="间隔需在 5 分钟 ~ 30 天之间")
        s.interval_minutes = body.interval_minutes
    if body.enabled is not None:
        s.enabled = body.enabled
    db.commit()
    return to_dict(s)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, user: User = Depends(require_write),
                    db: Session = Depends(get_db)):
    s = _owned(db, user.tenant_id, schedule_id)
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/{schedule_id}/run")
def trigger_now(schedule_id: int, user: User = Depends(require_write),
                db: Session = Depends(get_db)):
    """立即手动执行一次（不等待调度周期）。"""
    s = _owned(db, user.tenant_id, schedule_id)
    ok, detail = run_task(s.tenant_id, s.kind, s.workflow_key)
    s.last_run_at = utcnow()
    s.run_count += 1
    s.last_status = "success" if ok else "failed"
    db.commit()
    return {"ok": ok, "detail": detail, "schedule": to_dict(s)}


def _owned(db: Session, tenant_id: int, schedule_id: int) -> Schedule:
    s = db.get(Schedule, schedule_id)
    if not s or s.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="调度任务不存在")
    return s
