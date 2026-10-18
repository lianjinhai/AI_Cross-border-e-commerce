"""订单列表店铺范围端到端鉴权（决策 D63）。

本文件与 test_orders.py 的关系：test_orders.py 验证 B1 的「shop_id 筛选 + 富化」P0 正确性，
本文件专门验证「范围必须是服务端鉴权出来的」这一安全属性——跨租户 404、货源店 400、
no-shop_id 默认不变、scope 回显、切换稳定无泄漏。两者关注点不同，且本文件不改动 B1 已
提交的 test_orders.py（避免污染其验收基线），故独立成新文件。

夹具沿用 conftest 的 client / auth_headers（与全仓一致）。测试库为会话级单实例，
与并发 pytest 进程互斥；因此所有写入都用唯一前缀避免 UNIQUE(tenant,shop,platform,external_no)
撞键。不清理数据——与 test_orders.py 一样靠唯一标识隔离。
"""
from app.db import SessionLocal
from app.models import Order, Product, Shop, Tenant


def _admin_tenant_id(db):
    from app.models import User
    return db.query(User).filter(User.username == "admin").first().tenant_id


def _make_shop(db, tenant_id, name, role="sales", platform="shopee"):
    s = Shop(tenant_id=tenant_id, platform=platform, shop_name=name,
             role=role, status="authorized")
    db.add(s)
    db.flush()
    return s


def _make_product(db, tenant_id, title):
    p = Product(tenant_id=tenant_id, sku=f"SKU-{title}", title=title, status="active")
    db.add(p)
    db.flush()
    return p


def _add_order(db, tenant_id, shop_id, external_no, product_id=None,
               platform="shopee", amount=100.0, cost=60.0):
    db.add(Order(tenant_id=tenant_id, shop_id=shop_id, platform=platform,
                 external_no=external_no, product_id=product_id, qty=1,
                 amount=amount, cost=cost, profit=amount - cost,
                 currency="USD", status="paid"))


def test_shop_id_filter_isolates_and_returns_scope(client, auth_headers):
    """同租户下按 shop_id 过滤只返回该店订单，且回显 scope(店铺名)。"""
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        shop_a = _make_shop(db, tenant_id, "鉴权店A")
        shop_b = _make_shop(db, tenant_id, "鉴权店B")
        prod = _make_product(db, tenant_id, "鉴权商品")
        db.commit()
        for i in range(3):
            _add_order(db, tenant_id, shop_a.id, f"SCOPE-A-{i}", prod.id)
        for i in range(2):
            _add_order(db, tenant_id, shop_b.id, f"SCOPE-B-{i}", prod.id)
        db.commit()

        r = client.get("/api/orders", headers=auth_headers,
                       params={"shop_id": shop_a.id, "page_size": 200})
        assert r.status_code == 200, r.text
        body = r.json()
        # 既有 key 不被破坏
        assert set(["items", "total", "page", "page_size", "scope"]).issubset(body.keys())
        ext_nos = {it["external_no"] for it in body["items"]}
        assert ext_nos == {f"SCOPE-A-{i}" for i in range(3)}, ext_nos
        assert all(it["shop_id"] == shop_a.id for it in body["items"])
        # scope 回显的是被鉴权命中的店
        assert body["scope"]["shop_id"] == shop_a.id
        assert body["scope"]["shop_name"] == "鉴权店A"

        r = client.get("/api/orders", headers=auth_headers,
                       params={"shop_id": shop_b.id, "page_size": 200})
        assert r.status_code == 200, r.text
        ext_nos = {it["external_no"] for it in r.json()["items"]}
        assert ext_nos == {f"SCOPE-B-{i}" for i in range(2)}, ext_nos
        assert r.json()["scope"]["shop_name"] == "鉴权店B"
    finally:
        db.close()


def test_cross_tenant_shop_returns_404(client, auth_headers):
    """跨租户/工作区的 shop_id 必须 404，绝不 200+空集或返回他租户行。"""
    db = SessionLocal()
    try:
        admin_tenant = _admin_tenant_id(db)
        other = Tenant(name="他人工作区")
        db.add(other)
        db.flush()
        # 保持「租户 ↔ workspace_profile 1:1 配对」不变量：裸建 Tenant 会让
        # profile 自增 id 与 tenant id 错位，弄断 test_membership_write 的
        # workspace_id == tenant_id 金丝雀断言（全量回归实测过）。
        from app.services.membership_service import ensure_workspace_profile
        ensure_workspace_profile(db, other.id, other.name)
        other_shop = _make_shop(db, other.id, "他人店铺")
        db.commit()
        # 在他人租户下真实写入一条订单，证明数据存在但应被范围闸拒绝
        _add_order(db, other.id, other_shop.id, "XTEN-ORDER-1")
        db.commit()

        r = client.get("/api/orders", headers=auth_headers,
                       params={"shop_id": other_shop.id, "page_size": 200})
        # 决策 D63：跨租户 → 明确 404（不是 200+空，也不是 200+他租户行）
        assert r.status_code == 404, r.text
        assert "店铺不存在或无访问权限" in r.json()["detail"]

        # 即便不加 shop_id，他租户行也绝不会出现在本租户列表中（tenant 过滤为第二层）
        r2 = client.get("/api/orders", headers=auth_headers, params={"page_size": 200})
        assert r2.status_code == 200, r2.text
        all_nos = {it["external_no"] for it in r2.json()["items"]}
        assert "XTEN-ORDER-1" not in all_nos
    finally:
        db.close()


def test_source_shop_returns_400(client, auth_headers):
    """货源(source)店铺 id 必须 400，且文案与 import 路径一致。"""
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        source_shop = _make_shop(db, tenant_id, "货源店1688", role="source",
                                 platform="1688")
        db.commit()

        r = client.get("/api/orders", headers=auth_headers,
                       params={"shop_id": source_shop.id, "page_size": 200})
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "货源店铺" in detail and "sales" in detail, detail
    finally:
        db.close()


def test_no_shop_id_preserves_b1_default(client, auth_headers):
    """不传 shop_id：行为不变——返回本租户全部订单，scope 为 None。"""
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        shop_a = _make_shop(db, tenant_id, "默认店A")
        shop_b = _make_shop(db, tenant_id, "默认店B")
        prod = _make_product(db, tenant_id, "默认商品")
        db.commit()
        for i in range(2):
            _add_order(db, tenant_id, shop_a.id, f"DEF-A-{i}", prod.id)
        for i in range(2):
            _add_order(db, tenant_id, shop_b.id, f"DEF-B-{i}", prod.id)
        db.commit()

        r = client.get("/api/orders", headers=auth_headers, params={"page_size": 200})
        assert r.status_code == 200, r.text
        body = r.json()
        ext_nos = {it["external_no"] for it in body["items"]}
        # 两家店的订单都在（不过滤）
        assert {f"DEF-A-{i}" for i in range(2)}.issubset(ext_nos)
        assert {f"DEF-B-{i}" for i in range(2)}.issubset(ext_nos)
        # scope 为 None 表示「全店」
        assert body["scope"]["shop_id"] is None
        assert body["scope"]["shop_name"] is None
    finally:
        db.close()


def test_enrichment_still_correct_per_row(client, auth_headers):
    """带 shop_id 过滤时，当页富化 shop_name/product_title 仍正确（缺失回退 ""）。"""
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        shop = _make_shop(db, tenant_id, "富化店X")
        prod = _make_product(db, tenant_id, "富化商品X")
        db.commit()
        _add_order(db, tenant_id, shop.id, "ENR-X-1", prod.id)
        # 无店铺、无商品关联：富化字段应为空串
        _add_order(db, tenant_id, None, "ENR-X-2", None)
        db.commit()

        r = client.get("/api/orders", headers=auth_headers,
                       params={"shop_id": shop.id, "page_size": 200,
                               "keyword": "ENR-X"})
        assert r.status_code == 200, r.text
        items = {it["external_no"]: it for it in r.json()["items"]}
        # 仅返回该店订单（ENR-X-2 无 shop_id，被 shop_id 过滤排除）
        assert "ENR-X-1" in items
        assert "ENR-X-2" not in items
        assert items["ENR-X-1"]["shop_name"] == "富化店X"
        assert items["ENR-X-1"]["product_title"] == "富化商品X"
    finally:
        db.close()


def test_switch_shop_a_to_b_to_a_stable(client, auth_headers):
    """A→B→A 连续切换：每次都只返回目标店，无上一次请求的残留泄漏。"""
    db = SessionLocal()
    try:
        tenant_id = _admin_tenant_id(db)
        shop_a = _make_shop(db, tenant_id, "稳定店A")
        shop_b = _make_shop(db, tenant_id, "稳定店B")
        prod = _make_product(db, tenant_id, "稳定商品")
        db.commit()
        for i in range(3):
            _add_order(db, tenant_id, shop_a.id, f"STAB-A-{i}", prod.id)
        for i in range(3):
            _add_order(db, tenant_id, shop_b.id, f"STAB-B-{i}", prod.id)
        db.commit()

        def _ext_nos(shop_id):
            r = client.get("/api/orders", headers=auth_headers,
                           params={"shop_id": shop_id, "page_size": 200})
            assert r.status_code == 200, r.text
            return {it["external_no"] for it in r.json()["items"]}

        assert _ext_nos(shop_a.id) == {f"STAB-A-{i}" for i in range(3)}
        assert _ext_nos(shop_b.id) == {f"STAB-B-{i}" for i in range(3)}
        # 回到 A：必须是 A 的集合，绝不能混入 B
        back = _ext_nos(shop_a.id)
        assert back == {f"STAB-A-{i}" for i in range(3)}
        assert not any(n.startswith("STAB-B-") for n in back)
    finally:
        db.close()
