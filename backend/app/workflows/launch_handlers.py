"""Launch 业务处理器（B01 接通集）：资料完成、重试、取消；注册表供执行框架查找。

handler 只做领域前置校验并返回 StepEffect 断言（设计 D10），不自行提交事务、
不直接写库；落库、收敛与事件由 launch_actions 统一编排。触碰 AiAction/Attempt 的
提交/核验 handler 按设计 D1 二分集中在 launch_submit。
"""

from ..models import AiAction, PlatformPublishAttempt, utcnow
from .launch_access import LaunchError
from .launch_action_catalog import ActionContext, StepEffect
from .launch_state import facts_digest
from .launch_status import is_verified_online

# 基础 handler 注册表（文件末尾填充）；launch_submit.SUBMIT_HANDLERS 由
# launch_actions 合并进完整目录，避免 launch_handlers 前向引用提交/核验 handler。
HANDLERS: dict = {}


def complete_data(ctx: ActionContext) -> StepEffect:
    """商品资料完成：条件已由 NBA 门禁确定满足；固定证据并断言 COMPLETED。

    证据四要素固定为 {input_revision, facts_digest, completed_by, completed_at}（AC-5.1）；
    条件不满足时 409 且 blockers 复用 asset_rights.reasons（AC-5.2），步骤保持 READY。
    """
    step = ctx.step
    target = (ctx.plan.get("steps") or {}).get(step.step_code) or {}
    if target.get("completion_satisfied") is not True:
        raise LaunchError("ACTION_PRECONDITION_FAILED", "完成条件尚未被服务端事实满足", 409,
                          blockers=missing_blockers(ctx.facts, step))
    digest = facts_digest(ctx.facts, ctx.predicates)
    evidence = {"input_revision": step.input_revision, "facts_digest": digest,
                "completed_by": ctx.current.user_id, "completed_at": utcnow().isoformat()}
    return StepEffect(status="COMPLETED", result=evidence,
                      evidence_refs=["facts:%s" % digest[:16]],
                      receipt={"step_code": step.step_code, "step_status": "COMPLETED",
                               "evidence_digest": digest, "evidence": evidence})


def retry_step(ctx: ActionContext) -> StepEffect:
    """FAILED → READY（经规则重算）：attempts+1，事件记 predecessor（AC-8.1）。

    外部结果待核查（Attempt uncertain 或 AiAction EXECUTING）时禁止重发（AC-8.2）。
    """
    step = ctx.step
    _reject_pending_external(ctx)
    predecessor = {"previous_status": step.step_status}
    action_id = (step.result or {}).get("action_id")
    action = ctx.db.get(AiAction, action_id) if type(action_id) is int else None
    if action is not None:
        predecessor["action_id"] = action.id
        predecessor["action_status"] = action.status
    return StepEffect(status="READY", attempts_delta=1,
                      result={"retried_at": utcnow().isoformat()},
                      receipt={"step_code": step.step_code, "step_status": "READY",
                               "predecessor": predecessor, "attempts": step.attempts + 1})


def cancel_run(ctx: ActionContext) -> StepEffect:
    """CANCEL/ABANDON_PRODUCT 同语义终止本轮（AC-8.3/8.6）：纯本地终态 + 事件，
    不调用任何外部下架/退款；已核验在售或已完成流程一律 409（AC-7.6/8.4）。
    """
    run = ctx.run
    if run.ended_at is not None or run.execution_status == "CANCELLED":
        raise LaunchError("LAUNCH_ENDED", "已结束的流程不能重复取消", 409)
    if is_verified_online(run):
        raise LaunchError("ACTION_PRECONDITION_FAILED", "已核验在售的流程不能取消", 409)
    if run.execution_status == "COMPLETED":
        raise LaunchError("ACTION_PRECONDITION_FAILED", "已完成的流程不能取消", 409)
    now = utcnow()
    return StepEffect(cancelled=True, run_fields={"ended_at": now, "active_slot": None},
                      receipt={"ended_at": now.isoformat(), "active_slot_released": True,
                               "note": ctx.payload.get("note", "")})


def missing_blockers(facts, step):
    """把素材权利等具体缺项转成 blockers（AC-5.2：前端可逐条展示）。"""
    reasons = (facts.get("assets") or {}).get("reasons") or ["完成条件尚未满足"]
    return [{"code": "MISSING_DATA", "message": reason, "step_code": step.step_code,
             "owner_actor": step.actor, "evidence_refs": [], "repair_action": None}
            for reason in reasons]


def _reject_pending_external(ctx):
    """外部结果待核查时不重发（AC-8.2）：Attempt uncertain 或 AiAction EXECUTING。"""
    step = ctx.step
    if step.business_type != "PLATFORM_SUBMISSION":
        return
    attempt = ctx.db.query(PlatformPublishAttempt).filter_by(
        tenant_id=ctx.run.tenant_id, listing_id=ctx.run.listing_id,
        shop_id=ctx.run.shop_id, platform=ctx.run.platform).first()
    if attempt is not None and attempt.status == "uncertain":
        raise LaunchError("ACTION_PRECONDITION_FAILED", "外部结果待核查，请先同步核对", 409)
    action_id = (step.result or {}).get("action_id")
    action = ctx.db.get(AiAction, action_id) if type(action_id) is int else None
    if action is not None and action.status == "EXECUTING":
        raise LaunchError("ACTION_PRECONDITION_FAILED", "外部结果待核查，请先同步核对", 409)


HANDLERS.update({"COMPLETE_DATA": complete_data, "RETRY": retry_step,
                 "CANCEL": cancel_run, "ABANDON_PRODUCT": cancel_run})
