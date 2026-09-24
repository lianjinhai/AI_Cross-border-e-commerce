"""定价 Agent（真实利润/动态定价，第十一章）与广告增长 Agent（第十二章）。"""
from datetime import datetime

from ..models import (
    AdCampaign,
    ExchangeRate,
    Listing,
    PricingRecord,
    Product,
    ProductScore,
    SupplierOffer,
)
from ..services import settings_service
from .base import BaseAgent

_DEFAULT_RULES = {"min_margin": 0.15, "target_margin": 0.35,
                  "logistics_base": 18.0, "logistics_per_kg": 8.0, "ads_default": 1.5}
_DEFAULT_FEES = {"shopee": 0.06, "amazon": 0.15, "shopify": 0.02,
                 "ebay": 0.12, "temu": 0.05, "tiktok": 0.08}
_DEFAULT_FX = {"USD": 7.12}


def _setting(db, key: str, default: dict) -> dict:
    """兼容旧调用：无租户上下文时按平台级读取（保留供非租户场景使用）。"""
    row = settings_service.get_setting(db, None, key)
    v = dict(default)
    v.update(row)
    return v


def _setting_for(db, tenant_id: int, key: str, default: dict) -> dict:
    """按租户读取配置（租户覆盖 → 平台默认 → 代码默认）。"""
    v = dict(default)
    v.update(settings_service.get_setting(db, tenant_id, key))
    return v


class PricingAgent(BaseAgent):
    """真实利润 = 售价 - (采购+物流+平台佣金+广告)/汇率。"""

    name = "pricing"

    # ---------- 成本要素 ----------
    def _latest_fx(self, base: str, quote: str) -> float | None:
        if base == quote:
            return 1.0
        row = (self.db.query(ExchangeRate).filter(
            ExchangeRate.tenant_id == self.tenant_id,
            ExchangeRate.base_currency == base,
            ExchangeRate.quote_currency == quote,
            ExchangeRate.effective_at <= datetime.utcnow())
            .order_by(ExchangeRate.effective_at.desc()).first())
        return float(row.rate) if row else None

    def _to_cny(self, amount: float, currency: str) -> float:
        currency = (currency or "CNY").upper()
        direct = self._latest_fx(currency, "CNY")
        if direct is not None:
            return amount * direct
        # 财务主口径通常维护兑 USD 汇率，允许通过 USD 安全交叉换算。
        base_usd = self._latest_fx(currency, "USD")
        cny_usd = self._latest_fx("CNY", "USD")
        if base_usd is not None and cny_usd:
            return amount * base_usd / cny_usd
        raise ValueError(f"缺少 {currency}→CNY 的有效汇率，禁止计算利润")

    def _best_purchase(self, product: Product) -> tuple[float, int | None]:
        offers = (self.db.query(SupplierOffer)
                 .filter(SupplierOffer.tenant_id == self.tenant_id,
                          SupplierOffer.product_id == product.id,
                          SupplierOffer.in_stock.is_(True))
                 .all())
        converted = [(self._to_cny(float(o.price), o.currency), o.id) for o in offers]
        if converted:
            return min(converted, key=lambda x: x[0])
        return float((product.attrs or {}).get("supplier_price") or 10.0), None

    def cost_elements(self, product: Product, platform: str = "") -> dict:
        rules = _setting_for(self.db, self.tenant_id, "rules", _DEFAULT_RULES)
        fees = _setting_for(self.db, self.tenant_id, "platform_fees", _DEFAULT_FEES)
        fx_map = _setting_for(self.db, self.tenant_id, "fx", _DEFAULT_FX)
        attrs = product.attrs or {}
        platform = platform or attrs.get("platform") or "shopee"
        purchase_cny, offer_id = self._best_purchase(product)
        weight = float(attrs.get("weight_kg") or 0.3)
        return {
            "purchase_cny": purchase_cny, "offer_id": offer_id,
            "logistics_cny": round(rules["logistics_base"] + rules["logistics_per_kg"] * weight, 2),
            "fee_rate": float(fees.get(platform, 0.06)),
            "ads_cny": float(rules["ads_default"]),
            "fx": float(fx_map.get("USD", 7.12)),
        }

    # ---------- 利润计算 ----------
    def calc_profit(self, product_id: int, price: float | None = None) -> dict:
        p = self.db.get(Product, product_id)
        if not p or p.tenant_id != self.tenant_id:
            raise ValueError(f"商品 {product_id} 不存在")
        ce = self.cost_elements(p)
        price = float(price or (p.attrs or {}).get("sale_price") or 19.99)
        cost_total_cny = ce["purchase_cny"] + ce["logistics_cny"] + ce["ads_cny"] + ce["fee_rate"] * price * ce["fx"]
        profit = round(price - cost_total_cny / ce["fx"], 2)
        margin = round(profit / price, 4) if price else 0
        return {"product_id": product_id, "purchase_cost": ce["purchase_cny"],
                "logistics_cost": ce["logistics_cny"], "platform_fee_rate": ce["fee_rate"],
                "ads_cost": ce["ads_cny"], "price": price, "profit": profit,
                "margin": margin, "currency": "USD", "fx": ce["fx"]}

    # ---------- 动态定价 ----------
    def suggest_price(self, product_id: int) -> dict:
        p = self.db.get(Product, product_id)
        if not p or p.tenant_id != self.tenant_id:
            raise ValueError(f"商品 {product_id} 不存在")
        ce = self.cost_elements(p)
        rules = _setting_for(self.db, self.tenant_id, "rules", _DEFAULT_RULES)
        fx, fee = ce["fx"], ce["fee_rate"]
        cost_cny = ce["purchase_cny"] + ce["logistics_cny"] + ce["ads_cny"]
        floor = cost_cny * (1 + rules["min_margin"]) / (fx * (1 - fee))
        target = cost_cny * (1 + rules["target_margin"]) / (fx * (1 - fee))
        score = (self.db.query(ProductScore)
                 .filter(ProductScore.tenant_id == self.tenant_id, ProductScore.product_id == product_id)
                 .order_by(ProductScore.created_at.desc()).first())
        demand = score.demand if score else 55
        competition = score.competition if score else 50
        adjustments = []
        factor = 1.0
        if demand > 70:
            factor += 0.05
            adjustments.append(f"需求旺盛({demand:.0f}) 提价5%")
        if competition > 70:
            factor -= 0.05
            adjustments.append(f"竞争激烈({competition:.0f}) 降价5%")
        current = float((p.attrs or {}).get("sale_price") or 0)
        if current and current > target * 1.3:
            factor -= 0.05
            adjustments.append("现价偏高，向目标价回归5%")
        suggested = round(max(floor, target * factor), 2)
        price_now = current or suggested
        profit = round(price_now - (cost_cny + fee * price_now * fx) / fx, 2)

        def rule() -> dict:
            return {"suggested_price": suggested, "strategy": "成本加成+市场修正",
                    "adjustments": adjustments or ["按目标利润率定价"]}

        system = "你是跨境电商动态定价引擎。只返回 JSON。"
        prompt = (f"商品「{p.title}」成本¥{cost_cny:.2f}，佣金率{fee}，汇率{fx}，"
                  f"需求分{demand:.0f}，竞争分{competition:.0f}，价格下限${floor:.2f}，目标价${target:.2f}。"
                  "给出最终建议价(不得低于下限、可在目标价±8%浮动)。"
                  "返回 JSON: {\"suggested_price\":0,\"strategy\":\"一句话策略\",\"adjustments\":[\"中文理由\"]}")
        result, mode = self.ask_json("suggest_price", system, prompt, fallback=rule, small_task=True)
        try:
            sp = float(result.get("suggested_price"))
            if sp < floor * 0.999 or sp > target * 1.15:
                raise ValueError
            suggested, adjustments = round(sp, 2), result.get("adjustments") or adjustments
        except (TypeError, ValueError):
            mode = "rule"
        row = PricingRecord(
            tenant_id=self.tenant_id, product_id=product_id,
            purchase_cost=ce["purchase_cny"], logistics_cost=ce["logistics_cny"],
            platform_fee_rate=fee, ads_cost=ce["ads_cny"],
            price=price_now, suggested_price=suggested, profit=profit,
            margin=round(profit / price_now, 4) if price_now else 0,
            currency="USD",
            reason={"strategy": result.get("strategy", "成本加成+市场修正"),
                    "cost_cny": round(cost_cny, 2), "floor": round(floor, 2),
                    "target": round(target, 2), "adjustments": adjustments},
            model="llm" if mode == "llm" else "rule",
        )
        self.db.add(row)
        self.db.commit()
        out = {"id": row.id, "product_id": product_id, "purchase_cost": row.purchase_cost,
               "logistics_cost": row.logistics_cost, "platform_fee_rate": row.platform_fee_rate,
               "ads_cost": row.ads_cost, "price": row.price, "suggested_price": row.suggested_price,
               "profit": row.profit, "margin": row.margin, "currency": row.currency,
               "reason": row.reason, "model": row.model, "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S")}
        return out

    def reprice_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        ids = [r[0] for r in self.db.query(Product.id)
               .filter(Product.tenant_id == self.tenant_id, Product.status == "active").all()]
        repriced = []
        for pid in ids[:200]:
            try:
                r = self.suggest_price(int(pid))
                repriced.append({"product_id": pid, "suggested_price": r["suggested_price"],
                                 "margin": r["margin"], "profit": r["profit"]})
            except Exception:
                continue
        return {"repriced": repriced, "context_patch": {}}


class AdsAgent(BaseAgent):
    """广告关键词建议 / 预算优化 / ROI 报告。"""

    name = "ads"

    def _keywords_for(self, p: Product) -> list[str]:
        base = (p.title or "").lower().split()
        words = [w for w in base if len(w) > 2][:4]
        attrs = p.attrs or {}
        seeds = words + [str(attrs.get("color") or ""), p.category or ""]
        seeds = [s for s in seeds if s]
        modifiers = ["buy online", "best price", "free shipping", "2026", "wholesale", "hot sale"]
        kws = list(dict.fromkeys(seeds)) + [f"{s} {m}" for s in seeds[:4] for m in modifiers]
        return kws[:12]

    def suggest_for_product(self, product_id: int, platform: str = "facebook") -> dict:
        p = self.db.get(Product, product_id)
        if not p or p.tenant_id != self.tenant_id:
            raise ValueError(f"商品 {product_id} 不存在")
        def rule() -> dict:
            return {"keywords": self._keywords_for(p), "budget": 50.0,
                    "reason": "基于商品标题与类目的规则选词，建议日预算 50USD"}

        system = "你是跨境电商广告投放专家。只返回 JSON。"
        prompt = (f"为商品「{p.title}」（类目 {p.category}，平台 {platform}）设计广告投放方案："
                  "8-12 个投放关键词、建议日预算(USD)。"
                  "返回 JSON: {\"keywords\":[\"...\"],\"budget\":0,\"reason\":\"中文理由\"}")
        result, _mode = self.ask_json("suggest_for_product", system, prompt, fallback=rule, small_task=True)
        if not result.get("keywords"):
            result = rule()
        return {"name": f"{p.title[:24]}-{platform}广告", "platform": platform,
                "product_id": product_id, "keywords": result["keywords"],
                "budget": float(result.get("budget") or 50), "status": "draft",
                "reason": result.get("reason", "")}

    def draft_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        if params.get("product_ids"):
            ids = params["product_ids"]
        elif "published_product_ids" in context:
            ids = context["published_product_ids"]
        else:
            ids = context.get("product_ids")
        if not ids:
            ids = [r[0] for r in self.db.query(Listing.product_id)
                   .filter(Listing.tenant_id == self.tenant_id, Listing.status == "published")
                   .distinct().all()]
        platform = params.get("platform", "facebook")
        drafts = []
        for pid in ids[:20]:
            d = self.suggest_for_product(int(pid), platform)
            row = AdCampaign(tenant_id=self.tenant_id, name=d["name"], platform=platform,
                             product_id=pid, keywords=d["keywords"], budget=d["budget"], status="draft")
            self.db.add(row)
            self.db.commit()
            drafts.append({"id": row.id, "name": row.name, "platform": platform,
                           "product_id": pid, "keywords": row.keywords,
                           "budget": row.budget, "status": "draft", "reason": d["reason"]})
        return {"campaign_drafts": drafts, "context_patch": {}}

    def optimize_budget(self, campaign_id: int) -> dict:
        c = self.db.get(AdCampaign, campaign_id)
        if not c or c.tenant_id != self.tenant_id:
            raise ValueError(f"广告活动 {campaign_id} 不存在")
        roi = (c.revenue - c.spend) / c.spend if c.spend else 0
        old = c.budget
        if roi > 2:
            c.budget = min(500.0, round(old * 1.3, 2))
            action, reason = "加预算", f"ROI {roi:.2f} > 2，预算上调30%"
        elif roi < 0.8:
            c.budget = max(5.0, round(old * 0.6, 2))
            action, reason = "降预算", f"ROI {roi:.2f} < 0.8，预算下调40%"
        else:
            action, reason = "维持", f"ROI {roi:.2f} 处于健康区间"
        c.updated_at = datetime.utcnow()
        self.db.commit()
        return {"campaign_id": campaign_id, "old_budget": old, "new_budget": c.budget,
                "action": action, "reason": reason}

    def roi_report(self) -> dict:
        camps = (self.db.query(AdCampaign)
                 .filter(AdCampaign.tenant_id == self.tenant_id).all())
        items = []
        for c in camps:
            roi = round((c.revenue - c.spend) / c.spend, 2) if c.spend else 0
            ctr = round(c.clicks / c.impressions * 100, 2) if c.impressions else 0
            cvr = round(c.orders / c.clicks * 100, 2) if c.clicks else 0
            d = {"id": c.id, "name": c.name, "platform": c.platform, "product_id": c.product_id,
                 "keywords": c.keywords, "budget": c.budget, "spend": c.spend, "revenue": c.revenue,
                 "impressions": c.impressions, "clicks": c.clicks, "orders": c.orders,
                 "status": c.status, "roi": roi, "ctr": ctr, "cvr": cvr}
            items.append(d)
        spend = sum(c["spend"] for c in items)
        revenue = sum(c["revenue"] for c in items)
        clicks = sum(c["clicks"] for c in items)
        impressions = sum(c["impressions"] for c in items)
        return {"summary": {"total_spend": round(spend, 2), "total_revenue": round(revenue, 2),
                            "roi": round((revenue - spend) / spend, 2) if spend else 0,
                            "avg_ctr": round(clicks / impressions * 100, 2) if impressions else 0},
                "campaigns": items}
