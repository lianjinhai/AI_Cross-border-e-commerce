"""订单列表 P0 正确性：shop_id 筛选隔离 + 店铺名/商品标题富化。

B1 批次修复点（见 backend/app/routers/orders.py）：
  1. GET /api/orders 现支持 shop_id 查询参数，按当前租户 + 店铺 ID 隔离；
  2. 每个当页条目附带 shop_name / product_title（最多两次额外批量查询，无 N+1）。

本文件此前不存在（仅有 orders 路由无专属测试），沿用 conftest 的 client / auth_headers
夹具与 SessionLocal 直写模式（与 test_ai_native_p0.py 一致）。

注意：会话级测试库由 conftest._fresh_db 管理，单实例；与并发 pytest 进程互斥。
"""
from app.db import SessionLocal
from app.models import Order, Product, Shop, User


def _tenant_id(db):
    return db.query(User).filter(User.username == "admin").first().tenant_id


def _make_shop(db, tenant_id, name, platform="shopee"):
    s = Shop(tenant_id=tenant_id, platform=platform, shop_name=name, role="sales",
             status="authorized")
    db.add(s)
    db.flush()
    return s


def _make_product(db, tenant_id, title):
    p = Product(tenant_id=tenant_id, sku=f"SKU-{title}", title=title, status="active")
    db.add(p)
    db.flush()
    return p


def test_shop_id_filter_isolates_two_shops(client, auth_headers):
    """shop_id 筛选必须隔离：shop A 的订单不会出现在 shop B 的筛选结果里。"""
    db = SessionLocal()
    try:
        tenant_id = _tenant_id(db)
        shop_a = _make_shop(db, tenant_id, "深圳仓A")
        shop_b = _make_shop(db, tenant_id, "深圳仓B")
        prod = _make_product(db, tenant_id, "测试商品")
        db.commit()

        for i in range(3):
            db.add(Order(tenant_id=tenant_id, shop_id=shop_a.id, platform="shopee",
                         external_no=f"SA-{i}", product_id=prod.id, qty=1,
                         amount=100.0 + i, cost=60.0, profit=40.0 + i,
                         currency="CNY", status="paid"))
        for i in range(2):
            db.add(Order(tenant_id=tenant_id, shop_id=shop_b.id, platform="shopee",
                         external_no=f"SB-{i}", product_id=prod.id, qty=1,
                         amount=200.0 + i, cost=120.0, profit=80.0 + i,
                         currency="USD", status="paid"))
        db.commit()

        # 仅筛选 shop A
        r = client.get("/api/orders", headers=auth_headers,
                       params={"shop_id": shop_a.id, "page_size": 200})
        assert r.status_code == 200, r.text
        body = r.json()
        ext_nos = {it["external_no"] for it in body["items"]}
        assert ext_nos == {f"SA-{i}" for i in range(3)}, ext_nos
        assert all(it["shop_id"] == shop_a.id for it in body["items"])

        # 仅筛选 shop B
        r = client.get("/api/orders", headers=auth_headers,
                       params={"shop_id": shop_b.id, "page_size": 200})
        assert r.status_code == 200, r.text
        body = r.json()
        ext_nos = {it["external_no"] for it in body["items"]}
        assert ext_nos == {f"SB-{i}" for i in range(2)}, ext_nos
        assert all(it["shop_id"] == shop_b.id for it in body["items"])

        # 不放 shop_id 时不筛选（全部店铺，至少 5 条）
        r = client.get("/api/orders", headers=auth_headers, params={"page_size": 200})
        assert r.status_code == 200, r.text
        all_nos = {it["external_no"] for it in r.json()["items"]}
        assert {f"SA-{i}" for i in range(3)}.issubset(all_nos)
        assert {f"SB-{i}" for i in range(2)}.issubset(all_nos)
    finally:
        db.close()


def test_list_orders_enriches_shop_name_and_product_title(client, auth_headers):
    """当页条目应带 shop_name / product_title 富化（缺失时为 ""，不报错）。"""
    db = SessionLocal()
    try:
        tenant_id = _tenant_id(db)
        shop = _make_shop(db, tenant_id, "富化验证店")
        prod = _make_product(db, tenant_id, "富化验证商品")
        db.commit()
        db.add(Order(tenant_id=tenant_id, shop_id=shop.id, platform="shopee",
                     external_no="ENR-1", product_id=prod.id, qty=1,
                     amount=50.0, cost=30.0, profit=20.0,
                     currency="CNY", status="paid"))
        # 无店铺、无商品关联的订单：富化字段应为空串
        db.add(Order(tenant_id=tenant_id, shop_id=None, platform="shopee",
                     external_no="ENR-2", product_id=None, qty=1,
                     amount=10.0, cost=5.0, profit=5.0,
                     currency="USD", status="paid"))
        db.commit()

        r = client.get("/api/orders", headers=auth_headers,
                       params={"page_size": 200, "keyword": "ENR"})
        assert r.status_code == 200, r.text
        items = {it["external_no"]: it for it in r.json()["items"]}
        assert items["ENR-1"]["shop_name"] == "富化验证店"
        assert items["ENR-1"]["product_title"] == "富化验证商品"
        assert items["ENR-2"]["shop_name"] == ""
        assert items["ENR-2"]["product_title"] == ""
    finally:
        db.close()
