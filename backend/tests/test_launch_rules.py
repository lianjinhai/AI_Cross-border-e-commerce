"""生命周期依赖规则：真实状态迁移前的确定性计算，不冒充平台连接。"""

from copy import deepcopy

import pytest

from app.workflows.contract_profiles import complex_contract, simple_contract
from app.workflows.launch_rules import evaluate_readiness


def _states(profile, **overrides):
    return {**{step["step_code"]: "PENDING" for step in profile["steps"]}, **overrides}


def _facts():
    return {"product": {"title": "Owned product"}, "listing": {"attributes_complete": True},
            "platform": {"submission_reference": "submission-1", "status": "ACTIVE"}}, {
                "asset_rights_allowed": {"PUBLISHABLE": True},
                "verified_artifact": {"MARKET_REQUIRED": True, "ACTIVATION": True}}


def test_parallel_dependencies_do_not_follow_display_sequence():
    profile = complex_contract()
    facts, checks = _facts()
    states = _states(profile, PRODUCT_INFORMATION="COMPLETED")
    plan = evaluate_readiness(profile, states, facts, checks)
    assert plan["runnable_steps"] == ["PLATFORM_ATTRIBUTES", "MARKET_COMPLIANCE"]
    assert plan["steps"]["PRICE_REVIEW"]["status"] == "PENDING"
    assert plan["progress"] == {"completed": 1, "total": 12}
    # sequence 仅显示，不允许改变依赖处理语义。
    for step in profile["steps"]:
        step["sequence"] = 100 - step["sequence"]
    reordered = evaluate_readiness(profile, states, facts, checks)
    assert reordered["steps"] == plan["steps"]


def test_true_facts_never_auto_complete_or_advance_dependencies():
    profile = simple_contract()
    facts, checks = _facts()
    plan = evaluate_readiness(profile, _states(profile), facts, checks)
    assert plan["steps"]["INFORMATION"]["completion_satisfied"] is True
    assert plan["steps"]["INFORMATION"]["status"] == "READY"
    assert plan["steps"]["COMPLIANCE"]["status"] == "PENDING"
    assert plan["progress"] == {"completed": 0, "total": 4}


def test_unknown_applicability_blocks_but_false_skips():
    profile = simple_contract()
    profile["steps"][1]["applicability_condition"] = {"eq": {"field": "market.requires_report", "value": True}}
    facts, checks = _facts()
    states = _states(profile, INFORMATION="COMPLETED")
    unknown = evaluate_readiness(profile, states, facts, checks)
    assert unknown["execution_status"] == "BLOCKED"
    assert unknown["steps"]["COMPLIANCE"]["status"] == "BLOCKED"
    assert unknown["progress"]["total"] == 4
    facts["market"] = {"requires_report": False}
    false = evaluate_readiness(profile, states, facts, checks)
    assert false["steps"]["COMPLIANCE"]["status"] == "SKIPPED"
    assert false["steps"]["SUBMISSION"]["status"] == "READY"
    assert false["progress"]["total"] == 3


def test_upstream_revocation_invalidates_transitive_completions():
    profile = simple_contract()
    facts, checks = _facts()
    checks["asset_rights_allowed"]["PUBLISHABLE"] = False
    states = _states(profile, INFORMATION="COMPLETED", COMPLIANCE="COMPLETED", SUBMISSION="COMPLETED")
    plan = evaluate_readiness(profile, states, facts, checks)
    for code in ("INFORMATION", "COMPLIANCE", "SUBMISSION"):
        assert plan["steps"][code]["status"] == "BLOCKED"
        assert plan["steps"][code]["invalidated"] is True
    assert plan["steps"]["ACTIVATION"]["status"] == "PENDING"
    assert plan["progress"]["completed"] == 0


def test_blocked_branch_keeps_parallel_work_visible():
    profile = complex_contract()
    profile["steps"][1]["entry_condition"] = {"present": "missing.attributes"}
    facts, checks = _facts()
    plan = evaluate_readiness(profile, _states(profile, PRODUCT_INFORMATION="COMPLETED"), facts, checks)
    assert plan["execution_status"] == "BLOCKED"
    assert plan["runnable_steps"] == ["MARKET_COMPLIANCE"]
    assert set(plan["current_steps"]) == {"PLATFORM_ATTRIBUTES", "MARKET_COMPLIANCE"}


def test_active_history_is_preserved_and_monitoring_excluded_from_progress():
    profile = simple_contract()
    facts, checks = _facts()
    checks["verified_artifact"]["MARKET_REQUIRED"] = False
    states = {step["step_code"]: "COMPLETED" for step in profile["steps"]}
    states["MONITORING"] = "PENDING"
    plan = evaluate_readiness(profile, states, facts, checks, activated=True)
    assert plan["execution_status"] == "COMPLETED" and plan["blockers"]
    assert plan["progress"] == {"completed": 4, "total": 4}
    assert plan["runnable_steps"] == ["MONITORING"]
    states["MONITORING"] = "FAILED"
    failed_monitor = evaluate_readiness(profile, states, facts, checks, activated=True)
    assert failed_monitor["execution_status"] == "COMPLETED"
    assert failed_monitor["steps"]["MONITORING"]["status"] == "FAILED"


@pytest.mark.parametrize("waiting", ["RUNNING", "WAITING_USER", "WAITING_EXTERNAL", "WAITING_APPROVAL", "FAILED"])
def test_refresh_preserves_waits_failures_and_does_not_restart_tasks(waiting):
    profile = simple_contract()
    facts, checks = _facts()
    original = deepcopy(checks)
    plan = evaluate_readiness(profile, _states(profile, INFORMATION=waiting), facts, checks)
    assert plan["steps"]["INFORMATION"]["status"] == waiting
    assert not plan["runnable_steps"] and checks == original


@pytest.mark.parametrize("invalid", ["missing", "extra", "unknown"])
def test_corrupt_step_set_fails_closed(invalid):
    profile = simple_contract()
    states = _states(profile)
    if invalid == "missing":
        states.pop("COMPLIANCE")
    elif invalid == "extra":
        states["FAKE"] = "COMPLETED"
    else:
        states["INFORMATION"] = "APPROVED_BY_AI"
    with pytest.raises(ValueError, match="实例步骤"):
        evaluate_readiness(profile, states, {}, {})
