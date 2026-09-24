"""供应链路由：供应商 CRUD / AI 评分 / 最优货源 / 销量预测 / 报价单录入。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.supplier import SupplierAgent
from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import Supplier, SupplierOffer, SupplierScore, User
from ..serialize import to_dict

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
    with SupplierAgent(user.tenant_id) as a:
        if product_id:
            return a.forecast(product_id)
        return a.forecast_batch()


class OfferIn(BaseModel):
    supplier_id: int
    product_id: int
    price: float
    currency: str = "CNY"
    moq: int = 1
    ship_days: int = 7
    in_stock: bool = True


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
                      moq=body.moq, ship_days=body.ship_days, in_stock=body.in_stock)
    db.add(o)
    db.commit()
    return to_dict(o)


@router.get("/offers")
def offers(product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(SupplierOffer)
            .filter(SupplierOffer.tenant_id == user.tenant_id,
                    SupplierOffer.product_id == product_id).all())
    return {"items": [to_dict(o) for o in rows]}


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
    with SupplierAgent(user.tenant_id) as a:
        return a.score_supplier(supplier_id)
