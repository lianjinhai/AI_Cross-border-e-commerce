"""R3-1C QA 端到端（J1 真实闭环，隔离测试库）。

覆盖 J1：商品库→商品详情→渠道→目标店铺→创建 Launch→看阻断→补素材/核验→返回原步骤→
刷新准备状态与下一动作；并验证 7 条硬性要求：
  1) 不重输 Product/Store ID（上下文/详情回显身份，下游无需再输入）
  2) 不丢 Workspace 上下文（同一租户/工作区全程一致）
  3) 能返回原页（同一 run_id 详情在动作后仍可读且不漂移）
  4) 失败有原因（错误体带 code/message；阻断动作带 disabled_reason）
  5) 外部等待不显示成功（EXTERNAL_WAIT 未完成前 execution_status 不得为 COMPLETED）
  6) 无权限服务端拒绝（只读账号核验/登记 → 403）
  7) 跨店铺不串数据（素材按 目标店铺 market+platform 隔离，不跨市场串）

安全边界：由 conftest 设为隔离测试库（ERP_DB_URL=test_erp_<pid>.db），不触碰业务主库；
平台用独立字符串 ``qaj1`` 走 CONTRACT_TEST 本地契约流程，不调用任何真实平台，
不对真实店铺发布/核价/采购（只执行本地 COMPLETE_DATA，不触发 SUBMIT_PLATFORM）。
"""

import pytest

from app.auth import hash_password
from app.db import SessionLocal
from app.models import (
    Listing,
    PlatformPublishAttempt,
    Product,
    ProductAsset,
    Shop,
    User,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
    WorkflowTemplate,
)
from app.services.workspace_context import resolve_workspace_context
from app.workflows.profiles import create_profile, publish_profile

PLATFORM = "qaj1"
CONTRACT = "QA_J1"
COMPLIANCE_USER = "qa-j1-compliance"
READONLY_USER = "qa-j1-viewer"
COMPLIANCE_PASS = "qa-compliance-pass"
READONLY_PASS = "qa-viewer-pass"
PRODUCT_IMAGE = "https://example.com/main.jpg"


def _profile(version=1):
    """本地契约流程：资料 -> 提交 -> 在售核验 -> 监控（与 test_launch_api 同源）。"""
    steps = [
        {"step_code": "INFO", "step_name": "商品资料", "business_type": "DATA_PREPARATION",
         "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 0, "required": True,
         "dependencies": [], "available_actions": ["COMPLETE_DATA"],
         "evidence_requirements": ["INFORMATION_EVIDENCE"],
         "completion_condition": {"all": [{"present": "product.title"},
                                          {"asset_rights_allowed": "PUBLISHABLE"}]}},
        {"step_code": "SUBMISSION", "step_name": "提交平台", "business_type": "PLATFORM_SUBMISSION",
         "execution_mode": "ADAPTER_TASK", "actor": "SYSTEM", "sequence": 1, "required": True,
         "dependencies": ["INFO"], "available_actions": ["SUBMIT_PLATFORM"],
         "completion_condition": {"present": "platform.submission_reference"}},
        {"step_code": "ACTIVE", "step_name": "在售核验", "business_type": "PLATFORM_ACTIVATION",
         "execution_mode": "EXTERNAL_WAIT", "actor": "PLATFORM", "sequence": 2, "required": True,
         "dependencies": ["SUBMISSION"], "available_actions": ["CONFIRM_ACTIVATION"],
         "completion_condition": {"all": [{"eq": {"field": "platform.status", "value": "ACTIVE"}},
                                          {"verified_artifact": "ACTIVATION"},
                                          {"asset_rights_allowed": "PUBLISHABLE"}]}},
        {"step_code": "MONITORING", "step_name": "经营监控", "business_type": "MONITORING",
         "execution_mode": "SYSTEM_TASK", "actor": "SYSTEM", "sequence": 3, "required": False,
         "dependencies": ["ACTIVE"],
         "completion_condition": {"eq": {"field": "monitoring.registered", "value": True}}},
    ]
    return {"profile_key": CONTRACT, "version": version, "name": "QA J1 本地契约样本",
            "description": "本地流程验证，不代表真实平台接入。",
            "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
            "platform": PLATFORM, "market": "SG", "fulfillment_mode": "DROPSHIP",
            "category_scope": ["ANY"], "status_mapping": {"unknown": "BLOCK", "statuses": {}},
            "steps": steps}


@pytest.fixture
def j1_env(client):
    """最小 seed：1 商品 + 2 个 sales 店铺（SG / US，带 market）+ 已发布流程 + 合规/只读账号。"""
    with SessionLocal() as db:
        owner = db.query(User).filter_by(username="admin").one()
        ctx = resolve_workspace_context(db, owner)
        tenant = ctx.legacy_tenant_id
        product = Product(tenant_id=tenant, sku="qa-j1", title="QA J1 product", category="家居",
                          images=[PRODUCT_IMAGE], attrs={"destination_country": "SG"})
        shops = [Shop(tenant_id=tenant, platform=PLATFORM, shop_name="QA J1 SG", market="SG",
                      fulfillment_mode="DROPSHIP", is_demo=True),
                 Shop(tenant_id=tenant, platform=PLATFORM, shop_name="QA J1 US", market="US",
                      fulfillment_mode="DROPSHIP", is_demo=True)]
        extra = [User(tenant_id=tenant, username=COMPLIANCE_USER, password_hash=hash_password(COMPLIANCE_PASS),
                      role="compliance_approver", display_name="合规审批"),
                 User(tenant_id=tenant, username=READONLY_USER, password_hash=hash_password(READONLY_PASS),
                      role="viewer", display_name="只读账号")]
        db.add_all([product, *shops, *extra])
        db.commit()
        profile = create_profile(db, ctx, _profile())
        publish_profile(db, ctx, profile.id, profile.definition_hash)
        db.commit()
        yield db, ctx, product, shops
        db.rollback()
        _cleanup(db, tenant, product, shops)


def _cleanup(db, tenant, product, shops):
    run_ids = [row[0] for row in db.query(WorkflowRun.id).filter_by(product_id=product.id).all()]
    listing_ids = [row[0] for row in db.query(Listing.id).filter_by(product_id=product.id).all()]
    db.query(WorkflowRun).filter(WorkflowRun.product_id == product.id).update(
        {"previous_run_id": None}, synchronize_session=False)
    if run_ids:
        db.query(WorkflowEvent).filter(WorkflowEvent.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(WorkflowStep).filter(WorkflowStep.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).delete(synchronize_session=False)
    if listing_ids:
        db.query(PlatformPublishAttempt).filter(
            PlatformPublishAttempt.listing_id.in_(listing_ids)).delete(synchronize_session=False)
    db.query(Listing).filter(Listing.product_id == product.id).delete(synchronize_session=False)
    db.query(ProductAsset).filter(ProductAsset.product_id == product.id).delete(synchronize_session=False)
    db.query(WorkflowTemplate).filter(WorkflowTemplate.tenant_id == tenant,
                                      WorkflowTemplate.profile_key == CONTRACT).delete(synchronize_session=False)
    db.query(User).filter(User.username.in_((COMPLIANCE_USER, READONLY_USER))).delete(synchronize_session=False)
    db.delete(product)
    for shop in shops:
        db.delete(shop)
    db.commit()


def _login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def _asset_body(shop, **overrides):
    """AssetIn 完整体（含 market/platform，uri 用商品主图使其可发布）。"""
    body = {"shop_id": shop.id, "asset_key": "main_image", "expected_version": 0,
            "asset_type": "MAIN_IMAGE", "uri": PRODUCT_IMAGE, "content_hash": "a" * 64,
            "rights_status": "OWNED", "rights_evidence_ref": "", "source": "QA J1 seed",
            "market": shop.market, "platform": shop.platform}
    body.update(overrides)
    return body


def _step_map(client, headers, run_id):
    return {s["step_code"]: s for s in client.get(f"/api/launch/{run_id}/steps", headers=headers).json()["items"]}


def test_j1_full_closed_loop(client, auth_headers, j1_env):
    db, ctx, product, shops = j1_env
    shop_a, _shop_b = shops

    # 1) 商品库 → 能找到种子商品
    listing = client.get("/api/products", headers=auth_headers, params={"keyword": "QA J1"})
    assert listing.status_code == 200, listing.text
    assert any(item["id"] == product.id for item in listing.json()["items"])

    # 2) 商品详情回显身份（下游无需再输入 Product ID）
    detail = client.get(f"/api/products/{product.id}", headers=auth_headers)
    assert detail.status_code == 200 and detail.json()["id"] == product.id

    # 3) 渠道：无 run → 空；契约形状为 {product,total,channels}，无 items 键
    ch0 = client.get(f"/api/products/{product.id}/channels", headers=auth_headers)
    assert ch0.status_code == 200, ch0.text
    assert ch0.json()["channels"] == [] and "items" not in ch0.json()

    # 4) 目标店铺上下文（要求1：不重输 Store ID —— context 提供可选店铺清单）
    ctxr = client.get("/api/launch/context", headers=auth_headers)
    assert ctxr.status_code == 200 and ctxr.json()["can_create"] is True
    usable = {row["id"]: row for row in ctxr.json()["shops"]}
    assert usable[shop_a.id]["usable"] is True and usable[shop_a.id]["market"] == "SG"

    # 5) 创建 Launch（进 Launch）；身份回显（要求1）
    created = client.post("/api/launch", headers={**auth_headers, "Idempotency-Key": "qa-j1"},
                          json={"product_id": product.id, "shop_id": shop_a.id})
    assert created.status_code == 200, created.text
    run = created.json()
    run_id = run["id"]
    assert run["product"]["id"] == product.id and run["store"]["id"] == shop_a.id

    # 6) 看阻断：INFO 就绪但完成条件未满足 → COMPLETE_DATA 不可执行且带原因（要求4）
    steps = _step_map(client, auth_headers, run_id)
    assert steps["INFO"]["step_status"] == "READY"
    assert "INFORMATION_EVIDENCE" in steps["INFO"]["missing_evidence"]
    disabled = {a["action"]: a for a in run["disabled_actions"]}
    assert "COMPLETE_DATA" in disabled and disabled["COMPLETE_DATA"]["disabled_reason"]
    assert "COMPLETE_DATA" not in {a["action"] for a in run["available_actions"]}  # 条件未满足，不可执行
    assert run["execution_status"] != "COMPLETED"
    assert steps["ACTIVE"]["execution_mode"] == "EXTERNAL_WAIT"
    assert steps["ACTIVE"]["step_status"] not in ("COMPLETED", "READY")   # 外部等待不谎报成功（要求5）

    # 7) 失败有原因（要求4）：缺幂等键 / 重复活跃流程 / 版本冲突
    no_key = client.post("/api/launch", headers=auth_headers,
                         json={"product_id": product.id, "shop_id": shop_a.id})
    assert no_key.status_code == 400 and no_key.json()["detail"]["code"] == "IDEMPOTENCY_REQUIRED"
    dup = client.post("/api/launch", headers={**auth_headers, "Idempotency-Key": "qa-j1-2"},
                      json={"product_id": product.id, "shop_id": shop_a.id})
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "ACTIVE_LAUNCH_EXISTS"
    stale = client.post(f"/api/launch/{run_id}/actions/COMPLETE_DATA",
                        headers={**auth_headers, "Idempotency-Key": "qa-j1-conflict"},
                        json={"step_code": "INFO", "expected_revision": 999, "payload": {}})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "REVISION_CONFLICT"
    assert stale.json()["detail"]["current_revision"] == run["revision"]   # E10 409 回填依据

    # 8) 补素材：E03 真实闭环 —— 缺 market/platform 必 422；带两键（由店铺上下文推导）→ 200
    missing = client.post(f"/api/products/{product.id}/assets", headers=auth_headers,
                          json={k: v for k, v in _asset_body(shop_a).items() if k not in ("market", "platform")})
    assert missing.status_code == 422, "缺 market/platform 必须被 AssetIn 拒绝"
    registered = client.post(f"/api/products/{product.id}/assets", headers=auth_headers,
                             json=_asset_body(shop_a))
    assert registered.status_code == 200, registered.text
    asset = registered.json()
    assert (asset["market"], asset["platform"]) == ("SG", PLATFORM)

    # 9) 核验：E04 真实闭环 —— 自审 403(ASSET_SELF_REVIEW) / 只读 403 / 合规审批 200
    review = {"shop_id": shop_a.id, "expected_version": asset["version"],
              "decision": "VERIFIED", "evidence_ref": "evidence://qa/j1/rights.pdf",
              "reason": "授权书在档"}
    self_review = client.post(f"/api/products/{product.id}/assets/{asset['id']}/verify",
                              headers=auth_headers, json=review)
    assert self_review.status_code == 403 and self_review.json()["detail"]["code"] == "ASSET_SELF_REVIEW"
    viewer = _login(client, READONLY_USER, READONLY_PASS)
    assert client.post(f"/api/products/{product.id}/assets/{asset['id']}/verify",
                       headers=viewer, json=review).status_code == 403     # 要求6
    approver = _login(client, COMPLIANCE_USER, COMPLIANCE_PASS)
    approved = client.post(f"/api/products/{product.id}/assets/{asset['id']}/verify",
                           headers=approver, json=review)
    assert approved.status_code == 200, approved.text
    assert approved.json()["verification_status"] == "VERIFIED"

    # 10) 返回原步骤 + 刷新准备状态与下一动作（要求3）：同一 run_id，补素材后完成条件满足
    refreshed = client.get(f"/api/launch/{run_id}", headers=auth_headers)
    assert refreshed.status_code == 200 and refreshed.json()["id"] == run_id
    assert any(a["action"] == "COMPLETE_DATA" for a in refreshed.json()["available_actions"])
    assert refreshed.json()["next_best_action"]["action"] == "COMPLETE_DATA"

    # 11) 执行本地动作 COMPLETE_DATA（不触发任何外部提交）→ INFO 完成、下一动作前进
    done = client.post(f"/api/launch/{run_id}/actions/COMPLETE_DATA",
                       headers={**auth_headers, "Idempotency-Key": "qa-j1-complete"},
                       json={"step_code": "INFO", "expected_revision": refreshed.json()["revision"], "payload": {}})
    assert done.status_code == 200, done.text
    assert done.json()["step"]["step_status"] == "COMPLETED"
    assert done.json()["launch"]["next_best_action"]["action"] == "SUBMIT_PLATFORM"
    assert done.json()["launch"]["execution_status"] != "COMPLETED"    # 要求5：整体仍未完成
    assert _step_map(client, auth_headers, run_id)["ACTIVE"]["step_status"] not in ("COMPLETED", "READY")

    # 12) 渠道按店铺独立（要求7）：当前只有 target 店有活跃流程
    ch1 = client.get(f"/api/products/{product.id}/channels", headers=auth_headers).json()
    assert ch1["total"] == 1 and ch1["channels"][0]["shop"]["id"] == shop_a.id
    assert ch1["channels"][0]["active_launch"]["id"] == run_id
    assert ch1["channels"][0]["history"] == []


def test_j1_cross_shop_isolation(client, auth_headers, j1_env):
    """要求7：跨店铺不串数据——素材按目标店铺 market+platform 隔离，不跨市场串。"""
    db, ctx, product, shops = j1_env
    shop_sg, shop_us = shops   # SG / US 不同市场

    client.post(f"/api/products/{product.id}/assets", headers=auth_headers,
                json=_asset_body(shop_sg, asset_key="sg_only"))
    client.post(f"/api/products/{product.id}/assets", headers=auth_headers,
                json=_asset_body(shop_us, asset_key="us_only"))

    list_sg = client.get(f"/api/products/{product.id}/assets", headers=auth_headers,
                         params={"shop_id": shop_sg.id}).json()
    list_us = client.get(f"/api/products/{product.id}/assets", headers=auth_headers,
                         params={"shop_id": shop_us.id}).json()
    assert {item["asset_key"] for item in list_sg["items"]} == {"sg_only"}
    assert {item["asset_key"] for item in list_us["items"]} == {"us_only"}

    # 用 US 店商城币核验 SG 素材必须被拒（不跨市场串）
    us_asset = list_us["items"][0]
    misfit = client.post(f"/api/products/{product.id}/assets/{us_asset['id']}/verify", headers=auth_headers,
                         json={"shop_id": shop_sg.id, "expected_version": us_asset["version"],
                               "decision": "VERIFIED", "evidence_ref": "evidence://qa/x.pdf",
                               "reason": "跨市场尝试"})
    assert misfit.status_code == 404, misfit.text

    # 只读账号不能登记（服务端拒绝，要求6）
    viewer = _login(client, READONLY_USER, READONLY_PASS)
    denied = client.post(f"/api/products/{product.id}/assets", headers=viewer, json=_asset_body(shop_sg))
    assert denied.status_code == 403
