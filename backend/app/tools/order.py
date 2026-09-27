"""Order Tool：订单与销售分析（§10.4 冻结清单）。

为什么 `get_orders` 不返回 `buyer_name`
    §19 验收项 8「无 PII 泄漏」要求 Trace / Memory / AiLog 中不得出现买家 PII。
    Tool 的返回体会被写进审计与 Agent 上下文，一旦带上买家姓名，PII 就顺着
    审计链路扩散到所有下游。买家身份的合法用途在客服场景，那条链路有自己的
    读取口径，不从这里走。

为什么 `analyze_sales` 要显式报告币种混合
    把 USD 与 CNY 的 `amount` 直接相加得到的「GMV」是一个没有意义的数，但它
    看起来非常像一个正常数字——最危险的一类错误。因此这里显式给出
    `currency_mixed`，让上层必须自己决定怎么处理，而不是被动接受一个假总额。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func

from ..models import Order, RefundOrder
from .base import BaseTool, Reading, as_int, clamp_limit, reading, ts
from .contract import ToolSpec


def order_dict(o: Order) -> dict:
    return {"id": o.id, "external_no": o.external_no, "shop_id": o.shop_id,
            "platform": o.platform, "product_id": o.product_id,
            "listing_id": o.listing_id, "qty": o.qty, "amount": o.amount,
            "cost": o.cost, "profit": o.profit, "currency": o.currency,
            "status": o.status, "tracking_no": o.tracking_no, "source": o.source,
            "country": o.country, "created_at": ts(o.created_at)}


class OrderTool(BaseTool):
    name = "order"
    specs = (
        ToolSpec(tool="order", method="get_orders", permission="order:read",
                 writes=False, summary="列出本租户订单，可按订单/状态/店铺过滤"),
        ToolSpec(tool="order", method="analyze_sales", permission="order:read",
                 writes=False, summary="按窗口汇总销售额、退款与平台分布"),
        ToolSpec(tool="order", method="get_daily_sales", permission="order:read",
                 writes=False, summary="按日聚合单商品销量（排除退款单，仅 api/import 来源）"),
        ToolSpec(tool="order", method="get_sales_summary", permission="order:read",
                 writes=False, summary="经营概况口径的销售汇总（排除退款单）：GMV/订单数/利润"),
    )

    def _get_orders(self, limit=50, status: str = "", shop_id=None, order_id=None) -> Reading:
        n = clamp_limit(limit)
        # 参数校验先于数据库访问：见 supply.py 同款说明。
        sid = None if shop_id is None else as_int(shop_id, "shop_id")
        oid = None if order_id is None else as_int(order_id, "order_id")
        query = self.db.query(Order).filter(Order.tenant_id == self.context.tenant_id)
        if oid is not None:
            query = query.filter(Order.id == oid)
        state = (status or "").strip()
        if state:
            query = query.filter(Order.status == state)
        if sid is not None:
            query = query.filter(Order.shop_id == sid)
        rows = query.order_by(Order.id.desc()).limit(n).all()
        return reading([order_dict(o) for o in rows], table="orders",
                       order_ids=[o.id for o in rows])

    def _get_daily_sales(self, product_id, days=84, platform: str = "",
                         country: str = "") -> Reading:
        """按日聚合销量：口径与需求预测的训练集一致（排除退款单、仅真实来源）。

        为什么聚合在 SQL 里做而不是把订单取回来在 Python 里分组
            12 周窗口内一个爆款可以有上万条订单，而 Tool 返回体会进 Agent 上下文
            与审计；逐条返回等于把订单表搬进上下文。聚合后每天一行。
        """
        pid = as_int(product_id, "product_id")
        window = clamp_limit(days, default=84, maximum=3650, name="days")
        since = datetime.utcnow() - timedelta(days=window)
        query = (self.db.query(func.date(Order.created_at), func.sum(Order.qty))
                 .filter(Order.tenant_id == self.context.tenant_id,
                         Order.product_id == pid,
                         Order.created_at >= since,
                         Order.status != "refunded",
                         Order.source.in_(("api", "import"))))
        name = (platform or "").strip()
        if name:
            query = query.filter(Order.platform == name)
        region = (country or "").strip()
        if region:
            query = query.filter(Order.country == region)
        rows = query.group_by(func.date(Order.created_at)).all()
        return reading([{"date": str(d), "qty": float(q or 0)} for d, q in rows],
                       table="orders", product_id=pid, since=ts(since),
                       window_days=window, day_count=len(rows))

    def _analyze_sales(self, days=30) -> Reading:
        # 上限 3650 天（约 10 年）：不是业务限制，而是给「days=10**9」这类调用
        # 一个确定的边界，避免一次调用把整张订单表扫进内存。
        window = clamp_limit(days, default=30, maximum=3650, name="days")
        since = datetime.utcnow() - timedelta(days=window)
        orders = (self.db.query(Order)
                  .filter(Order.tenant_id == self.context.tenant_id,
                          Order.created_at >= since).all())
        refunds = (self.db.query(RefundOrder)
                   .filter(RefundOrder.tenant_id == self.context.tenant_id,
                           RefundOrder.created_at >= since,
                           RefundOrder.status != "rejected").all())
        currencies = sorted({(o.currency or "") for o in orders})
        by_platform: dict = {}
        by_shop: dict = {}
        for o in orders:
            for bucket, key in ((by_platform, o.platform or ""), (by_shop, o.shop_id)):
                cell = bucket.setdefault(key, {"orders": 0, "amount": 0.0, "refund_amount": 0.0})
                cell["orders"] += 1
                cell["amount"] = round(cell["amount"] + float(o.amount or 0), 4)
        for r in refunds:
            order = next((o for o in orders if o.id == r.order_id), None)
            if order is None:
                continue
            by_platform[order.platform or ""]["refund_amount"] = round(
                by_platform[order.platform or ""]["refund_amount"] + float(r.amount or 0), 4)
            by_shop[order.shop_id]["refund_amount"] = round(
                by_shop[order.shop_id]["refund_amount"] + float(r.amount or 0), 4)
        return reading(
            {"window_days": window, "since": ts(since),
             "orders": len(orders),
             "gross_amount": round(sum(float(o.amount or 0) for o in orders), 4),
             "profit": round(sum(float(o.profit or 0) for o in orders), 4),
             "refund_count": len(refunds),
             "refund_amount": round(sum(float(r.amount or 0) for r in refunds), 4),
             "currencies": currencies,
             "currency_mixed": len(currencies) > 1,
             "by_platform": by_platform,
             "by_shop": {str(k): v for k, v in by_shop.items()}},
            table="orders", since=ts(since),
            order_ids=[o.id for o in orders],
            refund_ids=[r.id for r in refunds])

    def _get_sales_summary(self, days=30) -> Reading:
        """近 N 天销售汇总（经营概况口径）：GMV / 订单数 / 真实利润。

        为什么与 `analyze_sales` 并存而不是复用它
            两者口径不同且都成立：`analyze_sales` 给的是**含退款单**的毛量与
            退款明细（用于对账），本方法按经营概况口径**整体排除退款单**
            （用于 GMV / ROI 播报）。T-53 要求「同一口径只有一份」，不是把不同
            口径强行合并成一个——合并后必有一处失真。
        """
        window = clamp_limit(days, default=30, maximum=3650, name="days")
        since = datetime.utcnow() - timedelta(days=window)
        row = (self.db.query(func.sum(Order.amount), func.count(Order.id),
                             func.sum(Order.profit))
               .filter(Order.tenant_id == self.context.tenant_id,
                       Order.created_at >= since,
                       Order.status != "refunded").first())
        gmv, orders, profit = float(row[0] or 0), int(row[1] or 0), float(row[2] or 0)
        return reading({"gmv": gmv, "orders": orders, "profit": profit,
                        "window_days": window, "since": ts(since)},
                       table="orders", window_days=window, since=ts(since))
