"""私域工厂机会 Agent：市场机会、真实供给与单位经济性联合门禁。

§18.3 第 3 步：读取全部经 Tool 层（Supply / Product Tool，见 D43）；匹配快照与
报价 upsert 的写入已迁出到 ``services/supply_outputs.py``（可信产物服务）。本 Agent
只产出只读提案（规则计算 + 经 Tool 读取），由 Orchestrator 经可信身份派发
``finalize_scan_private_supply_batch`` 在服务端校验、原子保存；Agent 内不得有任何
ORM 写（含 query/get），也不得直接调用成本计算服务（改由可信服务在同一事务内调用）。
"""
import re
from datetime import datetime, timedelta

from .base import BaseAgent
from .contracts import CONTRACTS


def _tokens(*values) -> set[str]:
    text = " ".join(str(v or "").lower() for v in values)
    return {x for x in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text) if len(x) >= 2}


def _parse_ts(value) -> datetime | None:
    """Tool 返回的时间统一是字符串（空值为 ""）——按同一口径解析回 datetime。

    为什么不让 Tool 直接返回 datetime：``ts()`` 是 Tool 层统一口径
    （tools/base.py），前端与 Agent 共用一种格式；数值比较留在调用方。
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


class FactoryOpportunityAgent(BaseAgent):
    name = "factory_opportunity"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["supply_intelligence"]

    # ---- 读取：全部经 Tool 层（§18.3 第 2 步）----
    def _catalogs(self) -> list[dict]:
        got = self.tool("supply").call("get_catalog_products", limit=200)
        return got.data if got.ok and isinstance(got.data, list) else []

    def _product(self, product_id: int) -> dict | None:
        got = self.tool("product").call("get_products", product_id=product_id)
        rows = got.data if got.ok and isinstance(got.data, list) else []
        return rows[0] if rows else None

    def _forecast(self, product_id: int) -> dict | None:
        got = self.tool("supply").call("get_forecast_snapshot", product_id=product_id)
        return got.data if got.ok and isinstance(got.data, dict) else None

    def scan_private_supply_batch(self, params: dict | None = None,
                                  context: dict | None = None) -> dict:
        """只读提案：返回每个商品的匹配/报价提案；写入由可信服务原子保存。

        §18.3 第 3 步：本方法不得有任何 ORM 写（含 query/get）。原 Agent 内的
        匹配快照 upsert 与报价 upsert、以及其后的 ``costing.calc_profit`` 调用，全部
        迁移到 ``services/supply_outputs.finalize_scan_private_supply_batch``——它先
        flush 报价、在同一会话内调用成本计算（取最低在库采购价），再整批单次提交。
        本 Agent 只负责读取目录/商品/预测并计算匹配分、汇总 gaps、决定是否要写报价。
        """
        params, context = params or {}, context or {}
        product_ids = params.get("product_ids") or context.get("product_ids") or []
        min_match = float(params.get("min_match_score", 50))

        catalogs = self._catalogs()
        if not catalogs:
            # 无目录时保持原有货源匹配：此处必须回填**请求的商品范围**而不是空列表，
            # 否则可信服务会把 context_patch.product_ids 写成 []，覆盖工作流上下文里
            # 上游（标准化）确定的商品范围，导致后续合规/Listing 步骤无目标、工作流
            # 误判为成功。旧实现返回空 context_patch（不改范围），语义等价。
            return {"catalog_present": False,
                    "skipped": "当前租户尚未维护私域工厂目录，继续使用原有货源匹配",
                    "product_ids": list(dict.fromkeys(int(x) for x in product_ids[:200])),
                    "matches": []}
        matches = []
        for product_id in [int(x) for x in product_ids[:200]]:
            product = self._product(product_id)
            if not product:
                continue
            target = _tokens(product["title"], product["category"],
                             *(product["attrs"] or {}).values())
            best = None
            for catalog in catalogs:
                supplier = catalog["supplier"]
                offered = _tokens(catalog["title"], catalog["category"],
                                  *catalog["capabilities"], *supplier["capabilities"])
                overlap = sorted(target & offered)
                category_match = bool(product["category"] and catalog["category"] and
                                      product["category"].lower() == catalog["category"].lower())
                title_match = bool(product["title"] and catalog["title"] and (
                    product["title"].lower() in catalog["title"].lower() or
                    catalog["title"].lower() in product["title"].lower()))
                capability = min(100.0, len(overlap) * 18.0 +
                                 (35 if category_match else 0) + (30 if title_match else 0))
                confirmed = _parse_ts(catalog["confirmed_at"])
                fresh = bool(confirmed and confirmed >= datetime.utcnow() - timedelta(days=90))
                gaps = []
                if supplier["verification_status"] != "verified": gaps.append("工厂尚未完成尽调")
                if not fresh: gaps.append("供给数据超过90天未确认")
                if not catalog["images"]: gaps.append("缺少商品图片")
                if catalog["monthly_capacity"] <= 0: gaps.append("未填写月产能")
                readiness = (40 if supplier["verification_status"] == "verified" else 0) + (
                    25 if fresh else 0) + (20 if catalog["monthly_capacity"] > 0 else 0) + (
                    15 if catalog["images"] else 0)
                total = round(capability * 0.65 + readiness * 0.35, 2)
                if best is None or total > best[0]:
                    best = (total, capability, readiness, overlap, gaps, catalog, supplier)
            if not best:
                continue
            total, capability, readiness, overlap, gaps, catalog, supplier = best
            gaps = list(gaps)
            forecast = self._forecast(product_id)
            cutoff = _parse_ts((forecast or {}).get("training_cutoff"))
            forecast_fresh = bool(cutoff and cutoff >= datetime.utcnow() - timedelta(days=7))
            if not forecast_fresh or (forecast or {}).get("confidence") != "high":
                gaps.append("缺少7天内高可信真实销量预测，禁止以产能推算营收")
            # 是否要写报价：匹配分达标、且没有任何数据/预测 gap（否则进入人工尽调）。
            write_offer = total >= min_match and not gaps
            matches.append({
                "product_id": product_id,
                "supplier_id": supplier["id"],
                "catalog_product_id": catalog["id"],
                "capability_score": capability,
                "readiness_score": readiness,
                "total_score": total,
                "matched_capabilities": list(overlap),
                "gaps": gaps,
                "write_offer": write_offer,
                "offer": ({"price": float(catalog["unit_price"]),
                           "currency": catalog["currency"], "moq": int(catalog["moq"]),
                           "ship_days": int(catalog["lead_days"]),
                           "in_stock": catalog["available_qty"] > 0}
                          if write_offer else None),
                "forecast_point": float((forecast or {}).get("point_forecast") or 0),
                "available_qty": catalog["available_qty"],
                "monthly_capacity": catalog["monthly_capacity"],
            })
        return {"catalog_present": True, "skipped": None,
                "product_ids": list(dict.fromkeys(int(x) for x in product_ids[:200])),
                "matches": matches}
