"""Launch 动作执行框架：校验链、幂等重放、revision CAS、状态机守卫与事件编排。

框架不认识任何具体业务动作（设计 D1）：新增动作只改 launch_action_catalog 与
handlers/submit。handler 返回 StepEffect 断言，由本模块统一收敛落库并记事件——
一次事务一条动作事件（设计 D10）；高危动作失败绝不自动重发（AC-4.10）。
"""

from sqlalchemy import update

from ..models import WorkflowEvent, WorkflowRun, WorkflowStep
from ..services.ai_actions import ActionError
from ..services.pii_redact import redact
from . import launch_state
from .kinds import PLATFORM_LAUNCH
from .launch_access import LaunchError, launch_context, owned_launch
from .launch_action_catalog import (
    ActionContext,
    StepEffect,
    action_digest,
    action_event_key,
    action_meta,
    evidence_fingerprint,
    payload_hash,
    validate_payload,
)
from .launch_handlers import HANDLERS as BASE_HANDLERS
from .launch_handlers import missing_blockers
from .launch_plan import activated_flag, launch_plan
from .launch_submit import SUBMIT_HANDLERS
from .transactions import ensure_write_transaction

# 完整动作目录：基础 handler + 提交/核验 handler（设计 D1 四件套在框架外扩展）。
HANDLERS = {**BASE_HANDLERS, **SUBMIT_HANDLERS}

# 事件类型按动作映射（设计 §3.4）；未列出者落 LaunchActionExecuted。
_EVENT_TYPES = {"CONFIRM_ACTIVATION": "LaunchActivationVerified", "RETRY": "LaunchActionRetried",
                "CANCEL": "LaunchCancelled", "ABANDON_PRODUCT": "LaunchCancelled"}
_IDEMPOTENCY_LIMIT = 128
_RUN_ACTIONS = frozenset({"CANCEL", "ABANDON_PRODUCT"})


def execute_launch_action(db, ctx, run_id, action, body, idempotency_key):
    """执行 Launch 业务动作；返回 {revision, action, status, step, receipt, event_id, run, plan}。

    status ∈ EXECUTED | PENDING_APPROVAL（提交待审批）| FAILED（意外异常，HTTP 仍 200，
    设计 D11）。校验链按序且全部零状态变更；写路径在 begin_nested 保存点内，任一失败
    整体回滚。调用方负责提交外层事务。
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > _IDEMPOTENCY_LIMIT:
        raise LaunchError("IDEMPOTENCY_REQUIRED", "Idempotency-Key 请求头必填且不超过 128 字符", 400)
    if not isinstance(action, str) or not action.strip():
        raise LaunchError("ACTION_NOT_ALLOWED", "动作不能为空", 409)
    action = action.strip()
    ensure_write_transaction(db)
    current, scope = launch_context(db, ctx, "launch:read")
    run = owned_launch(db, current, scope, run_id)
    if not isinstance(body, dict):
        raise LaunchError("REVISION_REQUIRED", "请求体必须是对象", 400)
    step_code = body.get("step_code") or ""
    payload = body.get("payload")
    if payload is None:
        payload = {}
    # 3. 幂等重放：同键同载荷返回原回执（仍先复核权限）；异载荷 409，零状态变更。
    event_key = action_event_key(run.id, step_code, action, idempotency_key)
    load_hash = payload_hash(step_code, action, payload if isinstance(payload, dict) else {})
    replayed = _replay(db, run, current, action, event_key, load_hash)
    if replayed is not None:
        replayed["run"] = run
        replayed["plan"] = launch_plan(db, run)[4]
        return replayed
    # 4. expected_revision 类型与一致性（409 带 current_revision）。
    expected_revision = body.get("expected_revision")
    if type(expected_revision) is not int or expected_revision < 1:
        raise LaunchError("REVISION_REQUIRED", "需要有效的流程版本号", 400)
    if run.revision != expected_revision:
        raise LaunchError("REVISION_CONFLICT", "流程已更新，请刷新后重试", 409,
                          current_revision=run.revision)
    # 5. 生命周期：已结束流程不能执行新动作；CANCEL 自身豁免，由 handler 判定终态。
    if action not in _RUN_ACTIONS and (run.ended_at is not None or run.execution_status == "CANCELLED"):
        raise LaunchError("LAUNCH_ENDED", "已结束的流程不能执行新动作", 409)
    # 只读计算段（6/9/10 与事务收敛共用）：定义/步骤/事实/计划。
    definition, steps, facts, predicates, plan = launch_plan(db, run)
    # 6. 步骤定位与动作目录（冻结快照 available_actions；run 级与框架级动作豁免）。
    meta = action_meta(action)
    if not meta.connected:
        raise LaunchError("ACTION_NOT_ALLOWED", meta.disabled_reason or "动作尚未接通", 409)
    step = _locate_step(db, run, action, step_code, meta, definition)
    # 7. 载荷契约（拒绝完成标记与未知键；note 截断）。
    normalized = validate_payload(action, payload)
    # 8. 权限目录（缺任一权限 403，不产生事件）。
    missing = [key for key in meta.permissions if not current.has(key)]
    if missing:
        raise LaunchError("PERMISSION_DENIED", "缺少权限：" + missing[0], 403)
    # 9. NBA 门禁：动作特判前置（设计 D6；权威 allowed_actions 由 T03 launch_nba 供给）。
    _action_gate(action, run, step, meta, plan, facts)
    # 10. 步骤状态机守卫：来源状态不满足 409 并附阻断原因（AC-4.5）。
    if step is not None and step.step_status not in meta.source_states:
        raise _step_state_conflict(step)
    handler = HANDLERS.get(action)
    if handler is None:
        raise LaunchError("ACTION_NOT_ALLOWED", "动作尚未接通", 409)
    context = ActionContext(db=db, run=run, step=step, current=current, payload=normalized,
                            facts=facts, plan=plan, definition=next(
                                (item for item in definition.steps
                                 if step is not None and item.step_code == step.step_code), None),
                            predicates=predicates)
    before = launch_state.state_snapshot(run, steps)
    digest = evidence_fingerprint(run, step, action, launch_state.facts_digest(facts, predicates))
    try:
        with db.begin_nested():
            effect = handler(context)
            return _finish(db, current, run, steps, expected_revision, action, step_code, effect,
                           event_key, load_hash, digest, facts, predicates, definition, plan, before)
    except LaunchError:
        raise
    except ActionError as exc:  # 领域失败兜底转换：409 零状态变更（设计 D11）。
        raise LaunchError("ACTION_PRECONDITION_FAILED", str(exc), 409) from exc
    except Exception as exc:  # 意外异常：落 FAILED + LaunchActionFailed 事件（D11）。
        error = redact(str(exc) or type(exc).__name__)[:2000]
        failed = StepEffect(status="FAILED", attempts_delta=1, result={"error": error},
                            receipt={"error": error, "attempts": step.attempts + 1 if step else 0})
        with db.begin_nested():
            return _finish(db, current, run, steps, expected_revision, action, step_code, failed,
                           "launch:action-failed:" + action_digest(run.id, step_code, action,
                                                                   idempotency_key),
                           load_hash, digest, facts, predicates, definition, plan, before,
                           event_type="LaunchActionFailed", status="FAILED")


def _finish(db, current, run, steps, expected_revision, action, step_code, effect, event_key,
            load_hash, digest, facts, predicates, definition, plan, before, *,
            event_type=None, status=None):
    """D10 收敛 + 落库 + 事件（成功/失败共用）：调用方已在保存点内，一次事务一条事件。"""
    target = next((item for item in steps if item.step_code == step_code), None)
    assertions = {}
    if target is not None:
        migration = _effect_migration(effect)
        if migration:
            assertions[step_code] = migration
    world_facts, world_predicates = launch_state.asserted_world(
        effect.run_fields, effect.result, target, facts, predicates)
    plan, overrides = launch_state.converge(db, run, steps, plan, world_facts, world_predicates,
                                            definition, activated=activated_flag(run),
                                            cancelled=effect.cancelled, assertions=assertions)
    _assert_terminal(effect, plan, step_code)
    changes = launch_state.plan_changes(run, steps, plan, overrides=overrides,
                                        run_overrides=effect.run_fields)
    _cas_run(db, run, current, expected_revision, changes)
    _apply_steps(db, steps, changes, step_code or None, target.step_status if target else None)
    db.flush()
    db.refresh(run)
    after = launch_state.state_snapshot(run, steps)
    status = status or status_of(step_code, after)
    event = _append_event(db, run, current, action, step_code, effect, event_key, before, after,
                          load_hash, digest, status,
                          event_type or _EVENT_TYPES.get(action, "LaunchActionExecuted"))
    return {"revision": run.revision, "action": action, "status": status,
            "step": {"step_code": step_code,
                     "step_status": (after["steps"].get(step_code) or {}).get("status")},
            "receipt": effect.receipt or {}, "event_id": event.id, "run": run, "plan": plan}


def _effect_migration(effect: StepEffect) -> dict:
    """StepEffect → 步骤迁移字典（标量断言 + result/evidence_refs/attempts/external）。"""
    migration = {}
    if effect.status:
        migration["step_status"] = effect.status
    if effect.result:
        migration["result"] = effect.result
    if effect.evidence_refs:
        migration["evidence_refs"] = list(effect.evidence_refs)
    if effect.attempts_delta:
        migration["attempts_delta"] = effect.attempts_delta
    if effect.external:
        migration["external_status"] = effect.external.get("status", "")
        migration["external_reference"] = effect.external.get("reference", "")
        migration["external_type"] = effect.external.get("type", "UNKNOWN")
    return migration


def status_of(step_code, after):
    """响应状态：目标步骤落入 WAITING_APPROVAL 即 PENDING_APPROVAL，否则 EXECUTED。"""
    if step_code and (after["steps"].get(step_code) or {}).get("status") == "WAITING_APPROVAL":
        return "PENDING_APPROVAL"
    return "EXECUTED"


def _assert_terminal(effect, plan, step_code):
    """后置不变量（D10）：handler 断言终态时重算计划必须给同一状态，否则 409 防假成功。"""
    if effect.status != "COMPLETED":
        return
    if ((plan.get("steps") or {}).get(step_code) or {}).get("status") != "COMPLETED":
        raise LaunchError("ACTION_PRECONDITION_FAILED", "完成条件在事务内未能满足，已拒绝落库", 409)


def _action_gate(action, run, step, meta, plan, facts):
    """NBA 门禁特判（设计 D6 executable 前置）：COMPLETE_DATA 需完成条件被服务端
    事实满足；run 级取消需流程可取消。权威 allowed_actions 由 T03 launch_nba 供给，
    届时本门禁并入该纯函数，框架只消费其结论。"""
    if step is not None and action == "COMPLETE_DATA":
        target = (plan.get("steps") or {}).get(step.step_code) or {}
        if target.get("completion_satisfied") is not True:
            raise LaunchError("ACTION_PRECONDITION_FAILED", "完成条件尚未被服务端事实满足", 409,
                              blockers=missing_blockers(facts, step))
    if meta.target == "run" and (run.execution_status == "COMPLETED"
                                 or (run.platform_status == "ACTIVE" and run.verification_status == "VERIFIED")):
        raise LaunchError("ACTION_PRECONDITION_FAILED", "当前流程不能取消", 409)


def _locate_step(db, run, action, step_code, meta, definition):
    """步骤定位：step 级动作必须命中本流程步骤且在冻结快照 available_actions 内；
    run 级动作与框架级动作（RETRY）豁免（AC-4.4）。"""
    if meta.target != "step":
        return None
    step = db.query(WorkflowStep).filter_by(run_id=run.id, step_code=step_code).first()
    if step is None:
        raise LaunchError("ACTION_NOT_ALLOWED", "步骤不存在于当前流程", 409)
    frozen = next(item for item in definition.steps if item.step_code == step_code)
    if not meta.framework and action not in frozen.available_actions:
        raise LaunchError("ACTION_NOT_ALLOWED", "动作不在该步骤的执行目录", 409)
    return step


def _step_state_conflict(step):
    """步骤状态冲突（AC-4.5）：附当前阻断原因，供前端刷新后重试。"""
    reason = step.blocking_reason or {}
    blockers = [reason] if reason else [{"code": "STEP_STATE_CONFLICT", "message": "步骤状态不满足执行条件",
                                         "step_code": step.step_code, "owner_actor": step.actor,
                                         "evidence_refs": [], "repair_action": None}]
    return LaunchError("STEP_STATE_CONFLICT", "步骤当前状态不允许该动作", 409, blockers=blockers)


def _cas_run(db, run, current, expected_revision, changes):
    """Run 级 CAS（设计 D3）：revision 条件更新，rowcount!=1 → 409 带 current_revision。"""
    result = db.execute(update(WorkflowRun).where(
        WorkflowRun.id == run.id, WorkflowRun.tenant_id == current.legacy_tenant_id,
        WorkflowRun.flow_kind == PLATFORM_LAUNCH, WorkflowRun.revision == expected_revision,
    ).values(revision=expected_revision + 1, **changes["run"]).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.refresh(run)
        raise LaunchError("REVISION_CONFLICT", "流程已更新，请刷新后重试", 409,
                          current_revision=run.revision)


def _apply_steps(db, steps, changes, target_code, source_state):
    """步骤落库：目标步骤按来源状态条件更新（D3 状态机守卫），其余步骤 ORM 写。"""
    by_code = {step.step_code: step for step in steps}
    for code, updates in changes["steps"].items():
        step = by_code[code]
        if code != target_code:
            for name, value in updates.items():
                setattr(step, name, value)
            continue
        result = db.execute(update(WorkflowStep).where(
            WorkflowStep.id == step.id, WorkflowStep.step_status == source_state,
        ).values(**updates).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise _step_state_conflict(step)
        db.refresh(step)
    db.flush()


def _append_event(db, run, current, action, step_code, effect, event_key, before, after,
                  load_hash, digest, status, event_type):
    """一次事务一条动作事件（设计 D10/§3.4）：payload 含审计四要素与回执。"""
    payload = {"action": action, "step_code": step_code, "payload_hash": load_hash,
               "evidence_fingerprint": digest, "status": status, "receipt": effect.receipt or {},
               "revision": run.revision, "actor_id": current.user_id}
    if effect.result and "action_id" in effect.result:
        payload["action_id"] = effect.result["action_id"]
    return launch_state.append_event(db, run, event_type=event_type, idempotency_key=event_key,
                                     source="USER", actor_id=current.user_id, before=before,
                                     after=after, payload=payload)


def _replay(db, run, current, action, event_key, load_hash):
    """幂等重放查询（设计 D2）：命中同载荷返回原回执；异载荷 409；未命中返回 None。"""
    meta = action_meta(action)
    missing = [key for key in meta.permissions if not current.has(key)]
    if missing:
        raise LaunchError("PERMISSION_DENIED", "缺少权限：" + missing[0], 403)
    event = db.query(WorkflowEvent).filter_by(tenant_id=run.tenant_id,
                                              idempotency_key=event_key).first()
    if event is None or event.run_id != run.id:
        return None
    if (event.payload or {}).get("payload_hash") != load_hash:
        raise LaunchError("IDEMPOTENCY_CONFLICT", "同一幂等键已用于不同载荷", 409)
    return replay_receipt(event)


def replay_receipt(event: WorkflowEvent) -> dict:
    """从事件重建动作回执（设计 §3.1）：含原 event_id，不新建事件、不产生外部意图。"""
    payload = event.payload or {}
    step_code = payload.get("step_code") or ""
    after_steps = (event.after or {}).get("steps") or {}
    return {"revision": payload.get("revision"), "action": payload.get("action"),
            "status": payload.get("status"),
            "step": {"step_code": step_code,
                     "step_status": (after_steps.get(step_code) or {}).get("status")},
            "receipt": payload.get("receipt") or {}, "event_id": event.id}
