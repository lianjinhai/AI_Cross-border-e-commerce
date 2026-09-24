"""上架复核 Agent：规则新鲜度、历史记忆、合规报告与平台规则的最终门禁。"""
import hashlib
import json
import os
from datetime import datetime

from ..models import ComplianceReport, Listing, ListingReviewDecision, Product
from ..services.platform_rules import check_updates, get_active_rules, validate_against_rules
from .base import BaseAgent


class ListingReviewAgent(BaseAgent):
    name = "listing_review"

    def review(self, listing_id: int) -> dict:
        listing = self.db.get(Listing, listing_id)
        if not listing or listing.tenant_id != self.tenant_id:
            raise ValueError("Listing 不存在")
        product = self.db.get(Product, listing.product_id)
        fingerprint = hashlib.sha256(json.dumps({
            "title": listing.title, "description": listing.description,
            "bullets": listing.bullets or [], "keywords": listing.keywords or [],
            "category": product.category, "brand": product.brand,
            "images": product.images or [],
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        update_result = None
        if os.getenv("ERP_RULES_URL"):
            update_result = check_updates(self.db, listing.platform)
        pack = get_active_rules(self.db, listing.platform)
        violations = validate_against_rules(self.db, listing.platform, listing, product)
        report = (self.db.query(ComplianceReport).filter(
            ComplianceReport.tenant_id == self.tenant_id,
            ComplianceReport.target_type == "listing",
            ComplianceReport.listing_id == listing_id)
            .order_by(ComplianceReport.created_at.desc()).first())
        reasons = list(violations)
        decision = "approved"
        if pack["origin"] == "none" or not pack.get("source_url"):
            decision, reasons = "manual_required", reasons + ["平台规则源不可用，不能确认当前规则"]
        if update_result and (update_result.get("error") or update_result.get("latest") == "not-found"):
            decision, reasons = "manual_required", reasons + [
                "实时规则同步失败，按关闭放行策略转人工审批：" +
                str(update_result.get("error") or update_result.get("hint"))]
        try:
            age = (datetime.utcnow().date() - datetime.strptime(pack["version"][:10], "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            age = 999
        if age > 30:
            decision, reasons = "manual_required", reasons + [f"平台规则已超过30天未更新（{pack['version']}）"]
        manual_categories = pack.get("rules", {}).get("manual_categories", [])
        matched_manual = [c for c in manual_categories if c and c in (product.category or "")]
        if matched_manual and decision != "rejected":
            decision, reasons = "manual_required", reasons + [
                f"类目「{product.category}」可能需要平台资质或预批准（{','.join(matched_manual)}）"]
        if report and report.risk_level == "high":
            decision, reasons = "rejected", reasons + ["Listing 合规报告为高风险"]
        elif report and report.risk_level == "mid" and decision != "rejected":
            decision, reasons = "manual_required", reasons + ["Listing 合规报告为中风险，必须人工确认"]
        if violations:
            decision = "rejected"
        latest_override = (self.db.query(ListingReviewDecision).filter(
            ListingReviewDecision.tenant_id == self.tenant_id,
            ListingReviewDecision.listing_id == listing.id,
            ListingReviewDecision.human_override.is_(True),
            ListingReviewDecision.decision == "approved")
            .order_by(ListingReviewDecision.created_at.desc()).first())
        override_matches = bool(
            latest_override
            and latest_override.rule_version == pack["version"]
            and (latest_override.evidence or {}).get("content_fingerprint") == fingerprint)
        previous_rejections = self.db.query(ListingReviewDecision).filter(
            ListingReviewDecision.tenant_id == self.tenant_id,
            ListingReviewDecision.platform == listing.platform,
            ListingReviewDecision.product_id == product.id,
            ListingReviewDecision.decision == "rejected").all()
        same_content_rejected = any(
            (item.evidence or {}).get("content_fingerprint") == fingerprint
            for item in previous_rejections)
        if same_content_rejected and decision == "approved":
            decision, reasons = "manual_required", reasons + ["相同内容在此平台有历史驳回记录，需人工复核"]
        # 人工批准只可解除 manual_required；明确违规和高风险永远不能强制覆盖。
        if decision == "manual_required" and override_matches:
            decision = "approved"
            reasons = reasons + [f"已由 {latest_override.reviewer} 人工批准当前内容与规则版本"]
        row = ListingReviewDecision(tenant_id=self.tenant_id, listing_id=listing.id,
            product_id=product.id, platform=listing.platform, decision=decision,
            reasons=reasons, evidence={"violations": violations,
                "compliance_risk": report.risk_level if report else "not_checked",
                "rule_origin": pack["origin"], "rule_age_days": age,
                "rule_sync": update_result,
                "content_fingerprint": fingerprint},
            rule_version=pack["version"], rule_source=pack.get("source_url", ""))
        self.db.add(row); self.db.commit()
        return {"review_id": row.id, "decision": decision, "reasons": reasons,
                "rule_version": row.rule_version, "rule_source": row.rule_source,
                "evidence": row.evidence}

    def review_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        """工作流批量门禁：只把通过复核的 Listing 交给发布步骤。"""
        params, context = params or {}, context or {}
        ids = params.get("listing_ids") or context.get("listing_ids") or []
        approved, blocked = [], []
        for listing_id in ids[:50]:
            result = self.review(int(listing_id))
            item = {"listing_id": int(listing_id), **result}
            if result["decision"] == "approved":
                approved.append(item)
            else:
                blocked.append(item)
        business_status = "blocked" if blocked and not approved else ("partial" if blocked else "success")
        return {"approved": approved, "blocked": blocked, "business_status": business_status,
                "context_patch": {"approved_listing_ids": [x["listing_id"] for x in approved],
                                  "review_blocked": blocked}}
