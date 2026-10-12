"""素材版本、权利与发布范围；全部在隔离数据库，不下载外部图片。"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.db import SessionLocal
from app.models import (
    Listing,
    ListingReviewDecision,
    PlatformRulePack,
    Product,
    ProductAsset,
    Shop,
    User,
    utcnow,
)
from app.services.action_publish import publish_facts
from app.services.action_records import listing_fingerprint
from app.services.adapters.contract import PlatformError
from app.services.adapters.shopee import ShopeeAdapter
from app.services.ai_actions import ActionError
from app.services.asset_rights import evaluate_asset_rights
from app.services.product_assets import AssetError, list_assets, register_asset, verify_asset
from app.services.workspace_context import resolve_workspace_context


@pytest.fixture
def assets_db(client):
    with SessionLocal() as db:
        contexts = {name: resolve_workspace_context(db, db.query(User).filter_by(username=name).one())
                    for name in ("admin", "ops", "viewer")}
        tenant = contexts["admin"].legacy_tenant_id
        product = Product(tenant_id=tenant, sku="asset-contract", title="Asset product",
                          images=["https://example.com/owned-product.jpg"])
        shop = Shop(tenant_id=tenant, platform="shopee", market="SG", shop_name="Asset test")
        db.add_all([product, shop])
        db.commit()
        yield db, contexts, product, shop
        db.rollback()
        db.query(ListingReviewDecision).filter_by(product_id=product.id).delete(synchronize_session=False)
        db.query(Listing).filter_by(product_id=product.id).delete(synchronize_session=False)
        db.query(ProductAsset).filter_by(product_id=product.id).delete(synchronize_session=False)
        db.query(PlatformRulePack).filter_by(platform="asset_probe").delete(synchronize_session=False)
        db.delete(product)
        db.delete(shop)
        db.commit()


def _payload(**changes):
    return {"asset_key": "main-photo", "expected_version": 0, "asset_type": "MAIN_IMAGE",
            "uri": "https://example.com/owned-product.jpg", "content_hash": "a" * 64,
            "rights_status": "OWNED", "source": "User product photo",
            "rights_evidence_ref": "evidence://declaration/owned-photo", "market": "SG", "platform": "shopee", **changes}


def _register_and_verify(db, contexts, product, shop, **changes):
    reported = register_asset(db, contexts["ops"], product.id, shop.id, _payload(**changes))
    verified = verify_asset(db, contexts["admin"], reported.id, shop.id, reported.version,
                            decision="VERIFIED", evidence_ref="evidence://review/source-check", reason="已核对原图与来源授权")
    db.commit()
    return reported, verified


def test_declaration_review_and_revocation_append_versions(assets_db):
    db, contexts, product, shop = assets_db
    declared = register_asset(db, contexts["ops"], product.id, shop.id, _payload())
    assert declared.verification_status == "MANUAL_REPORTED"
    assert evaluate_asset_rights(db, product.tenant_id, product, shop)["allowed"]
    assert register_asset(db, contexts["ops"], product.id, shop.id, _payload()).id == declared.id
    verified = verify_asset(db, contexts["admin"], declared.id, shop.id, 1, decision="VERIFIED",
                            evidence_ref="evidence://review/source-check", reason="独立检查来源")
    assert verified.parent_asset_id == declared.id and verified.version == 2
    assert declared.verification_status == "MANUAL_REPORTED"
    allowed = evaluate_asset_rights(db, product.tenant_id, product, shop)
    assert allowed["allowed"] and allowed["versions"][0]["id"] == verified.id
    revoked = register_asset(db, contexts["ops"], product.id, shop.id,
                             _payload(expected_version=2, rights_status="RESTRICTED", rights_evidence_ref=""))
    assert revoked.version == 3 and not evaluate_asset_rights(db, product.tenant_id, product, shop)["allowed"]
    assert len(list_assets(db, contexts["viewer"], product.id, shop.id)) == 3


def test_creator_cannot_self_verify_and_operator_cannot_review(assets_db):
    db, contexts, product, shop = assets_db
    own = register_asset(db, contexts["admin"], product.id, shop.id, _payload())
    for role, code in (("admin", "ASSET_SELF_REVIEW"), ("ops", "ASSET_PERMISSION_DENIED")):
        with pytest.raises(AssetError) as rejected:
            verify_asset(db, contexts[role], own.id, shop.id, 1, decision="VERIFIED",
                         evidence_ref="evidence://review/test", reason="attempt")
        assert rejected.value.code == code
    with pytest.raises(AssetError, match="不能执行"):
        register_asset(db, contexts["viewer"], product.id, shop.id, _payload(asset_key="other"))


@pytest.mark.parametrize("rights", ["UNKNOWN", "RESTRICTED"])
def test_review_cannot_make_unknown_or_restricted_rights_publishable(assets_db, rights):
    db, contexts, product, shop = assets_db
    _register_and_verify(db, contexts, product, shop, rights_status=rights, rights_evidence_ref="")
    assert not evaluate_asset_rights(db, product.tenant_id, product, shop)["allowed"]


def test_expiry_market_content_and_revision_change_invalidate_usage(assets_db):
    db, contexts, product, shop = assets_db
    now = utcnow()
    _, verified = _register_and_verify(db, contexts, product, shop, valid_until=now + timedelta(hours=1))
    first = evaluate_asset_rights(db, product.tenant_id, product, shop, now=now)
    assert first["allowed"]
    assert not evaluate_asset_rights(db, product.tenant_id, product, shop, now=now + timedelta(hours=2))["allowed"]
    shop.market = "MY"
    assert not evaluate_asset_rights(db, product.tenant_id, product, shop)["allowed"]
    shop.market = "SG"
    product.images = ["https://example.com/different.jpg"]
    assert not evaluate_asset_rights(db, product.tenant_id, product, shop)["allowed"]
    with pytest.raises(AssetError) as conflict:
        register_asset(db, contexts["ops"], product.id, shop.id, _payload(expected_version=1))
    assert conflict.value.code == "ASSET_VERSION_CONFLICT" and verified.version == 2


def test_outer_transaction_rollback_removes_asset_version(assets_db):
    db, contexts, product, shop = assets_db
    row = register_asset(db, contexts["ops"], product.id, shop.id, _payload())
    row_id = row.id
    db.rollback()
    assert db.get(ProductAsset, row_id) is None


@pytest.mark.parametrize("changes", [{"uri": "file:///C:/secret.txt"}, {"uri": "https://user:password@example.com/a"},
                                      {"rights_status": "LICENSED", "rights_evidence_ref": ""}, {"market": "EU"},
                                      {"verification_status": "VERIFIED"}, {"manifest": {"_review": "fake"}}])
def test_registration_rejects_unsafe_or_forged_claims(assets_db, changes):
    db, contexts, product, shop = assets_db
    with pytest.raises(ValidationError):
        register_asset(db, contexts["ops"], product.id, shop.id, _payload(**changes))


def test_adapter_rights_gate_blocks_unknown_and_accepts_verified(assets_db, monkeypatch):
    db, contexts, product, shop = assets_db
    adapter = ShopeeAdapter(db, shop)
    monkeypatch.setattr(adapter, "_destination_access_issues", lambda product: [])
    with pytest.raises(PlatformError, match="权利"):
        adapter._enforce_publish_gate(None, product, channel="asset-contract")
    _register_and_verify(db, contexts, product, shop)
    assert adapter._enforce_publish_gate(None, product, channel="asset-contract") == []
    register_asset(db, contexts["ops"], product.id, shop.id,
                   _payload(expected_version=2, rights_status="RESTRICTED", rights_evidence_ref=""))
    with pytest.raises(PlatformError, match="受限"):
        adapter._enforce_publish_gate(None, product, channel="asset-contract")


def test_asset_gate_backend_failure_is_not_a_bypass(assets_db, monkeypatch):
    db, _, product, shop = assets_db
    adapter = ShopeeAdapter(db, shop)
    monkeypatch.setattr(adapter, "_destination_access_issues", lambda product: [])

    def fail(*args):
        raise RuntimeError("rights storage offline")
    monkeypatch.setattr("app.services.asset_rights.evaluate_asset_rights", fail)
    with pytest.raises(PlatformError, match="禁止跳过"):
        adapter._enforce_publish_gate(None, product, channel="asset-contract")


def test_demo_purge_preserves_rights_history(assets_db, client, auth_headers):
    db, contexts, product, shop = assets_db
    register_asset(db, contexts["ops"], product.id, shop.id, _payload())
    db.commit()
    response = client.post("/api/shops/purge_demo_data", headers=auth_headers)
    assert response.status_code == 409 and "权利记录" in response.json()["detail"]
    assert db.query(ProductAsset).filter_by(product_id=product.id).count() == 1


def test_asset_http_registration_review_and_pagination(assets_db, client, auth_headers):
    db, _, product, shop = assets_db
    login = client.post("/api/auth/login", json={"username": "ops", "password": "ops123"})
    operator = {"Authorization": "Bearer " + login.json()["token"]}
    url = f"/api/products/{product.id}/assets"
    registered = client.post(url, headers=operator, json={**_payload(), "shop_id": shop.id})
    assert registered.status_code == 200, registered.text
    assert registered.json()["verification_status"] == "MANUAL_REPORTED"
    review = {"shop_id": shop.id, "expected_version": 1, "decision": "VERIFIED",
              "evidence_ref": "evidence://review/http", "reason": "核对来源与权利证明"}
    endpoint = f"{url}/{registered.json()['id']}/verify"
    assert client.post(endpoint, headers=operator, json=review).status_code == 403
    checked = client.post(endpoint, headers=auth_headers, json=review)
    assert checked.status_code == 200 and checked.json()["version"] == 2, checked.text
    listed = client.get(f"{url}?shop_id={shop.id}&page_size=1", headers=operator)
    assert listed.status_code == 200 and listed.json()["total"] == 2
    assert len(listed.json()["items"]) == 1 and listed.json()["items"][0]["version"] == 2
    assert evaluate_asset_rights(db, product.tenant_id, product, shop)["allowed"]
    forged = client.post(url, headers=operator, json={**_payload(), "shop_id": shop.id, "tenant_id": 999})
    assert forged.status_code == 422


def test_asset_store_scope_is_fresh_and_checked_before_read(assets_db):
    db, contexts, product, shop = assets_db
    row = register_asset(db, contexts["ops"], product.id, shop.id, _payload())
    db.commit()
    member = db.execute(text("SELECT id FROM workspace_memberships WHERE user_id=:id"),
                        {"id": contexts["ops"].user_id}).scalar_one()
    db.execute(text("INSERT INTO membership_data_scopes(membership_id,scope_type,scope_ref) VALUES(:id,'SHOP_SCOPED',:ref)"),
               {"id": member, "ref": json.dumps({"shop_ids": [99999999]})})
    try:
        with pytest.raises(AssetError) as denied:
            list_assets(db, contexts["ops"], product.id, shop.id)
        assert denied.value.status_code == 404
        with pytest.raises(AssetError):
            register_asset(db, contexts["ops"], product.id, shop.id, _payload())
        assert db.get(ProductAsset, row.id) is not None
    finally:
        db.rollback()


def test_asset_same_version_concurrent_requests_have_one_winner(assets_db):
    db, contexts, product, shop = assets_db
    product_id, shop_id = product.id, shop.id
    barrier = Barrier(2)

    def worker(index):
        with SessionLocal() as session:
            barrier.wait(timeout=10)
            try:
                row = register_asset(session, contexts["ops"], product_id, shop_id,
                                     _payload(content_hash=("a" if index == 0 else "b") * 64))
                session.commit()
                return row.id
            except AssetError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(worker, (0, 1)))
    assert sum(type(result) is int for result in results) == 1 and "ASSET_VERSION_CONFLICT" in results
    assert db.query(ProductAsset).filter_by(product_id=product_id).count() == 1


def test_publish_approval_fingerprint_tracks_asset_versions_and_revocation(assets_db):
    db, contexts, product, shop = assets_db
    shop.platform, shop.status, product.category = "asset_probe", "authorized", "家居"
    listing = Listing(tenant_id=product.tenant_id, product_id=product.id, platform=shop.platform,
                      title="Product photo", description="Photo", keywords=["photo"], risk_level="low")
    db.add_all([listing, PlatformRulePack(platform=shop.platform, version="asset-1",
                                          rules={"banned_words": [], "image_min": 1})])
    db.flush()
    db.add(ListingReviewDecision(tenant_id=product.tenant_id, listing_id=listing.id, product_id=product.id,
                                platform=shop.platform, decision="approved", human_override=True,
                                reviewer="contract-review", rule_version="asset-1",
                                evidence={"content_fingerprint": listing_fingerprint(listing, product)}))
    db.commit()
    with pytest.raises(ActionError, match="素材权利"):
        publish_facts(db, product.tenant_id, listing.id, shop.id)

    _register_and_verify(db, contexts, product, shop, platform=shop.platform)
    first = publish_facts(db, product.tenant_id, listing.id, shop.id)
    _register_and_verify(db, contexts, product, shop, platform=shop.platform, expected_version=2, content_hash="b" * 64)
    changed = publish_facts(db, product.tenant_id, listing.id, shop.id)
    assert first["fingerprint"] != changed["fingerprint"]
    register_asset(db, contexts["ops"], product.id, shop.id,
                   _payload(platform=shop.platform, expected_version=4, rights_status="RESTRICTED", rights_evidence_ref=""))
    with pytest.raises(ActionError, match="素材权利"):
        publish_facts(db, product.tenant_id, listing.id, shop.id)

@pytest.mark.parametrize("rights", ["OWNED", "SUPPLIER_AUTHORIZED", "LICENSED"])
def test_explicit_rights_declaration_does_not_require_extra_approval(assets_db, rights):
    db, contexts, product, shop = assets_db
    row = register_asset(db, contexts["admin"], product.id, shop.id, _payload(
        rights_status=rights, rights_evidence_ref="" if rights == "OWNED" else "evidence://license/proof",
        valid_until="2099-01-01T08:00:00+08:00"))
    assert row.verification_status == "MANUAL_REPORTED"
    assert row.valid_until.isoformat() == "2099-01-01T00:00:00"
    assert evaluate_asset_rights(db, product.tenant_id, product, shop)["allowed"]


def test_rejected_rights_record_cannot_publish(assets_db):
    db, contexts, product, shop = assets_db
    row = register_asset(db, contexts["ops"], product.id, shop.id, _payload())
    verify_asset(db, contexts["admin"], row.id, shop.id, 1, decision="REJECTED",
                 evidence_ref="evidence://review/rejection", reason="提供的来源不匹配")
    assert not evaluate_asset_rights(db, product.tenant_id, product, shop)["allowed"]
