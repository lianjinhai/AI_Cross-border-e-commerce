"""Profile 持久化、发布与确定性选择；调用方负责事务提交。"""

from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ..models import Product, Shop, WorkflowTemplate
from ..services.action_identity import fresh_context
from ..services.ai_actions import ActionError
from ..services.regions import store_market
from ..services.store_scope import StoreScopeError, resolve_store_scope
from .kinds import PLATFORM_LAUNCH
from .profile_schema import FULFILLMENT_MODES, ProfileDefinition
from .transactions import ensure_write_transaction


class ProfileError(ValueError):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def _context(db, ctx, write=False):
    try:
        current = fresh_context(db, ctx)
        scope = resolve_store_scope(db, current)
    except (ActionError, StoreScopeError) as exc:
        raise ProfileError("SCOPE_DENIED", str(exc), exc.status_code) from exc
    if write and (not current.can_admin() or scope.shop_ids is not None):
        raise ProfileError("PROFILE_FORBIDDEN", "仅 Workspace 全域 OWNER 可管理流程定义", 403)
    if not write and not current.has("product:read"):
        raise ProfileError("PROFILE_FORBIDDEN", "没有流程读取权限", 403)
    return current, scope


def _owned(db, tenant_id, profile_id):
    row = db.get(WorkflowTemplate, profile_id, populate_existing=True)
    if row is None or row.tenant_id != tenant_id or row.flow_kind != PLATFORM_LAUNCH:
        raise ProfileError("PROFILE_NOT_FOUND", "流程定义不存在", 404)
    return row


def _values(definition):
    values = definition.model_dump()
    return {**values, "key": definition.profile_key, "definition_hash": definition.fingerprint()}


def create_profile(db, ctx, payload):
    ensure_write_transaction(db)
    current, _ = _context(db, ctx, write=True)
    definition = ProfileDefinition.model_validate(payload)
    row = WorkflowTemplate(tenant_id=current.legacy_tenant_id, flow_kind=PLATFORM_LAUNCH,
                           definition_status="DRAFT", **_values(definition))
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        raise ProfileError("PROFILE_VERSION_EXISTS", "同一流程版本已存在，请新建版本", 409) from exc
    return row


def update_draft(db, ctx, profile_id, payload, expected_hash):
    current, _ = _context(db, ctx, write=True)
    row = _owned(db, current.legacy_tenant_id, profile_id)
    definition = ProfileDefinition.model_validate(payload)
    if (definition.profile_key, definition.version) != (row.profile_key, row.version):
        raise ProfileError("PROFILE_IDENTITY_CHANGED", "不能更改定义标识和版本", 409)
    _change(db, row, expected_hash, _values(definition))
    return row


def publish_profile(db, ctx, profile_id, expected_hash):
    current, _ = _context(db, ctx, write=True)
    row = _owned(db, current.legacy_tenant_id, profile_id)
    definition_snapshot(row)  # 重新校验完整 DAG 和内容摘要。
    _change(db, row, expected_hash, {"definition_status": "PUBLISHED"})
    return row


def _change(db, row, expected_hash, values):
    changed = db.execute(update(WorkflowTemplate).where(
        WorkflowTemplate.id == row.id, WorkflowTemplate.tenant_id == row.tenant_id,
        WorkflowTemplate.flow_kind == PLATFORM_LAUNCH, WorkflowTemplate.definition_status == "DRAFT",
        WorkflowTemplate.definition_hash == expected_hash).values(**values),
        execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        raise ProfileError("PROFILE_IMMUTABLE_OR_STALE", "已发布定义不可修改，或草稿已变更", 409)
    db.flush()
    db.refresh(row)


def retire_profile(db, ctx, profile_id):
    current, _ = _context(db, ctx, write=True)
    row = _owned(db, current.legacy_tenant_id, profile_id)
    if row.definition_status != "PUBLISHED":
        raise ProfileError("PROFILE_STATE_INVALID", "仅已发布定义可退役", 409)
    changed = db.execute(update(WorkflowTemplate).where(
        WorkflowTemplate.id == row.id, WorkflowTemplate.definition_status == "PUBLISHED"
    ).values(definition_status="RETIRED"), execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        raise ProfileError("PROFILE_STATE_INVALID", "定义状态已经变化", 409)
    db.refresh(row)
    return row


def definition_snapshot(row):
    payload = {name: getattr(row, name) for name in ProfileDefinition.model_fields}
    try:
        definition = ProfileDefinition.model_validate(payload)
        fingerprint = definition.fingerprint()
    except (ValidationError, ValueError) as exc:
        raise ProfileError("PROFILE_INTEGRITY_ERROR", "已存定义结构损坏", 409) from exc
    if fingerprint != row.definition_hash:
        raise ProfileError("PROFILE_INTEGRITY_ERROR", "流程定义与发布摘要不一致", 409)
    return definition.model_dump()


def select_profile(db, ctx, product_id, shop_id, environment):
    current, scope = _context(db, ctx)
    try:
        scope.require(shop_id)
    except StoreScopeError as exc:
        raise ProfileError("SCOPE_DENIED", str(exc), exc.status_code) from exc
    shop = db.get(Shop, shop_id, populate_existing=True)
    product = db.get(Product, product_id, populate_existing=True)
    if (shop is None or product is None or shop.tenant_id != current.legacy_tenant_id
            or product.tenant_id != current.legacy_tenant_id or shop.archived_at is not None):
        raise ProfileError("TARGET_NOT_FOUND", "目标商品或店铺不存在", 404)
    if shop.role != "sales" or shop.platform == "1688":
        raise ProfileError("SOURCE_STORE", "货源店铺不能作为上线目标")
    if not shop.market or shop.fulfillment_mode not in FULFILLMENT_MODES:
        raise ProfileError("STORE_CONTEXT_MISSING", "请补充目标国家和履约模式")
    market = store_market(shop.market)
    if not market:
        raise ProfileError("STORE_CONTEXT_MISSING", "店铺市场必须为明确支持的具体国家")
    if environment not in {"CONTRACT_TEST", "PRODUCTION"}:
        raise ProfileError("ENVIRONMENT_INVALID", "流程环境无效")
    targets = {field: getattr(shop, field) for field in
               ("platform", "store_type", "account_type", "business_mode", "fulfillment_mode")}
    targets["market"] = market
    rows = db.query(WorkflowTemplate).filter_by(
        tenant_id=current.legacy_tenant_id, flow_kind=PLATFORM_LAUNCH,
        definition_status="PUBLISHED", environment=environment).populate_existing().all()
    matches = {}
    for row in rows:
        definition_snapshot(row)
        score = _match_score(row, targets, product.category)
        if score is not None and (row.profile_key not in matches or row.version > matches[row.profile_key][1].version):
            matches[row.profile_key] = score, row
    if not matches:
        raise ProfileError("PROFILE_NOT_FOUND", "没有匹配的已发布流程", 404)
    best_score = max(score for score, _ in matches.values())
    best = [row for score, row in matches.values() if score == best_score]
    if len(best) != 1:
        raise ProfileError("PROFILE_AMBIGUOUS", "多个同优先级流程匹配，请调整适用范围", 409)
    return best[0]


def _match_score(row, targets, category):
    score = 0
    for field, target in targets.items():
        value = getattr(row, field)
        if value != "ANY" and value != target:
            return None
        score += value != "ANY"
    if row.category_scope != ["ANY"]:
        if not category or category not in row.category_scope:
            return None
        score += 1
    return score
