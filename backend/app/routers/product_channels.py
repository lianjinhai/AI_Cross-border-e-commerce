"""商品渠道聚合：GET /api/products/{id}/channels（P1，独立文件避免 products.py 超警戒线）。

只读聚合该商品各销售店铺的当前活跃 Launch 与历史轮次；Scope 外店铺不出现也不计入总数
（AC-12.1）；同平台多店不合并（AC-12.3）；母稿 Listing.status 不渲染为「已核验在售」（AC-12.2）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user, is_impersonating_user
from ..db import get_db
from ..models import User
from ..services.workspace_context import resolve_workspace_context
from ..workflows import launch_dto
from ..workflows.launch_access import LaunchError, launch_context

router = APIRouter(prefix="/products", tags=["product-channels"])


@router.get("/{product_id}/channels")
def product_channels(product_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    ctx = resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))
    try:
        current, scope = launch_context(db, ctx, "product:read")
        return launch_dto.channels_dto(db, current, scope, product_id)
    except LaunchError as exc:
        raise HTTPException(status_code=exc.status_code,
                            detail={"code": exc.code, "message": str(exc),
                                    "blockers": exc.blockers or []}) from exc
