"""QA 独立验证：上架合规闸门必须 fail-closed 硬拦截（5f68c5d 审查）。

背景
----
提交 ``5f68c5d`` 声称「修复充电器类目FCC 漏词并接入上架合规闸」。用户需求是
**直接修好**——真实发布路径遇到缺证据必须**阻断**，而不是"观察到了"。

本模块是 QA 的**独立验收测试**，不修改任何业务源码。测试分两类，泾渭分明：

- ``TestVerifiedFix`` —— 锁定已经修好的部分（FCC 漏词、只读性、demo 旁路），
  它们必须**一直绿**，是防回归的锚点；
- ``TestFailClosedRequired`` —— 把用户「直接修好 / fail-closed」的需求写成
  可执行断言。这些用例在当前实现下**应当失败**——它们的失败不是测试写错，
  而是**精确指出漏洞仍在**的证据（见模块末尾 Known Issues 注释）。

为什么不能把「warn 就算修好」写成断言
--------------------------------------
若把 ``mode=ENFORCE`` 断言成「返回 warn 且不抛错」，就把「观察到了」固化成了
「达标了」，正是本次要推翻的目标。闸门存在的唯一价值是拦住违规上架；
只会写日志的闸门拦不住任何东西。修复落地后，本文件中的
``TestFailClosedRequired`` 全部转绿，无需再改测试——断言写的是需求，不是实现。

隔离：全部用例自建内存库（``create_all`` + 独立 Tenant），不碰业务主库``erp.db``。
"""
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    AiAction,
    Listing,
    ListingReviewDecision,
    PlatformRulePack,
    Product,
    ProductComplianceEvidence,
    Shop,
    Tenant,
    TenantSetting,
)
from app.services import compliance_registry, publish_gate
from app.services.action_publish import publish_facts, publish_listing
from app.services.adapters.registry import ADAPTERS

# eBay 真实上架所需的全部 attrs（少一项会被适配器自身前置校验拦掉，
# 那样就测不到合规闸门了，必须给满）。
_EBAY_ATTRS = {
    "ebay_category_id": "12345",
    "ebay_location_key": "LOC",
    "ebay_fulfillment_policy_id": "F",
    "ebay_payment_policy_id": "P",
    "ebay_return_policy_id": "R",
    "sale_price": 39.9,
    "onhand": 100,
}
_PROBE_VERSION = "2026-10-02"


class _NoopLimiter:
    """替身限流器：让被测适配器跳过真实 sleep，保持测试快且无外部依赖。"""

    def wait(self):
        return None


def make_probe_env():
    """非夹具版建库（供参数化/循环内动态造场景使用）。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(name="QA 适配器覆盖探针")
    db.add(tenant)
    db.flush()
    return db, tenant.id


@pytest.fixture
def env():
    """内存库 + 独立租户。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="QA 合规闸门验收")
        db.add(tenant)
        db.flush()
        yield db, tenant.id


def _charger(db, tenant_id, *, attrs=None, platform_attrs=None):
    """SKU-46048 同款充电器：65W 氮化镓快充（美国站曾误报绿灯的那件）。"""
    payload = {"source_desc": "GaN charger 65W USB-C power adapter"}
    payload.update(attrs or {})
    payload.update(platform_attrs or {})
    product = Product(tenant_id=tenant_id, sku="SKU-46048", status="active",
                      category="3C配件", title="65W 氮化镓快充充电器",
                      images=["https://cdn.example.com/charger.jpg"], attrs=payload)
    db.add(product)
    db.commit()
    return product


def _publishable(db, tenant_id, product, *, platform="probe"):
    """构造能通过前四道既有校验的 Listing + 已通过复核记录。"""
    listing = Listing(tenant_id=tenant_id, product_id=product.id, platform=platform,
                      title="65W 氮化镓快充充电器", description="描述",
                      bullets=["65W"], keywords=["charger", "usb-c"], status="draft")
    rules = {"manual_categories": ["3C配件"], "banned_words": [], "image_min": 1}
    db.add_all([listing, PlatformRulePack(platform=platform, version=_PROBE_VERSION,
                                          rules=rules,
                                          source_url="https://example.com/rules")])
    db.flush()
    from app.services.action_records import listing_fingerprint

    db.add(ListingReviewDecision(
        tenant_id=tenant_id, listing_id=listing.id, product_id=product.id,
        platform=platform, decision="approved", human_override=True,
        reviewer="human:qa", reasons=["已人工核对"], rule_version=_PROBE_VERSION,
        evidence={"content_fingerprint": listing_fingerprint(listing, product)}))
    db.commit()
    return listing


def _approved_action(db, tenant_id, listing, shop, fingerprint):
    """构造一个已审批、指纹一致的 Action（模拟审批通过后的执行器入口）。"""
    action = AiAction(
        tenant_id=tenant_id, workspace_id=1, agent_type="qa",
        action_type="publish_listing", target_type="listing", target_id=listing.id,
        reason="QA 验收", evidence={"fingerprint": fingerprint}, expected_impact={},
        risk_level="low", required_permission="publish", execution_mode="apply",
        approval_required=True, status="APPROVED", requested_by=1,
        idempotency_key=f"qa-{listing.id}-{shop.id if shop else 'local'}")
    db.add(action)
    db.commit()
    return action


@pytest.fixture
def ebay_stub(monkeypatch):
    """拦截 eBay 真实 HTTP，只记录调用；返回 ``calls`` 列表。

    绝不发真实请求：既无凭据，也不允许测试触网。
    """
    from app.services.adapters.ebay import EbayAdapter

    calls = []
    monkeypatch.setattr(
        EbayAdapter, "_api_call",
        lambda self, method, path, body=None: (
            calls.append((method, path)) or {"offerId": "OFFER-1", "listingId": "LID-1"}))
    monkeypatch.setattr(EbayAdapter, "_pre_publish_checks",
                        lambda self, listing_, product_: None)
    return calls


# ============================================================ 已修好的部分（必须绿）
class TestVerifiedFix:
    """断言 1：FCC 漏词确实修好了。防回归锚点，必须始终通过。"""

    def test_us_charger_requires_fcc_and_fails_evidence_check(self, env):
        """check_evidence 直调：required/missing 含 FCC，passed 为 False。"""
        db, tenant_id = env
        product = _charger(db, tenant_id)
        report = compliance_registry.check_evidence(db, tenant_id, product, "US")
        required = [i["requirement"] for i in report["required"]]
        missing = [i["requirement"] for i in report["missing"]]
        assert "FCC" in required, report
        assert "FCC" in missing, report
        assert report["passed"] is False

    @pytest.mark.parametrize("country,requirement", [
        ("US", "FCC"), ("JP", "PSE"), ("GB", "UKCA"), ("EU", "CE"), ("KR", "KC"),
    ])
    def test_charger_requires_cert_in_every_market(self, env, country, requirement):
        """同一件充电器在 5 个主要市场都必须命中对应强制认证。"""
        db, tenant_id = env
        product = _charger(db, tenant_id)
        report = compliance_registry.check_evidence(db, tenant_id, product, country)
        assert requirement in [i["requirement"] for i in report["required"]], report

    def test_charger_not_over_broadened_to_battery_evidence(self, env):
        """反向边界：纯充电器不得被凭空要求 UN38.3 电池运输报告。"""
        db, tenant_id = env
        product = _charger(db, tenant_id)
        report = compliance_registry.check_evidence(db, tenant_id, product, "US")
        assert "UN38.3" not in [i["requirement"] for i in report["required"]], report

    def test_gate_reports_matching_cert_as_pass(self, env):
        """补齐 FCC 证据后闸门必须给 pass（否则修复过头变成一律拦）。"""
        db, tenant_id = env
        product = _charger(db, tenant_id)
        db.add(ProductComplianceEvidence(
            tenant_id=tenant_id, product_id=product.id, destination_country="US",
            requirement="FCC", evidence_ref="FCC-2026-001"))
        db.commit()
        result = publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
        assert result["gate_status"] == publish_gate.GATE_PASS
        assert not result["missing"]

    def test_unresolvable_destination_never_silently_passes(self, env):
        """目的国解析不出时必须 warn，绝不 pass（沉默的绿灯最危险）。"""
        db, tenant_id = env
        product = _charger(db, tenant_id)
        result = publish_gate.evaluate(db, tenant_id, product=product,
                                       platform="unknown_platform")
        assert result["gate_status"] == publish_gate.GATE_WARN
        assert "未声明目的国" in " ".join(result["reasons"])


class TestBypassIntentionallyPreserved:
    """断言 5：本地 / demo 旁路仍可发布（有意保留，E2E 依赖），且真实店铺未被误伤。"""

    def test_local_path_without_shop_still_publishes(self, env):
        """shop=None：本地直接置 published，闸门不得制造可用性事故。"""
        db, tenant_id = env
        product = _charger(db, tenant_id, attrs={"destination_country": "US"})
        listing = _publishable(db, tenant_id, product)
        facts = publish_facts(db, tenant_id, listing.id)
        action = _approved_action(db, tenant_id, listing, None, facts["fingerprint"])
        out = publish_listing(db, action, {})
        assert out["result"]["status"] == "published"
        assert out["result"]["source"] == "local"

    def test_demo_shop_path_still_publishes(self, env):
        """is_demo=1：E2E live_acceptance.py 依赖此路径，保留。"""
        db, tenant_id = env
        product = _charger(db, tenant_id, attrs={"destination_country": "US"})
        shop = Shop(tenant_id=tenant_id, platform="probe", role="sales",
                    status="authorized", is_demo=True)
        db.add(shop)
        db.commit()
        listing = _publishable(db, tenant_id, product)
        facts = publish_facts(db, tenant_id, listing.id, shop.id)
        action = _approved_action(db, tenant_id, listing, shop, facts["fingerprint"])
        out = publish_listing(db, action, {"shop_id": shop.id})
        assert out["result"]["status"] == "published"
        assert out["result"]["source"] == "demo"


class TestNoRetroactivePollution:
    """断言 6：闸门只读，不回溯污染已发布数据。"""

    def test_gate_does_not_mutate_published_listing(self, env):
        db, tenant_id = env
        product = _charger(db, tenant_id, attrs={"destination_country": "US"})
        listing = _publishable(db, tenant_id, product)
        listing.status = "published"
        listing.external_id = "EXT-1"
        db.commit()
        before = (listing.status, listing.external_id, listing.updated_at)
        publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
        db.commit()
        db.refresh(listing)
        assert (listing.status, listing.external_id, listing.updated_at) == before

    def test_gate_creates_no_compliance_evidence_rows(self, env):
        """闸门只读：绝不自动补写证据行（那是规则编辑器的职责）。"""
        db, tenant_id = env
        product = _charger(db, tenant_id, attrs={"destination_country": "US"})
        publish_gate.evaluate(db, tenant_id, product=product, platform="ebay")
        db.commit()
        assert db.query(ProductComplianceEvidence).count() == 0

    @pytest.mark.skipif(not os.path.exists(os.path.join(os.path.dirname(__file__),
                                                         "..", "erp.db")),
                        reason="业务主库不存在，跳过只读抽查")
    def test_business_db_published_listings_readable_and_intact(self):
        """只读连接抽查业务主库：已发布记录可正常读出，不被闸门改成非法状态。"""
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "erp.db"))
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT id, status, external_id FROM listings "
                "WHERE status='published' ORDER BY id").fetchall()
            assert rows, "业务主库应存在已发布 listing"
            for _id, status, external_id in rows:
                assert status == "published"
                assert external_id, f"listing {_id} 的 external_id 被清空"
        finally:
            con.close()


# ==================================== 用户需求：fail-closed 硬拦截（当前应失败 = 漏洞仍在）
class TestFailClosedRequired:
    """把用户「直接修好 / 真实路径必须阻断」的需求写成断言。

    ⚠️ 当前实现（warn-only）下这些用例会失败。失败即证据：闸门只观察、不阻断，
    缺认证商品仍可上架。修复后应全部转绿，**不需要改测试**。
    """

    def test_enforce_mode_must_block_when_evidence_missing(self, env):
        """断言 2 核心：MODE_ENFORCE 下缺证据必须真正阻断。

        期望二选一（任一满足即算修复）：
            1. evaluate 抛出阻断异常；或
            2. 返回 gate_status == GATE_BLOCK 且would_block 非空。
        当前实现只在 reasons 追加一句「阻断能力将在下一轮开启」→ 两者皆不满足。
        """
        db, tenant_id = env
        product = _charger(db, tenant_id, attrs={"destination_country": "US"})
        blocked = False
        result = None
        try:
            result = publish_gate.evaluate(db, tenant_id, product=product,
                                           platform="ebay",
                                           mode=publish_gate.MODE_ENFORCE)
        except Exception:  # noqa: BLE001 —— 抛任何阻断异常都算修复
            blocked = True
        assert blocked or (result and result["gate_status"] == publish_gate.GATE_BLOCK), (
            "ENFORCE 模式未实现阻断：既未抛异常，gate_status 也非 block，"
            f"实际={result and result['gate_status']!r}，"
            f"would_block={result and result['would_block']!r}")

    def test_publish_facts_must_reject_missing_evidence(self, env):
        """断言 2b：publish_facts 必须在**真实店铺**上真正阻断。

        ⚠️ 口径澄清（本条曾因用错 shop 而误报，勿退回）：
        ``publish_facts`` 按 ``shop is None or shop.is_demo`` 区分旁路——
        本地（shop=None）与 demo 店铺**有意放行**（E2E 依赖，且不对外产生真实上架），
        只有真实店铺（``is_demo=0``）走enforce 并 raise。
        因此本条必须传真实店铺；用 shop=None 断言阻断是**测试写错**，
        那种写法会把「有意保留的旁路」误判成缺陷。
        """
        from app.services.ai_actions import ActionError

        db, tenant_id = env
        product = _charger(db, tenant_id, attrs={"destination_country": "US"})
        shop = Shop(tenant_id=tenant_id, platform="probe", role="sales",
                    status="authorized", is_demo=False)
        db.add(shop)
        db.commit()
        listing = _publishable(db, tenant_id, product)
        with pytest.raises(ActionError) as excinfo:
            publish_facts(db, tenant_id, listing.id, shop.id)
        assert "FCC" in str(excinfo.value), (
            f"阻断错误信息应指出缺失项，实际={excinfo.value}")

    def test_real_shop_path_must_not_publish_uncertified_product(self, env, ebay_stub):
        """断言 3 核心：真实店铺（is_demo=0）不得把缺 FCC 商品发布上架。

        完整走真实分支：publish_facts → adapter.publish_listing → listing 置 published。
        """
        from app.services.ai_actions import ActionError

        db, tenant_id = env
        product = _charger(db, tenant_id, attrs={"destination_country": "US"},
                           platform_attrs=_EBAY_ATTRS)
        shop = Shop(tenant_id=tenant_id, platform="ebay", role="sales",
                    status="authorized", is_demo=False, app_key="k", app_secret="s",
                    shop_id="ru", access_token="t", refresh_token="r")
        db.add(shop)
        db.commit()
        listing = _publishable(db, tenant_id, product, platform="ebay")

        with pytest.raises(ActionError):
            facts = publish_facts(db, tenant_id, listing.id, shop.id)
            action = _approved_action(db, tenant_id, listing, shop, facts["fingerprint"])
            publish_listing(db, action, {"shop_id": shop.id})
        db.rollback()
        assert listing.status != "published", "缺 FCC 商品竟被置为 published"
        assert not ebay_stub, f"竟真实调用了 eBay 接口：{ebay_stub}"

    def test_ebay_adapter_must_raise_on_missing_destination_evidence(self, env, ebay_stub):
        """断言 4：eBay 前置校验必须 raise 阻断，而不是只拼进日志。

        对照 shopee.publish_listing：它对同一份 missing_publish_requirements
        是``raise PlatformError``。eBay 不应成为唯一不设防的平台。
        """
        from app.services.adapters.contract import PlatformError

        db, tenant_id = env
        product = _charger(db, tenant_id, attrs={"destination_country": "US"},
                           platform_attrs=_EBAY_ATTRS)
        shop = SimpleNamespace(tenant_id=tenant_id, platform="ebay", status="authorized",
                               token_expire_at=None, app_key="k", app_secret="s",
                               shop_id="ru", access_token="t", refresh_token="r")
        from app.services.adapters.ebay import EbayAdapter

        adapter = EbayAdapter(db, shop)
        listing = SimpleNamespace(title="65W 氮化镓快充充电器", description="描述",
                                  keywords=["charger"])
        with pytest.raises(PlatformError) as excinfo:
            adapter.publish_listing(listing, product)
        assert "FCC" in str(excinfo.value)
        assert not ebay_stub, f"竟真实调用了 eBay 接口：{ebay_stub}"

    def test_ebay_must_honour_tenant_enforce_switch(self, env, ebay_stub):
        """回归：租户显式开启 destination_compliance_enforce 后，eBay 必须阻断。

        这条更致命——租户**已经主动买了「合规阻断」**，
        eBay 却把这份阻断清单降级成 warning 记日志，等于开关完全失效。
        """
        from app.services.adapters.contract import PlatformError

        db, tenant_id = env
        product = _charger(db, tenant_id, attrs={"destination_country": "US"},
                           platform_attrs=_EBAY_ATTRS)
        db.add(TenantSetting(tenant_id=tenant_id, key="rules",
                             value={"destination_compliance_enforce": True}))
        db.commit()
        shop = SimpleNamespace(tenant_id=tenant_id, platform="ebay", status="authorized",
                               token_expire_at=None, app_key="k", app_secret="s",
                               shop_id="ru", access_token="t", refresh_token="r")
        from app.services.adapters.ebay import EbayAdapter

        adapter = EbayAdapter(db, shop)
        listing = SimpleNamespace(title="65W 氮化镓快充充电器", description="描述",
                                  keywords=["charger"])
        with pytest.raises(PlatformError) as excinfo:
            adapter.publish_listing(listing, product)
        assert "FCC" in str(excinfo.value)
        assert not ebay_stub, f"竟真实调用了 eBay 接口：{ebay_stub}"

    def test_every_publish_capable_adapter_must_consult_the_gate(self):
        """架构级断言：所有 can_publish=True 的适配器都必须让合规缺口真正拦住上架。

        逐个平台实测「缺 FCC 时publish_listing 是否真的被拦住」，而不是 grep 源码——
        grep 只能证明代码形状，证明不了运行时行为（eBay 就是形状齐全、
        行为却放行的反例）。

        判定口径（关键，勿搞反）：
          - 抛异常且异常信息含「目的国/FCC」→ **合规闸门真的拦住了**；
          - 抛异常但原因是**平台自身必填**（类目映射缺失、attrs 结构不对等）
            → **不算**闸门起作用，只是恰好也失败了；
          - 正常返回 PublishResult，或**已走到发网络请求** → **没拦住**。

        ⚠️ 为什么要区分前两种（第一版曾踩这个坑）：
        lazada/walmart 会因缺 ``attrs.lazada_product`` 抛错，shopee/tiktok 会因缺
        类目映射抛错——这些都与合规无关。若用「抛异常就算拦住」的宽松口径，
        会把「平台自己拦住了」误报成「合规闸门拦住了」，从而漏掉真正的失守平台。
        """
        blocked, bypassed, unrelated = [], [], []
        for name, adapter_cls in sorted(ADAPTERS.items()):
            if not getattr(adapter_cls, "can_publish", False):
                continue
            db, tenant_id = make_probe_env()
            product = _charger(db, tenant_id, attrs={"destination_country": "US"},
                               platform_attrs=_EBAY_ATTRS)
            shop = SimpleNamespace(tenant_id=tenant_id, platform=name, status="authorized",
                                   token_expire_at=None, app_key="k", app_secret="s",
                                   shop_id="ru", access_token="t", refresh_token="r")
            adapter = adapter_cls(db, shop)
            listing = SimpleNamespace(
                title="65W 氮化镓快充充电器", description="描述",
                keywords=["charger"], platform=name, category="3C配件",
                images=["https://cdn.example.com/charger.jpg"], attrs=product.attrs,
                bullets=["65W"], brand="QA", language="en-US")
            # 网络哨兵：任何真实 HTTP 都是「闸门没拦住」的确凿证据。
            reached_network = False

            def _sentinel(*_a, **_kw):
                nonlocal reached_network
                reached_network = True
                raise AssertionError("REACHED_NETWORK")

            patches = [patch.object(adapter, "_pre_publish_checks", lambda *a: None),
                       patch.object(adapter, "_limiter", lambda: _NoopLimiter())]
            for hook in ("_api_call", "_call", "_upload", "_post", "_request"):
                if hasattr(adapter, hook):
                    patches.append(patch.object(adapter, hook, _sentinel))
            reason = ""
            try:
                for ctx in patches:
                    ctx.start()
                try:
                    adapter.publish_listing(listing, product)
                except AssertionError:
                    reason = "已发网络请求"
                except Exception as exc:  # noqa: BLE001
                    reason = f"{type(exc).__name__}: {exc}"
            finally:
                for ctx in reversed(patches):
                    ctx.stop()
            if ("目的国" in reason) or ("FCC" in reason):
                blocked.append(name)
            elif reached_network or reason == "已发网络请求":
                bypassed.append(f"{name}(已发网络请求)")
            elif reason:
                unrelated.append(f"{name}(平台自身校验：{reason[:60]})")
            else:
                bypassed.append(f"{name}(正常返回)")
        assert blocked or bypassed, "未发现 can_publish=True 的适配器"
        assert not bypassed, (
            "这些 can_publish 平台在缺 FCC 时未被合规闸门拦住："
            f"{sorted(set(bypassed))}；"
            f"另有 {len(unrelated)} 个平台是因自身必填校验抛错（与合规无关），"
            "建议补齐其必填 attrs 后单独验证闸门口径")
