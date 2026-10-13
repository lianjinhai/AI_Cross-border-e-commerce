"""Launch 进程级恢复（AC-8.5 / 设计 D12）：重启时以系统身份回收未结束流程的 RUNNING 步骤。

与 ``launch_runtime.refresh_launch`` 的差异：本模块**无用户 ctx**、按确定性冻结规则回收
状态、**不调用任何外部适配器**、不做平台 read-back。零迁移：只写既有列
（``WorkflowStep.step_status``/``result``、``WorkflowRun.revision``、``WorkflowEvent``）。

事件与快照复用 ``launch_state`` 内核（``append_event``/``state_snapshot``），避免第二套
实现；但逐步骤事件（``LaunchRecovered`` vs 单条 ``LaunchReadinessChanged``）语义不同，
故未强抽 ``refresh_launch`` 的 CAS 落库段（抽取会把两套事件语义硬塞进一个布尔参数）。
"""

from sqlalchemy import update

from ..models import WorkflowRun, WorkflowStep
from . import launch_state
from .kinds import PLATFORM_LAUNCH
from .launch_plan import recover_running_steps
from .transactions import ensure_write_transaction

# 事件 payload 的 reason（设计 D12 事件表：reason, pending_verification?）。
READY_REASON = "no_persistent_intent"
PENDING_REASON = "outcome_pending_verification"


def recover_launch_steps(db) -> int:
    """启动扫描（系统身份，无用户 ctx）：回收全部未结束 PLATFORM_LAUNCH 的 RUNNING 步骤。

    规则（设计 D12/AC-8.5，只读判定后统一落库）：

    - ``RUNNING`` 且**无持久外部意图** → 回退 ``READY``（进程在产生副作用前中断）；
    - ``RUNNING`` 且**有持久外部意图** → 保持 ``RUNNING`` 并首次标注 ``result.pending_verification``
      （「结果待核查」），不重发；
    - 每个被回收的步骤写一条 ``LaunchRecovered`` 事件（``source=SYSTEM``、``actor_id=None``），
      ``idempotency_key = launch:{run_id}:recovery:{step_code}:{revision}``，与 revision 同步。

    返回被处理（回退或标注）的步骤数。**幂等**：二次调用在无待回收迁移时零写入
    （不产生事件、不递增 revision）。调用方拥有会话生命周期，本函数提交成功扫描。
    """
    candidates = []
    for run in _unfinished_runs(db):
        steps = _run_steps(db, run)
        migrations, reasons = _recover_migrations(db, run, steps)
        if migrations:
            candidates.append((run, steps, migrations, reasons))
    if not candidates:
        return 0
    ensure_write_transaction(db)
    processed = 0
    for run, steps, migrations, reasons in candidates:
        processed += _persist_recovery(db, run, steps, migrations, reasons)
    db.commit()
    return processed


def _unfinished_runs(db) -> list[WorkflowRun]:
    """未结束（未 CANCELLED 且 ended_at 为空）的平台上线流程，按 id 稳定排序。"""
    return db.query(WorkflowRun).filter(
        WorkflowRun.flow_kind == PLATFORM_LAUNCH,
        WorkflowRun.ended_at.is_(None),
        WorkflowRun.execution_status != "CANCELLED",
    ).order_by(WorkflowRun.id).all()


def _run_steps(db, run) -> list[WorkflowStep]:
    return db.query(WorkflowStep).filter(WorkflowStep.run_id == run.id).populate_existing().all()


def _recover_migrations(db, run, steps) -> tuple[dict[str, dict], dict[str, str]]:
    """计算回收迁移：返回 (migrations, reasons)。

    ``migrations`` 为纯步骤字段迁移（可直接 setattr）；``reasons[code]`` 为事件原因。
    复用 ``launch_plan.recover_running_steps`` 的只读判定，保证「同一事实同一迁移」。
    """
    recovered = recover_running_steps(db, run, steps)
    migrations = {code: dict(migration) for code, migration in recovered.items()}
    reasons = {code: READY_REASON for code in recovered}
    for step in steps:
        if step.step_status != "RUNNING" or step.step_code in migrations:
            continue
        if (step.result or {}).get("pending_verification") is True:
            continue  # 已标注：二次启动不重复处理（幂等）。
        migrations[step.step_code] = {
            "result": {**(step.result or {}), "pending_verification": True}}
        reasons[step.step_code] = PENDING_REASON
    return migrations, reasons


def _persist_recovery(db, run, steps, migrations, reasons) -> int:
    """CAS 落库：revision+1、应用步骤迁移、逐步骤写 LaunchRecovered 事件。

    返回被处理的步骤数；revision 冲突（并发改动）时放弃该 run（零状态变更、零事件）。
    """
    expected = run.revision
    before = launch_state.state_snapshot(run, steps)
    result = db.execute(update(WorkflowRun).where(
        WorkflowRun.id == run.id, WorkflowRun.tenant_id == run.tenant_id,
        WorkflowRun.flow_kind == PLATFORM_LAUNCH, WorkflowRun.revision == expected,
    ).values(revision=expected + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        return 0
    for step in steps:
        for name, value in migrations.get(step.step_code, {}).items():
            setattr(step, name, value)
    db.flush()
    db.refresh(run)
    after = launch_state.state_snapshot(run, steps)
    for code in sorted(migrations):
        launch_state.append_event(
            db, run, event_type="LaunchRecovered",
            idempotency_key=f"launch:{run.id}:recovery:{code}:{run.revision}",
            source="SYSTEM", actor_id=None, before=before, after=after,
            payload=_recovered_payload(reasons[code]))
    db.flush()
    return len(migrations)


def _recovered_payload(reason: str) -> dict:
    """LaunchRecovered 事件 payload（设计 D12 事件表列）。"""
    payload = {"reason": reason}
    if reason == PENDING_REASON:
        payload["pending_verification"] = True
    return payload
