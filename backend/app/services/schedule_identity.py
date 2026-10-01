"""调度身份只由服务器认证Context绑定，每次执行重新核验。"""

from ..models import User
from .action_identity import require_action_permission
from .ai_actions import ActionError
from .workspace_context import resolve_workspace_context


def bind_schedule(db, task, ctx):
    """创建或显式启用时绑定当前真实身份，拒绝代客定时授权。"""
    ctx = require_action_permission(db, ctx, "ai:write")
    if ctx.is_impersonating:
        raise ActionError(403, "代客访问不能绑定自主调度身份")
    if task.tenant_id != ctx.legacy_tenant_id:
        raise ActionError(403, "调度任务归属不一致")
    if task.kind == "trend_scan":
        ctx = require_action_permission(db, ctx, "product:write")
    task.requested_by, task.workspace_id = ctx.user_id, ctx.workspace_id


def schedule_context(db, task):
    """历史无身份、撤权、身份失效及跨租户均显式拒绝。"""
    if not task.requested_by or not task.workspace_id:
        raise ActionError(403, "历史调度缺少可信发起者，请由真实用户重新启用")
    user = db.get(User, task.requested_by, populate_existing=True)
    if user is None or user.tenant_id != task.tenant_id or user.role == "superadmin":
        raise ActionError(403, "调度发起者租户或身份已变化")
    ctx = resolve_workspace_context(db, user)
    if ctx.workspace_id != task.workspace_id:
        raise ActionError(403, "调度 Workspace 绑定已变化")
    ctx = require_action_permission(db, ctx, "ai:write")
    if task.kind == "trend_scan":
        ctx = require_action_permission(db, ctx, "product:write")
    return ctx
