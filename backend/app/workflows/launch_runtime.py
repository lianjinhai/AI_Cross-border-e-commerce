"""Launch 就绪度持久化：固定定义、CAS、步骤和事件同一事务；不调用旧 Worker。"""

from sqlalchemy import update

from ..models import WorkflowRun
from . import launch_state
from .kinds import PLATFORM_LAUNCH
from .launch_access import LaunchError, launch_context, owned_launch
from .launch_plan import activated_flag, launch_plan
from .transactions import ensure_write_transaction


def refresh_launch(db, ctx, run_id, expected_revision):
    """重新计算可运行节点；不隐式接受报价、通过合规或宣告在售。调用方提交。"""
    if type(expected_revision) is not int or expected_revision < 1:
        raise LaunchError("REVISION_REQUIRED", "需要有效的流程版本号")
    ensure_write_transaction(db)
    current, scope = launch_context(db, ctx, "launch:manage")
    run = owned_launch(db, current, scope, run_id)
    if run.revision != expected_revision:
        raise LaunchError("REVISION_CONFLICT", "流程已更新，请刷新后重试", 409)
    if run.ended_at is not None or run.execution_status == "CANCELLED":
        raise LaunchError("LAUNCH_ENDED", "已结束的流程不能重新推进", 409)
    definition, steps, facts, predicates, plan = launch_plan(db, run)
    # 刷新前收敛（设计 D4/D10）：AiAction 状态投影 + 回执落地，只读判定后统一落库。
    plan, converged = launch_state.converge(db, run, steps, plan, facts, predicates, definition,
                                            activated=activated_flag(run))
    before = _snapshot(run, steps)
    changes = _changes(run, steps, plan, overrides=converged)
    if not changes["run"] and not changes["steps"]:
        return run, plan
    with db.begin_nested():
        result = db.execute(update(WorkflowRun).where(
            WorkflowRun.id == run.id, WorkflowRun.tenant_id == current.legacy_tenant_id,
            WorkflowRun.flow_kind == PLATFORM_LAUNCH, WorkflowRun.revision == expected_revision,
        ).values(revision=expected_revision + 1, **changes["run"]).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise LaunchError("REVISION_CONFLICT", "流程已更新，请刷新后重试", 409)
        for step in steps:
            for name, value in changes["steps"].get(step.step_code, {}).items():
                setattr(step, name, value)
        db.flush()
        db.refresh(run)
        _record_event(db, current, run, before, _snapshot(run, steps), changes)
        db.flush()
    return run, plan


def _snapshot(run, steps):
    """委托 launch_state.state_snapshot（T01 迁出共享内核，行为不变）。"""
    return launch_state.state_snapshot(run, steps)


def _changes(run, steps, plan, *, overrides=None):
    """委托 launch_state.plan_changes：纯计算 diff，含 completed_at 与回执投影入口。"""
    return launch_state.plan_changes(run, steps, plan, overrides=overrides)


def _record_event(db, ctx, run, before, after, changes):
    # 一次 CAS 对应一个递增 sequence；所有步骤差异都保存在不可变事件主体。
    launch_state.append_event(db, run, event_type="LaunchReadinessChanged",
                              idempotency_key=f"launch:{run.id}:revision:{run.revision}", source="SYSTEM",
                              actor_id=ctx.user_id, before=before, after=after,
                              payload={"changed_steps": list(changes["steps"]),
                                       "definition_hash": run.definition_hash})
