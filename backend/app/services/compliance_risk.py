"""受限风险副本业务执行器：只投影可信最新报告，绝不修改内容或发布。"""

from ..models import AiDecision, ComplianceReport
from .action_identity import requester_context
from .ai_actions import ActionError
from .compliance_facts import SOURCE, current_basis, latest_report, metadata, public_report, targets
from .review_analysis import digest


def validate_risk_projection(db, action, payload):
    if (not isinstance(payload, dict) or set(payload) != {"report_id", "batch_id", "slot", "risk_level", "before"}
            or any(type(payload[key]) is not int or payload[key] <= 0 for key in ("report_id", "batch_id"))):
        raise ActionError(400, "风险投影载荷无效")
    ctx = requester_context(db, action)
    item = {"target_type": "listing", "ref_id": action.target_id}
    listing, _ = targets(db, action.tenant_id, "listing", action.target_id)
    row = db.get(ComplianceReport, payload.get("report_id"), populate_existing=True)
    origin = db.get(AiDecision, payload.get("batch_id"), populate_existing=True)
    slot = payload.get("slot")
    if (origin is None or origin.tenant_id != action.tenant_id or origin.agent != "compliance"
            or origin.action != "check_batch_output" or not isinstance(origin.evidence, dict)
            or origin.evidence.get("source") != SOURCE
            or type(slot) is not int or slot < 0):
        raise ActionError(409, "风险投影缺少可信合规产物来源")
    if (not isinstance(origin.evidence.get("scope"), str) or not origin.evidence["scope"]
            or not isinstance(origin.evidence.get("items"), list) or not isinstance(origin.decision, dict)):
        raise ActionError(409, "风险投影来源摘要结构无效")
    meta = metadata(ctx, origin.evidence.get("scope"), origin.evidence.get("items"))
    if origin.evidence != meta or slot >= len(meta["items"]) or meta["items"][slot] != item:
        raise ActionError(409, "风险投影来源身份或范围无效")
    records = origin.decision.get("records", [])
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ActionError(409, "风险投影来源记录无效")
    latest = latest_report(db, action.tenant_id, item)
    if (slot >= len(records) or row is None or row.tenant_id != action.tenant_id
            or row.target_type != "listing" or row.listing_id != listing.id
            or latest is None or latest.id != row.id):
        raise ActionError(409, "风险投影不是当前最新合规报告")
    record = records[slot]
    if (record.get("report_id") != row.id or record.get("report_sha") != digest(public_report(row))
            or record.get("basis_sha") != digest(current_basis(db, ctx, item))
            or payload.get("risk_level") != row.risk_level or row.risk_level not in {"low", "mid", "high"}):
        raise ActionError(409, "风险投影的内容、规则或报告依据已变化")
    return listing, row


def update_listing_compliance_risk(db, action, payload):
    listing, row = validate_risk_projection(db, action, payload)
    if listing.risk_level != payload.get("before"):
        raise ActionError(409, "风险副本执行前已变化")
    before = listing.risk_level
    listing.risk_level = row.risk_level
    return {"before": before, "result": {"listing_id": listing.id, "risk_level": row.risk_level,
                                          "report_id": row.id}}
