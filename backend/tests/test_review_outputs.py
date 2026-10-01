"""复核分析持久化：可信身份、完整依据、重放与真实调用入口。"""

import ast
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.listing_review import ListingReviewAgent
from app.agents.orchestrator import invoke_listing, invoke_review
from app.db import Base
from app.models import (
    AiAction,
    ComplianceReport,
    Listing,
    ListingReviewDecision,
    PlatformRulePack,
    Product,
    Tenant,
    User,
)
from app.services.action_publish import publish_facts
from app.services.ai_actions import ActionError
from app.services.review_outputs import approve_review_output, finalize_reviews
from app.services.workspace_context import resolve_workspace_context
from app.workflows.engine import _step_context, run_step


@pytest.fixture
def case(monkeypatch):
    monkeypatch.delenv("ERP_RULES_URL", raising=False)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="复核产物隔离探针")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="review-owner", password_hash="unused", role="admin")
        product = Product(tenant_id=tenant.id, sku="REVIEW-OUT", title="Organizer", category="家居",
                          status="active", images=["https://example.com/image.jpg"])
        db.add_all([user, product])
        db.flush()
        listing = Listing(tenant_id=tenant.id, product_id=product.id, platform="review_outputs_probe",
                          title="Organizer", description="Desk organizer", status="draft", risk_level="low")
        pack = PlatformRulePack(platform=listing.platform, version=datetime.utcnow().strftime("%Y-%m-%d"),
                                source_url="https://example.com/rules", rules={"image_min": 1, "banned_words": []})
        db.add_all([listing, pack])
        db.commit()
        for target in ("app.agents.base.SessionLocal", "app.tools.audit._session_factory",
                       "app.services.review_outputs.SessionLocal", "app.workflows.engine.SessionLocal"):
            monkeypatch.setattr(target, lambda: Session(engine))
        yield db, resolve_workspace_context(db, user), user, listing, product, pack
    engine.dispose()


def test_agent_has_no_orm_or_rules_sync_side_effects(case):
    db, ctx, _, listing, _, _ = case
    source = Path(__file__).resolve().parents[1] / "app/agents/listing_review.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Attribute) and node.attr == "db" for node in ast.walk(tree))
    assert "check_updates" not in source.read_text(encoding="utf-8")
    with ListingReviewAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        result = agent.review(listing.id)
    assert result["_review_analysis"]["decision"] == "approved"
    assert db.query(ListingReviewDecision).count() == 0


def test_trusted_entry_saves_and_replays_without_publishing(case):
    db, ctx, _, listing, _, _ = case
    first = invoke_review(db, ctx, "review", listing.id, scope_key="review:stable")
    again = invoke_review(db, ctx, "review", listing.id, scope_key="review:stable")
    assert first == again
    assert db.query(ListingReviewDecision).count() == 1
    assert db.query(AiAction).count() == 0
    assert listing.status == "draft"


def test_successful_sync_diagnostics_do_not_break_same_scope_replay(case, monkeypatch):
    db, ctx, _, listing, _, _ = case
    monkeypatch.setenv("ERP_RULES_URL", "https://example.invalid/mock")
    responses = iter([{"updated": True, "hint": "本次已更新"},
                      {"updated": False, "hint": "已是最新版本"}])
    monkeypatch.setattr("app.services.review_outputs.check_updates", lambda *a, **k: next(responses))
    first = invoke_review(db, ctx, "review", listing.id, scope_key="sync:stable")
    replay = invoke_review(db, ctx, "review", listing.id, scope_key="sync:stable")
    assert first == replay and first["evidence"]["rule_sync"]["updated"] is True
    assert db.query(ListingReviewDecision).count() == 1


@pytest.mark.parametrize("change", ["content", "same_version_rules", "new_report", "inactive", "revoked"])
def test_replay_revalidates_live_facts_and_permission(case, change):
    db, ctx, user, listing, product, pack = case
    invoke_review(db, ctx, "review", listing.id, scope_key="replay:facts")
    if change == "content":
        product.title = "Changed"
    elif change == "same_version_rules":
        pack.rules = {**pack.rules, "manual_categories": ["家居"]}
    elif change == "new_report":
        db.add(ComplianceReport(tenant_id=ctx.legacy_tenant_id, target_type="listing",
                                listing_id=listing.id, risk_level="high", score=0))
    elif change == "inactive":
        user.status = "disabled"
    else:
        user.role = "viewer"
    db.commit()
    with pytest.raises(ActionError):
        invoke_review(db, ctx, "review", listing.id, scope_key="replay:facts")
    assert db.query(ListingReviewDecision).count() == 1


def test_stale_or_forged_agent_output_is_not_saved(case):
    db, ctx, _, listing, _, _ = case
    with ListingReviewAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        output = agent.review(listing.id)
    output["_review_analysis"]["decision"] = "rejected"
    with pytest.raises(ActionError, match="已变化"):
        finalize_reviews(db, ctx, [output], "forged", [listing.id])
    assert db.query(ListingReviewDecision).count() == 0


def test_cross_tenant_product_and_atomic_invalid_batch(case):
    db, ctx, _, listing, product, _ = case
    with pytest.raises(ActionError):
        invoke_review(db, ctx, "review_batch", {"listing_ids": [listing.id, 999999]}, {}, scope_key="bad:batch")
    assert db.query(ListingReviewDecision).count() == 0
    tenant = Tenant(name="外租户")
    db.add(tenant)
    db.flush()
    product.tenant_id = tenant.id
    db.commit()
    with pytest.raises(ActionError, match="不存在"):
        invoke_review(db, ctx, "review", listing.id)


def test_manual_approval_resumes_same_scope_but_new_high_risk_blocks(case):
    db, ctx, _, listing, _, pack = case
    pack.rules = {**pack.rules, "manual_categories": ["家居"]}
    approver = User(tenant_id=ctx.legacy_tenant_id, username="review-compliance", password_hash="unused",
                    role="compliance_approver")
    db.add(approver)
    db.commit()
    first = invoke_review(db, ctx, "review", listing.id, scope_key="manual:resume")
    assert first["decision"] == "manual_required"
    approval_ctx = resolve_workspace_context(db, approver)
    assert not approval_ctx.has("listing:write")
    current = invoke_review(db, approval_ctx, "review", listing.id, approval=True)
    human = approve_review_output(db, approval_ctx, listing.id, "已核对资质", current["review_id"])
    assert human["human_override"] and "_persistence" not in human["evidence"]
    resumed = invoke_review(db, ctx, "review", listing.id, scope_key="manual:resume")
    assert resumed["decision"] == "approved"
    assert invoke_review(db, ctx, "review", listing.id, scope_key="manual:resume") == resumed
    db.add(ComplianceReport(tenant_id=ctx.legacy_tenant_id, target_type="listing",
                            listing_id=listing.id, risk_level="high", score=0))
    db.commit()
    with pytest.raises(ActionError):
        invoke_review(db, ctx, "review", listing.id, scope_key="manual:resume")
    with pytest.raises(ActionError):
        approve_review_output(db, approval_ctx, listing.id, "强制放行", resumed["review_id"])


def test_workflow_uses_trusted_requester_and_stable_empty_range(case):
    db, ctx, user, listing, _, _ = case
    context = {"listing_ids": [listing.id], "_action_requested_by": user.id, "_action_scope": "wf:review"}
    result = run_step("listing_review", "review_batch", ctx.legacy_tenant_id, {"listing_ids": []}, context)
    assert result["approved"] == [] and db.query(ListingReviewDecision).count() == 0
    context.update(result["context_patch"])
    with pytest.raises(ActionError, match="范围已变化"):
        run_step("listing_review", "review_batch", ctx.legacy_tenant_id, {"listing_ids": [listing.id]}, context)
    result = run_step("listing_review", "review_batch", ctx.legacy_tenant_id, {}, {
        "listing_ids": [listing.id], "_action_scope": "wf:missing"})
    assert result["business_status"] == "blocked"


def test_step_review_manifest_is_local():
    from types import SimpleNamespace

    step = SimpleNamespace(id=2, agent="listing_review", action="review_batch", output={})
    assert "_action_review_manifest" not in _step_context({"_action_review_manifest": {"scope": "other"}}, 1, step)
    step.output = {"context_patch": {"_action_review_manifest": {"scope": "workflow:1:step:2", "listing_ids": []}}}
    assert _step_context({}, 1, step)["_action_review_manifest"]["listing_ids"] == []


def test_publish_execution_detects_same_version_rule_or_report_change(case):
    db, ctx, _, listing, _, pack = case
    invoke_review(db, ctx, "review", listing.id)
    publish_facts(db, ctx.legacy_tenant_id, listing.id)
    pack.rules = {**pack.rules, "manual_categories": ["家居"]}
    db.commit()
    with pytest.raises(ActionError, match="已变化"):
        publish_facts(db, ctx.legacy_tenant_id, listing.id)


def test_publish_batch_rechecks_and_explicit_empty_is_not_expanded(case):
    db, ctx, _, listing, _, _ = case
    empty = invoke_listing(db, ctx, "publish_batch", {"listing_ids": []}, {"listing_ids": [listing.id]})
    assert empty["published"] == [] and empty["pending"] == []
    result = invoke_listing(db, ctx, "publish_batch", {}, {"listing_ids": [listing.id]}, scope_key="wf:publish")
    assert len(result["pending"]) == 1 and result["published"] == []
    assert db.query(ListingReviewDecision).count() == 1
    assert db.query(AiAction).one().approval_required
    assert listing.status == "draft"


def test_rule_sync_runs_outside_agent_and_failure_blocks(case, monkeypatch):
    db, ctx, _, listing, _, _ = case
    monkeypatch.setenv("ERP_RULES_URL", "https://example.invalid/test-only")
    calls = []

    def fail_sync(rules_db, platform, *, before_apply):
        assert rules_db is not db
        before_apply()
        calls.append(platform)
        return {"error": "mocked sync failure"}

    monkeypatch.setattr("app.services.review_outputs.check_updates", fail_sync)
    result = invoke_review(db, ctx, "review", listing.id)
    assert calls == [listing.platform]
    assert result["decision"] == "manual_required" and "mocked sync failure" in str(result["reasons"])


@pytest.mark.parametrize("field", ["source", "key", "scope", "listing_ids", "snapshot_sha", "workspace_id", "requested_by"])
def test_replay_rejects_tampered_origin_metadata(case, field):
    db, ctx, _, listing, _, _ = case
    result = invoke_review(db, ctx, "review", listing.id, scope_key="origin:tamper")
    row = db.get(ListingReviewDecision, result["review_id"])
    row.evidence = {**row.evidence, "_persistence": {**row.evidence["_persistence"], field: "tampered"}}
    db.commit()
    with pytest.raises(ActionError):
        invoke_review(db, ctx, "review", listing.id, scope_key="origin:tamper")
    assert db.query(ListingReviewDecision).count() == 1


def test_sync_failure_is_new_risk_but_specific_human_confirmation_is_preserved(case, monkeypatch):
    db, ctx, _, listing, _, _ = case
    first = invoke_review(db, ctx, "review", listing.id, scope_key="sync:changing")
    assert first["decision"] == "approved"
    monkeypatch.setenv("ERP_RULES_URL", "https://example.invalid/mock")
    monkeypatch.setattr("app.services.review_outputs.check_updates", lambda *a, **k: {"error": "mock offline"})
    with pytest.raises(ActionError):
        invoke_review(db, ctx, "review", listing.id, scope_key="sync:changing")
    approver = User(tenant_id=ctx.legacy_tenant_id, username="offline-reviewer", password_hash="unused",
                    role="compliance_approver")
    db.add(approver)
    db.commit()
    approver_ctx = resolve_workspace_context(db, approver)
    manual = invoke_review(db, approver_ctx, "review", listing.id, approval=True)
    assert manual["decision"] == "manual_required"
    approve_review_output(db, approver_ctx, listing.id, "人工核对当前规则资料", manual["review_id"])
    confirmed = invoke_review(db, ctx, "review", listing.id, scope_key="sync:confirmed")
    assert confirmed["decision"] == "approved"
    publish_facts(db, ctx.legacy_tenant_id, listing.id)


def test_remote_rule_fetch_revocation_prevents_shared_pack_write(case, monkeypatch):
    db, ctx, user, listing, _, pack = case
    monkeypatch.setenv("ERP_RULES_URL", "https://example.invalid/mock")
    old_version = pack.version

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"platform": listing.platform, "version": "2099-01-01", "source_url": "https://example.com/new",
                     "rules": {"title_max": 100, "desc_max": 3000, "image_min": 1, "image_max": 5,
                               "banned_words": [], "banned_categories": []}}]

    def fetch(*args, **kwargs):
        user.role = "viewer"
        db.commit()
        return Reply()

    monkeypatch.setattr("app.services.platform_rules.httpx.get", fetch)
    with pytest.raises(ActionError, match="缺少权限"):
        invoke_review(db, ctx, "review", listing.id)
    assert db.query(PlatformRulePack).count() == 1 and db.get(PlatformRulePack, pack.id).version == old_version
    assert db.query(ListingReviewDecision).count() == 0
