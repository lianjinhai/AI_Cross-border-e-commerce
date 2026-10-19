"""可信复核分析保存与人工裁决；不创建发布 Action，不执行业务发布。"""

import os

from sqlalchemy import func

from ..db import SessionLocal
from ..models import ComplianceReport, Listing, ListingReviewDecision, Product, Tenant
from ..serialize import to_dict
from .action_identity import require_action_permission
from .ai_actions import ActionError
from .platform_rules import check_updates, get_active_rules
from .review_analysis import digest, evaluate_review

SOURCE = "listing_review_analysis_v1"


def review_targets(db, ctx, lid):
    if type(lid) is not int or lid <= 0:
        raise ActionError(400, "复核 Listing ID 无效")
    listing = db.get(Listing, lid, populate_existing=True)
    product = db.get(Product, listing.product_id, populate_existing=True) if listing else None
    if (listing is None or listing.tenant_id != ctx.legacy_tenant_id
            or product is None or product.tenant_id != ctx.legacy_tenant_id or product.status == "deleted"):
        raise ActionError(404, "复核 Listing 或关联商品不存在")
    return listing, product


def synchronize_review_rules(db, ctx, ids, permission):
    """同步服务独立会话，既有 check_updates 的 commit 不提交调用方业务事务。"""
    current = require_action_permission(db, ctx, permission)
    platforms = {review_targets(db, current, lid)[0].platform for lid in ids}
    if not os.getenv("ERP_RULES_URL"):
        return {}
    results = {}
    with SessionLocal() as rules_db:
        for platform in sorted(platforms):
            require_action_permission(rules_db, current, permission)
            results[platform] = check_updates(rules_db, platform,
                before_apply=lambda: require_action_permission(rules_db, current, permission))
    return results


def current_analysis(db, ctx, lid, sync=None):
    listing, product = review_targets(db, ctx, lid)
    report = db.query(ComplianceReport).filter(
        ComplianceReport.tenant_id == ctx.legacy_tenant_id,
        ComplianceReport.target_type == "listing", ComplianceReport.listing_id == lid
    ).order_by(ComplianceReport.id.desc()).populate_existing().first()
    overrides = db.query(ListingReviewDecision).filter(
        ListingReviewDecision.tenant_id == ctx.legacy_tenant_id,
        ListingReviewDecision.listing_id == lid, ListingReviewDecision.decision == "approved",
        ListingReviewDecision.human_override.is_(True)
    ).order_by(ListingReviewDecision.id.desc()).populate_existing().limit(1).all()
    rejections = db.query(ListingReviewDecision).filter(
        ListingReviewDecision.tenant_id == ctx.legacy_tenant_id,
        ListingReviewDecision.product_id == product.id, ListingReviewDecision.platform == listing.platform,
        ListingReviewDecision.decision == "rejected"
    ).order_by(ListingReviewDecision.id.desc()).populate_existing().limit(200).all()
    return evaluate_review(to_dict(listing), to_dict(product), get_active_rules(db, listing.platform),
                           to_dict(report) if report else None,
                           [to_dict(row) for row in overrides], [to_dict(row) for row in rejections], sync)


def _public(row):
    return {"review_id": row.id, "decision": row.decision, "reasons": row.reasons,
            "rule_version": row.rule_version, "rule_source": row.rule_source,
            "evidence": {k: v for k, v in (row.evidence or {}).items() if k != "_persistence"}}


def _lock(db, ctx, permission):
    table = Tenant.__table__
    db.execute(table.update().where(table.c.id == ctx.legacy_tenant_id).values(id=table.c.id))
    return require_action_permission(db, ctx, permission)


def _same_analysis(original, expected):
    """同步成功的过程诊断不属于风险变化，失败摘要仍由 review_inputs 绑定。"""
    def comparable(record):
        return {**record, "evidence": {
            key: value for key, value in record["evidence"].items() if key != "rule_sync"}}
    return comparable(original) == comparable(expected)


def finalize_reviews(db, ctx, items, scope, ids, permission="listing:write", syncs=None):
    """整批原子保存；重放验证当前风险，只允许合法人工裁决解除同依据的人工阻断。"""
    if not isinstance(scope, str) or not scope or len(scope) > 512:
        raise ActionError(400, "复核缺少有效服务端范围")
    if (not isinstance(ids, list) or len(ids) > 50
            or any(type(lid) is not int or lid <= 0 for lid in ids)
            or len(set(ids)) != len(ids) or not isinstance(items, list)):
        raise ActionError(400, "复核产物范围无效")
    try:
        current = _lock(db, ctx, permission)
        if permission not in {"listing:write", "compliance:approve"}:
            raise ActionError(403, "复核保存权限无效")
        previous_batch = db.query(ListingReviewDecision).filter(
            ListingReviewDecision.tenant_id == current.legacy_tenant_id,
            ListingReviewDecision.human_override.is_(False),
            ListingReviewDecision.evidence["_persistence"]["scope"].as_string() == scope,
            ListingReviewDecision.evidence["_persistence"]["requested_by"].as_integer() == current.user_id
        ).first()
        if previous_batch and previous_batch.evidence["_persistence"].get("listing_ids") != ids:
            raise ActionError(409, "同一复核范围的 Listing 清单已变化")
        if previous_batch:
            meta = previous_batch.evidence["_persistence"]
            if (meta.get("key") != digest([current.workspace_id, current.user_id, scope, previous_batch.listing_id])
                    or meta.get("source") != SOURCE or meta.get("workspace_id") != current.workspace_id):
                raise ActionError(409, "复核恢复来源已变化")
        if len(items) != len(ids):
            raise ActionError(400, "复核分析范围不完整")
        analyses = {}
        for lid in ids:
            platform = review_targets(db, current, lid)[0].platform
            analyses[lid] = current_analysis(db, current, lid, (syncs or {}).get(platform))
        results = []
        for lid, item in zip(ids, items, strict=True):
            record = item.get("_review_analysis") if isinstance(item, dict) else None
            if not isinstance(record, dict) or record.get("listing_id") != lid:
                raise ActionError(400, "复核分析字段无效")
            expected = analyses[lid]
            if record != expected:
                raise ActionError(409, "复核内容、规则、报告或人工依据已变化")
            key = digest([current.workspace_id, current.user_id, scope, lid])
            saved = db.query(ListingReviewDecision).filter(
                ListingReviewDecision.tenant_id == current.legacy_tenant_id,
                ListingReviewDecision.human_override.is_(False),
                ListingReviewDecision.evidence["_persistence"]["key"].as_string() == key
            ).order_by(ListingReviewDecision.id.desc()).populate_existing().first()
            if saved:
                meta = (saved.evidence or {}).get("_persistence", {})
                original = {k: getattr(saved, k) for k in expected}
                original["evidence"] = {k: v for k, v in saved.evidence.items() if k != "_persistence"}
                if (meta.get("source") != SOURCE or meta.get("listing_ids") != ids
                        or meta.get("scope") != scope or meta.get("requested_by") != current.user_id
                        or meta.get("workspace_id") != current.workspace_id
                        or meta.get("snapshot_sha") != digest(original)):
                    raise ActionError(409, "复核恢复产物或范围已变化")
                if _same_analysis(original, expected):
                    results.append(_public(saved))
                    continue
                if not (original["decision"] == "manual_required" and expected["decision"] == "approved"
                        and original["evidence"]["review_inputs"] == expected["evidence"]["review_inputs"]):
                    raise ActionError(409, "原复核依据或风险已变化，请重新复核")
            row = ListingReviewDecision(tenant_id=current.legacy_tenant_id, **expected)
            row.evidence = {**expected["evidence"], "_persistence": {
                "source": SOURCE, "key": key, "scope": scope, "listing_ids": ids,
                "requested_by": current.user_id, "workspace_id": current.workspace_id,
                "trace_id": current.trace_id, "snapshot_sha": digest(expected)}}
            db.add(row)
            db.flush()
            results.append(_public(row))
        db.commit()
        return results
    except Exception:
        db.rollback()
        raise


def approve_review_output(db, ctx, lid, note, review_id):
    """审批服务按最新身份与当前内容重新验证，保持编辑人和审批人分离。"""
    try:
        current = _lock(db, ctx, "compliance:approve")
        listing, _ = review_targets(db, current, lid)
        if listing.last_edited_by == current.user_id:
            raise ActionError(403, "提交或编辑该 Listing 的人员不能审批自己的内容")
        if not isinstance(note, str) or not note.strip():
            raise ActionError(400, "人工审批必须填写依据")
        previous = db.get(ListingReviewDecision, review_id, populate_existing=True)
        if previous is None or previous.tenant_id != current.legacy_tenant_id or previous.listing_id != lid:
            raise ActionError(404, "人工审批依据不存在")
        expected = current_analysis(db, current, lid, (previous.evidence or {}).get("rule_sync"))
        if (previous.evidence or {}).get("review_inputs") != expected["evidence"]["review_inputs"]:
            raise ActionError(409, "人工审批依据已变化，请重新复核")
        if expected["decision"] == "rejected":
            raise ActionError(400, "明确违规或高风险不可人工强制放行")
        if expected["decision"] == "approved":
            db.commit()
            return {"review_id": previous.id, **expected, "already_approved": True}
        row = ListingReviewDecision(tenant_id=current.legacy_tenant_id, **{
            **expected, "decision": "approved", "reasons": [note.strip()],
            "evidence": {**expected["evidence"], "approved_review_id": previous.id, "approval_note": note.strip()},
            "reviewer": f"human:{current.username}", "human_override": True})
        db.add(row)
        db.commit()
        return to_dict(row)
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------- 复核队列（只读）

_REVIEW_STATUS = ("manual_required", "rejected", "approved")


def _validate_review_status(status: str) -> None:
    if status not in _REVIEW_STATUS:
        raise ActionError(400, "status 必须是 manual_required/rejected/approved")


def _latest_review_ids(db, tenant_id: int, status: str):
    """每个 Listing 的最新一次复核决策 id 子查询（按决策取值过滤）。"""
    return (db.query(func.max(ListingReviewDecision.id).label("max_id"))
            .filter(ListingReviewDecision.tenant_id == tenant_id,
                    ListingReviewDecision.decision == status)
            .group_by(ListingReviewDecision.listing_id).subquery())


def review_queue(db, tenant_id: int, status: str = "manual_required", limit: int = 50) -> dict:
    """合规审批队列：待人工复核的 Listing（router 与 workbench BFF 共用的单一实现）。

    默认返回 ``manual_required``（复核 Agent 判定需人工确认的），每条附最新复核决策与理由。
    """
    _validate_review_status(status)
    sub = _latest_review_ids(db, tenant_id, status)
    rows = (db.query(ListingReviewDecision, Listing)
            .join(sub, ListingReviewDecision.id == sub.c.max_id)
            .join(Listing, Listing.id == ListingReviewDecision.listing_id)
            .order_by(ListingReviewDecision.created_at.desc())
            .limit(max(1, min(int(limit or 50), 200))).all())
    items = []
    for decision, listing in rows:
        item = to_dict(decision)
        item["listing_title"] = listing.title
        item["platform"] = listing.platform
        item["listing_status"] = listing.status
        items.append(item)
    return {"items": items, "total": len(items)}


def review_queue_count(db, tenant_id: int, status: str = "manual_required") -> int:
    """符合条件的待复核 Listing **总数**（不受 limit 影响，供角标使用）。"""
    _validate_review_status(status)
    sub = _latest_review_ids(db, tenant_id, status)
    return int(db.query(func.count()).select_from(sub).scalar() or 0)
