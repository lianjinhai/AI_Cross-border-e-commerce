"""P0-2b：EXTERNAL_WAIT 步骤的等待态有生产者，且只有一个出口。

对应 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md` §3：
- 合法迁移包含 `READY/RUNNING → WAITING_EXTERNAL`（已发出外部意图）
- 以及 `WAITING_EXTERNAL → READY`（可信新外部事实到达，重新求规则）

本轮只对 `PLATFORM_ACTIVATION` 生效：它是唯一同时具备「真实外部事实源
（platform.status）」与「已接通 handler（CONFIRM_ACTIVATION）」的 EXTERNAL_WAIT
类型。其余 EXTERNAL_WAIT（如 PRICE_REVIEW）属 B03-B09 未接通，必须保持
READY + 禁用按钮 + 明确 disabled_reason，不得伪装成「在等外部」。
"""

import pytest

from app.workflows.contract_profiles import complex_contract, simple_contract
from app.workflows.launch_action_catalog import BUSINESS_ACTION_META
from app.workflows.launch_rules import evaluate_readiness


def _states(profile, **overrides):
    return {**{step["step_code"]: "PENDING" for step in profile["steps"]}, **overrides}


def _facts(status="SUBMITTED", *, activation_verified=False):
    facts = {"product": {"title": "Owned product"}, "listing": {"attributes_complete": True},
             "platform": {"submission_reference": "submission-1", "status": status}}
    checks = {"asset_rights_allowed": {"PUBLISHABLE": True},
              "verified_artifact": {"MARKET_REQUIRED": True, "ACTIVATION": activation_verified}}
    return facts, checks


def _submitted(profile):
    """INFORMATION / COMPLIANCE / SUBMISSION 全部完成的最小前置。"""
    return _states(profile, INFORMATION="COMPLETED", COMPLIANCE="COMPLETED",
                   SUBMISSION="COMPLETED")


# ------------------------------------------------------------------ 正例：等待态有生产者

@pytest.mark.parametrize("status", ["SUBMITTED", "UNDER_REVIEW"])
def test_activation_waits_for_external_fact(status):
    """提交完成但平台尚未接受：核验步骤必须等，不能直接给用户核验按钮。"""
    profile = simple_contract()
    facts, checks = _facts(status)
    plan = evaluate_readiness(profile, _submitted(profile), facts, checks)
    assert plan["steps"]["ACTIVATION"]["status"] == "WAITING_EXTERNAL"
    assert plan["execution_status"] == "WAITING_EXTERNAL"
    # 等待中的步骤不得出现在可执行列表（否则工作台会把它当成待办）。
    assert "ACTIVATION" not in plan["runnable_steps"]


def test_missing_platform_fact_still_waits():
    """连 platform.status 都没有时同样等待，不能因为事实缺失就放行。"""
    profile = simple_contract()
    facts, checks = _facts("SUBMITTED")
    facts["platform"].pop("status")
    plan = evaluate_readiness(profile, _submitted(profile), facts, checks)
    assert plan["steps"]["ACTIVATION"]["status"] == "WAITING_EXTERNAL"


# ------------------------------------------------------------------ 正例：唯一出口

@pytest.mark.parametrize("status", ["ACCEPTED", "ACTIVE"])
def test_accepted_fact_releases_to_ready(status):
    """可信新外部事实到达 → 回到 READY（状态模型 §3 的唯一出口）。"""
    profile = simple_contract()
    facts, checks = _facts(status)
    plan = evaluate_readiness(profile, _submitted(profile), facts, checks)
    assert plan["steps"]["ACTIVATION"]["status"] == "READY"
    assert "ACTIVATION" in plan["runnable_steps"]


def test_waiting_external_exits_to_ready_on_new_fact():
    """已持久为 WAITING_EXTERNAL 的步骤，收到接受事实后必须能出来（不能粘死）。"""
    profile = simple_contract()
    facts, checks = _facts("ACCEPTED")
    states = _states(profile, INFORMATION="COMPLETED", COMPLIANCE="COMPLETED",
                     SUBMISSION="COMPLETED", ACTIVATION="WAITING_EXTERNAL")
    plan = evaluate_readiness(profile, states, facts, checks)
    assert plan["steps"]["ACTIVATION"]["status"] == "READY"


def test_waiting_external_stays_when_fact_unchanged():
    """事实没变化时保持等待，不能自己跳回 READY。"""
    profile = simple_contract()
    facts, checks = _facts("UNDER_REVIEW")
    states = _states(profile, INFORMATION="COMPLETED", COMPLIANCE="COMPLETED",
                     SUBMISSION="COMPLETED", ACTIVATION="WAITING_EXTERNAL")
    plan = evaluate_readiness(profile, states, facts, checks)
    assert plan["steps"]["ACTIVATION"]["status"] == "WAITING_EXTERNAL"


# ------------------------------------------------------------------ 反例：不得扩大影响面

def test_manual_task_step_is_unaffected():
    """MANUAL_TASK 步骤仍应 READY——等待语义只属于外部执行模式。"""
    profile = simple_contract()
    facts, checks = _facts("SUBMITTED")
    plan = evaluate_readiness(profile, _states(profile), facts, checks)
    assert plan["steps"]["INFORMATION"]["status"] == "READY"
    assert profile["steps"][0]["execution_mode"] == "MANUAL_TASK"


def test_dependency_unsatisfied_never_waits():
    """依赖未完成时必须 PENDING，不能提前进入等待（否则等于宣称已提交）。"""
    profile = simple_contract()
    facts, checks = _facts("SUBMITTED")
    states = _states(profile, INFORMATION="COMPLETED")     # COMPLIANCE/SUBMISSION 未完成
    plan = evaluate_readiness(profile, states, facts, checks)
    assert plan["steps"]["ACTIVATION"]["status"] == "PENDING"


def test_other_external_wait_types_keep_ready():
    """未接通的 EXTERNAL_WAIT 类型（PRICE_REVIEW）保持 READY + 禁用，不伪装等待。"""
    profile = complex_contract()
    facts, checks = _facts("SUBMITTED")
    states = _states(profile, PRODUCT_INFORMATION="COMPLETED", PLATFORM_ATTRIBUTES="COMPLETED",
                     PRODUCT_CREATED="COMPLETED")
    plan = evaluate_readiness(profile, states, facts, checks)
    assert plan["steps"]["PRICE_REVIEW"]["status"] == "READY"
    assert BUSINESS_ACTION_META["REPORT_PRICE"].connected is False


# ------------------------------------------------------------------ 动作可从等待态核验

def test_confirm_activation_accepts_waiting_external():
    """平台可能已在售而 ACCEPTED 事实未到：人工核验应能从等待态发起。"""
    meta = BUSINESS_ACTION_META["CONFIRM_ACTIVATION"]
    assert "WAITING_EXTERNAL" in meta.source_states
    assert {"READY", "COMPLETED"} <= set(meta.source_states)
