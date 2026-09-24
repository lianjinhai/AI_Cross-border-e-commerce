"""AI 工作流路由：模板 / 运行 / 历史（第十六章多 Agent 协同）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import User, WorkflowRun, WorkflowStep, WorkflowTemplate
from ..serialize import to_dict
from ..workflows.engine import resume_run, start_run

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/runs/{run_id}/resume")
def resume(run_id: int, user: User = Depends(require_write)):
    try:
        return resume_run(run_id, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class RunIn(BaseModel):
    template_key: str
    context: dict = {}


@router.get("/templates")
def templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(WorkflowTemplate).filter(WorkflowTemplate.tenant_id == user.tenant_id)
            .order_by(WorkflowTemplate.id).all())
    return {"items": [to_dict(r) for r in rows]}


@router.post("/run")
def run(body: RunIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    try:
        run_dict = start_run(user.tenant_id, body.template_key, body.context)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    steps = (db.query(WorkflowStep).filter(WorkflowStep.run_id == run_dict["id"])
             .order_by(WorkflowStep.seq).all())
    run_dict["steps"] = [to_dict(s) for s in steps]
    return run_dict


@router.get("/runs")
def runs(limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(WorkflowRun).filter(WorkflowRun.tenant_id == user.tenant_id)
            .order_by(WorkflowRun.created_at.desc()).limit(max(1, min(100, limit))).all())
    return {"items": [to_dict(r) for r in rows]}


@router.get("/runs/{run_id}")
def run_detail(run_id: int, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    r = db.get(WorkflowRun, run_id)
    if not r or r.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    steps = (db.query(WorkflowStep).filter(WorkflowStep.run_id == run_id)
             .order_by(WorkflowStep.seq).all())
    return {**to_dict(r), "steps": [to_dict(s) for s in steps]}
