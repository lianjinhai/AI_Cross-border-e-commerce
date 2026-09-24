"""商品真实经营表现聚合（M1 选品数据飞轮）。

设计红线（方案 §4.4-3）：只统计真实来源订单（api/import/manual），
演示数据（seed/demo）不得进入飞轮——否则 AI 学的是假数据。
"""
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Order, Product, ProductPerformance, RefundOrder, utcnow

# 与 commercial_analytics 保持同一口径：演示数据不进经营分析
_REAL_SOURCES = ("api", "import", "manual")
_CACHE_HOURS = 6  # 表现分缓存有效期
_WINDOW_MIN, _WINDOW_MAX = 1, 365  # 统计窗口边界（防负数/超大值拖垮聚合）


class ProductNotFound(Exception):
    """商品不存在或不属于该租户（调用方翻译成 404，不泄漏他租户是否存在）。"""


def _assert_owned(db: Session, tenant_id: int, product_id: int) -> Product:
    """校验商品归属：跨租户读取必须拒绝。

    为什么在服务层校验而不是只在路由：``get_performance`` 会被路由与 Agent
    两条路径调用，只在路由校验会漏掉 Agent 路径；且本函数会**写入**
    product_performances（含 tenant_id），不校验归属会把他人商品的数据
    缓存进本租户，形成跨租户数据污染。
    """
    p = db.get(Product, product_id)
    if not p or p.tenant_id != tenant_id:
        raise ProductNotFound(f"商品不存在: {product_id}")
    return p


def _window_metrics(db: Session, tenant_id: int, product_id: int,
                    window_days: int) -> dict:
    """窗口内全部打分输入：订单数/销量/销售额/利润/退款单数/在手库存。

    退款单数必须单列：部分退款（refund qty < order qty）**不改订单状态**，
    订单侧的 销量/销售额/利润 三项完全不变，只看它们会让退款率陈旧。
    在手库存同理——收货入库或退货入库会改变售罄率。
    """
    since = utcnow() - timedelta(days=window_days)
    q = (db.query(func.sum(Order.qty), func.sum(Order.amount), func.sum(Order.profit),
                  func.count(Order.id))
         .filter(Order.tenant_id == tenant_id, Order.product_id == product_id,
                 Order.created_at >= since, Order.source.in_(_REAL_SOURCES),
                 Order.status != "refunded").first())
    refunded = (db.query(func.count(RefundOrder.id))
                .join(Order, Order.id == RefundOrder.order_id)
                .filter(RefundOrder.tenant_id == tenant_id,
                        Order.product_id == product_id,
                        RefundOrder.created_at >= since,
                        RefundOrder.status == "refunded").scalar() or 0)
    p = db.get(Product, product_id)
    onhand = float((p.attrs or {}).get("onhand") or 0) if p else 0.0
    return {"order_count": int(q[3] or 0), "units": int(q[0] or 0),
            "revenue": round(float(q[1] or 0), 2), "profit": round(float(q[2] or 0), 2),
            "refunded": int(refunded), "onhand": onhand}


def _derive(m: dict) -> dict:
    """由原始指标推导出全部落库字段（纯函数，便于缓存比对）。

    performance_score = 归一化(售罄率 40% + 毛利率 35% + (1-退款率) 25%)
    """
    units, revenue, profit = m["units"], m["revenue"], m["profit"]
    order_count, onhand = m["order_count"], m["onhand"]
    margin = round(profit / revenue, 4) if revenue else 0.0
    refund_rate = round(min(1.0, m["refunded"] / order_count), 4) if order_count else 0.0
    sell_through = round(units / (units + onhand), 4) if (units + onhand) > 0 else 0.0
    margin_norm = max(0.0, min(1.0, margin / 0.5))       # 毛利率 50% 视为满分
    score = round(100 * (0.40 * sell_through + 0.35 * margin_norm
                         + 0.25 * (1 - refund_rate)), 1)
    return {"units_sold": units, "revenue": revenue, "profit": profit,
            "margin": margin, "refund_rate": refund_rate,
            "sell_through": sell_through, "performance_score": score}


def compute_performance(db: Session, tenant_id: int, product_id: int,
                        window_days: int = 30, force: bool = False) -> dict:
    """计算单个商品的真实经营表现。

    performance_score = 归一化(售罄率 40% + 毛利率 35% + (1-退款率) 25%)
    无真实订单的新品返回中性分 50（不惩罚新品，也不虚高）。
    """
    window_days = max(_WINDOW_MIN, min(_WINDOW_MAX, int(window_days or 30)))
    _assert_owned(db, tenant_id, product_id)
    metrics = _window_metrics(db, tenant_id, product_id, window_days)
    fresh = _derive(metrics)
    if not force:
        cached = (db.query(ProductPerformance)
                  .filter(ProductPerformance.tenant_id == tenant_id,
                          ProductPerformance.product_id == product_id,
                          ProductPerformance.window_days == window_days)
                  .order_by(ProductPerformance.computed_at.desc()).first())
        if cached and (utcnow() - cached.computed_at) < timedelta(hours=_CACHE_HOURS):
            # 缓存有效性 = 「重算结果与缓存一致」。
            #
            # 为什么比「全部落库字段」而不是挑几个当指纹：任何影响输出的输入
            # 变化都必须让缓存失效，而输入维度会随规则演进增加（已踩过两次：
            # ① 只比「有无订单」→ 5 单变 25 单不失效；② 只比 销量/销售额/利润
            # → 部分退款不改订单状态，退款率陈旧）。直接比结果集最稳，
            # 新增维度无需再改这里。聚合查询本身很轻（走 tenant+product 索引）。
            if all(abs(getattr(cached, k) - v) < 1e-9 for k, v in fresh.items()):
                out = _to_dict(cached)
                out["has_data"] = metrics["order_count"] > 0
                return out

    if metrics["order_count"] == 0:
        # 新品/无真实销售：中性分，且明确标记无数据（前端可识别）
        row = ProductPerformance(tenant_id=tenant_id, product_id=product_id,
                                 window_days=window_days, units_sold=0, revenue=0,
                                 profit=0, margin=0, refund_rate=0, sell_through=0,
                                 performance_score=50.0, computed_at=utcnow())
        db.add(row)
        db.commit()
        out = _to_dict(row)
        out["has_data"] = False
        return out

    row = ProductPerformance(tenant_id=tenant_id, product_id=product_id,
                             window_days=window_days, computed_at=utcnow(), **fresh)
    db.add(row)
    db.commit()
    out = _to_dict(row)
    out["has_data"] = True
    return out


def get_performance(db: Session, tenant_id: int, product_id: int,
                    window_days: int = 30) -> dict:
    """读取表现分（优先缓存，过期则重算）。"""
    return compute_performance(db, tenant_id, product_id, window_days)


def performance_map(db: Session, tenant_id: int, product_ids: list[int],
                    window_days: int = 30) -> dict[int, float]:
    """批量取表现分（用于评分时的反馈维），缺失的按需计算。"""
    out: dict[int, float] = {}
    for pid in product_ids:
        out[pid] = get_performance(db, tenant_id, pid, window_days)["performance_score"]
    return out


def _to_dict(row: ProductPerformance) -> dict:
    return {
        "product_id": row.product_id,
        "window_days": row.window_days,
        "units_sold": row.units_sold,
        "revenue": row.revenue,
        "profit": row.profit,
        "margin": row.margin,
        "refund_rate": row.refund_rate,
        "sell_through": row.sell_through,
        "performance_score": row.performance_score,
        "computed_at": row.computed_at.strftime("%Y-%m-%d %H:%M:%S"),
    }
