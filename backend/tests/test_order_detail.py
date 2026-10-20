"""S5：订单单条详情与真实关联（行/费用/采购/退款/履约）的口径与范围。

为什么单测这条：订单列表只能看到订单头，采购单（CNY 应付）与订单成本（订单币种快照）
是两套口径；没有详情接口时，前端只能拿列表行去猜关联，既算不清也不敢算。
"""
from app.db import SessionLocal
from app.models import (
    Order,
    OrderFee,
    OrderLine,
    Product,
    PurchaseOrder,
    RefundOrder,
    Shop,
    Supplier,
    Tenant,
    User,
)


def _tenant_id(db):
    return db.query(User).filter(User.username == "admin").first().tenant_id


def _seed(db, external_no, *, currency="USD", tracking_no="", shop=True):
    tenant_id = _tenant_id(db)
    shop_row = None
    if shop:
        shop_row = Shop(tenant_id=tenant_id, platform="shopee",
                        shop_name=f"S5 详情店 {external_no}", role="sales", status="authorized")
        db.add(shop_row)
        db.flush()
    product = Product(tenant_id=tenant_id, sku=f"S5-{external_no}",
                      title=f"S5 商品 {external_no}", status="active")
    supplier = Supplier(tenant_id=tenant_id, name=f"S5 供应商 {external_no}")
    db.add_all([product, supplier])
    db.flush()

    order = Order(tenant_id=tenant_id, shop_id=shop_row.id if shop_row else None,
                  platform="shopee", external_no=external_no, product_id=product.id,
                  qty=2, amount=120.0, cost=70.0, profit=50.0, currency=currency,
                  status="shipped", tracking_no=tracking_no, source="import")
    db.add(order)
    db.flush()
    db.add_all([
        OrderLine(tenant_id=tenant_id, order_id=order.id, external_line_no="1",
                  product_id=product.id, sku=product.sku, title=product.title,
                  qty=2, unit_price=60, product_cost=35, currency=currency),
        OrderFee(tenant_id=tenant_id, order_id=order.id, fee_type="commission",
                 amount=12.5, currency=currency, source="platform"),
        OrderFee(tenant_id=tenant_id, order_id=order.id, fee_type="shipping",
                 amount=8.0, currency=currency, source="platform"),
        PurchaseOrder(tenant_id=tenant_id, po_no=f"PO-{external_no}", supplier_id=supplier.id,
                      product_id=product.id, sales_order_id=order.id, qty=2,
                      unit_price=45.0, total=90.0, status="received", purchase_type="stock"),
        RefundOrder(tenant_id=tenant_id, refund_no=f"RF-{external_no}", order_id=order.id,
                    qty=1, amount=30.0, reason="尺寸不符", status="pending"),
    ])
    db.commit()
    return order.id, tenant_id


def test_order_detail_returns_real_links_without_mixing_currencies(client, auth_headers):
    with SessionLocal() as db:
        order_id, _ = _seed(db, "S5-DETAIL-1", tracking_no="SF1234567890")

    body = client.get(f"/api/orders/{order_id}", headers=auth_headers).json()
    order = body["order"]
    assert order["shop_name"].startswith("S5 详情店") and order["product_title"].startswith("S5 商品")
    assert order["source"] == "import"

    assert len(body["lines"]) == 1 and body["lines"][0]["qty"] == 2
    assert body["fees"]["total_by_currency"] == {"USD": 20.5}
    assert len(body["purchases"]["items"]) == 1
    assert body["purchases"]["items"][0]["sales_order_id"] == order_id
    assert body["purchases"]["total_by_currency"] == {"CNY": 90.0}
    assert body["purchases"]["link"] == "purchase_orders.sales_order_id"
    assert "不可相加" in body["purchases"]["note"]

    # 两套口径必须分开：订单金额是 USD 原值，采购是 CNY 应付，绝不合并成一个数。
    totals = body["totals"]
    assert totals["currency"] == "USD" and totals["amount"] == 120.0
    assert totals["purchases_by_currency"] == {"CNY": 90.0}
    assert totals["mixed_currency"] is True
    assert "未做汇率换算" in body["source"]["honesty"]

    assert body["refunds"] and body["refunds"][0]["refund_no"] == "RF-S5-DETAIL-1"


def test_fulfillment_does_not_fabricate_tracking(client, auth_headers):
    """有单号但轨迹未接入：只回单号，明确 tracking_available=false。"""
    with SessionLocal() as db:
        order_id, _ = _seed(db, "S5-TRACK-1", tracking_no="SF999")

    body = client.get(f"/api/orders/{order_id}", headers=auth_headers).json()
    assert body["fulfillment"]["tracking_no"] == "SF999"
    assert body["fulfillment"]["tracking_available"] is False
    assert "未接入" in body["fulfillment"]["note"]


def test_order_detail_denies_other_tenant_and_missing(client, auth_headers):
    with SessionLocal() as db:
        tenant = Tenant(name="S5 别的租户")
        db.add(tenant)
        db.flush()
        other = Order(tenant_id=tenant.id, platform="shopee", external_no="S5-OTHER-1",
                      amount=10, cost=1, profit=9, currency="USD", status="paid")
        db.add(other)
        db.commit()
        other_id = other.id

    assert client.get(f"/api/orders/{other_id}", headers=auth_headers).status_code == 404
    assert client.get("/api/orders/99999999", headers=auth_headers).status_code == 404


def test_read_only_can_view_detail_but_not_ship(client, auth_headers):
    with SessionLocal() as db:
        order_id, _ = _seed(db, "S5-RO-1")

    viewer = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    assert viewer.status_code == 200
    vh = {"Authorization": f"Bearer {viewer.json()['token']}"}
    assert client.get(f"/api/orders/{order_id}", headers=vh).status_code == 200
    assert client.post(f"/api/orders/{order_id}/ship", headers=vh).status_code == 403
