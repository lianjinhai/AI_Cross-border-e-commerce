"""P0-4：三道门禁必须阻断并给出补齐入口（禁止只返回裸 409）。

三道门禁：
- **缺材料**：素材权利不通过 → `COMPLETE_DATA` 前置不满足，409 带具体缺项
- **低价**：毛利低于 `min_margin` → `PRICE_UNACCEPTABLE`
- **标签依据不足**：`LABEL_PACKAGE` 未核验 → `COMPLIANCE_BLOCK`

每道门禁一正一反。正例同时断言三要素——**阻断码 + 原因 + 补齐动作**；
反例断言未触发时不产生阻断（防止门禁过宽把正常流程卡死）。

补齐入口只允许指向真实存在的页面；能力未接入时必须 `connected=False` 并给出原因，
不得造一个点不动的按钮冒充可用。
"""

from types import SimpleNamespace

import pytest

from app.workflows.contract_profiles import simple_contract
from app.workflows.launch_handlers import missing_blockers
from app.workflows.launch_repair import repair_action
from app.workflows.launch_rules import BLOCK_CODES, evaluate_readiness


def _states(profile, **overrides):
    return {**{step["step_code"]: "PENDING" for step in profile["steps"]}, **overrides}


def _gate_profile(**overrides):
    """取 COMPLEX 契约 Profile，只改目标步骤的进入条件。

    依赖图不能动——`ProfileDefinition` 会校验「必需步骤必须是核验节点的上游」。
    所以隔离单道门禁靠「把上游步骤真正推成 COMPLETED」而不是摘依赖。
    """
    from app.workflows.contract_profiles import complex_contract

    profile = complex_contract()
    for step in profile["steps"]:
        if step["step_code"] in overrides:
            step.update(overrides[step["step_code"]])
    return profile


def _reached(profile, *codes):
    """把目标步骤的上游标成 COMPLETED，其余保持 PENDING。"""
    return _states(profile, **{code: "COMPLETED" for code in codes})


def _checks(*, assets=True, market_required=True, label_package=False, activation=False):
    return {"asset_rights_allowed": {"PUBLISHABLE": assets},
            "verified_artifact": {"MARKET_REQUIRED": market_required,
                                  "LABEL_PACKAGE": label_package, "ACTIVATION": activation}}


def _facts(**pricing):
    facts = {"product": {"id": 42, "title": "测试商品", "category": "家居"},
             "listing": {"title": "草稿", "attributes_complete": True},
             "platform": {"status": "NOT_SUBMITTED", "submission_reference": "submission-1"},
             "assets": {"reasons": ["缺少可发布图片"]}}
    if pricing:
        facts["pricing"] = pricing
    return facts


def _assert_three_parts(blocker, code):
    """三要素：阻断码非空 + 原因非空 + 补齐动作可执行或显式未接入。"""
    assert blocker["code"] == code
    assert blocker["message"].strip()
    repair = blocker["repair_action"]
    assert repair is not None, "阻断项必须带补齐入口，不能是裸 409"
    assert repair["kind"] in {"ROUTE", "ACTION", "UNAVAILABLE"}
    assert repair["label"].strip()
    assert repair["path"].startswith("/app"), "补齐入口必须指向应用内真实页面"
    assert isinstance(repair["connected"], bool)
    if not repair["connected"]:
        assert repair["reason"].strip(), "不能补齐时必须说明为什么"


# ------------------------------------------------------------------ 门禁一：缺材料

def test_missing_asset_gate_points_at_asset_registration_not_product_copy(monkeypatch):
    """正例：素材权利不通过时前置不满足，409 的每一项都带补齐入口。

    入口必须指向**素材与权利登记**，不能是 `COMPLETE_DATA`/「补充商品资料」——
    缺的是图片授权证据，去改标题分类补不出来（M2-D 修的就是这个错位）。
    """
    from app.config import settings

    monkeypatch.setattr(settings, "asset_upload_dir", "")
    step = SimpleNamespace(step_code="INFORMATION", business_type="DATA_PREPARATION", actor="USER")
    blockers = missing_blockers(_facts(), step)

    assert len(blockers) == 1
    _assert_three_parts(blockers[0], "ASSET_RIGHTS_MISSING")
    assert blockers[0]["message"] == "缺少可发布图片"
    repair = blockers[0]["repair_action"]
    assert repair["kind"] == "ROUTE"
    # 不是资料动作：`COMPLETE_DATA` 会直接 409（完成条件仍不满足），给这个入口等于死路。
    assert repair["action"] is None
    assert repair["path"] == "/app/products/42"
    # 缺上传服务时只能说「能看不能传」，不能造一个点了没反应的按钮。
    assert repair["connected"] is False
    assert "ERP_ASSET_UPLOAD_DIR" in repair["reason"]


def test_asset_gate_entry_becomes_usable_when_upload_is_connected(monkeypatch, tmp_path):
    """反例（同一入口的另一半）：接好上传服务后，入口转为可完成且不再需要免责说明。"""
    from app.config import settings

    monkeypatch.setattr(settings, "asset_upload_dir", str(tmp_path / "asset-store"))
    step = SimpleNamespace(step_code="PRODUCT_INFORMATION", business_type="DATA_PREPARATION", actor="USER")
    blocker = missing_blockers(_facts(), step)[0]

    assert blocker["code"] == "ASSET_RIGHTS_MISSING"
    assert blocker["repair_action"]["connected"] is True
    assert blocker["repair_action"]["reason"] == ""


def test_label_step_gap_still_points_at_compliance_not_assets():
    """材料类步骤不受影响：标签包缺口仍走合规页，不会被素材入口抢走。"""
    step = SimpleNamespace(step_code="LABEL_PREPARATION", business_type="LABEL", actor="SYSTEM")
    blocker = missing_blockers(_facts(), step)[0]

    assert blocker["code"] == "MISSING_DATA"
    assert blocker["repair_action"]["path"] == "/app/compliance"
    assert blocker["repair_action"]["connected"] is False


def test_missing_material_gate_passes_when_materials_are_complete():
    """反例：素材权利通过时不得产生阻断（否则正常流程被卡死）。"""
    profile = simple_contract()
    plan = evaluate_readiness(profile, _states(profile), _facts(), _checks(assets=True))

    assert plan["steps"]["INFORMATION"]["completion_satisfied"] is True
    assert plan["blockers"] == []
    # 素材不通过时同一判定翻转为 False，这道门禁才真的起作用。
    blocked = evaluate_readiness(profile, _states(profile), _facts(), _checks(assets=False))
    assert blocked["steps"]["INFORMATION"]["completion_satisfied"] is False


# ------------------------------------------------------------------ 门禁二：低价

def test_low_margin_gate_blocks_with_numeric_reason_and_pricing_entry():
    """正例：毛利低于最低要求 → PRICE_UNACCEPTABLE，原因带具体百分比。"""
    profile = _gate_profile(PRICE_REVIEW={"entry_condition": {"eq": {"field": "pricing.margin_ok",
                                                                    "value": True}}})
    states = _reached(profile, "PRODUCT_INFORMATION", "PLATFORM_ATTRIBUTES", "PRODUCT_CREATED")
    plan = evaluate_readiness(profile, states,
                              _facts(margin=0.08, min_margin=0.15, margin_ok=False), _checks())

    blocker = plan["steps"]["PRICE_REVIEW"]["blocking_reason"]
    assert plan["steps"]["PRICE_REVIEW"]["status"] == "BLOCKED"
    _assert_three_parts(blocker, "PRICE_UNACCEPTABLE")
    assert "8.0%" in blocker["message"] and "15.0%" in blocker["message"]
    assert blocker["repair_action"]["path"] == "/app/pricing"
    # M2-A 起核价轮次已接通：定价页能算出「多少钱才过门槛」，入口是真可用的，
    # 因此 connected=True 且不再需要「未接入」免责说明。
    assert blocker["repair_action"]["connected"] is True
    assert blocker["repair_action"]["reason"] == ""


def test_low_margin_gate_passes_above_floor():
    """反例：毛利达标时不阻断，步骤正常进入 READY。"""
    profile = _gate_profile(PRICE_REVIEW={"entry_condition": {"eq": {"field": "pricing.margin_ok",
                                                                    "value": True}}})
    states = _reached(profile, "PRODUCT_INFORMATION", "PLATFORM_ATTRIBUTES", "PRODUCT_CREATED")
    plan = evaluate_readiness(profile, states,
                              _facts(margin=0.32, min_margin=0.15, margin_ok=True), _checks())

    assert plan["steps"]["PRICE_REVIEW"]["status"] == "READY"
    assert plan["steps"]["PRICE_REVIEW"]["blocking_reason"] == {}


# ------------------------------------------------------------------ 门禁三：标签依据不足

def test_label_evidence_gate_blocks_and_points_to_compliance():
    """正例：标签包未核验 → COMPLIANCE_BLOCK，入口指向合规页并要求补材料。"""
    profile = _gate_profile(LABEL_PREPARATION={"entry_condition": {"verified_artifact": "LABEL_PACKAGE"}})
    states = _reached(profile, "PRODUCT_INFORMATION", "PLATFORM_ATTRIBUTES", "MARKET_COMPLIANCE")
    plan = evaluate_readiness(profile, states, _facts(), _checks(label_package=False))

    blocker = plan["steps"]["LABEL_PREPARATION"]["blocking_reason"]
    assert plan["steps"]["LABEL_PREPARATION"]["status"] == "BLOCKED"
    _assert_three_parts(blocker, "COMPLIANCE_BLOCK")
    assert "标签包" in blocker["message"]
    assert blocker["repair_action"]["path"] == "/app/compliance"
    assert blocker["repair_action"]["connected"] is False


def test_label_evidence_gate_passes_when_label_verified():
    """反例：标签包已核验时不阻断。"""
    profile = _gate_profile(LABEL_PREPARATION={"entry_condition": {"verified_artifact": "LABEL_PACKAGE"}})
    states = _reached(profile, "PRODUCT_INFORMATION", "PLATFORM_ATTRIBUTES", "MARKET_COMPLIANCE")
    plan = evaluate_readiness(profile, states, _facts(), _checks(label_package=True))

    assert plan["steps"]["LABEL_PREPARATION"]["status"] == "READY"
    assert plan["steps"]["LABEL_PREPARATION"]["blocking_reason"] == {}


# ------------------------------------------------------------------ 补齐入口契约

@pytest.mark.parametrize("code", sorted(set(BLOCK_CODES.values())
                                        | {"STEP_STATE_CONFLICT", "ACTION_PRECONDITION_FAILED",
                                           "PLATFORM_PENDING", "PLATFORM_ERROR",
                                           "EXTERNAL_SERVICE_REQUIRED", "SUPPLY_UNAVAILABLE",
                                           "ASSET_RIGHTS_MISSING"}))
def test_repair_action_never_null(code):
    """补齐入口永不缺席：未知码也要有兜底入口，不能退回 `repair_action: None`。"""
    repair = repair_action(code, business_type="DATA_PREPARATION", product_id=42)
    assert repair["kind"] in {"ROUTE", "ACTION", "UNAVAILABLE"}
    assert repair["path"].startswith("/app")
    assert isinstance(repair["connected"], bool)
    if not repair["connected"]:
        assert repair["reason"].strip()


def test_material_steps_do_not_point_at_the_product_page():
    """材料类步骤的补齐落在合规页：商品详情页并不能上传或核验材料。"""
    repair = repair_action("MISSING_DATA", business_type="LABEL", product_id=42)
    assert repair["path"] == "/app/compliance"
    assert repair["connected"] is False
