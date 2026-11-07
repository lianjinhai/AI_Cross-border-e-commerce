"""M2-A 核价契约：报价轮次（只增不改）、低价门禁、越权、成本变动重阻断。

为什么这些用例值得写：
    核价最容易出的错不是算错数，而是**把试算当成已核价**、或用「接受」绕过低价门禁。
    因此这里除了正例，重点覆盖：低价必须阻断且**一行都不许写**、历史不许被覆盖、
    成本一变旧轮次立刻失效、只读角色不能报价。

全部在隔离测试库运行，不触碰业务主库，也不向任何平台发送报价（本批无核价适配器）。
"""

import uuid

import pytest

from app.db import SessionLocal
from app.models import (
    Listing,
    ListingReviewDecision,
    PriceRound,
    Product,
    ProductAsset,
    Shop,
    Supplier,
    SupplierOffer,
    User,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
    WorkflowTemplate,
)
from app.services import pricing_rounds
from app.services.workspace_context import resolve_workspace_context
from app.workflows.launch_access import LaunchError
from app.workflows.launch_actions import execute_launch_action
from app.workflows.launch_records import create_launch
from app.workflows.launch_runtime import refresh_launch
from app.workflows.profiles import create_profile, publish_profile

PLATFORM = "priceprobe"
HIGH_PRICE = 99.0     # 远高于成本，必然过 15% 毛利门槛
LOW_PRICE = 1.0       # 远低于成本，必然被低价门禁挡住


def _profile(key, version=1):
    """本地契约流程：资料 -> 平台核价 -> 价格确认 -> 监控（不含平台往返）。"""
    return {
        "profile_key": key, "version": version, "name": "核价本地契约样本",
        "description": "本地核价验证，不代表真实平台接入。",
        "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
        "platform": PLATFORM, "market": "SG", "fulfillment_mode": "DROPSHIP",
        "category_scope": ["ANY"], "status_mapping": {"unknown": "BLOCK", "statuses": {}},
        "steps": [
            {"step_code": "INFORMATION", "step_name": "商品资料", "business_type": "DATA_PREPARATION",
             "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 0, "required": True,
             "dependencies": [], "available_actions": ["COMPLETE_DATA"],
             "evidence_requirements": ["INFORMATION_EVIDENCE"],
             "completion_condition": {"all": [{"present": "product.title"},
                                              {"asset_rights_allowed": "PUBLISHABLE"}]}},
            {"step_code": "PRICE_REVIEW", "step_name": "平台核价", "business_type": "PRICE_REVIEW",
             "execution_mode": "EXTERNAL_WAIT", "actor": "PLATFORM", "sequence": 1, "required": True,
             "dependencies": ["INFORMATION"], "available_actions": ["REPORT_PRICE"],
             "evidence_requirements": ["PRICE_REVIEW_EVIDENCE"],
             "completion_condition": {"all": [{"present": "pricing.review_id"},
                                              {"cost_snapshot_current": "PRICE_REVIEW"}]}},
            {"step_code": "PRICE_DECISION", "step_name": "价格确认", "business_type": "HUMAN_DECISION",
             "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 2, "required": True,
             "dependencies": ["PRICE_REVIEW"],
             "available_actions": ["ACCEPT_PRICE", "COUNTER_PRICE", "ABANDON_PRODUCT"],
             "evidence_requirements": ["PRICE_DECISION_EVIDENCE"],
             "completion_condition": {"all": [{"eq": {"field": "pricing.decision", "value": "ACCEPT"}},
                                              {"cost_snapshot_current": "PRICE_REVIEW"}]}},
            # 契约要求「唯一且始终必需的在售核验节点」；本批不走到它，只为通过定义校验。
            {"step_code": "ACTIVATION", "step_name": "在售核验", "business_type": "PLATFORM_ACTIVATION",
             "execution_mode": "EXTERNAL_WAIT", "actor": "PLATFORM", "sequence": 3, "required": True,
             "dependencies": ["PRICE_DECISION"], "available_actions": ["CONFIRM_ACTIVATION"],
             "evidence_requirements": ["ACTIVATION_EVIDENCE"],
             "completion_condition": {"all": [{"eq": {"field": "platform.status", "value": "ACTIVE"}},
                                              {"verified_artifact": "ACTIVATION"},
                                              {"asset_rights_allowed": "PUBLISHABLE"}]}},
            {"step_code": "MONITORING", "step_name": "经营监控", "business_type": "MONITORING",
             "execution_mode": "SYSTEM_TASK", "actor": "SYSTEM", "sequence": 4, "required": False,
             "dependencies": ["ACTIVATION"],
             "completion_condition": {"eq": {"field": "monitoring.registered", "value": True}}},
        ],
    }


@pytest.fixture
def env(client):
    with SessionLocal() as db:
        users = {name: db.query(User).filter_by(username=name).one() for name in ("admin", "viewer")}
        contexts = {name: resolve_workspace_context(db, user) for name, user in users.items()}
        tenant = contexts["admin"].legacy_tenant_id
        product = Product(tenant_id=tenant, sku="price-round", title="核价商品",
                          category="家居", images=["https://example.com/main.jpg"],
                          attrs={"destination_country": "SG"}, hs_code="940360")
        shop = Shop(tenant_id=tenant, platform=PLATFORM, shop_name="Price Shop", market="SG",
                    fulfillment_mode="DROPSHIP", is_demo=True)
        db.add_all([product, shop])
        db.flush()
        # 复用已存在的供应商：测试库跨会话保留，重复插入会撞 uq_supplier_source。
        supplier = db.query(Supplier).filter_by(
            tenant_id=tenant, name="核价测试供应商", source_url="https://example.com/s").first()
        if supplier is None:
            supplier = Supplier(tenant_id=tenant, name="核价测试供应商",
                                source_url="https://example.com/s")
            db.add(supplier)
            db.flush()
        offer = SupplierOffer(tenant_id=tenant, product_id=product.id, supplier_id=supplier.id,
                             price=10.0, currency="CNY", in_stock=True, source_kind="manual",
                             verification_status="manual")
        db.add(offer)
        db.flush()
        product.selected_offer_id = offer.id
        db.add(ProductAsset(tenant_id=tenant, workspace_id=tenant, product_id=product.id,
                           asset_key="main", version=1, asset_type="MAIN_IMAGE",
                           uri=product.images[0], content_hash="b" * 64, rights_status="OWNED",
                           source="price round fixture", rights_evidence_ref="evidence://fixture/source",
                           market="SG", platform=PLATFORM, verification_status="MANUAL_REPORTED",
                           created_by=users["admin"].id))
        db.commit()
        # 每个用例一个独立 profile_key/version：唯一索引是 (tenant, profile_key, version)，
        # 复用会撞「同一流程版本已存在」。
        key = "PRICE_PROBE_" + uuid.uuid4().hex[:8].upper()
        profile = create_profile(db, contexts["admin"], _profile(key))
        publish_profile(db, contexts["admin"], profile.id, profile.definition_hash)
        db.commit()
        yield db, contexts, product, shop, offer
        db.rollback()
        _cleanup(db, tenant, product, shop, offer, key)


def _cleanup(db, tenant, product, shop, offer, key):
    run_ids = [row[0] for row in db.query(WorkflowRun.id).filter_by(product_id=product.id).all()]
    listing_ids = [row[0] for row in db.query(Listing.id).filter_by(product_id=product.id).all()]
    db.query(WorkflowRun).filter(WorkflowRun.product_id == product.id).update(
        {"previous_run_id": None}, synchronize_session=False)
    db.query(PriceRound).filter(PriceRound.product_id == product.id).delete(synchronize_session=False)
    if run_ids:
        db.query(WorkflowEvent).filter(WorkflowEvent.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(WorkflowStep).filter(WorkflowStep.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).delete(synchronize_session=False)
    if listing_ids:
        db.query(ListingReviewDecision).filter(
            ListingReviewDecision.product_id == product.id).delete(synchronize_session=False)
    db.query(Listing).filter(Listing.product_id == product.id).delete(synchronize_session=False)
    db.query(ProductAsset).filter(ProductAsset.product_id == product.id).delete(synchronize_session=False)
    db.query(WorkflowTemplate).filter(WorkflowTemplate.tenant_id == tenant,
                                      WorkflowTemplate.profile_key == key).delete(
        synchronize_session=False)
    # products.selected_offer_id 指向该报价：先解引用再删报价，否则 FK 拒绝删除。
    db.query(Product).filter(Product.id == product.id).update(
        {"selected_offer_id": None}, synchronize_session=False)
    db.flush()
    db.query(SupplierOffer).filter(SupplierOffer.id == offer.id).delete(synchronize_session=False)
    db.delete(product)
    db.delete(shop)
    db.commit()


def _run(db, run_id):
    return db.get(WorkflowRun, run_id, populate_existing=True)


def _refresh(db, ctx, run_id):
    run = _run(db, run_id)
    run, plan = refresh_launch(db, ctx, run_id, run.revision)
    db.commit()
    return run, plan


def _step_status(db, run_id, code):
    return db.query(WorkflowStep).filter_by(run_id=run_id, step_code=code).one().step_status


def _exec(db, ctx, run_id, action, step_code, key, payload=None):
    body = {"step_code": step_code, "payload": payload or {},
            "expected_revision": _run(db, run_id).revision}
    out = execute_launch_action(db, ctx, run_id, action, body, key)
    db.commit()
    return out


def _start(db, ctx, product, shop):
    run = create_launch(db, ctx, product.id, shop.id, "price-start-" + uuid.uuid4().hex[:8])
    db.commit()
    return run


def _reached_price_review(db, ctx, product, shop):
    """把流程推到 PRICE_REVIEW READY：资料完成是它唯一上游。"""
    run = _start(db, ctx, product, shop)
    _refresh(db, ctx, run.id)
    _exec(db, ctx, run.id, "COMPLETE_DATA", "INFORMATION", "cd-1")
    _refresh(db, ctx, run.id)
    assert _step_status(db, run.id, "PRICE_REVIEW") == "READY"
    return run


# ------------------------------------------------------------------ 正例

def test_report_price_records_a_round_and_completes_review(env):
    """正例：正常轮次 → 落一轮报价、核价步骤完成、回执带轮次与毛利。"""
    db, contexts, product, shop, _offer = env
    ctx = contexts["admin"]
    run = _reached_price_review(db, ctx, product, shop)

    out = _exec(db, ctx, run.id, "REPORT_PRICE", "PRICE_REVIEW", "rp-1",
                {"price": HIGH_PRICE, "currency": "USD", "note": "首轮申报"})

    rows = db.query(PriceRound).filter_by(product_id=product.id).all()
    assert len(rows) == 1
    row = rows[0]
    assert (row.round_no, row.action, row.price, row.currency) == (1, "REPORT", HIGH_PRICE, "USD")
    assert row.margin_ok is True and row.margin >= row.min_margin
    assert row.cost_fingerprint and row.cost_snapshot["purchase_cny"] > 0
    assert row.created_by is not None
    assert out["receipt"]["round_no"] == 1 and out["receipt"]["margin_ok"] is True
    # 明确写着没向平台发送，避免以后被读成「平台已核价」
    assert "未向平台发送报价" in out["receipt"]["note"]
    assert _step_status(db, run.id, "PRICE_REVIEW") == "COMPLETED"
    assert _step_status(db, run.id, "PRICE_DECISION") == "READY"


def test_accept_price_completes_decision_and_keeps_history(env):
    """还价再接受：轮次只增不改，决策留痕指向被接受的那一轮。"""
    db, contexts, product, shop, _offer = env
    ctx = contexts["admin"]
    run = _reached_price_review(db, ctx, product, shop)
    _exec(db, ctx, run.id, "REPORT_PRICE", "PRICE_REVIEW", "rp-2",
          {"price": HIGH_PRICE, "currency": "USD"})
    first = db.query(PriceRound).filter_by(product_id=product.id).order_by(PriceRound.id).first()
    first_snapshot = (first.price, first.round_no, first.cost_fingerprint)

    _refresh(db, ctx, run.id)
    _exec(db, ctx, run.id, "COUNTER_PRICE", "PRICE_DECISION", "cp-1",
          {"price": HIGH_PRICE + 10, "currency": "USD", "note": "还价 +10"})
    assert _step_status(db, run.id, "PRICE_DECISION") != "COMPLETED"   # 还价不算谈拢
    _exec(db, ctx, run.id, "ACCEPT_PRICE", "PRICE_DECISION", "ap-1", {"note": "同意"})

    rows = db.query(PriceRound).filter_by(product_id=product.id).order_by(PriceRound.id).all()
    assert [row.round_no for row in rows] == [1, 2, 3]
    assert [row.action for row in rows] == ["REPORT", "COUNTER", "ACCEPT"]
    # 历史不被覆盖：第一轮三个关键字段一字未动
    db.refresh(rows[0])
    assert (rows[0].price, rows[0].round_no, rows[0].cost_fingerprint) == first_snapshot
    accept = rows[-1]
    assert accept.decision["decision"] == "ACCEPT"
    assert accept.decision["source_round_id"] == rows[1].id   # 接受的是还价那一轮
    assert accept.decision["note"] == "同意"
    assert _step_status(db, run.id, "PRICE_DECISION") == "COMPLETED"


# ------------------------------------------------------------------ 反例

def test_low_price_is_blocked_and_writes_nothing(env):
    """反例：低价必须阻断，且**零写入**（不落轮次、revision 不变）。"""
    db, contexts, product, shop, _offer = env
    ctx = contexts["admin"]
    run = _reached_price_review(db, ctx, product, shop)
    revision_before = _run(db, run.id).revision

    with pytest.raises(LaunchError) as blocked:
        _exec(db, ctx, run.id, "REPORT_PRICE", "PRICE_REVIEW", "rp-low",
              {"price": LOW_PRICE, "currency": "USD"})

    assert blocked.value.code == "ACTION_PRECONDITION_FAILED"
    assert blocked.value.status_code == 409
    blocker = blocked.value.blockers[0]
    assert blocker["code"] == "PRICE_UNACCEPTABLE"
    assert "%" in blocker["message"]
    assert blocker["repair_action"]["path"] == "/app/pricing"
    assert blocker["repair_action"]["connected"] is True
    assert db.query(PriceRound).filter_by(product_id=product.id).count() == 0
    assert _run(db, run.id).revision == revision_before
    assert _step_status(db, run.id, "PRICE_REVIEW") == "READY"


def test_price_without_currency_is_rejected(env):
    """反例：金额没有币种就是错数——拒绝，不默认 USD。"""
    db, contexts, product, shop, _offer = env
    ctx = contexts["admin"]
    run = _reached_price_review(db, ctx, product, shop)
    with pytest.raises(LaunchError) as rejected:
        _exec(db, ctx, run.id, "REPORT_PRICE", "PRICE_REVIEW", "rp-nocur",
              {"price": HIGH_PRICE})
    assert rejected.value.code == "ACTION_PAYLOAD_INVALID"
    assert rejected.value.status_code == 422
    assert db.query(PriceRound).filter_by(product_id=product.id).count() == 0


def test_cost_change_invalidates_the_round(env):
    """成本一变，已完成的核价立刻重新阻断（不是一次性通过永久生效）。"""
    db, contexts, product, shop, offer = env
    ctx = contexts["admin"]
    run = _reached_price_review(db, ctx, product, shop)
    _exec(db, ctx, run.id, "REPORT_PRICE", "PRICE_REVIEW", "rp-cost",
          {"price": HIGH_PRICE, "currency": "USD"})
    assert _step_status(db, run.id, "PRICE_REVIEW") == "COMPLETED"

    offer.price = 400.0          # 供应商暴涨，成本快照作废
    db.commit()
    _refresh(db, ctx, run.id)

    step = db.query(WorkflowStep).filter_by(run_id=run.id, step_code="PRICE_REVIEW").one()
    assert step.step_status == "BLOCKED"
    assert "依据已失效" in step.blocking_reason["message"]
    assert pricing_rounds.snapshot_current(db, product.tenant_id, product.id,
                                           run_id=run.id, shop_id=shop.id) is False


# ------------------------------------------------------------------ 越权

def test_read_only_role_cannot_report_price(env):
    """越权：只读角色报价必须 403，且不产生轮次与事件。"""
    db, contexts, product, shop, _offer = env
    ctx = contexts["admin"]
    run = _reached_price_review(db, ctx, product, shop)
    events_before = db.query(WorkflowEvent).filter_by(run_id=run.id).count()

    with pytest.raises(LaunchError) as denied:
        _exec(db, contexts["viewer"], run.id, "REPORT_PRICE", "PRICE_REVIEW", "rp-viewer",
              {"price": HIGH_PRICE, "currency": "USD"})

    assert denied.value.code == "PERMISSION_DENIED"
    assert denied.value.status_code == 403
    assert db.query(PriceRound).filter_by(product_id=product.id).count() == 0
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == events_before


# ------------------------------------------------------------------ 服务层

def test_quote_requires_currency_and_positive_price(env):
    db, _contexts, product, _shop, _offer = env
    tenant = product.tenant_id
    with pytest.raises(pricing_rounds.PriceRoundError) as currency:
        pricing_rounds.quote(db, tenant, product.id, 10, "")
    assert currency.value.code == "CURRENCY_REQUIRED"
    with pytest.raises(pricing_rounds.PriceRoundError) as price:
        pricing_rounds.quote(db, tenant, product.id, 0, "USD")
    assert price.value.code == "PRICE_INVALID"
    # 币种大小写归一化，但不接受 2 位或数字
    assert pricing_rounds.normalize_currency("usd") == "USD"
    with pytest.raises(pricing_rounds.PriceRoundError):
        pricing_rounds.normalize_currency("US")


def test_margin_gate_uses_the_single_costing_implementation(env):
    """毛利口径必须来自 costing（不许在核价里再写一套公式）。"""
    db, _contexts, product, _shop, _offer = env
    tenant = product.tenant_id
    from app.services import costing

    quote = pricing_rounds.quote(db, tenant, product.id, HIGH_PRICE, "USD")
    baseline = costing.calc_profit(db, tenant, product.id, price=HIGH_PRICE)
    assert quote["margin"] == baseline["margin"]
    assert quote["min_margin"] == costing.setting_for(
        db, tenant, "rules", costing.DEFAULT_RULES)["min_margin"]
