"""商品素材注册、历史分页与独立核验；不接受外部传入的 Workspace 身份。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..auth import (
    get_current_user,
    is_impersonating_user,
    require_compliance_approver,
    require_write,
)
from ..db import get_db
from ..models import ProductAsset, User
from ..pagination import PageNum, PageSize
from ..serialize import page, to_dict
from ..services import product_assets
from ..services.asset_schema import AssetRegistration
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/products", tags=["product-assets"])


class AssetIn(AssetRegistration):
    shop_id: int = Field(gt=0, strict=True)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop_id: int = Field(gt=0, strict=True)
    expected_version: int = Field(gt=0, strict=True)
    decision: Literal["VERIFIED", "REJECTED"]
    evidence_ref: str = Field(min_length=1, max_length=2048)
    reason: str = Field(min_length=1, max_length=2000)


def _context(db, user):
    return resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))


@router.get("/{product_id}/assets")
def assets(product_id: int, shop_id: int = Query(..., gt=0), page_num: int = PageNum, page_size: int = PageSize,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        items, total = product_assets.asset_page(db, _context(db, user), product_id, shop_id, page_num, page_size)
        return page([to_dict(item) for item in items], total, page_num, page_size)
    except product_assets.AssetError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/{product_id}/assets")
def register(product_id: int, body: AssetIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    try:
        row = product_assets.register_asset(db, _context(db, user), product_id, body.shop_id,
                                            body.model_dump(exclude={"shop_id"}))
        db.commit()
        return to_dict(row)
    except product_assets.AssetError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/{product_id}/assets/{asset_id}/verify")
def verify(product_id: int, asset_id: int, body: ReviewIn,
           user: User = Depends(require_compliance_approver), db: Session = Depends(get_db)):
    row = db.get(ProductAsset, asset_id)
    if row is None or row.product_id != product_id or row.tenant_id != user.tenant_id:
        raise HTTPException(404, "素材不存在")
    try:
        verified = product_assets.verify_asset(db, _context(db, user), asset_id, **body.model_dump())
        db.commit()
        return to_dict(verified)
    except product_assets.AssetError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
