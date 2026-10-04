"""上架合规闸门（publish_gate）与接入点测试。

背景（2026-10 P0）：65W 氮化镓充电器在美国站，因FCC(US) 关键词漏词导致
``check_evidence`` 返回 ``required=[]`` → 系统给出「无缺失、可上架」的**绿灯**；
同一件商品卖日本却被 PSE 正确拦下。误报绿灯比漏报更危险——运营会照绿灯上架
无认证商品，代价是下架甚至封店。

本模块锁定三件事：
    1. 闸门只读、且mode="warn" 下**绝不阻断**发布；
    2. 目的国解析不出来时**不得判定为通过**（沉默的绿灯最危险）；
    3. 三条发布路径（本地/demo/真实 API）都留下结构化 warn 日志。

隔离：服务级用例自建内存库（``create_all`` + 独立 Tenant），不碰业务主库。
"""
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    Listing,
    ListingReviewDecision,
    PlatformRulePack,
    Product,
    ProductComplianceEvidence,
    Shop,
    Tenant,
)
from app.services import publish_gate
from app.services.action_publish import publish_facts

# 与 test_review_fingerprint 同款的最小可发布世界：平台规则包 + 已通过复核。
_PLATFORM = "gate_probe"
_VERSION = "2026-10-02"


@pytest.fixture
def env():
    """内存库 + 独立租户 + 汇率。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="上架合规闸门探针")
        db.add(tenant)
        db.flush()
        yield db, tenant.id


def _charger(db, tenant_id, **kwargs) -> Product:
    """SKU-46048同款充电器：曾在美国站误报绿灯的那件商品。"""
    attrs = kwargs.pop("attrs", {})
    attrs.setdefault("source_desc", "GaN charger 65W USB-C power adapter")
    product = Product(tenant_id=tenant_id, sku=kwargs.pop("sku", "SKU-46048"),
                      status="active", category=kwargs.pop("category", "3C配件"),
                      title=kwargs.pop("title", "65W 氮化镓快充充电器"),
                      images=["https://cdn.example.com/charger.jpg"], attrs=attrs)
    db.add(product)
    db.commit()
    return product


# ---------------------------------------------------------------- 目的国解析
def test_destination_resolution_order_prefers_product_declaration(env):
    """商品显式声明的目的国优先于适配器 markets 默认站点。"""
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "JP"})
    assert publish_gate.resolve_destination(db, product, "ebay") == "JP"
    # 未声明时才回落到适配器 markets（eBay markets=["EBAY_US"] → US）
    fallback = _charger(db, tenant_id)
    assert publish_gate.resolve_destination(db, fallback, "ebay") == "US"
    assert publish_gate.resolve_destination(db, fallback, "shopee") == "SG"


def test_target_country_used_when_destination_country_absent(env):
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"target_country": "DE"})
    assert publish_gate.resolve_destination(db, product, "ebay") == "EU"


def test_unresolvable_destination_is_never_reported_as_pass(env):
    """解析不出目的国时必须 warn，**不得** pass（沉默的绿灯最危险）。"""
    db, tenant_id = env
    product = _charger(db, tenant_id)
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="unknown_platform")
    assert result["gate_status"] == publish_gate.GATE_WARN
    assert result["destination_country"] == ""
    assert "未声明目的国，无法校验目的国准入" in result["reasons"]


# ---------------------------------------------------------------- warn 语义
def test_missing_fcc_yields_warn_with_chinese_reasons(env):
    """核心场景：美国站充电器缺 FCC → warn + 可读原因，且不阻断。"""
    db, tenant_id = env
    product = _charger(db, tenant_id)
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
    assert result["gate_status"] == publish_gate.GATE_WARN
    assert result["destination_country"] == "US"
    assert "FCC" in result["required"] and "FCC" in result["missing"]
    assert any("缺少准入认证：FCC" in reason for reason in result["reasons"]), result
    assert result["mode"] == "warn"


def test_charger_does_not_require_battery_transport_evidence(env):
    """纯充电器不含电池：不得凭空要求 UN38.3（否则是另一种误导）。"""
    db, tenant_id = env
    product = _charger(db, tenant_id)
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
    assert "UN38.3" not in result["required"], result


def test_warn_mode_never_blocks_even_when_everything_is_missing(env):
    """mode="warn" 下绝不返回 block（阻断能力下一轮才开）。"""
    db, tenant_id = env
    product = _charger(db, tenant_id)
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay",
                                   mode=publish_gate.MODE_WARN)
    assert result["gate_status"] != publish_gate.GATE_BLOCK
    assert result["would_block"], "阻断依据仍须记录，供下一轮 enforce 使用"


def test_enforce_mode_records_intent_without_blocking_yet(env):
    """enforce 分支接口形态已就绪，但本轮不实现阻断。"""
    db, tenant_id = env
    product = _charger(db, tenant_id)
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay",
                                   mode=publish_gate.MODE_ENFORCE)
    assert result["mode"] == "enforce"
    assert result["gate_status"] == publish_gate.GATE_WARN
    assert result["would_block"]
    assert any("阻断能力将在下一轮开启" in reason for reason in result["reasons"])


def test_satisfied_evidence_yields_pass(env):
    db, tenant_id = env
    product = _charger(db, tenant_id)
    for requirement in ("FCC",):
        db.add(ProductComplianceEvidence(
            tenant_id=tenant_id, product_id=product.id, destination_country="US",
            requirement=requirement, evidence_ref="FCC-2026-001"))
    db.commit()
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
    assert result["gate_status"] == publish_gate.GATE_PASS
    assert not result["missing"] and not result["expired"]


def test_expired_evidence_is_reported_with_date(env):
    """过期证据必须带有效期出现在 reasons 里（运营要据此补件）。"""
    from datetime import datetime, timedelta

    db, tenant_id = env
    product = _charger(db, tenant_id)
    db.add(ProductComplianceEvidence(
        tenant_id=tenant_id, product_id=product.id, destination_country="US",
        requirement="FCC", evidence_ref="FCC-2020-001",
        valid_until=datetime.utcnow() - timedelta(days=1)))
    db.commit()
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
    assert "FCC" in result["expired"]
    assert any("已过期" in reason for reason in result["reasons"]), result
    assert result["gate_status"] == publish_gate.GATE_WARN


def test_gate_is_read_only(env):
    """闸门是只读的：调用前后证据与商品数据都不得变化。"""
    db, tenant_id = env
    product = _charger(db, tenant_id)
    before = (product.title, product.category, len(product.attrs or {}),
              db.query(ProductComplianceEvidence).count())
    publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
    db.commit()
    after = (product.title, product.category, len(product.attrs or {}),
             db.query(ProductComplianceEvidence).count())
    assert before == after


def test_gate_swallows_backend_failure_instead_of_breaking_publish(env, monkeypatch):
    """校验内部异常不得冒泡打断发布（闸门只读且 advisory）。"""

    def boom(*args, **kwargs):
        raise RuntimeError("模拟准入库故障")

    monkeypatch.setattr(publish_gate.compliance_registry, "check_evidence", boom)
    db, tenant_id = env
    product = _charger(db, tenant_id)
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
    assert result["gate_status"] == publish_gate.GATE_WARN
    assert any("准入校验失败" in reason for reason in result["reasons"]), result


# ---------------------------------------------------------------- 接入点
def _publishable(db, tenant_id, product, *, platform=_PLATFORM):
    """构造一个能通过前四道校验的Listing + 已通过复核记录。"""
    listing = Listing(tenant_id=tenant_id, product_id=product.id, platform=platform,
                      title="65W 氮化镓快充充电器", description="描述",
                      bullets=["65W"], keywords=["charger", "usb-c"], status="draft")
    rules = {"manual_categories": ["3C配件"], "banned_words": [], "image_min": 1}
    db.add_all([listing, PlatformRulePack(platform=platform, version=_VERSION,
                                           rules=rules,
                                           source_url="https://example.com/rules")])
    db.flush()
    from app.services.action_records import listing_fingerprint

    db.add(ListingReviewDecision(
        tenant_id=tenant_id, listing_id=listing.id, product_id=product.id,
        platform=platform, decision="approved", human_override=True,
        reviewer="human:probe", reasons=["已人工核对"], rule_version=_VERSION,
        evidence={"content_fingerprint": listing_fingerprint(listing, product)}))
    db.commit()
    return listing


def test_publish_facts_records_gate_result_without_blocking(env, caplog):
    """publish_facts 第五道闸门：缺 FCC 时照常返回 facts（不抛异常），且带闸门结论。"""
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    listing = _publishable(db, tenant_id, product)
    with caplog.at_level(logging.WARNING, logger="app.services.publish_gate"):
        facts = publish_facts(db, tenant_id, listing.id)
    assert facts["fingerprint"], "缺合规证据不得影响原有发布事实"
    assert facts["compliance_gate"]["gate_status"] == publish_gate.GATE_WARN
    assert "FCC" in facts["compliance_gate"]["missing"]
    assert any("publish_compliance_warn" in record.getMessage()
               for record in caplog.records), [r.getMessage() for r in caplog.records]


def test_publish_facts_gate_silent_when_compliance_is_satisfied(env, caplog):
    """证据齐备且目的国明确时不应刷warn 日志（避免噪声淹没真问题）。"""
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    db.add(ProductComplianceEvidence(tenant_id=tenant_id, product_id=product.id,
                                     destination_country="US", requirement="FCC",
                                     evidence_ref="FCC-2026-001"))
    db.commit()
    listing = _publishable(db, tenant_id, product)
    with caplog.at_level(logging.WARNING, logger="app.services.publish_gate"):
        facts = publish_facts(db, tenant_id, listing.id)
    assert facts["compliance_gate"]["gate_status"] == publish_gate.GATE_PASS
    assert not [r for r in caplog.records if "publish_compliance_warn" in r.getMessage()]


def test_publish_facts_gate_warns_for_demo_shop_path(env, caplog):
    """demo 店铺路径同样留痕（不阻断，但可观测）。"""
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    shop = Shop(tenant_id=tenant_id, platform=_PLATFORM, status="authorized", is_demo=True)
    db.add(shop)
    db.commit()
    listing = _publishable(db, tenant_id, product)
    with caplog.at_level(logging.WARNING, logger="app.services.publish_gate"):
        facts = publish_facts(db, tenant_id, listing.id, shop.id)
    assert facts["shop_id"] == shop.id
    assert facts["compliance_gate"]["gate_status"] == publish_gate.GATE_WARN
    assert facts["compliance_gate"]["shop_id"] == shop.id


def test_publish_facts_gate_does_not_block_unknown_destination(env, caplog):
    """未声明目的国时闸门给 warn，但**不得**阻断发布（不制造可用性事故）。"""
    db, tenant_id = env
    product = _charger(db, tenant_id)
    listing = _publishable(db, tenant_id, product)
    with caplog.at_level(logging.WARNING, logger="app.services.publish_gate"):
        facts = publish_facts(db, tenant_id, listing.id)
    assert facts["fingerprint"]
    assert facts["compliance_gate"]["gate_status"] == publish_gate.GATE_WARN


# ---------------------------------------------------------------- 适配器接入
def test_ebay_publish_lists_advisory_but_still_publishes(env, monkeypatch):
    """eBay：缺目的国证据时记日志并附加到错误上下文，但**不阻断**本可发布的 Listing。"""
    from types import SimpleNamespace

    from app.services.adapters.ebay import EbayAdapter

    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    shop = SimpleNamespace(tenant_id=tenant_id, platform="ebay", status="authorized",
                           token_expire_at=None, app_key="k", app_secret="s",
                           shop_id="ru", access_token="t", refresh_token="r")
    adapter = EbayAdapter(db, shop)
    listing = SimpleNamespace(title="65W 氮化镓快充充电器", description="描述",
                              keywords=["charger"])
    product.attrs = {**product.attrs, "ebay_category_id": "12345",
                     "ebay_location_key": "LOC", "ebay_fulfillment_policy_id": "F",
                     "ebay_payment_policy_id": "P", "ebay_return_policy_id": "R",
                     "sale_price": 39.9, "onhand": 100}
    db.commit()
    monkeypatch.setattr(adapter, "_pre_publish_checks", lambda *a: None)
    calls = []
    monkeypatch.setattr(adapter, "_api_call", lambda method, path, body=None:
                        calls.append(path) or {"offerId": "OFFER1", "listingId": "LID1"})
    result = adapter.publish_listing(listing, product)
    assert result.external_id == "LID1", "缺 FCC 证据不得让本可发布的 Listing 失败"
    assert calls, "仍应真实调用 eBay 接口"


def test_ebay_publish_attaches_advisory_to_existing_error_context(env, monkeypatch):
    """eBay 自身必填缺失时，准入提示附加进既有错误信息（不吞掉原错误）。"""
    from types import SimpleNamespace

    from app.services.adapters.contract import PlatformError
    from app.services.adapters.ebay import EbayAdapter

    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    shop = SimpleNamespace(tenant_id=tenant_id, platform="ebay", status="authorized",
                           token_expire_at=None, app_key="k", app_secret="s",
                           shop_id="ru", access_token="t", refresh_token="r")
    adapter = EbayAdapter(db, shop)
    listing = SimpleNamespace(title="充电器", description="描述", keywords=["charger"])
    monkeypatch.setattr(adapter, "_pre_publish_checks", lambda *a: None)
    with pytest.raises(PlatformError) as excinfo:
        adapter.publish_listing(listing, product)
    message = str(excinfo.value)
    assert "eBay 类目ID" in message, "原有错误信息必须保留"
    assert "缺少准入认证：FCC" in message, "准入提示应附加到错误上下文"
