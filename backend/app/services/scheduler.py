"""自主经营调度器（AI 运营中心）：按分钟级间隔自动执行工作流/趋势扫描。

- 单后台守护线程，每 30s 检查一次到期任务；到点后在独立线程执行，互不阻塞。
- 任务配置持久化在 schedules 表，可经 /api/schedules 在线增删启停。
- last_run_at + interval 决定下一次执行时间；无锁竞争用 per-run 独立会话。
"""
import threading
import traceback
from datetime import datetime, timedelta

from .. import config
from ..db import SessionLocal
from ..models import Schedule

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
            if now < next_at:
                continue
            task.last_status = "running"
            db.commit()
            threading.Thread(target=_execute, args=(task.id,), daemon=True).start()
    finally:
        db.close()


def _execute(schedule_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.get(Schedule, schedule_id)
        if not task:
            return
        ok, detail = run_task(task.tenant_id, task.kind, task.workflow_key)
        task.last_run_at = datetime.utcnow()
        task.run_count += 1
        task.last_status = "success" if ok else "failed"
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


def run_task(tenant_id: int, kind: str, workflow_key: str) -> tuple[bool, str]:
    """执行一次任务体：workflow 跑工作流模板；trend_scan 扫趋势；alert_scan 主动巡检。"""
    if kind == "workflow":
        from ..workflows.engine import start_run

        run = start_run(tenant_id, workflow_key, {"trigger": "schedule"})
        return run["status"] == "success", f"run#{run['id']}"
    if kind == "trend_scan":
        from ..agents.discovery import DiscoveryAgent

        with DiscoveryAgent(tenant_id) as a:
            trends = a.scan_trends()
        return True, f"{len(trends)} trends"
    if kind == "alert_scan":
        from ..db import SessionLocal
        from ..services import alerting

        db = SessionLocal()
        try:
            result = alerting.scan(db, tenant_id)
        finally:
            db.close()
        return True, f"{result['created']} alerts (skipped {result['skipped']})"
    return False, f"未知任务类型 {kind}"
