"""平台协议边界测试：不访问真实平台，只验证请求契约与数据归一化。"""
import time
from types import SimpleNamespace

import httpx
import pytest

from app.services.platform_adapters import (
    EbayAdapter,
    LazadaAdapter,
    ShopeeAdapter,
    TikTokAdapter,
    WalmartAdapter,
    platform_meta,
    request_with_retry,
)


def _shop(**overrides):
    values = {
        "app_key": "app-key",
        "app_secret": "app-secret",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "shop_id": "GCP_US_CIPHER",
        "status": "authorized",
        "token_expire_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_tiktok_signature_uses_path_sorted_query_and_body():
    adapter = TikTokAdapter(None, _shop())
    first = adapter._sign("/order/202309/orders/search", {
        "timestamp": 1700000000, "shop_cipher": "cipher", "app_key": "key",
    }, '{"create_time_ge":1}')
    second = adapter._sign("/order/202309/orders/search", {
        "app_key": "key", "shop_cipher": "cipher", "timestamp": 1700000000,
    }, '{"create_time_ge":1}')
    assert first == second
    assert len(first) == 64


def test_shopee_listing_readiness_checks_real_shop_requirements(monkeypatch):
    adapter = ShopeeAdapter(None, _shop(tenant_id=1, shop_id="10001"))
    listing = SimpleNamespace(platform="shopee", language="en")
    product = SimpleNamespace(
        category="家居", images=["https://cdn.example.com/1.jpg"],
        attrs={"sale_price": 19.9, "onhand": 10, "weight_kg": 0.5,
               "shopee_attributes": [{"attribute_id": 100, "value_list": [{"value_id": 1}]}]})
    monkeypatch.setattr(
        "app.services.platform_adapters.category_mapping_for", lambda *args: "100642")

    def fake_call(path, **kwargs):
        assert kwargs["method"] == "GET"
        if path.endswith("get_shop_info"):
            return {"region": "SG"}
        if path.endswith("get_channel_list"):
            return {"logistics_channel_list": [
                {"logistics_channel_id": 80001, "enabled": True}]}
        if path.endswith("get_attributes"):
            assert kwargs["business_query"]["category_id"] == 100642
            return {"attribute_list": [
                {"attribute_id": 100, "is_mandatory": True,
                 "original_attribute_name": "Material"}]}
        raise AssertionError(path)

    monkeypatch.setattr(adapter, "_call", fake_call)
    result = adapter.listing_readiness(listing, product)
    assert result["ready"] is True
    assert result["shop_region"] == "SG"
    assert result["enabled_logistics"] == [80001]


def test_tiktok_token_expiry_accepts_epoch_or_duration():
    now = int(time.time())
    assert 3500 <= TikTokAdapter._expiry_seconds(now + 3600) <= 3600
    assert TikTokAdapter._expiry_seconds(7200) == 7200


def test_tiktok_order_normalization_uses_202309_contract(monkeypatch):
    adapter = TikTokAdapter(None, _shop())
    captured = {}

    def fake_call(method, path, **kwargs):
        captured.update(method=method, path=path, **kwargs)
        return {"orders": [{
            "id": "576461413038785752",
            "status": "AWAITING_SHIPMENT",
            "payment": {"total_amount": "29.95", "currency": "USD"},
            "line_items": [{"quantity": 2}, {"quantity": 1}],
            "recipient_address": {"name": "Buyer"},
        }]}

    monkeypatch.setattr(adapter, "_call", fake_call)
    orders = adapter.fetch_orders(days=3)

    assert captured["method"] == "POST"
    assert captured["path"] == "/order/202309/orders/search"
    assert captured["query"]["shop_cipher"] == "GCP_US_CIPHER"
    assert orders[0].external_no == "576461413038785752"
    assert orders[0].qty == 3
    assert orders[0].status == "paid"
    assert orders[0].currency == "USD"
    assert orders[0].country == "US"


def test_tiktok_cross_border_listing_readiness(monkeypatch):
    adapter = TikTokAdapter(None, _shop(tenant_id=1))
    listing = SimpleNamespace(platform="tiktok", language="en-US")
    product = SimpleNamespace(
        category="家居", images=["https://cdn.example.com/1.jpg"],
        attrs={"sale_price": 29.9, "onhand": 10, "weight_kg": 0.8,
               "length_cm": 20, "width_cm": 15, "height_cm": 8,
               "tiktok_product_attributes": [{"id": "material", "values": ["wood"]}],
               "tiktok_certifications": [{"id": "cert"}]})
    monkeypatch.setattr(
        "app.services.platform_adapters.category_mapping_for",
        lambda *args: "600001")
    monkeypatch.setattr(adapter, "_call", lambda *args, **kwargs: {
        "product_certifications": [{"id": "cert", "name": "Safety", "is_required": True}],
        "size_chart": {"is_required": False},
    })

    result = adapter.listing_readiness(listing, product)

    assert result["ready"] is True
    assert result["mode"] == "cross_border_global_product"
    assert result["category_version"] == "v2"
    assert result["category_id"] == "600001"


def test_ebay_order_normalization():
    order = EbayAdapter._normalize_order({
        "orderId": "12-34567-89012",
        "orderPaymentStatus": "PAID",
        "orderFulfillmentStatus": "NOT_STARTED",
        "pricingSummary": {"total": {"value": "49.90", "currency": "USD"}},
        "lineItems": [{"quantity": 2}, {"quantity": 1}],
        "buyer": {"username": "buyer-1"},
        "fulfillmentStartInstructions": [{"shippingStep": {"shipTo": {
            "contactAddress": {"countryCode": "US"}}}}],
    })
    assert order.external_no == "12-34567-89012"
    assert order.qty == 3
    assert order.amount == 49.9
    assert order.status == "paid"
    assert order.country == "US"


def test_tiktok_cursor_pagination(monkeypatch):
    adapter = TikTokAdapter(None, _shop())
    calls = []
    def fake_call(method, path, **kw):
        calls.append(kw["query"].get("page_token"))
        n = len(calls)
        return {"orders": [{"id": str(n), "payment": {"total_amount": "1"}}],
                "next_page_token": "next" if n == 1 else ""}
    monkeypatch.setattr(adapter, "_call", fake_call)
    assert [o.external_no for o in adapter.fetch_orders()] == ["1", "2"]
    assert calls == [None, "next"]


def test_ebay_offset_pagination(monkeypatch):
    adapter = EbayAdapter(None, _shop())
    offsets = []
    class Response:
        content = b"{}"
        def raise_for_status(self): pass
        def json(self):
            offset = offsets[-1]
            return {"total": 2, "orders": [{"orderId": str(offset + 1),
                    "orderPaymentStatus": "PAID"}]}
    def fake_request(method, url, **kw):
        offsets.append(kw["params"]["offset"]); return Response()
    monkeypatch.setattr("app.services.platform_adapters.request_with_retry", fake_request)
    assert len(adapter.fetch_orders()) == 2
    assert offsets == [0, 1]


def test_walmart_cursor_and_lazada_offset_pagination(monkeypatch):
    walmart = WalmartAdapter(None, _shop())
    walmart_calls = []
    def walmart_call(method, path, **kw):
        walmart_calls.append(kw["params"])
        if len(walmart_calls) == 1:
            return {"list": {"meta": {"nextCursor": "?page=2"},
                    "elements": {"order": [{"purchaseOrderId": "w1"}]}}}
        return {"list": {"meta": {}, "elements": {"order": [{"purchaseOrderId": "w2"}]}}}
    monkeypatch.setattr(walmart, "_call", walmart_call)
    assert [o.external_no for o in walmart.fetch_orders()] == ["w1", "w2"]
    assert walmart_calls[1] == {"page": "2"}

    lazada = LazadaAdapter(None, _shop(shop_id="SG"))
    offsets = []
    def lazada_call(method, path, params):
        offsets.append(params["offset"])
        return {"total_count": 2, "orders": [{"order_id": f"l{len(offsets)}"}]}
    monkeypatch.setattr(lazada, "_call", lazada_call)
    assert [o.external_no for o in lazada.fetch_orders()] == ["l1", "l2"]
    assert offsets == ["0", "1"]


def test_retry_only_for_safe_requests(monkeypatch):
    statuses = [429, 503, 200]
    calls = []
    class Response:
        headers = {}
        def __init__(self, status): self.status_code = status
    monkeypatch.setattr("app.services.platform_adapters.httpx.request",
                        lambda *a, **kw: calls.append(a[0]) or Response(statuses.pop(0)))
    monkeypatch.setattr("app.services.platform_adapters.time.sleep", lambda *_: None)
    assert request_with_retry("GET", "https://sandbox.test").status_code == 200
    assert len(calls) == 3
    calls.clear(); statuses[:] = [503, 200]
    assert request_with_retry("POST", "https://sandbox.test").status_code == 503
    assert len(calls) == 1


def test_timeout_retry_and_expired_token(monkeypatch):
    attempts = []
    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectTimeout("timeout")
        return SimpleNamespace(status_code=200, headers={})
    monkeypatch.setattr("app.services.platform_adapters.httpx.request", flaky)
    monkeypatch.setattr("app.services.platform_adapters.time.sleep", lambda *_: None)
    assert request_with_retry("GET", "https://sandbox.test").status_code == 200
    assert len(attempts) == 3

    from datetime import datetime, timedelta
    adapter = EbayAdapter(None, _shop(token_expire_at=datetime.utcnow() - timedelta(seconds=1)))
    with pytest.raises(Exception, match="已过期"):
        adapter._ensure_authorized()


def test_tiktok_partial_success_resumes_from_global_product(monkeypatch):
    adapter = TikTokAdapter(None, _shop(tenant_id=1))
    listing = SimpleNamespace(title="Title", description="Desc")
    product = SimpleNamespace(id=1, sku="SKU1", images=["https://x/1.jpg"], attrs={
        "onhand": 1, "sale_price": 10, "weight_kg": 1,
        "length_cm": 1, "width_cm": 1, "height_cm": 1,
        "tiktok_product_attributes": []})
    monkeypatch.setattr(adapter, "listing_readiness", lambda *a: {"ready": True,
                                                                  "category_id": "10"})
    paths = []
    monkeypatch.setattr(adapter, "_call", lambda method, path, **kw:
                        paths.append(path) or {"product_ids": ["p1"]})
    checkpoints = []
    result = adapter.publish_listing(listing, product,
        resume={"image_uris": [{"uri": "u1"}], "global_product_id": "gp-existing"},
        checkpoint=lambda value: checkpoints.append(value))
    assert result.external_id == "gp-existing"
    assert paths == ["/product/202309/global_products/gp-existing/publish"]


def test_researched_platforms_are_explicitly_gated():
    items = {item["platform"]: item for item in platform_meta()}
    # 原断言 `in ("planned","restricted")` 无法发现两平台状态互换（都落在允许集内）。
    # 改为逐平台精确期望值：状态是「能否开放给客户」的产品承诺，必须钉死。
    expected_status = {"aliexpress": "planned", "temu": "restricted",
                       "shopify": "planned", "mercadolibre": "planned",
                       "shein": "restricted"}
    for name, status in expected_status.items():
        assert items[name]["integration_status"] == status, \
            f"{name} 集成状态应为 {status}，实际 {items[name]['integration_status']}"
        assert items[name]["can_order_sync"] is False
        assert items[name]["can_publish"] is False
        assert items[name]["docs"].startswith("https://")
    assert items["ebay"]["can_order_sync"] is True
    for name in ("tiktok", "ebay", "walmart", "lazada"):
        assert items[name]["integration_status"] == "protocol_ready_unverified"
        assert items[name]["can_order_sync"] is True
        assert items[name]["can_publish"] is True
