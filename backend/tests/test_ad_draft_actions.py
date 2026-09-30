"""广告草稿提案化闭环：独立内存库，不调用投放平台。"""

import ast
from pathlib import Path

import pytest

from app.agents.orchestrator import invoke_ad_drafts
from app.agents.pricing import AdsAgent
from app.models import AdCampaign, AiAction, Product, Tenant
from app.services.action_system import HANDLERS, execute_action, submit_action
from app.services.ai_actions import ActionError

from . import test_action_system as action_cases


@pytest.fixture
def case():
    yield from action_cases.case.__wrapped__()


def proposal(product_id):
    return {"action_type": "CREATE_AD_CAMPAIGN_DRAFT", "target_type": "product",
            "target_id": product_id, "reason": "只创建本地草稿，不启动投放",
            "payload": {"name": "Desk 广告", "platform": "facebook",
                        "keywords": ["desk"], "budget": 50.0}}


def test_ads_agent_has_no_business_orm_writes():
    path = Path(__file__).resolve().parents[1] / "app/agents/pricing.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ads = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AdsAgent")
    calls = [node for node in ast.walk(ads) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "db"]
    assert not calls, "AdsAgent 不得直接读取或写入业务 ORM"


def test_ad_draft_executor_is_idempotent_and_never_activates_campaign(case):
    db, ctx, _, product, _ = case
    action = submit_action(db, ctx, "ads", proposal(product.id), "draft-step")
    assert action.risk_level == "LOW" and action.execution_mode == "AUTO_SAFE"
    assert not action.approval_required and db.query(AdCampaign).count() == 0
    assert submit_action(db, ctx, "ads", proposal(product.id), "draft-step").id == action.id
    assert execute_action(db, ctx, action.id).status == "SUCCESS"
    row = db.query(AdCampaign).one()
    assert row.product_id == product.id and row.status == "draft" and row.budget == 50
    assert row.spend == row.revenue == row.impressions == row.clicks == row.orders == 0
    assert execute_action(db, ctx, action.id).outcome["result"]["id"] == row.id
    assert db.query(AdCampaign).count() == db.query(AiAction).count() == 1


@pytest.mark.parametrize("patch", [{"budget": 0}, {"budget": 501}, {"budget": True},
                                   {"keywords": "desk"}, {"keywords": []},
                                   {"status": "running"}, {"spend": 20}])
def test_invalid_ad_payload_fails_without_business_writes(case, patch):
    db, ctx, _, product, _ = case
    data = proposal(product.id)
    data["payload"].update(patch)
    action = submit_action(db, ctx, "ads", data, "invalid")
    result = execute_action(db, ctx, action.id)
    assert result.status == "FAILED" and result.outcome["error"]
    assert db.query(AdCampaign).count() == 0


def test_ad_draft_revalidates_permissions_and_target_ownership(case):
    db, ctx, user, product, _ = case
    tenant = Tenant(name="foreign")
    db.add(tenant)
    db.flush()
    other = Product(tenant_id=tenant.id, title="foreign", sku="foreign")
    db.add(other)
    db.commit()
    with pytest.raises(ActionError):
        submit_action(db, ctx, "ads", proposal(other.id), "foreign")
    action = submit_action(db, ctx, "ads", proposal(product.id), "revoke")
    user.role = "viewer"
    db.commit()
    with pytest.raises(ActionError):
        execute_action(db, ctx, action.id)
    assert db.query(AdCampaign).count() == 0


def test_ad_draft_rolls_back_partial_insert(case, monkeypatch):
    db, ctx, _, product, _ = case
    handler = HANDLERS["CREATE_AD_CAMPAIGN_DRAFT"]

    def fail(session, action, payload):
        handler(session, action, payload)
        raise ValueError("隔离回滚探针")

    monkeypatch.setitem(HANDLERS, "CREATE_AD_CAMPAIGN_DRAFT", fail)
    action = submit_action(db, ctx, "ads", proposal(product.id), "rollback")
    assert execute_action(db, ctx, action.id).status == "FAILED"
    assert db.query(AdCampaign).count() == 0


def test_orchestrator_finalizes_drafts_and_replays_same_scope(case, monkeypatch):
    db, ctx, _, product, _ = case

    def suggest(self, product_id, platform):
        return {**proposal(product_id)["payload"], "product_id": product_id,
                "status": "draft", "reason": "隔离广告草稿"}

    monkeypatch.setattr(AdsAgent, "suggest_for_product", suggest)
    params = {"product_ids": [product.id]}
    first = invoke_ad_drafts(db, ctx, params, {}, scope_key="workflow:1:step:1")
    replay = invoke_ad_drafts(db, ctx, params, {}, scope_key="workflow:1:step:1")
    assert first == replay and first["business_status"] == "success"
    assert first["context_patch"]["campaign_ids"] == [db.query(AdCampaign).one().id]
    assert "_action_proposal" not in first["campaign_drafts"][0]
    assert db.query(AdCampaign).count() == db.query(AiAction).count() == 1


def test_explicit_empty_ad_batch_does_not_fan_out(case, monkeypatch):
    db, ctx, _, _, _ = case

    def forbidden(*args, **kwargs):
        raise AssertionError("空的显式范围不允许读取全量商品")

    monkeypatch.setattr("app.agents.pricing._tool_published_product_ids", forbidden)
    for params, context in [({"product_ids": []}, {}), ({}, {"published_product_ids": []}),
                            ({}, {"product_ids": []}), ({"product_ids": None}, {}),
                            ({}, {"published_product_ids": None}), ({}, {"product_ids": None})]:
        result = invoke_ad_drafts(db, ctx, params, context, scope_key="empty")
        assert result["campaign_drafts"] == [] and result["context_patch"]["campaign_ids"] == []
    assert db.query(AdCampaign).count() == db.query(AiAction).count() == 0


def test_workflow_ad_step_requires_trusted_actor_and_uses_action_gateway(case, monkeypatch):
    from app.workflows import engine

    db, _, user, product, _ = case
    monkeypatch.setattr(engine, "SessionLocal", lambda: db)
    monkeypatch.setattr(AdsAgent, "suggest_for_product", lambda self, pid, platform: {
        **proposal(pid)["payload"], "product_id": pid, "status": "draft", "reason": "工作流探针"})
    params = {"product_ids": [product.id]}
    tenant_id, user_id = user.tenant_id, user.id
    blocked = engine.run_step("ads", "draft_batch", tenant_id, params, {})
    assert blocked["business_status"] == "blocked"
    trusted = {"_action_requested_by": user_id, "_action_scope": "workflow:probe:step:ads"}
    first = engine.run_step("ads", "draft_batch", tenant_id, params, trusted)
    replay = engine.run_step("ads", "draft_batch", tenant_id, params, trusted)
    assert first == replay and first["campaign_drafts"][0]["action_status"] == "SUCCESS"
    assert db.query(AdCampaign).count() == db.query(AiAction).count() == 1
