"""选品分析产物：隔离、不可变重放、真实口径和真实入口。"""

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.discovery import DiscoveryAgent
from app.agents.orchestrator import invoke_discovery
from app.db import Base, SessionLocal
from app.models import (
    AiAction,
    AiDecision,
    Order,
    Product,
    ProductPerformance,
    ProductScore,
    RefundOrder,
    Tenant,
    User,
)
from app.services.ai_actions import ActionError
from app.services.discovery_outputs import finalize_discovery_scores
from app.services.product_performance import read_performance
from app.services.workspace_context import resolve_workspace_context


@pytest.fixture
def case(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="选品产物探针")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="scoring-owner", password_hash="unused", role="admin")
        product = Product(tenant_id=tenant.id, sku="SCORE-1", title="Desk organizer", category="家居",
                          status="active", attrs={"sale_price": 20, "supplier_price": 8})
        db.add_all([user, product])
        db.commit()
        monkeypatch.setattr("app.agents.base.SessionLocal", lambda: Session(engine))
        monkeypatch.setattr("app.tools.audit._session_factory", lambda: Session(engine))
        monkeypatch.setattr(DiscoveryAgent, "ask_json", lambda self, *a, **kw: (kw["fallback"](), "rule"))
        yield db, resolve_workspace_context(db, user), user, product
    engine.dispose()


def analysis(pid, value=60):
    record = {"product_id": pid, "reasons": ["测试依据"], "model": "llm",
              **dict.fromkeys(("demand", "competition", "profit", "risk", "total"), value)}
    return {"_score_analysis": record, "_score_evidence": {"performance_source": "not_used"}}


def test_agent_only_analyzes_without_scores_decisions_or_cache(case):
    db, ctx, _, product = case
    with DiscoveryAgent(product.tenant_id, context=ctx) as agent:
        output = agent.score_product(product.id)
        empty = agent.pick_candidates(explicit_ids=[])
    assert output["_score_evidence"]["performance_source"] == "real_orders"
    assert output["_score_evidence"]["performance_score"] == 50
    assert empty["items"] == []
    assert db.query(ProductScore).count() == db.query(AiDecision).count() == db.query(ProductPerformance).count() == 0
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app/agents/discovery.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DiscoveryAgent")
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name != "scan_trends"]
    assert not [n for m in methods for n in ast.walk(m) if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Attribute) and n.value.attr == "db"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 101, True])
def test_invalid_llm_scores_fall_back_and_artifact_rejects_invalid(case, monkeypatch, value):
    db, ctx, _, product = case
    monkeypatch.setattr(DiscoveryAgent, "ask_json", lambda *a, **kw: (
        analysis(product.id, value)["_score_analysis"], "llm"))
    with DiscoveryAgent(product.tenant_id, context=ctx) as agent:
        output = agent.score_product(product.id)
    assert output["model"] == "rule" and 0 <= output["total"] <= 100
    with pytest.raises(ActionError):
        finalize_discovery_scores(db, ctx, [analysis(product.id, value)], "invalid")
    assert db.query(ProductScore).count() == 0


def test_atomic_persistence_original_replay_and_no_business_action(case, monkeypatch):
    db, ctx, _, product = case
    first = invoke_discovery(db, ctx, "score_product", product.id, scope_key="stable")
    monkeypatch.setattr(DiscoveryAgent, "score_product", lambda *a: pytest.fail("恢复不应重算"))
    assert invoke_discovery(db, ctx, "score_product", product.id, scope_key="stable") == first
    decision = db.query(AiDecision).one()
    assert decision.evidence["_persistence"]["score_id"] == first["score_id"]
    assert db.query(AiAction).count() == db.query(ProductPerformance).count() == 0
    assert db.get(Product, product.id).attrs["sale_price"] == 20
    with pytest.raises(ActionError):
        finalize_discovery_scores(db, ctx, [analysis(product.id), analysis(999999)], "atomic")
    assert db.query(ProductScore).count() == db.query(AiDecision).count() == 1
    db.get(ProductScore, first["score_id"]).reasons = ["人工改动"]
    db.commit()
    with pytest.raises(ActionError, match="内容已变化"):
        invoke_discovery(db, ctx, "score_product", product.id, scope_key="stable")


def test_permission_revocation_foreign_target_and_forged_metadata(case):
    db, ctx, user, product = case
    tenant = Tenant(name="外租户")
    db.add(tenant)
    db.flush()
    foreign = Product(tenant_id=tenant.id, sku="FOREIGN", title="外租户商品")
    db.add(foreign)
    db.commit()
    with pytest.raises(ActionError):
        finalize_discovery_scores(db, ctx, [analysis(foreign.id)], "foreign")
    item = analysis(product.id)
    item["_score_evidence"]["_persistence"] = {"score_id": 1}
    with pytest.raises(ActionError):
        finalize_discovery_scores(db, ctx, [item], "forged")
    user.role = "viewer"
    db.commit()
    with pytest.raises(ActionError):
        invoke_discovery(db, ctx, "score_product", product.id)
    assert db.query(ProductScore).count() == 0


def test_blocked_batch_is_atomic_and_empty_range_never_expands(case):
    db, ctx, _, product = case
    output = invoke_discovery(db, ctx, "score_batch", [product.id, 999999], scope_key="batch")
    assert output["business_status"] == "blocked" and output["errors"]
    assert output["context_patch"] == {} and db.query(ProductScore).count() == 0
    assert invoke_discovery(db, ctx, "pick_candidates", 3, 0, True, [])["items"] == []


def test_demo_refunds_and_foreign_orders_do_not_pollute_real_performance(case):
    db, _, _, product = case
    real = Order(tenant_id=product.tenant_id, external_no="REAL", platform="shopee", product_id=product.id,
                 source="manual", status="paid", qty=2, amount=40, profit=10)
    demo = Order(tenant_id=product.tenant_id, external_no="DEMO", platform="shopee", product_id=product.id,
                 source="demo", status="paid", qty=100, amount=9000, profit=9000)
    db.add_all([real, demo])
    db.flush()
    db.add(RefundOrder(tenant_id=product.tenant_id, refund_no="DEMO-REFUND", order_id=demo.id, status="refunded"))
    tenant = Tenant(name="污染订单租户")
    db.add(tenant)
    db.flush()
    foreign = Order(tenant_id=tenant.id, external_no="FOREIGN", platform="shopee", product_id=product.id,
                    source="api", status="paid", qty=800, amount=90000, profit=80000)
    db.add(foreign)
    db.flush()
    db.add(RefundOrder(tenant_id=product.tenant_id, refund_no="FOREIGN-REFUND",
                       order_id=foreign.id, status="refunded"))
    db.commit()
    out = read_performance(db, product.tenant_id, product.id)
    assert out["units_sold"] == 2 and out["revenue"] == 40 and out["refund_rate"] == 0
    assert db.query(ProductPerformance).count() == 0
    real.qty = 5
    db.commit()
    assert read_performance(db, product.tenant_id, product.id)["units_sold"] == 5
    db.add(RefundOrder(tenant_id=product.tenant_id, refund_no="REAL-REFUND",
                       order_id=real.id, status="refunded"))
    db.commit()
    assert read_performance(db, product.tenant_id, product.id)["refund_rate"] == 1


def test_llm_evidence_never_claims_unused_real_order_inputs(case, monkeypatch):
    db, ctx, _, product = case
    monkeypatch.setattr(DiscoveryAgent, "ask_json", lambda *a, **kw: (
        analysis(product.id)["_score_analysis"], "llm"))
    monkeypatch.setattr("app.tools.product.read_performance", lambda *a: pytest.fail("LLM 分支未使用经营聚合"))
    result = invoke_discovery(db, ctx, "score_product", product.id)
    assert result["model"] == "llm"
    assert db.query(AiDecision).one().evidence["performance_source"] == "not_used"


def test_rule_records_actual_fallback_trend_and_rejects_foreign_evidence(case):
    from app.models import MarketTrend

    db, ctx, _, product = case
    trend = MarketTrend(tenant_id=product.tenant_id, keyword="unrelated trend", platform="google",
                        search_volume=1000, growth_30d=10, competition=20)
    db.add(trend)
    db.commit()
    invoke_discovery(db, ctx, "score_product", product.id)
    assert db.query(AiDecision).one().evidence["trend_id"] == trend.id
    tenant = Tenant(name="趋势外租户")
    db.add(tenant)
    db.flush()
    foreign = MarketTrend(tenant_id=tenant.id, keyword="foreign", platform="google")
    db.add(foreign)
    db.commit()
    item = analysis(product.id)
    item["_score_evidence"]["trend_id"] = foreign.id
    with pytest.raises(ActionError):
        finalize_discovery_scores(db, ctx, [item], "foreign-trend")


def test_permission_is_rechecked_after_model_generation(case, monkeypatch):
    db, ctx, user, product = case

    def revoked(*args):
        user.role = "viewer"
        db.commit()
        return analysis(product.id)

    monkeypatch.setattr(DiscoveryAgent, "score_product", revoked)
    with pytest.raises(ActionError):
        invoke_discovery(db, ctx, "score_product", product.id)
    assert db.query(ProductScore).count() == db.query(AiDecision).count() == 0


def test_concurrent_scope_persists_one_immutable_score(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "scores.sqlite").as_posix(),
                           connect_args={"check_same_thread": False, "timeout": 20})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="并发选品")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="parallel-score", password_hash="x", role="admin")
        product = Product(tenant_id=tenant.id, sku="PARALLEL", title="并发商品")
        db.add_all([user, product])
        db.commit()
        uid, pid = user.id, product.id
    barrier = Barrier(2)

    def persist(value):
        with Session(engine) as db:
            ctx = resolve_workspace_context(db, db.get(User, uid))
            barrier.wait(timeout=10)
            return finalize_discovery_scores(db, ctx, [analysis(pid, value)], "parallel")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(persist, v) for v in (30, 80)]
        rows = [future.result(timeout=30) for future in futures]
    assert rows[0] == rows[1]
    with Session(engine) as db:
        assert db.query(ProductScore).count() == db.query(AiDecision).count() == 1
    engine.dispose()


def test_http_workflow_and_chat_preserve_public_contract(client, auth_headers):
    from app.models import WorkflowTemplate

    pid = client.get("/api/products", headers=auth_headers).json()["items"][0]["id"]
    response = client.post(f"/api/discovery/score/{pid}", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["score_id"] and not any(k.startswith("_") for k in response.json())
    with SessionLocal() as db:
        product = db.get(Product, pid)
        db.add(WorkflowTemplate(tenant_id=product.tenant_id, key="score-flow", name="选品评分闭环",
            steps=[{"agent": "discovery", "action": "pick_candidates", "params": {"product_ids": [pid]}}]))
        db.commit()
    response = client.post("/api/workflows/run", headers=auth_headers,
                           json={"template_key": "score-flow"})
    assert response.status_code == 200 and response.json()["status"] == "success", response.text
    assert response.json()["steps"][0]["output"]["picked_product_ids"] == [pid]
    response = client.post("/api/ai/chat", headers=auth_headers, json={"message": "帮我选品"})
    assert response.status_code == 200, response.text


def test_workflow_failed_explicit_scoring_keeps_range_without_partial_records(client, auth_headers):
    from app.models import WorkflowTemplate

    pid = client.get("/api/products", headers=auth_headers).json()["items"][0]["id"]
    with SessionLocal() as db:
        product = db.get(Product, pid)
        before = db.query(ProductScore).filter_by(product_id=pid).count()
        db.add(WorkflowTemplate(tenant_id=product.tenant_id, key="score-blocked", name="评分原子阻断",
            steps=[{"agent": "discovery", "action": "pick_candidates", "params": {}}]))
        db.commit()
    ids = [pid, 99999999]
    response = client.post("/api/workflows/run", headers=auth_headers,
        json={"template_key": "score-blocked", "context": {"product_ids": ids}})
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["status"] == "blocked" and first["context"]["product_ids"] == ids
    response = client.post(f"/api/workflows/runs/{first['id']}/resume", headers=auth_headers)
    assert response.status_code == 200 and response.json()["status"] == "blocked", response.text
    with SessionLocal() as db:
        assert db.query(ProductScore).filter_by(product_id=pid).count() == before
