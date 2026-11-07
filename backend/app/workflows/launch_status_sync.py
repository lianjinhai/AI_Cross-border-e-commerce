"""平台状态摄入编排：raw_status 映射 → 乱序/未映射守卫 → 迁移校验 → CAS 落库 + 事件。

设计依据 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md` §5。本模块只负责「让中间状态可达」：
`SUBMITTED → UNDER_REVIEW → ACCEPTED`。**不置 ACTIVE、不改 verification_status**——
在售只能由 `CONFIRM_ACTIVATION` 独立核验后置位，回执验证也不等于在售。
"""

from sqlalchemy import update

from ..models import PlatformPublishAttempt, WorkflowRun, utcnow
from . import launch_state, launch_status
from .kinds import PLATFORM_LAUNCH
from .launch_access import LaunchError, launch_context, owned_launch
from .launch_plan import launch_plan
from .launch_rules import evaluate_readiness, revoked_codes
from .transactions import ensure_write_transaction

MAPPING_VERSION = "platform-status-v1"


def sync_platform_status(db, ctx, run_id, payload, expected_revision):
    """摄入一次平台状态事件；返回 changed / platform_status / error / revision。调用方提交。"""
    if type(expected_revision) is not int or expected_revision < 1:
        raise LaunchError("REVISION_REQUIRED", "需要有效的流程版本号")
    ensure_write_transaction(db)
    current, scope = launch_context(db, ctx, "launch:manage")
    run = owned_launch(db, current, scope, run_id)
    if run.revision != expected_revision:
        raise LaunchError("REVISION_CONFLICT", "流程已更新，请刷新后重试", 409,
                          current_revision=run.revision)
    if run.ended_at is not None or run.execution_status == "CANCELLED":
        raise LaunchError("LAUNCH_ENDED", "已结束的流程不能同步平台状态", 409)

    definition, steps, facts, predicates, _plan = launch_plan(db, run)
    raw_status = (payload.get("raw_status") or "").strip()
    mapped, error = launch_status.map_platform_status(raw_status, definition.status_mapping)
    attempt = _attempt(db, run)
    previous_revision = attempt.source_revision if attempt is not None else None
    _record_attempt(attempt, payload, raw_status)

    # 守卫一：未注册的原始状态 → 保持原状态，记 PLATFORM_ERROR（§5 末行）。
    if error is not None:
        _event(db, current, run, steps, "PlatformStatusUnmapped",
               {"raw_status": raw_status, "error": error, "platform_status": run.platform_status})
        return _result(run, raw_status, False, error)

    # 守卫二：旧序号/重复序号只留审计，不回退状态（§5 末段）。
    if launch_status.is_stale_event(payload.get("source_revision"), previous_revision):
        _event(db, current, run, steps, "PlatformStatusStaleIgnored",
               {"raw_status": raw_status, "mapped": mapped,
                "source_revision": payload.get("source_revision"),
                "last_revision": previous_revision})
        return _result(run, raw_status, False, "STALE_EVENT")

    if mapped == "ACTIVE":
        raise LaunchError("ACTION_PRECONDITION_FAILED",
                          "在售状态不能由平台状态同步置位，须走 CONFIRM_ACTIVATION 独立核验", 409)
    if not launch_status.can_transition(run.platform_status, mapped):
        raise LaunchError("PLATFORM_TRANSITION_INVALID",
                          "平台状态不能从 %s 迁移到 %s" % (run.platform_status, mapped), 409)
    if mapped == run.platform_status:
        return _result(run, raw_status, False, None)

    plan = _recompute(definition, steps, run, facts, predicates, mapped)
    changes = launch_state.plan_changes(run, steps, plan, run_overrides={"platform_status": mapped})
    before = launch_state.state_snapshot(run, steps)
    with db.begin_nested():
        applied = db.execute(update(WorkflowRun).where(
            WorkflowRun.id == run.id, WorkflowRun.tenant_id == current.legacy_tenant_id,
            WorkflowRun.flow_kind == PLATFORM_LAUNCH, WorkflowRun.revision == expected_revision,
        ).values(revision=expected_revision + 1, **changes["run"])
            .execution_options(synchronize_session=False))
        if applied.rowcount != 1:
            raise LaunchError("REVISION_CONFLICT", "流程已更新，请刷新后重试", 409)
        for step in steps:
            for name, value in changes["steps"].get(step.step_code, {}).items():
                setattr(step, name, value)
        db.flush()
        db.refresh(run)
        _event(db, current, run, steps, "PlatformStatusChanged",
               {"raw_status": raw_status, "previous": before["platform_status"], "mapped": mapped,
                "source": payload.get("source"), "external_reference": payload.get("external_reference")},
               before=before)
        db.flush()
    db.refresh(run)
    return _result(run, raw_status, True, None)


def _recompute(definition, steps, run, facts, predicates, mapped):
    """按新平台状态重算就绪度：平台事实变化可能解锁/阻断步骤，不能沿用旧 plan。"""
    world_facts, world_predicates = launch_state.asserted_world(
        {"platform_status": mapped}, None, None, facts, predicates)
    activated = launch_status.is_activated(mapped, run.completed_at)
    states = {step.step_code: step.step_status for step in steps}
    return evaluate_readiness(definition.model_dump(), states, world_facts, world_predicates,
                              activated=activated, revoked=revoked_codes(steps))


def _attempt(db, run):
    """取该销售对象的发布尝试（外部事件留痕的载体）；未提交过则为 None。"""
    return db.query(PlatformPublishAttempt).filter_by(
        tenant_id=run.tenant_id, listing_id=run.listing_id,
        shop_id=run.shop_id, platform=run.platform).first()


def _record_attempt(attempt, payload, raw_status):
    """外部事件七要素留痕（§5）：来源、平台时间、外部引用、序号、映射版本。"""
    if attempt is None:
        return
    attempt.raw_status = raw_status[:256]
    attempt.source = (payload.get("source") or "")[:32]
    attempt.source_time = payload.get("source_time")
    attempt.external_reference = (payload.get("external_reference") or "")[:128]
    if payload.get("source_revision") is not None:
        attempt.source_revision = int(payload["source_revision"])
    attempt.received_at = utcnow()
    attempt.mapping_version = MAPPING_VERSION


def _event(db, ctx, run, steps, event_type, payload, *, before=None):
    """写不可变事件；after 用当前快照，before 缺省时与 after 相同（纯审计事件）。"""
    snapshot = launch_state.state_snapshot(run, steps)
    launch_state.append_event(
        db, run, event_type=event_type,
        idempotency_key="launch:%s:platform-status:%s:%s" % (
            run.id, run.revision, payload.get("raw_status", "")[:64]),
        source="PLATFORM", actor_id=ctx.user_id,
        before=before or snapshot, after=snapshot, payload=payload)


def _result(run, raw_status, changed, error):
    return {"changed": changed, "platform_status": run.platform_status, "raw_status": raw_status,
            "error": error, "revision": run.revision}
