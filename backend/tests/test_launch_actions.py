"""Launch 动作执行框架契约：幂等、revision CAS、状态机守卫、权限/Scope、事件与恢复。

覆盖增量 PRD AC-4（框架）、AC-5（COMPLETE_DATA）、AC-6（SUBMIT_PLATFORM）、
AC-7（CONFIRM_ACTIVATION）、AC-8（RETRY/CANCEL/恢复）。全部在隔离测试库运行，
demo 店铺走本地发布路径，不调用任何真实平台，也不触碰业务主库。

夹具用独立平台 ``launchprobe`` 与自建 CONTRACT_TEST 流程，避免与其它测试的
规则包/Profile 交叉；该流程为本地契约样本，不代表任何真实平台接入。
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.db import SessionLocal
from app.models import (
    AiAction,
    Listing,
    ListingReviewDecision,
    PlatformPublishAttempt,
    PlatformRulePack,
    Product,
    ProductAsset,
    Shop,
    User,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
    WorkflowTemplate,
)
from app.services import action_system
from app.services.action_records import listing_fingerprint
from app.services.workspace_context import resolve_workspace_context
from app.workflows.contract_profiles import simple_contract
from app.workflows.launch_access import LaunchError
from app.workflows.launch_actions import execute_launch_action
from app.workflows.launch_records import create_launch
from app.workflows.launch_runtime import refresh_launch
from app.workflows.profiles import create_profile, publish_profile

PLATFORM = "launchprobe"
RULE_VERSION = "launch-action-1"
VERIFIER = "launch-verifier"


def _action_profile(version=1):
    """本地契约流程：资料 -> 提交 -> 在售核验 -> 监控；用于动作框架可执行性验证。"""
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
    return {"profile_key": "ACTION_PROBE", "version": version, "name": "动作框架本地契约样本",
            "description": "本地流程验证，不代表真实平台接入。",
            "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
            "platform": PLATFORM, "market": "SG", "fulfillment_mode": "DROPSHIP",
            "category_scope": ["ANY"],
            "status_mapping": {"unknown": "BLOCK", "statuses": {}}, "steps": steps}


@pytest.fixture
def env(client):
    with SessionLocal() as db:
        users = {name: db.query(User).filter_by(username=name).one() for name in ("admin", "ops", "viewer")}
        contexts = {name: resolve_workspace_context(db, user) for name, user in users.items()}
        tenant = contexts["admin"].legacy_tenant_id
        product = Product(tenant_id=tenant, sku="launch-action", title="Launch product",
                          category="家居", images=["https://example.com/main.jpg"],
                          attrs={"destination_country": "SG"})
        shops = [Shop(tenant_id=tenant, platform=PLATFORM, shop_name=name, market="SG",
                      fulfillment_mode="DROPSHIP", is_demo=True) for name in ("Action A", "Action B")]
        db.add_all([product, *shops])
        db.flush()
        # 注册唯一当前权利记录，使素材权利 PUBLISHABLE（COMPLETE_DATA 前提，AC-5.1）。
        db.add(ProductAsset(tenant_id=tenant, workspace_id=tenant, product_id=product.id,
                            asset_key="main", version=1, asset_type="MAIN_IMAGE", uri=product.images[0],
                            content_hash="a" * 64, rights_status="OWNED", source="launch action fixture",
                            rights_evidence_ref="evidence://fixture/source", market="SG",
                            platform=PLATFORM, verification_status="MANUAL_REPORTED", created_by=users["admin"].id))
        db.commit()
        yield db, contexts, product, shops
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
        db.query(PlatformPublishAttempt).filter(PlatformPublishAttempt.listing_id.in_(listing_ids)).delete(
            synchronize_session=False)
        db.query(AiAction).filter(AiAction.target_id.in_(listing_ids)).delete(synchronize_session=False)
    db.query(ListingReviewDecision).filter(ListingReviewDecision.product_id == product.id).delete(
        synchronize_session=False)
    db.query(Listing).filter(Listing.product_id == product.id).delete(synchronize_session=False)
    db.query(ProductAsset).filter(ProductAsset.product_id == product.id).delete(synchronize_session=False)
    db.query(PlatformRulePack).filter(PlatformRulePack.platform == PLATFORM).delete(synchronize_session=False)
    db.query(User).filter(User.username == VERIFIER).delete(synchronize_session=False)
    db.query(WorkflowTemplate).filter(WorkflowTemplate.tenant_id == tenant,
                                      WorkflowTemplate.profile_key.in_(("ACTION_PROBE", "SIMPLE_CONTRACT"))).delete(
        synchronize_session=False)
    db.delete(product)
    for shop in shops:
        db.delete(shop)
    db.commit()


def _publish_profile(db, ctx, payload):
    profile = create_profile(db, ctx, payload)
    publish_profile(db, ctx, profile.id, profile.definition_hash)
    db.commit()
    return profile


def _probe_env(db, contexts):
    """自建 launchprobe 契约流程（覆盖动作框架的正向路径）。"""
    _publish_profile(db, contexts["admin"], _action_profile())


def _start(db, ctx, product, shop, key="start"):
    run = create_launch(db, ctx, product.id, shop.id, key)
    db.commit()
    return run


def _run(db, run_id):
    return db.get(WorkflowRun, run_id, populate_existing=True)


def _refresh(db, ctx, run_id, revision=None):
    run = _run(db, run_id)
    run, plan = refresh_launch(db, ctx, run_id, revision if revision is not None else run.revision)
    db.commit()
    return run, plan


def _step(db, run_id, code):
    return db.query(WorkflowStep).filter_by(run_id=run_id, step_code=code).one()


def _exec(db, ctx, run_id, action, step_code, key, revision=None, payload=None):
    body = {"step_code": step_code, "payload": payload or {},
            "expected_revision": revision if revision is not None else _run(db, run_id).revision}
    out = execute_launch_action(db, ctx, run_id, action, body, key)
    db.commit()
    return out


def _advance_to_submission(db, ctx, run_id):
    """资料步骤完成 -> SUBMISSION READY（供提交/核验用例复用）。"""
    _refresh(db, ctx, run_id)
    _exec(db, ctx, run_id, "COMPLETE_DATA", "INFORMATION", "complete-%s" % run_id)
    return _refresh(db, ctx, run_id)[0]


def _approve_publish(db, product, run, rules=None):
    """构造可发布世界：规则包 + 已通过复核（复用既有指纹口径）。"""
    db.add(PlatformRulePack(platform=PLATFORM, version=RULE_VERSION,
                            rules=rules or {"banned_words": [], "image_min": 1},
                            source_url="https://example.com/rules"))
    listing = db.get(Listing, run.listing_id)
    db.add(ListingReviewDecision(
        tenant_id=product.tenant_id, listing_id=listing.id, product_id=product.id, platform=PLATFORM,
        decision="approved", human_override=True, reviewer="human:probe", reasons=["已人工核对"],
        rule_version=RULE_VERSION, evidence={"content_fingerprint": listing_fingerprint(listing, product)}))
    db.commit()


def _land_submission(db, ctx, product, run, key):
    """提交 -> 审批 -> 执行 -> 刷新，使 SUBMISSION 完成、ACTIVE 就绪；返回 Action id。"""
    _approve_publish(db, product, run)
    action_id = _exec(db, ctx, run.id, "SUBMIT_PLATFORM", "SUBMISSION", key)["receipt"]["action_id"]
    action_system.decide_action(db, ctx, action_id, True, "同意")
    action_system.execute_action(db, ctx, action_id)
    db.commit()
    db.expire_all()
    _refresh(db, ctx, run.id)
    return action_id


def _live_actions(db, run_id):
    return db.query(AiAction).filter(
        AiAction.evidence["launch_id"].as_integer() == run_id).order_by(AiAction.id).all()


# ------------------------------------------------------------------ FR-4 框架

def test_idempotency_key_required(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    with pytest.raises(LaunchError) as rejected:
        execute_launch_action(db, contexts["admin"], run.id, "COMPLETE_DATA",
                              {"step_code": "INFORMATION", "expected_revision": 1, "payload": {}}, "  ")
    assert rejected.value.code == "IDEMPOTENCY_REQUIRED" and rejected.value.status_code == 400


def test_unknown_and_unconnected_actions_rejected(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    with pytest.raises(LaunchError) as unknown:
        execute_launch_action(db, contexts["admin"], run.id, "NOT_AN_ACTION",
                              {"step_code": "INFORMATION", "expected_revision": 1, "payload": {}}, "k1")
    assert unknown.value.code == "ACTION_NOT_ALLOWED"
    # 未接通领域动作（B03-B09）即使带合法步骤也一律 409 并给出禁用原因。
    with pytest.raises(LaunchError) as disabled:
        execute_launch_action(db, contexts["admin"], run.id, "REPORT_PRICE",
                              {"step_code": "INFORMATION", "expected_revision": 1, "payload": {}}, "k2")
    assert disabled.value.code == "ACTION_NOT_ALLOWED" and "未接入" in str(disabled.value)
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == 1


def test_action_must_be_in_step_catalog(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _refresh(db, contexts["admin"], run.id)
    with pytest.raises(LaunchError) as rejected:
        _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "INFORMATION", "k3")
    assert rejected.value.code == "ACTION_NOT_ALLOWED"


def test_step_state_conflict_before_ready(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    with pytest.raises(LaunchError) as rejected:
        _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "k4")
    assert rejected.value.code == "STEP_STATE_CONFLICT"
    assert _step(db, run.id, "INFORMATION").step_status == "PENDING"
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == 1


def test_revision_conflict_returns_current_revision(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _refresh(db, contexts["admin"], run.id)
    current = _run(db, run.id).revision
    with pytest.raises(LaunchError) as rejected:
        _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "k5", revision=current + 5)
    assert rejected.value.code == "REVISION_CONFLICT"
    assert rejected.value.current_revision == current and _run(db, run.id).revision == current


def test_idempotent_replay_and_payload_conflict(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _refresh(db, contexts["admin"], run.id)
    first = _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "dup")
    assert first["status"] == "EXECUTED"
    events_after_first = db.query(WorkflowEvent).filter_by(run_id=run.id).count()
    revision_after_first = _run(db, run.id).revision
    replay = _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "dup")
    assert replay["event_id"] == first["event_id"] and replay["status"] == first["status"]
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == events_after_first
    assert _run(db, run.id).revision == revision_after_first
    with pytest.raises(LaunchError) as conflict:
        _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "dup", payload={"note": "changed"})
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"


def test_read_only_member_is_denied(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _refresh(db, contexts["admin"], run.id)
    with pytest.raises(LaunchError) as denied:
        _exec(db, contexts["viewer"], run.id, "COMPLETE_DATA", "INFORMATION", "k6")
    assert denied.value.code == "PERMISSION_DENIED" and denied.value.status_code == 403
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == 2  # 仅创建 + 刷新
    assert _step(db, run.id, "INFORMATION").step_status == "READY"


def test_payload_rejects_forbidden_and_unknown_keys(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _refresh(db, contexts["admin"], run.id)
    for payload in ({"completed": True}, {"platform_status": "ACTIVE"}, {"bogus": 1}):
        with pytest.raises(LaunchError) as rejected:
            _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "k7", payload=payload)
        assert rejected.value.code == "ACTION_PAYLOAD_INVALID" and rejected.value.status_code == 422
    assert _step(db, run.id, "INFORMATION").step_status == "READY"


# ------------------------------------------------------------- FR-5 COMPLETE_DATA

def test_complete_data_success_evidence_and_event(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _refresh(db, contexts["admin"], run.id)
    before = _run(db, run.id).revision
    out = _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "cd-ok")
    step = _step(db, run.id, "INFORMATION")
    assert step.step_status == "COMPLETED"
    assert out["revision"] == before + 1 and out["step"]["step_status"] == "COMPLETED"
    assert set(step.result) >= {"input_revision", "facts_digest", "completed_by", "completed_at"}
    assert step.result["completed_by"] == contexts["admin"].user_id
    assert step.evidence_refs and step.evidence_refs[0].startswith("facts:")
    event = db.get(WorkflowEvent, out["event_id"])
    assert event.event_type == "LaunchActionExecuted" and event.after["steps"]["INFORMATION"]["status"] == "COMPLETED"
    assert event.payload["action"] == "COMPLETE_DATA" and event.payload["status"] == "EXECUTED"
    for key in ("payload_hash", "evidence_fingerprint", "revision", "actor_id"):
        assert key in event.payload
    # 资料完成后 SUBMISSION 就绪（依赖已满足）。
    assert _step(db, run.id, "SUBMISSION").step_status == "READY"


def test_complete_data_precondition_failed_with_asset_reasons(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    asset = db.query(ProductAsset).filter_by(product_id=product.id).one()
    asset.verification_status = "REJECTED"
    db.commit()
    _refresh(db, contexts["admin"], run.id)
    with pytest.raises(LaunchError) as rejected:
        _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "cd-block")
    assert rejected.value.code == "ACTION_PRECONDITION_FAILED" and rejected.value.status_code == 409
    assert rejected.value.blockers and "驳回" in rejected.value.blockers[0]["message"]
    assert _step(db, run.id, "INFORMATION").step_status == "READY"


# ----------------------------------------------------------- FR-6 SUBMIT_PLATFORM

def test_submit_precheck_failure_creates_no_intent(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _advance_to_submission(db, contexts["admin"], run.id)
    # 缺规则包与已通过复核：预检必然失败，且不得产生任何 Action 或 Attempt。
    with pytest.raises(LaunchError) as rejected:
        _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "SUBMISSION", "sub-fail")
    assert rejected.value.code == "ACTION_PRECONDITION_FAILED" and rejected.value.blockers
    assert _live_actions(db, run.id) == []
    assert db.query(PlatformPublishAttempt).filter_by(listing_id=run.listing_id).count() == 0
    assert _step(db, run.id, "SUBMISSION").step_status == "READY"


def test_submit_creates_pending_action_and_reuses_intent(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _advance_to_submission(db, contexts["admin"], run.id)
    _approve_publish(db, product, run)
    out = _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "SUBMISSION", "sub-1")
    assert out["status"] == "PENDING_APPROVAL"
    assert _step(db, run.id, "SUBMISSION").step_status == "WAITING_APPROVAL"
    actions = _live_actions(db, run.id)
    assert len(actions) == 1 and actions[0].status == "PENDING_APPROVAL"
    assert actions[0].action_type == "PUBLISH_LISTING"
    assert actions[0].evidence["launch_id"] == run.id and actions[0].evidence["step_code"] == "SUBMISSION"
    assert out["receipt"]["action_id"] == actions[0].id
    # 相同幂等键重复提交是纯重放：返回同一 Action，不新建事件、不产生第二个意图。
    again = _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "SUBMISSION", "sub-1")
    assert again["receipt"]["action_id"] == actions[0].id
    assert len(_live_actions(db, run.id)) == 1
    # 步骤已进入待审批：新幂等键的重复提交被状态机守卫拒绝，同样不产生第二个意图（AC-6.2）。
    with pytest.raises(LaunchError) as conflict:
        _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "SUBMISSION", "sub-2")
    assert conflict.value.code == "STEP_STATE_CONFLICT"
    assert len(_live_actions(db, run.id)) == 1


def test_submit_approval_lands_completed_without_active(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _advance_to_submission(db, contexts["admin"], run.id)
    _approve_publish(db, product, run)
    out = _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "SUBMISSION", "sub-3")
    action_id = out["receipt"]["action_id"]
    action_system.decide_action(db, contexts["admin"], action_id, True, "同意发布")
    action_system.execute_action(db, contexts["admin"], action_id)
    db.commit()
    db.expire_all()
    _refresh(db, contexts["admin"], run.id)
    step = _step(db, run.id, "SUBMISSION")
    assert step.step_status == "COMPLETED"
    assert step.result["receipt"]["platform_status"] == "SUBMITTED"
    assert step.result["receipt"]["attempt_id"] is not None
    # 提交回执绝不等于在售（AC-6.4）。
    current = _run(db, run.id)
    assert current.platform_status != "ACTIVE" and current.verification_status != "VERIFIED"
    # 提交完成只说明外部意图已发出；平台还没给 ACCEPTED/ACTIVE 事实，
    # 在售核验步骤应停在 WAITING_EXTERNAL（状态模型 §3），不是直接丢给用户一个核验按钮。
    assert _step(db, run.id, "ACTIVE").step_status == "WAITING_EXTERNAL"


# -------------------------------------------------------- FR-7 CONFIRM_ACTIVATION

def test_confirm_requires_material_and_note(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _advance_to_submission(db, contexts["admin"], run.id)
    _land_submission(db, contexts["admin"], product, run, "sub-4")
    # 等待态也允许核验（平台可能已在售而 ACCEPTED 事实未到），
    # 但材料/备注缺失仍必须 409 —— 状态放行不等于校验放行。
    assert _step(db, run.id, "ACTIVE").step_status == "WAITING_EXTERNAL"
    with pytest.raises(LaunchError) as rejected:
        _exec(db, contexts["admin"], run.id, "CONFIRM_ACTIVATION", "ACTIVE", "act-1", payload={"material_ref": ""})
    assert rejected.value.code == "ACTION_PRECONDITION_FAILED"
    with pytest.raises(LaunchError) as no_note:
        _exec(db, contexts["admin"], run.id, "CONFIRM_ACTIVATION", "ACTIVE", "act-1b",
              payload={"material_ref": "https://example.com/r", "note": "  "})
    assert no_note.value.code == "ACTION_PRECONDITION_FAILED"


def test_confirm_permission_and_independence(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _advance_to_submission(db, contexts["admin"], run.id)
    _approve_publish(db, product, run)
    action = _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "SUBMISSION", "sub-5")["receipt"]["action_id"]
    action_system.decide_action(db, contexts["admin"], action, True, "同意")
    action_system.execute_action(db, contexts["admin"], action)
    db.commit()
    db.expire_all()
    _refresh(db, contexts["admin"], run.id)
    payload = {"material_ref": "https://example.com/readback", "note": "平台后台截图 2026-10-13"}
    # 运营缺少 compliance:approve（AC-7.1 双权限）。
    with pytest.raises(LaunchError) as denied:
        _exec(db, contexts["ops"], run.id, "CONFIRM_ACTIVATION", "ACTIVE", "act-2", payload=payload)
    assert denied.value.code == "PERMISSION_DENIED" and denied.value.status_code == 403
    # Owner 具备双权限，但正是提交人，禁止自审（AC-7.1）。
    with pytest.raises(LaunchError) as self_verify:
        _exec(db, contexts["admin"], run.id, "CONFIRM_ACTIVATION", "ACTIVE", "act-3", payload=payload)
    assert self_verify.value.code == "ACTION_PRECONDITION_FAILED"
    assert _run(db, run.id).verification_status == "UNKNOWN"


def test_confirm_by_independent_owner_marks_verified_and_keeps_history(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _advance_to_submission(db, contexts["admin"], run.id)
    _approve_publish(db, product, run)
    action = _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "SUBMISSION", "sub-6")["receipt"]["action_id"]
    action_system.decide_action(db, contexts["admin"], action, True, "同意")
    action_system.execute_action(db, contexts["admin"], action)
    db.commit()
    db.expire_all()
    _refresh(db, contexts["admin"], run.id)
    verifier = User(tenant_id=contexts["admin"].legacy_tenant_id, username=VERIFIER,
                    password_hash="test", role="admin", display_name="独立核验人")
    db.add(verifier)
    db.commit()
    verifier_ctx = resolve_workspace_context(db, verifier)
    first = _exec(db, verifier_ctx, run.id, "CONFIRM_ACTIVATION", "ACTIVE", "act-4",
                  payload={"material_ref": "https://example.com/readback", "note": "首次核验"})
    current = _run(db, run.id)
    assert current.platform_status == "ACTIVE" and current.verification_status == "VERIFIED"
    step = _step(db, run.id, "ACTIVE")
    assert step.step_status == "COMPLETED"
    assert step.result["activation_verification"]["current"]["source"] == "MANUAL"
    assert first["status"] == "EXECUTED"
    # 误判更正：再次核验追加历史、不擦除旧记录（AC-7.5）。
    db.expire_all()
    _exec(db, verifier_ctx, run.id, "CONFIRM_ACTIVATION", "ACTIVE", "act-5",
          payload={"material_ref": "https://example.com/readback2", "note": "更正核验"})
    record = _step(db, run.id, "ACTIVE").result["activation_verification"]
    assert record["current"]["note"] == "更正核验" and len(record["history"]) == 1


def test_cancel_after_verified_is_rejected(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _advance_to_submission(db, contexts["admin"], run.id)
    _approve_publish(db, product, run)
    action = _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "SUBMISSION", "sub-7")["receipt"]["action_id"]
    action_system.decide_action(db, contexts["admin"], action, True, "同意")
    action_system.execute_action(db, contexts["admin"], action)
    db.commit()
    db.expire_all()
    _refresh(db, contexts["admin"], run.id)
    verifier = User(tenant_id=contexts["admin"].legacy_tenant_id, username=VERIFIER,
                    password_hash="test", role="admin")
    db.add(verifier)
    db.commit()
    _exec(db, resolve_workspace_context(db, verifier), run.id, "CONFIRM_ACTIVATION", "ACTIVE", "act-6",
          payload={"material_ref": "https://example.com/r", "note": "核验"})
    with pytest.raises(LaunchError) as rejected:
        _exec(db, contexts["admin"], run.id, "CANCEL", "", "cancel-1", payload={"note": "尝试下架", "confirm": True})
    assert rejected.value.code == "ACTION_PRECONDITION_FAILED"
    assert _run(db, run.id).ended_at is None


# ------------------------------------------------- FR-8 RETRY / CANCEL / 恢复

def test_retry_requires_failed_and_blocks_uncertain(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _advance_to_submission(db, contexts["admin"], run.id)
    _approve_publish(db, product, run)
    out = _exec(db, contexts["admin"], run.id, "SUBMIT_PLATFORM", "SUBMISSION", "sub-8")
    action = db.get(AiAction, out["receipt"]["action_id"])
    action.status = "FAILED"
    action.outcome = {"error": "平台 5xx"}
    db.commit()
    db.expire_all()
    _refresh(db, contexts["admin"], run.id)
    assert _step(db, run.id, "SUBMISSION").step_status == "FAILED"
    attempts = _step(db, run.id, "SUBMISSION").attempts
    retried = _exec(db, contexts["admin"], run.id, "RETRY", "SUBMISSION", "retry-1")
    assert retried["status"] == "EXECUTED" and _step(db, run.id, "SUBMISSION").step_status == "READY"
    assert _step(db, run.id, "SUBMISSION").attempts == attempts + 1
    assert db.get(WorkflowEvent, retried["event_id"]).event_type == "LaunchActionRetried"
    # 外部结果待核查时禁止重发（AC-8.2）。
    _step(db, run.id, "SUBMISSION").step_status = "FAILED"
    db.add(PlatformPublishAttempt(tenant_id=product.tenant_id, listing_id=run.listing_id, shop_id=run.shop_id,
                                  platform=PLATFORM, idempotency_key="uncertain-1", status="uncertain"))
    db.commit()
    with pytest.raises(LaunchError) as blocked:
        _exec(db, contexts["admin"], run.id, "RETRY", "SUBMISSION", "retry-2")
    assert blocked.value.code == "ACTION_PRECONDITION_FAILED" and "待核查" in str(blocked.value)


def test_cancel_releases_slot_and_blocks_further_actions(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _refresh(db, contexts["admin"], run.id)
    out = _exec(db, contexts["admin"], run.id, "CANCEL", "", "cancel-ok",
                payload={"note": "不再上线", "confirm": True})
    current = _run(db, run.id)
    assert current.execution_status == "CANCELLED" and current.ended_at is not None
    assert current.active_slot is None
    assert db.get(WorkflowEvent, out["event_id"]).event_type == "LaunchCancelled"
    # 终态流程拒绝新动作（AC-8.4）。
    with pytest.raises(LaunchError) as ended:
        _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "cancel-after")
    assert ended.value.code == "LAUNCH_ENDED"
    # 槽位释放后可创建新轮次（relaunch）。
    relaunch = create_launch(db, contexts["admin"], product.id, shops[0].id, "relaunch",
                             previous_run_id=run.id)
    db.commit()
    assert relaunch.id != run.id and relaunch.previous_run_id == run.id


def test_concurrent_actions_single_winner(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _refresh(db, contexts["admin"], run.id)
    revision = _run(db, run.id).revision
    barrier = Barrier(2)

    def worker(index):
        with SessionLocal() as session:
            barrier.wait(timeout=10)
            try:
                out = execute_launch_action(session, contexts["admin"], run.id, "COMPLETE_DATA",
                                            {"step_code": "INFORMATION", "expected_revision": revision,
                                             "payload": {}}, "race-%s" % index)
                session.commit()
                return out["status"]
            except LaunchError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (0, 1)))
    assert sorted(map(str, results)) == ["EXECUTED", "REVISION_CONFLICT"]
    assert _run(db, run.id).revision == revision + 1
    assert db.query(WorkflowEvent).filter(WorkflowEvent.run_id == run.id,
                                          WorkflowEvent.event_type == "LaunchActionExecuted").count() == 1


def test_recovery_resets_running_without_intent(env):
    db, contexts, product, shops = env
    _probe_env(db, contexts)
    run = _start(db, contexts["admin"], product, shops[0])
    _refresh(db, contexts["admin"], run.id)
    _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "rec-cd")
    assert _step(db, run.id, "SUBMISSION").step_status == "READY"
    # RUNNING 但无关联意图（进程在产生副作用前中断）：恢复扫描回退 READY（AC-8.5）。
    _step(db, run.id, "SUBMISSION").step_status = "RUNNING"
    db.commit()
    _refresh(db, contexts["admin"], run.id)
    assert _step(db, run.id, "SUBMISSION").step_status == "READY"
    # 有在途 Action 的 RUNNING 只重读，不被回退。
    _step(db, run.id, "SUBMISSION").step_status = "RUNNING"
    db.add(AiAction(tenant_id=product.tenant_id, workspace_id=contexts["admin"].workspace_id,
                    task_id=None, agent_type="listing", action_type="PUBLISH_LISTING",
                    target_type="listing", target_id=run.listing_id, reason="fixture",
                    evidence={"launch_id": run.id, "step_code": "SUBMISSION", "payload": {"shop_id": run.shop_id}},
                    expected_impact={}, risk_level="MEDIUM", required_permission="listing:write",
                    execution_mode="APPROVAL_REQUIRED", approval_required=True, status="EXECUTING",
                    requested_by=contexts["admin"].user_id, outcome={}, idempotency_key="live-intent"))
    db.commit()
    _refresh(db, contexts["admin"], run.id)
    assert _step(db, run.id, "SUBMISSION").step_status == "RUNNING"


def test_simple_contract_data_step_can_complete(env):
    """既有 SIMPLE_CONTRACT 样本的资料步骤同样可被确定性完成（不回归既有 Profile）。"""
    db, contexts, product, shops = env
    _publish_profile(db, contexts["admin"], simple_contract())
    shop = Shop(tenant_id=product.tenant_id, platform="shopee", shop_name="Simple sales", market="SG",
                fulfillment_mode="DROPSHIP", is_demo=True)
    db.add(shop)
    db.add(ProductAsset(tenant_id=product.tenant_id, workspace_id=product.tenant_id, product_id=product.id,
                        asset_key="simple", version=1, asset_type="MAIN_IMAGE", uri=product.images[0],
                        content_hash="b" * 64, rights_status="OWNED", source="simple fixture",
                        rights_evidence_ref="evidence://fixture/simple", market="SG", platform="shopee",
                        verification_status="MANUAL_REPORTED", created_by=contexts["admin"].user_id))
    db.commit()
    try:
        run = _start(db, contexts["admin"], product, shop, "simple-run")
        _refresh(db, contexts["admin"], run.id)
        out = _exec(db, contexts["admin"], run.id, "COMPLETE_DATA", "INFORMATION", "simple-cd")
        assert out["status"] == "EXECUTED"
    finally:
        db.rollback()
        run_ids = [row[0] for row in db.query(WorkflowRun.id).filter_by(product_id=product.id).all()]
        db.query(WorkflowRun).filter(WorkflowRun.product_id == product.id).update(
            {"previous_run_id": None}, synchronize_session=False)
        if run_ids:
            db.query(WorkflowEvent).filter(WorkflowEvent.run_id.in_(run_ids)).delete(synchronize_session=False)
            db.query(WorkflowStep).filter(WorkflowStep.run_id.in_(run_ids)).delete(synchronize_session=False)
            db.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).delete(synchronize_session=False)
        listing_ids = [row[0] for row in db.query(Listing.id).filter_by(product_id=product.id).all()]
        if listing_ids:
            db.query(AiAction).filter(AiAction.target_id.in_(listing_ids)).delete(synchronize_session=False)
            db.query(Listing).filter(Listing.product_id == product.id).delete(synchronize_session=False)
        db.query(ProductAsset).filter(ProductAsset.asset_key == "simple").delete(synchronize_session=False)
        db.delete(shop)
        db.commit()
