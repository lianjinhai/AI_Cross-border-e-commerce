"""Listing Tool：上架内容读取（Agent OS §10.4.1 第二批冻结清单）。

为什么第二批才补 Listing
    §10.4 的第一批清单聚焦「机会 → 供应 → 商品 → 渠道」这条主干，Listing 作为
    主干末端的内容对象没有进榜。但它是四个 Agent（compliance / listing /
    listing_review / orchestrator）的共同读取目标，缺它则这些 Agent 的读取点
    无法迁移（DEBT-36）。补批走的是「清单扩展」而不是「改冻结项」——原 22 条
    一字未动。

为什么凭证类字段一律不出现在返回体
    Listing 本身不含凭证，但它是发布链路的入口；一旦有人后续往本模块加
    「带店铺凭证一起返回」的便利方法，凭证就会顺着 Agent 上下文与审计扩散。
    因此本模块的字段口径写死在这里，新增字段必须回到本文件的 `listing_dict`。
"""

from __future__ import annotations

from ..models import Listing
from .base import BaseTool, Reading, as_int, clamp_limit, reading, ts
from .contract import ERR_BAD_PARAM, ToolError, ToolSpec

# 状态枚举取自 models.Listing.status 的注释（draft/published/offline）。
_STATUSES = ("draft", "published", "offline")


def listing_dict(row: Listing) -> dict:
    """Listing 的对外字段集（唯一一份，避免各 Tool 各挑一套字段）。"""
    return {"id": row.id, "product_id": row.product_id, "platform": row.platform,
            "language": row.language, "title": row.title,
            "description": row.description, "bullets": row.bullets or [],
            "keywords": row.keywords or [], "model": row.model,
            "status": row.status, "risk_level": row.risk_level,
            "external_id": row.external_id, "published_at": ts(row.published_at),
            "created_at": ts(row.created_at), "updated_at": ts(row.updated_at)}


class ListingTool(BaseTool):
    name = "listing"
    specs = (
        ToolSpec(tool="listing", method="get_listings", permission="listing:read",
                 writes=False, summary="列出本租户上架内容，可按 Listing/商品/状态过滤"),
    )

    def _get_listings(self, listing_id=None, product_id=None, status: str = "",
                      limit=50) -> Reading:
        # 参数校验先于任何数据库访问（D37 第三节缺陷 1 的教训）。
        lid = None if listing_id is None else as_int(listing_id, "listing_id")
        pid = None if product_id is None else as_int(product_id, "product_id")
        state = (status or "").strip()
        if state and state not in _STATUSES:
            raise ToolError(ERR_BAD_PARAM,
                            "status 必须是 %s 之一，实际 %r"
                            % ("/".join(_STATUSES), status))
        n = clamp_limit(limit)
        query = self.db.query(Listing).filter(
            Listing.tenant_id == self.context.tenant_id)
        if lid is not None:
            query = query.filter(Listing.id == lid)
        if pid is not None:
            query = query.filter(Listing.product_id == pid)
        if state:
            query = query.filter(Listing.status == state)
        rows = query.order_by(Listing.id.desc()).limit(n).all()
        return reading([listing_dict(r) for r in rows], table="listings",
                       listing_ids=[r.id for r in rows])
