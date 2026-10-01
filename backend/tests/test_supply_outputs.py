"""供应链域可信产物服务（services/supply_outputs）隔离测试：评分 / 预测 / 私域工厂机会扫描。

§18.3 第 3 步：Agent 经 Tool 层读取并产出只读提案，写入由本服务在服务端校验后
原子保存。本文件覆盖（仿 test_compliance_outputs）：
  * 评分保存（服务端校验 + 租户隔离）
  * 预测保存（含 commercial_gate 服务端重算兼容）
  * scan 原子批次（成功 / 失败整批回滚）
  * 人工报价保护（整行拒绝覆盖）
  * 三个派发入口（invoke_supplier / invoke_factory_opportunity / 聊天 _do_suppliers）
    与 Workflow 两个步骤（("supplier","forecast_batch")、("factory_opportunity",
    "scan_private_supply_batch")）经可信身份派发
  * Agent 源码无 ORM 写断言

全部使用隔离内存库，零真实外网、零主库写入。
"""
import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.factory_opportunity import FactoryOpportunityAgent
from app.agents.orchestrator import (
    OrchestratorAgent,
    invoke_factory_opportunity,
    invoke_supplier,
)
from app.db import Base
from app.models import (
    ForecastSnapshot,
    OpportunitySupplierMatch,
    Order,
    Product,
    Supplier,
    SupplierCatalogProduct,
    SupplierOffer,
    SupplierScore,
    Tenant,
    User,
)
from app.services.ai_actions import ActionError
from app.services.supply_outputs import (
    finalize_forecast,
    finalize_forecast_batch,
    finalize_scan_private_supply_batch,
    finalize_supplier_scores,
)
from app.services.workspace_context import resolve_workspace_context
from app.workflows.engine import run_step


@pytest.fixture
def case(monkeypatch):
    """自带富探针租户（供应商 + 报价 + 订单 + 目录 + 高可信预测），夹具内建内删。

    同时覆盖评分 / 预测 / scan 三种可信保存所需的读取数据，使 `invoke_*` 与
    `run_step` 能走通「Agent 只读提案 → 可信服务原子保存」全链路（规范 T-2）。
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="供应链可信保存隔离探针")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="supply-probe", password_hash="x", role="owner")
        db.add(user)
        # 跨租户隔离用的第二租户与商品 / 供应商。
        other = Tenant(name="供应链隔离对照租户")
        db.add(other)
        db.flush()
        product_other = Product(tenant_id=other.id, sku="OTHER-1", title="对照商品",
                                status="active", attrs={"sale_price": 50.0})
        db.add(product_other)
        supplier_other = Supplier(tenant_id=other.id, name="对照供应商", region="x",
                                  rating=4.0, ship_days=6, stability=80.0,
                                  verification_status="verified", capabilities=["服装"])
        db.add(supplier_other)

        product = Product(tenant_id=tenant.id, sku="SUP-OUT-1",
                          title="私域工厂针织衫", category="服装", status="active",
                          attrs={"onhand": 50, "sale_price": 120.0, "weight_kg": 0.3,
                                 "platform": "shopee", "country": "CN", "material": "cotton"})
        db.add(product)
        db.flush()
        supplier = Supplier(tenant_id=tenant.id, name="探针针织厂", region="石狮",
                            rating=4.5, ship_days=5, stability=85.0,
                            verification_status="verified", capabilities=["服装", "针织"])
        db.add(supplier)
        db.flush()
        db.add(SupplierOffer(tenant_id=tenant.id, supplier_id=supplier.id,
                             product_id=product.id, price=30.0, currency="CNY",
                             moq=10, ship_days=5, in_stock=True))
        now = datetime.utcnow()
        for days_ago, qty in ((7, 20), (14, 15), (21, 18), (28, 12), (35, 16)):
            db.add(Order(tenant_id=tenant.id, platform="shopee",
                         external_no="SUP-OUT-%d" % days_ago, product_id=product.id,
                         qty=qty, amount=100.0, currency="USD", status="paid",
                         source="api", created_at=now - timedelta(days=days_ago)))
        catalog = SupplierCatalogProduct(
            tenant_id=tenant.id, supplier_id=supplier.id, factory_sku="F-SUP-1",
            title="私域工厂针织衫", category="服装", capabilities=["服装", "针织"],
            images=["https://cdn.example.com/f.jpg"], unit_price=30.0, currency="CNY",
            moq=10, lead_days=5, monthly_capacity=1000, available_qty=500,
            status="active", confirmed_at=now - timedelta(days=1))
        db.add(catalog)
        db.add(ForecastSnapshot(tenant_id=tenant.id, product_id=product.id,
                                version="probe-v1",
                                training_cutoff=now - timedelta(days=1),
                                selected_model="probe", point_forecast=50.0,
                                confidence="high"))
        db.commit()

        for name in ("app.agents.base.SessionLocal", "app.tools.audit._session_factory",
                     "app.workflows.engine.SessionLocal"):
            monkeypatch.setattr(name, lambda: Session(engine))
        yield db, resolve_workspace_context(db, user), user, product, supplier, catalog
    engine.dispose()


# ---------------------------------------------------------- Agent 源码无 ORM 写

def test_agent_source_has_no_orm_write():
    """棘轮反向断言：两个供应链 Agent 源码不得出现任何 `.db` 属性（即无 ORM 写/读）。

    与 test_agent_layer_boundaries 的 AST 棘轮互为表里：此处直接从测试侧证明
    迁移后 Agent 内已无任何 `self.db` 直连（读取走 Tool、写入走可信服务）。
    """
    agents_dir = Path(__file__).resolve().parent.parent / "app" / "agents"
    for name in ("supplier.py", "factory_opportunity.py"):
        tree = ast.parse((agents_dir / name).read_text(encoding="utf-8"))
        assert not any(isinstance(node, ast.Attribute) and node.attr == "db"
                       for node in ast.walk(tree)), "%s 仍含 .db 直连" % name


# ---------------------------------------------------------- 供应商评分保存

def test_finalize_supplier_scores_saves_and_validates(case):
    """评分保存：合法提案落库含 score_id；越界分值 / 非法类型 / 跨租户均显式拒绝。"""
    db, ctx, _, product, supplier, _ = case
    proposal = {"supplier_id": supplier.id, "quality": 90.0, "cost": 80.0,
                "delivery": 70.0, "stability": 85.0, "total": 82.0,
                "reasons": ["平台评分高"], "model": "rule"}
    saved = finalize_supplier_scores(db, ctx, [proposal], "supply:score:1")
    assert len(saved) == 1 and saved[0]["score_id"]
    assert db.query(SupplierScore).filter(
        SupplierScore.tenant_id == ctx.legacy_tenant_id).count() == 1

    # 分值越界（total > 100）服务端校验拒绝。
    bad = dict(proposal, total=150.0)
    with pytest.raises(ActionError, match="评分数值无效"):
        finalize_supplier_scores(db, ctx, [bad], "supply:score:2")

    # 模型非法拒绝。
    with pytest.raises(ActionError, match="评分模型无效"):
        finalize_supplier_scores(db, ctx, [dict(proposal, model="gpt")], "supply:score:3")

    # 跨租户供应商拒绝（404）。
    from app.models import Supplier as S2
    from app.models import Tenant as T2
    other_t = T2(name="跨租户评分")
    db.add(other_t)
    db.flush()
    other_s = S2(tenant_id=other_t.id, name="外租户供应商", region="x",
                 rating=4.0, ship_days=6, stability=80.0)
    db.add(other_s)
    db.commit()
    with pytest.raises(ActionError, match="评分供应商不存在"):
        finalize_supplier_scores(db, ctx, [dict(proposal, supplier_id=other_s.id)],
                                 "supply:score:4")


def test_finalize_supplier_scores_requires_write_permission(case):
    """权限闸：无 supply:write 的调用方被拒绝（ActionError），不落库。"""
    db, ctx, user, _, _, _ = case
    user.role = "viewer"
    db.commit()
    vctx = resolve_workspace_context(db, user)
    assert not vctx.has("supply:write")
    with pytest.raises(ActionError):
        finalize_supplier_scores(db, vctx,
                                 [{"supplier_id": 1, "quality": 1, "cost": 1,
                                   "delivery": 1, "stability": 1, "total": 1,
                                   "reasons": [], "model": "rule"}], "scope")
    assert db.query(SupplierScore).count() == 0


# ---------------------------------------------------------- 销量预测保存

def _score_snapshot(product_id, confidence="high"):
    now = datetime.utcnow()
    return {"product_id": product_id, "version": "demand-v2.0",
            "training_cutoff": now, "target_start": now, "target_end": now + timedelta(days=7),
            "dimensions": {"sku": "SUP-OUT-1", "platform": "shopee", "country": "CN"},
            "features": {"sale_price": 120.0}, "candidates": [],
            "selected_model": "weighted_moving_average", "point_forecast": 40.0,
            "lower_bound": 30.0, "upper_bound": 50.0, "wape": 0.2, "bias": 0.05,
            "confidence": confidence}


def test_finalize_forecast_saves_with_commercial_gate(case):
    """预测保存：响应兼容前端，含 snapshot_id / version / training_cutoff /
    commercial_gate，且 automation_allowed 由服务端重算（不信任 Agent 传入）。"""
    db, ctx, _, product, _, _ = case
    proposal = {"product_id": product.id, "weekly_demand": 40.0,
                "_snapshot": _score_snapshot(product.id, confidence="high")}
    result = finalize_forecast(db, ctx, product.id, proposal, "supply:forecast:1")
    assert result["snapshot_id"]
    assert result["version"] == "demand-v2.0"
    assert result["training_cutoff"].endswith("Z")
    assert isinstance(result["commercial_gate"], dict) and "passed" in result["commercial_gate"]
    # automation_allowed 由服务端按「置信度 == high 且 商用门禁通过」重算，
    # 不信任 Agent 传入；本用例快照置信度 high，故等于 gate.passed。
    assert result["automation_allowed"] == ("high" == proposal["_snapshot"]["confidence"]
                                            and result["commercial_gate"]["passed"])
    assert db.query(ForecastSnapshot).filter(
        ForecastSnapshot.tenant_id == ctx.legacy_tenant_id).count() == 2  # 预置1 + 新1


def test_finalize_forecast_validation_rejects_bad_snapshot(case):
    """预测保存：product_id 不匹配 / 缺 training_cutoff 均显式拒绝。"""
    db, ctx, _, product, _, _ = case
    # product_id 与入参不一致。
    with pytest.raises(ActionError, match="预测提案无效"):
        finalize_forecast(db, ctx, product.id,
                         {"_snapshot": _score_snapshot(product.id + 999)}, "scope")
    # 缺 training_cutoff。
    bad = _score_snapshot(product.id)
    bad.pop("training_cutoff")
    with pytest.raises(ActionError, match="预测训练截止时间无效"):
        finalize_forecast(db, ctx, product.id, {"_snapshot": bad}, "scope")


def test_finalize_forecast_batch_is_tolerant(case):
    """批量预测：单条失败跳过（保持宽容语义），仅成功项落库。"""
    db, ctx, _, product, _, _ = case
    good = {"product_id": product.id, "_snapshot": _score_snapshot(product.id)}
    bad = {"product_id": product.id + 999, "_snapshot": _score_snapshot(product.id + 999)}
    results = finalize_forecast_batch(db, ctx, [good, bad], "supply:fb:1")
    assert len(results) == 1 and results[0]["snapshot_id"]
    # 预置快照(1) + 成功保存(1) = 2；失败项未落库。
    assert db.query(ForecastSnapshot).filter(
        ForecastSnapshot.tenant_id == ctx.legacy_tenant_id).count() == 2


# ---------------------------------------------------------- 私域工厂机会扫描原子批次

def _match(product_id, supplier_id, catalog_id, write_offer=True, price=30.0,
           in_stock=True, total=80.0):
    return {"product_id": product_id, "supplier_id": supplier_id,
            "catalog_product_id": catalog_id, "capability_score": 70.0,
            "readiness_score": 60.0, "total_score": total,
            "matched_capabilities": ["服装"], "gaps": [],
            "write_offer": write_offer,
            "offer": ({"price": price, "currency": "CNY", "moq": 10,
                       "ship_days": 5, "in_stock": in_stock} if write_offer else None),
            "forecast_point": 50.0, "available_qty": 500, "monthly_capacity": 1000}


def test_scan_atomic_success_and_ready(case):
    """scan 整批成功：匹配落库、报价落库、同事务内 calc_profit 取最低采购价、
    利润率达标即置 ready；整批单次提交。"""
    db, ctx, _, product, supplier, catalog = case
    proposal = {"catalog_present": True, "skipped": None,
                "product_ids": [product.id],
                "matches": [_match(product.id, supplier.id, catalog.id)]}
    out = finalize_scan_private_supply_batch(db, ctx, {"min_margin": 0.15}, proposal,
                                             "supply:scan:1")
    assert out["ready"] == 1
    match = out["candidates"][0]
    assert match["decision"] == "ready"
    assert match["expected_margin"] is not None and match["expected_margin"] >= 0.15
    assert db.query(OpportunitySupplierMatch).filter(
        OpportunitySupplierMatch.tenant_id == ctx.legacy_tenant_id).count() == 1
    # 报价由 trusted 服务写入（in_stock=True 供 calc_profit 取价）。
    offer = db.query(SupplierOffer).filter(
        SupplierOffer.tenant_id == ctx.legacy_tenant_id,
        SupplierOffer.supplier_id == supplier.id,
        SupplierOffer.product_id == product.id).one()
    assert offer.price == 30.0 and offer.in_stock is True


def test_scan_atomic_rollback_on_tenant_violation(case):
    """scan 整批回滚：任一条目跨租户，整批不落库（约束 #3：失败整批回滚、显式上抛）。"""
    db, ctx, _, product, supplier, catalog = case
    from app.models import Product as P2
    from app.models import Tenant as T2
    other_t = T2(name="scan回滚对照")
    db.add(other_t)
    db.flush()
    other_p = P2(tenant_id=other_t.id, sku="SCAN-OTHER", title="对照", status="active",
                 attrs={"sale_price": 60.0})
    db.add(other_p)
    db.commit()
    proposal = {"catalog_present": True, "skipped": None,
                "product_ids": [product.id, other_p.id],
                "matches": [
                    _match(product.id, supplier.id, catalog.id, write_offer=False),
                    # 第二条商品属外租户 -> 租户隔离校验抛 404 -> 整批回滚。
                    _match(other_p.id, supplier.id, catalog.id, write_offer=False),
                ]}
    with pytest.raises(ActionError, match="机会扫描商品不存在"):
        finalize_scan_private_supply_batch(db, ctx, {}, proposal, "supply:scan:rb")
    # 第一条虽已 flush，但整批回滚，一条都不留。
    assert db.query(OpportunitySupplierMatch).filter(
        OpportunitySupplierMatch.tenant_id == ctx.legacy_tenant_id).count() == 0


def test_scan_protects_manual_offer_whole_row_reject(case):
    """人工报价保护：已存在的人工/既有报价整行拒绝覆盖，保留原行、不新增行。

    策略=整行拒绝覆盖（见 supply_outputs 模块文档）：supplier_offers 无来源列，
    无法区分人工录入与历史 Agent 录入，故整行跳过写入以满足硬约束。

    注：case 夹具已为 (supplier, product) 预置一条在库报价（price=30），即扮演
    「人工/既有流程录入」角色；扫描不得覆盖它，也不得新增第二行。
    """
    db, ctx, _, product, supplier, catalog = case
    prior_price = db.query(SupplierOffer).filter(
        SupplierOffer.tenant_id == ctx.legacy_tenant_id,
        SupplierOffer.supplier_id == supplier.id,
        SupplierOffer.product_id == product.id).one().price

    proposal = {"catalog_present": True, "skipped": None,
                "product_ids": [product.id],
                "matches": [_match(product.id, supplier.id, catalog.id)]}
    out = finalize_scan_private_supply_batch(db, ctx, {"min_margin": 0.15}, proposal,
                                             "supply:scan:manual")
    # 原报价未被覆盖（仍是夹具预置价），且未新增第二行。
    offers = db.query(SupplierOffer).filter(
        SupplierOffer.tenant_id == ctx.legacy_tenant_id,
        SupplierOffer.supplier_id == supplier.id,
        SupplierOffer.product_id == product.id).all()
    assert len(offers) == 1 and offers[0].price == prior_price
    # 匹配仍建立，但 gap 标注「人工/既有流程录入」，证明扫描整行拒绝覆盖。
    cand = out["candidates"][0]
    assert any("人工或既有流程录入" in g for g in cand["gaps"])


# ---------------------------------------------------------- 可信身份派发入口

def test_invoke_supplier_score_and_forecast(case):
    """路由等价入口：invoke_supplier 绑定可信身份，Agent 出只读提案、可信服务落库。"""
    db, ctx, _, product, supplier, _ = case
    scored = invoke_supplier(db, ctx, "score_supplier", supplier.id, scope_key="s1")
    assert "total" in scored and scored["score_id"]
    assert db.query(SupplierScore).filter(
        SupplierScore.tenant_id == ctx.legacy_tenant_id).count() == 1

    fc = invoke_supplier(db, ctx, "forecast", product.id, scope_key="f1")
    assert fc["snapshot_id"] and "commercial_gate" in fc and "automation_allowed" in fc


def test_invoke_supplier_forecast_batch(case):
    """路由等价入口：forecast_batch 经可信身份派发并保存每条快照。"""
    db, ctx, _, product, _, _ = case
    out = invoke_supplier(db, ctx, "forecast_batch", {}, {}, scope_key="fb1")
    assert "forecasts" in out and out["forecasts"]
    assert db.query(ForecastSnapshot).filter(
        ForecastSnapshot.tenant_id == ctx.legacy_tenant_id).count() >= 2


def test_invoke_factory_opportunity_dispatch(case):
    """路由等价入口：invoke_factory_opportunity 调度扫描并原子保存匹配/报价。"""
    db, ctx, _, product, supplier, _ = case
    out = invoke_factory_opportunity(db, ctx, {"product_ids": [product.id]}, {},
                                     scope_key="fo1")
    assert out["candidates"]
    assert db.query(OpportunitySupplierMatch).filter(
        OpportunitySupplierMatch.tenant_id == ctx.legacy_tenant_id).count() == 1


def test_chat_entry_scores_via_trusted_dispatch(case, monkeypatch):
    """聊天入口（_do_suppliers）：经可信身份派发 invoke_supplier，而非 Agent 直写。

    通过替换 supply Tool 让 _do_suppliers 拿到候选供应商，断言其调用 invoke_supplier
    并产出评分（score_id 由可信服务写入，证明路由已迁移到可信派发）。
    """
    db, ctx, user, product, supplier, _ = case
    from app.agents import orchestrator as orch

    real_invoke = orch.invoke_supplier
    captured = {}

    def spy(db, c, method, *args, scope_key=None):
        captured["method"] = method
        return real_invoke(db, c, method, *args, scope_key=scope_key)

    monkeypatch.setattr(orch, "invoke_supplier", spy)

    agent = OrchestratorAgent(ctx.legacy_tenant_id, context=ctx)
    # 让 _do_suppliers 经 supply Tool 拿到该供应商。
    agent.tool = lambda name: type("T", (), {
        "call": lambda *a, **k: type("R", (), {"ok": True, "data": [
            {"id": supplier.id, "name": supplier.name}]})()
    })()
    reply, intent, actions, data = agent._do_suppliers()
    assert captured.get("method") == "score_supplier"
    assert data and data[0]["supplier_id"] == supplier.id


# ---------------------------------------------------------- Workflow 可信派发

def test_workflow_supplier_forecast_batch_dispatch(case):
    """Workflow 步骤 ("supplier","forecast_batch") 经可信身份派发落库。"""
    db, ctx, user, product, _, _ = case
    out = run_step("supplier", "forecast_batch", ctx.legacy_tenant_id, {},
                   {"_action_requested_by": user.id, "_action_scope": "wf:1:step:1"})
    assert "forecasts" in out and out["forecasts"]
    assert db.query(ForecastSnapshot).filter(
        ForecastSnapshot.tenant_id == ctx.legacy_tenant_id).count() >= 2


def test_workflow_factory_opportunity_scan_dispatch(case):
    """Workflow 步骤 ("factory_opportunity","scan_private_supply_batch") 经可信身份派发落库。"""
    db, ctx, user, product, _, _ = case
    out = run_step("factory_opportunity", "scan_private_supply_batch",
                   ctx.legacy_tenant_id, {"product_ids": [product.id]},
                   {"_action_requested_by": user.id, "_action_scope": "wf:2:step:1"})
    assert out["candidates"]
    assert db.query(OpportunitySupplierMatch).filter(
        OpportunitySupplierMatch.tenant_id == ctx.legacy_tenant_id).count() == 1


def test_scan_without_catalog_keeps_product_scope(case):
    """无私域工厂目录时不得清空商品范围（回归 D57）。

    曾在该分支返回 ``product_ids=[]``，被可信服务写进 context_patch，覆盖工作流
    上下文里上游（标准化）确定的商品范围，导致后续合规 / Listing 步骤无目标、
    自动铺货工作流误判为 success（真实用例 test_workflow_auto_listing 反序失败）。
    无目录时语义应为「不改范围」，与旧实现的空 context_patch 等价。
    """
    db, ctx, user, product, _supplier, _catalog = case
    # 删掉本租户目录，模拟「尚未维护私域工厂目录」。
    db.query(SupplierCatalogProduct).filter(
        SupplierCatalogProduct.tenant_id == ctx.legacy_tenant_id).delete()
    db.commit()
    with FactoryOpportunityAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        proposal = agent.scan_private_supply_batch({"product_ids": [product.id]}, {})
    assert proposal["catalog_present"] is False
    assert proposal["product_ids"] == [product.id]
    # 经 Workflow 可信派发后的 context_patch 也必须保留商品范围。
    out = run_step("factory_opportunity", "scan_private_supply_batch",
                   ctx.legacy_tenant_id, {"product_ids": [product.id]},
                   {"_action_requested_by": user.id, "_action_scope": "wf:9:step:1"})
    assert out["candidates"] == []
    assert out["context_patch"]["product_ids"] == [product.id]
