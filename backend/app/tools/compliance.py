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
from .base import BaseTool, Reading, as_int, reading, ts
from .contract import ERR_NOT_FOUND, ToolError, ToolSpec


def report_dict(r: ComplianceReport) -> dict:
    return {"id": r.id, "target_type": r.target_type, "product_id": r.product_id,
            "listing_id": r.listing_id, "risk_level": r.risk_level, "score": r.score,
            "issues": r.issues or [], "suggestions": r.suggestions or [],
            "model": r.model, "created_at": ts(r.created_at)}


class ComplianceTool(BaseTool):
    name = "compliance"
    specs = (
        ToolSpec(tool="compliance", method="check_product", permission="compliance:read",
                 writes=False, summary="读取商品最近一次合规报告"),
        ToolSpec(tool="compliance", method="check_listing", permission="compliance:read",
                 writes=False, summary="读取 Listing 的合规视图（复核结论 + 合规报告）"),
        ToolSpec(tool="compliance", method="get_platform_rules", permission="compliance:read",
                 writes=False, summary="读取平台规则（指定平台或全平台概览）"),
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
