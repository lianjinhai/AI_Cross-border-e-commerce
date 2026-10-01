"""合规报告与风险投影 Action：隔离数据库，零真实外网。"""

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.compliance import ComplianceAgent
from app.agents.orchestrator import invoke_compliance
from app.db import Base
from app.models import (
    AiAction,
    AiDecision,
    ComplianceReport,
    KnowledgeDoc,
    Listing,
    Product,
    Tenant,
    User,
    WorkflowRun,
    WorkflowStep,
)
from app.services.action_system import execute_action, submit_action
from app.services.ai_actions import ActionError
from app.services.compliance_analysis import rule_analysis
from app.services.compliance_outputs import finalize_compliance
from app.services.workspace_context import membership_table_available, resolve_workspace_context
from app.workflows.engine import _claim_run, _prepare_compliance_step, _step_context, run_step


@pytest.fixture
def case(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="合规投影隔离探针")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="compliance-probe", password_hash="unused", role="admin")
        product = Product(tenant_id=tenant.id, sku="COM-OUT", title="Organizer", status="active", images=["image.jpg"])
        db.add_all([user, product])
        db.flush()
        listing = Listing(tenant_id=tenant.id, product_id=product.id, platform="probe", title="Organizer",
                          description="Organizer", risk_level="low", status="draft")
        db.add(listing)
        db.commit()
        for name in ("app.agents.base.SessionLocal", "app.tools.audit._session_factory", "app.workflows.engine.SessionLocal"):
            monkeypatch.setattr(name, lambda: Session(engine))
        monkeypatch.setattr(ComplianceAgent, "ask_json", lambda self, *a, fallback, **k: (fallback(), "rule"))
        yield db, resolve_workspace_context(db, user), user, listing, product
    engine.dispose()


def analysis(case, target_type="listing", ref_id=None):
    _, ctx, _, listing, product = case
    with ComplianceAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        return agent.check(target_type, ref_id or (listing.id if target_type == "listing" else product.id))


def test_agent_no_business_orm_and_tool_analysis_only(case):
    db, _, _, _, _ = case
    tree = ast.parse((Path(__file__).parents[1] / "app/agents/compliance.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Attribute) and node.attr == "db" for node in ast.walk(tree))
    assert "_compliance_analysis" in analysis(case)
    assert db.query(ComplianceReport).count() == db.query(AiAction).count() == 0


def test_identity_schema_probe_preserves_uncommitted_transaction(case):
    db, ctx, _, _, product = case
    row = ComplianceReport(tenant_id=ctx.legacy_tenant_id, target_type="product", product_id=product.id)
    db.add(row)
    db.flush()
    assert membership_table_available(db) is False
    assert db.get(ComplianceReport, row.id, populate_existing=True) is row
    db.commit()
    assert db.query(ComplianceReport).count() == 1


def test_save_and_replay_report_and_action_without_publish(case):
    db, ctx, _, listing, _ = case
    first = invoke_compliance(db, ctx, "check_listing", listing.id, scope_key="same")
    second = invoke_compliance(db, ctx, "check_listing", listing.id, scope_key="same")
    assert first == second
    assert db.query(ComplianceReport).count() == db.query(AiAction).count() == db.query(AiDecision).count() == 1
    action = db.query(AiAction).one()
    assert (action.status, action.required_permission, action.risk_level, action.approval_required) == (
        "SUCCESS", "compliance:check", "LOW", False)
    assert listing.status == "draft" and listing.risk_level == first["risk_level"]
    assert action.outcome["before"] == "low"


def test_compliance_identity_can_check_without_ai_or_listing_write(case):
    db, _, user, listing, _ = case
    user.role = "compliance_approver"
    db.commit()
    ctx = resolve_workspace_context(db, user)
    assert not ctx.has("listing:write") and not ctx.has("ai:read")
    result = analysis((db, ctx, user, listing, case[4]))
    assert result["_compliance_analysis"]["basis"]["knowledge"]["mode"] == "not_used"
    saved = invoke_compliance(db, ctx, "check_listing", listing.id)
    assert saved["listing_id"] == listing.id and listing.status == "draft"


@pytest.mark.parametrize("bad", ["banana", float("nan"), float("inf"), "llm_low", "llm_high"])
def test_illegal_or_llm_only_risk_falls_back_to_rules(case, monkeypatch, bad):
    db, ctx, _, listing, _ = case
    if bad == "llm_low":
        listing.title = "Nike Organizer"
        db.commit()
    def fake(self, *args, fallback, **kwargs):
        result = dict(fallback())
        if bad == "banana":
            result["risk_level"] = bad
        elif bad in {"llm_low", "llm_high"}:
            result["risk_level"] = "low" if bad == "llm_low" else "high"
            result["score"] = 100 if bad == "llm_low" else 10
        else:
            result["score"] = bad
        return result, "llm"
    monkeypatch.setattr(ComplianceAgent, "ask_json", fake)
    result = analysis(case)["_compliance_analysis"]
    assert result["model"] == "rule"
    assert {key: result[key] for key in ("issues", "score", "risk_level", "suggestions")} == rule_analysis(result["basis"])
    assert result["risk_level"] == ("high" if bad == "llm_low" else "low")


@pytest.mark.parametrize("change", ["content", "product", "knowledge", "revocation"])
def test_fresh_inputs_and_identity_required(case, change):
    db, ctx, user, listing, product = case
    output = analysis(case)
    if change == "content":
        listing.title = "Nike"
    elif change == "product":
        product.title = "Changed product"
    elif change == "knowledge":
        db.add(KnowledgeDoc(tenant_id=ctx.legacy_tenant_id, title="商标黑名单", content="Organizer trademark 侵权"))
    else:
        user.role = "viewer"
    db.commit()
    with pytest.raises(ActionError):
        finalize_compliance(db, ctx, [output], "fresh", [{"target_type": "listing", "ref_id": listing.id}])
    assert db.query(ComplianceReport).count() == db.query(AiAction).count() == 0


def test_linked_product_cross_tenant_or_deleted_rejected(case):
    db, ctx, _, listing, product = case
    other = Tenant(name="other")
    db.add(other)
    db.flush()
    product.tenant_id = other.id
    db.commit()
    with pytest.raises(ActionError, match="关联商品不存在"):
        invoke_compliance(db, ctx, "check_listing", listing.id)


def test_batch_atomic_rollback_when_second_action_fails(case, monkeypatch):
    db, ctx, _, first, product = case
    first.title = "Nike"
    second = Listing(tenant_id=ctx.legacy_tenant_id, product_id=product.id, platform="probe", title="Adidas",
                     description="", risk_level="low", status="draft")
    db.add(second)
    db.commit()
    from app.services import action_system
    original = action_system.HANDLERS["UPDATE_LISTING_COMPLIANCE_RISK"]
    def fail_second(db, action, payload):
        if action.target_id == second.id:
            raise ActionError(409, "注入第二目标风险执行失败")
        return original(db, action, payload)
    monkeypatch.setitem(action_system.HANDLERS, "UPDATE_LISTING_COMPLIANCE_RISK", fail_second)
    with pytest.raises(ActionError, match="第二目标"):
        invoke_compliance(db, ctx, "check_batch", {"listing_ids": [first.id, second.id]}, {}, scope_key="atomic")
    db.expire_all()
    assert first.risk_level == second.risk_level == "low"
    assert db.query(ComplianceReport).count() == db.query(AiAction).count() == db.query(AiDecision).count() == 0


def test_scope_and_empty_range_are_stable(case):
    db, ctx, _, listing, product = case
    result = invoke_compliance(db, ctx, "check_batch", {"items": []}, {"listing_ids": [listing.id]}, scope_key="empty")
    assert result["reports"] == [] and db.query(ComplianceReport).count() == 0
    assert invoke_compliance(db, ctx, "check_batch", {"items": []}, {}, scope_key="empty") == result
    with pytest.raises(ActionError, match="清单已变化"):
        invoke_compliance(db, ctx, "check_batch", {"product_ids": [product.id]}, {}, scope_key="empty")


def test_old_low_action_cannot_replay_over_new_high_report(case):
    db, ctx, _, listing, _ = case
    invoke_compliance(db, ctx, "check_listing", listing.id, scope_key="low")
    action = db.query(AiAction).one()
    listing.title = "Nike"
    db.commit()
    high = invoke_compliance(db, ctx, "check_listing", listing.id, scope_key="high")
    assert high["risk_level"] == listing.risk_level == "high"
    with pytest.raises(ActionError, match="最新合规报告"):
        execute_action(db, ctx, action.id)
    assert listing.risk_level == "high"
    with pytest.raises(ActionError):
        invoke_compliance(db, ctx, "check_listing", listing.id, scope_key="low")


def test_no_synthetic_report_source_and_no_generic_atomic_for_other_actions(case):
    db, ctx, _, listing, product = case
    proposal = {"action_type": "UPDATE_LISTING_COMPLIANCE_RISK", "target_type": "listing",
                "target_id": listing.id, "payload": {"risk_level": "low"}}
    action = submit_action(db, ctx, "compliance", proposal, "forged")
    action = execute_action(db, ctx, action.id)
    assert action.status == "FAILED" and "载荷无效" in action.outcome["error"]
    with pytest.raises(ActionError, match="仅支持合规"):
        submit_action(db, ctx, "product", {"action_type": "UPDATE_PRODUCT_CONTENT", "target_type": "product",
            "target_id": product.id, "payload": {}}, "bad", commit=False)


def test_workflow_real_dispatch_and_step_manifest(case):
    db, ctx, user, listing, _ = case
    result = run_step("compliance", "check_batch", ctx.legacy_tenant_id, {"listing_ids": [listing.id]},
                      {"_action_requested_by": user.id, "_action_scope": "workflow:1:step:2"})
    assert result["reports"][0]["listing_id"] == listing.id
    from types import SimpleNamespace
    step = SimpleNamespace(id=2, agent="compliance", action="check_batch", output=result)
    scoped = _step_context({"_action_compliance_manifest": {"scope": "other"}}, 1, step)
    assert scoped["_action_compliance_manifest"] == result["context_patch"]["_action_compliance_manifest"]
    step.agent = "other"
    assert "_action_compliance_manifest" not in _step_context(scoped, 1, step)


def test_workflow_high_and_missing_identity_explicitly_block(case):
    db, ctx, user, listing, _ = case
    listing.title = "Nike"
    db.commit()
    result = run_step("compliance", "check_batch", ctx.legacy_tenant_id, {"listing_ids": [listing.id]},
                      {"_action_requested_by": user.id, "_action_scope": "high-workflow"})
    assert result["business_status"] == "blocked"
    assert result["context_patch"]["blocked_listing_ids"] == [listing.id]
    missing = run_step("compliance", "check_batch", ctx.legacy_tenant_id, {"listing_ids": [listing.id]}, {})
    assert missing["business_status"] == "blocked" and "发起者" in missing["reason"]


def test_failed_step_scope_is_saved_before_dispatch_and_empty_cannot_expand(case):
    db, ctx, _, listing, _ = case
    run = WorkflowRun(tenant_id=ctx.legacy_tenant_id, template_key="probe", name="scope", status="running")
    db.add(run)
    db.flush()
    step = WorkflowStep(tenant_id=ctx.legacy_tenant_id, run_id=run.id, seq=1, agent="compliance",
                        action="check_batch", params={"items": []}, status="running")
    db.add(step)
    db.commit()
    _prepare_compliance_step(db, {"listing_ids": [listing.id]}, run.id, step)
    original = step.output["context_patch"]["_action_compliance_manifest"]
    assert original["items"] == []
    step.params = {"listing_ids": [listing.id]}
    db.commit()
    _prepare_compliance_step(db, {}, run.id, step)
    assert step.output["context_patch"]["_action_compliance_manifest"] == original
    with pytest.raises(ActionError, match="范围已变化"):
        invoke_compliance(db, ctx, "check_batch", step.params, _step_context({}, run.id, step),
                          scope_key=original["scope"])


def test_claim_run_keeps_active_lease_and_claims_expired_lease(case):
    db, ctx, _, _, _ = case
    run = WorkflowRun(tenant_id=ctx.legacy_tenant_id, template_key="probe", name="lease", status="queued")
    db.add(run)
    db.commit()
    assert _claim_run(db, run.id, "first") == 1
    assert _claim_run(db, run.id, "second") == 0
    db.refresh(run)
    assert run.worker_id == "first"
    run.lease_until = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert _claim_run(db, run.id, "second") == 1
    db.refresh(run)
    assert run.worker_id == "second"
