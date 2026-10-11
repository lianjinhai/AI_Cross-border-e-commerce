"""Action 身份复核：当前执行人和原发起人均按服务端真实权限检查。"""

from datetime import datetime
from types import SimpleNamespace

from ..models import Tenant, User
from .ai_actions import ActionError, _tenant_id
from .store_scope import StoreScopeError, require_membership_active, resolve_store_scope
from .workspace_context import resolve_workspace_context


def fresh_context(db, ctx):
    tenant_id = _tenant_id(db, ctx)
    try:
        require_membership_active(db, ctx.user_id, tenant_id)
    except StoreScopeError as exc:
        raise ActionError(exc.status_code, str(exc)) from exc
    user = db.get(User, ctx.user_id, populate_existing=True)
    tenant = db.get(Tenant, tenant_id, populate_existing=True)
    if user is None or user.status != "active":
        raise ActionError(403, "发起者身份已失效")
    if (tenant is None or tenant.status != "active"
            or (tenant.license_until and tenant.license_until < datetime.utcnow())):
        raise ActionError(403, "Workspace 服务授权已失效")
    if ctx.is_impersonating:
        if user.role != "superadmin":
            raise ActionError(403, "代客访问身份已失效")
        user = SimpleNamespace(id=user.id, username=user.username,
                               display_name=user.display_name, role="operator",
                               tenant_id=tenant_id)
    current = resolve_workspace_context(
        db, user, trace_id=ctx.trace_id, is_impersonating=ctx.is_impersonating)
    if (current.workspace_id != ctx.workspace_id
            or current.legacy_tenant_id != tenant_id):
        raise ActionError(403, "发起者 Workspace 已变化")
    return current


def require_action_permission(db, ctx, permission):
    current = fresh_context(db, ctx)
    if not current.has(permission):
        raise ActionError(403, "缺少权限：" + permission)
    return current


def requester_context(db, action):
    user = db.get(User, action.requested_by, populate_existing=True)
    if user is None or user.status != "active":
        raise ActionError(403, "发起者身份已失效")
    impersonating = bool((action.evidence or {}).get("_impersonating"))
    if impersonating:
        if user.role != "superadmin":
            raise ActionError(403, "代客访问身份已失效")
        user = SimpleNamespace(id=user.id, username=user.username,
                               display_name=user.display_name, role="operator",
                               tenant_id=action.tenant_id)
    ctx = resolve_workspace_context(db, user, is_impersonating=impersonating)
    if ctx.workspace_id != action.workspace_id:
        raise ActionError(403, "发起者 Workspace 已变化")
    return require_action_permission(db, ctx, action.required_permission)


def require_store_scope(db, ctx, shop_id):
    try:
        resolve_store_scope(db, ctx).require(shop_id)
    except StoreScopeError as exc:
        raise ActionError(exc.status_code, str(exc)) from exc


def require_publish_action_scope(db, ctx, action, requester):
    if action.action_type != "PUBLISH_LISTING":
        return
    payload = (action.evidence or {}).get("payload") or {}
    shop_id = payload.get("shop_id")
    if action.evidence.get("shop_id", shop_id) != shop_id:
        raise ActionError(409, "发布 Action 店铺证据不一致")
    require_store_scope(db, ctx, shop_id)
    require_store_scope(db, requester, shop_id)


def require_publish_approver(db, action):
    """旧审批不能继续代表已撤权的批准人；执行前读取当前服务端权限。"""
    if action.action_type != "PUBLISH_LISTING" or not action.approval_required:
        return
    approval = SimpleNamespace(
        requested_by=action.approved_by, tenant_id=action.tenant_id,
        workspace_id=action.workspace_id, required_permission=action.required_permission,
        evidence={"_impersonating": bool((action.outcome or {}).get("approval_impersonating"))})
    approver = requester_context(db, approval)
    require_store_scope(db, approver, (action.evidence.get("payload") or {}).get("shop_id"))
