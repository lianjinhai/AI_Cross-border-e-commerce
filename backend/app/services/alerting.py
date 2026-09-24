"""主动巡检服务（M3）：系统定时发现经营风险并告警。

设计红线（方案 §4.4-1）：**只告警不执行** —— 巡检只写 AlertEvent，
绝不自动改价/下架/补货，决策权始终在人。

九条规则（覆盖库存/广告/售后/内容/供应链/定价/政策/汇率/物流）：
  stockout_risk / ads_burning / refund_spike / listing_stale / supplier_delay
  / price_below_floor / policy_changed / fx_volatility / shipping_degraded
"""
from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import (
    AdCampaign,
    AlertEvent,
    AlertRule,
    ExchangeRate,
    Listing,
    Order,
    PlatformRulePack,
    Product,
    RefundOrder,
    Supplier,
    SupplierOffer,
    utcnow,
)

# 默认规则集（阈值可被 AlertRule.threshold 覆盖）
DEFAULT_RULES = [
    {"key": "stockout_risk", "name": "库存断货风险", "level": "high",
     "threshold": {"weeks": 1}, "description": "周需求超过在手库存，即将断货"},
    {"key": "ads_burning", "name": "广告亏损烧钱", "level": "high",
     "threshold": {"max_roi": 0.5, "min_spend": 100}, "description": "广告 ROI 过低且已投入较大"},
    {"key": "price_below_floor", "name": "售价低于成本", "level": "high",
     "threshold": {}, "description": "当前售价低于采购+物流成本，每单亏损"},
    {"key": "policy_changed", "name": "平台政策变更", "level": "high",
     "threshold": {"days": 30}, "description": "平台规则包近期有更新，需复核在售 Listing"},
    {"key": "refund_spike", "name": "退款率异常", "level": "mid",
     "threshold": {"max_rate": 0.15, "days": 7}, "description": "近 7 天退款率超过阈值"},
    {"key": "supplier_delay", "name": "供应商发货延迟", "level": "mid",
     "threshold": {"max_days": 10}, "description": "供应商平均发货时效超过阈值"},
    {"key": "fx_volatility", "name": "汇率剧烈波动", "level": "mid",
     "threshold": {"max_change": 0.05, "days": 7}, "description": "汇率波动影响利润测算"},
    {"key": "shipping_degraded", "name": "物流时效恶化", "level": "mid",
     "threshold": {"grace_days": 3}, "description": "实际发货超出承诺时效"},
    {"key": "listing_stale", "name": "Listing 长期未优化", "level": "low",
     "threshold": {"days": 30}, "description": "已发布 Listing 超过阈值天数未优化"},
]

_LEVEL_ORDER = {"high": 0, "mid": 1, "low": 2}


def ensure_default_rules(db: Session, tenant_id: int) -> int:
    """为租户初始化默认规则（幂等：已存在则跳过）。"""
    existing = {r.key for r in db.query(AlertRule.key)
                .filter(AlertRule.tenant_id == tenant_id).all()}
    added = 0
    for spec in DEFAULT_RULES:
        if spec["key"] in existing:
            continue
        db.add(AlertRule(tenant_id=tenant_id, key=spec["key"], name=spec["name"],
                         level=spec["level"], threshold=spec["threshold"],
                         description=spec["description"]))
        added += 1
    if added:
        db.commit()
    return added


def _rule_map(db: Session, tenant_id: int) -> dict[str, AlertRule]:
    return {r.key: r for r in db.query(AlertRule)
            .filter(AlertRule.tenant_id == tenant_id).all()}


def _emit(db: Session, tenant_id: int, rule: AlertRule, subject_type: str,
          subject_id: int, title: str, detail: str, evidence: dict,
          dedupe_hours: int = 24, seen: set | None = None) -> bool:
    """写入告警（同规则同对象在去重窗口内不重复）。返回是否新建。

    去重键 = (rule_key, subject_type, subject_id)。两道防线缺一不可：
      1. ``seen``（本轮内存集合）：SessionLocal 是 autoflush=False，本轮已
         ``add`` 但未 flush 的告警对 ``db.query`` 不可见——只查库时同一轮里
         同一对象的第 2 次触发会重复入库（实测：同一供应商 2 条报价产生 2 条
         相同告警）。
      2. 库查询：跨轮次/跨进程的去重窗口。

    subject_type 约定：对象主键是整数时用纯类型名（product/supplier/...）；
    主键是自然键（字符串）时用 ``<类型>:<自然键>``，例如 ``platform:shopee``、
    ``currency:CNY``。若这类对象把 subject_id 写死为 0，不同自然键会共用同一
    去重键而互相抑制（漏报）。
    """
    token = (rule.key, subject_type, subject_id)
    if seen is not None and token in seen:
        return False
    since = utcnow() - timedelta(hours=dedupe_hours)
    dup = (db.query(AlertEvent)
           .filter(AlertEvent.tenant_id == tenant_id, AlertEvent.rule_key == rule.key,
                   AlertEvent.subject_type == subject_type,
                   AlertEvent.subject_id == subject_id,
                   AlertEvent.created_at >= since).first())
    if dup:
        if seen is not None:
            seen.add(token)
        return False
    db.add(AlertEvent(tenant_id=tenant_id, rule_key=rule.key, level=rule.level,
                      subject_type=subject_type, subject_id=subject_id,
                      title=title, detail=detail, evidence=evidence, status="open"))
    if seen is not None:
        seen.add(token)
    return True


def _weekly_demand(db: Session, tenant_id: int, product_id: int) -> float:
    """近 28 天真实订单的周均销量。"""
    since = utcnow() - timedelta(days=28)
    units = (db.query(func.sum(Order.qty))
             .filter(Order.tenant_id == tenant_id, Order.product_id == product_id,
                     Order.created_at >= since, Order.status != "refunded",
                     Order.source.in_(("api", "import", "manual"))).scalar() or 0)
    return float(units) / 4.0


def scan(db: Session, tenant_id: int) -> dict:
    """执行一轮巡检，返回 {created, skipped, by_rule}。只告警不执行。"""
    ensure_default_rules(db, tenant_id)
    rules = _rule_map(db, tenant_id)
    created, skipped = 0, 0
    by_rule: dict[str, int] = {}
    # 本轮已产生的去重键：SessionLocal 是 autoflush=False，仅靠查库无法拦住
    # 同一轮内的重复触发（见 _emit 文档）。
    seen: set = set()

    def fire(key: str, subject_type: str, subject_id: int, title: str,
             detail: str, evidence: dict) -> None:
        nonlocal created, skipped
        rule = rules.get(key)
        if not rule or not rule.enabled:
            return
        if _emit(db, tenant_id, rule, subject_type, subject_id, title, detail,
                 evidence, seen=seen):
            created += 1
            by_rule[key] = by_rule.get(key, 0) + 1
        else:
            skipped += 1

    # 1) 库存断货风险
    rule = rules.get("stockout_risk")
    if rule and rule.enabled:
        # 两个阈值都必须可配（此前「建议补货量」硬编码 4 周，改阈值不生效）：
        #   weeks       触发线：在手库存可支撑的周数低于该值即告警（默认 1 周）
        #   cover_weeks 备货目标：建议补货到可支撑的周数（默认 4 周）
        trigger_weeks = max(1, int(rule.threshold.get("weeks", 1) or 1))
        cover_weeks = max(trigger_weeks, int(rule.threshold.get("cover_weeks", 4) or 4))
        for p in db.query(Product).filter(Product.tenant_id == tenant_id,
                                          Product.status == "active").all():
            demand = _weekly_demand(db, tenant_id, p.id)
            if demand <= 0:
                continue
            onhand = float((p.attrs or {}).get("onhand") or 0)
            if onhand < demand * trigger_weeks:
                fire("stockout_risk", "product", p.id,
                     f"库存断货风险：{p.title[:30]}",
                     f"周需求 {demand:.1f} 件，在手 {onhand:.0f} 件，"
                     f"按 {cover_weeks} 周备货建议补货 "
                     f"{max(0, int(demand * cover_weeks - onhand))} 件",
                     {"weekly_demand": round(demand, 1), "onhand": onhand,
                      "trigger_weeks": trigger_weeks, "cover_weeks": cover_weeks})

    # 2) 广告亏损烧钱
    rule = rules.get("ads_burning")
    if rule and rule.enabled:
        max_roi = float(rule.threshold.get("max_roi", 0.5))
        min_spend = float(rule.threshold.get("min_spend", 100))
        for c in db.query(AdCampaign).filter(AdCampaign.tenant_id == tenant_id,
                                             AdCampaign.status == "running").all():
            if c.spend < min_spend:
                continue
            roi = (c.revenue - c.spend) / c.spend if c.spend else 0
            if roi < max_roi:
                fire("ads_burning", "campaign", c.id,
                     f"广告亏损：{c.name[:30]}",
                     f"ROI {roi:.2f}（低于 {max_roi}），已花费 ${c.spend:.2f}，收入 ${c.revenue:.2f}",
                     {"roi": round(roi, 2), "spend": c.spend, "revenue": c.revenue})

    # 3) 售价低于成本
    rule = rules.get("price_below_floor")
    if rule and rule.enabled:
        for p in db.query(Product).filter(Product.tenant_id == tenant_id,
                                          Product.status == "active").all():
            attrs = p.attrs or {}
            price = float(attrs.get("sale_price") or 0)
            if price <= 0:
                continue
            offer = (db.query(SupplierOffer)
                     .filter(SupplierOffer.tenant_id == tenant_id,
                             SupplierOffer.product_id == p.id,
                             SupplierOffer.in_stock.is_(True))
                     .order_by(SupplierOffer.price).first())
            cost_cny = float(offer.price if offer else attrs.get("supplier_price") or 0)
            if cost_cny <= 0:
                continue
            weight = float(attrs.get("weight_kg") or 0.3)
            logistics_cny = 18 + 8 * weight
            cost_usd = (cost_cny + logistics_cny) / 7.12
            if price < cost_usd:
                fire("price_below_floor", "product", p.id,
                     f"售价低于成本：{p.title[:30]}",
                     f"售价 ${price:.2f} < 成本 ${cost_usd:.2f}（采购 ¥{cost_cny:.2f} + 物流 ¥{logistics_cny:.2f}），每单亏损 ${cost_usd - price:.2f}",
                     {"price": price, "cost_usd": round(cost_usd, 2),
                      "purchase_cny": cost_cny, "logistics_cny": logistics_cny})

    # 4) 平台政策变更（规则包近期更新）
    rule = rules.get("policy_changed")
    if rule and rule.enabled:
        days = int(rule.threshold.get("days", 30))
        since = utcnow() - timedelta(days=days)
        for pack in db.query(PlatformRulePack).filter(
                PlatformRulePack.updated_at >= since).all():
            fire("policy_changed", f"platform:{pack.platform}", 0,
                 f"平台规则更新：{pack.platform}",
                 f"{pack.platform} 规则包更新至 {pack.version}（{pack.updated_at:%Y-%m-%d}），"
                 f"建议复核在售 Listing 合规性",
                 {"platform": pack.platform, "version": pack.version,
                  "source_url": pack.source_url})

    # 5) 退款率异常
    rule = rules.get("refund_spike")
    if rule and rule.enabled:
        max_rate = float(rule.threshold.get("max_rate", 0.15))
        days = int(rule.threshold.get("days", 7))
        since = utcnow() - timedelta(days=days)
        total = (db.query(func.count(Order.id))
                 .filter(Order.tenant_id == tenant_id, Order.created_at >= since,
                         Order.source.in_(("api", "import", "manual"))).scalar() or 0)
        if total >= 5:
            refunded = (db.query(func.count(RefundOrder.id))
                        .filter(RefundOrder.tenant_id == tenant_id,
                                RefundOrder.created_at >= since,
                                RefundOrder.status == "refunded").scalar() or 0)
            rate = refunded / total
            if rate > max_rate:
                fire("refund_spike", "tenant", tenant_id,
                     f"退款率异常：近 {days} 天 {rate * 100:.1f}%",
                     f"近 {days} 天 {total} 单中 {refunded} 单退款（{rate * 100:.1f}%），"
                     f"高于阈值 {max_rate * 100:.0f}%，建议排查商品质量与描述一致性",
                     {"refund_rate": round(rate, 4), "orders": total, "refunded": refunded})

    # 6) 供应商发货延迟
    rule = rules.get("supplier_delay")
    if rule and rule.enabled:
        max_days = int(rule.threshold.get("max_days", 10))
        for s in db.query(Supplier).filter(Supplier.tenant_id == tenant_id).all():
            if s.ship_days > max_days:
                fire("supplier_delay", "supplier", s.id,
                     f"发货延迟：{s.name[:30]}",
                     f"平均发货 {s.ship_days} 天（阈值 {max_days} 天），影响履约时效与买家体验",
                     {"ship_days": s.ship_days, "max_days": max_days})

    # 7) 汇率剧烈波动
    rule = rules.get("fx_volatility")
    if rule and rule.enabled:
        max_change = float(rule.threshold.get("max_change", 0.05))
        days = int(rule.threshold.get("days", 7))
        since = utcnow() - timedelta(days=days)
        rows = (db.query(ExchangeRate)
                .filter(ExchangeRate.tenant_id == tenant_id,
                        ExchangeRate.effective_at >= since)
                .order_by(ExchangeRate.effective_at).all())
        by_ccy: dict[str, list[float]] = {}
        for r in rows:
            by_ccy.setdefault(r.quote_currency, []).append(float(r.rate))
        for ccy, series in by_ccy.items():
            if len(series) < 2 or series[0] <= 0:
                continue
            change = abs(series[-1] - series[0]) / series[0]
            if change > max_change:
                fire("fx_volatility", f"currency:{ccy}", 0,
                     f"汇率波动：{ccy} 近 {days} 天变动 {change * 100:.1f}%",
                     f"{ccy} 从 {series[0]:.4f} 变动至 {series[-1]:.4f}"
                     f"（{change * 100:.1f}%），建议复核定价与利润测算",
                     {"currency": ccy, "from": series[0], "to": series[-1],
                      "change": round(change, 4)})

    # 8) 物流时效恶化（报价承诺 vs 供应商实际）
    rule = rules.get("shipping_degraded")
    if rule and rule.enabled:
        grace = int(rule.threshold.get("grace_days", 3))
        rows = (db.query(SupplierOffer, Supplier)
                .join(Supplier, Supplier.id == SupplierOffer.supplier_id)
                .filter(SupplierOffer.tenant_id == tenant_id).all())
        for offer, sup in rows:
            if offer.ship_days > sup.ship_days + grace:
                fire("shipping_degraded", "supplier", sup.id,
                     f"物流时效恶化：{sup.name[:30]}",
                     f"商品 #{offer.product_id} 实际发货 {offer.ship_days} 天，"
                     f"超出供应商承诺 {sup.ship_days} 天 + 宽限 {grace} 天",
                     {"product_id": offer.product_id, "offer_ship_days": offer.ship_days,
                      "promised_days": sup.ship_days})

    # 9) Listing 长期未优化
    rule = rules.get("listing_stale")
    if rule and rule.enabled:
        days = int(rule.threshold.get("days", 30))
        cutoff = utcnow() - timedelta(days=days)
        stale = (db.query(Listing)
                 .filter(Listing.tenant_id == tenant_id, Listing.status == "published",
                         Listing.updated_at < cutoff).all())
        for lst in stale:
            fire("listing_stale", "listing", lst.id,
                 f"Listing 长期未优化：#{lst.id}",
                 f"已发布 {days} 天以上未优化（最后更新 {lst.updated_at:%Y-%m-%d}），"
                 f"建议用 AI 优化标题与关键词",
                 {"listing_id": lst.id, "platform": lst.platform,
                  "updated_at": lst.updated_at.strftime("%Y-%m-%d")})

    db.commit()
    return {"created": created, "skipped": skipped, "by_rule": by_rule,
            "scanned_at": utcnow().strftime("%Y-%m-%d %H:%M:%S")}


def alert_total(db: Session, tenant_id: int, status: str = "",
                level: str = "") -> int:
    """符合条件的告警**总数**（不受 limit 影响，供分页使用）。"""
    q = db.query(func.count(AlertEvent.id)).filter(AlertEvent.tenant_id == tenant_id)
    if status:
        q = q.filter(AlertEvent.status == status)
    if level:
        q = q.filter(AlertEvent.level == level)
    return int(q.scalar() or 0)


def alert_counts(db: Session, tenant_id: int) -> dict:
    """按级别与状态统计告警数（用于看板卡片）。

    为什么单独聚合而不是数列表长度：列表有 limit 上限，用它统计会在告警多时
    少算（KPI 卡片显示"低风险 100"而库里其实有 300 条）。
    """
    counts = {"high": 0, "mid": 0, "low": 0, "open": 0}
    for level, total in (db.query(AlertEvent.level, func.count(AlertEvent.id))
                         .filter(AlertEvent.tenant_id == tenant_id)
                         .group_by(AlertEvent.level).all()):
        counts[level] = counts.get(level, 0) + int(total or 0)
    counts["open"] = int(
        db.query(func.count(AlertEvent.id))
        .filter(AlertEvent.tenant_id == tenant_id, AlertEvent.status == "open")
        .scalar() or 0)
    return counts


def list_alerts(db: Session, tenant_id: int, status: str = "",
                level: str = "", limit: int = 100) -> list[AlertEvent]:
    q = db.query(AlertEvent).filter(AlertEvent.tenant_id == tenant_id)
    if status:
        q = q.filter(AlertEvent.status == status)
    if level:
        q = q.filter(AlertEvent.level == level)
    # 级别排序必须下推到 SQL，再截断 limit。
    # 反例（实测）：先按时间取 100 条再在 Python 里按级别排，当库里有 120 条
    # 新低风险告警 + 1 条较早的高风险告警时，高风险会被 limit 挡在结果之外——
    # 用户只看到"低风险"，最该处理的风险反而漏报。
    level_rank = case(
        *[(AlertEvent.level == lv, rank) for lv, rank in _LEVEL_ORDER.items()],
        else_=9,
    )
    rows = (q.order_by(level_rank, AlertEvent.created_at.desc(), AlertEvent.id.desc())
            .limit(max(1, min(500, int(limit or 100)))).all())
    return rows


def ack_alert(db: Session, tenant_id: int, alert_id: int) -> AlertEvent | None:
    row = db.get(AlertEvent, alert_id)
    if not row or row.tenant_id != tenant_id:
        return None
    row.status = "acked"
    row.acked_at = datetime.utcnow()
    db.commit()
    return row
