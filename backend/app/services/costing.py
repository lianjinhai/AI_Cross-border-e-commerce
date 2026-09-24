"""成本与利润计算（Agent 共享的领域计算，不依赖任何 Agent）。

为什么必须独立成 service（而不是留在 ``agents/pricing.py``）：
    ``FactoryOpportunityAgent`` 需要真实利润率做门禁，原实现直接
    ``from .pricing import PricingAgent`` 再 ``PricingAgent(...).calc_profit()``
    ——这是 **Agent 之间 P2P 调用**，违反 Agent OS 架构冻结文档 §3 与规范 L-3
    （所有 Agent 协作只能由 Orchestrator 编排）。P2P 会让权限、审计、数据范围
    三道闸全部失效：被调 Agent 用自己的会话/租户上下文执行，调用方无从控制，
    Trace 也串不起来。

    修法遵循分层 ``agents/ -> tools/ -> services/``：把「成本要素 + 利润」这类
    纯领域计算下沉到 ``services/``，两个 Agent 各自调用同一份实现。
    这样既消除 P2P，又保证口径**唯一**——两处各写一遍迟早漂移（一处改了
    汇率取法、另一处没改，门禁用的利润率与定价页展示的就不是同一个数）。

调用方必须自己持有 Session 并传入 ``tenant_id``：本模块不建会话、不猜租户，
避免出现「无上下文计算」。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import ExchangeRate, Product, SupplierOffer
from . import settings_service

DEFAULT_RULES = {"min_margin": 0.15, "target_margin": 0.35,
                 "logistics_base": 18.0, "logistics_per_kg": 8.0, "ads_default": 1.5}
DEFAULT_FEES = {"shopee": 0.06, "amazon": 0.15, "shopify": 0.02,
                "ebay": 0.12, "temu": 0.05, "tiktok": 0.08}
DEFAULT_FX = {"USD": 7.12}


def setting_for(db: Session, tenant_id: int | None, key: str, default: dict) -> dict:
    """按租户读取配置（租户覆盖 → 平台默认 → 代码默认）。"""
    value = dict(default)
    value.update(settings_service.get_setting(db, tenant_id, key))
    return value


def latest_fx(db: Session, tenant_id: int, base: str, quote: str) -> float | None:
    """取最近一条生效汇率；同币种直接返回 1.0。"""
    if base == quote:
        return 1.0
    row = (db.query(ExchangeRate).filter(
        ExchangeRate.tenant_id == tenant_id,
        ExchangeRate.base_currency == base,
        ExchangeRate.quote_currency == quote,
        ExchangeRate.effective_at <= datetime.utcnow())
        .order_by(ExchangeRate.effective_at.desc()).first())
    return float(row.rate) if row else None


def to_cny(db: Session, tenant_id: int, amount: float, currency: str) -> float:
    """折算成人民币。缺汇率必须抛错（fail closed），禁止用猜测汇率算利润。"""
    currency = (currency or "CNY").upper()
    direct = latest_fx(db, tenant_id, currency, "CNY")
    if direct is not None:
        return amount * direct
    # 财务主口径通常维护兑 USD 汇率，允许通过 USD 安全交叉换算。
    base_usd = latest_fx(db, tenant_id, currency, "USD")
    cny_usd = latest_fx(db, tenant_id, "CNY", "USD")
    if base_usd is not None and cny_usd:
        return amount * base_usd / cny_usd
    raise ValueError(f"缺少 {currency}→CNY 的有效汇率，禁止计算利润")


def best_purchase(db: Session, tenant_id: int, product: Product) -> tuple[float, int | None]:
    """在库且可用的报价里取最低采购价（已折算人民币）。"""
    offers = (db.query(SupplierOffer)
              .filter(SupplierOffer.tenant_id == tenant_id,
                      SupplierOffer.product_id == product.id,
                      SupplierOffer.in_stock.is_(True))
              .all())
    converted = [(to_cny(db, tenant_id, float(o.price), o.currency), o.id) for o in offers]
    if converted:
        return min(converted, key=lambda x: x[0])
    return float((product.attrs or {}).get("supplier_price") or 10.0), None


def cost_elements(db: Session, tenant_id: int, product: Product, platform: str = "") -> dict:
    """拆出利润计算所需的全部成本要素（采购/物流/佣金率/广告/汇率）。"""
    rules = setting_for(db, tenant_id, "rules", DEFAULT_RULES)
    fees = setting_for(db, tenant_id, "platform_fees", DEFAULT_FEES)
    fx_map = setting_for(db, tenant_id, "fx", DEFAULT_FX)
    attrs = product.attrs or {}
    platform = platform or attrs.get("platform") or "shopee"
    purchase_cny, offer_id = best_purchase(db, tenant_id, product)
    weight = float(attrs.get("weight_kg") or 0.3)
    return {
        "purchase_cny": purchase_cny, "offer_id": offer_id,
        "logistics_cny": round(rules["logistics_base"] + rules["logistics_per_kg"] * weight, 2),
        "fee_rate": float(fees.get(platform, 0.06)),
        "ads_cny": float(rules["ads_default"]),
        "fx": float(fx_map.get("USD", 7.12)),
    }


def calc_profit(db: Session, tenant_id: int, product_id: int,
                price: float | None = None) -> dict:
    """真实利润 = 售价 - (采购+物流+平台佣金+广告)/汇率。"""
    product = db.get(Product, product_id)
    if not product or product.tenant_id != tenant_id:
        raise ValueError(f"商品 {product_id} 不存在")
    ce = cost_elements(db, tenant_id, product)
    price = float(price or (product.attrs or {}).get("sale_price") or 19.99)
    cost_total_cny = (ce["purchase_cny"] + ce["logistics_cny"] + ce["ads_cny"]
                      + ce["fee_rate"] * price * ce["fx"])
    profit = round(price - cost_total_cny / ce["fx"], 2)
    margin = round(profit / price, 4) if price else 0
    return {"product_id": product_id, "purchase_cost": ce["purchase_cny"],
            "logistics_cost": ce["logistics_cny"], "platform_fee_rate": ce["fee_rate"],
            "ads_cost": ce["ads_cny"], "price": price, "profit": profit,
            "margin": margin, "currency": "USD", "fx": ce["fx"]}
