"""采购路由：补货预警生成采购单 → 提交供应商 → 收货入库；1688 一件代发下单（第十四章自动采购）。

店铺角色契约：Shop.role = source（货源：1688 搜品/一件代发下单）| sales（销售：上架/拉单）。
代发下单只接受 source 店铺，销售店铺调用会被 400 明确拒绝——两类店铺绝不可混用。
"""
import hashlib
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.orchestrator import invoke_supplier
from ..auth import get_current_user, is_impersonating_user, require_write
from ..db import get_db
from ..models import Product, PurchaseOrder, Shop, Supplier, SupplierOffer, User
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict
from ..services.ai_actions import ActionError
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/purchases", tags=["purchases"])

_VALID = {"draft", "submitted", "received", "cancelled"}


class FromForecastIn(BaseModel):
    product_ids: list[int] = []   # 空则对所有缺货预警商品生成
    qty_multiplier: float = 1.0   # 建议补货量倍数


class PurchaseIn(BaseModel):
    product_id: int
    qty: int
    supplier_id: int | None = None   # 缺省自动选最优货源
    note: str = ""


class ReceiveIn(BaseModel):
    qty: int | None = None        # 缺省=全部


def _po_dict(db: Session, po: PurchaseOrder) -> dict:
    d = to_dict(po)
    p = db.get(Product, po.product_id)
    s = db.get(Supplier, po.supplier_id)
    d["product_title"] = p.title if p else ""
    d["supplier_name"] = s.name if s else ""
    return d


def _best_offer(db: Session, tenant_id: int, product_id: int,
                supplier_id: int | None = None) -> tuple[SupplierOffer, Supplier]:
    q = (db.query(SupplierOffer, Supplier)
         .join(Supplier, Supplier.id == SupplierOffer.supplier_id)
         .filter(SupplierOffer.tenant_id == tenant_id,
                 SupplierOffer.product_id == product_id,
                 SupplierOffer.in_stock.is_(True)))
    if supplier_id:
        q = q.filter(SupplierOffer.supplier_id == supplier_id,
                     Supplier.tenant_id == tenant_id)
    rows = q.all()
    if not rows:
        detail = (f"供应商 {supplier_id} 对商品 {product_id} 无可用货源报价" if supplier_id
                  else f"商品 {product_id} 无可用货源报价")
        raise HTTPException(status_code=404, detail=detail)
    return min(rows, key=lambda r: r[0].price)


def _gen_po(db: Session, tenant_id: int, product_id: int, qty: int,
            supplier_id: int | None = None) -> PurchaseOrder:
    if supplier_id:
        sup = db.get(Supplier, supplier_id)
        if not sup or sup.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="供应商不存在")
    offer, supplier = _best_offer(db, tenant_id, product_id, supplier_id)
    if getattr(supplier, "verification_status", "verified") != "verified":
        raise HTTPException(status_code=409, detail="源头工厂尚未完成尽调，禁止生成采购单")
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_no=f"PO{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{product_id % 100:02d}",
        supplier_id=supplier.id, product_id=product_id,
        qty=qty, unit_price=offer.price, total=round(offer.price * qty, 2),
        status="draft",
        expected_date=(datetime.utcnow() + timedelta(days=supplier.ship_days)).strftime("%Y-%m-%d"),
        note=(f"指定供应商生成：{supplier.name}（¥{offer.price}/件）" if supplier_id
              else f"按最优货源自动生成：{supplier.name}（¥{offer.price}/件）"))
    db.add(po)
    db.flush()
    return po


@router.post("/from_forecast")
def from_forecast(body: FromForecastIn, user: User = Depends(require_write),
                  db: Session = Depends(get_db)):
    """对缺货预警商品按 AI 建议补货量批量生成采购单（草稿）。"""
    from ..services.commercial_analytics import forecast_monitoring
    commercial_gate = forecast_monitoring(db, user.tenant_id)["commercial_gate"]
    if not commercial_gate["passed"]:
        product_ids = body.product_ids or [row.id for row in db.query(Product.id).filter(
            Product.tenant_id == user.tenant_id).all()]
        reason = "预测商用全局门禁未通过，禁止自动生成采购单"
        return {"created": [], "commercial_gate": commercial_gate,
                "skipped": [{"product_id": int(pid), "reason": reason,
                             "gate_checks": commercial_gate["checks"]}
                            for pid in product_ids]}
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        if body.product_ids:
            forecasts = []
            for pid in body.product_ids:
                try:
                    forecasts.append(invoke_supplier(db, ctx, "forecast", int(pid)))
                except (ActionError, ValueError):
                    continue
        else:
            forecasts = invoke_supplier(db, ctx, "forecast_batch", {}, {})["forecasts"]
    except (ActionError, ValueError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc)) from exc
    created, skipped = [], []
    for f in forecasts:
        if not f.get("automation_allowed", False):
            skipped.append({"product_id": f["product_id"],
                            "reason": "预测可信度低，禁止自动生成采购单",
                            "data_quality": f.get("data_quality"),
                            "backtest": f.get("backtest")})
            continue
        if f["shortage_risk"] == "low" or f["suggest_restock_qty"] <= 0:
            skipped.append({"product_id": f["product_id"], "reason": "库存充足"})
            continue
        qty = max(1, int(f["suggest_restock_qty"] * body.qty_multiplier))
        try:
            po = _gen_po(db, user.tenant_id, f["product_id"], qty)
        except HTTPException as e:
            skipped.append({"product_id": f["product_id"], "reason": e.detail})
            continue
        created.append(_po_dict(db, po))
    db.commit()
    return {"created": created, "skipped": skipped}


@router.post("")
def create_po(body: PurchaseIn, user: User = Depends(require_write),
              db: Session = Depends(get_db)):
    if body.qty <= 0:
        raise HTTPException(status_code=400, detail="采购数量必须大于 0")
    po = _gen_po(db, user.tenant_id, body.product_id, body.qty, body.supplier_id)
    if body.note:
        po.note = body.note
    db.commit()
    return _po_dict(db, po)


class DropshipIn(BaseModel):
    """一件代发下单：从已授权 1688 货源店铺按 offer 下单。"""
    shop_id: int                # 货源店铺（必须 role=source；is_demo 走演示通道）
    product_id: int             # 本地商品池商品（来源须为 1688）
    order_id: int               # 关联已付款销售订单
    qty: int = 1
    consignee: str = ""         # 收件人
    phone: str = ""
    address: str = ""           # 收货地址（真实下单时传平台）


def _offer_id_of(product: Product) -> int | None:
    import re
    m = re.search(r"offer/(\d+)\.html", product.source_url or "")
    return int(m.group(1)) if m else None


@router.post("/dropship")
def dropship_order(body: DropshipIn, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    """1688 一件代发：买家在销售平台下单 → 本地订单 → 按需向 1688 货源店铺代发下单。

    强约束：shop 必须 role=source（销售店铺传进来直接 400），演示店铺走模拟通道。
    """
    shop = db.get(Shop, body.shop_id)
    if not shop or shop.tenant_id != user.tenant_id or shop.archived_at is not None:
        raise HTTPException(status_code=404, detail="店铺不存在")
    if shop.role != "source":
        raise HTTPException(
            status_code=400,
            detail=f"「{shop.shop_name}」是销售店铺（sales），一件代发必须使用货源店铺（source，如 1688）。两类店铺不可混用")
    from ..models import Order
    sales_order = db.get(Order, body.order_id)
    if not sales_order or sales_order.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="关联销售订单不存在")
    if sales_order.status not in ("paid", "shipped"):
        raise HTTPException(status_code=409, detail="仅已付款销售订单可创建代发采购")
    if sales_order.product_id and sales_order.product_id != body.product_id:
        raise HTTPException(status_code=409, detail="销售订单商品与代发商品不一致")
    p = db.get(Product, body.product_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    if body.qty <= 0:
        raise HTTPException(status_code=400, detail="代发数量必须大于 0")
    offer_id = _offer_id_of(p)
    if not offer_id:
        raise HTTPException(status_code=400,
                            detail="该商品没有 1688 offer 来源链接，无法代发下单（请先通过 1688 采集或填写 source_url）")

    marker = f"sales_order:{sales_order.id}"
    idempotency_key = hashlib.sha256(
        f"{user.tenant_id}:{shop.id}:{sales_order.id}:{p.id}".encode()).hexdigest()
    if not shop.is_demo and shop.status != "authorized":
        raise HTTPException(status_code=400,
                            detail=f"货源店铺「{shop.shop_name}」未授权（当前 {shop.status}），请先完成 1688 OAuth 授权")
    existing = (db.query(PurchaseOrder).filter(
        PurchaseOrder.tenant_id == user.tenant_id,
        PurchaseOrder.idempotency_key == idempotency_key).first())
    if existing:
        if existing.platform_trade_no:
            return {"ok": True, "mode": "idempotent_replay",
                    "platform_trade_no": existing.platform_trade_no,
                    "purchase": _po_dict(db, existing)}
    # 演示店铺模拟返回
    platform_trade_no, mode = "", "demo" if shop.is_demo else "api"
    if shop.is_demo:
        platform_trade_no = f"DEMO{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{offer_id % 1000:04d}"
        if not platform_trade_no:
            raise HTTPException(status_code=400, detail="1688 未返回代发订单号，请到平台核对")

    # 先持久化任务再调平台；即使平台成功后进程断线，重试也沿用同一幂等键。
    po = existing
    if not po:
        po = PurchaseOrder(
            tenant_id=user.tenant_id,
            po_no=f"DS{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{offer_id % 100:02d}",
            supplier_id=_fallback_supplier(db, user.tenant_id, body.product_id),
            product_id=p.id, qty=body.qty,
            unit_price=float((p.attrs or {}).get("supplier_price") or 0),
            total=round(float((p.attrs or {}).get("supplier_price") or 0) * body.qty, 2),
            status="submitted" if shop.is_demo else "draft",
            sales_order_id=sales_order.id, source_shop_id=shop.id,
            idempotency_key=idempotency_key, platform_trade_no=platform_trade_no,
            purchase_type="dropship",
            note=f"{marker}｜一件代发({mode}) 平台单号 {platform_trade_no}｜收件:{body.consignee or '-'} {body.address[:40]}")
        db.add(po)
        db.commit()
        db.refresh(po)
    if not shop.is_demo:
        from ..services.open_1688 import Api1688Error, call_api
        try:
            payload = {
                "offerId": offer_id, "quantity": body.qty,
                "consigneeName": body.consignee, "mobile": body.phone,
                "address": body.address, "outBizCode": idempotency_key,
            }
            raw = call_api(db, "alibaba.trade.fastCreateOrder",
                           {"flow": "dropshipping", "orderRequest": json.dumps(payload, ensure_ascii=False)},
                           credentials={"app_key": shop.app_key, "app_secret": shop.app_secret,
                                        "access_token": shop.access_token})
            result = raw.get("result") or raw.get("data") or {}
            platform_trade_no = str(result.get("orderId") or result.get("orderIdOfStr") or "")
            if not platform_trade_no:
                raise Api1688Error("1688 未返回代发订单号")
        except Api1688Error as e:
            po.note = f"{po.note}｜平台结果待确认:{str(e)[:160]}"
            db.commit()
            raise HTTPException(status_code=502,
                                detail=f"1688代发结果未确认，已保留幂等任务，请重试或到平台核对：{e}") from e
        po.platform_trade_no = platform_trade_no
        po.status = "submitted"
        po.note = f"{marker}｜一件代发(api) 平台单号 {platform_trade_no}｜收件:{body.consignee or '-'} {body.address[:40]}"
        db.commit()
    return {"ok": True, "mode": mode, "platform_trade_no": platform_trade_no,
            "offer_id": offer_id, "purchase": _po_dict(db, po)}


def _fallback_supplier(db: Session, tenant_id: int, product_id: int) -> int:
    offer = (db.query(SupplierOffer)
             .filter(SupplierOffer.tenant_id == tenant_id,
                     SupplierOffer.product_id == product_id)
             .order_by(SupplierOffer.price).first())
    if not offer:
        raise HTTPException(status_code=400,
                            detail="该商品在供应商库无报价记录，无法归集采购成本（请先录入报价单）")
    return offer.supplier_id


@router.get("")
def list_pos(status: str = "", page_num: int = PageNum, page_size: int = PageSize,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(PurchaseOrder).filter(PurchaseOrder.tenant_id == user.tenant_id)
    if status:
        q = q.filter(PurchaseOrder.status == status)
    total = q.count()
    rows = (q.order_by(PurchaseOrder.id.desc())
            .offset((page_num - 1) * page_size).limit(page_size).all())
    return page([_po_dict(db, r) for r in rows], total, page_num, page_size)


class PoUpdate(BaseModel):
    qty: int | None = None
    status: str | None = None
    note: str | None = None


@router.put("/{po_id}")
def update_po(po_id: int, body: PoUpdate, user: User = Depends(require_write),
              db: Session = Depends(get_db)):
    po = _owned(db, user.tenant_id, po_id)
    if body.qty is not None:
        if body.qty <= 0 or po.status != "draft":
            raise HTTPException(status_code=400, detail="仅草稿状态可改数量且必须大于 0")
        po.qty = body.qty
        po.total = round(po.unit_price * body.qty, 2)
    if body.note is not None:
        po.note = body.note
    if body.status is not None:
        if body.status not in _VALID:
            raise HTTPException(status_code=400, detail="状态不合法")
        allowed = {"draft": {"submitted", "cancelled"},
                   "submitted": {"received", "cancelled"},
                   "received": set(), "cancelled": set()}
        if body.status != po.status and body.status not in allowed.get(po.status, set()):
            raise HTTPException(status_code=409,
                                detail=f"采购单状态不可从 {po.status} 流转到 {body.status}")
        if body.status == "submitted":
            supplier = db.get(Supplier, po.supplier_id)
            if not supplier or getattr(supplier, "verification_status", "verified") != "verified":
                raise HTTPException(status_code=409, detail="源头工厂未通过尽调，禁止提交采购")
        po.status = body.status  # draft -> submitted 即提交供应商
    db.commit()
    return _po_dict(db, po)


@router.post("/{po_id}/receive")
def receive_po(po_id: int, body: ReceiveIn, user: User = Depends(require_write),
               db: Session = Depends(get_db)):
    """收货入库：虚拟库存增加，预警自然消除。"""
    po = _owned(db, user.tenant_id, po_id)
    if po.status != "submitted":
        raise HTTPException(status_code=400, detail=f"状态 {po.status} 不可收货")
    qty = body.qty if body.qty is not None else po.qty
    if not 0 < qty <= po.qty:
        raise HTTPException(status_code=400, detail=f"收货数量需在 1-{po.qty} 之间")
    p = db.get(Product, po.product_id)
    attrs = dict(p.attrs or {})
    attrs["onhand"] = int(attrs.get("onhand") or 0) + qty
    p.attrs = attrs
    p.updated_at = datetime.utcnow()
    po.status = "received"
    po.received_at = datetime.utcnow()
    if qty < po.qty:
        po.note = (po.note + " | ").strip("| ") + f"部分收货 {qty}/{po.qty}，余量按取消处理"
    db.commit()
    return {"ok": True, "in_stock_added": qty, "onhand_now": attrs["onhand"],
            "purchase": _po_dict(db, po)}


@router.delete("/{po_id}")
def cancel_po(po_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    po = _owned(db, user.tenant_id, po_id)
    if po.status == "received":
        raise HTTPException(status_code=400, detail="已收货的采购单不可取消")
    po.status = "cancelled"
    db.commit()
    return {"ok": True}


def _owned(db: Session, tenant_id: int, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if not po or po.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="采购单不存在")
    return po
