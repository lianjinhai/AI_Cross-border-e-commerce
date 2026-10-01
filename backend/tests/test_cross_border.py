"""跨境到岸成本专项测试（D58）：关税引擎 / 物流计费 / 平台费率 / 目的国合规 / 利润公式。

隔离：服务级用例自建内存库（``create_all`` + 独立 Tenant），不碰业务主库；
接口级用例走既有 ``client`` + ``auth_headers``（测试库由 conftest 全链迁移到 head）。
"""
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    DestinationComplianceRule,
    DutyRate,
    ExchangeRate,
    LogisticsRoute,
    PlatformFeeSchedule,
    Product,
    ProductComplianceEvidence,
    Tenant,
    User,
)
from app.services import (
    compliance_registry,
    costing,
    duty,
    logistics,
    platform_fees,
    settings_service,
)

BACKEND = Path(__file__).resolve().parents[1]

# D58 新增的 5 张跨境成本表（迁移 Revision 20 建立）。
CROSS_BORDER_TABLES = (
    "duty_rates", "logistics_routes", "platform_fee_schedules",
    "destination_compliance_rules", "product_compliance_evidence",
)


@pytest.fixture
def case():
    """内存库 + 独立租户 + 汇率，供服务级用例使用。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="跨境成本隔离探针")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="cross-border-probe",
                    password_hash="unused", role="admin")
        db.add(user)
        db.add(ExchangeRate(tenant_id=tenant.id, base_currency="USD", quote_currency="CNY",
                            rate=7.12, effective_at=datetime.utcnow() - timedelta(days=1)))
        db.add(ExchangeRate(tenant_id=tenant.id, base_currency="EUR", quote_currency="CNY",
                            rate=7.8, effective_at=datetime.utcnow() - timedelta(days=1)))
        db.commit()
        yield db, tenant.id


def _product(db, tenant_id, **kwargs) -> Product:
    attrs = kwargs.pop("attrs", {})
    kwargs.setdefault("title", "跨境探针商品")
    product = Product(tenant_id=tenant_id, sku=f"CB-{time.time_ns()}",
                      status="active", attrs=attrs, **kwargs)
    db.add(product)
    db.commit()
    return product


# ---------------------------------------------------------------- 目的国归一化
def test_country_normalization_and_eu_mapping():
    from app.services.regions import COUNTRY_ALIASES  # noqa: F401  (存在性自证)
    assert duty.normalize_country("美国") == "US"
    assert duty.normalize_country("united states") == "US"
    assert duty.normalize_country("uk") == "GB"
    assert duty.normalize_country("") == ""
    # 欧盟成员国统一按 EU 规则判定（(EU) 2026/382 的 €3/件是欧盟口径）
    assert duty.duty_country("DE") == "EU"
    assert duty.duty_country("FR") == "EU"
    assert duty.duty_country("US") == "US"


# ---------------------------------------------------------------- 关税引擎
def test_us_ad_valorem_duty(case):
    db, tenant_id = case
    db.add(DutyRate(tenant_id=tenant_id, destination_country="US", hs_prefix="",
                    rate_type="ad_valorem", rate=0.075, currency="USD", de_minimis=0.0))
    db.commit()
    out = duty.compute_landed_cost(db, tenant_id, country="US", hs_code="610910",
                                   declared_value_cny=1000.0, qty=1)
    assert out["duty_cny"] == pytest.approx(75.0, abs=0.01), out
    assert out["rate_source"] == "tenant"
    assert out["rate_configured"] is True and out["estimated"] is False
    assert out["de_minimis_exempt"] is False


def test_eu_fixed_per_item_three_euro(case):
    """欧盟过渡期：按 HS 税则子目「每件 €3」定额，按件数计税。"""
    db, tenant_id = case
    db.add(DutyRate(tenant_id=tenant_id, destination_country="EU", hs_prefix="",
                    rate_type="fixed_per_item", rate=3.0, currency="EUR"))
    db.commit()
    out = duty.compute_landed_cost(db, tenant_id, country="DE", hs_code="610910",
                                   declared_value_cny=500.0, qty=3)
    assert out["country"] == "EU"
    assert out["duty_cny"] == pytest.approx(3.0 * 7.8 * 3, abs=0.05), out


def test_de_minimis_exemption(case):
    db, tenant_id = case
    db.add(DutyRate(tenant_id=tenant_id, destination_country="GB", hs_prefix="",
                    rate_type="ad_valorem", rate=0.20, currency="USD", de_minimis=135.0))
    db.commit()
    low = duty.compute_landed_cost(db, tenant_id, country="GB", declared_value_cny=500.0)
    assert low["de_minimis_exempt"] is True and low["duty_cny"] == 0.0
    high = duty.compute_landed_cost(db, tenant_id, country="GB", declared_value_cny=2000.0)
    assert high["de_minimis_exempt"] is False
    assert high["duty_cny"] == pytest.approx(400.0, abs=0.01)


def test_hs_longest_prefix_wins(case):
    db, tenant_id = case
    db.add_all([
        DutyRate(tenant_id=tenant_id, destination_country="US", hs_prefix="61",
                 rate_type="ad_valorem", rate=0.10, currency="USD"),
        DutyRate(tenant_id=tenant_id, destination_country="US", hs_prefix="6109",
                 rate_type="ad_valorem", rate=0.20, currency="USD"),
    ])
    db.commit()
    picked = duty.resolve_duty_rate(db, tenant_id, "US", "610910")
    assert picked["rate"] == pytest.approx(0.20), picked
    other = duty.resolve_duty_rate(db, tenant_id, "US", "611020")
    assert other["rate"] == pytest.approx(0.10), other


def test_effective_window_excludes_expired(case):
    db, tenant_id = case
    db.add(DutyRate(tenant_id=tenant_id, destination_country="US", hs_prefix="",
                    rate_type="ad_valorem", rate=0.30, currency="USD",
                    effective_from=datetime.utcnow() - timedelta(days=60),
                    effective_to=datetime.utcnow() - timedelta(days=1)))
    db.commit()
    found = duty.resolve_duty_rate(db, tenant_id, "US", "610910")
    # 过期行不生效 → 落到代码兜底的 US 参考行（从价 0）
    assert found["found"] is True and found["source"] == "default", found
    assert found["rate"] == 0.0


def test_missing_country_is_zero_and_flagged(case):
    db, tenant_id = case
    out = duty.compute_landed_cost(db, tenant_id, country="", declared_value_cny=1000.0)
    assert out["duty_cny"] == 0.0 and out["total_cny"] == 0.0
    assert out["reason"] == "missing_country" and out["estimated"] is True


def test_unconfigured_country_only_clearance(case):
    db, tenant_id = case
    out = duty.compute_landed_cost(db, tenant_id, country="ZZ", declared_value_cny=1000.0)
    assert out["reason"] == "unconfigured_country"
    assert out["duty_cny"] == 0.0
    assert out["clearance_cny"] > 0
    assert out["total_cny"] == pytest.approx(out["clearance_cny"], abs=0.01)


def test_import_vat_and_toggle(case):
    db, tenant_id = case
    db.add(DutyRate(tenant_id=tenant_id, destination_country="US", hs_prefix="",
                    rate_type="ad_valorem", rate=0.10, currency="USD"))
    db.commit()
    with_vat = duty.compute_landed_cost(db, tenant_id, country="JP",
                                        declared_value_cny=1000.0)
    assert with_vat["vat_rate"] == pytest.approx(0.10)
    assert with_vat["import_vat_cny"] == pytest.approx(100.0, abs=0.05)
    without = duty.compute_landed_cost(db, tenant_id, country="JP", declared_value_cny=1000.0,
                                       with_import_vat=False)
    assert without["import_vat_cny"] == 0.0


# ---------------------------------------------------------------- 物流计费
def test_volumetric_weight_beats_actual_for_bulky_goods():
    attrs = {"weight_kg": 0.5, "length_cm": 30, "width_cm": 20, "height_cm": 10}
    assert logistics.volumetric_weight(attrs, 6000) == pytest.approx(1.0)
    assert logistics.actual_weight(attrs) == pytest.approx(0.5)
    result = logistics.quote(None, None, attrs)
    # 无路由/无目的国 → 回退旧线性口径（口径不变的保证）
    assert result["source"] == "legacy"
    assert result["total_cny"] == pytest.approx(18.0 + 8.0 * 0.5, abs=0.01)


def test_route_quote_per_kg_with_surcharge(case):
    db, tenant_id = case
    db.add(LogisticsRoute(tenant_id=tenant_id, name="US 空运", channel_type="direct_mail",
                          destination_country="US", billing_method="per_kg",
                          first_weight_kg=0.5, first_weight_fee=60.0, additional_per_kg=40.0,
                          volumetric_divisor=6000, min_charge=60.0, fuel_surcharge_rate=0.10))
    db.commit()
    attrs = {"weight_kg": 1.5}
    out = logistics.quote(db, tenant_id, attrs, destination_country="US")
    assert out["source"] == "tenant" and out["billing_method"] == "per_kg"
    base = 60.0 + 40.0 * (1.5 - 0.5)
    assert out["base_cny"] == pytest.approx(base, abs=0.01)
    assert out["total_cny"] == pytest.approx(base * 1.10, abs=0.01)


def test_route_quote_uses_volumetric_weight(case):
    db, tenant_id = case
    db.add(LogisticsRoute(tenant_id=tenant_id, name="EU 泡货", channel_type="direct_mail",
                          destination_country="EU", billing_method="per_kg",
                          first_weight_kg=1.0, first_weight_fee=50.0, additional_per_kg=30.0,
                          volumetric_divisor=6000, min_charge=50.0))
    db.commit()
    attrs = {"weight_kg": 0.4, "dim_cm": [40, 30, 30]}   # 36000/6000 = 6.0kg
    out = logistics.quote(db, tenant_id, attrs, destination_country="DE")
    assert out["billing_weight_kg"] == pytest.approx(6.0)
    assert out["total_cny"] == pytest.approx(50.0 + 30.0 * 5.0, abs=0.01)


def test_route_quote_per_cbm(case):
    db, tenant_id = case
    db.add(LogisticsRoute(tenant_id=tenant_id, name="海运头程", channel_type="sea_freight",
                          destination_country="EU", billing_method="per_cbm",
                          per_cbm=800.0, per_item=5.0, min_charge=100.0))
    db.commit()
    attrs = {"dim_cm": [100, 100, 100], "weight_kg": 20}
    out = logistics.quote(db, tenant_id, attrs, destination_country="EU", qty=2)
    assert out["billing_method"] == "per_cbm"
    assert out["cbm"] == pytest.approx(1.0)
    assert out["total_cny"] == pytest.approx(800.0 * 1.0 * 2 + 5.0 * 2, abs=0.01)


# ---------------------------------------------------------------- 平台费率
def test_platform_fee_default_matches_legacy():
    out = platform_fees.resolve(None, None, "shopee")
    assert out["total_rate"] == pytest.approx(costing.DEFAULT_FEES["shopee"])
    unknown = platform_fees.resolve(None, None, "nope")
    assert unknown["total_rate"] == pytest.approx(platform_fees.FALLBACK_RATE)


def test_platform_fee_specificity_and_tenant_priority(case):
    db, tenant_id = case
    db.add_all([
        PlatformFeeSchedule(tenant_id=tenant_id, platform="shopee", category="",
                            site="", commission_rate=0.05),
        PlatformFeeSchedule(tenant_id=tenant_id, platform="shopee", category="电子",
                            site="SG", commission_rate=0.08, transaction_rate=0.02,
                            service_rate=0.01),
    ])
    db.commit()
    general = platform_fees.resolve(db, tenant_id, "shopee")
    assert general["total_rate"] == pytest.approx(0.05)
    specific = platform_fees.resolve(db, tenant_id, "shopee", "电子", "SG")
    assert specific["total_rate"] == pytest.approx(0.11), specific


def test_platform_fee_listing_includes_defaults(case):
    db, tenant_id = case
    items = platform_fees.list_schedules(db, tenant_id)
    sources = {item["platform"]: item["source"] for item in items}
    assert sources.get("shopee") == "default"
    assert sources.get("amazon") == "default"


# ---------------------------------------------------------------- 目的国合规
def test_ce_required_for_eu_electronics(case):
    db, tenant_id = case
    product = _product(db, tenant_id, category="电子产品", title="无线充电器")
    report = compliance_registry.check_evidence(db, tenant_id, product, "DE")
    assert report["country"] == "EU"
    requirements = {item["requirement"] for item in report["required"]}
    assert "CE" in requirements and "EPR" in requirements
    assert report["passed"] is False and report["blocking"]


def test_evidence_satisfies_and_expiry_blocks(case):
    db, tenant_id = case
    product = _product(db, tenant_id, category="电子产品", title="无线充电器")
    db.add(ProductComplianceEvidence(tenant_id=tenant_id, product_id=product.id,
                                     destination_country="EU", requirement="CE",
                                     evidence_ref="CE-2026-001",
                                     valid_until=datetime.utcnow() + timedelta(days=365)))
    db.commit()
    partial = compliance_registry.check_evidence(db, tenant_id, product, "DE")
    assert any(item["requirement"] == "CE" for item in partial["satisfied"])
    # 过期证据必须落入 expired 并继续阻断
    row = (db.query(ProductComplianceEvidence)
           .filter(ProductComplianceEvidence.product_id == product.id).first())
    row.valid_until = datetime.utcnow() - timedelta(days=1)
    db.commit()
    expired = compliance_registry.check_evidence(db, tenant_id, product, "DE")
    assert any(item["requirement"] == "CE" for item in expired["expired"])
    assert expired["passed"] is False


def test_battery_requirement_by_keyword(case):
    db, tenant_id = case
    product = _product(db, tenant_id, category="数码配件", title="锂电池移动电源 20000mAh")
    report = compliance_registry.check_evidence(db, tenant_id, product, "US")
    requirements = {item["requirement"] for item in report["required"]}
    assert "UN38.3" in requirements


def test_tenant_rule_overrides_defaults(case):
    db, tenant_id = case
    db.add(DestinationComplianceRule(tenant_id=tenant_id, destination_country="EU",
                                     category="", requirement="CE-MARK",
                                     mandatory=True, note="本租户自定义准入项"))
    db.commit()
    product = _product(db, tenant_id, category="电子产品")
    report = compliance_registry.check_evidence(db, tenant_id, product, "DE")
    assert {item["requirement"] for item in report["required"]} == {"CE-MARK"}


# ---------------------------------------------------------------- 利润公式
def test_profit_formula_includes_all_cross_border_items(case):
    db, tenant_id = case
    db.add(DutyRate(tenant_id=tenant_id, destination_country="EU", hs_prefix="",
                    rate_type="fixed_per_item", rate=3.0, currency="EUR"))
    settings_service.set_tenant_setting(db, tenant_id, "rules", {
        "payment_fee_rate": 0.01, "refund_rate": 0.05, "tax_rebate_rate": 0.13,
        "clearance_fee_cny": 12.0,
    })
    db.commit()
    product = _product(db, tenant_id, attrs={"sale_price": 39.99, "supplier_price": 45.0,
                                             "weight_kg": 0.4})
    out = costing.calc_profit(db, tenant_id, product.id, destination_country="DE")
    fx = out["fx"]
    breakdown = out["cost_breakdown"]
    # 关税：€3/件固定，qty=1
    assert breakdown["duty_cny"] == pytest.approx(3.0 * 7.8, abs=0.05)
    # 八项明细之和（退税为减项）应等于 cost_total_cny
    total = (breakdown["purchase_cny"] + breakdown["logistics_cny"] + breakdown["duty_cny"]
             + breakdown["import_vat_cny"] + breakdown["clearance_cny"]
             + breakdown["platform_fee_cny"] + breakdown["payment_fee_cny"]
             + breakdown["ads_cny"] + breakdown["refund_cost_cny"]
             - breakdown["tax_rebate_cny"])
    assert out["cost_total_cny"] == pytest.approx(total, abs=0.1), out
    assert out["profit"] == pytest.approx(39.99 - total / fx, abs=0.05), out
    # 各项确实非零（证明不是"零值占位"）
    for key in ("duty_cny", "import_vat_cny", "clearance_cny", "payment_fee_cny",
                "refund_cost_cny", "tax_rebate_cny"):
        assert breakdown[key] != 0, (key, breakdown)
    assert out["landed_cost_applied"] is True


def test_profit_without_destination_keeps_legacy_formula(case):
    """未指定目的国时口径不变：不得因新增能力而改变既有利润。"""
    db, tenant_id = case
    product = _product(db, tenant_id, attrs={"sale_price": 19.99, "supplier_price": 30.0,
                                             "weight_kg": 0.3})
    out = costing.calc_profit(db, tenant_id, product.id)
    expected = (out["price"]
                - (out["purchase_cost"] + out["logistics_cost"] + out["ads_cost"]) / out["fx"]
                - out["price"] * out["platform_fee_rate"])
    assert out["profit"] == pytest.approx(expected, abs=0.02), out
    assert out["cost_breakdown"]["duty_cny"] == 0.0
    assert out["landed_cost_applied"] is False


def test_list_endpoints_include_reference_defaults(case):
    db, tenant_id = case
    rates = duty.list_rates(db, tenant_id)
    assert any(item["source"] == "default" and item["destination_country"] == "EU"
               for item in rates), rates
    routes = logistics.list_routes(db, tenant_id)
    assert any(item["source"] == "default" and item["destination_country"] == "EU"
               for item in routes), routes


def test_us_default_rate_note_carries_verifiable_policy_anchors():
    """美国兜底税率的政策依据锚点不得被无意识删除（D58 政策守恒）。

    rate=0 是诚实兜底（ маслоeù税按 HS 子目维护），但 note 必须能让运维查到
    现行依据：E.O. 14324 / 14388、Proclamation 临时进口附加费、Federal Register。
    """
    us = next(item for item in duty.DEFAULT_DUTY_RATES
              if item["destination_country"] == "US")
    note = us["note"]
    for anchor in ("14324", "14388", "Proclamation 2026-02-20", "Federal Register"):
        assert anchor in note, f"US 兜底税率 note 缺少政策锚点 {anchor}：{note}"
    assert us["source_url"].startswith("https://www.federalregister.gov/"), us["source_url"]


# ---------------------------------------------------------------- 接口与权限
def test_cross_border_permissions(client, auth_headers):
    ok = client.get("/api/cross-border/duty-rates", headers=auth_headers)
    assert ok.status_code == 200, ok.text
    assert any(item["source"] == "default" for item in ok.json()["items"])
    viewer = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    assert viewer.status_code == 200, viewer.text
    vh = {"Authorization": f"Bearer {viewer.json()['token']}"}
    assert client.get("/api/cross-border/duty-rates", headers=vh).status_code == 200
    denied = client.post("/api/cross-border/duty-rates", headers=vh,
                         json={"destination_country": "US"})
    assert denied.status_code == 403, denied.text


def test_duty_rate_crud_and_landed_cost_endpoint(client, auth_headers):
    created = client.post("/api/cross-border/duty-rates", headers=auth_headers, json={
        "destination_country": "XX", "hs_prefix": "", "rate_type": "ad_valorem",
        "rate": 0.10, "currency": "USD", "de_minimis": 0,
        "note": "接口用例专用目的国，避免与内置参考值冲突",
    })
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["destination_country"] == "XX" and row["tenant_id"]
    product = client.post("/api/products", headers=auth_headers, json={
        "title": f"跨境接口探针-{time.time_ns()}", "hs_code": "610910", "attrs": {},
    })
    assert product.status_code == 200, product.text
    pid = product.json()["id"]
    assert product.json()["hs_code"] == "610910"
    calc = client.post("/api/cross-border/landed-cost", headers=auth_headers, json={
        "product_id": pid, "destination_country": "XX", "price": 20.0, "qty": 1,
    })
    assert calc.status_code == 200, calc.text
    body = calc.json()
    assert body["destination_country"] == "XX"
    assert body["duty_cost"] == pytest.approx(20.0 * body["fx"] * 0.10, abs=0.05), body
    assert body["landed_cost_detail"]["rate_source"] == "tenant"
    # 更新与删除（本租户行）
    assert client.put(f"/api/cross-border/duty-rates/{row['id']}", headers=auth_headers, json={
        "destination_country": "XX", "rate": 0.12, "currency": "USD",
    }).status_code == 200
    assert client.delete(f"/api/cross-border/duty-rates/{row['id']}",
                         headers=auth_headers).status_code == 200
    # 平台内置参考值（无 id）不可被寻址修改
    assert client.delete("/api/cross-border/duty-rates/999999",
                         headers=auth_headers).status_code == 404


def test_compliance_evidence_endpoint(client, auth_headers):
    product = client.post("/api/products", headers=auth_headers, json={
        "title": f"合规接口探针-{time.time_ns()}", "category": "电子产品",
        "attrs": {"source_desc": "wireless charger CE"},
    })
    assert product.status_code == 200, product.text
    pid = product.json()["id"]
    report = client.get(f"/api/cross-border/products/{pid}/compliance",
                        headers=auth_headers, params={"country": "DE"})
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["country"] == "EU" and body["passed"] is False
    for requirement in ("CE", "EPR", "REACH"):
        saved = client.post(f"/api/cross-border/products/{pid}/compliance",
                            headers=auth_headers, json={
                                "destination_country": "DE", "requirement": requirement,
                                "evidence_ref": f"{requirement}-2026",
                                "valid_until": "2030-01-01",
                            })
        assert saved.status_code == 200, saved.text
    final = client.get(f"/api/cross-border/products/{pid}/compliance",
                       headers=auth_headers, params={"country": "DE"})
    assert final.json()["passed"] is True, final.text


def test_destination_gate_is_opt_in(case):
    """上架门禁的目的国准入默认不阻断；开启后缺证据才阻断。"""
    from types import SimpleNamespace

    from app.services.adapters.base import BaseAdapter

    db, tenant_id = case
    product = _product(db, tenant_id, category="电子产品",
                       attrs={"destination_country": "DE"})
    listing = SimpleNamespace(keywords=["charger"])
    adapter = BaseAdapter(db, SimpleNamespace(tenant_id=tenant_id))
    assert adapter.missing_publish_requirements(listing, product) == []
    settings_service.set_tenant_setting(db, tenant_id, "rules",
                                        {"destination_compliance_enforce": True})
    db.commit()
    issues = adapter.missing_publish_requirements(listing, product)
    assert issues and all("目的国 EU" in item for item in issues), issues
    for requirement in ("CE", "EPR"):
        db.add(ProductComplianceEvidence(tenant_id=tenant_id, product_id=product.id,
                                         destination_country="EU", requirement=requirement,
                                         evidence_ref="evidence"))
    db.commit()
    assert adapter.missing_publish_requirements(listing, product) == []


def test_pricing_calc_accepts_destination(client, auth_headers):
    product = client.post("/api/products", headers=auth_headers, json={
        "title": f"定价跨境探针-{time.time_ns()}", "attrs": {"sale_price": 25.0},
    })
    pid = product.json()["id"]
    r = client.post("/api/pricing/calc", headers=auth_headers,
                    json={"product_id": pid, "destination_country": "JP"})
    assert r.status_code == 200, r.text
    assert r.json()["destination_country"] == "JP"
    assert r.json()["landed_cost_applied"] is True


def test_new_tenant_tables_declare_tenant_fk():
    """契约：D58 的 5 张新表必须声明 tenant_id -> tenants.id。

    它们在 Revision 16 的 TENANT_FK_TABLES 清单之外（禁止回改已执行迁移），
    故其租户外键由本用例独立核对，避免窄库与迁移库结构漂移。
    """
    for name in CROSS_BORDER_TABLES:
        table = Base.metadata.tables[name]
        assert "tenant_id" in table.columns, name
        targets = {fk.target_fullname for fk in table.columns["tenant_id"].foreign_keys}
        assert "tenants.id" in targets, (name, targets)


def test_cross_border_migration_roundtrip_on_legacy_products(tmp_path):
    """契约：真实旧库（products 无 hs_code）升级只新增结构，且降级可回滚。

    迁移的「只做加法」硬断言若写得过严（要求既有表列逐字不变），会在真实旧库
    升级时误报中止 `alembic upgrade`。本用例锁住该缺陷：允许 products 仅新增
    hs_code，5 张新表可建可删，products 数据不丢。
    """
    target = tmp_path / "cross-border-migration.db"
    with sqlite3.connect(target) as db:
        db.executescript("""
            CREATE TABLE tenants (id INTEGER PRIMARY KEY);
            CREATE TABLE products (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL,
                title VARCHAR(512) NOT NULL,
                CONSTRAINT fk_products_tenant_id_tenants FOREIGN KEY(tenant_id)
                    REFERENCES tenants(id));
            INSERT INTO tenants VALUES(1);
            INSERT INTO products VALUES(1,1,'旧商品');
            CREATE TABLE alembic_version(version_num VARCHAR(32));
            INSERT INTO alembic_version VALUES('20261001_19');
        """)
    env = {**os.environ, "ERP_DB_URL": "sqlite:///" + target.as_posix(),
           "PYTHONIOENCODING": "utf-8"}
    steps = (("upgrade", "head"), ("downgrade", "20261001_19"), ("upgrade", "head"))
    for direction, revision in steps:
        result = subprocess.run([sys.executable, "-m", "alembic", direction, revision],
                                cwd=BACKEND, env=env, capture_output=True, text=True,
                                encoding="utf-8")
        assert result.returncode == 0, result.stderr
        at_head = direction == "upgrade"
        with sqlite3.connect(target) as db:
            tables = {row[0] for row in
                      db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            columns = {row[1] for row in db.execute("PRAGMA table_info(products)")}
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert {row[0] for row in db.execute("SELECT title FROM products")} == {"旧商品"}
        assert (set(CROSS_BORDER_TABLES) <= tables) == at_head
        assert ("hs_code" in columns) == at_head
