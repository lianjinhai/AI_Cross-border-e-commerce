"""商品池路由：CRUD / 详情聚合 / 真实URL与批量采集 / 标准化 / CSV导出。"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from ..agents.orchestrator import invoke_product
from ..auth import get_current_user, is_impersonating_user, require_write
from ..db import get_db
from ..models import (
    ComplianceReport,
    Listing,
    PricingRecord,
    Product,
    ProductAsset,
    ProductScore,
    Supplier,
    SupplierOffer,
    User,
    WorkflowRun,
)
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict
from ..services import mock_market, scraper
from ..services.ai_actions import ActionError
from ..services.costing import best_purchase, cost_completeness, offer_state, to_cny
from ..services.product_performance import read_performance
from ..services.workspace_context import resolve_workspace_context
from ..workflows import launch_dto
from ..workflows.launch_access import LaunchError, launch_context

router = APIRouter(prefix="/products", tags=["products"])


class ProductIn(BaseModel):
    title: str
    sku: str = ""
    category: str = ""
    brand: str = ""
    # HS 归类（关税计算依据）。None 表示「本次未提交该字段」，PUT 时保留原值，
    # 避免旧前端表单未带该字段就把已维护的 HS 编码清空。
    hs_code: str | None = None
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
    # 轻量列表信号：3 条批量聚合查询覆盖本页全部 product_id（COUNT ... GROUP BY），
    # 不引入 N+1，也不改变任何既有列表键。
    signals: dict[int, dict] = {}
    if pids:
        offer_rows = (db.query(SupplierOffer.product_id, func.count(SupplierOffer.id))
                      .filter(SupplierOffer.tenant_id == user.tenant_id,
                              SupplierOffer.product_id.in_(pids))
                      .group_by(SupplierOffer.product_id).all())
        offers_map = {pid: c for pid, c in offer_rows}
        channel_rows = (db.query(WorkflowRun.product_id,
                                 func.count(distinct(WorkflowRun.shop_id)))
                        .filter(WorkflowRun.tenant_id == user.tenant_id,
                                WorkflowRun.flow_kind == "PLATFORM_LAUNCH",
                                WorkflowRun.product_id.in_(pids))
                        .group_by(WorkflowRun.product_id).all())
        channels_map = {pid: c for pid, c in channel_rows}
        asset_rows = (db.query(ProductAsset.product_id, func.count(ProductAsset.id))
                      .filter(ProductAsset.tenant_id == user.tenant_id,
                              ProductAsset.verification_status == "VERIFIED",
                              ProductAsset.product_id.in_(pids))
                      .group_by(ProductAsset.product_id).all())
        assets_map = {pid: c for pid, c in asset_rows}
        for pid in pids:
            signals[pid] = {"offers_count": offers_map.get(pid, 0),
                            "channels_count": channels_map.get(pid, 0),
                            "assets_verified_count": assets_map.get(pid, 0)}

    out = []
    for p in items:
        d = to_dict(p)
        s = latest_score.get(p.id)
        if s:
            d["score_total"] = s.total
        d["signals"] = signals.get(p.id, {"offers_count": 0, "channels_count": 0,
                                          "assets_verified_count": 0})
        out.append(d)
    return page(out, total, page_num, page_size)


@router.post("")
def create_product(body: ProductIn, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    p = Product(tenant_id=user.tenant_id, sku=body.sku or mock_market.gen_sku(),
                title=body.title, category=body.category, brand=body.brand,
                hs_code=(body.hs_code or "").strip(),
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
    data = body.model_dump()
    # hs_code 未提交时保留原值（None 语义），其余字段与既有行为一致。
    hs_code = data.pop("hs_code", None)
    for k, v in data.items():
        setattr(p, k, v)
    if hs_code is not None:
        p.hs_code = hs_code.strip()
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


class SelectedOfferIn(BaseModel):
    offer_id: int | None = None


@router.put("/{product_id}/selected-offer")
def set_selected_offer(product_id: int, body: SelectedOfferIn,
                       user: User = Depends(require_write), db: Session = Depends(get_db)):
    """选定/清除某商品的指定报价（costing 优先采用）。

    - 商品不归本租户 → 404 商品不存在；
    - offer_id 给定但报价行不存在或不属本租户 → 404 报价不存在或无访问权限；
    - 报价存在但 offer.product_id != product_id → 400 报价不属于该商品；
    - offer_id 为 null → 显式清除选择（幂等）。
    成功 200 返回 {product_id, selected_offer_id, updated_at}。重复 PUT 同一值幂等。
    """
    p = _get_owned(db, user.tenant_id, product_id)
    if body.offer_id is None:
        p.selected_offer_id = None
    else:
        offer = db.get(SupplierOffer, body.offer_id)
        if not offer or offer.tenant_id != user.tenant_id:
            raise HTTPException(status_code=404, detail="报价不存在或无访问权限")
        if offer.product_id != product_id:
            raise HTTPException(status_code=400, detail="报价不属于该商品")
        p.selected_offer_id = body.offer_id
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return {"product_id": product_id, "selected_offer_id": p.selected_offer_id,
            "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M:%S")}


def _offer_price_cny(db: Session, tenant_id: int, offer: SupplierOffer) -> float | None:
    """把报价价格折算成人民币；缺汇率时退化为原始价格（不阻断 overview）。"""
    try:
        return round(to_cny(db, tenant_id, float(offer.price), offer.currency), 2)
    except ValueError:
        return round(float(offer.price), 2)


def _derive_stage(offers_count: int, channels_count: int, verified_assets: int,
                  has_orders: bool) -> dict:
    """由真实字段推导商品阶段（中文 reasons 必须指向实际读到的字段）。"""
    if has_orders:
        return {"key": "OPERATING", "label": "运营中",
                "reasons": ["已有真实订单，商品进入常态化运营阶段"]}
    if channels_count >= 1:
        return {"key": "LAUNCHING", "label": "上架中",
                "reasons": ["已建立 %d 个销售渠道，等待正式开售" % channels_count]}
    if offers_count >= 1:
        return {"key": "CHANNEL_PENDING", "label": "待上架渠道",
                "reasons": ["已有 %d 个供应商报价，但尚未创建销售渠道" % offers_count]}
    if verified_assets >= 1:
        return {"key": "SUPPLY_READY", "label": "货源就绪",
                "reasons": ["暂无可售报价，但已具备 %d 个已核验素材" % verified_assets]}
    return {"key": "NO_SUPPLY", "label": "无货源",
            "reasons": ["该商品暂无任何供应商报价，且无可核验素材"]}


@router.get("/{product_id}/overview")
def product_overview(product_id: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """商品全局概览（V9.1 原型 04/05/06 聚合入口）。

    顶层键固定：product / supply / channels / performance / stage / generated_at。
    channels 复用 product_channels 的 channels_dto（同一函数，不复制 SQL）；
    performance 复用 product_performance.read_performance，无可靠数据时为 null（绝不臆造 0）。
    """
    p = _get_owned(db, user.tenant_id, product_id)
    tenant_id = user.tenant_id

    offers = (db.query(SupplierOffer)
              .filter(SupplierOffer.tenant_id == tenant_id,
                      SupplierOffer.product_id == product_id).all())
    offers_count = len(offers)
    selected_offer_id = p.selected_offer_id

    selected_offer_price_cny = None
    if selected_offer_id is not None:
        sel = db.get(SupplierOffer, selected_offer_id)
        if sel and sel.tenant_id == tenant_id and sel.product_id == product_id:
            selected_offer_price_cny = _offer_price_cny(db, tenant_id, sel)

    # min_offer_price_cny 语义是「真正的最低在库价」（供与选定价对比），
    # 必须 honor_selection=False——否则选定缺货高价报价后该字段被覆盖成选定价，
    # 前端「最低在库报价」标签就会撒谎。cost_offer_id 则是成本引擎实际采用的
    # 报价（选定优先），供前端在选定失效时标注回退去向。
    min_offer_price_cny, _min_offer_id = best_purchase(
        db, tenant_id, p, honor_selection=False)
    _, cost_offer_id = best_purchase(db, tenant_id, p)
    cost_missing, cost_complete = cost_completeness(db, tenant_id, p)
    # 选定报价诚实信号：唯一实现见 costing.offer_state（三档：MISSING 失效 /
    # EXPIRED·OUT_OF_STOCK·UNVERIFIED 保留偏好但阻断对外承诺 / OK）。
    # selected_offer_missing 仅为向后兼容保留（= state 为 MISSING）。
    sel_state, sel_limits = offer_state(db, tenant_id, p)
    selected_offer_missing = sel_state == "MISSING"
    supply = {
        "offers_count": offers_count,
        "selected_offer_id": selected_offer_id,
        "selected_offer_price_cny": selected_offer_price_cny,
        "min_offer_price_cny": min_offer_price_cny,
        "cost_missing": cost_missing,
        "cost_complete": cost_complete,
        "selected_offer_missing": selected_offer_missing,
        "selected_offer_state": sel_state,
        "selected_offer_limits": sel_limits,
        "cost_offer_id": cost_offer_id,
    }

    # channels：直接复用 product_channels 的聚合函数（同一实现，零 SQL 复制）。
    channels: dict = {"product": {"id": p.id, "title": p.title, "sku": p.sku},
                      "total": 0, "channels": []}
    try:
        ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
        current, scope = launch_context(db, ctx, "product:read")
        channels = launch_dto.channels_dto(db, current, scope, product_id)
    except Exception:
        # 无 workspace 上下文或渠道渲染异常时降级为空渠道，绝不让 overview 500。
        pass

    # performance：复用 read_performance；无真实订单数据 → null（不臆造 0）。
    performance: object | None = None
    try:
        perf = read_performance(db, tenant_id, product_id)
        if perf.get("has_data"):
            performance = perf
    except Exception:
        performance = None

    verified_assets = (db.query(ProductAsset)
                       .filter(ProductAsset.tenant_id == tenant_id,
                               ProductAsset.product_id == product_id,
                               ProductAsset.verification_status == "VERIFIED").count())

    channels_count = int(channels.get("total", 0))
    has_orders = bool(performance and performance.get("units_sold", 0) > 0)
    stage = _derive_stage(offers_count, channels_count, int(verified_assets), has_orders)

    return {
        "product": to_dict(p),
        "supply": supply,
        "channels": channels,
        "performance": performance,
        "stage": stage,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
