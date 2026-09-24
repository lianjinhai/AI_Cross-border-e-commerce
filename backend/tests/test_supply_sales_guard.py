"""Supply/Sales 边界回归：禁止 source（货源）店铺产生销售订单。

会话级夹具由 tests/conftest.py 自动注入，本模块不 import 其它测试模块
（规范 §8 T-2：测试不得依赖执行顺序）。
"""
import uuid

_GUARD_KEYWORD = "货源店铺(source)不能同步销售订单"


def _ext_no(tag: str) -> str:
    """唯一订单号：测试库在同一会话/多次运行间复用，避免按单号去重造成误判。"""
    return f"{tag}-{uuid.uuid4().hex[:10].upper()}"


def _create_shop(client, headers, **payload):
    r = client.post("/api/shops", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_source_shop_rejects_sales_order_sync(client, auth_headers):
    """货源店铺（source）不能作为销售订单来源：店铺级拉单必须 400。"""
    shop = _create_shop(client, auth_headers, platform="1688",
                        shop_name="守门-1688 货源店", role="source", is_demo=True)
    try:
        r = client.post(f"/api/shops/{shop['id']}/sync_orders", headers=auth_headers)
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert _GUARD_KEYWORD in detail
        assert "销售店铺" in detail
        # 守门必须发生在拉单之前：不得落库任何订单
        assert "synced" not in r.json()
    finally:
        client.delete(f"/api/shops/{shop['id']}", headers=auth_headers)


def test_sales_shop_sync_succeeds(client, auth_headers):
    """销售店铺（sales）演示拉单正常：守门不能误伤正常路径。"""
    shop = _create_shop(client, auth_headers, platform="shopee",
                        shop_name="守门-Shopee 销售店", role="sales", is_demo=True)
    try:
        r = client.post(f"/api/shops/{shop['id']}/sync_orders", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "demo" and body["synced"] == 5
        # 演示订单不携带 shop_id（mock 订单无店铺归属），按平台+单号去重
        assert len(body["items"]) == 5
    finally:
        client.delete(f"/api/shops/{shop['id']}", headers=auth_headers)


def test_platform_sync_rejects_when_only_source_shops(client, auth_headers):
    """按 platform 同步且该平台只有 source 店铺 -> 400（覆盖平台命中货源店铺）。"""
    # 选一个当前租户尚无销售店铺的平台，保证"该平台只有 source 店铺"这一前提成立
    shops = client.get("/api/shops", headers=auth_headers).json()["items"]
    sales_platforms = {s["platform"] for s in shops if s["role"] == "sales"}
    candidates = ["tiktok", "walmart", "lazada", "amazon", "ebay"]
    platform = next(p for p in candidates if p not in sales_platforms)
    shop = _create_shop(client, auth_headers, platform=platform,
                        shop_name=f"守门-{platform} 货源店", role="source", is_demo=True)
    try:
        r = client.post("/api/orders/sync", headers=auth_headers,
                        json={"platform": f"demo:{platform}", "count": 2})
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert _GUARD_KEYWORD in detail
        assert "销售店铺" in detail
    finally:
        client.delete(f"/api/shops/{shop['id']}", headers=auth_headers)


def test_platform_sync_rejects_source_platform(client, auth_headers):
    """货源平台（1688）无论店铺配置如何都禁止作为销售订单来源。"""
    r = client.post("/api/orders/sync", headers=auth_headers,
                    json={"platform": "demo:1688", "count": 1})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert _GUARD_KEYWORD in detail
    assert "1688" in detail


def test_csv_import_rejects_source_shop(client, auth_headers):
    """CSV 导入指定 shop_id 且该店铺为货源店铺 -> 400。"""
    shop = _create_shop(client, auth_headers, platform="1688",
                        shop_name="守门-CSV 货源店", role="source")
    ext_no = _ext_no("GUARD-CSV-SRC")
    try:
        r = client.post("/api/orders/import", headers=auth_headers,
                        json={"shop_id": shop["id"],
                              "csv_text": ("external_no,platform,amount\n"
                                           f"{ext_no},1688,30")})
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert _GUARD_KEYWORD in detail
        # 被拒绝后不得落库
        found = client.get("/api/orders", headers=auth_headers,
                           params={"keyword": ext_no}).json()
        assert found["total"] == 0
    finally:
        client.delete(f"/api/shops/{shop['id']}", headers=auth_headers)


def test_csv_import_to_sales_shop_succeeds(client, auth_headers):
    """CSV 导入指定 sales 店铺正常通过，且订单归属该店铺。"""
    shop = _create_shop(client, auth_headers, platform="shopee",
                        shop_name="守门-CSV 销售店", role="sales")
    ext_no = _ext_no("GUARD-CSV-SALES")
    try:
        r = client.post("/api/orders/import", headers=auth_headers,
                        json={"shop_id": shop["id"],
                              "csv_text": ("external_no,platform,amount\n"
                                           f"{ext_no},shopee,45")})
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 1, r.json()
        found = client.get("/api/orders", headers=auth_headers,
                           params={"keyword": ext_no}).json()["items"]
        assert len(found) == 1
        assert found[0]["shop_id"] == shop["id"]   # 归属到指定销售店铺
    finally:
        client.delete(f"/api/shops/{shop['id']}", headers=auth_headers)


def test_csv_import_unknown_shop_is_404(client, auth_headers):
    """CSV 导入指定不存在/非本租户店铺 -> 404（不泄漏他租户店铺）。"""
    r = client.post("/api/orders/import", headers=auth_headers,
                    json={"shop_id": 999999,
                          "csv_text": ("external_no,platform,amount\n"
                                       f"{_ext_no('GUARD-CSV-404')},shopee,10")})
    assert r.status_code == 404
    assert r.json()["detail"] == "店铺不存在"


def test_read_only_order_endpoints_not_gated(client, auth_headers):
    """只读操作不设 Supply/Sales 门禁：列表与导出保持可用。"""
    assert client.get("/api/orders", headers=auth_headers).status_code == 200
    exported = client.get("/api/orders/export", headers=auth_headers)
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")


def test_shop_role_validation(client, auth_headers):
    """创建店铺只接受 source/sales，非法值 400，缺省按平台推导。"""
    bad = client.post("/api/shops", headers=auth_headers,
                      json={"platform": "shopee", "role": "supplier"})
    assert bad.status_code == 400
    assert "source" in bad.json()["detail"] and "sales" in bad.json()["detail"]

    inferred_source = _create_shop(client, auth_headers, platform="1688",
                                   shop_name="守门-缺省 1688 店")
    inferred_sales = _create_shop(client, auth_headers, platform="shopee",
                                  shop_name="守门-缺省 Shopee 店")
    try:
        assert inferred_source["role"] == "source"
        assert inferred_sales["role"] == "sales"
    finally:
        client.delete(f"/api/shops/{inferred_source['id']}", headers=auth_headers)
        client.delete(f"/api/shops/{inferred_sales['id']}", headers=auth_headers)
