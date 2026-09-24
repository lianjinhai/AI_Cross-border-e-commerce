"""商业数据口径的独立回归测试。"""
import os
import pathlib
from datetime import datetime, timedelta

import pytest

# 与 API 测试在导入 app 前使用同一隔离配置，避免测试收集顺序把默认业务库
# 绑定到全局 SessionLocal。库路径解析与 conftest.py 保持一致（含 ERP_TEST_DB
# 覆盖），否则并行跑测试时本文件会指向默认库、与另一个进程踩踏。
_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_OVERRIDE = os.environ.get("ERP_TEST_DB", "").strip()
_DB_FILE = pathlib.Path(_OVERRIDE) if _OVERRIDE else _BACKEND_DIR / "test_erp.db"
if not _DB_FILE.is_absolute():
    _DB_FILE = _BACKEND_DIR / _DB_FILE
os.environ.setdefault("ERP_DB_URL", "sqlite:///" + _DB_FILE.as_posix())
os.environ.setdefault("ERP_JWT_SECRET", "test-secret-at-least-32-bytes-long")
os.environ.setdefault("ERP_SUPERADMIN_PASSWORD", "root-test-123")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.pricing import PricingAgent
from app.db import Base
from app.models import (
    ExchangeRate,
    ForecastSnapshot,
    Listing,
    OpportunitySupplierMatch,
    Order,
    Product,
    RefundOrder,
    Supplier,
    SupplierCatalogProduct,
    SupplierOffer,
)
from app.services.commercial_analytics import metric_summary
from app.services.outcome_attribution import (
    reconcile_forecast_outcomes,
    reconcile_opportunity_attributions,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close(); engine.dispose()


def test_refunded_order_is_not_double_subtracted(db):
    order = Order(tenant_id=1, platform="shopee", external_no="R-1", qty=1,
                  amount=100, cost=40, currency="USD", status="refunded", source="api")
    db.add(order); db.flush()
    db.add(RefundOrder(tenant_id=1, refund_no="RF-1", order_id=order.id,
                       qty=1, amount=100, status="refunded"))
    db.commit()

    result = metric_summary(db, 1, 30)

    assert result["gmv"] == 100
    assert result["refund_amount"] == 100
    assert result["net_revenue"] == 0


def test_supplier_offer_currency_uses_traceable_fx_and_missing_fx_fails_closed(db):
    product = Product(tenant_id=1, sku="SKU-FX", title="FX product",
                      attrs={"sale_price": 100, "weight_kg": 0.3})
    supplier = Supplier(tenant_id=1, name="factory")
    db.add_all([product, supplier]); db.flush()
    offer = SupplierOffer(tenant_id=1, supplier_id=supplier.id, product_id=product.id,
                          price=10, currency="USD", in_stock=True)
    db.add(offer); db.commit()
    agent = PricingAgent.__new__(PricingAgent)
    agent.tenant_id, agent.db = 1, db

    with pytest.raises(ValueError, match="缺少 USD→CNY"):
        agent.cost_elements(product)

    db.add(ExchangeRate(tenant_id=1, base_currency="CNY", quote_currency="USD",
                        rate=0.14, effective_at=datetime.utcnow(), source="test"))
    db.commit()
    costs = agent.cost_elements(product)
    assert costs["purchase_cny"] == pytest.approx(10 / 0.14)


def test_forecast_outcome_uses_only_target_window_real_platform_orders(db):
    now = datetime.utcnow()
    product = Product(tenant_id=1, sku="SKU-F", title="forecast")
    db.add(product); db.flush()
    snapshot = ForecastSnapshot(tenant_id=1, product_id=product.id, version="test",
        training_cutoff=now - timedelta(days=14), target_start=now - timedelta(days=7),
        target_end=now - timedelta(days=1), dimensions={}, features={}, candidates=[],
        selected_model="mean", point_forecast=10, lower_bound=8, upper_bound=12)
    db.add(snapshot); db.flush()
    db.add_all([
        Order(tenant_id=1, platform="shopee", external_no="F-1", product_id=product.id,
              qty=9, amount=90, source="api", created_at=now - timedelta(days=3)),
        Order(tenant_id=1, platform="shopee", external_no="F-DEMO", product_id=product.id,
              qty=99, amount=990, source="demo", created_at=now - timedelta(days=3)),
        Order(tenant_id=1, platform="shopee", external_no="F-OLD", product_id=product.id,
              qty=50, amount=500, source="api", created_at=now - timedelta(days=10)),
    ]); db.commit()

    result = reconcile_forecast_outcomes(db, 1, now)

    assert result["evaluated"] == 1
    assert result["items"][0].actual_qty == 9
    assert result["items"][0].covered is True
    assert result["wape"] == pytest.approx(1 / 9, abs=0.0001)


def test_factory_opportunity_attributes_only_after_explicit_promotion(db):
    now = datetime.utcnow()
    product = Product(tenant_id=1, sku="SKU-O", title="opportunity")
    supplier = Supplier(tenant_id=1, name="factory", verification_status="verified")
    db.add_all([product, supplier]); db.flush()
    catalog = SupplierCatalogProduct(tenant_id=1, supplier_id=supplier.id,
        factory_sku="FAC-1", title="opportunity", unit_price=10)
    db.add(catalog); db.flush()
    promoted = OpportunitySupplierMatch(tenant_id=1, product_id=product.id,
        supplier_id=supplier.id, catalog_product_id=catalog.id, decision="ready",
        promoted_at=now - timedelta(days=5))
    unpromoted = OpportunitySupplierMatch(tenant_id=1, product_id=product.id,
        supplier_id=supplier.id, catalog_product_id=catalog.id + 1, decision="ready")
    db.add_all([promoted, unpromoted]); db.flush()
    listing = Listing(tenant_id=1, product_id=product.id, platform="shopee",
                      status="published", created_at=now - timedelta(days=4))
    order = Order(tenant_id=1, platform="shopee", external_no="O-1",
                  product_id=product.id, qty=2, amount=100, cost=40,
                  currency="USD", source="api", created_at=now - timedelta(days=2))
    db.add_all([listing, order]); db.commit()

    rows = reconcile_opportunity_attributions(db, 1, now)

    assert len(rows) == 1
    assert rows[0].match_id == promoted.id
    assert rows[0].published_listing_count == 1
    assert rows[0].order_count == 1
    assert rows[0].gmv_usd == 100
    assert rows[0].contribution_profit_usd == 60
