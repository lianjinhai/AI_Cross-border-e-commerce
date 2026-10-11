"""本地验收用 Profile；不注册生产能力，不代表任何平台官方完整流程。"""


def _step(code, name, kind, dependencies=(), actions=(), mode="MANUAL_TASK", actor="USER", required=True):
    return {"step_code": code, "step_name": name, "business_type": kind,
            "sequence": 0, "dependencies": list(dependencies), "required": required,
            "execution_mode": mode, "actor": actor, "available_actions": list(actions),
            "evidence_requirements": [code + "_EVIDENCE"],
            "completion_condition": _completion(code, kind)}


def _completion(code, kind):
    # 条件读取未来 Runtime 构造的业务事实，不接受 UI 的通用“完成”标记。
    if kind == "DATA_PREPARATION":
        fields = {"PLATFORM_ATTRIBUTES": "listing.attributes_complete", "READY_FOR_SALE": "readiness.all_required_verified"}
        return {"all": [{"present": "product.title"}, {"asset_rights_allowed": "PUBLISHABLE"}]} if code not in fields else {
            "eq": {"field": fields[code], "value": True}}
    if kind == "PLATFORM_SUBMISSION":
        return {"present": "platform.submission_reference"}
    if kind == "PRICE_REVIEW":
        return {"all": [{"present": "pricing.review_id"}, {"cost_snapshot_current": "PRICE_REVIEW"}]}
    if kind == "HUMAN_DECISION":
        return {"all": [{"eq": {"field": "pricing.decision", "value": "ACCEPT"}},
                        {"cost_snapshot_current": "PRICE_REVIEW"}]}
    if kind == "STOCK_PREPARATION":
        return {"present": "stock.request_reference"} if code == "FIRST_ORDER" else {
            "eq": {"field": "stock.prepared_requirement_met", "value": True}}
    if kind in {"COMPLIANCE", "LABEL", "EVIDENCE"}:
        return {"verified_artifact": {"COMPLIANCE": "MARKET_REQUIRED", "LABEL": "LABEL_PACKAGE",
                                      "EVIDENCE": "PHYSICAL_EVIDENCE"}[kind]}
    if kind == "PLATFORM_ACTIVATION":
        return {"all": [{"eq": {"field": "platform.status", "value": "ACTIVE"}},
                        {"verified_artifact": "ACTIVATION"}, {"asset_rights_allowed": "PUBLISHABLE"}]}
    return {"eq": {"field": "monitoring.registered", "value": True}}


def simple_contract(version=1):
    steps = [
        _step("INFORMATION", "商品资料", "DATA_PREPARATION", actions=["COMPLETE_DATA"]),
        _step("COMPLIANCE", "市场合规", "COMPLIANCE", ["INFORMATION"], ["UPLOAD_ARTIFACT", "VERIFY_ARTIFACT"]),
        _step("SUBMISSION", "提交平台", "PLATFORM_SUBMISSION", ["COMPLIANCE"], ["SUBMIT_PLATFORM"],
              "ADAPTER_TASK", "SYSTEM"),
        _step("ACTIVATION", "在售核验", "PLATFORM_ACTIVATION", ["SUBMISSION"], ["CONFIRM_ACTIVATION"],
              "EXTERNAL_WAIT", "PLATFORM"),
        _step("MONITORING", "经营监控", "MONITORING", ["ACTIVATION"], mode="SYSTEM_TASK", actor="SYSTEM", required=False),
    ]
    return _profile("SIMPLE_CONTRACT", "简单平台生命周期测试样本", version, "shopee", "ANY", steps)


def complex_contract(version=1):
    steps = [
        _step("PRODUCT_INFORMATION", "商品资料", "DATA_PREPARATION", actions=["COMPLETE_DATA"]),
        _step("PLATFORM_ATTRIBUTES", "平台属性", "DATA_PREPARATION", ["PRODUCT_INFORMATION"], ["COMPLETE_DATA"]),
        _step("PRODUCT_CREATED", "提交商品", "PLATFORM_SUBMISSION", ["PLATFORM_ATTRIBUTES"], ["SUBMIT_PLATFORM"],
              "ADAPTER_TASK", "SYSTEM"),
        _step("PRICE_REVIEW", "平台核价", "PRICE_REVIEW", ["PRODUCT_CREATED"], ["REPORT_PRICE"],
              "EXTERNAL_WAIT", "PLATFORM"),
        _step("PRICE_DECISION", "价格确认", "HUMAN_DECISION", ["PRICE_REVIEW"],
              ["ACCEPT_PRICE", "COUNTER_PRICE", "ABANDON_PRODUCT"]),
        _step("FIRST_ORDER", "平台首批备货任务", "STOCK_PREPARATION", ["PRICE_DECISION"], ["REQUEST_STOCK"]),
        _step("STOCK_PREPARATION", "备货", "STOCK_PREPARATION", ["FIRST_ORDER"], ["CONFIRM_STOCK"], actor="FACTORY"),
        _step("MARKET_COMPLIANCE", "市场合规", "COMPLIANCE", ["PRODUCT_INFORMATION"], ["UPLOAD_ARTIFACT", "VERIFY_ARTIFACT"]),
        _step("LABEL_PREPARATION", "标签准备", "LABEL", ["MARKET_COMPLIANCE", "PLATFORM_ATTRIBUTES"],
              ["GENERATE_LABEL", "REGENERATE_LABEL"], "SYSTEM_TASK", "SYSTEM"),
        _step("PHYSICAL_EVIDENCE", "实物材料核验", "EVIDENCE", ["STOCK_PREPARATION", "LABEL_PREPARATION"],
              ["UPLOAD_PHYSICAL_EVIDENCE", "VERIFY_EVIDENCE"]),
        _step("READY_FOR_SALE", "上线前检查", "DATA_PREPARATION", ["PRICE_DECISION", "MARKET_COMPLIANCE", "PHYSICAL_EVIDENCE"],
              mode="SYSTEM_TASK", actor="SYSTEM"),
        _step("ACTIVE", "在售核验", "PLATFORM_ACTIVATION", ["READY_FOR_SALE"], ["CONFIRM_ACTIVATION"],
              "EXTERNAL_WAIT", "PLATFORM"),
        _step("MONITORING", "经营监控", "MONITORING", ["ACTIVE"], mode="SYSTEM_TASK", actor="SYSTEM", required=False),
    ]
    profile = _profile("COMPLEX_CONTRACT", "复杂平台全托管样本（未核验）", version, "temu", "PLATFORM_STOCK", steps)
    profile["business_mode"] = "FULLY_MANAGED"
    return profile


def _profile(key, name, version, platform, fulfillment, steps):
    for sequence, step in enumerate(steps):
        step["sequence"] = sequence
    return {"profile_key": key, "version": version, "name": name,
            "description": "用户样本的本地契约定义；非官方流程，未连接真实平台。",
            "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
            "platform": platform, "market": "ANY", "fulfillment_mode": fulfillment,
            "category_scope": ["ANY"], "steps": steps,
            "status_mapping": {"unknown": "BLOCK", "statuses": {"CONTRACT_SUBMITTED": "SUBMITTED",
                                                                       "CONTRACT_ACTIVE": "ACTIVE"}}}
