"""Store Tool：店铺列表与店铺级经营指标（§10.4 冻结清单）。

为什么店铺列表必须显式排除归档行
    `DELETE /api/shops/{id}` 是**归档式软删除**（行仍在库中，订单/采购单/结算
    仍引用它）。因此「能列出」等于「可用」——归档店铺一旦出现在列表里，上层就
    可能对它发起拉单或发布，形成「已删除但可用」的越权路径。可见性判定统一由
    `services/shop_scope.py` 承担，本 Tool 只调用它，不自己重写一遍（T-53）。

为什么 `get_store_metrics` 只算订单口径、不含广告花费
    §10.4 给它的权限是 `order:read`——权限边界即数据边界。广告数据属另一个域
    （其权限与 Action 归口都不在 `order:read` 范围内），塞进来会让一个
    `order:read` 角色间接读到广告投放数据。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..models import Order, RefundOrder, Shop
from ..services.shop_scope import active_shop
from .base import BaseTool, Reading, as_int, clamp_limit, reading, ts
from .contract import ERR_NOT_FOUND, ToolError, ToolSpec


def shop_dict(s: Shop) -> dict:
    # 刻意不含 app_secret / access_token / refresh_token：凭证不进 Agent 上下文，
    # 也不进审计（§19 验收项 8）。
    return {"id": s.id, "platform": s.platform, "shop_name": s.shop_name,
            "shop_id": s.shop_id, "role": s.role, "status": s.status,
            "is_demo": s.is_demo, "auth_message": s.auth_message,
            "token_expire_at": ts(s.token_expire_at), "created_at": ts(s.created_at)}


class StoreTool(BaseTool):
    name = "store"
    specs = (
        ToolSpec(tool="store", method="get_store_metrics", permission="order:read",
                 writes=False, summary="店铺（或全部可见店铺）的订单/GMV/退款指标"),
        ToolSpec(tool="store", method="list_connected_stores", permission="workspace:read",
                 writes=False, summary="列出本租户已授权店铺（归档店铺视为不存在）"),
        ToolSpec(tool="store", method="sync_orders", permission="order:write",
                 writes=True, summary="从平台拉取订单（须经 Action System）"),
    )

    def _list_connected_stores(self) -> Reading:
        rows = (self.db.query(Shop)
                .filter(Shop.tenant_id == self.context.tenant_id,
                        Shop.archived_at.is_(None))
                .order_by(Shop.id.asc()).all())
        return reading([shop_dict(s) for s in rows], table="shops",
                       shop_ids=[s.id for s in rows])

    def _get_store_metrics(self, shop_id=None, days=30) -> Reading:
        window = clamp_limit(days, default=30, maximum=3650, name="days")
        since = datetime.utcnow() - timedelta(days=window)

        shop_ids = None
        if shop_id is not None:
            sid = as_int(shop_id, "shop_id")
            if active_shop(self.db, self.context.tenant_id, sid) is None:
                raise ToolError(ERR_NOT_FOUND, "店铺 %s 不存在或已归档" % sid)
            shop_ids = [sid]

        query = self.db.query(Order).filter(Order.tenant_id == self.context.tenant_id,
                                            Order.created_at >= since)
        if shop_ids is not None:
            query = query.filter(Order.shop_id.in_(shop_ids))
        orders = query.all()
        order_ids = [o.id for o in orders]
        refunds = []
        if order_ids:
            refunds = (self.db.query(RefundOrder)
                       .filter(RefundOrder.tenant_id == self.context.tenant_id,
                               RefundOrder.order_id.in_(order_ids),
                               RefundOrder.status != "rejected").all())

        per_shop: dict = {}
        for o in orders:
            cell = per_shop.setdefault(o.shop_id, {"orders": 0, "qty": 0,
                                                   "amount": 0.0, "profit": 0.0,
                                                   "refund_amount": 0.0})
            cell["orders"] += 1
            cell["qty"] += int(o.qty or 0)
            cell["amount"] = round(cell["amount"] + float(o.amount or 0), 4)
            cell["profit"] = round(cell["profit"] + float(o.profit or 0), 4)
        by_order = {o.id: o.shop_id for o in orders}
        for r in refunds:
            cell = per_shop.get(by_order.get(r.order_id))
            if cell is not None:
                cell["refund_amount"] = round(cell["refund_amount"] + float(r.amount or 0), 4)

        currencies = sorted({(o.currency or "") for o in orders})
        return reading(
            {"window_days": window, "since": ts(since), "shop_id": shop_id,
             "orders": len(orders), "qty": sum(int(o.qty or 0) for o in orders),
             "gross_amount": round(sum(float(o.amount or 0) for o in orders), 4),
             "profit": round(sum(float(o.profit or 0) for o in orders), 4),
             "refund_count": len(refunds),
             "refund_amount": round(sum(float(r.amount or 0) for r in refunds), 4),
             "currencies": currencies, "currency_mixed": len(currencies) > 1,
             "per_shop": {str(k): v for k, v in per_shop.items()}},
            table="orders", since=ts(since), order_ids=order_ids,
            refund_ids=[r.id for r in refunds])
