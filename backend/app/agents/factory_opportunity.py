"""私域工厂机会 Agent：市场机会、真实供给与单位经济性联合门禁。"""
import re
from datetime import datetime, timedelta

from ..models import (
    ForecastSnapshot,
    OpportunitySupplierMatch,
    Product,
    Supplier,
    SupplierCatalogProduct,
    SupplierOffer,
)
from ..services import costing
from .base import BaseAgent
from .contracts import CONTRACTS


def _tokens(*values) -> set[str]:
    text = " ".join(str(v or "").lower() for v in values)
    return {x for x in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text) if len(x) >= 2}


class FactoryOpportunityAgent(BaseAgent):
    name = "factory_opportunity"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["supply_intelligence"]

    def scan_private_supply_batch(self, params: dict | None = None,
                                  context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        product_ids = params.get("product_ids") or context.get("product_ids") or []
        min_match = float(params.get("min_match_score", 50))
        min_margin = float(params.get("min_margin", 0.15))

        ready_ids, candidates, blocked = [], [], []
        catalogs = (self.db.query(SupplierCatalogProduct, Supplier)
                    .join(Supplier, Supplier.id == SupplierCatalogProduct.supplier_id)
                    .filter(SupplierCatalogProduct.tenant_id == self.tenant_id,
                            SupplierCatalogProduct.status == "active").all())
        if not catalogs:
            return {"candidates": [], "ready": 0, "blocked": [],
                    "skipped": "当前租户尚未维护私域工厂目录，继续使用原有货源匹配",
                    "context_patch": {}}
        for product_id in [int(x) for x in product_ids[:200]]:
            product = self.db.get(Product, product_id)
            if not product or product.tenant_id != self.tenant_id:
                continue
            target = _tokens(product.title, product.category, *(product.attrs or {}).values())
            best = None
            for catalog, supplier in catalogs:
                offered = _tokens(catalog.title, catalog.category, *catalog.capabilities,
                                  *supplier.capabilities)
                overlap = sorted(target & offered)
                category_match = bool(product.category and catalog.category and
                                      product.category.lower() == catalog.category.lower())
                title_match = bool(product.title and catalog.title and (
                    product.title.lower() in catalog.title.lower() or
                    catalog.title.lower() in product.title.lower()))
                capability = min(100.0, len(overlap) * 18.0 +
                                 (35 if category_match else 0) + (30 if title_match else 0))
                fresh = bool(catalog.confirmed_at and
                             catalog.confirmed_at >= datetime.utcnow() - timedelta(days=90))
                gaps = []
                if supplier.verification_status != "verified": gaps.append("工厂尚未完成尽调")
                if not fresh: gaps.append("供给数据超过90天未确认")
                if not catalog.images: gaps.append("缺少商品图片")
                if catalog.monthly_capacity <= 0: gaps.append("未填写月产能")
                readiness = (40 if supplier.verification_status == "verified" else 0) + (
                    25 if fresh else 0) + (20 if catalog.monthly_capacity > 0 else 0) + (
                    15 if catalog.images else 0)
                total = round(capability * 0.65 + readiness * 0.35, 2)
                if best is None or total > best[0]:
                    best = (total, capability, readiness, overlap, gaps, catalog, supplier)
            if not best:
                blocked.append({"product_id": product_id, "reason": "私域工厂暂无有效目录商品"})
                continue
            total, capability, readiness, overlap, gaps, catalog, supplier = best
            gaps = list(gaps)
            latest_forecast = (self.db.query(ForecastSnapshot).filter(
                ForecastSnapshot.tenant_id == self.tenant_id,
                ForecastSnapshot.product_id == product_id)
                .order_by(ForecastSnapshot.created_at.desc()).first())
            forecast_fresh = bool(latest_forecast and
                                  latest_forecast.training_cutoff >= datetime.utcnow() - timedelta(days=7))
            if not forecast_fresh or latest_forecast.confidence != "high":
                gaps.append("缺少7天内高可信真实销量预测，禁止以产能推算营收")
            match = (self.db.query(OpportunitySupplierMatch).filter(
                OpportunitySupplierMatch.tenant_id == self.tenant_id,
                OpportunitySupplierMatch.product_id == product_id,
                OpportunitySupplierMatch.catalog_product_id == catalog.id).first())
            if not match:
                match = OpportunitySupplierMatch(tenant_id=self.tenant_id, product_id=product_id,
                    supplier_id=supplier.id, catalog_product_id=catalog.id)
                self.db.add(match)
            match.capability_score, match.readiness_score, match.total_score = capability, readiness, total
            match.matched_capabilities, match.gaps = overlap, list(gaps)
            match.decision = "due_diligence"
            self.db.flush()
            if total < min_match:
                match.gaps = list(match.gaps) + [f"匹配分 {total} 低于门槛 {min_match}"]
            elif gaps:
                pass
            else:
                offer = (self.db.query(SupplierOffer).filter(
                    SupplierOffer.tenant_id == self.tenant_id,
                    SupplierOffer.supplier_id == supplier.id,
                    SupplierOffer.product_id == product_id).first())
                if not offer:
                    offer = SupplierOffer(tenant_id=self.tenant_id, supplier_id=supplier.id,
                                          product_id=product_id)
                    self.db.add(offer)
                offer.price = float(catalog.unit_price); offer.currency = catalog.currency.upper()
                offer.moq = catalog.moq
                offer.ship_days = catalog.lead_days; offer.in_stock = catalog.available_qty > 0
                self.db.commit()  # 先落库报价，下面的成本计算据此取最低采购价
                try:
                    # 经 services/ 共享实现计算利润，而不是直接调用 PricingAgent：
                    # Agent 间 P2P 违反 Agent OS §3 / 规范 L-3（协作只能由
                    # Orchestrator 编排）。成本口径与定价页同源，避免两处漂移。
                    economics = costing.calc_profit(self.db, self.tenant_id, product_id)
                except ValueError as exc:
                    match.gaps = list(match.gaps) + [str(exc)]
                    economics = None
                if economics is None:
                    item = {"match_id": match.id, "product_id": product_id,
                            "supplier_id": supplier.id, "catalog_product_id": catalog.id,
                            "score": total, "decision": match.decision,
                            "expected_margin": match.expected_margin, "gaps": match.gaps}
                    candidates.append(item); blocked.append(item)
                    continue
                match.expected_price = economics["price"]
                match.expected_unit_profit = economics["profit"]
                match.expected_margin = economics["margin"]
                monthly_demand = max(float(latest_forecast.point_forecast) * 4, 0)
                monthly_units = min(monthly_demand, max(catalog.available_qty, 0),
                                    max(catalog.monthly_capacity, 0))
                match.expected_monthly_revenue = round(monthly_units * economics["price"], 2)
                if economics["margin"] >= min_margin and economics["profit"] > 0 and offer.in_stock:
                    match.decision = "ready"
                    ready_ids.append(product_id)
                else:
                    match.gaps = list(match.gaps) + [
                        f"预计利润率 {economics['margin']:.1%} 未达到 {min_margin:.1%} 或当前无库存"]
            item = {"match_id": match.id, "product_id": product_id, "supplier_id": supplier.id,
                    "catalog_product_id": catalog.id, "score": total, "decision": match.decision,
                    "expected_margin": match.expected_margin, "gaps": match.gaps}
            candidates.append(item)
            if match.decision != "ready": blocked.append(item)
        self.db.commit()
        return {"candidates": candidates, "ready": len(ready_ids), "blocked": blocked,
                "context_patch": {"product_ids": list(dict.fromkeys(int(x) for x in product_ids)),
                                  "private_ready_product_ids": list(dict.fromkeys(ready_ids)),
                                  "factory_opportunity_matches": candidates}}
