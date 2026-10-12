"""Launch 共享状态内核与动作目录：载荷白名单、纯函数 diff、投影、落地、事件脱敏。"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    AiAction,
    Listing,
    PlatformPublishAttempt,
    Product,
    Shop,
    Tenant,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
)
from app.services.workspace_context import (
    ROLE_FACTORY_COLLABORATOR,
    SOURCE_FACTORY,
    WorkspaceContext,
)
from app.workflows.kinds import PLATFORM_LAUNCH
from app.workflows.launch_access import LaunchError, launch_context
from app.workflows.launch_action_catalog import (
    BUSINESS_ACTION_META,
    PRICE_STOCK_ACTIONS,
    action_meta,
    validate_payload,
)
from app.workflows.launch_facts import launch_facts_from_rows, load_launch_facts
from app.workflows.launch_state import (
    action_step_projection,
    append_event,
    facts_digest,
    land_completed_waits,
    next_sequence,
    plan_changes,
    platform_receipt,
    state_snapshot,
)
from app.workflows.profile_schema import BUSINESS_ACTIONS


@pytest.fixture
def state_db():
    """独立内存库：租户 + 商品/店铺/草稿 + 三步流程（INFORMATION/SUBMISSION/ACTIVATION）。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="状态内核探针")
        db.add(tenant)
        db.flush()
        product = Product(tenant_id=tenant.id, sku="STATE-1", title="状态商品", category="家居")
        shop = Shop(tenant_id=tenant.id, platform="shopee", shop_name="State Shop", market="SG",
                    fulfillment_mode="DROPSHIP", is_demo=True)
        db.add_all([product, shop])
        db.flush()
        listing = Listing(tenant_id=tenant.id, product_id=product.id, shop_id=shop.id,
                          platform="shopee", title="State draft")
        db.add(listing)
        db.flush()
        run = WorkflowRun(tenant_id=tenant.id, workspace_id=tenant.id, flow_kind=PLATFORM_LAUNCH,
                          template_key="SIMPLE_CONTRACT", name="状态样本", product_id=product.id,
                          shop_id=shop.id, listing_id=listing.id, environment="CONTRACT_TEST",
                          platform="shopee", market="SG", fulfillment_mode="DROPSHIP", revision=1,
                          workflow_version=1, definition_hash="probe-hash",
                          execution_status="READY", platform_status="NOT_SUBMITTED",
                          verification_status="UNKNOWN", current_step="INFORMATION")
        db.add(run)
        db.flush()
        steps = {}
        for code, kind, status in (("INFORMATION", "DATA_PREPARATION", "READY"),
                                   ("SUBMISSION", "PLATFORM_SUBMISSION", "READY"),
                                   ("ACTIVATION", "PLATFORM_ACTIVATION", "READY")):
            step = WorkflowStep(tenant_id=tenant.id, run_id=run.id, step_code=code, business_type=kind,
                                step_status=status, agent="", action="")
            db.add(step)
            steps[code] = step
        db.commit()
        yield db, run, steps
    engine.dispose()


def _action(db, run, step_code, status, **kwargs):
    """构造关联本流程步骤的 AiAction（Launch 关联引用键与 submit_action.extra_evidence 一致）。"""
    now = datetime.utcnow()
    action = AiAction(tenant_id=run.tenant_id, workspace_id=run.workspace_id, agent_type="listing",
                      action_type="PUBLISH_LISTING", target_type="listing", target_id=run.listing_id,
                      reason="状态投影探针", evidence={"launch_id": run.id, "step_code": step_code,
                                                       "payload": {"shop_id": run.shop_id}},
                      expected_impact={}, risk_level="HIGH", required_permission="listing:write",
                      execution_mode="APPROVAL_REQUIRED", approval_required=True, status=status,
                      requested_by=1, outcome=kwargs.pop("outcome", {}), idempotency_key=kwargs.pop(
                          "idempotency_key", "probe-%s-%s" % (step_code, status)), created_at=now,
                      updated_at=now)
    for name, value in kwargs.items():
        setattr(action, name, value)
    db.add(action)
    db.flush()
    return action


def _plan(**satisfied):
    return {"steps": {code: {"status": "READY", "completion_satisfied": flag}
                      for code, flag in satisfied.items()}}


# ---------------------------------------------------------------- 动作目录与载荷契约

def test_catalog_covers_every_registered_business_action():
    registered = set().union(*BUSINESS_ACTIONS.values()) | {"RETRY", "CANCEL"}
    assert registered == set(BUSINESS_ACTION_META)
    connected = {action for action, meta in BUSINESS_ACTION_META.items() if meta.connected}
    assert connected == {"COMPLETE_DATA", "SUBMIT_PLATFORM", "CONFIRM_ACTIVATION", "RETRY",
                         "CANCEL", "ABANDON_PRODUCT"}
    for action in connected:
        assert BUSINESS_ACTION_META[action].disabled_reason == ""
    for action, meta in BUSINESS_ACTION_META.items():
        if not meta.connected:
            assert meta.disabled_reason, action + " 未接通必须给出原因"
    assert PRICE_STOCK_ACTIONS == {"REPORT_PRICE", "ACCEPT_PRICE", "COUNTER_PRICE",
                                   "REQUEST_STOCK", "CONFIRM_STOCK", "ABANDON_PRODUCT"}


def test_unknown_action_is_rejected_with_409():
    with pytest.raises(LaunchError) as refused:
        action_meta("DELETE_EVERYTHING")
    assert refused.value.code == "ACTION_NOT_ALLOWED" and refused.value.status_code == 409


@pytest.mark.parametrize("key", ["completed", "status", "platform_status", "verification_status",
                                 "execution_status", "step_status", "revision", "active_slot"])
def test_payload_rejects_completion_markers(key):
    with pytest.raises(LaunchError) as invalid:
        validate_payload("COMPLETE_DATA", {"note": "资料已核对", key: True})
    assert invalid.value.code == "ACTION_PAYLOAD_INVALID" and invalid.value.status_code == 422


def test_payload_rejects_unknown_key_and_normalizes_note():
    with pytest.raises(LaunchError) as unknown:
        validate_payload("COMPLETE_DATA", {"note": "ok", "reject_reason": "越界键"})
    assert unknown.value.code == "ACTION_PAYLOAD_INVALID"
    normalized = validate_payload("COMPLETE_DATA", {"note": "备" * 600})
    assert normalized == {"note": "备" * 500}
    with pytest.raises(LaunchError) as invalid:
        validate_payload("COMPLETE_DATA", "note=直接给字符串")
    assert invalid.value.code == "ACTION_PAYLOAD_INVALID"


def test_payload_required_keys_per_action():
    # CONFIRM_ACTIVATION 的材料引用/备注缺失由 handler 以 409 拒绝（AC-7.2），契约层只做白名单。
    with pytest.raises(LaunchError) as unknown:
        validate_payload("CONFIRM_ACTIVATION", {"material_ref": "订单截图#1", "verified": True})
    assert unknown.value.code == "ACTION_PAYLOAD_INVALID"
    assert validate_payload("CONFIRM_ACTIVATION", {"material_ref": "订单截图#1", "note": "已核对"}) == {
        "material_ref": "订单截图#1", "note": "已核对"}
    with pytest.raises(LaunchError) as missing:
        validate_payload("CANCEL", {"confirm": True})
    assert missing.value.code == "ACTION_PAYLOAD_INVALID" and "note" in str(missing.value)
    with pytest.raises(LaunchError) as unconfirmed:
        validate_payload("CANCEL", {"note": "不再上线", "confirm": False})
    assert unconfirmed.value.code == "ACTION_PAYLOAD_INVALID"
    assert validate_payload("CANCEL", {"note": "不再上线", "confirm": True}) == {
        "note": "不再上线", "confirm": True}


# ---------------------------------------------------------------- plan_changes 纯函数

def _run(**kwargs):
    base = {"revision": 2, "execution_status": "READY", "platform_status": "NOT_SUBMITTED",
            "verification_status": "UNKNOWN", "current_step": "INFORMATION", "blocked_reason": {},
            "started_at": None, "completed_at": None, "ended_at": None, "active_slot": 1}
    base.update(kwargs)
    return SimpleNamespace(**base)


def _step(code, status="PENDING", **kwargs):
    base = {"step_code": code, "step_status": status, "blocking_reason": {}, "input_revision": 0,
            "result": {}, "evidence_refs": [], "attempts": 0}
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_plan_changes_no_diff_when_plan_matches_instance():
    run, step = _run(), _step("INFORMATION", "READY")
    plan = {"execution_status": "READY", "current_step": "INFORMATION", "blockers": [],
            "steps": {"INFORMATION": {"status": "READY", "blocking_reason": {}, "invalidated": False}}}
    assert plan_changes(run, [step], plan) == {"run": {}, "steps": {}}


def test_plan_changes_projects_receipt_only_from_unsubmitted():
    plan = {"execution_status": "READY", "current_step": "SUBMISSION", "blockers": [],
            "steps": {"SUBMISSION": {"status": "READY", "blocking_reason": {}, "invalidated": False}}}
    step = _step("SUBMISSION")
    receipt = {"platform_status": "SUBMITTED"}
    projected = plan_changes(_run(), [step], plan, receipt=receipt)["run"]
    assert projected["platform_status"] == "SUBMITTED"
    assert projected["started_at"] is not None
    unknown = plan_changes(_run(platform_status="UNKNOWN"), [step], plan, receipt=receipt)["run"]
    assert unknown["platform_status"] == "SUBMITTED"
    active = plan_changes(_run(platform_status="ACTIVE"), [step], plan, receipt=receipt)["run"]
    assert "platform_status" not in active
    assert "platform_status" not in plan_changes(_run(), [step], plan)["run"]
    assert "platform_status" not in plan_changes(_run(), [step], plan, receipt={})["run"]


def test_plan_changes_completed_at_only_once():
    now = datetime(2026, 10, 12, 8, 0, 0)
    plan = {"execution_status": "COMPLETED", "current_step": "", "blockers": [],
            "steps": {"ACTIVATION": {"status": "COMPLETED", "blocking_reason": {}, "invalidated": False}}}
    step = _step("ACTIVATION", "COMPLETED")
    changed = plan_changes(_run(execution_status="READY"), [step], plan, now=now)["run"]
    assert changed["completed_at"] == now
    kept = plan_changes(_run(execution_status="READY", completed_at=now), [step], plan, now=now)["run"]
    assert "completed_at" not in kept


def test_plan_changes_merges_overrides_and_invalidation():
    now = datetime(2026, 10, 12, 9, 0, 0)
    plan = {"execution_status": "READY", "current_step": "SUBMISSION", "blockers": [],
            "steps": {"SUBMISSION": {"status": "READY", "blocking_reason": {}, "invalidated": True}}}
    step = _step("SUBMISSION", "WAITING_APPROVAL", result={"action_id": 7}, evidence_refs=["action:7"],
                 attempts=1, input_revision=4)
    changes = plan_changes(_run(current_step="SUBMISSION", started_at=now), [step], plan, now=now,
                           overrides={"SUBMISSION": {
                               "step_status": "FAILED", "result": {"error": "平台超时"},
                               "evidence_refs": ["attempt:9", "action:7"], "attempts_delta": 1}})
    assert changes["steps"]["SUBMISSION"] == {"step_status": "FAILED", "input_revision": 5,
                                              "result": {"action_id": 7, "error": "平台超时"},
                                              "evidence_refs": ["action:7", "attempt:9"], "attempts": 2}
    assert changes["run"] == {}


def test_plan_changes_run_overrides_win_over_receipt_projection():
    plan = {"execution_status": "COMPLETED", "current_step": "", "blockers": [],
            "steps": {"ACTIVATION": {"status": "COMPLETED", "blocking_reason": {}, "invalidated": False}}}
    step = _step("ACTIVATION", "COMPLETED")
    ended = datetime(2026, 10, 12, 10, 0, 0)
    changed = plan_changes(_run(), [step], plan, receipt={"platform_status": "SUBMITTED"},
                           run_overrides={"platform_status": "ACTIVE", "verification_status": "VERIFIED",
                                          "execution_status": "CANCELLED", "ended_at": ended,
                                          "active_slot": None}, now=ended)["run"]
    assert changed["platform_status"] == "ACTIVE" and changed["verification_status"] == "VERIFIED"
    assert changed["execution_status"] == "CANCELLED" and changed["ended_at"] == ended
    assert changed["active_slot"] is None and "completed_at" not in changed


def test_plan_changes_rejects_plan_without_step():
    plan = {"execution_status": "READY", "current_step": "", "blockers": [], "steps": {}}
    with pytest.raises(ValueError, match="缺少步骤"):
        plan_changes(_run(), [_step("MISSING")], plan)


# ---------------------------------------------------------------- AiAction 状态投影

def test_action_projection_maps_non_terminal_and_failed_states(state_db):
    db, run, steps = state_db
    _action(db, run, "SUBMISSION", "PENDING_APPROVAL")
    assert action_step_projection(db, run, list(steps.values())) == {
        "SUBMISSION": {"step_status": "WAITING_APPROVAL"}}
    steps["SUBMISSION"].step_status = "WAITING_APPROVAL"
    _action(db, run, "SUBMISSION", "APPROVED", idempotency_key="probe-approved")
    assert action_step_projection(db, run, list(steps.values())) == {}
    db.query(AiAction).filter_by(idempotency_key="probe-approved").delete()
    _action(db, run, "SUBMISSION", "EXECUTING", idempotency_key="probe-executing")
    assert action_step_projection(db, run, list(steps.values())) == {
        "SUBMISSION": {"step_status": "RUNNING"}}


def test_action_projection_failed_lands_once_and_redacts_error(state_db):
    db, run, steps = state_db
    _action(db, run, "SUBMISSION", "FAILED", outcome={"error": "回调手机 13800138000 核验失败"})
    first = action_step_projection(db, run, list(steps.values()))
    assert first["SUBMISSION"]["step_status"] == "FAILED"
    assert first["SUBMISSION"]["attempts_delta"] == 1
    assert "13800138000" not in first["SUBMISSION"]["result"]["error"]
    assert "[手机号]" in first["SUBMISSION"]["result"]["error"]
    steps["SUBMISSION"].step_status = "FAILED"
    db.flush()
    assert action_step_projection(db, run, list(steps.values())) == {}


def test_action_projection_rejected_and_success_and_foreign_rows(state_db):
    db, run, steps = state_db
    steps["SUBMISSION"].step_status = "WAITING_APPROVAL"
    _action(db, run, "SUBMISSION", "REJECTED", outcome={"approval_note": "材料不齐，打回"})
    assert action_step_projection(db, run, list(steps.values())) == {
        "SUBMISSION": {"step_status": "READY", "result": {"rejection_note": "材料不齐，打回"}}}
    db.query(AiAction).delete()
    _action(db, run, "SUBMISSION", "SUCCESS")
    assert action_step_projection(db, run, list(steps.values())) == {}
    db.query(AiAction).delete()
    foreign = _action(db, run, "SUBMISSION", "FAILED", idempotency_key="foreign-launch")
    foreign.evidence = {"launch_id": run.id + 99, "step_code": "SUBMISSION"}
    db.flush()
    assert action_step_projection(db, run, list(steps.values())) == {}


# ---------------------------------------------------------------- 回执/核验落地

def test_land_submission_requires_success_action_and_receipt(state_db):
    db, run, steps = state_db
    steps["SUBMISSION"].step_status = "WAITING_APPROVAL"
    steps["SUBMISSION"].result = {"action_id": 0}
    action = _action(db, run, "SUBMISSION", "PENDING_APPROVAL")
    steps["SUBMISSION"].result = {"action_id": action.id}
    receipt = {"attempt_id": 3, "external_id": "ext-3", "platform_status": "SUBMITTED"}
    facts = {"platform": {"submission_receipt": receipt}}
    plan = _plan(SUBMISSION=True)
    assert land_completed_waits(db, run, list(steps.values()), plan, facts) == {}
    action.status = "SUCCESS"
    db.flush()
    landed = land_completed_waits(db, run, list(steps.values()), plan, facts)
    assert landed == {"SUBMISSION": {"step_status": "COMPLETED", "result": {"receipt": receipt},
                                     "evidence_refs": ["attempt:3"]}}
    assert land_completed_waits(db, run, list(steps.values()), plan, {"platform": {}}) == {}
    assert land_completed_waits(db, run, list(steps.values()), _plan(SUBMISSION=False), facts) == {}


def test_land_activation_requires_verification_record(state_db):
    db, run, steps = state_db
    steps["ACTIVATION"].step_status = "WAITING_EXTERNAL"
    plan = _plan(ACTIVATION=True)
    assert land_completed_waits(db, run, list(steps.values()), plan, {}) == {}
    steps["ACTIVATION"].result = {"activation_verification": {"current": {"reviewer_id": 7}}}
    assert land_completed_waits(db, run, list(steps.values()), plan, {}) == {
        "ACTIVATION": {"step_status": "COMPLETED"}}


def test_land_ignores_other_business_types_and_non_waiting_steps(state_db):
    db, run, steps = state_db
    steps["INFORMATION"].step_status = "WAITING_USER"
    plan = _plan(INFORMATION=True)
    assert land_completed_waits(db, run, list(steps.values()), plan, {}) == {}
    steps["SUBMISSION"].step_status = "READY"
    receipt = {"attempt_id": 5, "external_id": "ext-5", "platform_status": "SUBMITTED"}
    assert land_completed_waits(db, run, list(steps.values()), _plan(SUBMISSION=True),
                                {"platform": {"submission_receipt": receipt}}) == {}


# ---------------------------------------------------------------- 事件、序号与指纹

def test_append_event_redacts_and_sequence_increments(state_db):
    db, run, _ = state_db
    assert next_sequence(db, run.id) == 1
    first = append_event(db, run, event_type="LaunchActionExecuted", idempotency_key="probe:event:1",
                         source="USER", actor_id=1, before={"revision": 1},
                         after={"revision": 2}, payload={"note": "联系 13800138000",
                                                         "nested": {"mail": "ops@example.com"}})
    assert first.sequence == 1 and first.event_type == "LaunchActionExecuted"
    assert first.payload["note"] == "联系 [手机号]"
    assert first.payload["nested"]["mail"] == "[邮箱]"
    assert first.before == {"revision": 1}
    second = append_event(db, run, event_type="LaunchCancelled", idempotency_key="probe:event:2",
                          source="USER", actor_id=1, before={}, after={}, payload={})
    assert second.sequence == 2
    assert next_sequence(db, run.id) == 3
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == 2


def test_state_snapshot_and_facts_digest_are_deterministic(state_db):
    db, run, steps = state_db
    snapshot = state_snapshot(run, list(steps.values()))
    assert snapshot["revision"] == 1 and snapshot["execution_status"] == "READY"
    assert set(snapshot["steps"]) == {"INFORMATION", "SUBMISSION", "ACTIVATION"}
    assert snapshot["steps"]["SUBMISSION"] == {"status": "READY", "blocking_reason": {},
                                               "input_revision": 0}
    facts, predicates = {"a": [1, {"b": 2}]}, {"p": {"Q": True}}
    digest = facts_digest(facts, predicates)
    assert digest == facts_digest({"a": [1, {"b": 2}]}, {"p": {"Q": True}})
    assert digest != facts_digest(facts, {"p": {"Q": False}})
    assert len(digest) == 64


def test_platform_receipt_reads_only_succeeded_fact():
    assert platform_receipt({"platform": {"submission_receipt": {"attempt_id": 1}}}) == {"attempt_id": 1}
    assert platform_receipt({"platform": {"status": "NOT_SUBMITTED"}}) is None
    assert platform_receipt({}) is None and platform_receipt(None) is None


# ---------------------------------------------------------------- 事实扩展

def test_launch_facts_extension_reasons_receipt_and_activation(state_db):
    db, run, steps = state_db
    facts, predicates = load_launch_facts(db, run)
    assert facts["assets"]["reasons"] == ["缺少可发布图片"]
    assert facts["assets"]["rights_fingerprint"]
    assert "submission_receipt" not in facts["platform"]
    assert predicates["verified_artifact"] == {"ACTIVATION": False}
    attempt = PlatformPublishAttempt(tenant_id=run.tenant_id, listing_id=run.listing_id,
                                     shop_id=run.shop_id, platform="shopee",
                                     idempotency_key="state-receipt", status="succeeded",
                                     external_id="ext-9")
    db.add(attempt)
    db.flush()
    facts, predicates = load_launch_facts(db, run)
    assert facts["platform"]["submission_reference"] == "ext-9"
    assert facts["platform"]["submission_receipt"]["attempt_id"] == attempt.id
    assert facts["platform"]["submission_receipt"]["external_id"] == "ext-9"
    assert facts["platform"]["submission_receipt"]["received_at"] is None
    steps["ACTIVATION"].result = {"activation_verification": {"current": {"reviewer_id": 7}}}
    db.flush()
    _, predicates = load_launch_facts(db, run)
    assert predicates["verified_artifact"] == {"ACTIVATION": True}


def test_launch_facts_from_rows_uses_provided_main_rows(state_db):
    db, run, _ = state_db
    product = db.get(Product, run.product_id)
    listing = db.get(Listing, run.listing_id)
    shop = db.get(Shop, run.shop_id)
    mismatch = PlatformPublishAttempt(tenant_id=run.tenant_id, listing_id=run.listing_id,
                                      shop_id=run.shop_id + 99, platform="shopee",
                                      idempotency_key="foreign-shop", status="succeeded",
                                      external_id="ext-x")
    db.add(mismatch)
    db.flush()
    facts, predicates = launch_facts_from_rows(db, run, product, listing, shop, mismatch)
    assert "submission_receipt" not in facts["platform"]
    assert facts["assets"]["reasons"] == ["缺少可发布图片"]
    assert predicates["asset_rights_allowed"]["PUBLISHABLE"] is False


# ---------------------------------------------------------------- Factory 身份 404

def test_factory_identity_gets_launch_not_found(state_db):
    db, run, _ = state_db
    ctx = WorkspaceContext(user_id=999, username="factory", display_name="工厂协作方",
                           workspace_id=None, workspace_name="工厂门户", workspace_kind="FACTORY",
                           membership_id=None, role=ROLE_FACTORY_COLLABORATOR,
                           permissions=frozenset({"supply:read"}), data_scope="FACTORY_SELF",
                           source=SOURCE_FACTORY, legacy_tenant_id=run.tenant_id)
    with pytest.raises(LaunchError) as denied:
        launch_context(db, ctx, "launch:read")
    assert denied.value.code == "LAUNCH_NOT_FOUND" and denied.value.status_code == 404
