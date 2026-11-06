"""Launch API HTTP 契约（B10）：context/创建/列表/详情/步骤/动作/sync/事件 + 渠道聚合。

覆盖 PRD AC-1~3、AC-10~13。全部在隔离测试库运行，demo 店铺走本地发布路径，
不调用任何真实平台，也不触碰业务主库。夹具用独立平台 ``launchapi`` 与自建
CONTRACT_TEST 流程，避免与其它测试的规则包/Profile 交叉。
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
from app.workflows import launch_dto
from app.workflows.launch_access import LaunchError
from app.workflows.launch_records import create_launch
from app.workflows.profiles import create_profile, publish_profile

PLATFORM = "launchapi"
CONTRACT = "API_PROBE"
COMPLIANCE_USER = "launch-api-compliance"
FACTORY_USER = "launch-api-factory"
# DTO 契约：响应中绝不出现价格/成本/利润率/备货数量字段（AC-3.2，递归断言）。
_FORBIDDEN_KEYS = frozenset({"price", "cost", "margin", "profit", "stock", "stock_qty",
                             "supply_price", "cost_price", "profit_rate", "cost_snapshot"})


def _api_profile(version=1):
    """本地契约流程：资料 -> 提交 -> 在售核验 -> 监控。"""
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
    return {"profile_key": CONTRACT, "version": version, "name": "Launch API 本地契约样本",
            "description": "本地流程验证，不代表真实平台接入。",
            "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
            "platform": PLATFORM, "market": "SG", "fulfillment_mode": "DROPSHIP",
            "category_scope": ["ANY"], "status_mapping": {"unknown": "BLOCK", "statuses": {}},
            "steps": steps}


@pytest.fixture
def api_env(client):
    with SessionLocal() as db:
        owner = db.query(User).filter_by(username="admin").one()
        ctx = resolve_workspace_context(db, owner)
        tenant = ctx.legacy_tenant_id
        product = Product(tenant_id=tenant, sku="launch-api", title="API product", category="家居",
                          images=["https://example.com/main.jpg"], attrs={"destination_country": "SG"})
        shops = [Shop(tenant_id=tenant, platform=PLATFORM, shop_name=name, market="SG",
                      fulfillment_mode="DROPSHIP", is_demo=True) for name in ("API A", "API B")]
        extra = [User(tenant_id=tenant, username=COMPLIANCE_USER, password_hash=hash_password("compliance-pass"),
                      role="compliance", display_name="合规员"),
                 User(tenant_id=tenant, username=FACTORY_USER, password_hash=hash_password("factory-pass"),
                      role="supplier", display_name="工厂协作")]
        db.add_all([product, *shops, *extra])
        db.flush()
        db.add(ProductAsset(tenant_id=tenant, workspace_id=tenant, product_id=product.id,
                            asset_key="main", version=1, asset_type="MAIN_IMAGE", uri=product.images[0],
                            content_hash="b" * 64, rights_status="OWNED", source="launch api fixture",
                            rights_evidence_ref="evidence://fixture/source", market="SG", platform=PLATFORM,
                            verification_status="MANUAL_REPORTED", created_by=owner.id))
        db.commit()
        profile = create_profile(db, ctx, _api_profile())
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
    db.query(User).filter(User.username.in_((COMPLIANCE_USER, FACTORY_USER))).delete(synchronize_session=False)
    db.delete(product)
    for shop in shops:
        db.delete(shop)
    db.commit()


def _create(client, auth_headers, product, shop, key="api-create", **extra):
    body = {"product_id": product.id, "shop_id": shop.id, **extra}
    return client.post("/api/launch", headers={**auth_headers, "Idempotency-Key": key}, json=body)


def _login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def _assert_no_forbidden_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            assert key.lower() not in _FORBIDDEN_KEYS, "响应含价格/成本/备货字段：" + key
            _assert_no_forbidden_keys(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_forbidden_keys(item)


# ------------------------------------------------------------------ AC-13 上下文与创建

def test_context_lists_scope_shops_and_creation_gate(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    response = client.get("/api/launch/context", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effective_experience_mode"] == "GUIDED" and body["can_create"] is True
    assert body["blocked_reason"] is None and body["permissions"]
    ours = {shop["id"]: shop for shop in body["shops"] if shop["id"] in {s.id for s in shops}}
    assert ours[shops[0].id]["profile_available"] is True and ours[shops[0].id]["usable"] is True


def test_create_returns_detail_replays_and_blocks_active(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    created = _create(client, auth_headers, product, shops[0])
    assert created.status_code == 200, created.text
    detail = created.json()
    run_id = detail["id"]
    assert detail["revision"] >= 1 and detail["store"]["id"] == shops[0].id
    assert detail["next_best_action"]["action"] == "COMPLETE_DATA"
    assert detail["verification_notice"] == "本地流程验证，不代表真实平台接入"   # AC-2.5/13.1
    replayed = _create(client, auth_headers, product, shops[0])
    assert replayed.status_code == 200 and replayed.json()["id"] == run_id       # AC-13.2
    conflict = _create(client, auth_headers, product, shops[0], key="different")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "ACTIVE_LAUNCH_EXISTS"
    assert conflict.json()["detail"]["existing_launch_id"] == run_id


def test_create_requires_idempotency_key(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    response = client.post("/api/launch", headers=auth_headers,
                           json={"product_id": product.id, "shop_id": shops[0].id})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "IDEMPOTENCY_REQUIRED"


def test_create_production_without_profile_returns_not_found(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    response = _create(client, auth_headers, product, shops[0], key="prod",
                       environment="PRODUCTION")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "PROFILE_NOT_FOUND"


# ------------------------------------------------------------------ AC-1 列表

def test_list_filters_pagination_and_validation(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    listing = client.get("/api/launch", headers=auth_headers, params={"product_id": product.id})
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["page_num"] == 1 and body["page_size"] == 20 and body["total"] >= 1
    assert any(item["id"] == run_id for item in body["items"])
    mine = client.get("/api/launch", headers=auth_headers,
                      params={"product_id": product.id, "mine": True})
    assert any(item["id"] == run_id for item in mine.json()["items"])   # AC-1.4 资料步骤分配给创建者
    assert client.get("/api/launch", headers=auth_headers, params={"page_size": 500}).status_code == 422
    assert client.get("/api/launch", headers=auth_headers, params={"sort": "desc"}).status_code == 422
    bad = client.get("/api/launch", headers=auth_headers, params={"execution_status": "NOPE"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "FILTER_INVALID"


# ------------------------------------------------------------------ AC-2/3 详情与步骤

def test_detail_fields_and_read_only_does_not_bump_revision(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    detail = client.get(f"/api/launch/{run_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    for key in ("profile", "revision", "progress", "current_steps", "blockers", "available_actions",
                "next_best_action", "recommendations", "steps", "last_synced_at",
                "professional_links", "monitoring", "disabled_actions"):
        assert key in body, key
    assert body["monitoring"]["status"] == "UNAVAILABLE"   # AC-2.3
    assert all(item["source"] == "rule" for item in body["recommendations"])   # AC-2.4
    assert {link["path"] for link in body["professional_links"]}   # 合规链接确定映射
    _assert_no_forbidden_keys(body)
    before = body["revision"]
    viewer = _login(client, "viewer", "viewer123")
    readonly = client.get(f"/api/launch/{run_id}", headers=viewer)
    assert readonly.status_code == 200 and readonly.json()["revision"] == before   # AC-2.2 只读不落库


def test_steps_dto_has_evidence_and_no_price_fields(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    response = client.get(f"/api/launch/{run_id}/steps", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"] >= 1 and body["profile"]["key"] == CONTRACT
    steps = {item["step_code"]: item for item in body["items"]}
    assert steps["INFO"]["available_actions"][0]["action"] == "COMPLETE_DATA"
    assert "INFORMATION_EVIDENCE" in steps["INFO"]["evidence_requirements"]   # AC-3.1
    assert "INFORMATION_EVIDENCE" in steps["INFO"]["missing_evidence"]
    assert steps["ACTIVE"]["external"]["type"] == "UNKNOWN"
    _assert_no_forbidden_keys(body)


def test_compliance_projection_has_no_price_fields(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    compliance = _login(client, COMPLIANCE_USER, "compliance-pass")
    response = client.get(f"/api/launch/{run_id}", headers=compliance)
    assert response.status_code == 200, response.text
    _assert_no_forbidden_keys(response.json())
    assert client.post(f"/api/launch/{run_id}/sync", headers=compliance,
                       json={"mode": "refresh", "expected_revision": 1}).status_code == 403   # AC-3.3


# ------------------------------------------------------------------ AC-4/8 动作执行

def test_action_executes_and_replays_idempotently(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    revision = client.get(f"/api/launch/{run_id}", headers=auth_headers).json()["revision"]
    headers = {**auth_headers, "Idempotency-Key": "complete-1"}
    body = {"step_code": "INFO", "expected_revision": revision, "payload": {"note": "资料已核对"}}
    first = client.post(f"/api/launch/{run_id}/actions/COMPLETE_DATA", headers=headers, json=body)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["status"] == "EXECUTED" and payload["step"]["step_status"] == "COMPLETED"
    assert payload["launch"]["id"] == run_id
    replay = client.post(f"/api/launch/{run_id}/actions/COMPLETE_DATA", headers=headers, json=body)
    assert replay.status_code == 200 and replay.json()["event_id"] == payload["event_id"]   # AC-4.1


def test_action_requires_idempotency_key(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    response = client.post(f"/api/launch/{run_id}/actions/COMPLETE_DATA", headers=auth_headers,
                           json={"step_code": "INFO", "expected_revision": 1, "payload": {}})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "IDEMPOTENCY_REQUIRED"


def test_read_only_member_cannot_execute(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    viewer = _login(client, "viewer", "viewer123")
    response = client.post(f"/api/launch/{run_id}/actions/COMPLETE_DATA",
                           headers={**viewer, "Idempotency-Key": "viewer-1"},
                           json={"step_code": "INFO", "expected_revision": 1, "payload": {}})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "PERMISSION_DENIED"


# ------------------------------------------------------------------ AC-10 sync

def test_sync_refresh_and_mode_validation(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    detail = _create(client, auth_headers, product, shops[0]).json()
    run_id, revision = detail["id"], detail["revision"]
    response = client.post(f"/api/launch/{run_id}/sync", headers=auth_headers,
                           json={"mode": "refresh", "expected_revision": revision})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["refreshed"] is True and body["launch"]["id"] == run_id
    assert body["launch"]["last_synced_at"] is not None   # AC-10.5
    unsupported = client.post(f"/api/launch/{run_id}/sync", headers=auth_headers,
                              json={"mode": "push", "expected_revision": revision})
    assert unsupported.status_code == 422
    assert unsupported.json()["detail"]["supported"] == ["refresh", "platform_status"]   # AC-10.1
    injected = client.post(f"/api/launch/{run_id}/sync", headers=auth_headers,
                           json={"mode": "refresh", "expected_revision": revision,
                                 "platform_status": "ACTIVE"})
    assert injected.status_code == 422   # AC-10.3 extra=forbid


# ------------------------------------------------------------------ AC-11 事件

def test_events_paginate_ascending_and_redact(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    response = client.get(f"/api/launch/{run_id}/events", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 2 and body["items"]
    sequences = [item["sequence"] for item in body["items"]]
    assert sequences == sorted(sequences)   # AC-11.1 升序
    assert any(item["event_type"] == "LaunchCreated" for item in body["items"])
    beyond = client.get(f"/api/launch/{run_id}/events", headers=auth_headers,
                        params={"page_num": 99, "page_size": 20})
    assert beyond.status_code == 200 and beyond.json()["items"] == []   # AC-11.3


# ------------------------------------------------------------------ AC-12 渠道聚合 + Factory

def test_product_channels_aggregates_sales_shops(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    response = client.get(f"/api/products/{product.id}/channels", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["product"]["id"] == product.id and body["total"] == 1   # 仅 shop A 有流程
    channel = body["channels"][0]
    assert channel["shop"]["id"] == shops[0].id and channel["active_launch"]["id"] == run_id
    assert channel["history"] == []
    _assert_no_forbidden_keys(body)
    assert client.get("/api/products/999999/channels", headers=auth_headers).status_code == 404


def test_factory_identity_cannot_read_launch(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run_id = _create(client, auth_headers, product, shops[0]).json()["id"]
    factory = db.query(User).filter_by(username=FACTORY_USER).one()
    with pytest.raises(LaunchError) as denied:
        launch_dto.load_detail(db, resolve_workspace_context(db, factory), run_id)
    assert denied.value.code == "LAUNCH_NOT_FOUND" and denied.value.status_code == 404   # AC-3.4


def test_relaunch_only_from_cancelled_same_object(client, auth_headers, api_env):
    db, ctx, product, shops = api_env
    run = create_launch(db, ctx, product.id, shops[0].id, "relaunch-base")
    db.commit()
    response = _create(client, auth_headers, product, shops[1], key="relaunch",
                       previous_run_id=run.id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "RELAUNCH_NOT_READY"
