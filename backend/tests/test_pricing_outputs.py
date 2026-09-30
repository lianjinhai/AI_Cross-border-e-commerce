"""定价分析记录接管：无财务 Action、原子落库、事务锁去重。"""

import ast
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.orchestrator import invoke_pricing
from app.agents.pricing import PricingAgent
from app.db import Base, SessionLocal
from app.models import AiAction, PricingRecord, Product, Tenant, User
from app.serialize import to_dict
from app.services.ai_actions import ActionError
from app.services.pricing_outputs import finalize_pricing_output
from app.services.workspace_context import resolve_workspace_context

from . import test_action_system as action_cases


@pytest.fixture
def case():
    yield from action_cases.case.__wrapped__()


def analysis(product_id, suggested=20.0):
    record = {"product_id": product_id, "purchase_cost": 8.0, "logistics_cost": 4.0,
              "platform_fee_rate": 0.06, "ads_cost": 2.0, "price": 25.0,
              "suggested_price": suggested, "profit": 20.0, "margin": 0.8,
              "currency": "USD", "model": "rule",
              "reason": {"strategy": "隔离探针", "floor": 10, "target": 20}}
    return {**record, "id": None, "created_at": None, "_analysis_record": record}


def test_pricing_agent_has_no_business_orm_writes_or_action_proposals():
    source = Path(__file__).resolve().parents[1] / "app/agents/pricing.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    pricing = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == "PricingAgent")
    forbidden = {"add", "add_all", "flush", "commit", "delete", "execute", "query", "get", "propose"}
    calls = [node for node in ast.walk(pricing) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr in forbidden
             and (isinstance(node.func.value, ast.Name) and node.func.value.id == "self"
                  or isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "db")]
    assert not calls, "PricingAgent 只能返回分析，不能写业务 ORM 或产出 Action"


def test_analysis_is_persisted_once_without_changing_price_or_tenant(case):
    db, ctx, _, product, _ = case
    before_product, before_tenant = to_dict(product), to_dict(db.get(Tenant, product.tenant_id))
    item = analysis(product.id)
    assert db.query(PricingRecord).count() == 0
    first = finalize_pricing_output(db, ctx, item, "workflow:1:step:pricing")
    replay = finalize_pricing_output(db, ctx, analysis(product.id, 30), "workflow:1:step:pricing")
    assert first == replay and first["suggested_price"] == 20
    assert first["id"] and first["created_at"] and "_analysis_record" not in first
    metadata = first["reason"]["_persistence"]
    assert metadata["requested_by"] == ctx.user_id and metadata["workspace_id"] == ctx.workspace_id
    assert metadata["agent_type"] == "pricing"
    assert db.query(PricingRecord).count() == 1 and db.query(AiAction).count() == 0
    assert to_dict(db.get(Product, product.id)) == before_product
    assert to_dict(db.get(Tenant, product.tenant_id)) == before_tenant
    fresh = finalize_pricing_output(db, ctx, item, "new-request")
    assert fresh["id"] != first["id"] and db.query(PricingRecord).count() == 2


@pytest.mark.parametrize("patch", [{"suggested_price": float("nan")}, {"price": float("inf")},
                                   {"platform_fee_rate": 1}, {"purchase_cost": -1},
                                   {"price": True}, {"currency": "CNY"},
                                   {"reason": {"_persistence": {"key": "forged"}}},
                                   {"reason": {"floor": float("nan")}}, {"model": []}])
def test_invalid_analysis_is_not_persisted(case, patch):
    db, ctx, _, product, _ = case
    item = analysis(product.id)
    item["_analysis_record"].update(patch)
    with pytest.raises(ActionError):
        finalize_pricing_output(db, ctx, item, "invalid")
    assert db.query(PricingRecord).count() == db.query(AiAction).count() == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_llm_price_falls_back_to_rule(monkeypatch, value):
    agent = PricingAgent.__new__(PricingAgent)
    agent.tenant_id, agent.db = 1, None
    monkeypatch.setattr("app.agents.pricing._tool_product", lambda *args: {
        "title": "Rule price", "attrs": {"sale_price": 25}})
    monkeypatch.setattr("app.agents.pricing._tool_cost_elements", lambda *args: {
        "fx": 7, "fee_rate": 0.06, "purchase_cny": 8, "logistics_cny": 4, "ads_cny": 2})
    monkeypatch.setattr("app.agents.pricing._tool_score", lambda *args: None)
    monkeypatch.setattr("app.agents.pricing._setting_for", lambda *args: {
        "min_margin": 0.1, "target_margin": 0.3})
    monkeypatch.setattr(agent, "ask_json", lambda *args, **kwargs: ({"suggested_price": value}, "llm"))
    result = agent.suggest_price(1)
    assert result["model"] == "rule" and math.isfinite(result["suggested_price"])
    assert result["suggested_price"] > 0 and "_action_proposal" not in result


def test_foreign_target_and_revoked_permissions_fail_closed(case):
    db, ctx, user, product, _ = case
    tenant = Tenant(name="foreign analysis")
    db.add(tenant)
    db.flush()
    foreign = Product(tenant_id=tenant.id, title="foreign", sku="pricing-foreign")
    db.add(foreign)
    db.commit()
    with pytest.raises(ActionError, match="不存在"):
        finalize_pricing_output(db, ctx, analysis(foreign.id), "foreign")
    user.role = "viewer"
    db.commit()
    with pytest.raises(ActionError, match="权限"):
        finalize_pricing_output(db, ctx, analysis(product.id), "revoked")
    assert db.query(PricingRecord).count() == 0


@pytest.mark.parametrize("change", ["disabled", "expired", "suspended"])
def test_pricing_revalidates_current_user_and_workspace_license(case, change):
    db, ctx, user, product, _ = case
    if change == "disabled":
        user.status = "disabled"
    else:
        tenant = db.get(Tenant, product.tenant_id)
        if change == "expired":
            tenant.license_until = datetime.utcnow() - timedelta(seconds=1)
        else:
            tenant.status = "suspended"
    db.commit()
    with pytest.raises(ActionError):
        finalize_pricing_output(db, ctx, analysis(product.id), "stale-identity")
    assert db.query(PricingRecord).count() == db.query(AiAction).count() == 0


def test_batch_analysis_keeps_errors_and_blocks_without_fabricating_results(case, monkeypatch):
    db, ctx, _, product, _ = case

    def suggest(self, pid):
        if pid != product.id:
            raise ValueError("商品不存在")
        return analysis(pid)

    monkeypatch.setattr(PricingAgent, "suggest_price", suggest)
    result = invoke_pricing(db, ctx, "reprice_batch", {"product_ids": [product.id, 999999]}, {},
                            scope_key="partial-batch")
    assert result["business_status"] == "blocked"
    assert result["errors"] == [{"product_id": 999999, "error": "商品不存在"}]
    assert len(result["repriced"]) == db.query(PricingRecord).count() == 1
    replay = invoke_pricing(db, ctx, "reprice_batch", {"product_ids": [product.id, 999999]}, {},
                            scope_key="partial-batch")
    assert result == replay and db.query(PricingRecord).count() == 1
    empty = invoke_pricing(db, ctx, "reprice_batch", {"product_ids": []}, {}, scope_key="empty")
    assert empty["repriced"] == [] and empty["context_patch"]["pricing_record_ids"] == []


def test_batch_insert_is_atomic_on_late_failure(case, monkeypatch):
    db, ctx, _, product, _ = case
    second = Product(tenant_id=product.tenant_id, title="second", sku="PRICING-2")
    db.add(second)
    db.commit()
    original = db.flush
    count = 0

    def fail(*args, **kwargs):
        nonlocal count
        if any(isinstance(row, PricingRecord) for row in db.new):
            count += 1
            if count == 2:
                raise RuntimeError("第二条写入故障")
        return original(*args, **kwargs)

    monkeypatch.setattr(db, "flush", fail)
    output = {"repriced": [analysis(product.id), analysis(second.id)]}
    with pytest.raises(RuntimeError, match="写入故障"):
        finalize_pricing_output(db, ctx, output, "atomic-batch")
    assert db.query(PricingRecord).count() == 0
    result = finalize_pricing_output(db, ctx, output, "atomic-batch")
    assert len(result["context_patch"]["pricing_record_ids"]) == 2


def test_orchestrator_and_workflow_persist_analysis_with_trusted_context(case, monkeypatch):
    from app.workflows import engine

    db, ctx, user, product, _ = case
    monkeypatch.setattr(PricingAgent, "suggest_price", lambda self, pid: analysis(pid))
    item = invoke_pricing(db, ctx, "suggest_price", product.id, scope_key="api-analysis")
    assert item["id"] and db.query(AiAction).count() == 0
    monkeypatch.setattr(engine, "SessionLocal", lambda: db)
    params = {"product_ids": [product.id]}
    tenant_id, user_id = user.tenant_id, user.id
    blocked = engine.run_step("pricing", "reprice_batch", tenant_id, params, {})
    assert blocked["business_status"] == "blocked"
    trusted = {"_action_requested_by": user_id, "_action_scope": "workflow:1:step:1"}
    first = engine.run_step("pricing", "reprice_batch", tenant_id, params, trusted)
    replay = engine.run_step("pricing", "reprice_batch", tenant_id, params, trusted)
    assert first == replay and first["business_status"] == "success"
    assert first["context_patch"]["pricing_record_ids"] == [first["repriced"][0]["id"]]
    assert db.query(PricingRecord).count() == 2 and db.query(AiAction).count() == 0


def test_concurrent_same_scope_creates_only_one_analysis(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'pricing.db').as_posix()}",
                           connect_args={"timeout": 10, "check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="concurrent pricing")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="pricing-user", password_hash="unused", role="admin")
        product = Product(tenant_id=tenant.id, title="concurrent", sku="concurrent")
        db.add_all([user, product])
        db.commit()
        ctx, product_id = resolve_workspace_context(db, user), product.id
    barrier = Barrier(2)

    def persist():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return finalize_pricing_output(db, ctx, analysis(product_id), "concurrent")["id"]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: persist(), range(2)))
        assert results[0] == results[1]
        with Session(engine) as db:
            assert db.query(PricingRecord).count() == 1 and db.query(AiAction).count() == 0
    finally:
        engine.dispose()


def test_pricing_http_and_chat_return_real_records_without_actions(client, auth_headers):
    product = client.post("/api/products", headers=auth_headers, json={
        "title": "Pricing artifact product", "attrs": {"sale_price": 25, "supplier_price": 8}}).json()
    with SessionLocal() as db:
        db.get(Product, product["id"]).status = "active"
        db.commit()
    response = client.post("/api/pricing/suggest", headers=auth_headers,
                           json={"product_id": product["id"]})
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["id"] and record["created_at"] and "_analysis_record" not in record
    chat = client.post("/api/ai/chat", headers=auth_headers, json={"message": "定价分析"})
    assert chat.status_code == 200 and chat.json()["intent"] == "pricing", chat.text
    assert chat.json()["data"] and all(row["id"] for row in chat.json()["data"])
    chat_record = next(row for row in chat.json()["data"] if row["product_id"] == product["id"])
    assert chat_record["id"] != record["id"] and "_analysis_record" not in chat_record
    detail = client.get("/api/pricing", headers=auth_headers,
                        params={"product_id": product["id"]}).json()
    assert any(row["id"] == record["id"] for row in detail["items"])
    assert len(detail["items"]) == 2
    with SessionLocal() as db:
        assert db.query(AiAction).filter_by(agent_type="pricing").count() == 0
    actual = client.get(f"/api/products/{product['id']}", headers=auth_headers)
    assert actual.status_code == 200 and actual.json()["attrs"]["sale_price"] == 25
