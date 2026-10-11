"""Listing 路由：AI 生成 / 人工编辑 / 优化 / 一键发布（第九章一键铺货）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..agents.orchestrator import invoke_listing, invoke_review
from ..auth import (
    get_current_user,
    is_impersonating_user,
    require_compliance_approver,
    require_write,
)
from ..db import get_db
from ..models import Listing, ListingReviewDecision, PlatformPublishAttempt, Product, Shop, User
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict
from ..services.ai_actions import ActionError
from ..services.platform_adapters import ADAPTERS
from ..services.review_outputs import approve_review_output
from ..services.workspace_context import resolve_workspace_context


def _invoke(db, user, method, *args):
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        return invoke_listing(db, ctx, method, *args)
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

router = APIRouter(prefix="/listings", tags=["listings"])


class GenerateIn(BaseModel):
    product_id: int
    platform: str = "shopee"
    language: str = "en"


class ListingEdit(BaseModel):
    title: str
    description: str
    bullets: list[str] = []
    keywords: list[str] = []


@router.get("")
def list_listings(product_id: int | None = None, platform: str = "", status: str = "",
                  page_num: int = PageNum, page_size: int = PageSize,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Listing).filter(Listing.tenant_id == user.tenant_id)
    if product_id:
        q = q.filter(Listing.product_id == product_id)
    if platform:
        q = q.filter(Listing.platform == platform)
    if status:
        q = q.filter(Listing.status == status)
    total = q.count()
    rows = (q.order_by(Listing.id.desc())
            .offset((page_num - 1) * page_size).limit(page_size).all())
    titles = {p.id: p.title for p in db.query(Product.id, Product.title)
              .filter(Product.tenant_id == user.tenant_id).all()}
    items = []
    for r in rows:
        d = to_dict(r)
        d["product_title"] = titles.get(r.product_id, "")
        items.append(d)
    return page(items, total, page_num, page_size)


@router.get("/{listing_id}/publication-attempts")
def publication_attempts(listing_id: int, user: User = Depends(get_current_user),
                         db: Session = Depends(get_db), page_num: int = PageNum,
                         page_size: int = PageSize):
    _owned(db, user.tenant_id, listing_id)
    query = (db.query(PlatformPublishAttempt, Shop)
            .join(Shop, PlatformPublishAttempt.shop_id == Shop.id)
            .filter(PlatformPublishAttempt.tenant_id == user.tenant_id,
                    PlatformPublishAttempt.listing_id == listing_id,
                    Shop.tenant_id == user.tenant_id, Shop.archived_at.is_(None)))
    total = query.count()
    rows = (query.order_by(PlatformPublishAttempt.id.desc())
            .offset((page_num - 1) * page_size).limit(page_size).all())
    items = [{"id": attempt.id, "shop_id": shop.id, "shop_name": shop.shop_name,
                       "platform": attempt.platform, "external_id": attempt.external_id,
                       "external_object_type": attempt.external_object_type,
                       "platform_status": attempt.platform_status,
                       "verification_status": attempt.verification_status,
                       "received_at": attempt.received_at,
                       "can_query_submission": attempt.external_object_type == "SUBMISSION"
                       and shop.status == "authorized" and not shop.is_demo
                       and getattr(ADAPTERS.get(shop.platform), "can_submission_status", False)}
                      for attempt, shop in rows]
    return page(items, total, page_num, page_size)


@router.post("/generate")
def generate(body: GenerateIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    p = db.get(Product, body.product_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    return _invoke(db, user, "generate", body.product_id, body.platform, body.language)


@router.put("/{listing_id}")
def edit_listing(listing_id: int, body: ListingEdit,
                 user: User = Depends(require_write), db: Session = Depends(get_db)):
    """人工编辑 Listing（AI 生成后的人工优化是标准运营流程）。"""
    row = _owned(db, user.tenant_id, listing_id)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="标题不能为空")
    row.title = body.title.strip()[:1024]
    row.description = body.description
    row.bullets = [b.strip() for b in body.bullets if b.strip()][:10]
    row.keywords = [k.strip() for k in body.keywords if k.strip()][:20]
    row.updated_at = datetime.utcnow()
    row.last_edited_by = user.id
    db.commit()
    return to_dict(row)


@router.post("/{listing_id}/optimize")
def optimize(listing_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    _owned(db, user.tenant_id, listing_id)
    return _invoke(db, user, "optimize", listing_id)


class PublishIn(BaseModel):
    shop_id: int | None = None    # 指定销售平台店铺 -> 真实/演示上架；缺省 -> 本地模拟


class ReviewApprovalIn(BaseModel):
    note: str


@router.post("/{listing_id}/review")
def review_listing(listing_id: int, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    """显式执行上架前复核，便于审批台展示证据与阻断原因。"""
    _owned(db, user.tenant_id, listing_id)
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        return invoke_review(db, ctx, "review", listing_id)
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/review-queue")
def review_queue(status: str = "manual_required", limit: int = 50,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """合规审批队列：待人工复核的 Listing（合规工作台数据源）。

    默认返回 ``manual_required``（复核 Agent 判定需人工确认的），
    每条附最新的复核决策与理由，供审批人判断。
    """
    if status not in ("manual_required", "rejected", "approved"):
        raise HTTPException(status_code=400, detail="status 必须是 manual_required/rejected/approved")
    # 取每个 Listing 的最新一次复核决策
    sub = (db.query(func.max(ListingReviewDecision.id).label("max_id"))
           .filter(ListingReviewDecision.tenant_id == user.tenant_id,
                   ListingReviewDecision.decision == status)
           .group_by(ListingReviewDecision.listing_id).subquery())
    rows = (db.query(ListingReviewDecision, Listing)
            .join(sub, ListingReviewDecision.id == sub.c.max_id)
            .join(Listing, Listing.id == ListingReviewDecision.listing_id)
            .order_by(ListingReviewDecision.created_at.desc())
            .limit(max(1, min(200, limit))).all())
    items = []
    for decision, listing in rows:
        d = to_dict(decision)
        d["listing_title"] = listing.title
        d["platform"] = listing.platform
        d["listing_status"] = listing.status
        items.append(d)
    return {"items": items, "total": len(items)}


@router.get("/{listing_id}/reviews")
def review_history(listing_id: int, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    _owned(db, user.tenant_id, listing_id)
    rows = (db.query(ListingReviewDecision).filter(
        ListingReviewDecision.tenant_id == user.tenant_id,
        ListingReviewDecision.listing_id == listing_id)
        .order_by(ListingReviewDecision.created_at.desc()).all())
    return [to_dict(row) for row in rows]


@router.post("/{listing_id}/review/approve")
def approve_review(listing_id: int, body: ReviewApprovalIn,
                   user: User = Depends(require_compliance_approver), db: Session = Depends(get_db)):
    """人工审批仅能放行 manual_required，不能覆盖明确规则违规。"""
    _owned(db, user.tenant_id, listing_id)
    listing = db.get(Listing, listing_id)
    if listing.last_edited_by and listing.last_edited_by == user.id:
        raise HTTPException(status_code=403, detail="提交或编辑该 Listing 的人员不能审批自己的内容")
    if not body.note.strip():
        raise HTTPException(status_code=400, detail="人工审批必须填写依据")
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        result = invoke_review(db, ctx, "review", listing_id, approval=True)
        return approve_review_output(db, ctx, listing_id, body.note, result["review_id"])
    except ActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{listing_id}/publish")
def publish(listing_id: int, body: PublishIn | None = None,
            user: User = Depends(require_write), db: Session = Depends(get_db)):
    _owned(db, user.tenant_id, listing_id)
    return _invoke(db, user, "publish", listing_id, body.shop_id if body else None)


@router.delete("/{listing_id}")
def delete_listing(listing_id: int, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    row = _owned(db, user.tenant_id, listing_id)
    db.delete(row)
    db.commit()
    return {"ok": True}


def _owned(db: Session, tenant_id: int, listing_id: int) -> Listing:
    row = db.get(Listing, listing_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Listing 不存在")
    return row
