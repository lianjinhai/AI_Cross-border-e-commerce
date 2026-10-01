"""海外仓持有成本引擎：库龄 × 日费率 → 持有成本 + 超期附加（D59）。

把海外仓费用从「路由计费」（按出库件数平摊）升级为「库存模型」
（按库龄累计）。库存模型回答的是：「这批货在海外仓囤了多久，
该扣多少仓储费，超期要不要叠加」——这才是真实利润杀手。

分层与边界：
    - 纯领域计算，不写库；金额口径统一为人民币。
    - 库龄 = (now - received_at).days，下限 0（刚到货不算负成本）。
    - 持有成本 = 库龄 × daily_fee × qty；超期部分 × (1 + surcharge_rate)。
    - 未配 Warehouse 时返回全 0，并显式标记 ``holding_cost_applied=False``，
      保证未启用库存模型的租户 / 既有测试口径不变。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import InventorySnapshot, Warehouse


def _null_result(reason: str) -> dict:
    return {"holding_cost_cny": 0.0, "days_in_stock": 0, "qty": 0,
            "daily_fee_per_unit": 0.0, "long_term_surcharge_rate": 0.0,
            "long_term_surcharge_cny": 0.0, "warehouse_id": None,
            "holding_cost_applied": False, "reason": reason}


def holding_cost(db: Session, tenant_id: int | None, *, warehouse_id: int | None,
                 product_id: int | None = None, sku: str = "", at: datetime | None = None) -> dict:
    """计算库位 × 商品的最坏情况下持有成本（拥有最长库龄的那批）。

    真实海外仓成本取决于「最老那批货」：货龄越老，越可能滞销。
    本函数取同 SKU 在该库位中库龄最大的快照作为代表，计算其持有成本。
    回退语义：
        - ``warehouse_id`` 未给 → 全 0、``holding_cost_applied=False``；
        - Warehouse 不存在或 inactive → 全 0、``reason="warehouse_not_found"``；
        - 商品未配库存（无快照）→ 库龄 0，holding_cost_cny=0。
    """
    if warehouse_id is None:
        return _null_result("warehouse_not_specified")
    at = at or datetime.utcnow()
    wh = db.get(Warehouse, warehouse_id)
    if wh is None or not wh.active:
        return _null_result("warehouse_not_found")
    if tenant_id is not None and (wh.tenant_id is None or wh.tenant_id != tenant_id):
        # 租户隔离：平台内置库位（tenant_id IS NULL）对所有租户可见，
        # 租户自建库位仅自身可见。
        if wh.tenant_id is not None:
            return _null_result("tenant_mismatch")

    query = db.query(InventorySnapshot).filter(
        InventorySnapshot.warehouse_id == warehouse_id,
        InventorySnapshot.qty_on_hand > 0)
    if tenant_id is not None:
        query = query.filter(InventorySnapshot.tenant_id.is_(None)
                              | (InventorySnapshot.tenant_id == tenant_id))
    if product_id is not None:
        query = query.filter(InventorySnapshot.product_id == product_id)
    if sku:
        query = query.filter(InventorySnapshot.sku == sku)
    # 取库龄最大的快照（received_at 最早）作为代表。
    snapshot = query.order_by(InventorySnapshot.received_at.asc()).first()
    if snapshot is None:
        return _null_result("no_inventory")

    days = max(0, (at - snapshot.received_at).days)
    daily = float(wh.daily_fee_per_unit or 0)
    qty = int(snapshot.qty_on_hand or 0)
    base = days * daily * qty
    surcharge_rate = float(wh.long_term_surcharge_rate or 0)
    threshold = int(wh.long_term_threshold_days or 0)
    surcharge = 0.0
    if threshold > 0 and days > threshold:
        # 超期部分叠加附加费率，而非全期叠加
        surcharge = (days - threshold) * daily * qty * surcharge_rate
    return {
        "holding_cost_cny": round(base + surcharge, 2),
        "days_in_stock": days,
        "qty": qty,
        "daily_fee_per_unit": daily,
        "long_term_threshold_days": threshold,
        "long_term_surcharge_rate": surcharge_rate,
        "long_term_surcharge_cny": round(surcharge, 2),
        "warehouse_id": warehouse_id,
        "warehouse_code": wh.code,
        "snapshot_id": snapshot.id,
        "received_at": snapshot.received_at.strftime("%Y-%m-%d"),
        "holding_cost_applied": True,
        "reason": "ok",
    }


def record_receipt(db: Session, tenant_id: int | None, *, warehouse_id: int,
                   product_id: int, sku: str = "", qty: int = 1,
                   at: datetime | None = None) -> InventorySnapshot:
    """登记入库：写一条快照记录库龄起算点。

    入库操作费（inbound_fee_per_unit）由调用方在 ``costing`` 里叠加，
    此处只记事实，避免在「记事实」与「计费」之间产生耦合。
    """
    at = at or datetime.utcnow()
    snap = InventorySnapshot(
        tenant_id=tenant_id, warehouse_id=warehouse_id,
        product_id=product_id, sku=sku or "",
        qty_on_hand=max(int(qty or 0), 0), received_at=at, snapshot_at=at)
    db.add(snap)
    db.flush()
    return snap
