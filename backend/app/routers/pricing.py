"""动态定价路由：成本利润计算 / AI 定价建议（第十一章）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.pricing import PricingAgent
from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import PricingRecord, Product, User
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict

router = APIRouter(prefix="/pricing", tags=["pricing"])


class CalcIn(BaseModel):
    product_id: int
    price: float | None = None


class SuggestIn(BaseModel):
    product_id: int


@router.get("")
def list_records(product_id: int | None = None, page_num: int = PageNum, page_size: int = PageSize,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(PricingRecord).filter(PricingRecord.tenant_id == user.tenant_id)
    if product_id:
        q = q.filter(PricingRecord.product_id == product_id)
    total = q.count()
    rows = (q.order_by(PricingRecord.created_at.desc())
            .offset((page_num - 1) * page_size).limit(page_size).all())
    titles = {p.id: p.title for p in db.query(Product.id, Product.title)
              .filter(Product.tenant_id == user.tenant_id).all()}
    items = []
    for r in rows:
        d = to_dict(r)
        d["product_title"] = titles.get(r.product_id, "")
        items.append(d)
    return page(items, total, page_num, page_size)


@router.post("/calc")
def calc(body: CalcIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    p = db.get(Product, body.product_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    with PricingAgent(user.tenant_id) as a:
        return a.calc_profit(body.product_id, body.price)


@router.post("/suggest")
def suggest(body: SuggestIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    p = db.get(Product, body.product_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    with PricingAgent(user.tenant_id) as a:
        return a.suggest_price(body.product_id)
