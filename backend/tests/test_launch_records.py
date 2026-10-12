"""Launch 持久化的事务/版本/并发契约；不调用真实 Adapter。"""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import (
    Listing,
    PlatformPublishAttempt,
    Product,
    Shop,
    User,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
    WorkflowTemplate,
)
from app.services.action_publish import publish_targets
from app.services.ai_actions import ActionError
from app.services.workspace_context import resolve_workspace_context
from app.workflows import launch_records, launch_runtime
from app.workflows.contract_profiles import simple_contract
from app.workflows.launch_access import LaunchError, get_launch
from app.workflows.launch_facts import load_launch_facts
from app.workflows.launch_records import create_launch
from app.workflows.launch_runtime import refresh_launch
from app.workflows.profiles import create_profile, publish_profile


@pytest.fixture
def launch_db(client):
    with SessionLocal() as db:
        owner = db.query(User).filter_by(username="admin").one()
        ctx = resolve_workspace_context(db, owner)
        product = Product(tenant_id=owner.tenant_id, sku="launch-record-contract", title="Launch product", category="家居")
        shops = [Shop(tenant_id=owner.tenant_id, platform="shopee", shop_name=name, market="SG",
                      fulfillment_mode="DROPSHIP", is_demo=True) for name in ("Launch A", "Launch B")]
        db.add_all([product, *shops])
        db.flush()
        parent = Listing(tenant_id=owner.tenant_id, product_id=product.id, platform="shopee", title="Parent content",
                         status="published", external_id="historical-reference", risk_level="low")
        db.add(parent)
        db.commit()
        profile = create_profile(db, ctx, simple_contract())
        publish_profile(db, ctx, profile.id, profile.definition_hash)
        db.commit()
        yield db, ctx, product, shops, parent
        db.rollback()
        runs = db.query(WorkflowRun.id).filter_by(product_id=product.id).all()
        ids = [row[0] for row in runs]
        db.query(WorkflowEvent).filter(WorkflowEvent.run_id.in_(ids)).delete(synchronize_session=False)
        db.query(WorkflowStep).filter(WorkflowStep.run_id.in_(ids)).delete(synchronize_session=False)
        db.query(WorkflowRun).filter(WorkflowRun.id.in_(ids)).delete(synchronize_session=False)
        listing_ids = db.query(Listing.id).filter_by(product_id=product.id)
        db.query(PlatformPublishAttempt).filter(PlatformPublishAttempt.listing_id.in_(listing_ids)).delete(synchronize_session=False)
        db.query(Listing).filter_by(product_id=product.id).delete(synchronize_session=False)
        db.delete(product)
        for shop in shops:
            db.delete(shop)
        db.query(WorkflowTemplate).filter_by(tenant_id=ctx.legacy_tenant_id, profile_key="SIMPLE_CONTRACT").delete()
        db.commit()


def test_dual_store_independent_drafts_and_pinned_versions(launch_db):
    db, ctx, product, shops, parent = launch_db
    first = create_launch(db, ctx, product.id, shops[0].id, "first", parent_listing_id=parent.id)
    db.commit()
    old_hash = first.definition_hash
    new_profile = create_profile(db, ctx, {**simple_contract(2), "name": "New lifecycle"})
    publish_profile(db, ctx, new_profile.id, new_profile.definition_hash)
    db.commit()
    second = create_launch(db, ctx, product.id, shops[1].id, "second", parent_listing_id=parent.id)
    db.commit()
    assert first.id != second.id and first.listing_id != second.listing_id
    db.expire_all()
    first = get_launch(db, ctx, first.id)
    assert first.workflow_version == 1 and first.definition_snapshot["version"] == 1
    assert first.definition_hash == old_hash and second.workflow_version == 2
    for run, shop in ((first, shops[0]), (second, shops[1])):
        listing = db.get(Listing, run.listing_id)
        assert listing.shop_id == shop.id and listing.parent_listing_id == parent.id
        assert listing.title == "Parent content" and listing.status == "draft"
        assert listing.external_id == "" and listing.risk_level == "unknown"
        assert listing.verification_status == "UNKNOWN" and listing.platform_status == "UNKNOWN"
        assert db.query(WorkflowStep).filter_by(run_id=run.id).count() == 5
        event = db.query(WorkflowEvent).filter_by(run_id=run.id).one()
        assert event.event_type == "LaunchCreated" and event.delivery_status == "PENDING"
        assert event.after["platform_status"] == "NOT_SUBMITTED" and run.active_slot == 1
    assert parent.status == "published" and parent.external_id == "historical-reference" and parent.shop_id is None


def test_idempotency_and_active_object_conflicts(launch_db):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[0].id, "same")
    db.commit()
    assert create_launch(db, ctx, product.id, shops[0].id, "same").id == run.id
    with pytest.raises(LaunchError) as conflict:
        create_launch(db, ctx, product.id, shops[1].id, "same")
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(LaunchError) as active:
        create_launch(db, ctx, product.id, shops[0].id, "different")
    assert active.value.code == "ACTIVE_LAUNCH_EXISTS" and active.value.existing_launch_id == run.id
    assert db.query(WorkflowRun).filter_by(product_id=product.id).count() == 1
    assert db.query(Listing).filter_by(product_id=product.id).count() == 2


def test_outer_rollback_removes_draft_steps_run_and_event(launch_db):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[0].id, "rollback")
    run_id, listing_id = run.id, run.listing_id
    db.rollback()
    assert db.get(WorkflowRun, run_id) is None and db.get(Listing, listing_id) is None
    assert db.query(WorkflowStep).filter_by(run_id=run_id).count() == 0
    assert db.query(WorkflowEvent).filter_by(run_id=run_id).count() == 0


def test_event_failure_does_not_leave_partial_create(launch_db, monkeypatch):
    db, ctx, product, shops, _ = launch_db
    original = launch_records._steps_and_event

    def fail_after_event(*args):
        original(*args)
        args[0].flush()
        raise RuntimeError("contract event failure")

    monkeypatch.setattr(launch_records, "_steps_and_event", fail_after_event)
    with pytest.raises(RuntimeError, match="event failure"):
        create_launch(db, ctx, product.id, shops[0].id, "failure")
    db.commit()
    assert db.query(WorkflowRun).filter_by(product_id=product.id).count() == 0
    assert db.query(Listing).filter_by(product_id=product.id).count() == 1


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_creation_has_single_sales_object(launch_db, same_key):
    db, ctx, product, shops, _ = launch_db
    product_id, shop_id = product.id, shops[0].id
    barrier = Barrier(2)

    def worker(index):
        with SessionLocal() as worker_db:
            barrier.wait(timeout=10)
            try:
                run = create_launch(worker_db, ctx, product_id, shop_id, "concurrent" if same_key else f"key-{index}")
                worker_db.commit()
                return run.id
            except LaunchError as exc:
                worker_db.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(worker, (0, 1)))
    if same_key:
        assert results[0] == results[1] and type(results[0]) is int
    else:
        assert sum(type(result) is int for result in results) == 1 and "ACTIVE_LAUNCH_EXISTS" in results
    assert db.query(WorkflowRun).filter_by(product_id=product_id).count() == 1
    assert db.query(Listing).filter_by(product_id=product_id).count() == 2


def test_database_slot_constraint_and_bound_listing_target(launch_db):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[0].id, "bound")
    db.commit()
    for slot in (1, 2):
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(WorkflowRun(tenant_id=ctx.legacy_tenant_id, template_key="collision", product_id=product.id,
                               shop_id=shops[0].id, active_slot=slot))
            db.flush()
    for target in (None, shops[1].id):
        with pytest.raises(ActionError, match="绑定"):
            publish_targets(db, ctx.legacy_tenant_id, run.listing_id, target)


def test_read_create_and_replay_recheck_store_scope(launch_db):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[1].id, "before-scope")
    db.commit()
    membership = db.execute(text("SELECT id FROM workspace_memberships WHERE user_id=:id"), {"id": ctx.user_id}).scalar_one()
    db.execute(text("INSERT INTO membership_data_scopes(membership_id,scope_type,scope_ref) VALUES(:id,'SHOP_SCOPED',:ref)"),
               {"id": membership, "ref": json.dumps({"shop_ids": [shops[0].id]})})
    # 同一旧 Context 不能绕过新生效的店铺限制；最后回滚不影响账户原权限。
    try:
        for operation in (
            lambda: get_launch(db, ctx, run.id),
            lambda: create_launch(db, ctx, product.id, shops[1].id, "before-scope"),
            lambda: create_launch(db, ctx, product.id, shops[1].id, "after-scope"),
        ):
            with pytest.raises(LaunchError) as denied:
                operation()
            assert denied.value.status_code == 404
        allowed = create_launch(db, ctx, product.id, shops[0].id, "allowed-scope")
        assert allowed.shop_id == shops[0].id
    finally:
        db.rollback()


def test_demo_purge_cannot_delete_launch_audit(launch_db, client, auth_headers):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[0].id, "preserve-audit")
    db.commit()
    response = client.post("/api/shops/purge_demo_data", headers=auth_headers)
    assert response.status_code == 409 and "审计" in response.json()["detail"]
    db.expire_all()
    assert get_launch(db, ctx, run.id).listing_id is not None
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == 1
    assert db.get(Product, product.id) is not None


def test_readiness_refresh_persists_once_and_preserves_platform_facts(launch_db):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[0].id, "readiness")
    db.commit()
    run, plan = refresh_launch(db, ctx, run.id, 1)
    db.commit()
    assert run.revision == 2 and run.execution_status == "READY" and run.current_step == "INFORMATION"
    assert plan["runnable_steps"] == ["INFORMATION"]
    assert run.platform_status == "NOT_SUBMITTED" and run.verification_status == "UNKNOWN"
    event = db.query(WorkflowEvent).filter_by(run_id=run.id, sequence=2).one()
    assert event.before["execution_status"] == "NOT_STARTED" and event.after["execution_status"] == "READY"
    assert event.payload["changed_steps"] == ["INFORMATION"]
    replay, _ = refresh_launch(db, ctx, run.id, 2)
    db.commit()
    assert replay.revision == 2 and db.query(WorkflowEvent).filter_by(run_id=run.id).count() == 2
    with pytest.raises(LaunchError) as stale:
        refresh_launch(db, ctx, run.id, 1)
    assert stale.value.code == "REVISION_CONFLICT"


@pytest.mark.parametrize("event_failure", [False, True])
def test_readiness_state_and_event_rollback_together(launch_db, monkeypatch, event_failure):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[0].id, "readiness-rollback")
    db.commit()
    run_id = run.id
    if event_failure:
        def fail(*args):
            raise RuntimeError("outbox write failure")
        monkeypatch.setattr(launch_runtime, "_record_event", fail)
        with pytest.raises(RuntimeError, match="outbox"):
            refresh_launch(db, ctx, run_id, 1)
        db.commit()  # 即使调用方捕获错误后提交，保存点内也不得留下半步状态。
    else:
        refresh_launch(db, ctx, run_id, 1)
        db.rollback()
    db.expire_all()
    assert db.get(WorkflowRun, run_id).revision == 1
    assert db.get(WorkflowRun, run_id).execution_status == "NOT_STARTED"
    assert {step.step_status for step in db.query(WorkflowStep).filter_by(run_id=run_id)} == {"PENDING"}
    assert db.query(WorkflowEvent).filter_by(run_id=run_id).count() == 1


def test_concurrent_readiness_refresh_rejects_stale_revision(launch_db):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[0].id, "readiness-concurrent")
    db.commit()
    run_id = run.id
    barrier = Barrier(2)

    def worker(_):
        with SessionLocal() as session:
            barrier.wait(timeout=10)
            try:
                changed, _ = refresh_launch(session, ctx, run_id, 1)
                session.commit()
                return changed.revision
            except LaunchError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(worker, (0, 1)))
    assert sorted(map(str, results)) == ["2", "REVISION_CONFLICT"]
    assert db.query(WorkflowEvent).filter_by(run_id=run_id).count() == 2


@pytest.mark.parametrize("corruption", ["profile", "step", "shop"])
def test_refresh_rejects_changed_definition_step_or_store(launch_db, corruption):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[0].id, "invalid-refresh")
    db.commit()
    if corruption == "profile":
        run.definition_hash = "invalid"
    elif corruption == "step":
        step = db.query(WorkflowStep).filter_by(run_id=run.id, step_code="INFORMATION").one()
        step.params = {**step.params, "completion_condition": True}
    else:
        shops[0].market = "MY"
    db.flush()
    with pytest.raises(LaunchError) as refused:
        refresh_launch(db, ctx, run.id, 1)
    assert refused.value.code == ("LAUNCH_CONTEXT_CHANGED" if corruption == "shop" else "LAUNCH_DEFINITION_CORRUPT")
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == 1
    db.rollback()


def test_only_matching_successful_receipt_becomes_submission_fact(launch_db):
    db, ctx, product, shops, _ = launch_db
    run = create_launch(db, ctx, product.id, shops[0].id, "receipt-fact")
    db.commit()
    attempt = PlatformPublishAttempt(tenant_id=ctx.legacy_tenant_id, listing_id=run.listing_id,
                                     shop_id=shops[1].id, platform="shopee", idempotency_key="fact-receipt",
                                     status="succeeded", external_id="receipt-1", raw_status="ACTIVE")
    db.add(attempt)
    db.flush()
    assert "submission_reference" not in load_launch_facts(db, run)[0]["platform"]
    attempt.shop_id = shops[0].id
    attempt.status = "uncertain"
    db.flush()
    assert "submission_reference" not in load_launch_facts(db, run)[0]["platform"]
    attempt.status = "succeeded"
    db.flush()
    facts, predicates = load_launch_facts(db, run)
    assert facts["platform"] == {"status": "NOT_SUBMITTED", "submission_reference": "receipt-1"}
    assert not predicates and run.verification_status == "UNKNOWN"
