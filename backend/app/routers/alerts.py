"""主动巡检路由（M3）：告警列表/确认、规则配置、手动触发巡检。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import AlertRule, User
from ..serialize import to_dict
from ..services import alerting

router = APIRouter(prefix="/alerts", tags=["alerts"])


class RuleUpdate(BaseModel):
    enabled: bool | None = None
    level: str | None = None
    threshold: dict | None = None


@router.get("")
def list_alerts(status: str = "", level: str = "", limit: int = 100,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """告警列表（high 优先）。默认返回全部状态，可筛 open/acked。"""
    rows = alerting.list_alerts(db, user.tenant_id, status=status, level=level, limit=limit)
    items = [to_dict(r) for r in rows]
    # counts 与 total 都走数据库聚合：列表有 limit，数列表长度会少算
    # （total 曾等于 len(items)，与契约里「总数」的语义不符——一旦前端按
    #  total 做分页就会漏数据）。
    return {"items": items, "returned": len(items),
            "total": alerting.alert_total(db, user.tenant_id, status, level),
            "counts": alerting.alert_counts(db, user.tenant_id)}


@router.put("/{alert_id}/ack")
def ack(alert_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    """确认告警（标记已处理，不删除——保留审计痕迹）。"""
    row = alerting.ack_alert(db, user.tenant_id, alert_id)
    if not row:
        raise HTTPException(status_code=404, detail="告警不存在")
    return to_dict(row)


@router.get("/rules")
def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """巡检规则配置（9 条，可启停/调阈值）。"""
    alerting.ensure_default_rules(db, user.tenant_id)
    rows = (db.query(AlertRule).filter(AlertRule.tenant_id == user.tenant_id)
            .order_by(AlertRule.id).all())
    return {"items": [to_dict(r) for r in rows]}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate,
                user: User = Depends(require_write), db: Session = Depends(get_db)):
    row = db.get(AlertRule, rule_id)
    if not row or row.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="规则不存在")
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.level is not None:
        if body.level not in ("high", "mid", "low"):
            raise HTTPException(status_code=400, detail="级别必须是 high/mid/low")
        row.level = body.level
    if body.threshold is not None:
        merged = dict(row.threshold or {})
        merged.update(body.threshold)
        row.threshold = merged
    db.commit()
    return to_dict(row)


@router.post("/scan")
def trigger_scan(user: User = Depends(require_write), db: Session = Depends(get_db)):
    """手动触发一轮巡检（调度器默认每 6 小时自动执行）。"""
    return alerting.scan(db, user.tenant_id)
