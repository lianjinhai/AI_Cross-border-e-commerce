"""Action 身份复核：当前执行人和原发起人均按服务端真实权限检查。"""

from datetime import datetime
from types import SimpleNamespace

from ..models import Tenant, User
from .ai_actions import ActionError, _tenant_id
from .workspace_context import resolve_workspace_context


def fresh_context(db, ctx):
    tenant_id = _tenant_id(db, ctx)
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
