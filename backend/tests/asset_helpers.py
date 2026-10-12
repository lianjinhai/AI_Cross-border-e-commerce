"""需要真实素材门禁的 HTTP 契约用例，共用登记/独立核验与定向清理夹具。"""

import pytest

from app.db import SessionLocal
from app.models import ProductAsset


@pytest.fixture
def register_reviewed_image(client, auth_headers):
    products = []

    def register(product_id, shop_id, *, uri, market="SG", platform="shopee"):
        products.append(product_id)
        login = client.post("/api/auth/login", json={"username": "ops", "password": "ops123"})
        assert login.status_code == 200, login.text
        operator = {"Authorization": "Bearer " + login.json()["token"]}
        path = f"/api/products/{product_id}/assets"
        declared = client.post(path, headers=operator, json={
            "shop_id": shop_id, "asset_key": "contract-main-photo", "expected_version": 0,
            "asset_type": "MAIN_IMAGE", "uri": uri, "content_hash": "a" * 64,
            "rights_status": "OWNED", "source": "isolated contract photo",
            "rights_evidence_ref": "evidence://contract/ownership", "market": market, "platform": platform})
        assert declared.status_code == 200, declared.text
        reviewed = client.post(f"{path}/{declared.json()['id']}/verify", headers=auth_headers, json={
            "shop_id": shop_id, "expected_version": 1, "decision": "VERIFIED",
            "evidence_ref": "evidence://contract/reviewer", "reason": "隔离契约样本的独立核验"})
        assert reviewed.status_code == 200, reviewed.text
        return reviewed.json()

    yield register
    with SessionLocal() as db:
        db.query(ProductAsset).filter(ProductAsset.product_id.in_(products)).delete(synchronize_session=False)
        db.commit()
