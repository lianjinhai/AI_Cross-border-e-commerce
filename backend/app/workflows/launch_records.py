"""Launch 创建事务：复用商品与草稿，固定定义，实例/步骤/事件一起提交。"""

import hashlib
import json
from copy import deepcopy

from sqlalchemy.exc import IntegrityError

from ..models import Listing, Product, Shop, WorkflowEvent, WorkflowRun, WorkflowStep
from .kinds import PLATFORM_LAUNCH
from .launch_access import LaunchError, launch_context, owned_launch, require_shop_scope
from .profiles import ProfileError, definition_snapshot, select_profile
from .transactions import ensure_write_transaction


def create_launch(db, ctx, product_id, shop_id, request_key, *, environment="CONTRACT_TEST",
                  parent_listing_id=None, previous_run_id=None):
    request, key, fingerprint = _request(product_id, shop_id, request_key, environment, parent_listing_id, previous_run_id)
    ensure_write_transaction(db)
    current, scope = launch_context(db, ctx, "launch:create")
    if not current.has("listing:write") or not current.has("product:read"):
        raise LaunchError("PERMISSION_DENIED", "创建上线流程还需商品读取和 Listing 写权限", 403)
    require_shop_scope(scope, shop_id)
    product, shop = _targets(db, current, product_id, shop_id)
    existing = _replay(db, current, scope, key, fingerprint)
    if existing is not None:
        return existing
    _reject_active(db, current, product_id, shop_id)
    _previous(db, current, scope, previous_run_id, product_id, shop_id)
    parent = _parent(db, current, scope, parent_listing_id, product_id, shop.platform)
    try:
        definition = select_profile(db, current, product_id, shop_id, environment)
        snapshot = definition_snapshot(definition)
    except ProfileError as exc:
        raise LaunchError(exc.code, str(exc), exc.status_code) from exc
    try:
        with db.begin_nested():
            listing = _draft(db, current, product, shop, parent)
            run = WorkflowRun(tenant_id=current.legacy_tenant_id, workspace_id=current.workspace_id,
                              flow_kind=PLATFORM_LAUNCH, template_key=definition.profile_key, name=definition.name,
                              product_id=product.id, shop_id=shop.id, listing_id=listing.id, definition_id=definition.id,
                              workflow_version=definition.version, definition_snapshot=snapshot,
                              definition_hash=definition.definition_hash, environment=environment, platform=shop.platform,
                              market=shop.market, fulfillment_mode=shop.fulfillment_mode, created_by=current.user_id,
                              previous_run_id=previous_run_id, active_slot=1, idempotency_key=key, revision=1,
                              execution_status="NOT_STARTED", platform_status="NOT_SUBMITTED", verification_status="UNKNOWN",
                              context={"launch_request_hash": fingerprint, "launch_request": request})
            db.add(run)
            db.flush()
            _steps_and_event(db, current, run, snapshot)
            db.flush()
    except IntegrityError as exc:
        # 保存点只撤销本次创建；并发赢家可以在同一外层事务重新读取。
        existing = _replay(db, current, scope, key, fingerprint)
        if existing is not None:
            return existing
        _reject_active(db, current, product_id, shop_id)
        raise LaunchError("LAUNCH_CONFLICT", "创建发生约束冲突，请刷新后重试", 409) from exc
    return run


def _request(product_id, shop_id, request_key, environment, parent_id, previous_id):
    if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
        raise LaunchError("IDEMPOTENCY_REQUIRED", "需要非空且不超过 128 字符的幂等键")
    if any(type(value) is not int or value <= 0 for value in (product_id, shop_id)):
        raise LaunchError("TARGET_INVALID", "商品和店铺编号必须为正整数")
    if any(value is not None and (type(value) is not int or value <= 0) for value in (parent_id, previous_id)):
        raise LaunchError("TARGET_INVALID", "草稿和历史流程编号无效")
    if environment not in {"CONTRACT_TEST", "PRODUCTION"}:
        raise LaunchError("ENVIRONMENT_INVALID", "流程环境无效")
    request = {"product_id": product_id, "shop_id": shop_id, "environment": environment,
               "parent_listing_id": parent_id, "previous_run_id": previous_id}
    fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    return request, hashlib.sha256(request_key.encode()).hexdigest(), fingerprint


def _targets(db, ctx, product_id, shop_id):
    product = db.get(Product, product_id, populate_existing=True)
    shop = db.get(Shop, shop_id, populate_existing=True)
    if (product is None or shop is None or product.tenant_id != ctx.legacy_tenant_id
            or shop.tenant_id != ctx.legacy_tenant_id or shop.archived_at is not None):
        raise LaunchError("TARGET_NOT_FOUND", "商品或店铺不存在", 404)
    if shop.role != "sales" or shop.platform == "1688":
        raise LaunchError("SOURCE_STORE", "货源店铺不能作为销售上线目标")
    return product, shop


def _replay(db, ctx, scope, key, fingerprint):
    run = db.query(WorkflowRun).filter_by(tenant_id=ctx.legacy_tenant_id, idempotency_key=key).first()
    if run is None:
        return None
    run = owned_launch(db, ctx, scope, run.id)
    if (run.context or {}).get("launch_request_hash") != fingerprint:
        raise LaunchError("IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同创建请求", 409)
    return run


def _reject_active(db, ctx, product_id, shop_id):
    run = db.query(WorkflowRun).filter_by(tenant_id=ctx.legacy_tenant_id, product_id=product_id,
                                         shop_id=shop_id, active_slot=1).first()
    if run is not None:
        raise LaunchError("ACTIVE_LAUNCH_EXISTS", "此商品在目标店铺已有上线流程", 409, run.id)


def _previous(db, ctx, scope, previous_id, product_id, shop_id):
    if previous_id is None:
        return
    previous = owned_launch(db, ctx, scope, previous_id)
    if (previous.product_id != product_id or previous.shop_id != shop_id or previous.active_slot is not None
            or previous.ended_at is None):
        raise LaunchError("RELAUNCH_NOT_READY", "历史流程尚未结束或不属于同一销售对象", 409)


def _parent(db, ctx, scope, parent_id, product_id, platform):
    if parent_id is None:
        return None
    parent = db.get(Listing, parent_id, populate_existing=True)
    if parent is None or parent.tenant_id != ctx.legacy_tenant_id:
        raise LaunchError("LISTING_NOT_FOUND", "源草稿不存在", 404)
    if parent.shop_id is not None:
        require_shop_scope(scope, parent.shop_id)
    if parent.product_id != product_id or parent.platform != platform:
        raise LaunchError("LISTING_MISMATCH", "源草稿必须属于同一商品和目标平台")
    return parent


def _draft(db, ctx, product, shop, parent):
    content = {name: deepcopy(getattr(parent, name)) for name in
               ("language", "title", "description", "bullets", "keywords", "model")} if parent else {"title": product.title}
    listing = Listing(tenant_id=ctx.legacy_tenant_id, product_id=product.id, shop_id=shop.id,
                      parent_listing_id=parent.id if parent else None, platform=shop.platform,
                      created_by=ctx.user_id, last_edited_by=ctx.user_id, **content)
    db.add(listing)
    db.flush()
    return listing


def _steps_and_event(db, ctx, run, snapshot):
    for definition in snapshot["steps"]:
        db.add(WorkflowStep(tenant_id=run.tenant_id, run_id=run.id, seq=definition["sequence"],
                            step_code=definition["step_code"], business_type=definition["business_type"],
                            execution_mode=definition["execution_mode"], actor=definition["actor"],
                            required=definition["required"], step_status="PENDING", agent="", action="",
                            params=deepcopy(definition), assigned_user_id=ctx.user_id if definition["actor"] == "USER" else None,
                            max_attempts=definition["timeout_policy"]["max_attempts"]))
    db.add(WorkflowEvent(tenant_id=run.tenant_id, workspace_id=run.workspace_id, run_id=run.id,
                         sequence=1, event_type="LaunchCreated", idempotency_key=f"launch:{run.id}:created",
                         actor_id=ctx.user_id, source="USER", profile_version=run.workflow_version,
                         before={}, after={"execution_status": run.execution_status, "platform_status": run.platform_status,
                                           "verification_status": run.verification_status},
                         payload={"product_id": run.product_id, "shop_id": run.shop_id, "listing_id": run.listing_id,
                                  "definition_hash": run.definition_hash, "environment": run.environment}))
