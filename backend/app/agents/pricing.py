"""定价 Agent（真实利润/动态定价，第十一章）与广告增长 Agent（第十二章）。"""
from datetime import datetime

from ..models import (
    AdCampaign,
    Listing,
    PricingRecord,
    Product,
    ProductScore,
)
from ..services import costing
from .base import BaseAgent
from .contracts import CONTRACTS

# 口径唯一来源：成本/利润实现已下沉到 services/costing.py（见该模块文档说明的
# L-3 红线背景）。此处保留同名别名，避免存量调用方与测试因改名而失效。
_DEFAULT_RULES = costing.DEFAULT_RULES
_DEFAULT_FEES = costing.DEFAULT_FEES
_DEFAULT_FX = costing.DEFAULT_FX


def _setting(db, key: str, default: dict) -> dict:
    """兼容旧调用：无租户上下文时按平台级读取（保留供非租户场景使用）。"""
    return costing.setting_for(db, None, key, default)


def _setting_for(db, tenant_id: int, key: str, default: dict) -> dict:
    """按租户读取配置（租户覆盖 → 平台默认 → 代码默认）。"""
    return costing.setting_for(db, tenant_id, key, default)


class PricingAgent(BaseAgent):
    """真实利润 = 售价 - (采购+物流+平台佣金+广告)/汇率。"""

    name = "pricing"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["finance_intelligence"]

    # ---------- 成本要素 ----------
    def _latest_fx(self, base: str, quote: str) -> float | None:
        return costing.latest_fx(self.db, self.tenant_id, base, quote)

    def _to_cny(self, amount: float, currency: str) -> float:
        return costing.to_cny(self.db, self.tenant_id, amount, currency)

    def _best_purchase(self, product: Product) -> tuple[float, int | None]:
        return costing.best_purchase(self.db, self.tenant_id, product)

    def cost_elements(self, product: Product, platform: str = "") -> dict:
        return costing.cost_elements(self.db, self.tenant_id, product, platform)

    # ---------- 利润计算 ----------
    def calc_profit(self, product_id: int, price: float | None = None) -> dict:
        return costing.calc_profit(self.db, self.tenant_id, product_id, price)

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
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["operation_optimization"]

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
