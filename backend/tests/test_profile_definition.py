"""Profile 的结构/条件/DAG 安全性；不执行平台通信。"""

import pytest
from pydantic import ValidationError

from app.workflows.conditions import evaluate_condition, validate_condition
from app.workflows.contract_profiles import complex_contract, simple_contract
from app.workflows.profile_schema import ProfileDefinition


def test_contract_profiles_preserve_parallel_dependencies_and_verification_boundary():
    simple = ProfileDefinition.model_validate(simple_contract())
    complex_ = ProfileDefinition.model_validate(complex_contract())
    assert len(simple.steps) == 5 and len(complex_.steps) == 13
    nodes = {step.step_code: step for step in complex_.steps}
    assert nodes["MARKET_COMPLIANCE"].dependencies == ["PRODUCT_INFORMATION"]
    assert nodes["LABEL_PREPARATION"].dependencies == ["MARKET_COMPLIANCE", "PLATFORM_ATTRIBUTES"]
    assert complex_.environment == "CONTRACT_TEST" and complex_.verification_status == "UNVERIFIED"
    assert complex_.fulfillment_mode == "PLATFORM_STOCK"
    assert simple.fingerprint() == ProfileDefinition.model_validate(simple.model_dump()).fingerprint()
    assert simple.fingerprint() != complex_.fingerprint()


@pytest.mark.parametrize("change", ["cycle", "missing_dependency", "duplicate", "orphan_required", "unknown_action",
                                    "manual_no_evidence", "unsafe_condition", "unknown_status", "no_unknown_guard",
                                    "regional_market", "fake_verification"])
def test_invalid_profiles_rejected(change):
    payload = simple_contract()
    if change == "cycle":
        payload["steps"][0]["dependencies"] = ["ACTIVATION"]
    elif change == "missing_dependency":
        payload["steps"][1]["dependencies"] = ["MISSING"]
    elif change == "duplicate":
        payload["steps"][1]["step_code"] = "INFORMATION"
    elif change == "orphan_required":
        payload["steps"][2]["dependencies"] = ["INFORMATION"]
    elif change == "unknown_action":
        payload["steps"][0]["available_actions"] = ["EXECUTE_PYTHON"]
    elif change == "manual_no_evidence":
        payload["steps"][0]["evidence_requirements"] = []
    elif change == "unsafe_condition":
        payload["steps"][0]["completion_condition"] = {"eval": "__import__('os')"}
    elif change == "unknown_status":
        payload["status_mapping"]["statuses"]["OK"] = "VERIFIED"
    elif change == "no_unknown_guard":
        payload["status_mapping"]["unknown"] = "ACTIVE"
    elif change == "regional_market":
        payload["market"] = "EU"
    else:
        payload["verification_status"] = "VERIFIED"
    with pytest.raises(ValidationError):
        ProfileDefinition.model_validate(payload)


@pytest.mark.parametrize("condition,facts,result", [
    ({"present": "product.title"}, {}, None),
    ({"present": "product.title"}, {"product": {"title": ""}}, False),
    ({"not": {"present": "product.title"}}, {}, None),
    ({"all": [False, {"present": "missing"}]}, {}, False),
    ({"any": [True, {"present": "missing"}]}, {}, True),
    ({"all": [True, {"present": "missing"}]}, {}, None),
    ({"eq": {"field": "quantity", "value": 1}}, {"quantity": True}, False),
    ({"in": {"field": "market", "value": ["US", "TR"]}}, {"market": "TR"}, True),
])
def test_conditions_preserve_unknown(condition, facts, result):
    assert evaluate_condition(condition, facts) is result


def test_predicates_only_accept_server_boolean_and_bound_nesting():
    condition = {"verified_artifact": "CERTIFICATE"}
    assert evaluate_condition(condition, {}, {"verified_artifact": {"CERTIFICATE": "yes"}}) is None
    assert evaluate_condition(condition, {}, {"verified_artifact": {"CERTIFICATE": True}}) is True
    nested = True
    for _ in range(14):
        nested = {"not": nested}
    with pytest.raises(ValueError, match="深度"):
        validate_condition(nested)
