"""供应链路由：供应商 CRUD / AI 评分 / 最优货源 / 销量预测 / 报价单录入。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..agents.orchestrator import invoke_supplier
from ..agents.supplier import SupplierAgent
from ..auth import get_current_user, is_impersonating_user, require_write
from ..db import get_db
from ..models import Product, Supplier, SupplierOffer, SupplierScore, User
from ..serialize import to_dict
from ..services.ai_actions import ActionError
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


class SupplierIn(BaseModel):
    name: str
    region: str = ""
    rating: float = 4.5
    ship_days: int = 7
    stability: float = 80
    supplier_type: str = "factory"
    capabilities: list[str] = []
    certifications: list[str] = []
    note: str = ""


class MatchIn(BaseModel):
    product_id: int


@router.get("")
def list_suppliers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(Supplier).filter(Supplier.tenant_id == user.tenant_id)
            .order_by(Supplier.id).all())
    latest = {}
    for s in (db.query(SupplierScore).filter(SupplierScore.tenant_id == user.tenant_id)
              .order_by(SupplierScore.created_at.desc()).all()):
        latest.setdefault(s.supplier_id, s)
    items = []
    for s in rows:
        d = to_dict(s)
        sc = latest.get(s.id)
        if sc:
            d["score_total"] = sc.total
        items.append(d)
    return {"items": items}


@router.post("")
def create_supplier(body: SupplierIn, user: User = Depends(require_write),
                    db: Session = Depends(get_db)):
    s = Supplier(tenant_id=user.tenant_id, verification_status="candidate",
                 source_kind="private_network", **body.model_dump())
    db.add(s)
    db.commit()
    return to_dict(s)


def _owned(db: Session, tenant_id: int, supplier_id: int) -> Supplier:
    s = db.get(Supplier, supplier_id)
    if not s or s.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return s


@router.put("/{supplier_id}")
def update_supplier(supplier_id: int, body: SupplierIn,
                    user: User = Depends(require_write), db: Session = Depends(get_db)):
    s = _owned(db, user.tenant_id, supplier_id)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return to_dict(s)


@router.post("/match")
def match_best(body: MatchIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    with SupplierAgent(user.tenant_id) as a:
        r = a.match_best(body.product_id)
    if not r:
        raise HTTPException(status_code=404, detail="该商品暂无可用货源报价")
    return r


@router.get("/forecast")
def forecast(product_id: int | None = None,
             user: User = Depends(require_write), db: Session = Depends(get_db)):
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        if product_id:
            return invoke_supplier(db, ctx, "forecast", product_id)
        return invoke_supplier(db, ctx, "forecast_batch", {}, {})
    except (ActionError, ValueError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc)) from exc


class OfferIn(BaseModel):
    supplier_id: int
    product_id: int
    price: float
    currency: str = "CNY"
    moq: int = 1
    ship_days: int = 7
    in_stock: bool = True
    # 报价诚实性扩展：有效期 / 来源种类 / 核实状态（人工录入即视为已核实来源）。
    valid_until: datetime | None = None
    source_kind: str = "manual"
    verification_status: str = "unverified"

    @field_validator("source_kind")
    @classmethod
    def _check_source_kind(cls, v: str) -> str:
        allowed = {"manual", "scraped", "imported", "api"}
        if v not in allowed:
            raise ValueError("source_kind 必须是 manual/scraped/imported/api 之一")
        return v

    @field_validator("verification_status")
    @classmethod
    def _check_verification_status(cls, v: str) -> str:
        allowed = {"manual", "verified", "unverified", "scraped"}
        if v not in allowed:
            raise ValueError(
                "verification_status 必须是 manual/verified/unverified/scraped 之一")
        return v


@router.post("/offers")
def create_offer(body: OfferIn, user: User = Depends(require_write),
                 db: Session = Depends(get_db)):
    """录入供应商报价单（新商品接入货源的常规流程）。"""
    _owned(db, user.tenant_id, body.supplier_id)
    from ..models import Product as _P

    # 必须校验归属：只查存在性时，A 租户可把报价挂到 B 租户商品上（脏数据 +
    # 借 404/200 差异探测他人商品 ID）。与同文件 _owned 的写法保持一致。
    product = db.get(_P, body.product_id)
    if not product or product.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    if body.price <= 0:
        raise HTTPException(status_code=400, detail="报价必须大于 0")
    o = SupplierOffer(tenant_id=user.tenant_id, supplier_id=body.supplier_id,
                      product_id=body.product_id, price=body.price,
                      currency=body.currency.upper(),
                      moq=body.moq, ship_days=body.ship_days, in_stock=body.in_stock,
                      valid_until=body.valid_until, source_kind=body.source_kind,
                      verification_status=body.verification_status)
    db.add(o)
    db.commit()
    return to_dict(o)


@router.get("/offers")
def offers(product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(SupplierOffer)
            .filter(SupplierOffer.tenant_id == user.tenant_id,
                    SupplierOffer.product_id == product_id).all())
    product = db.get(Product, product_id)
    selected_offer_id = product.selected_offer_id if product else None
    # 批量加载供应商，避免 N+1；一次查询覆盖本页全部 supplier_id。
    supplier_ids = {o.supplier_id for o in rows}
    suppliers = {}
    if supplier_ids:
        for s in (db.query(Supplier)
                  .filter(Supplier.tenant_id == user.tenant_id,
                          Supplier.id.in_(supplier_ids)).all()):
            suppliers[s.id] = s
    items = []
    for o in rows:
        d = to_dict(o)
        s = suppliers.get(o.supplier_id)
        d["supplier"] = (
            {"id": s.id, "name": s.name, "region": s.region,
             "supplier_type": s.supplier_type, "verification_status": s.verification_status,
             "rating": s.rating, "certifications": s.certifications,
             "capabilities": s.capabilities}
            if s else None)
        d["is_selected"] = bool(selected_offer_id and o.id == selected_offer_id)
        items.append(d)
    return {"items": items, "selected_offer_id": selected_offer_id}


@router.get("/{supplier_id}")
def supplier_detail(supplier_id: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    s = _owned(db, user.tenant_id, supplier_id)
    offers_ = (db.query(SupplierOffer)
               .filter(SupplierOffer.tenant_id == user.tenant_id,
                       SupplierOffer.supplier_id == supplier_id).all())
    score = (db.query(SupplierScore)
             .filter(SupplierScore.tenant_id == user.tenant_id,
                     SupplierScore.supplier_id == supplier_id)
             .order_by(SupplierScore.created_at.desc()).first())
    return {**to_dict(s), "offers": [to_dict(o) for o in offers_],
            "score": to_dict(score) if score else None}


@router.post("/{supplier_id}/score")
def score_supplier(supplier_id: int, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    _owned(db, user.tenant_id, supplier_id)
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        return invoke_supplier(db, ctx, "score_supplier", supplier_id)
    except (ActionError, ValueError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc)) from exc
