"""Launch 就绪度持久化：固定定义、CAS、步骤和事件同一事务；不调用旧 Worker。"""

from sqlalchemy import update

from ..models import WorkflowRun, WorkflowStep
from . import launch_state
from .kinds import PLATFORM_LAUNCH
from .launch_access import LaunchError, launch_context, owned_launch
from .launch_facts import load_launch_facts
from .launch_rules import STEP_STATES, evaluate_readiness
from .profile_schema import ProfileDefinition
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
    definition, steps = _definition_and_steps(db, run)
    facts, predicates = load_launch_facts(db, run)
    plan = evaluate_readiness(definition.model_dump(), {step.step_code: step.step_status for step in steps},
                              facts, predicates, activated=run.platform_status in {"ACTIVE", "PAUSED", "OFFLINE"}
                              and run.completed_at is not None)
    before = _snapshot(run, steps)
    changes = _changes(run, steps, plan)
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


def _definition_and_steps(db, run):
    try:
        definition = ProfileDefinition.model_validate(run.definition_snapshot)
        if definition.fingerprint() != run.definition_hash or definition.version != run.workflow_version:
            raise ValueError("实例定义摘要或版本不一致")
        if definition.environment != run.environment or definition.platform != run.platform:
            raise ValueError("实例环境或平台不一致")
        steps = db.query(WorkflowStep).filter_by(run_id=run.id).populate_existing().all()
        definitions = {step.step_code: step.model_dump() for step in definition.steps}
        if len(steps) != len(definitions) or {step.step_code for step in steps} != set(definitions):
            raise ValueError("实例步骤集合不一致")
        for step in steps:
            expected = definitions[step.step_code]
            if (step.tenant_id != run.tenant_id or step.params != expected or step.step_status not in STEP_STATES
                    or any(getattr(step, field) != expected[field] for field in
                           ("business_type", "execution_mode", "actor", "required"))):
                raise ValueError("实例步骤归属或固定参数不一致")
        return definition, steps
    except ValueError as exc:
        raise LaunchError("LAUNCH_DEFINITION_CORRUPT", "流程定义或步骤完整性校验失败", 409) from exc


def _snapshot(run, steps):
    """委托 launch_state.state_snapshot（T01 迁出共享内核，行为不变）。"""
    return launch_state.state_snapshot(run, steps)


def _changes(run, steps, plan):
    """委托 launch_state.plan_changes：纯计算 diff，含 completed_at 与回执投影入口。"""
    return launch_state.plan_changes(run, steps, plan)


def _record_event(db, ctx, run, before, after, changes):
    # 一次 CAS 对应一个递增 sequence；所有步骤差异都保存在不可变事件主体。
    launch_state.append_event(db, run, event_type="LaunchReadinessChanged",
                              idempotency_key=f"launch:{run.id}:revision:{run.revision}", source="SYSTEM",
                              actor_id=ctx.user_id, before=before, after=after,
                              payload={"changed_steps": list(changes["steps"]),
                                       "definition_hash": run.definition_hash})
