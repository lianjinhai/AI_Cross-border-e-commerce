"""Supply Tool：供应商与报价读取（§10.4 冻结清单）。

为什么报价要按租户过滤两遍（Supplier 与 SupplierOffer 各一次）
    `SupplierOffer` 自带 `tenant_id`，理论上只过滤它就够；但供应商的可见性
    还受 `Supplier` 的租户归属与未来可能的档案状态约束。两处都过滤，才能保证
    「拿到的报价，其供应商一定也在本租户可见范围内」——只过滤一层时，一旦
    出现脏数据（跨租户 offer 指向本租户 supplier），泄漏不会被挡住。
"""

from __future__ import annotations

from sqlalchemy import func

from ..models import Supplier, SupplierOffer
from .base import BaseTool, Reading, as_int, clamp_limit, reading, ts
from .contract import ToolSpec


def supplier_dict(s: Supplier) -> dict:
    return {"id": s.id, "name": s.name, "region": s.region, "rating": s.rating,
            "ship_days": s.ship_days, "settlement_days": s.settlement_days,
            "stability": s.stability, "supplier_type": s.supplier_type,
            "verification_status": s.verification_status,
            "capabilities": s.capabilities or [],
            "certifications": s.certifications or [],
            "source_kind": s.source_kind, "source_url": s.source_url,
            "created_at": ts(s.created_at)}


def offer_dict(o: SupplierOffer) -> dict:
    return {"id": o.id, "supplier_id": o.supplier_id, "product_id": o.product_id,
            "price": o.price, "currency": o.currency, "moq": o.moq,
            "ship_days": o.ship_days, "in_stock": o.in_stock,
            "created_at": ts(o.created_at)}


def _as_id_list(value) -> list[int]:
    """把「单个 id / id 列表 / 逗号分隔字符串」统一成 int 列表（空值 -> []）。

    为什么要兼容三种形态：调用方既有 Agent（传列表）也有脚本（传字符串），
    各写一套解析必然漂移（T-53）；脏值统一走 `as_int` 报 BAD_PARAM。
    """
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [part for part in str(value).split(",") if part.strip()]
    return [as_int(item, "supplier_ids") for item in items]


class SupplyTool(BaseTool):
    name = "supply"
    specs = (
        ToolSpec(tool="supply", method="search_suppliers", permission="supply:read",
                 writes=False, summary="按名称检索本租户供应商"),
        ToolSpec(tool="supply", method="get_supplier_offers", permission="supply:read",
                 writes=False, summary="读取供应商报价，可按供应商或商品过滤"),
        ToolSpec(tool="supply", method="get_offer_stats", permission="supply:read",
                 writes=False, summary="报价聚合（条数/均价/最低/最高），可按供应商过滤"),
        ToolSpec(tool="supply", method="create_purchase_order", permission="purchase:write",
                 writes=True, summary="创建采购单（须经 Action System）"),
    )

    def _search_suppliers(self, keyword: str = "", supplier_ids=None, limit=20) -> Reading:
        n = clamp_limit(limit, default=20)
        query = self.db.query(Supplier).filter(
            Supplier.tenant_id == self.context.tenant_id)
        ids = _as_id_list(supplier_ids)
        if ids:
            query = query.filter(Supplier.id.in_(ids))
        text = (keyword or "").strip()
        if text:
            query = query.filter(Supplier.name.like("%" + text + "%"))
        rows = query.order_by(Supplier.rating.desc(), Supplier.id.desc()).limit(n).all()
        return reading([supplier_dict(s) for s in rows], table="suppliers",
                       supplier_ids=[s.id for s in rows])

    def _get_supplier_offers(self, supplier_id=None, product_id=None,
                             in_stock=None, limit=50) -> Reading:
        n = clamp_limit(limit)
        # 参数校验必须先于任何数据库访问：脏参数应当在「碰到数据库之前」被拒绝，
        # 否则失败会退化成 INTERNAL（实现内部报错），调用方无从判断是自己传错了。
        sid = None if supplier_id is None else as_int(supplier_id, "supplier_id")
        pid = None if product_id is None else as_int(product_id, "product_id")
        stock = None
        if in_stock is not None:
            stock = (in_stock if isinstance(in_stock, bool)
                     else str(in_stock).strip().lower() in ("1", "true", "yes"))
        query = (self.db.query(SupplierOffer)
                 .join(Supplier, Supplier.id == SupplierOffer.supplier_id)
                 .filter(SupplierOffer.tenant_id == self.context.tenant_id,
                         Supplier.tenant_id == self.context.tenant_id))
        if sid is not None:
            query = query.filter(SupplierOffer.supplier_id == sid)
        if pid is not None:
            query = query.filter(SupplierOffer.product_id == pid)
        if stock is not None:
            query = query.filter(SupplierOffer.in_stock.is_(stock))
        rows = query.order_by(SupplierOffer.price.asc(), SupplierOffer.id.desc()).limit(n).all()
        return reading([offer_dict(o) for o in rows], table="supplier_offers",
                       offer_ids=[o.id for o in rows])

    def _get_offer_stats(self, supplier_id=None) -> Reading:
        """报价聚合：条数 / 均价 / 最低价 / 最高价（在 SQL 侧聚合，不取回全量报价）。

        与 `get_supplier_offers` 同款双层租户过滤（见模块 docstring）。
        """
        sid = None if supplier_id in (None, "") else as_int(supplier_id, "supplier_id")
        query = (self.db.query(func.count(SupplierOffer.id),
                               func.avg(SupplierOffer.price),
                               func.min(SupplierOffer.price),
                               func.max(SupplierOffer.price))
                 .join(Supplier, Supplier.id == SupplierOffer.supplier_id)
                 .filter(SupplierOffer.tenant_id == self.context.tenant_id,
                         Supplier.tenant_id == self.context.tenant_id))
        if sid is not None:
            query = query.filter(SupplierOffer.supplier_id == sid)
        count, avg_price, min_price, max_price = query.one()

        def money(value):
            return None if value is None else float(value)

        return reading({"count": int(count or 0), "avg_price": money(avg_price),
                        "min_price": money(min_price), "max_price": money(max_price)},
                       table="supplier_offers", supplier_id=sid)
