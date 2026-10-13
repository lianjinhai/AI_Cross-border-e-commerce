"""Launch 提交与在售核验 handler（B01 接通集）：复用 action_system 审批队列与 Attempt 回执。

按设计 D1 二分，所有触碰 AiAction/PlatformPublishAttempt 的领域逻辑集中在本文件：
预检失败零状态变更、不建 Action（AC-6.1）；scope_key 带提交序号后缀，终态提案不被
复用而死锁（设计 R4）；核验双权限与核验人独立性在本处强制（AC-7.1）。
"""

from ..models import AiAction, WorkflowStep, utcnow
from ..services.action_publish import publish_facts
from ..services.action_system import submit_action
from ..services.ai_actions import ActionError
from .launch_access import LaunchError
from .launch_action_catalog import ActionContext, StepEffect

# 提交/核验 handler 注册表；由 launch_actions 与 launch_handlers.HANDLERS 合并。
SUBMIT_HANDLERS = {"SUBMIT_PLATFORM": None, "CONFIRM_ACTIVATION": None}


def submit_platform(ctx: ActionContext) -> StepEffect:
    """预检 publish_facts → 创建/复用 PUBLISH_LISTING 提案（commit=False）→ 断言 WAITING_APPROVAL。

    回执 {action_id, approval_required, status}；步骤证据固定 {action_id, submission_seq,
    facts{fingerprint, rule_version}}（AC-6.2）。审批/执行完全复用既有 Action 队列。
    """
    run, step = ctx.run, ctx.step
    try:
        facts = publish_facts(ctx.db, run.tenant_id, run.listing_id, run.shop_id)
    except ActionError as exc:
        raise LaunchError("ACTION_PRECONDITION_FAILED", str(exc), 409,
                          blockers=_blockers(exc, step)) from exc
    sequence = _submission_sequence(ctx)
    proposal = {"action_type": "PUBLISH_LISTING", "target_type": "listing",
                "target_id": run.listing_id, "payload": {"shop_id": run.shop_id},
                "reason": "上线流程提交平台：%s" % step.step_code}
    try:
        action = submit_action(ctx.db, ctx.current, "listing", proposal,
                               "launch:%s:%s:%s" % (run.id, step.step_code, sequence),
                               commit=False,
                               extra_evidence={"launch_id": run.id, "step_code": step.step_code})
    except ActionError as exc:
        raise LaunchError("ACTION_PRECONDITION_FAILED", str(exc), 409,
                          blockers=_blockers(exc, step)) from exc
    return StepEffect(status="WAITING_APPROVAL",
                      result={"action_id": action.id, "submission_seq": sequence,
                              "facts": {"fingerprint": facts["fingerprint"],
                                        "rule_version": facts["rule_version"]}},
                      receipt={"action_id": action.id, "approval_required": True,
                               "status": "PENDING_APPROVAL"})


def confirm_activation(ctx: ActionContext) -> StepEffect:
    """在售核验：双权限 + 核验人独立（AC-7.1）、材料引用与备注必填（AC-7.2）、
    核验记录入步骤证据与事件（AC-7.3/7.5），断言 COMPLETED 并置 ACTIVE/VERIFIED。

    绝不调用平台适配器：source=MANUAL 只证明人工已核对材料，不冒充 API 核验（AC-6.4）。
    """
    step = ctx.step
    material_ref = (ctx.payload.get("material_ref") or "").strip()
    note = (ctx.payload.get("note") or "").strip()
    if not material_ref or not note:
        raise LaunchError("ACTION_PRECONDITION_FAILED",
                          "在售核验必须提供材料引用与备注（来源/时间/外部对象）", 409)
    _reject_self_verification(ctx)
    result = step.result or {}
    previous = (result.get("activation_verification") or {}).get("current")
    record = {"reviewer_id": ctx.current.user_id, "material_ref": material_ref,
              "note": note, "reviewed_at": utcnow().isoformat(), "source": "MANUAL",
              "correction_of": previous.get("reviewed_at") if previous else None}
    history = list((result.get("activation_verification") or {}).get("history") or [])
    if previous:
        history.append(previous)  # 误判更正不擦除历史（AC-7.5）。
    return StepEffect(status="COMPLETED",
                      result={"activation_verification": {"current": record, "history": history}},
                      evidence_refs=["verification:MANUAL"],
                      run_fields={"platform_status": "ACTIVE", "verification_status": "VERIFIED"},
                      receipt={"verification": record, "platform_status": "ACTIVE",
                               "verification_status": "VERIFIED", "corrected": bool(previous)})


def _submission_sequence(ctx):
    """提交序号（设计 D4/R4）：该步骤已有 Launch 关联 Action 数 + 1。

    序号后缀使 _scope_action 永不命中终态（REJECTED/FAILED）提案；非终态复用由
    action_system._existing_intent 按指纹完成（AC-6.2/8.1）。
    """
    rows = ctx.db.query(AiAction.id).filter(
        AiAction.tenant_id == ctx.run.tenant_id, AiAction.workspace_id == ctx.run.workspace_id,
        AiAction.evidence["launch_id"].as_integer() == ctx.run.id,
        AiAction.evidence["step_code"].as_string() == ctx.step.step_code).count()
    return int(rows) + 1


def _reject_self_verification(ctx):
    """核验人必须与提交人/执行人不同（AC-7.1）：读提交提案的 requested_by/executed_by。"""
    submission = ctx.db.query(WorkflowStep).filter_by(
        run_id=ctx.run.id, business_type="PLATFORM_SUBMISSION").first()
    action = None
    if submission is not None:
        action_id = (submission.result or {}).get("action_id")
        action = ctx.db.get(AiAction, action_id) if type(action_id) is int else None
    if action is None:
        raise LaunchError("ACTION_PRECONDITION_FAILED", "尚未提交平台，不能核验在售", 409)
    involved = {value for value in (action.requested_by, action.executed_by) if value is not None}
    if ctx.current.user_id in involved:
        raise LaunchError("ACTION_PRECONDITION_FAILED",
                          "在售核验不能由提交人或执行人本人完成", 409)


def _blockers(exc, step):
    """领域失败转 409 时附具体缺项（AC-6.1/6.6）：消息入 blockers 供前端展示。"""
    return [{"code": "ACTION_PRECONDITION_FAILED", "message": str(exc)[:500],
             "step_code": step.step_code, "owner_actor": step.actor,
             "evidence_refs": [], "repair_action": None}]


SUBMIT_HANDLERS.update({"SUBMIT_PLATFORM": submit_platform, "CONFIRM_ACTIVATION": confirm_activation})
