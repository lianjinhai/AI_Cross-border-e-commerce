"""店铺可见性守卫：归档（软删除）店铺对所有业务入口一律视为不存在。

背景：DELETE /api/shops/{id} 已改为归档式软删除（见 routers/shops.py）。
店铺行仍在库中（订单/采购单/结算单需要保留引用），因此每个直接读取店铺的
业务入口都必须显式排除 archived_at 非空的行，否则被删除的店铺仍能被拉单、
发布或代发，形成「已删除但可用」的越权路径。

用法：
    shop = active_shop(db, tenant_id, shop_id)   # 返回 None 表示不存在/不可用
"""
from sqlalchemy.orm import Session

from ..models import Shop


def active_shop(db: Session, tenant_id: int, shop_id: int) -> Shop | None:
    """按租户读取可用店铺；不存在、跨租户或已归档均返回 None。"""
    shop = db.get(Shop, shop_id)
    if not shop or shop.tenant_id != tenant_id or shop.archived_at is not None:
        return None
    return shop
