"""商品池路由：CRUD / 详情聚合 / 真实URL与批量采集 / 标准化 / CSV导出。"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.orchestrator import invoke_product
from ..auth import get_current_user, is_impersonating_user, require_write
from ..db import get_db
from ..models import (
    ComplianceReport,
    Listing,
    PricingRecord,
    Product,
    ProductScore,
    Supplier,
    SupplierOffer,
    User,
)
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict
from ..services import mock_market, scraper
from ..services.ai_actions import ActionError
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/products", tags=["products"])


class ProductIn(BaseModel):
    title: str
    sku: str = ""
    category: str = ""
    brand: str = ""
    attrs: dict = {}
    images: list[str] = []
    source_platform: str = "1688"
    source_url: str = ""


class CollectIn(BaseModel):
    source_platform: str = "1688"
    keyword: str = ""
    count: int = 8


class CollectUrlIn(BaseModel):
    url: str


class CollectHtmlIn(BaseModel):
    html: str
    url: str = ""


def _get_owned(db: Session, tenant_id: int, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if not p or p.tenant_id != tenant_id or p.status == "deleted":
        raise HTTPException(status_code=404, detail="商品不存在")
    return p


@router.get("")
def list_products(keyword: str = "", category: str = "", status: str = "",
                  page_num: int = PageNum, page_size: int = PageSize,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Product).filter(Product.tenant_id == user.tenant_id,
                                 Product.status != "deleted")
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(Product.title.like(like) | Product.sku.like(like))
    if category:
        q = q.filter(Product.category == category)
    if status:
        q = q.filter(Product.status == status)
    total = q.count()
    items = (q.order_by(Product.id.desc())
             .offset((page_num - 1) * page_size).limit(page_size).all())
    latest_score = {}
    pids = [p.id for p in items]
    if pids:
        rows = (db.query(ProductScore)
                .filter(ProductScore.tenant_id == user.tenant_id,
                        ProductScore.product_id.in_(pids))
                .order_by(ProductScore.created_at.desc()).all())
        for r in rows:
            latest_score.setdefault(r.product_id, r)
    out = []
    for p in items:
        d = to_dict(p)
        s = latest_score.get(p.id)
        if s:
            d["score_total"] = s.total
        out.append(d)
    return page(out, total, page_num, page_size)


@router.post("")
def create_product(body: ProductIn, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    p = Product(tenant_id=user.tenant_id, sku=body.sku or mock_market.gen_sku(),
                title=body.title, category=body.category, brand=body.brand,
                attrs=body.attrs, images=body.images,
                source_platform=body.source_platform, source_url=body.source_url)
    db.add(p)
    db.commit()
    return to_dict(p)


@router.post("/collect_url")
def collect_by_url(body: CollectUrlIn, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    """真实采集（多级管线）：静态 HTTP → 无头浏览器渲染，抓取商品页入库。"""
    try:
        item, engine = scraper.fetch_product_auto(db, body.url.strip())
    except scraper.ScrapeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"{e}。该站点可能需要登录/有验证码，可改用「粘贴网页源码」方式采集",
        ) from e
    return _insert_scraped(db, user.tenant_id, item, engine)


def _insert_scraped(db: Session, tenant_id: int, item: dict, engine: str) -> dict:
    p = Product(
        tenant_id=tenant_id, sku=mock_market.gen_sku(), title=item["title"],
        category="", brand="",
        attrs={"sale_price": item["price"] or 19.99, "supplier_price": round((item["price"] or 19.99) * 6.5, 2),
               "source_desc": item["description"][:200] if item["description"] else ""},
        images=item["images"] or [f"/api/placeholder/{mock_market.gen_sku()}.svg"],
        source_platform=item["domain"], source_url=item["source_url"],
    )
    db.add(p)
    db.commit()
    return {"collected": 1, "engine": engine, "item": to_dict(p), "parsed": item}


@router.post("/collect_html")
def collect_by_html(body: CollectHtmlIn, user: User = Depends(require_write),
                    db: Session = Depends(get_db)):
    """Level 3 兜底：粘贴网页源码解析入库（应对登录墙/验证码/强反爬站点）。

    用法：浏览器打开商品页 → 右键「查看网页源代码」全选复制 → 粘贴。
    """
    html = (body.html or "").strip()
    if len(html) < 500:
        raise HTTPException(status_code=400, detail="网页源码内容过短，请复制完整源码")
    url = body.url.strip() or "https://manual-input.local/page"
    try:
        item = scraper.parse_product_html(html, url)
    except scraper.ScrapeError as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {e}") from e
    return _insert_scraped(db, user.tenant_id, item, "manual")


@router.get("/export")
def export_csv(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """导出商品池 CSV（utf-8-sig，Excel 直开不乱码）。"""
    rows = (db.query(Product)
            .filter(Product.tenant_id == user.tenant_id, Product.status != "deleted")
            .order_by(Product.id).all())
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "sku", "title", "category", "sale_price",
                     "supplier_price", "source_platform", "status", "created_at"])
    for p in rows:
        a = p.attrs or {}
        writer.writerow([p.id, p.sku, p.title, p.category,
                         a.get("sale_price", ""), a.get("supplier_price", ""),
                         p.source_platform, p.status,
                         p.created_at.strftime("%Y-%m-%d %H:%M:%S")])
    data = buf.getvalue().encode("utf-8-sig")
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=products.csv"})


@router.get("/{product_id}")
def product_detail(product_id: int, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    p = _get_owned(db, user.tenant_id, product_id)
    scores = (db.query(ProductScore)
              .filter(ProductScore.tenant_id == user.tenant_id, ProductScore.product_id == product_id)
              .order_by(ProductScore.created_at.desc()).limit(5).all())
    offers = (db.query(SupplierOffer, Supplier)
              .join(Supplier, Supplier.id == SupplierOffer.supplier_id)
              .filter(SupplierOffer.tenant_id == user.tenant_id,
                      SupplierOffer.product_id == product_id).all())
    listings = (db.query(Listing)
                .filter(Listing.tenant_id == user.tenant_id, Listing.product_id == product_id)
                .order_by(Listing.id.desc()).all())
    pricing = (db.query(PricingRecord)
               .filter(PricingRecord.tenant_id == user.tenant_id,
                       PricingRecord.product_id == product_id)
               .order_by(PricingRecord.created_at.desc()).first())
    comp = (db.query(ComplianceReport)
            .filter(ComplianceReport.tenant_id == user.tenant_id,
                    ComplianceReport.target_type == "product",
                    ComplianceReport.product_id == product_id)
            .order_by(ComplianceReport.created_at.desc()).first())
    return {
        **to_dict(p),
        "scores": [to_dict(s) for s in scores],
        "offers": [{**to_dict(o), "supplier_name": s.name} for o, s in offers],
        "listings": [to_dict(item) for item in listings],
        "pricing": to_dict(pricing) if pricing else None,
        "compliance": to_dict(comp) if comp else None,
    }


@router.put("/{product_id}")
def update_product(product_id: int, body: ProductIn,
                   user: User = Depends(require_write), db: Session = Depends(get_db)):
    p = _get_owned(db, user.tenant_id, product_id)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    p.updated_at = datetime.utcnow()
    db.commit()
    return to_dict(p)


@router.delete("/{product_id}")
def delete_product(product_id: int, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    p = _get_owned(db, user.tenant_id, product_id)
    p.status = "deleted"
    db.commit()
    return {"ok": True}


@router.post("/collect")
def collect_products(body: CollectIn, user: User = Depends(require_write),
                     db: Session = Depends(get_db)):
    """模拟从 1688 等平台采集商品进入商品池（第六章采集流程演示）。"""
    if not 1 <= body.count <= 50:
        raise HTTPException(status_code=400, detail="count 需在 1-50 之间")
    return mock_market.collect(db, user.tenant_id, body.source_platform,
                               body.keyword or None, body.count)


@router.post("/{product_id}/standardize")
def standardize(product_id: int, user: User = Depends(require_write),
                db: Session = Depends(get_db)):
    _get_owned(db, user.tenant_id, product_id)
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        return invoke_product(db, ctx, "standardize", product_id)
    except (ActionError, ValueError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc)) from exc
