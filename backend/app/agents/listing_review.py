"""上架复核 Agent：规则新鲜度、历史记忆、合规报告与平台规则的最终门禁。

§18.3 第 2 步：读取全部经 Tool 层；写路径（复核结论落库）集中标注，
属第 3 步（Action 层）欠账。
"""
import os
from datetime import datetime

from ..models import ListingReviewDecision
from ..services.action_records import listing_fingerprint
from ..services.platform_rules import check_updates, validate_listing_fields
from .base import BaseAgent
from .contracts import CONTRACTS


class ListingReviewAgent(BaseAgent):
    name = "listing_review"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["risk_compliance"]

    # ---- 读取：全部经 Tool 层（§18.3 第 2 步）----
    def _listing(self, listing_id: int) -> dict:
        got = self.tool("listing").call("get_listings", listing_id=listing_id)
        rows = got.data if got.ok and isinstance(got.data, list) else []
        if not rows:
            raise ValueError("Listing 不存在")
        return rows[0]

    def _product(self, product_id) -> dict:
        got = self.tool("product").call("get_products", product_id=product_id)
        rows = got.data if got.ok and isinstance(got.data, list) else []
        if not rows:
            raise ValueError(f"Listing 关联商品 {product_id} 不存在")
        return rows[0]

    def _rule_pack(self, platform: str) -> dict:
        """平台规则包走 Compliance Tool：与 compliance / listing 同一读取口径。"""
        got = self.tool("compliance").call("get_platform_rules", platform=platform)
        pack = got.data if got.ok and isinstance(got.data, dict) else None
        if not pack:
            # 与旧实现「未知平台得到 rules={} / origin=none」等价：门禁据此判
            # manual_required（不能确认当前规则），不会误放行。
            return {"platform": platform, "version": "none", "rules": {},
                    "source_url": "", "origin": "none"}
        return pack

    def _listing_report(self, listing_id: int) -> dict | None:
        got = self.tool("compliance").call("check_listing", listing_id=listing_id)
        report = got.data.get("report") if (got.ok and isinstance(got.data, dict)) else None
        return report if isinstance(report, dict) else None

    def _decisions(self, **filters) -> list[dict]:
        got = self.tool("compliance").call("get_review_decisions", **filters)
        return got.data if got.ok and isinstance(got.data, list) else []

    def review(self, listing_id: int) -> dict:
        listing = self._listing(listing_id)
        product = self._product(listing["product_id"])
        fingerprint = listing_fingerprint(listing, product)
        update_result = None
        if os.getenv("ERP_RULES_URL"):
            # 实时规则同步（仅在 ERP_RULES_URL 配置时启用）；它是 services 层的
            # 既有能力，写的是平台级规则包（tenant_id=NULL），不在本步迁移范围。
            update_result = check_updates(self.db, listing["platform"])
        pack = self._rule_pack(listing["platform"])
        # 规则包与 Listing/商品都来自 Tool，判定用 services 的字段级核心（T-53）。
        violations = validate_listing_fields(listing["platform"], pack.get("rules", {}),
                                             listing, product)
        report = self._listing_report(listing_id)
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
        matched_manual = [c for c in manual_categories
                          if c and c in (product["category"] or "")]
        if matched_manual and decision != "rejected":
            decision, reasons = "manual_required", reasons + [
                f"类目「{product['category']}」可能需要平台资质或预批准"
                f"（{','.join(matched_manual)}）"]
        if report and report["risk_level"] == "high":
            decision, reasons = "rejected", reasons + ["Listing 合规报告为高风险"]
        elif report and report["risk_level"] == "mid" and decision != "rejected":
            decision, reasons = "manual_required", reasons + ["Listing 合规报告为中风险，必须人工确认"]
        if violations:
            decision = "rejected"
        latest_override = next(iter(self._decisions(
            listing_id=listing["id"], decision="approved",
            human_override=True, limit=1)), None)
        override_matches = bool(
            latest_override
            and latest_override["rule_version"] == pack["version"]
            and (latest_override["evidence"] or {}).get("content_fingerprint") == fingerprint)
        previous_rejections = self._decisions(
            platform=listing["platform"], product_id=product["id"],
            decision="rejected", limit=200)
        same_content_rejected = any(
            (item["evidence"] or {}).get("content_fingerprint") == fingerprint
            for item in previous_rejections)
        if same_content_rejected and decision == "approved":
            decision, reasons = "manual_required", reasons + ["相同内容在此平台有历史驳回记录，需人工复核"]
        # 人工批准只可解除 manual_required；明确违规和高风险永远不能强制覆盖。
        if decision == "manual_required" and override_matches:
            decision = "approved"
            reasons = reasons + [f"已由 {latest_override['reviewer']} 人工批准当前内容与规则版本"]
        row = ListingReviewDecision(tenant_id=self.tenant_id, listing_id=listing["id"],
            product_id=product["id"], platform=listing["platform"], decision=decision,
            reasons=reasons, evidence={"violations": violations,
                "compliance_risk": report["risk_level"] if report else "not_checked",
                "rule_origin": pack["origin"], "rule_age_days": age,
                "rule_sync": update_result,
                "content_fingerprint": fingerprint},
            rule_version=pack["version"], rule_source=pack.get("source_url", ""))
        # 写路径（新建复核结论）：§18.3 第 3 步（Action 层）欠账，见 D42。
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
