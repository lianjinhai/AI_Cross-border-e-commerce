"""M2-E 标签契约：依据充分才生成、依据变了立刻失效、只增不改、越权即拒。

为什么这些用例值得写：
    标签最容易出的错不是排版，而是**在没有依据的情况下把标签填满**——
    「大概是 CE 吧」「这个市场应该不用认证」。一旦印出去就是合规事故。
    因此这里除了正例，重点覆盖四种「必须阻断」：缺证据、证据过期、证据被替换、
    目的国要求未收录（`required=[]` 被 `check_evidence` 报成 `passed=True` 的那个陷阱）。

全部在隔离测试库运行，不触碰业务主库；本批**没有**打印、上传或平台发送能力。
"""

import uuid
from datetime import datetime, timedelta

import pytest

from app.db import SessionLocal
from app.models import (
    DestinationComplianceRule,
    LabelPackage,
    Listing,
    ListingReviewDecision,
    Product,
    ProductAsset,
    ProductComplianceEvidence,
    Shop,
    User,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
    WorkflowTemplate,
)
from app.services import compliance_registry, label_packages
from app.services.workspace_context import resolve_workspace_context
from app.workflows.launch_access import LaunchError
from app.workflows.launch_actions import execute_launch_action
from app.workflows.launch_records import create_launch
from app.workflows.launch_runtime import refresh_launch
from app.workflows.profiles import create_profile, publish_profile

PLATFORM = "labelprobe"
# 流程市场必须是具体国家（"EU" 不是合法店铺市场）；德国归一到 EU 判定单元。
EU_MARKET = "DE"
EU_REQUIREMENTS = ("CE", "EPR")   # 类目「电子」在 EU 下必然命中这两条
# 用例自己补的租户级要求行的唯一标记：`_cleanup` 兜底按它删除，避免留下跨用例污染。
_RULE_MARKER = "目的国标签标识要求（测试用租户覆盖行）"


def _profile(key, market, version=1):
    """本地契约流程：资料 -> 标签准备 -> 在售核验 -> 监控（不含平台往返）。"""
    return {
        "profile_key": key, "version": version, "name": "标签本地契约样本",
        "description": "本地标签验证，不代表真实平台接入。",
        "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
        "platform": PLATFORM, "market": market, "fulfillment_mode": "DROPSHIP",
        "category_scope": ["ANY"], "status_mapping": {"unknown": "BLOCK", "statuses": {}},
        "steps": [
            {"step_code": "INFORMATION", "step_name": "商品资料", "business_type": "DATA_PREPARATION",
             "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 0, "required": True,
             "dependencies": [], "available_actions": ["COMPLETE_DATA"],
             "evidence_requirements": ["INFORMATION_EVIDENCE"],
             "completion_condition": {"all": [{"present": "product.title"},
                                              {"asset_rights_allowed": "PUBLISHABLE"}]}},
            {"step_code": "LABEL_PREPARATION", "step_name": "标签准备", "business_type": "LABEL",
             "execution_mode": "SYSTEM_TASK", "actor": "SYSTEM", "sequence": 1, "required": True,
             "dependencies": ["INFORMATION"],
             "available_actions": ["GENERATE_LABEL", "REGENERATE_LABEL"],
             "evidence_requirements": ["LABEL_PREPARATION_EVIDENCE"],
             "completion_condition": {"verified_artifact": "LABEL_PACKAGE"}},
            {"step_code": "ACTIVATION", "step_name": "在售核验", "business_type": "PLATFORM_ACTIVATION",
             "execution_mode": "EXTERNAL_WAIT", "actor": "PLATFORM", "sequence": 2, "required": True,
             "dependencies": ["LABEL_PREPARATION"], "available_actions": ["CONFIRM_ACTIVATION"],
             "evidence_requirements": ["ACTIVATION_EVIDENCE"],
             "completion_condition": {"all": [{"eq": {"field": "platform.status", "value": "ACTIVE"}},
                                              {"verified_artifact": "ACTIVATION"},
                                              {"asset_rights_allowed": "PUBLISHABLE"}]}},
            {"step_code": "MONITORING", "step_name": "经营监控", "business_type": "MONITORING",
             "execution_mode": "SYSTEM_TASK", "actor": "SYSTEM", "sequence": 3, "required": False,
             "dependencies": ["ACTIVATION"],
             "completion_condition": {"eq": {"field": "monitoring.registered", "value": True}}},
        ],
    }


class _Env:
    """一次用例的隔离基座：商品 + 店铺 + 已发布 Profile。"""

    def __init__(self, db, contexts, product, shop, key):
        self.db, self.contexts, self.product, self.shop, self.key = db, contexts, product, shop, key

    @property
    def admin(self):
        return self.contexts["admin"]


def _env(client, market=EU_MARKET):
    db = SessionLocal()
    users = {name: db.query(User).filter_by(username=name).one() for name in ("admin", "viewer")}
    contexts = {name: resolve_workspace_context(db, user) for name, user in users.items()}
    tenant = contexts["admin"].legacy_tenant_id
    suffix = uuid.uuid4().hex[:8]
    product = Product(tenant_id=tenant, sku="label-" + suffix, title="65W 氮化镓充电器",
                      category="电子", images=["https://example.com/main.jpg"],
                      attrs={"origin_country": "CN"}, hs_code="850440")
    shop = Shop(tenant_id=tenant, platform=PLATFORM, shop_name="Label Shop", market=market,
                fulfillment_mode="DROPSHIP", is_demo=True)
    db.add_all([product, shop])
    db.flush()
    db.add(ProductAsset(tenant_id=tenant, workspace_id=tenant, product_id=product.id,
                        asset_key="main", version=1, asset_type="MAIN_IMAGE",
                        uri=product.images[0], content_hash="c" * 64, rights_status="OWNED",
                        source="label fixture", rights_evidence_ref="evidence://fixture/source",
                        market=market, platform=PLATFORM, verification_status="MANUAL_REPORTED",
                        created_by=users["admin"].id))
    db.commit()
    # profile 唯一索引是 (tenant, profile_key, version)：每个用例独立 key。
    key = "LABEL_PROBE_" + suffix.upper()
    profile = create_profile(db, contexts["admin"], _profile(key, market))
    publish_profile(db, contexts["admin"], profile.id, profile.definition_hash)
    db.commit()
    return _Env(db, contexts, product, shop, key)


def _cleanup(env):
    db, product, shop = env.db, env.product, env.shop
    db.rollback()
    run_ids = [row[0] for row in db.query(WorkflowRun.id).filter_by(product_id=product.id).all()]
    listing_ids = [row[0] for row in db.query(Listing.id).filter_by(product_id=product.id).all()]
    db.query(WorkflowRun).filter(WorkflowRun.product_id == product.id).update(
        {"previous_run_id": None}, synchronize_session=False)
    db.query(LabelPackage).filter(LabelPackage.product_id == product.id).delete(
        synchronize_session=False)
    if run_ids:
        db.query(WorkflowEvent).filter(WorkflowEvent.run_id.in_(run_ids)).delete(
            synchronize_session=False)
        db.query(WorkflowStep).filter(WorkflowStep.run_id.in_(run_ids)).delete(
            synchronize_session=False)
        db.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).delete(synchronize_session=False)
    if listing_ids:
        db.query(ListingReviewDecision).filter(
            ListingReviewDecision.product_id == product.id).delete(synchronize_session=False)
    db.query(Listing).filter(Listing.product_id == product.id).delete(synchronize_session=False)
    db.query(ProductAsset).filter(ProductAsset.product_id == product.id).delete(
        synchronize_session=False)
    db.query(ProductComplianceEvidence).filter(
        ProductComplianceEvidence.product_id == product.id).delete(synchronize_session=False)
    # 租户级夹具（不是本用例的商品数据）：不清会污染任何同市场的上架用例。
    db.query(DestinationComplianceRule).filter(
        DestinationComplianceRule.tenant_id == product.tenant_id,
        DestinationComplianceRule.note == _RULE_MARKER).delete(synchronize_session=False)
    db.query(WorkflowTemplate).filter(WorkflowTemplate.tenant_id == product.tenant_id,
                                      WorkflowTemplate.profile_key == env.key).delete(
        synchronize_session=False)
    db.flush()
    db.delete(product)
    db.delete(shop)
    db.commit()


@pytest.fixture
def eu_env(client):
    env = _env(client, EU_MARKET)
    yield env
    _cleanup(env)


@pytest.fixture
def sg_env(client):
    env = _env(client, "SG")
    yield env
    _cleanup(env)


def _run(db, run_id):
    return db.get(WorkflowRun, run_id, populate_existing=True)


def _refresh(db, ctx, run_id):
    run = _run(db, run_id)
    run, plan = refresh_launch(db, ctx, run_id, run.revision)
    db.commit()
    return run, plan


def _step(db, run_id, code):
    return db.query(WorkflowStep).filter_by(run_id=run_id, step_code=code).one()


def _exec(db, ctx, run_id, action, step_code, key, payload=None):
    body = {"step_code": step_code, "payload": payload or {},
            "expected_revision": _run(db, run_id).revision}
    out = execute_launch_action(db, ctx, run_id, action, body, key)
    db.commit()
    return out


def _evidence(db, env, requirement, evidence_ref, valid_until=None):
    db.add(ProductComplianceEvidence(
        tenant_id=env.product.tenant_id, product_id=env.product.id,
        destination_country="EU", requirement=requirement,
        evidence_ref=evidence_ref, valid_until=valid_until))
    db.commit()


def _reached_label(db, env):
    """把流程推到 LABEL_PREPARATION READY：资料完成是它唯一上游。"""
    run = create_launch(db, env.admin, env.product.id, env.shop.id, "label-start-" + uuid.uuid4().hex[:8])
    db.commit()
    _refresh(db, env.admin, run.id)
    _exec(db, env.admin, run.id, "COMPLETE_DATA", "INFORMATION", "cd-" + uuid.uuid4().hex[:6])
    _refresh(db, env.admin, run.id)
    assert _step(db, run.id, "LABEL_PREPARATION").step_status == "READY"
    return run


# ------------------------------------------------------------------ 必须阻断

def test_missing_evidence_blocks_generation_and_writes_nothing(eu_env):
    """反例（核心）：证据没齐 → 409 逐条点名缺哪条，且**零写入**。"""
    env = eu_env
    db, ctx = env.db, env.admin
    run = _reached_label(db, env)
    revision_before = _run(db, run.id).revision

    with pytest.raises(LaunchError) as blocked:
        _exec(db, ctx, run.id, "GENERATE_LABEL", "LABEL_PREPARATION", "gl-missing",
              {"note": "先试一次"})

    assert blocked.value.code == "ACTION_PRECONDITION_FAILED"
    assert blocked.value.status_code == 409, "依据不足必须是 409，不能是 500，也不能静默成功"
    codes = {item["code"] for item in blocked.value.blockers}
    assert codes == {"LABEL_BASIS_MISSING"}
    messages = " ".join(item["message"] for item in blocked.value.blockers)
    for requirement in EU_REQUIREMENTS:
        assert requirement in messages, "阻断原因必须点名缺的是哪一条依据"
    repair = blocked.value.blockers[0]["repair_action"]
    assert repair["path"] == "/app/products/%s" % env.product.id
    assert repair["connected"] is True
    assert db.query(LabelPackage).filter_by(product_id=env.product.id).count() == 0
    assert _run(db, run.id).revision == revision_before
    assert _step(db, run.id, "LABEL_PREPARATION").step_status == "READY"


def test_uncovered_country_is_blocked_not_silently_passed(sg_env):
    """「没查到要求」≠「没有要求」：SG 未收录任何要求时必须阻断。

    `compliance_registry.check_evidence` 对未收录国家返回 `required=[]` 且 `passed=True`。
    照抄这个 True 就会给所有没做过目的国调研的市场发一张「无需认证」的绿灯标签。
    """
    env = sg_env
    db, ctx = env.db, env.admin
    run = _reached_label(db, env)
    basis = label_packages.resolve_basis(db, env.product.tenant_id, env.product, "SG")
    # 前提核实：合规档案对 SG 确实「一条要求都没有」，且 check_evidence 认为 passed。
    assert basis["requirements"] == [] and basis["covered"] is False
    passed = compliance_registry.check_evidence(db, env.product.tenant_id, env.product, "SG")
    assert passed["passed"] is True and passed["required"] == []

    with pytest.raises(LaunchError) as blocked:
        _exec(db, ctx, run.id, "GENERATE_LABEL", "LABEL_PREPARATION", "gl-sg")

    assert blocked.value.status_code == 409
    assert "未收录" in blocked.value.blockers[0]["message"]
    assert "不是「无需认证」" in blocked.value.blockers[0]["message"]
    assert db.query(LabelPackage).filter_by(product_id=env.product.id).count() == 0


def test_expired_evidence_reblocks_a_completed_step(eu_env):
    """证据过期后已完成的标签步骤重新阻断（不是一次性通过永久生效）。"""
    env = eu_env
    db, ctx = env.db, env.admin
    _evidence(db, env, "CE", "CE-CERT-001", datetime.utcnow() + timedelta(days=30))
    _evidence(db, env, "EPR", "EPR-DE-777", None)
    run = _reached_label(db, env)
    _exec(db, ctx, run.id, "GENERATE_LABEL", "LABEL_PREPARATION", "gl-ok")
    assert _step(db, run.id, "LABEL_PREPARATION").step_status == "COMPLETED"

    row = db.query(ProductComplianceEvidence).filter_by(
        tenant_id=env.product.tenant_id, product_id=env.product.id, requirement="CE").one()
    row.valid_until = datetime.utcnow() - timedelta(days=1)   # 证书到期
    db.commit()
    _refresh(db, ctx, run.id)

    step = _step(db, run.id, "LABEL_PREPARATION")
    assert step.step_status == "BLOCKED"
    assert step.blocking_reason["code"] == "LABEL_BASIS_MISSING"
    assert "已过期" in step.blocking_reason["message"]
    # 旧的标签包还在（历史不擦除），但已不再「当前」。
    assert label_packages.basis_current(db, env.product.tenant_id, env.product,
                                       env.shop.id, "EU") is False


def test_read_model_keeps_the_reblocked_step_blocked(client, auth_headers, eu_env):
    """撤销 COMPLETED 之后，读模型必须跟着阻断，不能读一次就变回 READY。

    规则对 BLOCKED 不是粘滞的（只有 WAITING 是粘滞的），所以「刷新写入 BLOCKED →
    同一次请求里再求值一次」会把阻断洗成 READY：用户看到的是一颗绿灯，
    既拿不到「缺哪条证据」，也没有补齐入口——这与「依不足必须阻断」直接冲突。
    故锁定两次连续读取都必须是 BLOCKED，且原因仍是 LABEL_BASIS_MISSING。
    """
    env = eu_env
    db, ctx = env.db, env.admin
    _evidence(db, env, "CE", "CE-CERT-001", datetime.utcnow() + timedelta(days=30))
    _evidence(db, env, "EPR", "EPR-DE-777", None)
    run = _reached_label(db, env)
    _exec(db, ctx, run.id, "GENERATE_LABEL", "LABEL_PREPARATION", "gl-ok")
    row = db.query(ProductComplianceEvidence).filter_by(
        tenant_id=env.product.tenant_id, product_id=env.product.id, requirement="CE").one()
    row.valid_until = datetime.utcnow() - timedelta(days=1)
    db.commit()

    for attempt in (1, 2):
        response = client.get(f"/api/launch/{run.id}", headers=auth_headers)
        assert response.status_code == 200
        step = next(item for item in response.json()["steps"]
                    if item["step_code"] == "LABEL_PREPARATION")
        assert step["step_status"] == "BLOCKED", f"第 {attempt} 次读取把阻断洗成了 {step['step_status']}"
        assert step["blocking_reason"]["code"] == "LABEL_BASIS_MISSING"
        assert "已过期" in step["blocking_reason"]["message"]

    assert _step(db, run.id, "LABEL_PREPARATION").step_status == "BLOCKED"


def test_replacing_evidence_invalidates_the_package(eu_env):
    """证据引用被换成另一份（哪怕仍有效）也要失配：依据变了就是另一版标签。"""
    env = eu_env
    db, ctx = env.db, env.admin
    _evidence(db, env, "CE", "CE-CERT-001")
    _evidence(db, env, "EPR", "EPR-DE-777")
    run = _reached_label(db, env)
    _exec(db, ctx, run.id, "GENERATE_LABEL", "LABEL_PREPARATION", "gl-swap")
    assert label_packages.basis_current(db, env.product.tenant_id, env.product,
                                       env.shop.id, "EU") is True

    row = db.query(ProductComplianceEvidence).filter_by(
        tenant_id=env.product.tenant_id, product_id=env.product.id, requirement="CE").one()
    row.evidence_ref = "CE-CERT-002"
    db.commit()
    _refresh(db, ctx, run.id)

    assert label_packages.basis_current(db, env.product.tenant_id, env.product,
                                       env.shop.id, "EU") is False
    assert _step(db, run.id, "LABEL_PREPARATION").step_status == "BLOCKED"
    # 阻断态下仍能重新生成（BLOCKED 在来源状态里），否则用户卡死在阻断里。
    _exec(db, ctx, run.id, "REGENERATE_LABEL", "LABEL_PREPARATION", "rl-after-swap")
    assert _step(db, run.id, "LABEL_PREPARATION").step_status == "COMPLETED"


def test_regenerate_without_a_package_is_rejected(eu_env):
    """没有旧版就不许「重新生成」：否则历史版本号与审计链会对不上。"""
    env = eu_env
    db, ctx = env.db, env.admin
    _evidence(db, env, "CE", "CE-CERT-001")
    _evidence(db, env, "EPR", "EPR-DE-777")
    run = _reached_label(db, env)

    with pytest.raises(LaunchError) as rejected:
        _exec(db, ctx, run.id, "REGENERATE_LABEL", "LABEL_PREPARATION", "rl-first")

    assert rejected.value.status_code == 409
    assert rejected.value.blockers[0]["code"] == "LABEL_PACKAGE_ABSENT"
    assert db.query(LabelPackage).filter_by(product_id=env.product.id).count() == 0


# ------------------------------------------------------------------ 正例

def test_generate_after_evidence_registered_marks_label_verified(eu_env):
    """补齐证据后可推进：落一版标签包、步骤 COMPLETED、认证声明只来自已核验证据。"""
    env = eu_env
    db, ctx = env.db, env.admin
    _evidence(db, env, "CE", "CE-CERT-001", datetime.utcnow() + timedelta(days=365))
    _evidence(db, env, "EPR", "EPR-DE-777")
    run = _reached_label(db, env)

    out = _exec(db, ctx, run.id, "GENERATE_LABEL", "LABEL_PREPARATION", "gl-good",
                {"note": "依据已齐"})

    rows = db.query(LabelPackage).filter_by(product_id=env.product.id).all()
    assert len(rows) == 1
    row = rows[0]
    assert (row.version, row.action, row.destination_country) == (1, "GENERATE", "EU")
    assert row.content["sku"] == env.product.sku
    assert row.content["origin_country"] == "CN"
    assert {mark["requirement"] for mark in row.content["marks"]} == set(EU_REQUIREMENTS)
    assert all(mark["evidence_ref"] for mark in row.content["marks"]), \
        "认证声明必须挂到具体证据，不能只有名字"
    # 本系统给不出的印刷字段必须显式列出，不能当成已齐备。
    assert any("进口商" in item for item in row.open_items)
    assert out["receipt"]["version"] == 1
    assert out["receipt"]["label_package_current"] is True
    assert "未打印" in out["receipt"]["note"]
    assert _step(db, run.id, "LABEL_PREPARATION").step_status == "COMPLETED"
    # 完成后重新读库仍成立：事实的唯一来源是 DB，不是本次事务里的断言。
    _refresh(db, ctx, run.id)
    assert _step(db, run.id, "LABEL_PREPARATION").step_status == "COMPLETED"


def test_regenerate_appends_a_version_and_keeps_history(eu_env):
    """重生成 = 追加新版本，旧版本一字不改（只增不改）。"""
    env = eu_env
    db, ctx = env.db, env.admin
    _evidence(db, env, "CE", "CE-CERT-001")
    _evidence(db, env, "EPR", "EPR-DE-777")
    run = _reached_label(db, env)
    _exec(db, ctx, run.id, "GENERATE_LABEL", "LABEL_PREPARATION", "gl-v1")
    first = db.query(LabelPackage).filter_by(product_id=env.product.id).one()
    snapshot = (first.version, first.content_digest, first.basis_fingerprint)

    _exec(db, ctx, run.id, "REGENERATE_LABEL", "LABEL_PREPARATION", "rl-v2")

    rows = db.query(LabelPackage).filter_by(product_id=env.product.id).order_by(
        LabelPackage.version).all()
    assert [row.version for row in rows] == [1, 2]
    assert [row.action for row in rows] == ["GENERATE", "REGENERATE"]
    db.refresh(rows[0])
    assert (rows[0].version, rows[0].content_digest, rows[0].basis_fingerprint) == snapshot


# ------------------------------------------------------------------ 越权

def test_read_only_role_cannot_generate_a_label(eu_env):
    """越权：只读角色生成标签必须 403，且不产生标签包与事件。"""
    env = eu_env
    db = env.db
    _evidence(db, env, "CE", "CE-CERT-001")
    _evidence(db, env, "EPR", "EPR-DE-777")
    run = _reached_label(db, env)
    events_before = db.query(WorkflowEvent).filter_by(run_id=run.id).count()

    with pytest.raises(LaunchError) as denied:
        _exec(db, env.contexts["viewer"], run.id, "GENERATE_LABEL", "LABEL_PREPARATION", "gl-viewer")

    assert denied.value.code == "PERMISSION_DENIED"
    assert denied.value.status_code == 403
    assert db.query(LabelPackage).filter_by(product_id=env.product.id).count() == 0
    assert db.query(WorkflowEvent).filter_by(run_id=run.id).count() == events_before


# ------------------------------------------------------------------ 服务层

def test_basis_reports_each_missing_requirement_once(eu_env):
    """服务层：缺项逐条列出，且带着要求自带的说明（用户才知道要补什么）。"""
    env = eu_env
    basis = label_packages.resolve_basis(env.db, env.product.tenant_id, env.product, "EU")
    assert basis["covered"] is True and basis["complete"] is False
    assert {item["requirement"] for item in basis["missing"]} == set(EU_REQUIREMENTS)
    assert len(basis["reasons"]) == len(EU_REQUIREMENTS)
    assert basis["fingerprint"], "依据必须有指纹，否则无法判断旧包是否仍当前"


def test_tenant_compliance_rule_covers_a_country(eu_env):
    """未收录的国家可以由租户补录要求行后变为「有依据」——这就是「去哪里补」的闭环。

    补出来的要求行是**租户级**数据（不是本用例的商品级夹具），必须自己删干净：
    留着它会让后续任何 SG 市场的上架用例都被按「缺 LABELING 认证」拦下，
    表现为一条与标签毫无关系的「上架合规闸门未通过」——污染比失败更难查。
    """
    env = eu_env
    db = env.db
    assert label_packages.resolve_basis(db, env.product.tenant_id, env.product, "SG")["covered"] is False
    rule = DestinationComplianceRule(tenant_id=env.product.tenant_id, destination_country="SG",
                                     category="", requirement="LABELING", mandatory=True,
                                     note=_RULE_MARKER)
    db.add(rule)
    db.commit()
    try:
        basis = label_packages.resolve_basis(db, env.product.tenant_id, env.product, "SG")
        assert basis["covered"] is True
        assert [item["requirement"] for item in basis["missing"]] == ["LABELING"]
    finally:
        db.query(DestinationComplianceRule).filter_by(id=rule.id).delete(synchronize_session=False)
        db.commit()
