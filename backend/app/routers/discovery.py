"""商品发现路由：趋势 / 关键词扩展 / 选品评分 / 一键选品。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.discovery import DiscoveryAgent
from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import MarketTrend, Product, ProductScore, User
from ..serialize import page, to_dict

router = APIRouter(prefix="/discovery", tags=["discovery"])


class KeywordIn(BaseModel):
    keyword: str


class PickIn(BaseModel):
    limit: int = 3


@router.get("/trends")
def trends(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(MarketTrend).filter(MarketTrend.tenant_id == user.tenant_id)
            .order_by(MarketTrend.search_volume.desc()).all())
    return {"items": [to_dict(r) for r in rows]}


@router.post("/trends/scan")
def scan_trends(user: User = Depends(require_write), db: Session = Depends(get_db)):
    with DiscoveryAgent(user.tenant_id) as a:
        return {"items": a.scan_trends()}


@router.post("/expand")
def expand(body: KeywordIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    with DiscoveryAgent(user.tenant_id) as a:
        return a.expand_keywords(body.keyword)


@router.post("/score/{product_id}")
def score(product_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    with DiscoveryAgent(user.tenant_id) as a:
        return a.score_product(product_id)


@router.post("/pick")
def pick(body: PickIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    if not 1 <= body.limit <= 20:
        raise HTTPException(status_code=400, detail="limit 需在 1-20 之间")
    with DiscoveryAgent(user.tenant_id) as a:
        return a.pick_candidates(body.limit)


@router.get("/performance/{product_id}")
def performance(product_id: int, window_days: int = 30,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """商品真实经营表现（M1 数据飞轮）：真实订单聚合，演示数据不计入。"""
    from ..services.product_performance import ProductNotFound, get_performance

    try:
        return get_performance(db, user.tenant_id, product_id, window_days)
    except ProductNotFound:
        raise HTTPException(status_code=404, detail="商品不存在") from None


class TrendCsvIn(BaseModel):
    csv_text: str
    platform_default: str = "csv"


@router.post("/trends/import")
def import_trends(body: TrendCsvIn, user: User = Depends(require_write),
                  db: Session = Depends(get_db)):
    """导入真实趋势数据（CSV，M5）：表头含 关键词/keyword，可选 搜索量/增长率/竞争度/平台。"""
    from ..services.trend_source import import_csv

    try:
        return import_csv(db, user.tenant_id, body.csv_text, body.platform_default)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/trends/source")
def trends_source(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """趋势数据来源分布（M5）：如实区分 api/csv/builtin，不伪装数据出处。"""
    from ..services.trend_source import trend_source_summary

    return trend_source_summary(db, user.tenant_id)


@router.get("/scores")
def scores(product_id: int | None = None, page_num: int = 1, page_size: int = 20,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(ProductScore).filter(ProductScore.tenant_id == user.tenant_id)
    if product_id:
        q = q.filter(ProductScore.product_id == product_id)
    total = q.count()
    items = (q.order_by(ProductScore.created_at.desc())
             .offset((page_num - 1) * page_size).limit(page_size).all())
    return page([to_dict(r) for r in items], total, page_num, page_size)
