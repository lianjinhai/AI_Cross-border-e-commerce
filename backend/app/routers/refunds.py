"""售后逆向路由：退款单发起 → 审核 → 退货入库 → 退款完成（订单联动）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import Order, Product, RefundOrder, User, utcnow
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict

router = APIRouter(prefix="/refunds", tags=["refunds"])

_ACTIVE = ("pending", "approved", "returned")
_REFUNDABLE = {"paid", "shipped", "delivered"}


class RefundIn(BaseModel):
    order_id: int
    type: str = "refund_only"        # refund_only 退款不退货 / return_refund 退货退款
    qty: int = 1
    amount: float | None = None      # 缺省按订单单价×qty 自动计算
    reason: str = ""
    restock: bool = True             # 退货是否回补库存


class RefundAction(BaseModel):
    note: str = ""


def _no(prefix: str, pk: int) -> str:
    return f"{prefix}{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{pk % 100:02d}"


def _po_dict(db: Session, r: RefundOrder) -> dict:
    o = db.get(Order, r.order_id)
    d = to_dict(r)
    d["external_no"] = o.external_no if o else ""
    d["platform"] = o.platform if o else ""
    d["buyer_name"] = o.buyer_name if o else ""
    return d


@router.post("")
def create_refund(body: RefundIn, user: User = Depends(require_write),
                  db: Session = Depends(get_db)):
    o = db.get(Order, body.order_id)
    if not o or o.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    if o.status not in _REFUNDABLE:
        raise HTTPException(status_code=400,
                            detail=f"订单状态 {o.status} 不可发起退款（仅已付款/已发货/已签收）")
    if body.type not in ("refund_only", "return_refund"):
        raise HTTPException(status_code=400, detail="类型必须是 refund_only / return_refund")
    if not 1 <= body.qty <= o.qty:
        raise HTTPException(status_code=400, detail=f"退货数量需在 1-{o.qty} 之间")
    # 同订单存在进行中的退款单时拦截（防重复退款）
    dup = (db.query(RefundOrder)
           .filter(RefundOrder.tenant_id == user.tenant_id, RefundOrder.order_id == o.id,
                   RefundOrder.status.in_(_ACTIVE)).first())
    if dup:
        raise HTTPException(status_code=400, detail=f"该订单已有进行中的退款单 {dup.refund_no}")
    if o.status == "refunded" and o.qty <= body.qty:
        raise HTTPException(status_code=400, detail="订单已整单退款")
    unit = o.amount / o.qty if o.qty else 0
    amount = round(float(body.amount) if body.amount is not None else unit * body.qty, 2)
    if amount <= 0 or amount > round(unit * body.qty, 2) + 0.001:
        raise HTTPException(status_code=400,
                            detail=f"退款金额需在 0-{round(unit * body.qty, 2)} 之间（按数量比例）")
    r = RefundOrder(tenant_id=user.tenant_id, refund_no=_no("RF", o.id),
                    order_id=o.id, type=body.type, qty=body.qty,
                    amount=amount, reason=body.reason, restock=body.restock,
                    status="pending")
    db.add(r)
    db.commit()
    return _po_dict(db, r)


@router.get("")
def list_refunds(status: str = "", page_num: int = PageNum, page_size: int = PageSize,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(RefundOrder).filter(RefundOrder.tenant_id == user.tenant_id)
    if status:
        q = q.filter(RefundOrder.status == status)
    total = q.count()
    rows = (q.order_by(RefundOrder.id.desc())
            .offset((page_num - 1) * page_size).limit(page_size).all())
    return page([_po_dict(db, r) for r in rows], total, page_num, page_size)


@router.get("/{refund_id}")
def refund_detail(refund_id: int, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    return _po_dict(db, _owned(db, user.tenant_id, refund_id))


class StatusIn(BaseModel):
    status: str
    note: str = ""


@router.put("/{refund_id}/status")
def update_status(refund_id: int, body: StatusIn,
                  user: User = Depends(require_write), db: Session = Depends(get_db)):
    """审核动作：approve 同意 / reject 拒绝（pending 状态）。"""
    r = _owned(db, user.tenant_id, refund_id)
    if r.status != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态 {r.status} 不可审核")
    if body.status == "approved":
        r.status = "approved"
    elif body.status == "rejected":
        r.status = "rejected"
    else:
        raise HTTPException(status_code=400, detail="审核动作必须是 approved / rejected")
    if body.note:
        r.note = body.note
    db.commit()
    return _po_dict(db, r)


@router.post("/{refund_id}/return_receive")
def return_receive(refund_id: int, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    """退货入库：商品回补虚拟库存（restock=True 时）。"""
    r = _owned(db, user.tenant_id, refund_id)
    if r.type != "return_refund":
        raise HTTPException(status_code=400, detail="仅退货退款单需要退货入库")
    if r.status != "approved":
        raise HTTPException(status_code=400, detail="需先审核同意（approved）")
    o = db.get(Order, r.order_id)
    restocked = 0
    if r.restock and o and o.product_id:
        p = db.get(Product, o.product_id)
        attrs = dict(p.attrs or {})
        attrs["onhand"] = int(attrs.get("onhand") or 0) + r.qty
        p.attrs = attrs
        restocked = r.qty
    r.status = "returned"
    if r.note:
        r.note += "；"
    r.note += f"已退货入库 {restocked} 件" if restocked else "已退货（不回补库存）"
    db.commit()
    return {"ok": True, "restocked": restocked, "refund": _po_dict(db, r)}


@router.post("/{refund_id}/refund")
def do_refund(refund_id: int, user: User = Depends(require_write),
              db: Session = Depends(get_db)):
    """执行退款：流转订单状态（真实打款由平台/支付渠道后台完成，此处记录闭环）。"""
    r = _owned(db, user.tenant_id, refund_id)
    if r.type == "return_refund" and r.status != "returned":
        raise HTTPException(status_code=400, detail="退货退款需先完成退货入库")
    if r.status not in ("approved", "returned"):
        raise HTTPException(status_code=400, detail=f"当前状态 {r.status} 不可退款")
    o = db.get(Order, r.order_id)
    r.status = "refunded"
    r.refunded_at = utcnow()
    if o:
        # 全额整单退款 -> 订单置 refunded；部分退款保留原状态但记录
        if r.qty >= o.qty:
            o.status = "refunded"
        o.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "refund": _po_dict(db, r),
            "order_status": o.status if o else None}


def _owned(db: Session, tenant_id: int, refund_id: int) -> RefundOrder:
    r = db.get(RefundOrder, refund_id)
    if not r or r.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="退款单不存在")
    return r
