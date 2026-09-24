"""Listing 路由：AI 生成 / 人工编辑 / 优化 / 一键发布（第九章一键铺货）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..agents.listing import ListingAgent
from ..auth import get_current_user, require_compliance_approver, require_write
from ..db import get_db
from ..models import Listing, ListingReviewDecision, Product, User
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict

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


@router.post("/generate")
def generate(body: GenerateIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    p = db.get(Product, body.product_id)
    if not p or p.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    with ListingAgent(user.tenant_id) as a:
        result = a.generate(body.product_id, body.platform, body.language)
    row = db.get(Listing, result["id"])
    row.created_by = row.last_edited_by = user.id
    db.commit()
    return result


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
    with ListingAgent(user.tenant_id) as a:
        result = a.optimize(listing_id)
    listing = db.get(Listing, listing_id)
    listing.last_edited_by = user.id
    db.commit()
    return result


class PublishIn(BaseModel):
    shop_id: int | None = None    # 指定销售平台店铺 -> 真实/演示上架；缺省 -> 本地模拟


class ReviewApprovalIn(BaseModel):
    note: str


@router.post("/{listing_id}/review")
def review_listing(listing_id: int, user: User = Depends(require_write),
                   db: Session = Depends(get_db)):
    """显式执行上架前复核，便于审批台展示证据与阻断原因。"""
    _owned(db, user.tenant_id, listing_id)
    from ..agents.listing_review import ListingReviewAgent
    with ListingReviewAgent(user.tenant_id) as reviewer:
        return reviewer.review(listing_id)


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
    from ..agents.listing_review import ListingReviewAgent
    with ListingReviewAgent(user.tenant_id) as reviewer:
        result = reviewer.review(listing_id)
    if result["decision"] == "rejected":
        raise HTTPException(status_code=400, detail="明确违规或高风险不可人工强制放行")
    if result["decision"] == "approved":
        return {**result, "already_approved": True}
    current = db.get(ListingReviewDecision, result["review_id"])
    approval = ListingReviewDecision(
        tenant_id=user.tenant_id, listing_id=current.listing_id,
        product_id=current.product_id, platform=current.platform,
        decision="approved", reasons=[body.note.strip()],
        evidence={**(current.evidence or {}), "approved_review_id": current.id,
                  "approval_note": body.note.strip()},
        rule_version=current.rule_version, rule_source=current.rule_source,
        reviewer=f"human:{user.username}", human_override=True)
    db.add(approval); db.commit(); db.refresh(approval)
    return to_dict(approval)


@router.post("/{listing_id}/publish")
def publish(listing_id: int, body: PublishIn | None = None,
            user: User = Depends(require_write), db: Session = Depends(get_db)):
    row = _owned(db, user.tenant_id, listing_id)
    shop_id = body.shop_id if body else None
    if shop_id:
        from ..models import PlatformPublishAttempt, Product, Shop
        from ..services import platforms

        shop = db.get(Shop, shop_id)
        if not shop or shop.tenant_id != user.tenant_id or shop.archived_at is not None:
            raise HTTPException(status_code=404, detail="店铺不存在")
        if row.platform != shop.platform:
            raise HTTPException(status_code=400,
                                detail=f"Listing 平台为 {row.platform}，不能发布到 {shop.platform} 店铺")
        product = db.get(Product, row.product_id)
        if not shop.is_demo and shop.status != "authorized":
            raise HTTPException(status_code=400,
                                detail=f"店铺未授权（当前 {shop.status}），请先完成 OAuth 授权")
        from ..agents.listing_review import ListingReviewAgent
        with ListingReviewAgent(user.tenant_id) as reviewer:
            review = reviewer.review(row.id)
        if review["decision"] != "approved":
            label = "驳回" if review["decision"] == "rejected" else "要求人工审批"
            raise HTTPException(status_code=400 if review["decision"] == "rejected" else 409,
                                detail=f"上架复核{label}：" + "；".join(review["reasons"]))
        # 客户端超时重试时直接返回既有结果，避免重复创建平台商品。
        if row.status == "published" and row.external_id:
            return {**to_dict(row), "publish_url": "", "source": "api",
                    "idempotent_replay": True}
        attempt = (db.query(PlatformPublishAttempt)
                   .filter(PlatformPublishAttempt.tenant_id == user.tenant_id,
                           PlatformPublishAttempt.listing_id == row.id,
                           PlatformPublishAttempt.shop_id == shop.id).first())
        if attempt and attempt.status == "succeeded" and attempt.external_id:
            row.status, row.external_id = "published", attempt.external_id
            db.commit()
            return {**to_dict(row), "publish_url": "", "source": "api",
                    "idempotent_replay": True}
        if not attempt:
            import uuid
            attempt = PlatformPublishAttempt(
                tenant_id=user.tenant_id, listing_id=row.id, shop_id=shop.id,
                platform=shop.platform, idempotency_key=str(uuid.uuid4()),
                status="queued", checkpoint={}, requested_by=user.id,
                request_payload={"listing_id": row.id, "shop_id": shop.id})
            db.add(attempt); db.commit()
        def save_checkpoint(values: dict):
            attempt.checkpoint = {**(attempt.checkpoint or {}), **values}
            attempt.status = "processing"; db.commit()
        try:
            attempt.status = "processing"
            attempt.started_at = attempt.started_at or datetime.utcnow()
            db.commit()
            if shop.is_demo:
                result = platforms.demo_publish(row, product)
                source = "demo"
            else:
                result = platforms.publish_to_shop(db, shop, row, product,
                    resume=attempt.checkpoint or {}, checkpoint=save_checkpoint)
                source = "api"
        except platforms.PlatformError as e:
            attempt.status = "uncertain" if attempt.checkpoint else "failed"
            attempt.error = str(e)[:2000]
            attempt.finished_at = datetime.utcnow()
            db.commit()
            raise HTTPException(status_code=400, detail=str(e)) from e
        row.status = "published"
        row.external_id = result.external_id
        row.published_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        attempt.status, attempt.external_id, attempt.error = "succeeded", result.external_id, ""
        attempt.finished_at = datetime.utcnow()
        db.commit()
        return {**to_dict(row), "publish_url": result.url, "source": source}
    # 缺省：本地模拟发布（合规门禁仍生效），返回结构与真实通道保持一致
    with ListingAgent(user.tenant_id) as a:
        try:
            result = a.publish(listing_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return {**result, "source": "local", "publish_url": ""}


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
