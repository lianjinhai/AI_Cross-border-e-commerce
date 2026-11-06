"""P0-2 平台状态摄入契约：映射、迁移守卫、乱序丢弃、在售不可由摄入置位。

覆盖 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md` §5：
- raw_status 经 Profile `status_mapping` 映射为 platform_status（此前该配置从未被消费）
- 未注册 raw_status → UNKNOWN + PLATFORM_ERROR，不推进
- 旧序号/重复序号事件只留审计，不回退状态
- **摄入路径永远不能把状态置为 ACTIVE**（在售须走 CONFIRM_ACTIVATION 独立核验）

夹具使用独立平台 ``p01sync`` 与自建 Profile，避免与其它 Launch 测试的规则包交叉。
"""

from uuid import uuid4

import pytest

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
from app.workflows.launch_records import create_launch
from app.workflows.launch_status import (
    PLATFORM_TRANSITIONS,
    can_transition,
    is_activated,
    is_stale_event,
    is_verified_online,
    map_platform_status,
)
from app.workflows.profiles import ProfileError, create_profile, publish_profile

PLATFORM = "p01sync"
PROFILE_KEY = "P01_SYNC"
# 映射故意混用大小写：验证「精确匹配失败后大小写不敏感回退」。
STATUS_MAPPING = {"unknown": "BLOCK", "statuses": {
    "SHOPEE_REVIEWING": "UNDER_REVIEW",
    "SHOPEE_ACCEPTED": "ACCEPTED",
    "shopee_submitted": "SUBMITTED",
}}


# ------------------------------------------------------------------ 纯函数：映射

def test_map_uses_profile_status_mapping_exact_match():
    assert map_platform_status("SHOPEE_REVIEWING", STATUS_MAPPING) == ("UNDER_REVIEW", None)


def test_map_falls_back_to_case_insensitive():
    assert map_platform_status("Shopee_Submitted", STATUS_MAPPING) == ("SUBMITTED", None)


@pytest.mark.parametrize("raw", ["", "   ", "PLATFORM_SAYS_WHATEVER", None])
def test_unregistered_raw_status_never_advances(raw):
    """不认识的原始状态必须 UNKNOWN + PLATFORM_ERROR（§5 末行），不得猜。"""
    status, error = map_platform_status(raw, STATUS_MAPPING)
    assert status == "UNKNOWN"
    assert error == "PLATFORM_ERROR"


def test_mapping_to_non_platform_state_is_rejected():
    """映射到核验事实或拼写错误一律视为未注册，防止两域互串。"""
    bad = {"unknown": "BLOCK", "statuses": {"X": "VERIFIED"}}
    assert map_platform_status("X", bad) == ("UNKNOWN", "PLATFORM_ERROR")


def test_missing_status_mapping_degrades_to_error():
    assert map_platform_status("SHOPEE_REVIEWING", None) == ("UNKNOWN", "PLATFORM_ERROR")
    assert map_platform_status("SHOPEE_REVIEWING", {}) == ("UNKNOWN", "PLATFORM_ERROR")


# ------------------------------------------------------------------ 纯函数：迁移守卫

def test_forward_chain_is_allowed():
    assert can_transition("NOT_SUBMITTED", "SUBMITTED")
    assert can_transition("SUBMITTED", "UNDER_REVIEW")
    assert can_transition("UNDER_REVIEW", "ACCEPTED")


def test_active_is_never_a_transition_target():
    """机器可校验的不变量：摄入无法伪造在售。"""
    targets = set().union(*PLATFORM_TRANSITIONS.values())
    assert "ACTIVE" not in targets
    for source in PLATFORM_TRANSITIONS:
        if source == "ACTIVE":
            continue          # 同状态视为幂等重放，不是「迁入 ACTIVE」
        assert not can_transition(source, "ACTIVE"), source


def test_backward_and_shortcut_transitions_are_rejected():
    assert not can_transition("ACCEPTED", "UNDER_REVIEW")      # 回退
    assert not can_transition("SUBMITTED", "NOT_SUBMITTED")    # 回退
    assert not can_transition("OFFLINE", "ACTIVE")             # 须重新核验


def test_rejected_can_be_resubmitted_and_same_state_is_idempotent():
    assert can_transition("REJECTED", "SUBMITTED")
    assert can_transition("ACCEPTED", "ACCEPTED")


def test_stale_event_detection():
    assert is_stale_event(1, 2) is True        # 更旧
    assert is_stale_event(2, 2) is True        # 重复
    assert is_stale_event(3, 2) is False       # 更新
    assert is_stale_event(None, 2) is False    # 无序号：不判定为旧
    assert is_stale_event(2, None) is False    # 首个事件


def test_verified_online_and_activated_helpers():
    class Run:
        platform_status = "ACTIVE"
        verification_status = "VERIFIED"
        completed_at = None

    run = Run()
    assert is_verified_online(run) is True
    assert is_activated("ACCEPTED", None) is False
    assert is_activated("ACTIVE", None) is False        # 未完成不算上线后
    run.verification_status = "PENDING_VERIFICATION"
    assert is_verified_online(run) is False             # 平台 ACTIVE 但未核验 ≠ 在售


# ------------------------------------------------------------------ 夹具

def _profile():
    steps = [
        {"step_code": "INFO", "step_name": "商品资料", "business_type": "DATA_PREPARATION",
         "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 0, "required": True,
         "dependencies": [], "available_actions": ["COMPLETE_DATA"],
         "evidence_requirements": ["INFORMATION_EVIDENCE"],
         "completion_condition": {"present": "product.title"}},
        # 契约要求：必须有唯一且始终必需的在售核验节点。
        {"step_code": "ACTIVE", "step_name": "在售核验", "business_type": "PLATFORM_ACTIVATION",
         "execution_mode": "EXTERNAL_WAIT", "actor": "PLATFORM", "sequence": 1, "required": True,
         "dependencies": ["INFO"], "available_actions": ["CONFIRM_ACTIVATION"],
         "completion_condition": {"all": [{"eq": {"field": "platform.status", "value": "ACTIVE"}},
                                          {"verified_artifact": "ACTIVATION"}]}},
    ]
    return {"profile_key": PROFILE_KEY, "version": 1, "name": "P0-2 平台状态摄入样本",
            "description": "仅用于验证状态摄入，不代表真实平台接入。",
            "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
            "platform": PLATFORM, "market": "SG", "fulfillment_mode": "DROPSHIP",
            "category_scope": ["ANY"], "status_mapping": STATUS_MAPPING, "steps": steps}


@pytest.fixture
def sync_env(client, auth_headers):
    """独立租户内造 商品/店铺/Profile，返回 run_id / revision / 尝试行键。"""
    with SessionLocal() as db:
        owner = db.query(User).filter_by(username="admin").one()
        ctx = resolve_workspace_context(db, owner)
        tenant = ctx.legacy_tenant_id
        product = Product(tenant_id=tenant, sku="p01-sync", title="P0-2 状态摄入商品", category="家居",
                          images=["https://example.com/p01.jpg"],
                          attrs={"destination_country": "SG"})
        shop = Shop(tenant_id=tenant, platform=PLATFORM, shop_name="P0-2 店铺", market="SG",
                    fulfillment_mode="DROPSHIP", is_demo=True)
        db.add_all([product, shop])
        db.flush()
        db.add(ProductAsset(tenant_id=tenant, workspace_id=tenant, product_id=product.id,
                            asset_key="main", version=1, asset_type="MAIN_IMAGE",
                            uri=product.images[0], content_hash="c" * 64, rights_status="OWNED",
                            source="p0-2 fixture", rights_evidence_ref="evidence://p02/source",
                            market="SG", platform=PLATFORM,
                            verification_status="MANUAL_REPORTED", created_by=owner.id))
        db.commit()
        # 规则包可能因上一轮异常退出而残留（Windows 下测试库文件偶发删不掉，
        # 见 conftest._fresh_db 的说明）；版本已存在时直接复用，不重复建。
        try:
            profile = create_profile(db, ctx, _profile())
            publish_profile(db, ctx, profile.id, profile.definition_hash)
            db.commit()
        except ProfileError as exc:
            db.rollback()
            if exc.code != "PROFILE_VERSION_EXISTS":
                raise
        run = create_launch(db, ctx, product.id, shop.id, "p01-sync-" + uuid4().hex)
        db.commit()
        run_id, revision, listing_id, shop_id = run.id, run.revision, run.listing_id, shop.id
        # 发布尝试行：外部事件留痕的载体（source/source_time/external_reference/source_revision）。
        attempt_key = "p02-attempt-" + uuid4().hex
        db.add(PlatformPublishAttempt(tenant_id=tenant, listing_id=listing_id, shop_id=shop_id,
                                      platform=PLATFORM, idempotency_key=attempt_key,
                                      status="succeeded", external_id="P02-EXT-1"))
        db.commit()
        yield {"run_id": run_id, "revision": revision, "tenant": tenant, "attempt_key": attempt_key}
        _cleanup(db, tenant, product, shop)


def _cleanup(db, tenant, product, shop):
    run_ids = [row[0] for row in db.query(WorkflowRun.id).filter_by(product_id=product.id).all()]
    listing_ids = [row[0] for row in db.query(Listing.id).filter_by(product_id=product.id).all()]
    db.query(WorkflowRun).filter(WorkflowRun.product_id == product.id).update(
        {"previous_run_id": None}, synchronize_session=False)
    if run_ids:
        db.query(WorkflowEvent).filter(WorkflowEvent.run_id.in_(run_ids)).delete(
            synchronize_session=False)
        db.query(WorkflowStep).filter(WorkflowStep.run_id.in_(run_ids)).delete(
            synchronize_session=False)
        db.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).delete(synchronize_session=False)
    if listing_ids:
        db.query(PlatformPublishAttempt).filter(
            PlatformPublishAttempt.listing_id.in_(listing_ids)).delete(synchronize_session=False)
    db.query(Listing).filter(Listing.product_id == product.id).delete(synchronize_session=False)
    db.query(ProductAsset).filter(ProductAsset.product_id == product.id).delete(
        synchronize_session=False)
    db.query(WorkflowTemplate).filter(WorkflowTemplate.tenant_id == tenant,
                                      WorkflowTemplate.profile_key == PROFILE_KEY).delete(
        synchronize_session=False)
    db.delete(product)
    db.delete(shop)
    db.commit()


def _sync(client, auth_headers, env, revision, **body):
    return client.post(f"/api/launch/{env['run_id']}/sync", headers=auth_headers,
                       json={"mode": "platform_status", "expected_revision": revision, **body})


# ------------------------------------------------------------------ HTTP 契约

def test_platform_status_chain_is_reachable(client, auth_headers, sync_env):
    """正例：SUBMITTED → UNDER_REVIEW → ACCEPTED 全链路可走（P0-1 F3 的修复目标）。"""
    revision = sync_env["revision"]
    submitted = _sync(client, auth_headers, sync_env, revision,
                      raw_status="shopee_submitted", source="API", source_revision=1)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["changed"] is True
    assert submitted.json()["platform_status"] == "SUBMITTED"

    revision = submitted.json()["revision"]
    reviewing = _sync(client, auth_headers, sync_env, revision,
                      raw_status="SHOPEE_REVIEWING", source="API", source_revision=2)
    assert reviewing.status_code == 200, reviewing.text
    assert reviewing.json()["platform_status"] == "UNDER_REVIEW"

    revision = reviewing.json()["revision"]
    accepted = _sync(client, auth_headers, sync_env, revision,
                     raw_status="Shopee_Accepted", source="API", source_revision=3)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["platform_status"] == "ACCEPTED"
    # 摄入不改核验事实：ACCEPTED 不等于在售。
    assert accepted.json()["launch"]["verification_status"] != "VERIFIED"


def test_unmapped_raw_status_keeps_state_and_records_error(client, auth_headers, sync_env):
    revision = sync_env["revision"]
    response = _sync(client, auth_headers, sync_env, revision,
                     raw_status="PLATFORM_SAYS_WHATEVER", source="API")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is False
    assert body["error"] == "PLATFORM_ERROR"
    assert body["platform_status"] == "NOT_SUBMITTED"     # 不推进
    assert body["revision"] == revision                   # 不涨版本


def test_stale_revision_is_audited_without_regression(client, auth_headers, sync_env):
    revision = sync_env["revision"]
    first = _sync(client, auth_headers, sync_env, revision,
                  raw_status="SHOPEE_ACCEPTED", source="API", source_revision=5)
    assert first.status_code == 200 and first.json()["platform_status"] == "ACCEPTED"

    stale = _sync(client, auth_headers, sync_env, first.json()["revision"],
                  raw_status="shopee_submitted", source="API", source_revision=4)
    assert stale.status_code == 200, stale.text
    assert stale.json()["changed"] is False
    assert stale.json()["error"] == "STALE_EVENT"
    assert stale.json()["platform_status"] == "ACCEPTED"   # 不回退


def test_backward_transition_is_rejected(client, auth_headers, sync_env):
    revision = sync_env["revision"]
    accepted = _sync(client, auth_headers, sync_env, revision,
                     raw_status="SHOPEE_ACCEPTED", source="API", source_revision=1)
    assert accepted.json()["platform_status"] == "ACCEPTED"
    rejected = _sync(client, auth_headers, sync_env, accepted.json()["revision"],
                     raw_status="SHOPEE_REVIEWING", source="API", source_revision=2)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "PLATFORM_TRANSITION_INVALID"


def test_active_cannot_be_injected(client, auth_headers, sync_env):
    """反例：幻想直接用同步接口把状态置为 ACTIVE / 直接写 platform_status 字段，均被拒。"""
    revision = sync_env["revision"]
    injected = _sync(client, auth_headers, sync_env, revision, platform_status="ACTIVE")
    assert injected.status_code == 422                    # extra=forbid，无此入参


def test_revision_conflict_is_reported(client, auth_headers, sync_env):
    stale_revision = sync_env["revision"] + 99
    response = _sync(client, auth_headers, sync_env, stale_revision,
                     raw_status="SHOPEE_REVIEWING", source="API")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVISION_CONFLICT"


def test_attempt_provenance_is_recorded(client, auth_headers, sync_env):
    """外部事件七要素留痕（§5）：来源、外部引用、序号、映射版本。"""
    revision = sync_env["revision"]
    response = _sync(client, auth_headers, sync_env, revision, raw_status="SHOPEE_REVIEWING",
                     source="API", external_reference="EXT-OBJ-9", source_revision=7)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        attempt = db.query(PlatformPublishAttempt).filter_by(
            platform=PLATFORM, idempotency_key=sync_env["attempt_key"]).first()
        assert attempt is not None
        assert attempt.raw_status == "SHOPEE_REVIEWING"
        assert attempt.source == "API"
        assert attempt.external_reference == "EXT-OBJ-9"
        assert attempt.source_revision == 7
        assert attempt.mapping_version == "platform-status-v1"
        assert attempt.received_at is not None
