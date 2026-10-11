"""店铺上下文写入与输入边界，不接受用户伪造能力证据。"""


def test_shop_context_roundtrip_and_validation(client, auth_headers):
    response = client.post("/api/shops", headers=auth_headers, json={
        "platform": "shopee", "market": "德国", "business_mode": "seller",
        "fulfillment_mode": "PLATFORM_STOCK", "capability_revision": 99})
    assert response.status_code == 200, response.text
    shop = response.json()
    assert shop["market"] == "DE" and shop["capability_revision"] == 0
    assert shop["fulfillment_mode"] == "PLATFORM_STOCK"
    for payload in ({"market": "EU"}, {"market": "ZZ"}, {"fulfillment_mode": "invented"}):
        rejected = client.put(f"/api/shops/{shop['id']}", headers=auth_headers, json=payload)
        assert rejected.status_code == 422, rejected.text
    updated = client.put(f"/api/shops/{shop['id']}", headers=auth_headers,
                         json={"market": "TR", "fulfillment_mode": "DROPSHIP"})
    assert updated.status_code == 200
    assert updated.json()["market"] == "TR" and updated.json()["fulfillment_mode"] == "DROPSHIP"


def test_market_change_after_approval_prevents_execution(client, auth_headers):
    product = client.post("/api/products", headers=auth_headers, json={
        "title": "Market revision organizer", "category": "家居",
        "images": ["https://example.com/contract.jpg"]}).json()
    listing = client.post("/api/listings/generate", headers=auth_headers,
                          json={"product_id": product["id"], "platform": "shopee"}).json()
    shop = client.post("/api/shops", headers=auth_headers,
                       json={"platform": "shopee", "is_demo": True, "market": "SG"}).json()
    pending = client.post(f"/api/listings/{listing['id']}/publish", headers=auth_headers,
                          json={"shop_id": shop["id"]})
    assert pending.status_code == 200, pending.text
    action_id = pending.json()["action_id"]
    approved = client.post(f"/api/actions/{action_id}/approve", headers=auth_headers,
                           json={"note": "核对新加坡目标"})
    assert approved.status_code == 200, approved.text
    updated = client.put(f"/api/shops/{shop['id']}", headers=auth_headers, json={"market": "MY"})
    assert updated.status_code == 200
    executed = client.post(f"/api/actions/{action_id}/execute", headers=auth_headers)
    assert executed.status_code == 200 and executed.json()["status"] == "FAILED", executed.text
    receipts = client.get(f"/api/listings/{listing['id']}/publication-attempts", headers=auth_headers)
    assert receipts.json()["total"] == 0
