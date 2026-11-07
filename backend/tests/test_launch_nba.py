"""确定性 NBA 契约（B02）：纯函数、同输入双算一致、排序、禁用原因、角色投影。

覆盖 PRD AC-9.1~9.8。全程不访问数据库、不读时钟——compute_nba 的输入仅服务端事实。
"""

from datetime import datetime
from types import SimpleNamespace

from app.workflows.launch_action_catalog import PRICE_STOCK_ACTIONS, action_meta
from app.workflows.launch_nba import (
    action_block_reason,
    cancellable,
    compute_nba,
    next_action_summary,
    recommendations,
)
from app.workflows.profile_schema import ProfileDefinition

OWNER_PERMS = frozenset({"launch:manage", "listing:write", "launch:submit", "launch:price_review",
                         "launch:stock_prepare", "launch:compliance_manage", "compliance:approve"})
COMPLIANCE_PERMS = frozenset({"compliance:read", "compliance:approve", "compliance:check",
                              "listing:read", "product:read", "launch:read",
                              "launch:compliance_manage"})


def _profile():
    """NBA 样本：资料 -> 人工决策 / 备货（并行）-> 在售核验（唯一必需末节点）。"""
    steps = [
        {"step_code": "INFO", "step_name": "商品资料", "business_type": "DATA_PREPARATION",
         "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 0, "required": True,
         "dependencies": [], "available_actions": ["COMPLETE_DATA"],
         "evidence_requirements": ["INFORMATION_EVIDENCE"],
         "completion_condition": {"present": "product.title"}},
        {"step_code": "DECISION", "step_name": "人工决策", "business_type": "HUMAN_DECISION",
         "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 1, "required": True,
         "dependencies": ["INFO"], "evidence_requirements": ["DECISION_EVIDENCE"],
         "available_actions": ["ACCEPT_PRICE", "COUNTER_PRICE", "ABANDON_PRODUCT", "COMPLETE_DATA"],
         "completion_condition": {"present": "decision.made"}},
        {"step_code": "STOCK", "step_name": "备货准备", "business_type": "STOCK_PREPARATION",
         "execution_mode": "ADAPTER_TASK", "actor": "SYSTEM", "sequence": 2, "required": True,
         "dependencies": ["INFO"], "available_actions": ["REQUEST_STOCK", "CONFIRM_STOCK"],
         "completion_condition": {"present": "stock.ready"}},
        {"step_code": "ACTIVE", "step_name": "在售核验", "business_type": "PLATFORM_ACTIVATION",
         "execution_mode": "EXTERNAL_WAIT", "actor": "PLATFORM", "sequence": 3, "required": True,
         "dependencies": ["DECISION", "STOCK"], "available_actions": ["CONFIRM_ACTIVATION"],
         "completion_condition": {"verified_artifact": "ACTIVATION"}},
    ]
    return {"profile_key": "NBA_PROBE", "version": 1, "name": "NBA 本地契约样本",
            "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
            "platform": "shopee", "market": "SG", "fulfillment_mode": "DROPSHIP",
            "category_scope": ["ANY"], "status_mapping": {"unknown": "BLOCK", "statuses": {}},
            "steps": steps}


def _definitions():
    definition = ProfileDefinition.model_validate(_profile())
    return {step.step_code: step for step in definition.steps}


def _step(code, status, *, actor="USER", assigned=7, seq=0, deadline=None):
    return SimpleNamespace(step_code=code, step_status=status, actor=actor, assigned_user_id=assigned,
                           seq=seq, deadline_at=deadline, attempts=0, result={}, evidence_refs=[],
                           blocking_reason={}, input_revision=0, external_status="",
                           external_reference="", external_type="UNKNOWN")


def _steps():
    return [_step("INFO", "READY", seq=0), _step("DECISION", "READY", seq=1),
            _step("STOCK", "READY", actor="SYSTEM", seq=2), _step("ACTIVE", "PENDING", actor="PLATFORM", seq=3)]


def _plan(statuses=None, *, completion=None, blockers=None, current="INFO"):
    statuses = statuses or {"INFO": "READY", "DECISION": "READY", "STOCK": "READY", "ACTIVE": "PENDING"}
    completion = completion or {"INFO": True}
    steps = {code: {"step_code": code, "status": status, "applicable": True,
                    "completion_satisfied": completion.get(code, False),
                    "blocking_reason": {}, "invalidated": False}
             for code, status in statuses.items()}
    return {"execution_status": "READY", "steps": steps, "blockers": blockers or [],
            "current_steps": [current] if current else [], "current_step": current or "",
            "progress": {"completed": 0, "total": 4},
            "runnable_steps": [code for code, status in statuses.items() if status == "READY"]}


def _run():
    return SimpleNamespace(id=1, revision=3, created_by=7, ended_at=None, execution_status="READY",
                           platform_status="NOT_SUBMITTED", verification_status="UNKNOWN")


def _nba(permissions=OWNER_PERMS, role="OWNER", plan=None, steps=None, run=None):
    return compute_nba(plan or _plan(), steps or _steps(), _definitions(), permissions,
                       role=role, revision=3, facts_digest="digest", run=run or _run())


def test_same_input_produces_identical_output():
    assert _nba() == _nba()


def test_allowed_actions_only_executable_ready_steps():
    nba = _nba()
    pairs = {(entry["action"], entry["step_code"]) for entry in nba["allowed_actions"]}
    assert ("COMPLETE_DATA", "INFO") in pairs and ("ABANDON_PRODUCT", "DECISION") in pairs
    assert all(entry["step_code"] != "ACTIVE" for entry in nba["allowed_actions"])   # 非 READY 不候选
    assert all(entry["expected_revision"] == 3 for entry in nba["allowed_actions"])  # AC-9.1
    assert all(entry["evidence_fingerprint"] == "digest" for entry in nba["allowed_actions"])
    disabled = {entry["action"]: entry["disabled_reason"] for entry in nba["disabled_actions"]}
    assert "未接入" in disabled["REQUEST_STOCK"]   # AC-9.6：未接通动作进禁用清单


def test_next_best_action_and_owner():
    nba = _nba()
    assert nba["ordering"] == "rule"
    best = nba["next_best_action"]
    assert best == {"action": "COMPLETE_DATA", "step_code": "INFO", "executable": True}
    assert nba["owner"] == {"actor": "USER", "user_id": 7, "role_hint": "运营"}
    summary = next_action_summary(nba)
    assert summary["action"] == "COMPLETE_DATA" and summary["executable"] is True
    assert summary["owner"]["role_hint"] == "运营"


def test_ordering_prefers_earlier_deadline():
    steps = [_step("INFO", "READY", seq=0, deadline=None),
             _step("DECISION", "READY", seq=1, deadline=datetime(2020, 1, 1)),
             _step("STOCK", "READY", actor="SYSTEM", seq=2),
             _step("ACTIVE", "PENDING", actor="PLATFORM", seq=3)]
    nba = _nba(steps=steps)
    assert nba["next_best_action"]["step_code"] == "DECISION"   # 到期时间优先


def test_disabled_actions_include_missing_permission():
    nba = _nba(permissions=frozenset({"launch:read"}), role="READ_ONLY")
    assert nba["allowed_actions"] == []
    reasons = {entry["action"]: entry["disabled_reason"] for entry in nba["disabled_actions"]}
    assert "缺少权限" in reasons["COMPLETE_DATA"]
    assert nba["next_best_action"]["executable"] is False


def test_unconnected_action_has_batch_reason():
    # M2-A 起核价三动作已接通，改用仍未接通的备货动作：禁用原因必须指向责任领域。
    reason = action_block_reason("REQUEST_STOCK", action_meta("REQUEST_STOCK"), "READY", {},
                                 OWNER_PERMS, _run())
    assert reason and "未接入" in reason   # AC-9.6：禁用原因指向责任领域


def test_compliance_projection_removes_price_and_stock_actions():
    nba = _nba(permissions=COMPLIANCE_PERMS, role="COMPLIANCE")
    surface = {entry["action"] for entry in nba["allowed_actions"]}
    surface |= {entry["action"] for entry in nba["disabled_actions"]}
    assert surface.isdisjoint(PRICE_STOCK_ACTIONS)   # AC-3.2：完全移除
    assert "ABANDON_PRODUCT" in {entry["action"] for entry in _nba()["allowed_actions"]}   # 对照可见


def test_run_level_cancel_present_and_owner_summary():
    nba = _nba()
    cancels = [entry for entry in nba["allowed_actions"] if entry["action"] == "CANCEL"]
    assert cancels and cancels[0]["step_code"] == ""
    assert cancellable(_run()) is True


def test_non_cancellable_run_marks_cancel_disabled():
    run = _run()
    run.platform_status, run.verification_status = "ACTIVE", "VERIFIED"
    nba = _nba(run=run)
    cancelled = [entry for entry in nba["disabled_actions"] if entry["action"] == "CANCEL"]
    assert cancelled and "不能取消" in cancelled[0]["disabled_reason"]
    assert cancellable(run) is False


def test_recommendations_are_rule_sourced_and_complete():
    plan = _plan(blockers=[{"code": "COMPLIANCE_BLOCK", "message": "缺少合规材料",
                            "step_code": "STOCK", "owner_actor": "SYSTEM"}])
    nba = _nba(plan=plan)
    entries = recommendations(nba, plan)
    assert entries and all(entry["source"] == "rule" for entry in entries)
    assert any(entry["reason"] == "缺少合规材料" for entry in entries)
