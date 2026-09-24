"""供应商账期结算路由：汇总已收货采购单 → 对账确认 → 付款完成 → 应付账龄总览。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import PurchaseOrder, Settlement, Supplier, User, utcnow
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict

router = APIRouter(prefix="/settlements", tags=["settlements"])


def _no(pk: int) -> str:
    return f"ST{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{pk % 100:02d}"


def _st_dict(db: Session, s: Settlement) -> dict:
    d = to_dict(s)
    sup = db.get(Supplier, s.supplier_id)
    d["supplier_name"] = sup.name if sup else ""
    d["settlement_days"] = sup.settlement_days if sup else 30
    return d


@router.post("/generate")
def generate(body: dict, user: User = Depends(require_write), db: Session = Depends(get_db)):
    """按供应商汇总「已收货且未结算」的采购单，生成对账单。"""
    supplier_id = int(body.get("supplier_id") or 0)
    sup = db.get(Supplier, supplier_id)
    if not sup or sup.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="供应商不存在")
    pos = (db.query(PurchaseOrder)
           .filter(PurchaseOrder.tenant_id == user.tenant_id,
                   PurchaseOrder.supplier_id == supplier_id,
                   PurchaseOrder.status == "received",
                   PurchaseOrder.settlement_id.is_(None)).all())
    if not pos:
        raise HTTPException(status_code=400, detail="该供应商没有待结算的已收货采购单")
    total = round(sum(p.total for p in pos), 2)
    s = Settlement(tenant_id=user.tenant_id,
                   settle_no=f"ST{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{supplier_id % 100:02d}",
                   supplier_id=supplier_id,
                   period_start=min(p.created_at for p in pos),
                   period_end=max(p.created_at for p in pos),
                   po_count=len(pos), total_amount=total, status="pending")
    db.add(s)
    db.flush()
    for p in pos:
        p.settlement_id = s.id
    db.commit()
    return _st_dict(db, s)


@router.get("")
def list_settlements(status: str = "", page_num: int = PageNum, page_size: int = PageSize,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Settlement).filter(Settlement.tenant_id == user.tenant_id)
    if status:
        q = q.filter(Settlement.status == status)
    total = q.count()
    rows = (q.order_by(Settlement.id.desc())
            .offset((page_num - 1) * page_size).limit(page_size).all())
    return page([_st_dict(db, r) for r in rows], total, page_num, page_size)


@router.get("/summary")
def payable_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """应付总览：每供应商 未结算应付/账期/已逾期金额（PO 收货日+账期 < 今天 且未付款）。"""
    sups = db.query(Supplier).filter(Supplier.tenant_id == user.tenant_id).all()
    out = []
    for s in sups:
        # 未结算应付 = 已收货且尚未付款：未挂对账单，或所挂对账单还未 paid
        # （对账单一生成即回写 settlement_id，仅按 settlement_id is null 过滤会把
        #   pending/confirmed 的应付提前归零）
        unsettled = (db.query(PurchaseOrder)
                     .outerjoin(Settlement, Settlement.id == PurchaseOrder.settlement_id)
                     .filter(PurchaseOrder.tenant_id == user.tenant_id,
                             PurchaseOrder.supplier_id == s.id,
                             PurchaseOrder.status == "received",
                             or_(PurchaseOrder.settlement_id.is_(None),
                                 Settlement.status != "paid")).all())
        overdue_pos = [p for p in unsettled
                       if p.received_at and (p.received_at + timedelta(days=s.settlement_days)) < utcnow()]
        out.append({
            "supplier_id": s.id, "supplier_name": s.name,
            "settlement_days": s.settlement_days,
            "unsettled_count": len(unsettled),
            "unsettled_amount": round(sum(p.total for p in unsettled), 2),
            "overdue_count": len(overdue_pos),
            "overdue_amount": round(sum(p.total for p in overdue_pos), 2),
        })
    out.sort(key=lambda x: -x["overdue_amount"])
    return {"items": out}


class SettleAction(BaseModel):
    status: str                     # confirmed / paid
    note: str = ""


@router.put("/{settle_id}")
def update_settlement(settle_id: int, body: SettleAction,
                      user: User = Depends(require_write), db: Session = Depends(get_db)):
    s = _owned(db, user.tenant_id, settle_id)
    if body.status not in ("confirmed", "paid"):
        raise HTTPException(status_code=400, detail="动作必须是 confirmed / paid")
    allowed = {"pending": {"confirmed"}, "confirmed": {"paid"}, "paid": set()}
    if body.status != s.status and body.status not in allowed.get(s.status, set()):
        raise HTTPException(status_code=409,
                            detail=f"结算单状态不可从 {s.status} 流转到 {body.status}")
    s.status = body.status
    if body.status == "paid":
        s.paid_at = utcnow()
    if body.note:
        s.note = body.note
    db.commit()
    return _st_dict(db, s)


def _owned(db: Session, tenant_id: int, settle_id: int) -> Settlement:
    s = db.get(Settlement, settle_id)
    if not s or s.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="结算单不存在")
    return s
