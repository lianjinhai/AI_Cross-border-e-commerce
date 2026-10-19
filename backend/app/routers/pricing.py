"""动态定价路由：成本利润计算 / AI 定价建议（第十一章）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.orchestrator import invoke_pricing
from ..agents.pricing import PricingAgent
from ..auth import get_current_user, is_impersonating_user, require_write
from ..db import get_db
from ..models import PricingRecord, Product, User
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict
from ..services.ai_actions import ActionError
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/pricing", tags=["pricing"])


class CalcIn(BaseModel):
    product_id: int
    price: float | None = None
    # 跨境到岸成本（D58）：给出目的国即计入关税/进口 VAT/清关费与路由物流费。
    destination_country: str = ""
    channel_type: str = ""
    site: str = ""
    qty: int = 1
    # 成本上下文（B3）：目标店铺。给出时校验归属（否则 422），响应回显 shop_id；
    # 未给出表示通用试算，响应 is_generic_estimate=True，不得展示为某店铺确认利润。
    shop_id: int | None = None


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
    destination_country = body.destination_country
    if body.shop_id is not None:
        # 成本上下文归属校验（D63 唯一实现）：跨租户/已归档 → 404；
        # 货源店铺不承载销售成本口径 → 422（与订单的 sales/source 语义保持一致）。
        from ..services.shop_scope import active_shop

        shop = active_shop(db, user.tenant_id, body.shop_id)
        if not shop:
            raise HTTPException(status_code=404, detail="店铺不存在或无访问权限")
        if shop.role != "sales":
            raise HTTPException(
                status_code=422,
                detail="货源店铺不承载销售成本口径，请选择销售店铺（sales）或改用通用试算")
        # 市场口径唯一来源：显式目的国 > 店铺市场。缺省即沿用店铺市场，
        # 避免「选了店铺却回显 market=null」的口径空转（前端不得自行推断）。
        destination_country = destination_country or (shop.market or "")
    with PricingAgent(user.tenant_id) as a:
        return a.calc_profit(body.product_id, body.price,
                            destination_country=destination_country,
                            channel_type=body.channel_type, site=body.site,
                            qty=max(int(body.qty or 1), 1), shop_id=body.shop_id)


@router.post("/suggest")
def suggest(body: SuggestIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    p = db.get(Product, body.product_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        return invoke_pricing(db, ctx, "suggest_price", body.product_id)
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
