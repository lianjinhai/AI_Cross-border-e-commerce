"""Launch 服务统一身份与店铺范围；工厂投影另走既有供应门户。"""

from ..models import WorkflowRun
from ..services.action_identity import fresh_context
from ..services.ai_actions import ActionError
from ..services.store_scope import StoreScopeError, resolve_store_scope
from ..services.workspace_context import ROLE_FACTORY_COLLABORATOR, SOURCE_FACTORY
from .kinds import PLATFORM_LAUNCH


class LaunchError(ValueError):
    def __init__(self, code, message, status_code=400, existing_launch_id=None,
                 blockers=None, current_revision=None):
        super().__init__(message)
        self.code, self.status_code = code, status_code
        self.existing_launch_id = existing_launch_id
        self.blockers = blockers
        self.current_revision = current_revision


def launch_context(db, ctx, permission="launch:read"):
    # Factory 身份一律 404 LAUNCH_NOT_FOUND（AC-3.4，不泄露存在性），先于 Scope 解析。
    if ctx.source == SOURCE_FACTORY or ctx.role == ROLE_FACTORY_COLLABORATOR:
        raise LaunchError("LAUNCH_NOT_FOUND", "上线流程不存在", 404)
    try:
        current = fresh_context(db, ctx)
        scope = resolve_store_scope(db, current)
    except (ActionError, StoreScopeError) as exc:
        raise LaunchError("SCOPE_DENIED", str(exc), exc.status_code) from exc
    if not current.has(permission):
        raise LaunchError("PERMISSION_DENIED", "缺少权限：" + permission, 403)
    return current, scope


def require_shop_scope(scope, shop_id):
    try:
        scope.require(shop_id)
    except StoreScopeError as exc:
        raise LaunchError("SCOPE_DENIED", str(exc), exc.status_code) from exc


def owned_launch(db, current, scope, run_id):
    run = db.get(WorkflowRun, run_id, populate_existing=True)
    if (run is None or run.flow_kind != PLATFORM_LAUNCH or run.tenant_id != current.legacy_tenant_id
            or run.workspace_id != current.workspace_id):
        raise LaunchError("LAUNCH_NOT_FOUND", "上线流程不存在", 404)
    require_shop_scope(scope, run.shop_id)
    return run


def get_launch(db, ctx, run_id):
    current, scope = launch_context(db, ctx)
    return owned_launch(db, current, scope, run_id)
