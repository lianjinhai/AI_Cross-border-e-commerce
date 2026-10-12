"""Launch 就绪度持久化：固定定义、CAS、步骤和事件同一事务；不调用旧 Worker。"""

from copy import deepcopy

from sqlalchemy import update

from ..models import WorkflowEvent, WorkflowRun, WorkflowStep, utcnow
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
    return {"revision": run.revision, "execution_status": run.execution_status,
            "platform_status": run.platform_status, "verification_status": run.verification_status,
            "current_step": run.current_step, "blocked_reason": deepcopy(run.blocked_reason),
            "steps": {step.step_code: {"status": step.step_status, "blocking_reason": deepcopy(step.blocking_reason),
                                       "input_revision": step.input_revision} for step in steps}}


def _changes(run, steps, plan):
    values = {"execution_status": plan["execution_status"], "current_step": plan["current_step"],
              "blocked_reason": {"items": plan["blockers"]} if plan["blockers"] else {}}
    changed = {name: value for name, value in values.items() if getattr(run, name) != value}
    step_changes = {}
    for step in steps:
        target = plan["steps"][step.step_code]
        updates = {name: value for name, value in {"step_status": target["status"],
                   "blocking_reason": target["blocking_reason"]}.items() if getattr(step, name) != value}
        if target["invalidated"]:
            updates["input_revision"] = step.input_revision + 1
        if updates:
            step_changes[step.step_code] = updates
    if (changed or step_changes) and run.started_at is None:
        changed["started_at"] = utcnow()
    return {"run": changed, "steps": step_changes}


def _record_event(db, ctx, run, before, after, changes):
    # 一次 CAS 对应一个递增 sequence；所有步骤差异都保存在不可变事件主体。
    db.add(WorkflowEvent(tenant_id=run.tenant_id, workspace_id=run.workspace_id, run_id=run.id,
                         actor_id=ctx.user_id, sequence=run.revision, event_type="LaunchReadinessChanged",
                         idempotency_key=f"launch:{run.id}:revision:{run.revision}", source="SYSTEM",
                         before=before, after=after, profile_version=run.workflow_version,
                         payload={"changed_steps": list(changes["steps"]), "definition_hash": run.definition_hash}))
