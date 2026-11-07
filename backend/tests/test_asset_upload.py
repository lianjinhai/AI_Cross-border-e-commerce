"""素材上传（M2-D）：未接上传服务一律拒绝且零写入；接入后哈希只能由服务端算。

为什么这些用例存在
------------------
登记接口（`POST /api/products/{id}/assets`）收的是客户端声明的 `content_hash`，
`schema` 只能验它是 64 位十六进制——编一个就能过。于是「图片权利证据」变成
没人能复核的空头承诺。两种情形必须分别锁死：

1. **未接上传服务**：上传 409 `ASSET_UPLOAD_UNAVAILABLE`、`asset://` 引用登记同样
   409，两种情况都**不许**留下任何 `product_assets` 行；
2. **接入之后**：哈希由服务端读字节算出来，登记的哈希对不上文件就 409
   `ASSET_HASH_MISMATCH`，引用不存在的文件就 409 `ASSET_FILE_MISSING`。
"""
import hashlib
import uuid

import pytest

from app.auth import hash_password
from app.config import settings
from app.db import SessionLocal
from app.models import Product, ProductAsset, Shop, User

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"m2d-asset-upload-probe"


def _payload(**changes):
    """合法登记载荷；默认走外部 https 引用（不触发上传校验）。"""
    base = {
        "asset_key": "main-photo", "expected_version": 0, "asset_type": "MAIN_IMAGE",
        "uri": "https://example.com/owned-product.jpg", "content_hash": "a" * 64,
        "rights_status": "OWNED", "source": "供应商提供的原图",
        "rights_evidence_ref": "evidence://declaration/owned-photo",
        "market": "SG", "platform": "shopee",
    }
    return {**base, **changes}


@pytest.fixture
def env(client, auth_headers):
    """真实商品 + 销售店铺（市场 SG），挂在演示租户下，用完删干净。"""
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").one()
        suffix = uuid.uuid4().hex[:8]
        product = Product(tenant_id=admin.tenant_id, sku="m2d-" + suffix,
                          title="上传探针商品", images=["https://example.com/m2d.jpg"])
        shop = Shop(tenant_id=admin.tenant_id, platform="shopee", market="SG",
                    shop_name="上传探针店 " + suffix, role="sales")
        db.add_all([product, shop])
        db.commit()
        data = {"product_id": product.id, "shop_id": shop.id,
                "tenant_id": admin.tenant_id, "headers": auth_headers}
        yield data
        db.rollback()
        db.query(ProductAsset).filter(
            ProductAsset.product_id == product.id).delete(synchronize_session=False)
        db.delete(product)
        db.delete(shop)
        db.commit()


def _count(env):
    with SessionLocal() as db:
        return db.query(ProductAsset).filter(
            ProductAsset.product_id == env["product_id"]).count()


def _upload(client, env, data=PNG_BYTES, content_type="image/png", name="main.png", headers=None):
    return client.post(
        f"/api/products/{env['product_id']}/assets/upload",
        headers=headers or env["headers"], data={"shop_id": env["shop_id"]},
        files={"file": (name, data, content_type)})


def _assert_no_rows(env):
    with SessionLocal() as db:
        rows = (db.query(ProductAsset.product_id, ProductAsset.uri, ProductAsset.content_hash)
                .filter(ProductAsset.product_id == env["product_id"]).all())
    assert rows == [], "拒绝路径不得留下任何素材记录：%s" % rows


# ---------------------------------------------------------------- 未接上传服务
def test_upload_capability_reports_the_gap(client, env, monkeypatch):
    """能力端点必须如实说「不能传」，前端据此禁用按钮而不是假装可用。"""
    monkeypatch.setattr(settings, "asset_upload_dir", "")
    r = client.get(f"/api/products/{env['product_id']}/assets/upload-capability",
                   headers=env["headers"], params={"shop_id": env["shop_id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is False
    assert "ERP_ASSET_UPLOAD_DIR" in body["reason"]


def test_upload_is_refused_and_writes_nothing_when_service_missing(client, env, monkeypatch):
    """未接上传服务：409 + 明确错误码 + **零**素材记录（不生成假哈希凑合）。"""
    monkeypatch.setattr(settings, "asset_upload_dir", "")
    r = _upload(client, env)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "ASSET_UPLOAD_UNAVAILABLE"
    _assert_no_rows(env)


def test_asset_reference_is_untrusted_without_storage(client, env, monkeypatch):
    """没有存储时任何 `asset://` 引用都不可信：登记也必须拒绝且零写入。"""
    monkeypatch.setattr(settings, "asset_upload_dir", "")
    sha = "a" * 64
    r = client.post(f"/api/products/{env['product_id']}/assets", headers=env["headers"],
                    json={**_payload(uri="asset://%s/main.png" % sha, content_hash=sha),
                          "shop_id": env["shop_id"]})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "ASSET_UPLOAD_UNAVAILABLE"
    _assert_no_rows(env)


# ---------------------------------------------------------------- 接入之后
def test_upload_returns_server_computed_hash_and_round_trips_version(client, env, monkeypatch, tmp_path):
    """接好存储后：上传拿到服务端哈希 → 登记 → 版本可回读 → 追加版本。"""
    monkeypatch.setattr(settings, "asset_upload_dir", str(tmp_path / "asset-store"))
    uploaded = _upload(client, env)
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    expected = hashlib.sha256(PNG_BYTES).hexdigest()
    assert body["content_hash"] == expected, "哈希必须由服务端按字节算，不能来自客户端"
    assert body["uri"] == "asset://%s/main.png" % expected
    assert body["size"] == len(PNG_BYTES)

    first = client.post(f"/api/products/{env['product_id']}/assets", headers=env["headers"],
                        json={**_payload(uri=body["uri"], content_hash=body["content_hash"]),
                              "shop_id": env["shop_id"]})
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    assert first.json()["content_hash"] == expected

    listed = client.get(f"/api/products/{env['product_id']}/assets", headers=env["headers"],
                        params={"shop_id": env["shop_id"]})
    assert listed.status_code == 200, listed.text
    assert [row["content_hash"] for row in listed.json()["items"]] == [expected]

    second = client.post(f"/api/products/{env['product_id']}/assets", headers=env["headers"],
                         json={**_payload(uri=body["uri"], content_hash=body["content_hash"],
                                          expected_version=1, source="同一张原图，补登记说明"),
                               "shop_id": env["shop_id"]})
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 2
    assert second.json()["parent_asset_id"] == first.json()["id"]


def test_fabricated_hash_is_rejected_for_uploaded_file(client, env, monkeypatch, tmp_path):
    """文件是真的、哈希是编的 → 409 且不落库（这是「假哈希」最典型的形态）。"""
    monkeypatch.setattr(settings, "asset_upload_dir", str(tmp_path / "asset-store"))
    uploaded = _upload(client, env).json()
    forged = "b" * 64
    r = client.post(f"/api/products/{env['product_id']}/assets", headers=env["headers"],
                    json={**_payload(uri=uploaded["uri"], content_hash=forged),
                          "shop_id": env["shop_id"]})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "ASSET_HASH_MISMATCH"
    _assert_no_rows(env)


def test_missing_uploaded_file_is_rejected(client, env, monkeypatch, tmp_path):
    """引用存储里不存在的文件 → 409 ASSET_FILE_MISSING 且零写入。"""
    monkeypatch.setattr(settings, "asset_upload_dir", str(tmp_path / "asset-store"))
    ghost = "c" * 64
    r = client.post(f"/api/products/{env['product_id']}/assets", headers=env["headers"],
                    json={**_payload(uri="asset://%s/ghost.png" % ghost, content_hash=ghost),
                          "shop_id": env["shop_id"]})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "ASSET_FILE_MISSING"
    _assert_no_rows(env)


def test_upload_rejects_unsupported_type_and_oversize(client, env, monkeypatch, tmp_path):
    """类型与大小是门禁：明确拒绝，不静默截断也不改名混进去。"""
    monkeypatch.setattr(settings, "asset_upload_dir", str(tmp_path / "asset-store"))
    bad_type = _upload(client, env, data=b"plain text", content_type="text/plain", name="a.txt")
    assert bad_type.status_code == 400, bad_type.text
    assert bad_type.json()["detail"]["code"] == "ASSET_TYPE_UNSUPPORTED"

    from app.services import asset_upload
    too_big = _upload(client, env, data=b"\x89PNG\r\n\x1a\n" + b"x" * (asset_upload.MAX_BYTES + 1))
    assert too_big.status_code == 413, too_big.text
    assert too_big.json()["detail"]["code"] == "ASSET_TOO_LARGE"
    _assert_no_rows(env)


def test_read_only_account_cannot_upload(client, env, monkeypatch, tmp_path):
    """只读账号上传 403（require_write 闸门），且不落任何文件记录。"""
    monkeypatch.setattr(settings, "asset_upload_dir", str(tmp_path / "asset-store"))
    with SessionLocal() as db:
        username = "m2d_viewer_" + uuid.uuid4().hex[:6]
        db.add(User(tenant_id=env["tenant_id"], username=username, role="viewer",
                    password_hash=hash_password("View0rd!")))
        db.commit()
    login = client.post("/api/auth/login", json={"username": username, "password": "View0rd!"})
    assert login.status_code == 200, login.text
    viewer = {"Authorization": "Bearer " + login.json()["token"]}

    r = _upload(client, env, headers=viewer)
    assert r.status_code == 403, r.text
    _assert_no_rows(env)
