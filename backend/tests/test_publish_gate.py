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
    attrs = kwargs.pop("attrs", {"destination_country": "US"})
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
    """无店铺预览读取商品声明，但不再猜测适配器默认站点。"""
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "JP"})
    assert publish_gate.resolve_destination(db, product, "ebay") == "JP"
    # 未声明目的地不能从平台名猜测国家。
    fallback = _charger(db, tenant_id, attrs={})
    assert publish_gate.resolve_destination(db, fallback, "ebay") == ""
    assert publish_gate.resolve_destination(db, fallback, "shopee") == ""


def test_target_country_used_when_destination_country_absent(env):
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"target_country": "DE"})
    assert publish_gate.resolve_destination(db, product, "ebay") == "EU"


def test_unresolvable_destination_is_never_reported_as_pass(env):
    """解析不出目的国时必须 warn，**不得** pass（沉默的绿灯最危险）。"""
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={})
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="unknown_platform")
    assert result["gate_status"] == publish_gate.GATE_WARN
    assert result["destination_country"] == ""
    assert "目标国家未配置或当前不支持，无法校验目的国准入" in result["reasons"]


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


def test_enforce_mode_blocks_when_evidence_missing(env):
    """enforce 模式：缺证据必须真正 block（发布链路据此真拦截上架）。

    ⚠️ 2026-10 语义变更：本条原先断言 enforce 下仍返回 ``GATE_WARN``，那是
    返工前「本轮只做 warn、不实现阻断」的临时预期。改为 fail-closed 后，
    enforce 必须返回 ``GATE_BLOCK``，否则 warn-only 等于没闸门。
    """
    db, tenant_id = env
    product = _charger(db, tenant_id)
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay",
                                   mode=publish_gate.MODE_ENFORCE)
    assert result["mode"] == "enforce"
    assert result["gate_status"] == publish_gate.GATE_BLOCK
    assert result["would_block"]


def test_warn_mode_still_never_blocks_for_readonly_callers(env):
    """warn 模式（evaluate 默认值，供试算/预览用）：缺证据只 warn，不阻断。"""
    db, tenant_id = env
    product = _charger(db, tenant_id)
    result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
    assert result["mode"] == "warn"
    assert result["gate_status"] == publish_gate.GATE_WARN
    assert result["would_block"], "阻断依据仍须记录"


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
    shop = Shop(tenant_id=tenant_id, platform=_PLATFORM, market="US", status="authorized", is_demo=True)
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
    product = _charger(db, tenant_id, attrs={})
    listing = _publishable(db, tenant_id, product)
    with caplog.at_level(logging.WARNING, logger="app.services.publish_gate"):
        facts = publish_facts(db, tenant_id, listing.id)
    assert facts["fingerprint"]
    assert facts["compliance_gate"]["gate_status"] == publish_gate.GATE_WARN


def test_publish_facts_blocks_real_shop_missing_fcc(env):
    """真实店铺（is_demo=0）缺 FCC：publish_facts 必须抛 ActionError（fail-closed）。

    2026-10 fail-closed 定稿的核心断言。本地（shop=None）与 demo 店铺的旁路
    由 QA 用例 test_local_path_without_shop_still_publishes /
    test_demo_shop_path_still_publishes 锁定。
    """
    from app.services.ai_actions import ActionError

    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    shop = Shop(tenant_id=tenant_id, platform=_PLATFORM, role="sales",
                market="US", status="authorized", is_demo=False)
    db.add(shop)
    db.commit()
    listing = _publishable(db, tenant_id, product)
    with pytest.raises(ActionError) as excinfo:
        publish_facts(db, tenant_id, listing.id, shop.id)
    assert "FCC" in str(excinfo.value)


def test_publish_facts_allows_real_shop_once_fcc_present(env):
    """反向约束：真实店铺证据齐备时不得被闸门误拦（防止修成一律拦死）。"""
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    db.add(ProductComplianceEvidence(tenant_id=tenant_id, product_id=product.id,
                                     destination_country="US", requirement="FCC",
                                     evidence_ref="FCC-2026-001"))
    shop = Shop(tenant_id=tenant_id, platform=_PLATFORM, role="sales",
                market="US", status="authorized", is_demo=False)
    db.add(shop)
    db.commit()
    listing = _publishable(db, tenant_id, product)
    facts = publish_facts(db, tenant_id, listing.id, shop.id)
    assert facts["fingerprint"], "证据齐备的发布事实必须正常产出"
    assert facts["compliance_gate"]["gate_status"] == publish_gate.GATE_PASS


# ---------------------------------------------------------------- 适配器接入
def test_shop_market_change_invalidates_approved_fingerprint(env):
    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    listing = _publishable(db, tenant_id, product)
    shop = Shop(tenant_id=tenant_id, platform=_PLATFORM, role="sales", market="US", is_demo=True)
    db.add(shop)
    db.commit()
    before = publish_facts(db, tenant_id, listing.id, shop.id)
    shop.market = "TR"
    db.commit()
    after = publish_facts(db, tenant_id, listing.id, shop.id)
    assert before["fingerprint"] != after["fingerprint"]
    assert after["compliance_gate"]["destination_country"] == "TR"


def _record_hook(name, sink):
    """构造记录调用来源的桩（工厂函数：避免闭包 late-binding 绑错循环变量）。"""
    def _hook(*_args, **_kwargs):
        sink.append(name)
        return {}
    return _hook


# ⚠️ 2026-10 语义变更（fail-closed 定稿）：以下两条原先断言「缺 FCC 只记日志、
# 不阻断本可发布的 Listing」。那是「本轮只做 warn」阶段的临时预期，现已作废——
# 法定强制认证缺失属法律硬底线，不允许靠租户开关放行。两条改为断言**必须拦截**。
def test_ebay_publish_blocks_when_fcc_missing(env, monkeypatch):
    """eBay：缺 FCC 认证必须拦在网络调用之前（不得发出任何真实请求）。"""
    from types import SimpleNamespace

    from app.services.adapters.contract import PlatformError
    from app.services.adapters.ebay import EbayAdapter

    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    shop = SimpleNamespace(tenant_id=tenant_id, platform="ebay", market="US", status="authorized",
                           token_expire_at=None, app_key="k", app_secret="s",
                           shop_id="ru", access_token="t", refresh_token="r")
    adapter = EbayAdapter(db, shop)
    listing = SimpleNamespace(title="65W 氮化镓快充充电器", description="描述",
                              keywords=["charger"])
    # 刻意把 eBay 自身的必填字段全部补齐：证明拦住它的**只有**合规闸门，
    # 而不是「反正字段也缺、顺手一起报」。
    product.attrs = {**product.attrs, "ebay_category_id": "12345",
                     "ebay_location_key": "LOC", "ebay_fulfillment_policy_id": "F",
                     "ebay_payment_policy_id": "P", "ebay_return_policy_id": "R",
                     "sale_price": 39.9, "onhand": 100}
    db.commit()
    monkeypatch.setattr(adapter, "_pre_publish_checks", lambda *a: None)
    calls = []
    monkeypatch.setattr(adapter, "_api_call", lambda method, path, body=None:
                        calls.append(path) or {"offerId": "OFFER1", "listingId": "LID1"})
    with pytest.raises(PlatformError) as excinfo:
        adapter.publish_listing(listing, product)
    assert "缺少准入认证：FCC" in str(excinfo.value)
    assert not calls, f"缺 FCC 认证竟仍真实调用了 eBay 接口：{calls}"


def test_ebay_publish_succeeds_once_fcc_evidence_present(env, monkeypatch):
    """反向约束：补齐 FCC 证据后必须能正常发布（防止修成一律拦死）。"""
    from types import SimpleNamespace

    from app.services.adapters.ebay import EbayAdapter

    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    db.add(ProductComplianceEvidence(tenant_id=tenant_id, product_id=product.id,
                                     destination_country="US", requirement="FCC",
                                     evidence_ref="FCC-2026-001"))
    shop = SimpleNamespace(tenant_id=tenant_id, platform="ebay", market="US", status="authorized",
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
    assert result.external_id == "LID1", "证据齐备后不得被闸门误拦"
    assert calls, "仍应真实调用 eBay 接口"


@pytest.mark.parametrize("platform", ["lazada", "tiktok", "walmart"])
def test_every_can_publish_adapter_blocks_when_fcc_missing(env, monkeypatch, platform):
    """架构级回归：缺 FCC 时**每一个** can_publish 平台都必须拦住。

    2026-10 验收发现 eBay 修好后，lazada / tiktok / walmart 三个同样
    can_publish=True 的平台一次都不咨询闸门。本条逐个平台实测运行时行为，
    避免「形状齐全、行为放行」再次发生。
    """
    from types import SimpleNamespace

    from app.services.adapters.contract import PlatformError
    from app.services.platform_adapters import ADAPTERS

    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    shop = SimpleNamespace(tenant_id=tenant_id, platform=platform, market="US", status="authorized",
                           token_expire_at=None, app_key="k", app_secret="s",
                           shop_id="100", access_token="t", refresh_token="r")
    adapter = ADAPTERS[platform](db, shop)
    listing = SimpleNamespace(title="65W 氮化镓快充充电器", description="描述",
                              keywords=["charger"], platform=platform, category="3C配件",
                              images=["https://cdn.example.com/c.jpg"], attrs=product.attrs,
                              bullets=["65W"], brand="probe", language="en-US")
    monkeypatch.setattr(adapter, "_pre_publish_checks", lambda *a: None)
    monkeypatch.setattr(adapter, "listing_readiness",
                        lambda *a: {"ready": True, "mode": "probe", "market": "US",
                                    "category_id": "1", "shop_region": "US",
                                    "enabled_logistics": ["1"],
                                    "required_attribute_count": 0, "blockers": [],
                                    "warnings": [], "next_action": ""})
    reached = []
    for hook in ("_api_call", "_call", "_upload_image", "_upload"):
        if hasattr(adapter, hook):
            monkeypatch.setattr(adapter, hook, _record_hook(hook, reached))
    with pytest.raises(PlatformError) as excinfo:
        adapter.publish_listing(listing, product)
    assert "缺少准入认证：FCC" in str(excinfo.value), f"{platform} 未报出 FCC 缺口"
    assert not reached, f"{platform} 缺 FCC 却仍发起了外部调用：{reached}"


def test_ebay_own_field_error_not_swallowed_by_gate(env, monkeypatch):
    """合规通过但 eBay 自身必填缺失时，必须报 eBay 自己的错（闸门不吞错误）。

    ⚠️ 2026-10 语义变更：原用例断言「准入提示附加进eBay 既有错误信息」。
    fail-closed 后闸门口径独立且**先于**平台字段检查抛错，两者不再混在一条
    消息里——保留的是「不吞掉原错误」这个意图：证据齐备时，缺什么报什么。
    """
    from types import SimpleNamespace

    from app.services.adapters.contract import PlatformError
    from app.services.adapters.ebay import EbayAdapter

    db, tenant_id = env
    product = _charger(db, tenant_id, attrs={"destination_country": "US"})
    db.add(ProductComplianceEvidence(tenant_id=tenant_id, product_id=product.id,
                                     destination_country="US", requirement="FCC",
                                     evidence_ref="FCC-2026-001"))
    shop = SimpleNamespace(tenant_id=tenant_id, platform="ebay", market="US", status="authorized",
                           token_expire_at=None, app_key="k", app_secret="s",
                           shop_id="ru", access_token="t", refresh_token="r")
    adapter = EbayAdapter(db, shop)
    listing = SimpleNamespace(title="充电器", description="描述", keywords=["charger"])
    monkeypatch.setattr(adapter, "_pre_publish_checks", lambda *a: None)
    with pytest.raises(PlatformError) as excinfo:
        adapter.publish_listing(listing, product)
    message = str(excinfo.value)
    assert "eBay 类目ID" in message, "eBay 自身的必填缺失必须照常报出"
    assert "合规闸门" not in message, "证据齐备时不应被合规闸门误拦"
