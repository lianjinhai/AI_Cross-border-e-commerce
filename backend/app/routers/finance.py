"""财务基础数据：汇率、订单费用、订单行与平台结算对账。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin, require_write
from ..db import get_db
from ..models import ExchangeRate, Order, OrderFee, OrderLine, PlatformSettlementRecord, User
from ..serialize import to_dict

router = APIRouter(prefix="/finance", tags=["finance"])


class FxIn(BaseModel):
    base_currency: str
    quote_currency: str = "USD"
    rate: float = Field(gt=0)
    effective_at: datetime
    source: str = "manual"


class FeeIn(BaseModel):
    fee_type: str
    amount: float
    currency: str = "USD"
    source: str = "manual"
    occurred_at: datetime | None = None


class LineIn(BaseModel):
    external_line_no: str
    sku: str = ""
    title: str = ""
    qty: int = Field(gt=0)
    unit_price: float = Field(ge=0)
    product_cost: float = Field(ge=0, default=0)
    currency: str = "USD"


class SettlementIn(BaseModel):
    shop_id: int | None = None
    platform: str
    external_settlement_no: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    gross_amount: float = Field(ge=0)
    fee_amount: float = Field(ge=0, default=0)
    refund_amount: float = Field(ge=0, default=0)
    net_amount: float
    currency: str = "USD"
    status: str = "pending"
    paid_at: datetime | None = None
    raw: dict = Field(default_factory=dict)


@router.get("/fx")
def list_fx(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(ExchangeRate).filter(ExchangeRate.tenant_id == user.tenant_id)
            .order_by(ExchangeRate.effective_at.desc()).limit(1000).all())
    return {"items": [to_dict(x) for x in rows]}


@router.post("/fx")
def create_fx(body: FxIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = ExchangeRate(tenant_id=user.tenant_id,
        base_currency=body.base_currency.upper(), quote_currency=body.quote_currency.upper(),
        rate=body.rate, effective_at=body.effective_at, source=body.source)
    db.add(row); db.commit(); db.refresh(row)
    return to_dict(row)


def _order(db: Session, tenant_id: int, order_id: int) -> Order:
    row = db.get(Order, order_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    return row


@router.get("/orders/{order_id}/detail")
def order_finance_detail(order_id: int, user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    order = _order(db, user.tenant_id, order_id)
    lines = db.query(OrderLine).filter(OrderLine.tenant_id == user.tenant_id,
                                       OrderLine.order_id == order.id).all()
    fees = db.query(OrderFee).filter(OrderFee.tenant_id == user.tenant_id,
                                     OrderFee.order_id == order.id).all()
    return {"order": to_dict(order), "lines": [to_dict(x) for x in lines],
            "fees": [to_dict(x) for x in fees]}


@router.post("/orders/{order_id}/lines")
def add_order_line(order_id: int, body: LineIn, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    order = _order(db, user.tenant_id, order_id)
    row = OrderLine(tenant_id=user.tenant_id, order_id=order.id, **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return to_dict(row)


@router.post("/orders/{order_id}/fees")
def add_order_fee(order_id: int, body: FeeIn, user: User = Depends(require_write),
                  db: Session = Depends(get_db)):
    order = _order(db, user.tenant_id, order_id)
    row = OrderFee(tenant_id=user.tenant_id, order_id=order.id,
        fee_type=body.fee_type, amount=body.amount, currency=body.currency.upper(),
        source=body.source, occurred_at=body.occurred_at or datetime.utcnow())
    db.add(row); db.commit(); db.refresh(row)
    return to_dict(row)


@router.get("/settlement-reconciliation")
def settlement_reconciliation(user: User = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    rows = db.query(PlatformSettlementRecord).filter(
        PlatformSettlementRecord.tenant_id == user.tenant_id).all()
    items = []
    for row in rows:
        expected = float(row.gross_amount) - float(row.fee_amount) - float(row.refund_amount)
        actual = float(row.net_amount)
        items.append({**to_dict(row), "expected_net": round(expected, 2),
                      "variance": round(actual - expected, 2),
                      "reconciled": abs(actual - expected) < 0.01})
    return {"items": items, "unreconciled": sum(not x["reconciled"] for x in items)}


@router.post("/platform-settlements")
def upsert_platform_settlement(body: SettlementIn,
                               user: User = Depends(require_write),
                               db: Session = Depends(get_db)):
    """按平台结算单号幂等写入；重复回调更新同一条事实记录。"""
    platform = body.platform.strip().lower()
    settlement_no = body.external_settlement_no.strip()
    if not platform or not settlement_no:
        raise HTTPException(status_code=422, detail="platform 和 external_settlement_no 必填")
    row = db.query(PlatformSettlementRecord).filter(
        PlatformSettlementRecord.tenant_id == user.tenant_id,
        PlatformSettlementRecord.platform == platform,
        PlatformSettlementRecord.external_settlement_no == settlement_no).first()
    values = body.model_dump(exclude={"platform", "external_settlement_no"})
    values["currency"] = body.currency.upper()
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        row = PlatformSettlementRecord(
            tenant_id=user.tenant_id, platform=platform,
            external_settlement_no=settlement_no, **values)
        db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="结算单并发写入冲突，请安全重试") from e
    db.refresh(row)
    return {"item": to_dict(row), "idempotent_key": f"{platform}:{settlement_no}"}
