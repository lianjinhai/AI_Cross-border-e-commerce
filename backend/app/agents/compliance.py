"""合规 Agent 仅经 Tool 读取和生成结构化分析；报告及风险副本由可信调度接管。"""

from ..services.compliance_analysis import QUERIES, inputs, rule_analysis, validate_result
from .base import BaseAgent
from .contracts import CONTRACTS


class ComplianceAgent(BaseAgent):
    name = "compliance"
    agent_contract = CONTRACTS["risk_compliance"]

    def _read(self, tool, method, **kwargs):
        result = self.tool(tool).call(method, **kwargs)
        if not result.ok or not isinstance(result.data, list):
            raise ValueError(f"合规依据读取失败：{tool}.{method}")
        return result.data

    def check(self, target_type: str, ref_id: int) -> dict:
        if target_type not in {"product", "listing"} or type(ref_id) is not int or ref_id <= 0:
            raise ValueError("合规目标类型或 ID 无效")
        rows = self._read(target_type, "get_products" if target_type == "product" else "get_listings",
                          **{f"{target_type}_id": ref_id})
        if not rows:
            raise ValueError("合规目标不存在")
        target = rows[0]
        products = ([target] if target_type == "product" else
                    self._read("product", "get_products", product_id=target["product_id"]))
        if not products or products[0]["status"] == "deleted":
            raise ValueError("合规目标关联商品不存在")
        knowledge = {"mode": "not_used", "brands": [], "platform": []}
        if self.context is None or self.context.has("ai:read"):
            knowledge = {"mode": "readonly_tf", **{
                key: self._read("knowledge", "search", query=query, top_k=limit, read_only=True)
                for key, (query, limit) in zip(("brands", "platform"), QUERIES, strict=True)}}
        basis = inputs(target_type, target, products[0], knowledge)
        floor = rule_analysis(basis)
        result, mode = self.ask_json("check", "你是跨境电商合规审核引擎。只返回 JSON。",
            f"审核内容及规则依据：{basis}。规则命中不可删减，分数不可升高，风险不可降低。"
            f"按以下字段输出：{floor}", fallback=lambda: floor)
        try:
            normalized = validate_result(result, floor)
            if normalized["risk_level"] == "high" and floor["risk_level"] != "high":
                raise ValueError("高风险必须有确定性规则依据")
        except ValueError:
            normalized, mode = floor, "rule"
        return {"_compliance_analysis": {"target_type": target_type, "ref_id": ref_id,
                "basis": basis, **normalized, "model": "llm" if mode == "llm" else "rule"}}

    def check_product(self, product_id: int) -> dict:
        return self.check("product", product_id)

    def check_listing(self, listing_id: int) -> dict:
        return self.check("listing", listing_id)

    def check_batch(self, params=None, context=None) -> dict:
        params, context = params or {}, context or {}
        items = params.get("items")
        if items is None:
            items = ([{"target_type": "product", "ref_id": pid} for pid in
                      params.get("product_ids", context.get("product_ids", []))] +
                     [{"target_type": "listing", "ref_id": lid} for lid in
                      params.get("listing_ids", context.get("listing_ids", []))])
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError("合规批次范围无效")
        return {"analyses": [self.check(item["target_type"], item["ref_id"]) for item in items]}
