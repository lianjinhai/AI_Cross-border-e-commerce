"""待处理 Action 的统一查询（单一实现）：`routers/actions.py` 与只读 BFF 共用。

为什么单独成模块：待审批 Action 的查询原先是内联在 `routers/actions.py` 里的，
workbench 聚合若另写一份 SQL，就会出现两套「什么算待审批」的口径漂移——一处改了
店铺范围过滤、另一处忘了改，前端两处角标就会互相矛盾。这里把查询收敛为唯一实现，
路由与 BFF 都调用它，`PUBLISH_LISTING` 的店铺数据范围过滤只写一遍。

S3 扩展（能力/契约对齐）：
  * ``action_type=None`` 表示「全部已注册类型」，不再是只查 ``ADJUST_AD_BUDGET``；
  * ``status=None`` 表示「全部状态」；
  * 分页用 ``page_num/page_size`` 并返回总数（此前只有 ``limit``、没有 ``total``，
    前端只能对每种状态各查一页再拼接，无法翻页也无法显示总量）。
"""
from __future__ import annotations

from sqlalchemy import func, or_

from ..models import AiAction
from .store_scope import StoreScopeError, resolve_store_scope

# Action 状态合法值（与 routers/actions.py 对外契约一致）。
VALID_STATUS = frozenset({"PENDING_APPROVAL", "APPROVED", "EXECUTING", "SUCCESS",
                          "FAILED", "REJECTED"})

# 证据里携带 shop_id、需要按店铺数据范围过滤的 Action 类型。
_SCOPED_ACTION_TYPE = "PUBLISH_LISTING"

MAX_PAGE_SIZE = 200


def _shop_id_column():
    """PUBLISH_LISTING 证据中的 shop_id（兼容顶层与 payload 两种历史写法）。"""
    return func.coalesce(AiAction.evidence["shop_id"].as_integer(),
                         AiAction.evidence["payload"]["shop_id"].as_integer())


def _scope_condition(db, ctx, action_type):
    """店铺数据范围收窄条件；返回 None 表示不需要额外过滤。

    ``action_type`` 为单一类型时保持原有严格语义（越权/无范围 → 抛 StoreScopeError）；
    「全部类型」查询则降级为**排除范围外的 PUBLISH_LISTING**——只收窄、绝不放大，
    这样平台/工厂身份仍能看非发布类 Action，不会因缺少销售店铺范围整页 403。
    """
    if action_type is not None and action_type != _SCOPED_ACTION_TYPE:
        return None
    try:
        scope = resolve_store_scope(db, ctx)
    except StoreScopeError:
        if action_type == _SCOPED_ACTION_TYPE:
            raise
        return AiAction.action_type != _SCOPED_ACTION_TYPE
    if scope.shop_ids is None:
        return None
    column = _shop_id_column()
    if action_type == _SCOPED_ACTION_TYPE:
        return column.in_(scope.shop_ids)
    return or_(AiAction.action_type != _SCOPED_ACTION_TYPE, column.in_(scope.shop_ids))


def _base_query(db, ctx, action_type, status, allowed_types=None):
    query = db.query(AiAction).filter(
        AiAction.workspace_id == ctx.workspace_id,
        AiAction.tenant_id == ctx.legacy_tenant_id)
    if action_type:
        query = query.filter(AiAction.action_type == action_type)
    elif allowed_types is not None:
        # 「全部」= 当前身份持有权限的类型集合（不是架构里的全部类型）：
        # 让队列里出现的每一条都能被本人处理，避免「看得见但点不动」。
        query = query.filter(AiAction.action_type.in_(list(allowed_types)))
    if status:
        query = query.filter(AiAction.status == status)
    condition = _scope_condition(db, ctx, action_type)
    return query if condition is None else query.filter(condition)


def _normalize_paging(page_num, page_size):
    page = max(1, int(page_num or 1))
    size = max(1, min(int(page_size or 50), MAX_PAGE_SIZE))
    return page, size


def query_actions(db, ctx, action_type=None, status=None, page_num=1, page_size=50,
                  allowed_types=None):
    """按类型/状态分页查询，返回 ``(rows, total)``（total 不受分页影响）。

    ``action_type=None`` 时用 ``allowed_types`` 限定可见类型（通常=本人持有权限的类型）；
    传 ``None`` 表示不再按类型收窄（仅供内部全量统计，路由层不要这样用）。
    """
    page, size = _normalize_paging(page_num, page_size)
    base = _base_query(db, ctx, action_type, status, allowed_types)
    total = int(base.with_entities(func.count(AiAction.id)).scalar() or 0)
    rows = (base.order_by(AiAction.id.desc())
            .offset((page - 1) * size).limit(size).all())
    return rows, total


def list_actions(db, ctx, action_type, status, limit=50):
    """兼容旧调用：单类型 + 单状态 + limit（无分页游标）。"""
    rows, _ = query_actions(db, ctx, action_type, status, 1, limit)
    return rows


def count_actions(db, ctx, action_type, status=None):
    """同过滤条件下的总数（不受分页影响，供角标使用）。"""
    return int(_base_query(db, ctx, action_type, status)
               .with_entities(func.count(AiAction.id)).scalar() or 0)
