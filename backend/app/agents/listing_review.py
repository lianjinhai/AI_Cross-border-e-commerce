"""上架复核 Agent：仅通过 Tool 读取并返回结构化分析，不写规则或复核表。"""

from ..services.review_analysis import evaluate_review
from .base import BaseAgent
from .contracts import CONTRACTS


class ListingReviewAgent(BaseAgent):
    name = "listing_review"
    agent_contract = CONTRACTS["risk_compliance"]

    def _read(self, tool, method, **params):
        result = self.tool(tool).call(method, **params)
        if not result.ok:
            raise ValueError("复核依据读取失败：" + str(result.error))
        return result.data

    def _listing(self, listing_id):
        rows = self._read("listing", "get_listings", listing_id=listing_id)
        if not rows:
            raise ValueError("Listing 不存在")
        return rows[0]

    def _product(self, product_id):
        products = self._read("product", "get_products", product_id=product_id)
        if not products or products[0].get("status") == "deleted":
            raise ValueError("Listing 关联商品不存在")
        return products[0]

    def _rule_pack(self, platform):
        return self._read("compliance", "get_platform_rules", platform=platform)

    def _listing_report(self, listing_id):
        return self._read("compliance", "check_listing", listing_id=listing_id).get("report")

    def _decisions(self, **filters):
        return self._read("compliance", "get_review_decisions", **filters)

    def review(self, listing_id: int, *, rule_sync=None) -> dict:
        listing = self._listing(listing_id)
        product = self._product(listing["product_id"])
        pack = self._rule_pack(listing["platform"])
        report = self._listing_report(listing_id)
        overrides = self._decisions(listing_id=listing_id, decision="approved", human_override=True, limit=1)
        rejections = self._decisions(platform=listing["platform"], product_id=product["id"],
                                    decision="rejected", limit=200)
        analysis = evaluate_review(listing, product, pack, report, overrides, rejections, rule_sync)
        return {**analysis, "_review_analysis": analysis}

    def review_batch(self, params=None, context=None):
        params, context = params or {}, context or {}
        ids = params.get("listing_ids", context.get("listing_ids", []))
        if not isinstance(ids, list) or len(ids) > 50:
            raise ValueError("复核 Listing 范围无效")
        return {"_review_batch": [self.review(lid) for lid in dict.fromkeys(ids)]}
