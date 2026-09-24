"""统一经营指标与数据质量门禁。所有金额当前统一为订单记账币种 USD。"""
from datetime import datetime, timedelta

from ..models import (
    AdCampaign,
    ExchangeRate,
    ForecastSnapshot,
    Order,
    OrderFee,
    OrderLine,
    Product,
    PurchaseOrder,
    RefundOrder,
)

METRIC_DEFINITIONS = {
    "gmv": "可信订单退款前成交额合计；退款仅在净收入中扣减",
    "net_revenue": "GMV - 已完成退款金额",
    "contribution_profit": "净收入 - 商品成本 - 平台/支付/税费/物流/仓储等订单费用 - 广告花费",
    "roas": "广告归因收入 / 广告花费",
    "roi": "(广告归因收入 - 广告花费) / 广告花费",
    "refund_rate": "已退款订单数 / 全部订单数",
}


def _fx_rate(db, tenant_id: int, currency: str, at: datetime,
             quote: str = "USD") -> float | None:
    currency, quote = (currency or quote).upper(), quote.upper()
    if currency == quote:
        return 1.0
    row = (db.query(ExchangeRate).filter(
        ExchangeRate.tenant_id == tenant_id,
        ExchangeRate.base_currency == currency,
        ExchangeRate.quote_currency == quote,
        ExchangeRate.effective_at <= at)
        .order_by(ExchangeRate.effective_at.desc()).first())
    return float(row.rate) if row else None


def metric_summary(db, tenant_id: int, days: int = 30, real_only: bool = True,
                   start_at: datetime | None = None, end_at: datetime | None = None,
                   product_ids: list[int] | None = None) -> dict:
    """唯一经营口径入口。

    默认按最近 ``days`` 天统计；内部调用方可传半开区间 ``[start_at, end_at)``，
    以保证驾驶舱、趋势和经营报告不会再各自重复一套计算。
    """
    cutoff = start_at or (datetime.utcnow() - timedelta(days=days))
    q = db.query(Order).filter(Order.tenant_id == tenant_id, Order.created_at >= cutoff)
    if end_at is not None:
        q = q.filter(Order.created_at < end_at)
    if product_ids is not None:
        q = q.filter(Order.product_id.in_(product_ids))
    if real_only:
        q = q.filter(Order.source.in_(("api", "import", "manual")))
    rows = q.all()
    converted, missing_fx = {}, []
    for order in rows:
        rate = _fx_rate(db, tenant_id, order.currency, order.created_at)
        if rate is None:
            missing_fx.append({"order_id": order.id, "currency": order.currency,
                               "created_at": order.created_at.isoformat() + "Z"})
        else:
            converted[order.id] = rate
    # GMV 保留退款前成交额，退款仅在净收入中扣减，避免 refunded 订单被先
    # 排除、随后又扣退款事实而发生双减。
    trusted_orders = [o for o in rows if o.id in converted]
    gmv = sum(float(o.amount) * converted[o.id] for o in trusted_orders)
    order_ids = [o.id for o in rows]
    refunds = (db.query(RefundOrder).filter(RefundOrder.tenant_id == tenant_id,
                RefundOrder.order_id.in_(order_ids), RefundOrder.status == "refunded").all()
               if order_ids else [])
    refund_amount = sum(float(r.amount) * converted.get(r.order_id, 0) for r in refunds)
    lines = (db.query(OrderLine).filter(OrderLine.tenant_id == tenant_id,
             OrderLine.order_id.in_(list(converted))).all() if converted else [])
    line_orders = {line.order_id for line in lines}
    line_cost = sum(float(line.product_cost) * line.qty *
                    (_fx_rate(db, tenant_id, line.currency, line.created_at) or 0) for line in lines)
    legacy_cost = sum(float(o.cost) * converted[o.id] for o in trusted_orders
                      if o.id not in line_orders)
    product_cost = line_cost + legacy_cost
    fees = (db.query(OrderFee).filter(OrderFee.tenant_id == tenant_id,
            OrderFee.order_id.in_(list(converted))).all() if converted else [])
    fee_by_type = {}
    missing_fee_fx = []
    for fee in fees:
        rate = _fx_rate(db, tenant_id, fee.currency, fee.occurred_at)
        if rate is None:
            missing_fee_fx.append({"fee_id": fee.id, "currency": fee.currency})
            continue
        fee_by_type[fee.fee_type] = fee_by_type.get(fee.fee_type, 0.0) + float(fee.amount) * rate
    fee_total = sum(fee_by_type.values())
    net = gmv - refund_amount
    ads_q = db.query(AdCampaign).filter(AdCampaign.tenant_id == tenant_id,
                                       AdCampaign.created_at >= cutoff)
    if end_at is not None:
        ads_q = ads_q.filter(AdCampaign.created_at < end_at)
    if product_ids is not None:
        ads_q = ads_q.filter(AdCampaign.product_id.in_(product_ids))
    ads = ads_q.all()
    spend = sum(a.spend for a in ads); ad_revenue = sum(a.revenue for a in ads)
    contribution = net - product_cost - fee_total - spend
    return {"period_days": days, "scope": "real_only" if real_only else "all_sources",
            "currency": "USD", "gmv": round(gmv, 2), "refund_amount": round(refund_amount, 2),
            "net_revenue": round(net, 2), "order_cost": round(product_cost, 2),
            "order_fees": round(fee_total, 2),
            "fee_breakdown": {k: round(v, 2) for k, v in fee_by_type.items()},
            "ad_spend": round(spend, 2), "contribution_profit": round(contribution, 2),
            "contribution_margin": round(contribution / net, 4) if net else None,
            "roas": round(ad_revenue / spend, 4) if spend else None,
            "roi": round((ad_revenue - spend) / spend, 4) if spend else None,
            "refund_rate": round(len([o for o in rows if o.status == "refunded"]) / len(rows), 4) if rows else None,
            "orders": len(rows), "trusted_orders": len(converted),
            "excluded_orders_missing_fx": missing_fx, "excluded_fees_missing_fx": missing_fee_fx,
            "definitions": METRIC_DEFINITIONS,
            "as_of": datetime.utcnow().isoformat(timespec="seconds") + "Z"}


def quality_report(db, tenant_id: int) -> dict:
    orders = db.query(Order).filter(Order.tenant_id == tenant_id).all()
    products = db.query(Product).filter(Product.tenant_id == tenant_id).all()
    ads = db.query(AdCampaign).filter(AdCampaign.tenant_id == tenant_id).all()
    purchases = db.query(PurchaseOrder).filter(PurchaseOrder.tenant_id == tenant_id).all()
    lines = db.query(OrderLine).filter(OrderLine.tenant_id == tenant_id).all()
    fees = db.query(OrderFee).filter(OrderFee.tenant_id == tenant_id).all()
    duplicate_orders = len(orders) - len({(o.shop_id, o.platform, o.external_no) for o in orders})
    invalid_orders = sum(o.amount < 0 or o.qty <= 0 or o.status not in
                         ("pending", "paid", "shipped", "delivered", "refunded") for o in orders)
    orphan_orders = sum(o.product_id is not None and not any(p.id == o.product_id for p in products)
                        for o in orders)
    missing_fx = sum(_fx_rate(db, tenant_id, o.currency, o.created_at) is None for o in orders)
    line_totals = {}
    for line in lines:
        line_totals[line.order_id] = line_totals.get(line.order_id, 0) + float(line.unit_price) * line.qty
    line_mismatch = sum(abs(line_totals[o.id] - float(o.amount)) > 0.02
                        for o in orders if o.id in line_totals)
    checks = [
        {"dataset": "orders", "check": "shop+platform+external_no uniqueness", "failed": duplicate_orders},
        {"dataset": "orders", "check": "amount/qty/status validity", "failed": invalid_orders},
        {"dataset": "orders", "check": "product referential integrity", "failed": orphan_orders},
        {"dataset": "orders", "check": "daily FX available", "failed": missing_fx},
        {"dataset": "order_lines", "check": "line total reconciles to order", "failed": line_mismatch},
        {"dataset": "order_fees", "check": "valid fee type/currency", "failed":
         sum(not f.fee_type or not f.currency for f in fees)},
        {"dataset": "products", "check": "sku/title required", "failed": sum(not p.sku or not p.title for p in products)},
        {"dataset": "ads", "check": "non-negative spend/revenue", "failed": sum(a.spend < 0 or a.revenue < 0 for a in ads)},
        {"dataset": "purchases", "check": "positive qty/unit price", "failed": sum(p.qty <= 0 or p.unit_price < 0 for p in purchases)},
    ]
    max_date = max((o.updated_at or o.created_at for o in orders), default=None)
    freshness_hours = ((datetime.utcnow() - max_date).total_seconds() / 3600) if max_date else None
    source_counts = {s: sum(o.source == s for o in orders) for s in ("api", "import", "manual", "demo", "seed")}
    failures = sum(c["failed"] for c in checks)
    real_count = sum(source_counts[s] for s in ("api", "import", "manual"))
    grade = "high" if failures == 0 and real_count >= 100 and (freshness_hours or 999) <= 24 else (
            "medium" if failures == 0 and real_count >= 20 else "low")
    return {"grade": grade, "commercial_ready": grade in ("high", "medium"),
            "checks": checks, "source_counts": source_counts,
            "freshness_hours": round(freshness_hours, 2) if freshness_hours is not None else None,
            "real_order_count": real_count, "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z"}


def forecast_monitoring(db, tenant_id: int) -> dict:
    rows = (db.query(ForecastSnapshot).filter(ForecastSnapshot.tenant_id == tenant_id)
            .order_by(ForecastSnapshot.created_at.desc()).limit(5000).all())
    groups = {}
    for row in rows:
        dims = row.dimensions or {}
        key = (dims.get("sku", "unknown"), dims.get("platform", "unknown"),
               dims.get("country", "unknown"))
        groups.setdefault(key, []).append(row)
    items = []
    for (sku, platform, country), values in groups.items():
        valid = [v for v in values if v.wape is not None]
        items.append({"sku": sku, "platform": platform, "country": country,
                      "snapshots": len(values), "coverage": round(len(valid) / len(values), 4),
                      "wape": round(sum(v.wape for v in valid) / len(valid), 4) if valid else None,
                      "bias": round(sum(v.bias or 0 for v in valid) / len(valid), 4) if valid else None,
                      "latest_confidence": values[0].confidence,
                      "latest_cutoff": values[0].training_cutoff.isoformat() + "Z"})
    covered = [i for i in items if i["wape"] is not None]
    summary = {"segments": len(items),
            "forecast_coverage": round(len(covered) / len(items), 4) if items else 0,
            "wape": round(sum(i["wape"] for i in covered) / len(covered), 4) if covered else None,
            "bias": round(sum(i["bias"] for i in covered) / len(covered), 4) if covered else None}
    real_orders = db.query(Order).filter(Order.tenant_id == tenant_id,
                                         Order.source.in_(("api", "import"))).count()
    checks = {"real_orders": real_orders >= 100,
              "wape": summary["wape"] is not None and summary["wape"] <= 0.30,
              "bias": summary["bias"] is not None and abs(summary["bias"]) <= 0.20,
              "coverage": summary["forecast_coverage"] >= 0.80}
    return {"items": items, "summary": summary,
            "commercial_gate": {"passed": all(checks.values()), "checks": checks,
                                "actual_real_orders": real_orders, "min_real_orders": 100,
                                "max_wape": 0.30, "max_abs_bias": 0.20, "min_coverage": 0.80,
                                "label": "商用通过" if all(checks.values()) else "未达商用门槛"}}
