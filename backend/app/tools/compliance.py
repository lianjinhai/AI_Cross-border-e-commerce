"""Compliance Tool：合规视图读取（§10.4 冻结清单）。

为什么 `check_product` / `check_listing` 是**读**而不是「发起一次检测」
    §10.4 把这两个方法冻结为读操作（权限 `compliance:read`，读写列标「读」）。
    因此它们返回**已持久化的最近一次**报告，不重新跑检测、不落库。
    真正的「跑检测并生成报告」是写操作，按 §9 必须走 Action 路径（第 3 步），
    本层不提供该入口——否则 `compliance:read` 就成了绕过写闸的后门。

    「检测算法仍在 `ComplianceAgent` 内、没有下沉到 services」这一点已登记为
    债务：算法归位后才能让 Tool 层提供无副作用的即时评估。
"""

from __future__ import annotations

from ..models import ComplianceReport, Listing, ListingReviewDecision
from ..services import platform_rules
from .base import BaseTool, Reading, as_int, clamp_limit, reading, ts
from .contract import ERR_BAD_PARAM, ERR_NOT_FOUND, ToolError, ToolSpec

# 复核结论枚举取自该表写入方（listing_review.py 的 decision 取值）。
_DECISIONS = ("approved", "rejected", "manual_required")


def report_dict(r: ComplianceReport) -> dict:
    return {"id": r.id, "target_type": r.target_type, "product_id": r.product_id,
            "listing_id": r.listing_id, "risk_level": r.risk_level, "score": r.score,
            "issues": r.issues or [], "suggestions": r.suggestions or [],
            "model": r.model, "created_at": ts(r.created_at)}


def decision_dict(r: ListingReviewDecision) -> dict:
    return {"id": r.id, "listing_id": r.listing_id, "product_id": r.product_id,
            "platform": r.platform, "decision": r.decision, "reasons": r.reasons or [],
            "evidence": r.evidence or {}, "reviewer": r.reviewer,
            "human_override": r.human_override, "rule_version": r.rule_version,
            "rule_source": r.rule_source, "created_at": ts(r.created_at)}


class ComplianceTool(BaseTool):
    name = "compliance"
    specs = (
        ToolSpec(tool="compliance", method="check_product", permission="compliance:read",
                 writes=False, summary="读取商品最近一次合规报告"),
        ToolSpec(tool="compliance", method="check_listing", permission="compliance:read",
                 writes=False, summary="读取 Listing 的合规视图（复核结论 + 合规报告）"),
        ToolSpec(tool="compliance", method="get_platform_rules", permission="compliance:read",
                 writes=False, summary="读取平台规则（指定平台或全平台概览）"),
        ToolSpec(tool="compliance", method="get_review_decisions", permission="compliance:read",
                 writes=False, summary="列出上架复核结论（可按 Listing/商品/平台/结论过滤）"),
    )

    def _check_product(self, product_id: int) -> Reading:
        pid = as_int(product_id, "product_id")
        row = (self.db.query(ComplianceReport)
               .filter(ComplianceReport.tenant_id == self.context.tenant_id,
                       ComplianceReport.target_type == "product",
                       ComplianceReport.product_id == pid)
               .order_by(ComplianceReport.id.desc()).first())
        if row is None:
            raise ToolError(ERR_NOT_FOUND, "商品 %s 尚无合规报告" % pid)
        return reading(report_dict(row), table="compliance_reports",
                       report_id=row.id, product_id=pid)

    def _check_listing(self, listing_id: int) -> Reading:
        lid = as_int(listing_id, "listing_id")
        listing = self.db.get(Listing, lid)
        if not listing or listing.tenant_id != self.context.tenant_id:
            raise ToolError(ERR_NOT_FOUND, "Listing %s 不存在" % lid)
        decision = (self.db.query(ListingReviewDecision)
                    .filter(ListingReviewDecision.tenant_id == self.context.tenant_id,
                            ListingReviewDecision.listing_id == lid)
                    .order_by(ListingReviewDecision.id.desc()).first())
        report = (self.db.query(ComplianceReport)
                  .filter(ComplianceReport.tenant_id == self.context.tenant_id,
                          ComplianceReport.target_type == "listing",
                          ComplianceReport.listing_id == lid)
                  .order_by(ComplianceReport.id.desc()).first())
        return reading(
            {"listing": {"id": listing.id, "product_id": listing.product_id,
                         "platform": listing.platform, "language": listing.language,
                         "title": listing.title, "status": listing.status,
                         "risk_level": listing.risk_level,
                         "external_id": listing.external_id,
                         "published_at": ts(listing.published_at),
                         "updated_at": ts(listing.updated_at)},
             "review_decision": None if decision is None else {
                 "id": decision.id, "decision": decision.decision,
                 "reasons": decision.reasons or [],
                 "rule_version": decision.rule_version,
                 "reviewer": decision.reviewer,
                 "human_override": decision.human_override,
                 "created_at": ts(decision.created_at)},
             "report": None if report is None else report_dict(report)},
            table="listings", listing_id=lid,
            decision_id=decision.id if decision else None,
            report_id=report.id if report else None)

    def _get_platform_rules(self, platform: str = "") -> Reading:
        name = (platform or "").strip()
        if name:
            data = platform_rules.get_active_rules(self.db, name)
            return reading(data, table="platform_rule_packs", platform=name)
        rows = platform_rules.all_rules_overview(self.db)
        return reading(rows, table="platform_rule_packs",
                       platforms=[r.get("platform") for r in rows])

    def _get_review_decisions(self, listing_id=None, product_id=None, platform: str = "",
                              decision: str = "", human_override=None,
                              limit=50) -> Reading:
        """列出上架复核结论（最新在前，可按 Listing/商品/平台/结论/人工覆盖过滤）。

        为什么排序用 `id` 而不是 `created_at`：同一批写入的时间戳可能完全相同
        （秒级精度），`id` 才是唯一单调的次序；与 `check_listing` 的口径一致。
        """
        n = clamp_limit(limit)
        lid = None if listing_id in (None, "") else as_int(listing_id, "listing_id")
        pid = None if product_id in (None, "") else as_int(product_id, "product_id")
        state = (decision or "").strip()
        if state and state not in _DECISIONS:
            raise ToolError(ERR_BAD_PARAM, "decision 必须是 %s 之一，实际 %r"
                            % ("/".join(_DECISIONS), decision))
        override = None
        if human_override is not None:
            override = (human_override if isinstance(human_override, bool)
                        else str(human_override).strip().lower() in ("1", "true", "yes"))
        query = self.db.query(ListingReviewDecision).filter(
            ListingReviewDecision.tenant_id == self.context.tenant_id)
        if lid is not None:
            query = query.filter(ListingReviewDecision.listing_id == lid)
        if pid is not None:
            query = query.filter(ListingReviewDecision.product_id == pid)
        name = (platform or "").strip()
        if name:
            query = query.filter(ListingReviewDecision.platform == name)
        if state:
            query = query.filter(ListingReviewDecision.decision == state)
        if override is not None:
            query = query.filter(ListingReviewDecision.human_override.is_(override))
        rows = query.order_by(ListingReviewDecision.id.desc()).limit(n).all()
        return reading([decision_dict(r) for r in rows], table="listing_review_decisions",
                       decision_ids=[r.id for r in rows], count=len(rows))
