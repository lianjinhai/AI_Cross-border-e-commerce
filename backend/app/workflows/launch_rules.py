"""确定性 DAG 就绪度；只计算状态，不执行动作、不接收客户端完成指令。"""

from copy import deepcopy

from .conditions import evaluate_condition
from .launch_repair import repair_action
from .profile_schema import ProfileDefinition

STEP_STATES = frozenset({"PENDING", "READY", "RUNNING", "WAITING_EXTERNAL", "WAITING_USER",
                         "WAITING_APPROVAL", "COMPLETED", "BLOCKED", "FAILED", "SKIPPED"})
WAITING = frozenset({"RUNNING", "WAITING_EXTERNAL", "WAITING_USER", "WAITING_APPROVAL", "FAILED"})
BLOCK_CODES = {"COMPLIANCE": "COMPLIANCE_BLOCK", "LABEL": "COMPLIANCE_BLOCK",
               "EVIDENCE": "COMPLIANCE_BLOCK", "STOCK_PREPARATION": "STOCK_REQUIRED",
               "PRICE_REVIEW": "PRICE_UNACCEPTABLE", "HUMAN_DECISION": "USER_ACTION_REQUIRED"}


def evaluate_readiness(snapshot, states, facts, predicates, *, activated=False, cancelled=False):
    """只接受服务端事实。完成需专用 handler；此函数绝不自动写 COMPLETED。"""
    definition = ProfileDefinition.model_validate(snapshot)
    nodes = {step.step_code: step for step in definition.steps}
    if set(states) != set(nodes) or any(state not in STEP_STATES for state in states.values()):
        raise ValueError("实例步骤与固定定义不一致或状态未知")
    results, checks = {}, deepcopy(predicates)
    checks["dependency_completed"] = {}
    for code in _topological(nodes):
        step = nodes[code]
        deps = all(results[dep]["status"] in {"COMPLETED", "SKIPPED"} for dep in step.dependencies)
        applicable = evaluate_condition(step.applicability_condition, facts, checks)
        entered = evaluate_condition(step.entry_condition, facts, checks)
        complete = evaluate_condition(step.completion_condition, facts, checks)
        # 状态模型 §3：WAITING_EXTERNAL 的出口是「可信新外部事实到达」。
        # 只对 PLATFORM_ACTIVATION 求值：它是唯一有真实外部事实源（platform.status）
        # 且 handler 已接通的 EXTERNAL_WAIT 类型；其余（如 PRICE_REVIEW）属 B03-B09
        # 未接通，保持 READY + 禁用按钮 + 明确 disabled_reason，不伪装成「在等外部」。
        external_arrived = _external_arrived(step, facts, checks)
        status, reason = _status(step, states[code], applicable, deps, entered, complete,
                                 activated, cancelled, external_arrived)
        results[code] = {"step_code": code, "status": status, "applicable": applicable,
                         "completion_satisfied": complete, "blocking_reason": _blocker(step, reason, facts) if reason else {},
                         "invalidated": states[code] == "COMPLETED" and status != "COMPLETED"}
        checks["dependency_completed"][code] = status == "COMPLETED"
    return _summary(definition, results, activated, cancelled)


def _external_arrived(step, facts, checks):
    """平台是否已给出可信接受事实（ACCEPTED/ACTIVE）；非在售核验类步骤返回 None。"""
    if step.business_type != "PLATFORM_ACTIVATION":
        return None
    return evaluate_condition({"in": {"field": "platform.status", "value": ["ACCEPTED", "ACTIVE"]}},
                              facts, checks)



def _topological(nodes):
    ordered, visited = [], set()

    def visit(code):
        if code in visited:
            return
        for dependency in nodes[code].dependencies:
            visit(dependency)
        visited.add(code)
        ordered.append(code)

    for step in sorted(nodes.values(), key=lambda item: (item.sequence, item.step_code)):
        visit(step.step_code)
    return ordered


def _status(step, old, applicable, dependencies, entered, complete, activated, cancelled,
            external_arrived=None):
    if cancelled:
        return old, ""
    if activated and old == "COMPLETED":
        # 上线后的失效只产生整改阻断，不擦除历史完成、也不伪造平台下架。
        return old, "上线后证据需重新核查" if applicable is not True or entered is not True or complete is not True else ""
    if old == "COMPLETED":
        if applicable is True and dependencies and entered is True and complete is True:
            return old, ""
        return "BLOCKED", "已完成步骤的依据已失效，需要重新确认"
    if applicable is None:
        return "BLOCKED", "缺少适用性判断资料，不能跳过"
    if applicable is False:
        if old in WAITING:
            return "BLOCKED", "适用条件已变化，先核查在途任务结果"
        return "SKIPPED", ""
    if not dependencies:
        return ("BLOCKED", "上游依据已失效，需先核查在途任务") if old in WAITING else ("PENDING", "")
    if entered is not True:
        return "BLOCKED", "缺少进入条件资料" if entered is None else "进入条件未满足"
    if old in WAITING:
        # 状态模型 §3 的唯一出口：可信新外部事实到达才回到 READY（外部意图已发出，
        # 但没有平台接受事实时就该一直等，不能把等待步骤放进可执行列表）。
        if old == "WAITING_EXTERNAL" and external_arrived is True:
            return "READY", ""
        return old, ""
    if external_arrived is not True and _awaits_external(step):
        # 无平台事实（None）或事实不满足（False，如 UNDER_REVIEW）都仍需等待；
        # 只有 True（ACCEPTED/ACTIVE）才放行到 READY。
        return "WAITING_EXTERNAL", ""
    return "READY", ""


def _awaits_external(step):
    """在售核验类步骤在依赖满足后就开始等平台接受，而不是直接给用户一个「核验」按钮。"""
    return step.business_type == "PLATFORM_ACTIVATION" and step.execution_mode == "EXTERNAL_WAIT"



def _blocker(step, message, facts=None):
    """阻断项三要素：阻断码 + 原因 + 补齐动作（P0-4）。"""
    code = BLOCK_CODES.get(step.business_type, "MISSING_DATA")
    facts = facts if isinstance(facts, dict) else {}
    product = facts.get("product") or {}
    return {"code": code, "message": _message(step, code, message, facts),
            "step_code": step.step_code, "owner_actor": step.actor, "evidence_refs": [],
            "repair_action": repair_action(code, business_type=step.business_type,
                                           product_id=product.get("id"))}


def _message(step, code, message, facts):
    """把通用原因细化成说人话的具体原因；无法细化时保留原样，不编造细节。"""
    if code == "PRICE_UNACCEPTABLE":
        pricing = facts.get("pricing") or {}
        margin, floor = pricing.get("margin"), pricing.get("min_margin")
        # 只有确实低于门槛时才改写成「毛利 X% 低于 Y%」；否则（如成本快照失效导致的重阻断）
        # 保留原原因，避免出现「毛利 89.5% 低于最低要求 15.0%」这种自相矛盾的文案。
        if (isinstance(margin, (int, float)) and isinstance(floor, (int, float))
                and margin < floor):
            return f"售价毛利 {margin:.1%} 低于最低要求 {floor:.1%}，不能进入核价"
    if code == "COMPLIANCE_BLOCK" and step.business_type == "LABEL":
        return "标签包缺少可用依据（LABEL_PACKAGE 未核验或已失效）" if message else message
    return message


def _summary(definition, results, activated, cancelled):
    ordered = sorted(definition.steps, key=lambda step: (step.sequence, step.step_code))
    required = [step for step in ordered if step.required and step.business_type != "MONITORING"
                and results[step.step_code]["applicable"] is not False]
    if not required:
        raise ValueError("流程必需上线步骤不能为空")
    completed = sum(results[step.step_code]["status"] == "COMPLETED" for step in required)
    blockers = [results[step.step_code]["blocking_reason"] for step in ordered
                if results[step.step_code]["blocking_reason"]]
    blocking = any(results[step.step_code]["blocking_reason"] for step in ordered if step.required or step.blocking)
    # 经营监控及非阻断可选任务的失败不应抹掉已完成的上线里程碑。
    statuses = {results[step.step_code]["status"] for step in ordered
                if (step.required or step.blocking) and step.business_type != "MONITORING"}
    status = _run_status(statuses, blocking, completed == len(required), activated, cancelled)
    current = [step.step_code for step in ordered if results[step.step_code]["status"]
               in {"READY", "RUNNING", "BLOCKED", "WAITING_USER", "WAITING_EXTERNAL", "WAITING_APPROVAL"}]
    return {"execution_status": status, "steps": results, "blockers": blockers,
            "current_steps": current, "current_step": current[0] if current else "",
            "progress": {"completed": completed, "total": len(required)},
            "runnable_steps": [step.step_code for step in ordered if results[step.step_code]["status"] == "READY"]}


def _run_status(states, blocked, all_completed, activated, cancelled):
    if cancelled:
        return "CANCELLED"
    if "FAILED" in states:
        return "FAILED"
    if all_completed and (not blocked or activated):
        return "COMPLETED"
    if blocked:
        return "BLOCKED"
    for state in ("RUNNING", "READY", "WAITING_APPROVAL", "WAITING_USER", "WAITING_EXTERNAL"):
        if state in states:
            return state
    return "NOT_STARTED"
