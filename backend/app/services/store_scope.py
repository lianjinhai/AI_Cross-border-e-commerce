"""读取既有 Membership 数据范围；不新建身份模型或信任请求中的店铺列表。"""

import json
from dataclasses import dataclass

from sqlalchemy import inspect, text


class StoreScopeError(ValueError):
    def __init__(self, message, status_code=403):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class StoreScope:
    shop_ids: frozenset[int] | None = None  # None 为明确的 Workspace 全域

    def require(self, shop_id):
        if self.shop_ids is not None and shop_id not in self.shop_ids:
            raise StoreScopeError("店铺不存在或不在当前数据范围内", 404)

    def filter(self, query, column):
        return query if self.shop_ids is None else query.filter(column.in_(self.shop_ids))


def _membership(db, user_id, tenant_id):
    tables = set(inspect(db.connection()).get_table_names())
    if "workspace_memberships" not in tables:
        return None, tables
    row = db.execute(text("""
        SELECT wm.id, wm.status, wp.status AS workspace_status, wm.workspace_id
        FROM workspace_memberships wm JOIN workspace_profiles wp ON wp.id=wm.workspace_id
        WHERE wm.user_id=:user_id AND wp.tenant_id=:tenant_id
    """), {"user_id": user_id, "tenant_id": tenant_id}).mappings().one_or_none()
    if row and (row["status"] != "ACTIVE" or row["workspace_status"] != "active"):
        raise StoreScopeError("Workspace Membership 已停用，不允许回退旧身份权限")
    return row, tables


def require_membership_active(db, user_id, tenant_id):
    """无迁移/无 membership 可兼容；已存在但撤销的 membership 必须拒绝。"""
    _membership(db, user_id, tenant_id)


def resolve_store_scope(db, ctx):
    if ctx.workspace_id is None or ctx.legacy_tenant_id is None or ctx.source in {"PLATFORM", "FACTORY"}:
        raise StoreScopeError("当前身份没有销售店铺数据范围")
    row, tables = _membership(db, ctx.user_id, ctx.legacy_tenant_id)
    if row is None:
        if ctx.source == "MEMBERSHIP":
            raise StoreScopeError("Membership 已移除")
        return StoreScope()
    if ctx.source == "MEMBERSHIP" and (row["id"] != ctx.membership_id or row["workspace_id"] != ctx.workspace_id):
        raise StoreScopeError("Membership 与当前 Workspace 不一致")
    if "membership_data_scopes" not in tables:
        raise StoreScopeError("Membership 数据范围表缺失")
    scopes = db.execute(text("SELECT scope_type, scope_ref FROM membership_data_scopes WHERE membership_id=:id"),
                        {"id": row["id"]}).mappings().all()
    allowed = None
    for scope in scopes:
        kind, ref = scope["scope_type"], scope["scope_ref"]
        if kind == "WORKSPACE_ALL":
            continue  # 全域记录不能覆盖同一 Membership 的受限记录。
        if kind != "SHOP_SCOPED":
            raise StoreScopeError("数据范围类型尚不支持，禁止扩大访问")
        try:
            ref = json.loads(ref) if isinstance(ref, str) else ref
        except (ValueError, TypeError) as exc:
            raise StoreScopeError("店铺范围配置损坏") from exc
        ids = ref.get("shop_ids") if isinstance(ref, dict) else None
        if not isinstance(ids, list) or not ids or any(type(value) is not int or value <= 0 for value in ids):
            raise StoreScopeError("店铺范围为空或格式无效")
        allowed = set(ids) if allowed is None else allowed.intersection(ids)
    if allowed is not None and not allowed:
        raise StoreScopeError("店铺范围交集为空")
    return StoreScope(None if allowed is None else frozenset(allowed))
