"""预测结果与私域工厂机会的到期归因服务。"""
from datetime import datetime, timedelta

from ..models import (
    ForecastOutcome,
    ForecastSnapshot,
    Listing,
    OpportunityAttribution,
    OpportunitySupplierMatch,
    Order,
    PlatformSettlementRecord,
)
from .commercial_analytics import _fx_rate, metric_summary

FORECAST_SOURCES = ("api", "import")
COMMERCIAL_SOURCES = ("api", "import", "manual")


def reconcile_forecast_outcomes(db, tenant_id: int, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    snapshots = db.query(ForecastSnapshot).filter(ForecastSnapshot.tenant_id == tenant_id).all()
    evaluated, pending = [], 0
    for snapshot in snapshots:
        start = snapshot.target_start or snapshot.training_cutoff
        end = snapshot.target_end or (start + timedelta(days=7))
        if end > now:
            pending += 1
            continue
        rows = db.query(Order).filter(
            Order.tenant_id == tenant_id, Order.product_id == snapshot.product_id,
            Order.created_at >= start, Order.created_at < end,
            Order.status != "refunded", Order.source.in_(FORECAST_SOURCES)).all()
        actual = float(sum(order.qty for order in rows))
        forecast = float(snapshot.point_forecast)
        outcome = db.query(ForecastOutcome).filter(
            ForecastOutcome.snapshot_id == snapshot.id,
            ForecastOutcome.tenant_id == tenant_id).first()
        if not outcome:
            outcome = ForecastOutcome(tenant_id=tenant_id, snapshot_id=snapshot.id,
                                      product_id=snapshot.product_id)
            db.add(outcome)
        outcome.target_start, outcome.target_end = start, end
        outcome.forecast_qty, outcome.actual_qty = forecast, actual
        outcome.absolute_error = abs(forecast - actual)
        outcome.bias = (forecast - actual) / actual if actual else None
        outcome.covered = float(snapshot.lower_bound) <= actual <= float(snapshot.upper_bound)
        outcome.source_order_count = len(rows)
        outcome.evaluated_at = now
        evaluated.append(outcome)
    db.commit()
    actual_total = sum(x.actual_qty for x in evaluated)
    return {
        "evaluated": len(evaluated), "pending": pending,
        "wape": round(sum(x.absolute_error for x in evaluated) / actual_total, 4)
        if actual_total else None,
        "bias": round(sum(x.forecast_qty - x.actual_qty for x in evaluated) / actual_total, 4)
        if actual_total else None,
        "coverage": round(sum(1 for x in evaluated if x.covered) / len(evaluated), 4)
        if evaluated else None,
        "items": evaluated,
    }


def _allocated_settlement_net(db, tenant_id: int, product_id: int,
                              start: datetime, now: datetime) -> float:
    """按同店铺、同平台、同结算周期的商品 GMV 占比分摊实际到账。"""
    total = 0.0
    settlements = db.query(PlatformSettlementRecord).filter(
        PlatformSettlementRecord.tenant_id == tenant_id,
        PlatformSettlementRecord.status.in_(("paid", "settled")),
        PlatformSettlementRecord.period_end >= start,
        PlatformSettlementRecord.period_start < now).all()
    for settlement in settlements:
        period_start = max(start, settlement.period_start or start)
        period_end = min(now, settlement.period_end or now)
        base = db.query(Order).filter(
            Order.tenant_id == tenant_id, Order.platform == settlement.platform,
            Order.created_at >= period_start, Order.created_at < period_end,
            Order.source.in_(COMMERCIAL_SOURCES))
        if settlement.shop_id is not None:
            base = base.filter(Order.shop_id == settlement.shop_id)
        rows = base.all()
        converted = [(o, _fx_rate(db, tenant_id, o.currency, o.created_at)) for o in rows]
        all_gmv = sum(float(o.amount) * rate for o, rate in converted if rate is not None)
        product_gmv = sum(float(o.amount) * rate for o, rate in converted
                          if rate is not None and o.product_id == product_id)
        settlement_rate = _fx_rate(db, tenant_id, settlement.currency,
                                   settlement.paid_at or settlement.created_at)
        if all_gmv > 0 and settlement_rate is not None:
            total += float(settlement.net_amount) * settlement_rate * product_gmv / all_gmv
    return total


def reconcile_opportunity_attributions(db, tenant_id: int,
                                        now: datetime | None = None) -> list[OpportunityAttribution]:
    now = now or datetime.utcnow()
    matches = db.query(OpportunitySupplierMatch).filter(
        OpportunitySupplierMatch.tenant_id == tenant_id,
        OpportunitySupplierMatch.promoted_at.isnot(None)).all()
    results = []
    for match in matches:
        start = match.promoted_at
        listings = db.query(Listing).filter(
            Listing.tenant_id == tenant_id, Listing.product_id == match.product_id,
            Listing.created_at >= start).all()
        orders = db.query(Order).filter(
            Order.tenant_id == tenant_id, Order.product_id == match.product_id,
            Order.created_at >= start, Order.created_at < now,
            Order.source.in_(COMMERCIAL_SOURCES)).all()
        metrics = metric_summary(db, tenant_id, real_only=True, start_at=start,
                                 end_at=now, product_ids=[match.product_id])
        row = db.query(OpportunityAttribution).filter(
            OpportunityAttribution.tenant_id == tenant_id,
            OpportunityAttribution.match_id == match.id).first()
        if not row:
            row = OpportunityAttribution(tenant_id=tenant_id, match_id=match.id,
                                         product_id=match.product_id,
                                         supplier_id=match.supplier_id,
                                         attribution_start=start)
            db.add(row)
        row.listing_ids = [x.id for x in listings]
        row.order_ids = [x.id for x in orders]
        row.published_listing_count = sum(x.status == "published" for x in listings)
        row.order_count = len(orders)
        row.units = sum(x.qty for x in orders)
        row.gmv_usd = metrics["gmv"]
        row.net_revenue_usd = metrics["net_revenue"]
        row.contribution_profit_usd = metrics["contribution_profit"]
        row.settled_net_usd = round(_allocated_settlement_net(
            db, tenant_id, match.product_id, start, now), 2)
        row.refreshed_at = now
        results.append(row)
    db.commit()
    return results
