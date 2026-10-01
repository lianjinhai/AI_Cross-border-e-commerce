"""自主经营调度器（AI 运营中心）：按分钟级间隔自动执行工作流/趋势扫描。

- 单后台守护线程，每 30s 检查一次到期任务；到点后在独立线程执行，互不阻塞。
- 任务配置持久化在 schedules 表，可经 /api/schedules 在线增删启停。
- last_run_at + interval 决定下一次执行时间；无锁竞争用 per-run 独立会话。
"""
import threading
import traceback
from datetime import datetime, timedelta

from sqlalchemy import update

from .. import config
from ..db import SessionLocal
from ..models import Schedule
from .ai_actions import ActionError
from .schedule_identity import schedule_context

_TICK_SECONDS = 30
_started = threading.Event()
_lock = threading.Lock()


def start_scheduler() -> None:
    """随应用启动（测试同步模式或重复调用时跳过）。"""
    if _started.is_set() or config.settings.sync_workflow:
        return
    with _lock:
        if _started.is_set():
            return
        _started.set()
    threading.Thread(target=_loop, name="erp-scheduler", daemon=True).start()


def _loop() -> None:
    while True:
        try:
            _tick()
        except Exception:  # 调度循环永不退出
            traceback.print_exc()
        threading.Event().wait(_TICK_SECONDS)


def _tick() -> None:
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        due = db.query(Schedule).filter(Schedule.enabled.is_(True)).all()
        for task in due:
            next_at = (task.last_run_at or task.created_at) + timedelta(minutes=task.interval_minutes)
            if now < next_at or task.last_status == "running":
                continue
            changed = db.execute(update(Schedule).where(
                Schedule.id == task.id, Schedule.enabled.is_(True), Schedule.last_status != "running"
            ).values(last_status="running"))
            db.commit()
            if changed.rowcount != 1:
                continue
            threading.Thread(target=_execute, args=(task.id,), daemon=True).start()
    finally:
        db.close()


def _execute(schedule_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.get(Schedule, schedule_id)
        if not task or not task.enabled:
            return
        ok, detail = run_task(task.tenant_id, task.kind, task.workflow_key, schedule=task)
        task.last_run_at = datetime.utcnow()
        task.run_count += 1
        task.last_status = ("dispatched" if ok and task.kind == "workflow" and
                            ("(running)" in detail or "(queued)" in detail) else "success" if ok else "failed")
        db.commit()
        print(f"[scheduler] #{task.id} {task.name} -> {task.last_status} {detail}")
    except Exception:
        db.rollback()
        task = db.get(Schedule, schedule_id)
        if task:
            task.last_run_at = datetime.utcnow()
            task.last_status = "failed"
            db.commit()
        traceback.print_exc()
    finally:
        db.close()


def run_task(tenant_id: int, kind: str, workflow_key: str, *, schedule=None) -> tuple[bool, str]:
    """执行一次任务体：workflow 跑工作流模板；trend_scan 扫趋势；alert_scan 主动巡检。"""
    if schedule is None or schedule.tenant_id != tenant_id or schedule.kind != kind:
        return False, "缺少可信调度身份绑定"
    try:
        with SessionLocal() as identity_db:
            stored = identity_db.get(Schedule, schedule.id)
            if stored is None or stored.tenant_id != tenant_id or stored.kind != kind:
                return False, "调度任务归属或类型已变化"
            schedule_context(identity_db, stored)
    except (ActionError, ValueError) as exc:
        return False, str(exc)
    if kind in {"workflow", "trend_scan"}:
        # 既有 services→workflow 债务保留，调度不再反向调用领域Agent。
        from ..workflows.engine import run_scheduled_task
        try:
            with SessionLocal() as task_db:
                stored = task_db.get(Schedule, schedule.id, populate_existing=True)
                if stored is None or stored.tenant_id != tenant_id or stored.kind != kind:
                    return False, "调度任务归属或类型已变化"
                return run_scheduled_task(task_db, stored)
        except (ActionError, ValueError) as exc:
            return False, str(exc)
    if kind == "alert_scan":
        from ..services import alerting

        db = SessionLocal()
        try:
            result = alerting.scan(db, tenant_id)
        finally:
            db.close()
        return True, f"{result['created']} alerts (skipped {result['skipped']})"
    return False, f"未知任务类型 {kind}"
