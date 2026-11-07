"""Launch 只读计算段：定义/步骤完整性校验 + 服务端事实 + 确定性就绪度（零写库）。

执行框架（launch_actions）与刷新（launch_runtime）共用本模块，保证「同一实例 ->
同一计划」只有一份计算实现（设计 D10）。本函数不写库、不改 revision、不产生事件；
所有拒绝均为前置 LaunchError。
"""

from ..models import AiAction, WorkflowStep
from .launch_access import LaunchError
from .launch_facts import load_launch_facts
from .launch_rules import STEP_STATES, evaluate_readiness, revoked_codes
from .launch_status import is_activated
from .profile_schema import ProfileDefinition

# 有持久意图的 AiAction 状态：RUNNING 步骤只要命中其一即视为「在途」，恢复时只重读不重发。
_LIVE_INTENT_STATES = ("PENDING_APPROVAL", "APPROVED", "EXECUTING", "SUCCESS")


def launch_plan(db, run):
    """只读计算段；返回 (definition, steps, facts, predicates, plan)。

    抛 LaunchError: LAUNCH_DEFINITION_CORRUPT(409)（自 launch_runtime._definition_and_steps
    迁出，行为不变）/ LAUNCH_TARGET_INVALID(409) / LAUNCH_CONTEXT_CHANGED(409)
    （后两者由 load_launch_facts 抛出）。
    """
    definition, steps = definition_and_steps(db, run)
    facts, predicates = load_launch_facts(db, run)
    plan = evaluate_readiness(
        definition.model_dump(), {step.step_code: step.step_status for step in steps},
        facts, predicates, activated=activated_flag(run), revoked=revoked_codes(steps))
    return definition, steps, facts, predicates, plan


def activated_flag(run):
    """上线后失效分支开关（既有 refresh_launch 语义）：在售三态且已完成才激活整改阻断。"""
    return is_activated(run.platform_status, run.completed_at)


def recover_running_steps(db, run, steps) -> dict[str, dict]:
    """进程级恢复扫描（AC-8.5，只读判定）：无关联意图的 RUNNING 步骤回退 READY。

    规则对 RUNNING 是粘滞的（设计 R1），进程重启后既不能凭旧状态冒充在途、也不能重发
    外部调用：命中 _LIVE_INTENT_STATES 的 AiAction 视为真实在途（只重读，由投影/回执落地
    推进）；没有任何意图的 RUNNING 说明进程在产生副作用前中断，安全回退 READY 待重新调度。
    """
    running = [step for step in steps if step.step_status == "RUNNING"]
    if not running:
        return {}
    rows = db.query(AiAction).filter(
        AiAction.tenant_id == run.tenant_id, AiAction.workspace_id == run.workspace_id,
        AiAction.evidence["launch_id"].as_integer() == run.id,
        AiAction.evidence["step_code"].as_string().in_([step.step_code for step in running]),
        AiAction.status.in_(_LIVE_INTENT_STATES)).all()
    live = {row.evidence.get("step_code") for row in rows}
    return {step.step_code: {"step_status": "READY"} for step in running if step.step_code not in live}


def definition_and_steps(db, run):
    """实例定义/步骤与冻结快照一致性校验（自 launch_runtime 迁出，语义不变）。"""
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
