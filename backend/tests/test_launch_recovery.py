"""Launch 进程级恢复契约（AC-8.5 / 设计 D12）：启动扫描的回收、待核查标注与幂等。

直接调用 ``app.workflows.launch_recovery.recover_launch_steps``（系统身份、无用户 ctx），
不经 HTTP，验证「重启即回收」的确定性行为，且**不调用任何外部适配器、不重发**。

夹具用独立平台 ``launchrecover`` 与自建 CONTRACT_TEST 流程，避免与其它测试的规则包/
Profile 交叉；该流程为本地契约样本，不代表任何真实平台接入。
"""

import pytest

from app.db import SessionLocal
from app.models import (
    AiAction,
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
    utcnow,
)
from app.services.workspace_context import resolve_workspace_context
from app.workflows.launch_records import create_launch
from app.workflows.launch_recovery import PENDING_REASON, READY_REASON, recover_launch_steps
from app.workflows.profiles import create_profile, publish_profile

PLATFORM = "launchrecover"
PROFILE_KEY = "RECOVERY_PROBE"


def _profile():
    """本地契约流程：资料 -> 提交 -> 在售核验 -> 监控；用于进程恢复可执行性验证。"""
    steps = [
        {"step_code": "INFORMATION", "step_name": "商品资料", "business_type": "DATA_PREPARATION",
         "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 0, "required": True,
         "dependencies": [], "available_actions": ["COMPLETE_DATA"],
         "evidence_requirements": ["INFORMATION_EVIDENCE"],
         "completion_condition": {"all": [{"present": "product.title"},
                                          {"asset_rights_allowed": "PUBLISHABLE"}]}},
        {"step_code": "SUBMISSION", "step_name": "提交平台", "business_type": "PLATFORM_SUBMISSION",
         "execution_mode": "ADAPTER_TASK", "actor": "SYSTEM", "sequence": 1, "required": True,
         "dependencies": ["INFORMATION"], "available_actions": ["SUBMIT_PLATFORM"],
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
    return {"profile_key": PROFILE_KEY, "version": 1, "name": "进程恢复本地契约样本",
            "description": "本地流程验证，不代表真实平台接入。",
            "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
            "platform": PLATFORM, "market": "SG", "fulfillment_mode": "DROPSHIP",
            "category_scope": ["ANY"],
            "status_mapping": {"unknown": "BLOCK", "statuses": {}}, "steps": steps}


@pytest.fixture
def env(client):
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").one()
        ctx = resolve_workspace_context(db, admin)
        tenant = ctx.legacy_tenant_id
        product = Product(tenant_id=tenant, sku="launch-recovery", title="Recovery product",
                          category="家居", images=["https://example.com/main.jpg"],
                          attrs={"destination_country": "SG"})
        shop = Shop(tenant_id=tenant, platform=PLATFORM, shop_name="Recovery shop", market="SG",
                    fulfillment_mode="DROPSHIP", is_demo=True)
        db.add_all([product, shop])
        db.flush()
        db.add(ProductAsset(tenant_id=tenant, workspace_id=tenant, product_id=product.id,
                            asset_key="main", version=1, asset_type="MAIN_IMAGE", uri=product.images[0],
                            content_hash="c" * 64, rights_status="OWNED", source="recovery fixture",
                            rights_evidence_ref="evidence://fixture/recovery", market="SG",
                            platform=PLATFORM, verification_status="MANUAL_REPORTED", created_by=admin.id))
        profile = create_profile(db, ctx, _profile())
        publish_profile(db, ctx, profile.id, profile.definition_hash)
        db.commit()
        yield db, ctx, product, shop
        db.rollback()
        _cleanup(db, tenant, product, shop)


def _cleanup(db, tenant, product, shop):
    run_ids = [row[0] for row in db.query(WorkflowRun.id).filter_by(product_id=product.id).all()]
    listing_ids = [row[0] for row in db.query(Listing.id).filter_by(product_id=product.id).all()]
    db.query(WorkflowRun).filter(WorkflowRun.product_id == product.id).update(
        {"previous_run_id": None}, synchronize_session=False)
    if run_ids:
        db.query(WorkflowEvent).filter(WorkflowEvent.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(WorkflowStep).filter(WorkflowStep.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).delete(synchronize_session=False)
    if listing_ids:
        db.query(PlatformPublishAttempt).filter(PlatformPublishAttempt.listing_id.in_(listing_ids)).delete(
            synchronize_session=False)
        db.query(AiAction).filter(AiAction.target_id.in_(listing_ids)).delete(synchronize_session=False)
    db.query(Listing).filter(Listing.product_id == product.id).delete(synchronize_session=False)
    db.query(ProductAsset).filter(ProductAsset.product_id == product.id).delete(synchronize_session=False)
    db.query(WorkflowTemplate).filter(WorkflowTemplate.tenant_id == tenant,
                                      WorkflowTemplate.profile_key == PROFILE_KEY).delete(
        synchronize_session=False)
    db.delete(product)
    db.delete(shop)
    db.commit()


def _start(db, ctx, product, shop, key="recovery-run"):
    run = create_launch(db, ctx, product.id, shop.id, key)
    db.commit()
    return run


def _run(db, run_id):
    return db.get(WorkflowRun, run_id, populate_existing=True)


def _step(db, run_id, code):
    return db.query(WorkflowStep).filter_by(run_id=run_id, step_code=code).one()


def _set_running(db, run_id, code):
    _step(db, run_id, code).step_status = "RUNNING"
    db.commit()


def _recovered_events(db, run_id):
    return db.query(WorkflowEvent).filter_by(run_id=run_id, event_type="LaunchRecovered").all()


def test_startup_scan_resets_running_without_intent(env):
    """(a) 无意图 RUNNING → READY，且恰好一条 SYSTEM 身份的 LaunchRecovered。"""
    db, ctx, product, shop = env
    recover_launch_steps(db)  # 预热：清空会话库既有可回收项，使后续计数确定
    run = _start(db, ctx, product, shop)
    _set_running(db, run.id, "SUBMISSION")
    revision_before = _run(db, run.id).revision
    assert recover_launch_steps(db) == 1
    assert _step(db, run.id, "SUBMISSION").step_status == "READY"
    assert _run(db, run.id).revision == revision_before + 1
    events = _recovered_events(db, run.id)
    assert len(events) == 1
    event = events[0]
    assert event.source == "SYSTEM" and event.actor_id is None
    assert event.payload == {"reason": READY_REASON}
    assert event.after["steps"]["SUBMISSION"]["status"] == "READY"
    assert event.after["revision"] == revision_before + 1


def test_startup_scan_marks_intent_pending_without_resend(env):
    """(b) 有意图 RUNNING → 保持 RUNNING + pending_verification=true，且不重发。"""
    db, ctx, product, shop = env
    recover_launch_steps(db)
    run = _start(db, ctx, product, shop)
    _set_running(db, run.id, "SUBMISSION")
    db.add(AiAction(tenant_id=product.tenant_id, workspace_id=ctx.workspace_id,
                    task_id=None, agent_type="listing", action_type="PUBLISH_LISTING",
                    target_type="listing", target_id=run.listing_id, reason="fixture",
                    evidence={"launch_id": run.id, "step_code": "SUBMISSION",
                              "payload": {"shop_id": run.shop_id}},
                    expected_impact={}, risk_level="MEDIUM", required_permission="listing:write",
                    execution_mode="APPROVAL_REQUIRED", approval_required=True, status="EXECUTING",
                    requested_by=ctx.user_id, outcome={}, idempotency_key="recover-intent"))
    db.commit()
    actions_before = db.query(AiAction).filter(AiAction.target_id == run.listing_id).count()
    attempts_before = db.query(PlatformPublishAttempt).filter_by(listing_id=run.listing_id).count()
    assert recover_launch_steps(db) == 1
    step = _step(db, run.id, "SUBMISSION")
    assert step.step_status == "RUNNING" and step.result["pending_verification"] is True
    events = _recovered_events(db, run.id)
    assert len(events) == 1
    assert events[0].payload == {"reason": PENDING_REASON, "pending_verification": True}
    # 不重发：外部适配器零调用（无新增 AiAction / Attempt）。
    assert db.query(AiAction).filter(AiAction.target_id == run.listing_id).count() == actions_before
    assert db.query(PlatformPublishAttempt).filter_by(listing_id=run.listing_id).count() == attempts_before


def test_startup_scan_is_idempotent_on_second_call(env):
    """(c) 连续两次：第二次零新事件、零 revision 变化（R9 幂等）。"""
    db, ctx, product, shop = env
    recover_launch_steps(db)
    run = _start(db, ctx, product, shop)
    _set_running(db, run.id, "SUBMISSION")
    assert recover_launch_steps(db) == 1
    revision_after_first = _run(db, run.id).revision
    events_after_first = db.query(WorkflowEvent).filter_by(run_id=run.id).count()
    assert recover_launch_steps(db) == 0
    assert _run(db, run.id).revision == revision_after_first
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == events_after_first


def test_startup_scan_ignores_cancelled_and_ended(env):
    """(d) 已 CANCELLED / 已结束的 run 不被触碰。"""
    db, ctx, product, shop = env
    recover_launch_steps(db)
    run = _start(db, ctx, product, shop)
    _set_running(db, run.id, "SUBMISSION")
    current = _run(db, run.id)
    current.execution_status = "CANCELLED"
    current.ended_at = utcnow()
    current.active_slot = None
    db.commit()
    revision_before = _run(db, run.id).revision
    assert recover_launch_steps(db) == 0
    assert _step(db, run.id, "SUBMISSION").step_status == "RUNNING"
    assert _run(db, run.id).revision == revision_before
    assert _recovered_events(db, run.id) == []
