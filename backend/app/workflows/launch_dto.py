"""Launch 读模型 DTO：列表/详情/步骤/事件/上下文/渠道聚合 + COMPLIANCE 角色投影（设计 D8）。

所有 DTO 结构性不含价格/成本/利润率/备货数字段（AC-3.2，契约测试递归断言）。
读详情/步骤（launch:manage）触发确定性刷新（无变化不增版，AC-2.2）；只读方仅计算不落库。
"""

from ..models import Listing, PlatformPublishAttempt, Product, Shop, WorkflowRun, WorkflowStep
from .kinds import PLATFORM_LAUNCH
from .launch_access import LaunchError, launch_context, owned_launch
from .launch_action_catalog import PRICE_STOCK_ACTIONS, action_meta
from .launch_facts import launch_facts_from_rows
from .launch_nba import action_block_reason, compute_nba, next_action_summary, recommendations
from .launch_plan import activated_flag, launch_plan
from .launch_rules import evaluate_readiness
from .launch_runtime import refresh_launch
from .launch_state import deep_redact, facts_digest
from .profile_schema import ProfileDefinition
from .profiles import ProfileError, probe_profile

_EXPERIENCE_MODE = "GUIDED"
_NOTICE = "本地流程验证，不代表真实平台接入"
_MONITORING = {"status": "UNAVAILABLE", "reason": "经营数据未接入，不以 Workspace 总额冒充单店表现"}
_PRO_FEATURES = {"DATA_PREPARATION": "/listings", "COMPLIANCE": "/compliance-workbench",
                 "PRICE_REVIEW": "/pricing", "STOCK_PREPARATION": "/suppliers"}
_REASON_TEXT = {"STORE_CONTEXT_MISSING": "店铺缺少目标国家或履约配置",
                "PROFILE_NOT_FOUND": "没有匹配的已发布流程",
                "PROFILE_AMBIGUOUS": "多个同优先级流程匹配，需调整适用范围",
                "SOURCE_STORE": "货源店铺不能作为上线目标"}


def fmt_dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value is not None else None


def product_ref(product):
    return None if product is None else {"id": product.id, "title": product.title,
                                         "sku": product.sku, "category": product.category}


def store_ref(shop):
    return None if shop is None else {"id": shop.id, "name": shop.shop_name, "platform": shop.platform}


def verification_notice(run, definition):
    """CONTRACT_TEST 或 Profile UNVERIFIED → 固定诚实标注（AC-2.5/17.1）。"""
    if run.environment == "CONTRACT_TEST" or definition.verification_status == "UNVERIFIED":
        return _NOTICE
    return None


def step_dto(step, definition, *, role, revision, plan_step=None, permissions=frozenset(), run=None):
    """单步骤 DTO（含 COMPLIANCE 动作投影）；status/blocking 取收敛后的计划值。"""
    plan_step = plan_step or {}
    status = plan_step.get("status", step.step_status)
    blocking = plan_step.get("blocking_reason") or step.blocking_reason or {}
    actions = []
    for action in (definition.available_actions if definition is not None else []):
        if role == "COMPLIANCE" and action in PRICE_STOCK_ACTIONS:
            continue
        reason = action_block_reason(action, action_meta(action), status, plan_step, permissions, run)
        entry = {"action": action, "executable": reason is None}
        if reason is not None:
            entry["disabled_reason"] = reason
        actions.append(entry)
    refs = list(step.evidence_refs or [])
    requirements = list(definition.evidence_requirements) if definition is not None else []
    return {"step_code": step.step_code,
            "step_name": definition.step_name if definition is not None else step.step_code,
            "business_type": step.business_type,
            "execution_mode": definition.execution_mode if definition is not None else step.execution_mode,
            "actor": step.actor, "sequence": definition.sequence if definition is not None else step.seq,
            "required": definition.required if definition is not None else step.required,
            "dependencies": list(definition.dependencies) if definition is not None else [],
            "step_status": status, "blocking_reason": blocking,
            "evidence_requirements": requirements, "evidence_refs": refs,
            "missing_evidence": [item for item in requirements if item not in refs],
            "result": step.result or {},
            "external": {"status": step.external_status, "reference": step.external_reference,
                         "type": step.external_type},
            "assigned_user_id": step.assigned_user_id, "input_revision": step.input_revision,
            "available_actions": actions}


def event_dto(event):
    """事件 DTO（AC-11.1/11.2）：payload/before/after 深度脱敏，occurred_at 转本地无时区串。"""
    return {"id": event.id, "sequence": event.sequence, "event_type": event.event_type,
            "actor_id": event.actor_id, "source": event.source,
            "occurred_at": fmt_dt(event.occurred_at), "before": deep_redact(event.before),
            "after": deep_redact(event.after), "payload": deep_redact(event.payload)}


def load_detail(db, ctx, run_id):
    """详情（AC-2.1/2.2）：launch:read 可读；持 launch:manage 先确定性刷新一次。"""
    current, scope = launch_context(db, ctx, "launch:read")
    run = owned_launch(db, current, scope, run_id)
    if current.has("launch:manage"):
        run = _refresh_once(db, ctx, current, scope, run_id)
    definition, steps, facts, predicates, plan = launch_plan(db, run)
    return launch_detail(db, run, current, plan, _nba(plan, steps, definition, current, facts, predicates, run))


def load_steps(db, ctx, run_id):
    """步骤 DTO 列表（AC-3.1）；manage 调用方先刷新以对齐持久状态。"""
    current, scope = launch_context(db, ctx, "launch:read")
    run = owned_launch(db, current, scope, run_id)
    if current.has("launch:manage"):
        run = _refresh_once(db, ctx, current, scope, run_id)
    definition, steps, facts, predicates, plan = launch_plan(db, run)
    definitions = _definitions(definition)
    items = [step_dto(step, definitions.get(step.step_code), role=current.role, revision=run.revision,
                      plan_step=plan["steps"].get(step.step_code), permissions=current.permissions,
                      run=run) for step in steps]
    return {"items": items, "revision": run.revision,
            "profile": {"key": run.template_key, "version": run.workflow_version,
                        "hash": run.definition_hash}}


def launch_detail(db, run, current, plan, nba):
    """组装详情 DTO（ListItem + 冻结补充字段，AC-2.1）。"""
    definition = ProfileDefinition.model_validate(run.definition_snapshot)
    definitions = _definitions(definition)
    steps = db.query(WorkflowStep).filter_by(run_id=run.id).order_by(WorkflowStep.seq).all()
    items = [step_dto(step, definitions.get(step.step_code), role=current.role, revision=run.revision,
                      plan_step=plan["steps"].get(step.step_code), permissions=current.permissions,
                      run=run) for step in steps]
    detail = {"id": run.id, "environment": run.environment,
              "product": product_ref(db.get(Product, run.product_id)), "store": store_ref(db.get(Shop, run.shop_id)),
              "market": run.market, "fulfillment_mode": run.fulfillment_mode,
              "execution_status": plan["execution_status"], "platform_status": run.platform_status,
              "verification_status": run.verification_status, "progress": plan["progress"],
              "current_steps": plan["current_steps"], "blockers": plan["blockers"],
              "blocked_summary": _summary(plan["blockers"]),
              "profile": {"key": run.template_key, "version": run.workflow_version, "hash": run.definition_hash},
              "available_actions": nba["allowed_actions"], "disabled_actions": nba["disabled_actions"],
              "next_best_action": nba["next_best_action"], "next_action": next_action_summary(nba),
              "owner": nba["owner"], "recommendations": recommendations(nba, plan), "steps": items,
              "last_synced_at": fmt_dt(run.last_synced_at),
              "professional_links": _professional_links(run, definition),
              "monitoring": dict(_MONITORING), "previous_run_id": run.previous_run_id,
              "revision": run.revision, "is_history": run.active_slot is None,
              "created_at": fmt_dt(run.created_at)}
    notice = verification_notice(run, definition)
    if notice:
        detail["verification_notice"] = notice
    return detail


def launch_list_item(db, run, current, *, product, shop, attempt, steps=None, listing=None):
    """单行读模型：facts + evaluate_readiness + compute_nba；LaunchError 交由 launch_list 降级。"""
    definition = ProfileDefinition.model_validate(run.definition_snapshot)
    if listing is None:
        listing = db.get(Listing, run.listing_id)
    if steps is None:
        steps = db.query(WorkflowStep).filter_by(run_id=run.id).all()
    states = {step.step_code: step.step_status for step in steps}
    facts, predicates = launch_facts_from_rows(db, run, product, listing, shop, attempt)
    plan = evaluate_readiness(definition.model_dump(), states, facts, predicates, activated=activated_flag(run))
    nba = _nba(plan, steps, definition, current, facts, predicates, run)
    item = {"id": run.id, "environment": run.environment, "product": product_ref(product),
            "store": store_ref(shop), "market": run.market, "fulfillment_mode": run.fulfillment_mode,
            "execution_status": plan["execution_status"], "platform_status": run.platform_status,
            "verification_status": run.verification_status, "progress": plan["progress"],
            "blocked_summary": _summary(plan["blockers"]), "next_action": next_action_summary(nba),
            "owner": nba["owner"], "profile": {"key": run.template_key, "version": run.workflow_version},
            "revision": run.revision, "is_history": run.active_slot is None,
            "created_at": fmt_dt(run.created_at)}
    notice = verification_notice(run, definition)
    if notice:
        item["verification_notice"] = notice
    return item


def context_dto(db, current, scope):
    """上线入口上下文（AC-13.1）：Scope 内销售店铺 + 权限 + can_create 与原因。"""
    shops = [shop for shop in db.query(Shop).filter(
        Shop.tenant_id == current.legacy_tenant_id, Shop.role == "sales",
        Shop.platform != "1688", Shop.archived_at.is_(None)).order_by(Shop.id).all()
        if scope.shop_ids is None or shop.id in scope.shop_ids]
    rows = [_shop_context(db, current, shop) for shop in shops]
    if not (current.has("launch:create") and current.has("listing:write") and current.has("product:read")):
        blocked = {"code": "PERMISSION_DENIED", "message": "缺少创建上线流程所需的权限"}
    elif not shops:
        blocked = {"code": "NO_USABLE_SHOP", "message": "没有可用的销售店铺"}
    elif not [row for row in rows if row["usable"]]:
        blocked = {"code": "NO_PROFILE", "message": "没有匹配的已发布流程"}
    else:
        blocked = None
    return {"shops": rows, "effective_experience_mode": _EXPERIENCE_MODE,
            "permissions": sorted(current.permissions), "can_create": blocked is None,
            "blocked_reason": blocked}


def channels_dto(db, current, scope, product_id):
    """商品渠道聚合（AC-12.1/12.3）：Scope 外店铺不出现也不计入总数；同平台多店不合并。"""
    product = db.get(Product, product_id)
    if product is None or product.tenant_id != current.legacy_tenant_id:
        raise LaunchError("LAUNCH_NOT_FOUND", "商品不存在", 404)
    query = db.query(WorkflowRun).filter(
        WorkflowRun.tenant_id == current.legacy_tenant_id,
        WorkflowRun.workspace_id == current.workspace_id,
        WorkflowRun.flow_kind == PLATFORM_LAUNCH, WorkflowRun.product_id == product_id)
    runs = scope.filter(query, WorkflowRun.shop_id).order_by(WorkflowRun.created_at.desc()).all()
    grouped = {}
    for run in runs:
        grouped.setdefault(run.shop_id, []).append(run)
    shops = {shop.id: shop for shop in db.query(Shop).filter(Shop.id.in_(list(grouped))).all()} if grouped else {}
    channels = [_channel(db, current, product, shops[shop_id], grouped[shop_id])
                for shop_id in sorted(grouped) if shop_id in shops]
    return {"product": {"id": product.id, "title": product.title, "sku": product.sku},
            "total": len(channels), "channels": channels}


def _definitions(definition):
    return {step.step_code: step for step in definition.steps}


def _nba(plan, steps, definition, current, facts, predicates, run):
    return compute_nba(plan, steps, _definitions(definition), current.permissions,
                       role=current.role, revision=run.revision,
                       facts_digest=facts_digest(facts, predicates), run=run)


def _summary(blockers):
    return [{"code": item.get("code"), "message": item.get("message"),
             "step_code": item.get("step_code"), "owner_actor": item.get("owner_actor")}
            for item in (blockers or [])[:3]]


def _professional_links(run, definition):
    links = []
    for definition_step in definition.steps:
        path = _PRO_FEATURES.get(definition_step.business_type)
        if path:
            links.append({"product_id": run.product_id, "listing_id": run.listing_id,
                          "shop_id": run.shop_id, "step_code": definition_step.step_code,
                          "path": path, "return_to": "/launch/%d" % run.id})
    return links


def _shop_context(db, current, shop):
    try:
        row, reason = probe_profile(db, current, shop.id, "CONTRACT_TEST")
    except ProfileError as exc:
        row, reason = None, exc.code
    return {"id": shop.id, "name": shop.shop_name, "platform": shop.platform, "market": shop.market,
            "store_type": shop.store_type, "account_type": shop.account_type,
            "business_mode": shop.business_mode, "fulfillment_mode": shop.fulfillment_mode,
            "is_demo": shop.is_demo, "status": shop.status, "usable": row is not None,
            "blocked_reason": ({"code": reason, "message": _REASON_TEXT.get(reason, reason)} if reason else None),
            "profile_available": row is not None,
            "profile_key": row.profile_key if row is not None else None}


def _channel(db, current, product, shop, runs):
    active, history = None, []
    for run in runs:
        attempt = db.query(PlatformPublishAttempt).filter_by(
            tenant_id=run.tenant_id, listing_id=run.listing_id, shop_id=run.shop_id,
            platform=run.platform).first()
        item = launch_list_item(db, run, current, product=product, shop=shop, attempt=attempt)
        if run.active_slot == 1:
            active = item
        else:
            history.append(item)
    return {"shop": {"id": shop.id, "name": shop.shop_name, "platform": shop.platform,
                     "market": shop.market}, "active_launch": active, "history": history}


def _refresh_once(db, ctx, current, scope, run_id):
    """manage 读触发刷新（AC-2.2/R5）：已结束流程不刷新；并发冲突重读重试一次。"""
    run = owned_launch(db, current, scope, run_id)
    if run.ended_at is not None or run.execution_status == "CANCELLED":
        return run
    for _ in range(2):
        try:
            run, _plan = refresh_launch(db, ctx, run_id, run.revision)
            return run
        except LaunchError as exc:
            if exc.code != "REVISION_CONFLICT":
                raise
            run = owned_launch(db, current, scope, run_id)
    raise LaunchError("REVISION_CONFLICT", "流程已更新，请刷新后重试", 409, current_revision=run.revision)
