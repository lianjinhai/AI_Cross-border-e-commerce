"""私域源头工厂网络：门户自维护、机会匹配、供给候选转化。"""
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..agents.orchestrator import invoke_factory_opportunity
from ..auth import (
    get_current_user,
    hash_password,
    is_impersonating_user,
    require_admin,
    require_write,
)
from ..db import get_db
from ..models import (
    OpportunitySupplierMatch,
    Product,
    Supplier,
    SupplierCatalogProduct,
    SupplierOffer,
    SupplierPortalMember,
    User,
)
from ..serialize import to_dict
from ..services.ai_actions import ActionError
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/factory-network", tags=["factory-network"])


class PortalAccountIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=128)
    display_name: str = ""


class CatalogProductIn(BaseModel):
    factory_sku: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    category: str = ""
    capabilities: list[str] = Field(default_factory=list)
    attrs: dict = Field(default_factory=dict)
    images: list[str] = Field(default_factory=list)
    unit_price: float = Field(gt=0)
    currency: str = "CNY"
    moq: int = Field(ge=1)
    lead_days: int = Field(ge=1, le=365)
    monthly_capacity: int = Field(ge=0)
    available_qty: int = Field(ge=0)
    status: str = "active"


class VerificationIn(BaseModel):
    status: str
    note: str = ""


class MatchIn(BaseModel):
    product_id: int
    limit: int = Field(default=20, ge=1, le=100)


def _supplier(db: Session, tenant_id: int, supplier_id: int) -> Supplier:
    row = db.get(Supplier, supplier_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="源头工厂不存在")
    return row


def _portal_scope(db: Session, user: User) -> SupplierPortalMember:
    member = db.query(SupplierPortalMember).filter(
        SupplierPortalMember.user_id == user.id,
        SupplierPortalMember.tenant_id == user.tenant_id,
        SupplierPortalMember.status == "active").first()
    if user.role != "supplier" or not member:
        raise HTTPException(status_code=403, detail="仅已绑定的工厂门户账号可访问")
    return member


@router.post("/suppliers/{supplier_id}/portal-account")
def provision_portal_account(supplier_id: int, body: PortalAccountIn,
                             user: User = Depends(require_admin),
                             db: Session = Depends(get_db)):
    supplier = _supplier(db, user.tenant_id, supplier_id)
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="用户名已存在")
    account = User(tenant_id=user.tenant_id, username=body.username,
                   password_hash=hash_password(body.password), role="supplier",
                   display_name=body.display_name or supplier.name)
    db.add(account); db.flush()
    db.add(SupplierPortalMember(tenant_id=user.tenant_id, supplier_id=supplier.id,
                                user_id=account.id))
    db.commit(); db.refresh(account)
    return {"user_id": account.id, "supplier_id": supplier.id,
            "username": account.username, "role": account.role}


@router.put("/suppliers/{supplier_id}/verification")
def verify_supplier(supplier_id: int, body: VerificationIn,
                    user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.status not in ("candidate", "contacting", "verified", "rejected", "suspended"):
        raise HTTPException(status_code=400, detail="工厂核验状态不合法")
    supplier = _supplier(db, user.tenant_id, supplier_id)
    supplier.verification_status = body.status
    supplier.note = ((supplier.note + " | ") if supplier.note else "") + body.note.strip()
    db.commit()
    return to_dict(supplier)


@router.get("/portal/me")
def portal_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    member = _portal_scope(db, user)
    return {"account": {"id": user.id, "username": user.username, "role": user.role},
            "supplier": to_dict(_supplier(db, user.tenant_id, member.supplier_id))}


@router.get("/portal/products")
def portal_products(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    member = _portal_scope(db, user)
    rows = db.query(SupplierCatalogProduct).filter(
        SupplierCatalogProduct.tenant_id == user.tenant_id,
        SupplierCatalogProduct.supplier_id == member.supplier_id).all()
    return {"items": [to_dict(x) for x in rows]}


@router.post("/portal/products")
def create_portal_product(body: CatalogProductIn, user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    member = _portal_scope(db, user)
    if body.status not in ("draft", "active", "paused"):
        raise HTTPException(status_code=400, detail="商品状态不合法")
    duplicate = db.query(SupplierCatalogProduct).filter(
        SupplierCatalogProduct.tenant_id == user.tenant_id,
        SupplierCatalogProduct.supplier_id == member.supplier_id,
        SupplierCatalogProduct.factory_sku == body.factory_sku).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="本厂 SKU 已存在")
    row = SupplierCatalogProduct(tenant_id=user.tenant_id, supplier_id=member.supplier_id,
        **body.model_dump(exclude={"currency"}), currency=body.currency.upper(),
        confirmed_at=datetime.utcnow(), updated_by=user.id)
    db.add(row); db.commit(); db.refresh(row)
    return to_dict(row)


@router.put("/portal/products/{catalog_id}")
def update_portal_product(catalog_id: int, body: CatalogProductIn,
                          user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    member = _portal_scope(db, user)
    row = db.get(SupplierCatalogProduct, catalog_id)
    if not row or row.tenant_id != user.tenant_id or row.supplier_id != member.supplier_id:
        raise HTTPException(status_code=404, detail="工厂商品不存在")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.currency = body.currency.upper(); row.confirmed_at = datetime.utcnow()
    row.updated_at = datetime.utcnow(); row.updated_by = user.id
    db.commit(); db.refresh(row)
    return to_dict(row)


def _tokens(*values) -> set[str]:
    text = " ".join(str(v or "").lower() for v in values)
    return {x for x in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text) if len(x) >= 2}


@router.post("/opportunities/match")
def match_opportunity(body: MatchIn, user: User = Depends(require_write),
                      db: Session = Depends(get_db)):
    product = db.get(Product, body.product_id)
    if not product or product.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="市场机会商品不存在")
    target = _tokens(product.title, product.category, *(product.attrs or {}).keys(),
                     *(product.attrs or {}).values())
    rows = (db.query(SupplierCatalogProduct, Supplier)
            .join(Supplier, Supplier.id == SupplierCatalogProduct.supplier_id)
            .filter(SupplierCatalogProduct.tenant_id == user.tenant_id,
                    SupplierCatalogProduct.status == "active",
                    Supplier.verification_status.in_(("candidate", "contacting", "verified")))
            .all())
    ranked = []
    for catalog, supplier in rows:
        offered = _tokens(catalog.title, catalog.category, *catalog.capabilities,
                          *supplier.capabilities)
        overlap = sorted(target & offered)
        capability = min(100.0, 25.0 + len(overlap) * 18.0) if overlap else 0.0
        fresh = bool(catalog.confirmed_at and
                     catalog.confirmed_at >= datetime.utcnow() - timedelta(days=90))
        readiness = (40 if supplier.verification_status == "verified" else 10) + (
            25 if fresh else 0) + (20 if catalog.monthly_capacity > 0 else 0) + (
            15 if catalog.images else 0)
        total = round(capability * 0.65 + readiness * 0.35, 2)
        gaps = []
        if supplier.verification_status != "verified": gaps.append("工厂尚未完成尽调")
        if not fresh: gaps.append("供给数据超过90天未确认")
        if not catalog.images: gaps.append("缺少商品图片")
        if catalog.monthly_capacity <= 0: gaps.append("未填写月产能")
        match = db.query(OpportunitySupplierMatch).filter(
            OpportunitySupplierMatch.tenant_id == user.tenant_id,
            OpportunitySupplierMatch.product_id == product.id,
            OpportunitySupplierMatch.catalog_product_id == catalog.id).first()
        if not match:
            match = OpportunitySupplierMatch(tenant_id=user.tenant_id, product_id=product.id,
                supplier_id=supplier.id, catalog_product_id=catalog.id)
            db.add(match)
        match.capability_score = capability
        match.readiness_score = readiness
        match.total_score = total
        match.matched_capabilities = overlap
        match.gaps = gaps
        match.decision = "matched" if capability >= 50 and not gaps else "due_diligence"
        ranked.append((match, catalog, supplier))
        db.commit()
        # 机会扫描写入经可信产物服务原子保存（Agent 不再直写匹配/报价）。
        # 与 suppliers/purchases 路由一致：ActionError 映射为对应 HTTP 状态，
        # 避免权限不足时以 500 泄漏内部错误。
        ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
        try:
            invoke_factory_opportunity(db, ctx, {"product_ids": [product.id]}, {})
        except ActionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        for match, _, _ in ranked:
            db.refresh(match)
    ranked.sort(key=lambda x: x[0].total_score, reverse=True)
    return {"product": to_dict(product), "items": [
        {**to_dict(m), "catalog_product": to_dict(c), "supplier": to_dict(s),
         "can_promote": m.decision == "ready"} for m, c, s in ranked[:body.limit]]}


@router.get("/opportunities")
def list_opportunities(product_id: int | None = None,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(OpportunitySupplierMatch).filter(
        OpportunitySupplierMatch.tenant_id == user.tenant_id)
    if product_id:
        q = q.filter(OpportunitySupplierMatch.product_id == product_id)
    rows = q.order_by(OpportunitySupplierMatch.created_at.desc()).limit(500).all()
    items = []
    for match in rows:
        items.append({**to_dict(match),
                      "product": to_dict(db.get(Product, match.product_id)),
                      "supplier": to_dict(db.get(Supplier, match.supplier_id)),
                      "catalog_product": to_dict(db.get(SupplierCatalogProduct,
                                                         match.catalog_product_id)),
                      "can_promote": match.decision == "ready"})
    return {"items": items}


@router.post("/matches/{match_id}/promote")
def promote_match(match_id: int, user: User = Depends(require_write),
                  db: Session = Depends(get_db)):
    match = db.get(OpportunitySupplierMatch, match_id)
    if not match or match.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="机会匹配不存在")
    supplier = _supplier(db, user.tenant_id, match.supplier_id)
    catalog = db.get(SupplierCatalogProduct, match.catalog_product_id)
    if match.decision != "ready" or supplier.verification_status != "verified":
        raise HTTPException(status_code=409, detail="工厂尽调或供给资料门禁未通过，不得进入上架链路")
    offer = db.query(SupplierOffer).filter(
        SupplierOffer.tenant_id == user.tenant_id,
        SupplierOffer.supplier_id == supplier.id,
        SupplierOffer.product_id == match.product_id).first()
    if not offer:
        offer = SupplierOffer(tenant_id=user.tenant_id, supplier_id=supplier.id,
                              product_id=match.product_id)
        db.add(offer)
    offer.price = float(catalog.unit_price); offer.moq = catalog.moq
    offer.currency = catalog.currency.upper()
    offer.ship_days = catalog.lead_days; offer.in_stock = catalog.available_qty > 0
    if match.promoted_at is None:
        match.promoted_at = datetime.utcnow()
    db.commit(); db.refresh(offer)
    return {"offer": to_dict(offer), "next_step": "生成 Listing 后执行 Agent 复核和人工审批",
            "auto_published": False}


@router.get("/opportunity-attribution")
def opportunity_attribution(refresh: bool = True,
                            user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    from ..models import OpportunityAttribution
    from ..services.outcome_attribution import reconcile_opportunity_attributions
    if refresh:
        rows = reconcile_opportunity_attributions(db, user.tenant_id)
    else:
        rows = db.query(OpportunityAttribution).filter(
            OpportunityAttribution.tenant_id == user.tenant_id).all()
    return {"currency": "USD", "scope": "promoted_factory_opportunities",
            "items": [to_dict(row) for row in rows]}
