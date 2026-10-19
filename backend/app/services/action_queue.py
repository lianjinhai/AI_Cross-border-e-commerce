"""待处理 Action 的统一查询（单一实现）：`routers/actions.py` 与只读 BFF 共用。

为什么单独成模块：待审批 Action 的查询原先是内联在 `routers/actions.py` 里的，
workbench 聚合若另写一份 SQL，就会出现两套「什么算待审批」的口径漂移——一处改了
店铺范围过滤、另一处忘了改，前端两处角标就会互相矛盾。这里把查询收敛为唯一实现，
路由与 BFF 都调用它，`PUBLISH_LISTING` 的店铺数据范围过滤只写一遍。
"""
from __future__ import annotations

from sqlalchemy import func

from ..models import AiAction
from .store_scope import resolve_store_scope

# Action 状态合法值（与 routers/actions.py 对外契约一致）。
VALID_STATUS = frozenset({"PENDING_APPROVAL", "APPROVED", "EXECUTING", "SUCCESS",
                          "FAILED", "REJECTED"})

# 证据里携带 shop_id、需要按店铺数据范围过滤的 Action 类型。
_SCOPED_ACTION_TYPE = "PUBLISH_LISTING"


def _shop_id_column():
    """PUBLISH_LISTING 证据中的 shop_id（兼容顶层与 payload 两种历史写法）。"""
    return func.coalesce(AiAction.evidence["shop_id"].as_integer(),
                         AiAction.evidence["payload"]["shop_id"].as_integer())


def _apply_store_scope(db, ctx, query):
    """按当前 Workspace 的店铺数据范围收窄查询（范围外 Action 不可见）。"""
    return resolve_store_scope(db, ctx).filter(query, _shop_id_column())


def list_actions(db, ctx, action_type, status, limit=50):
    """当前 Workspace 指定类型/状态的 Action（倒序，上限 200）。"""
    query = (db.query(AiAction)
             .filter(AiAction.workspace_id == ctx.workspace_id,
                     AiAction.tenant_id == ctx.legacy_tenant_id,
                     AiAction.action_type == action_type,
                     AiAction.status == status))
    if action_type == _SCOPED_ACTION_TYPE:
        query = _apply_store_scope(db, ctx, query)
    return (query.order_by(AiAction.id.desc())
            .limit(max(1, min(int(limit or 50), 200))).all())


def count_actions(db, ctx, action_type, status):
    """同 `list_actions` 过滤条件下的**总数**（不受 limit 影响，供角标使用）。"""
    query = (db.query(func.count(AiAction.id))
             .filter(AiAction.workspace_id == ctx.workspace_id,
                     AiAction.tenant_id == ctx.legacy_tenant_id,
                     AiAction.action_type == action_type,
                     AiAction.status == status))
    if action_type == _SCOPED_ACTION_TYPE:
        query = _apply_store_scope(db, ctx, query)
    return int(query.scalar() or 0)
