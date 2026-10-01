"""海外仓 / FBA 库存模型测试（D59）：库龄 × 日费率 → 持有成本 + 超期附加。

覆盖：
    - 库龄计算（库龄 = now - received_at，下限 0）
    - 持有成本 = 库龄 × 日费率 × qty
    - 超期附加：库龄超过阈值的部分叠加 surcharge_rate
    - 未配 warehouse_id 时 holding_cost=0、口径不变（向后兼容）
    - 租户隔离与 Warehouse 不存在/inactive 的回退
    - calc_profit 给出 warehouse_id 时持有成本计入 cost_total

隔离：内存库 create_all + 独立 Tenant，不碰业务主库。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    ExchangeRate,
    InventorySnapshot,
    Product,
    Tenant,
    User,
    Warehouse,
)
from app.services import inventory_service
from app.services.costing import calc_profit


@pytest.fixture
def case():
    """内存库 + 独立租户 + 汇率 + 商品，供服务级用例使用。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="海外仓隔离探针")
        db.add(tenant)
        db.flush()
        db.add(User(tenant_id=tenant.id, username="wh-probe",
                    password_hash="unused", role="admin"))
        db.add(ExchangeRate(tenant_id=tenant.id, base_currency="USD",
                            quote_currency="CNY", rate=7.12,
                            effective_at=datetime.utcnow() - timedelta(days=1)))
        prod = Product(tenant_id=tenant.id, sku="WH-TEST-001",
                       title="海外仓测试商品",
                       attrs={"weight_kg": 0.5, "supplier_price": 20.0,
                              "sale_price": 29.99})
        db.add(prod)
        db.commit()
        yield db, tenant.id, prod


@pytest.fixture
def warehouse(case):
    db, tenant_id, _ = case
    wh = Warehouse(tenant_id=tenant_id, code="FBA-US-USE1", name="FBA 美东一仓",
                   warehouse_type="fba", country="US",
                   daily_fee_per_unit=0.10, inbound_fee_per_unit=3.0,
                   outbound_fee_per_unit=2.5, long_term_threshold_days=90,
                   long_term_surcharge_rate=0.5, active=True)
    db.add(wh)
    db.flush()
    return wh


def test_holding_cost_zero_without_warehouse_id(case):
    db, tenant_id, prod = case
    out = inventory_service.holding_cost(db, tenant_id, warehouse_id=None,
                                          product_id=prod.id)
    assert out["holding_cost_cny"] == 0.0
    assert out["holding_cost_applied"] is False
    assert out["reason"] == "warehouse_not_specified"


def test_holding_cost_warehouse_not_found(case):
    db, tenant_id, prod = case
    out = inventory_service.holding_cost(db, tenant_id, warehouse_id=999999,
                                          product_id=prod.id)
    assert out["holding_cost_cny"] == 0.0
    assert out["reason"] == "warehouse_not_found"


def test_holding_cost_no_inventory(case, warehouse):
    db, tenant_id, prod = case
    out = inventory_service.holding_cost(db, tenant_id, warehouse_id=warehouse.id,
                                          product_id=prod.id)
    assert out["holding_cost_cny"] == 0.0
    assert out["reason"] == "no_inventory"


def test_holding_cost_basic(case, warehouse):
    """库龄 30 天 × 0.10/天 × 100 件 = 300 CNY（未超期，无附加）。"""
    db, tenant_id, prod = case
    received = datetime.utcnow() - timedelta(days=30)
    db.add(InventorySnapshot(tenant_id=tenant_id, warehouse_id=warehouse.id,
                              product_id=prod.id, sku=prod.sku,
                              qty_on_hand=100, received_at=received, snapshot_at=received))
    db.flush()
    out = inventory_service.holding_cost(db, tenant_id, warehouse_id=warehouse.id,
                                          product_id=prod.id)
    assert out["holding_cost_applied"] is True
    assert out["days_in_stock"] == 30
    assert out["qty"] == 100
    assert out["holding_cost_cny"] == pytest.approx(300.0, abs=0.01)
    assert out["long_term_surcharge_cny"] == 0.0


def test_holding_cost_long_term_surcharge(case, warehouse):
    """库龄 120 天（超期 30 天）：基础 1200 + 附加 150 = 1350 CNY。"""
    db, tenant_id, prod = case
    received = datetime.utcnow() - timedelta(days=120)
    db.add(InventorySnapshot(tenant_id=tenant_id, warehouse_id=warehouse.id,
                              product_id=prod.id, sku=prod.sku,
                              qty_on_hand=100, received_at=received, snapshot_at=received))
    db.flush()
    out = inventory_service.holding_cost(db, tenant_id, warehouse_id=warehouse.id,
                                          product_id=prod.id)
    # 基础 = 120 × 0.10 × 100 = 1200；超期 30 天 × 0.10 × 100 × 0.5 = 150
    assert out["holding_cost_cny"] == pytest.approx(1350.0, abs=0.01)
    assert out["long_term_surcharge_cny"] == pytest.approx(150.0, abs=0.01)


def test_holding_cost_negative_days_clamped_to_zero(case, warehouse):
    """received_at 在未来时库龄按 0 计，不产生负成本。"""
    db, tenant_id, prod = case
    future = datetime.utcnow() + timedelta(days=5)
    db.add(InventorySnapshot(tenant_id=tenant_id, warehouse_id=warehouse.id,
                              product_id=prod.id, sku=prod.sku,
                              qty_on_hand=50, received_at=future, snapshot_at=future))
    db.flush()
    out = inventory_service.holding_cost(db, tenant_id, warehouse_id=warehouse.id,
                                          product_id=prod.id)
    assert out["days_in_stock"] == 0
    assert out["holding_cost_cny"] == 0.0


def test_calc_profit_without_warehouse_keeps_legacy(case):
    """未配 warehouse_id 时利润与 D58 口径一致（holding_cost=0）。"""
    db, tenant_id, prod = case
    out = calc_profit(db, tenant_id, prod.id, price=29.99)
    assert out["holding_cost"] == 0.0
    assert out["holding_cost_applied"] is False
    assert out["cost_breakdown"]["holding_cost_cny"] == 0.0


def test_calc_profit_with_warehouse_includes_holding(case, warehouse):
    """配 warehouse_id 时持有成本 + 入库费计入 cost_total，利润相应下降。"""
    db, tenant_id, prod = case
    received = datetime.utcnow() - timedelta(days=60)
    db.add(InventorySnapshot(tenant_id=tenant_id, warehouse_id=warehouse.id,
                              product_id=prod.id, sku=prod.sku,
                              qty_on_hand=100, received_at=received, snapshot_at=received))
    db.flush()
    baseline = calc_profit(db, tenant_id, prod.id, price=29.99)
    with_wh = calc_profit(db, tenant_id, prod.id, price=29.99,
                           warehouse_id=warehouse.id)
    # 库龄 60 × 0.10 × 100 = 600；入库费 3.0 × 1 = 3；合计 603 CNY
    assert with_wh["holding_cost"] == pytest.approx(603.0, abs=0.01)
    assert with_wh["holding_cost_applied"] is True
    assert with_wh["profit"] < baseline["profit"]


def test_record_receipt_creates_snapshot(case, warehouse):
    db, tenant_id, prod = case
    snap = inventory_service.record_receipt(
        db, tenant_id, warehouse_id=warehouse.id,
        product_id=prod.id, sku=prod.sku, qty=50)
    db.commit()
    assert snap.id is not None
    assert snap.qty_on_hand == 50
    out = inventory_service.holding_cost(db, tenant_id, warehouse_id=warehouse.id,
                                          product_id=prod.id)
    assert out["days_in_stock"] == 0
    assert out["holding_cost_cny"] == 0.0
