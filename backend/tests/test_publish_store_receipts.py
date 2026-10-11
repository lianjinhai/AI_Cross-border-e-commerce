"""P0-1：经 HTTP 审批/执行链验证店铺回执，不访问真实平台。"""

from types import SimpleNamespace

from app.db import SessionLocal
from app.models import PlatformPublishAttempt
from app.services import platforms

from .action_helpers import approve_and_execute


def test_two_stores_keep_separate_receipts_and_replay(client, auth_headers, monkeypatch):
    product = client.post("/api/products", headers=auth_headers, json={
        "title": "Store receipt organizer", "category": "家居",
        "images": ["https://example.com/owned-contract-image.jpg"]})
    assert product.status_code == 200, product.text
    listing = client.post("/api/listings/generate", headers=auth_headers,
                          json={"product_id": product.json()["id"], "platform": "shopee"})
    assert listing.status_code == 200, listing.text
    listing_id = listing.json()["id"]
    shops = []
    for name in ("Contract store A", "Contract store B"):
        shop = client.post("/api/shops", headers=auth_headers,
                           json={"platform": "shopee", "is_demo": True, "shop_name": name})
        assert shop.status_code == 200, shop.text
        shops.append(shop.json()["id"])
    calls = []

    def contract_publish(listing, product):
        receipt = f"contract-receipt-{len(calls) + 1}"
        calls.append(receipt)
        return SimpleNamespace(external_id=receipt, url="", raw={"demo": True, "status": "ACTIVE"},
                               external_object_type="SUBMISSION")

    monkeypatch.setattr(platforms, "demo_publish", contract_publish)
    results = {}
    for shop_id in shops:
        pending = client.post(f"/api/listings/{listing_id}/publish", headers=auth_headers,
                              json={"shop_id": shop_id})
        assert pending.status_code == 200, pending.text
        results[shop_id] = approve_and_execute(client, auth_headers, pending.json())
    assert len(calls) == 2, "第二店必须独立提交，不能重放第一店的 Listing 全局状态"
    assert results[shops[0]]["external_id"] != results[shops[1]]["external_id"]
    for shop_id, result in results.items():
        assert result["shop_id"] == shop_id
        assert result["platform_status"] == "SUBMITTED", "提交响应的原始 ACTIVE 不构成在售核验"
        assert result["verification_status"] == "UNKNOWN", "演示回执不能验证生产在售"
        assert result["external_object_type"] == "SUBMISSION"
    with SessionLocal() as db:
        receipts = db.query(PlatformPublishAttempt).filter_by(listing_id=listing_id).all()
        assert {row.shop_id: row.external_id for row in receipts} == {
            shop_id: result["external_id"] for shop_id, result in results.items()}
        for row in receipts:
            assert row.raw_status == "ACTIVE"
            assert row.received_at is not None and row.mapping_version == "submission-v1"
            assert row.platform_status == "SUBMITTED" and row.verification_status == "UNKNOWN"
    for shop_id in shops:
        replay = client.post(f"/api/listings/{listing_id}/publish", headers=auth_headers,
                             json={"shop_id": shop_id})
        assert replay.status_code == 200, replay.text
        assert replay.json()["external_id"] == results[shop_id]["external_id"]
    assert len(calls) == 2
    response = client.get(f"/api/listings/{listing_id}/publication-attempts", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert {row["shop_id"]: row["external_id"] for row in response.json()["items"]} == {
        shop_id: result["external_id"] for shop_id, result in results.items()}
    assert all(row["can_query_submission"] is False for row in response.json()["items"])
    paged = client.get(f"/api/listings/{listing_id}/publication-attempts?page_size=1&page_num=2",
                       headers=auth_headers).json()
    assert paged["total"] == 2 and len(paged["items"]) == 1
    assert paged["items"][0]["shop_id"] == shops[0], "第二页应返回较早提交的店铺"
