"""复核纯评估：Agent 与可信保存服务共用，零数据库副作用。"""

import hashlib
import json
from datetime import datetime

from .action_records import listing_fingerprint
from .platform_rules import validate_listing_fields


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def review_inputs(listing, product, pack, report):
    fields = ("id", "product_id", "listing_id", "target_type", "risk_level",
              "score", "issues", "suggestions", "model")
    return {"content": listing_fingerprint(listing, product),
            "listing_risk": listing.get("risk_level"), "rules": digest(pack),
            "report": digest({k: report.get(k) for k in fields}) if report else None}


def evaluate_review(listing, product, pack, report, overrides, rejections, sync=None):
    inputs = review_inputs(listing, product, pack, report)
    sync_failure = bool(sync and (sync.get("error") or sync.get("latest") == "not-found"))
    if sync_failure:
        inputs["rule_sync_failure"] = digest({key: sync.get(key) for key in ("error", "latest", "hint")})
    violations = validate_listing_fields(listing["platform"], pack.get("rules", {}), listing, product)
    reasons, decision = list(violations), "approved"
    if pack["origin"] == "none" or not pack.get("source_url"):
        decision, reasons = "manual_required", reasons + ["平台规则源不可用，不能确认当前规则"]
    if sync and (sync.get("error") or sync.get("latest") == "not-found"):
        decision, reasons = "manual_required", reasons + [
            "实时规则同步失败，按关闭放行策略转人工审批：" + str(sync.get("error") or sync.get("hint"))]
    try:
        age = (datetime.utcnow().date() - datetime.strptime(pack["version"][:10], "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        age = 999
    if age > 30:
        decision, reasons = "manual_required", reasons + [f"平台规则已超过30天未更新（{pack['version']}）"]
    manual = [c for c in pack.get("rules", {}).get("manual_categories", [])
              if c and c in (product["category"] or "")]
    if manual:
        decision, reasons = "manual_required", reasons + [
            f"类目「{product['category']}」可能需要平台资质或预批准（{','.join(manual)}）"]
    if listing.get("risk_level") == "high" or (report and report["risk_level"] == "high"):
        decision, reasons = "rejected", reasons + ["Listing 合规报告或内容为高风险"]
    elif report and report["risk_level"] == "mid":
        decision, reasons = "manual_required", reasons + ["Listing 合规报告为中风险，必须人工确认"]
    if violations:
        decision = "rejected"
    if decision == "approved" and any(
            (r.get("evidence") or {}).get("content_fingerprint") == inputs["content"] for r in rejections):
        decision, reasons = "manual_required", reasons + ["相同内容在此平台有历史驳回记录，需人工复核"]
    override = next(iter(overrides), None)
    if (decision == "manual_required" and override and override.get("human_override")
            and override["rule_version"] == pack["version"]
            and (override.get("evidence") or {}).get("review_inputs") == inputs):
        decision = "approved"
        reasons += [f"已由 {override['reviewer']} 人工批准当前内容与规则版本"]
    return {"listing_id": listing["id"], "product_id": product["id"], "platform": listing["platform"],
            "decision": decision, "reasons": reasons, "rule_version": pack["version"],
            "rule_source": pack.get("source_url", ""), "evidence": {
                "violations": violations, "compliance_risk": report["risk_level"] if report else "not_checked",
                "rule_origin": pack["origin"], "rule_age_days": age, "rule_sync": sync,
                "content_fingerprint": inputs["content"], "review_inputs": inputs}}
