"""P0-6/8：店铺范围与 Membership 撤权，全部隔离测试库。"""

import json

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models import PlatformPublishAttempt

from .action_helpers import approve_and_execute


@pytest.fixture
def scoped_user(client, auth_headers):
    created = client.post("/api/auth/users", headers=auth_headers,
                          json={"username": "launch-scoped-ops", "password": "scope-test-123", "role": "operator"})
    assert created.status_code == 200, created.text
    user_id = created.json()["id"]
    login = client.post("/api/auth/login", json={"username": "launch-scoped-ops", "password": "scope-test-123"})
    headers = {"Authorization": "Bearer " + login.json()["token"]}
    shops = []
    for name in ("allowed", "denied"):
        response = client.post("/api/shops", headers=auth_headers,
                               json={"platform": "shopee", "is_demo": True, "shop_name": name, "market": "SG"})
        assert response.status_code == 200, response.text
        shops.append(response.json()["id"])
    with SessionLocal() as db:
        membership = db.execute(text("SELECT id FROM workspace_memberships WHERE user_id=:id"), {"id": user_id}).scalar_one()
        db.execute(text("INSERT INTO membership_data_scopes(membership_id,scope_type,scope_ref) VALUES(:id,'SHOP_SCOPED',:ref)"),
                   {"id": membership, "ref": json.dumps({"shop_ids": [shops[0]]})})
        db.commit()
    yield headers, membership, shops
    with SessionLocal() as db:
        db.execute(text("DELETE FROM membership_data_scopes WHERE membership_id=:id"), {"id": membership})
        db.execute(text("DELETE FROM workspace_memberships WHERE id=:id"), {"id": membership})
        db.commit()
    client.delete(f"/api/auth/users/{user_id}", headers=auth_headers)


def test_scoped_shop_list_detail_and_create_are_enforced(client, scoped_user):
    headers, _, shops = scoped_user
    response = client.get("/api/shops", headers=headers)
    assert response.status_code == 200, response.text
    assert {row["id"] for row in response.json()["items"]} == {shops[0]}
    assert client.put(f"/api/shops/{shops[1]}", headers=headers, json={"market": "MY"}).status_code == 404
    assert client.put(f"/api/shops/{shops[0]}", headers=headers, json={"market": "SG"}).status_code == 200
    assert client.post("/api/shops", headers=headers, json={"platform": "shopee"}).status_code == 403


def test_revoked_membership_never_falls_back_to_legacy_operator(client, scoped_user):
    headers, membership, shops = scoped_user
    with SessionLocal() as db:
        db.execute(text("UPDATE workspace_memberships SET status='INACTIVE' WHERE id=:id"), {"id": membership})
        db.commit()
    assert client.get("/api/shops", headers=headers).status_code == 403
    assert client.put(f"/api/shops/{shops[0]}", headers=headers, json={"market": "MY"}).status_code == 403


@pytest.mark.parametrize("kind,ref", [("SELF_ONLY", {}), ("SHOP_SCOPED", {"shop_ids": []}),
                                     ("SHOP_SCOPED", {"shop_ids": [True]}), ("TYPO", {})])
def test_invalid_scope_fails_closed(client, scoped_user, kind, ref):
    headers, membership, _ = scoped_user
    with SessionLocal() as db:
        db.execute(text("UPDATE membership_data_scopes SET scope_type=:kind,scope_ref=:ref WHERE membership_id=:id"),
                   {"id": membership, "kind": kind, "ref": json.dumps(ref)})
        db.commit()
    assert client.get("/api/shops", headers=headers).status_code == 403


def test_publish_queue_receipts_and_success_replay_keep_store_scope(client, auth_headers, scoped_user):
    headers, _, shops = scoped_user
    product = client.post("/api/products", headers=auth_headers,
                          json={"title": "Scope contract organizer", "category": "家居",
                                "images": ["https://example.com/scope-contract.jpg"]})
    assert product.status_code == 200, product.text
    listing = client.post("/api/listings/generate", headers=auth_headers,
                          json={"product_id": product.json()["id"], "platform": "shopee"})
    assert listing.status_code == 200, listing.text
    listing_id = listing.json()["id"]
    denied = client.post(f"/api/listings/{listing_id}/publish", headers=headers,
                         json={"shop_id": shops[1]})
    assert denied.status_code == 404, denied.text
    for shop_id in shops:
        pending = client.post(f"/api/listings/{listing_id}/publish", headers=auth_headers,
                              json={"shop_id": shop_id})
        assert pending.status_code == 200, pending.text
        approve_and_execute(client, auth_headers, pending.json())
    queue = client.get("/api/actions?action_type=PUBLISH_LISTING&status=SUCCESS&limit=1", headers=headers)
    assert queue.status_code == 200, queue.text
    assert len(queue.json()["items"]) == 1
    assert queue.json()["items"][0]["evidence"]["shop_id"] == shops[0]
    receipts = client.get(f"/api/listings/{listing_id}/publication-attempts?page_size=1", headers=headers)
    assert receipts.status_code == 200, receipts.text
    assert receipts.json()["total"] == 1
    assert receipts.json()["items"][0]["shop_id"] == shops[0]
    replay = client.post(f"/api/listings/{listing_id}/publish", headers=headers,
                         json={"shop_id": shops[1]})
    assert replay.status_code == 404, replay.text


@pytest.mark.parametrize("revoked_actor", ["requester", "approver"])
def test_approved_publish_rechecks_each_actor_store_scope(client, auth_headers, scoped_user, revoked_actor):
    headers, membership, shops = scoped_user
    product = client.post("/api/products", headers=auth_headers,
                          json={"title": "Approval scope organizer", "category": "家居",
                                "images": ["https://example.com/scope-contract.jpg"]})
    assert product.status_code == 200, product.text
    listing = client.post("/api/listings/generate", headers=auth_headers,
                          json={"product_id": product.json()["id"], "platform": "shopee"})
    assert listing.status_code == 200, listing.text
    listing_id = listing.json()["id"]
    pending = client.post(f"/api/listings/{listing_id}/publish",
                          headers=headers if revoked_actor == "requester" else auth_headers,
                          json={"shop_id": shops[0]})
    assert pending.status_code == 200, pending.text
    action_id = pending.json()["action_id"]
    approved = client.post(f"/api/actions/{action_id}/approve",
                           headers=headers if revoked_actor == "approver" else auth_headers,
                           json={"note": "限定店铺审批测试"})
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        db.execute(text("UPDATE membership_data_scopes SET scope_ref=:ref WHERE membership_id=:id AND scope_type='SHOP_SCOPED'"),
                   {"id": membership, "ref": json.dumps({"shop_ids": [shops[1]]})})
        db.commit()
    execution = client.post(f"/api/actions/{action_id}/execute", headers=auth_headers)
    assert execution.status_code == 404, execution.text
    with SessionLocal() as db:
        assert db.query(PlatformPublishAttempt).filter_by(listing_id=listing_id).count() == 0
