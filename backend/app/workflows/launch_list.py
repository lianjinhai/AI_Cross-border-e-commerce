"""Launch 列表查询：先 Scope 后分页、SQL 侧筛选、批预取、逐行就绪度 + 单行降级（设计 D7）。

行**重算就绪度与 NBA**（保证下一动作/阻断摘要权威），但用四层控制查询量：
Scope 过滤 → 分页 → 批预取（product/shop/listing/steps/attempt）→ 逐行仅剩 1 次权利查询。
单行事实异常不使整页失败（AC-10.6）：该行以降级阻断摘要展示。
"""

from sqlalchemy import or_

from ..models import Listing, PlatformPublishAttempt, Product, Shop, WorkflowRun, WorkflowStep
from .kinds import PLATFORM_LAUNCH
from .launch_access import LaunchError
from .launch_dto import fmt_dt, launch_list_item, product_ref, store_ref

# 执行态合法值（AC-1.6）；非法值 422 FILTER_INVALID 并列出合法值。
EXECUTION_STATES = frozenset({"NOT_STARTED", "READY", "RUNNING", "WAITING_USER", "WAITING_EXTERNAL",
                              "WAITING_APPROVAL", "BLOCKED", "FAILED", "COMPLETED", "CANCELLED"})
# mine=true（AC-1.4）的「需我处理」非终态集合；等待平台（AC-1.5）的外部等待集合。
_MY_STATES = ("READY", "WAITING_USER", "WAITING_APPROVAL", "FAILED")
_WAITING_STATES = ("WAITING_EXTERNAL",)
_PLATFORM_WAITING = ("SUBMITTED", "UNDER_REVIEW")


def list_launches(db, current, scope, *, page_num, page_size, product_id=None, shop_id=None,
                  platform=None, market=None, execution_status=None, owner_user_id=None, mine=False,
                  waiting_platform=False, blocked_only=False, include_history=False,
                  extra_params=frozenset()):
    """先 Scope 后分页；返回 {items, total, page_num, page_size}（AC-1.1~1.6）。"""
    if extra_params:
        raise LaunchError("FILTER_INVALID", "未知查询参数：" + "、".join(sorted(extra_params)), 422)
    if execution_status is not None and execution_status not in EXECUTION_STATES:
        raise LaunchError("FILTER_INVALID",
                          "执行状态无效，合法值：" + "、".join(sorted(EXECUTION_STATES)), 422)
    query = db.query(WorkflowRun).filter(
        WorkflowRun.tenant_id == current.legacy_tenant_id,
        WorkflowRun.workspace_id == current.workspace_id, WorkflowRun.flow_kind == PLATFORM_LAUNCH)
    query = scope.filter(query, WorkflowRun.shop_id)
    if product_id is not None:
        query = query.filter(WorkflowRun.product_id == product_id)
    if shop_id is not None:
        query = query.filter(WorkflowRun.shop_id == shop_id)
    if platform:
        query = query.filter(WorkflowRun.platform == platform)
    if market:
        query = query.filter(WorkflowRun.market == market)
    if execution_status:
        query = query.filter(WorkflowRun.execution_status == execution_status)
    if not include_history:
        query = query.filter(WorkflowRun.active_slot == 1)
    if blocked_only:
        query = query.filter(WorkflowRun.execution_status.in_(("BLOCKED", "FAILED")))
    if owner_user_id is not None:
        query = query.filter(_step_exists(db, owner_user_id=owner_user_id, statuses=_MY_STATES))
    if mine:
        query = query.filter(_step_exists(db, owner_user_id=current.user_id, statuses=_MY_STATES))
    if waiting_platform:
        query = query.filter(or_(WorkflowRun.platform_status.in_(_PLATFORM_WAITING),
                                 _step_exists(db, owner_user_id=None, statuses=_WAITING_STATES)))
    total = query.count()
    rows = (query.order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .offset((page_num - 1) * page_size).limit(page_size).all())
    return {"items": _items(db, current, rows), "total": total,
            "page_num": page_num, "page_size": page_size}


def _step_exists(db, *, owner_user_id, statuses):
    """相关 EXISTS 子查询（mine/owner/waiting_platform 翻译为 SQL，避免全表遍历）。"""
    sub = db.query(WorkflowStep.id).filter(WorkflowStep.run_id == WorkflowRun.id,
                                           WorkflowStep.step_status.in_(statuses))
    if owner_user_id is not None:
        sub = sub.filter(WorkflowStep.assigned_user_id == owner_user_id)
    return sub.exists()


def _items(db, current, rows):
    """批预取主表后逐行组装；单行 LaunchError/ValueError 降级，不使整页失败（AC-10.6）。"""
    if not rows:
        return []
    run_ids = [run.id for run in rows]
    products = _by_id(db, Product, {run.product_id for run in rows if run.product_id})
    shops = _by_id(db, Shop, {run.shop_id for run in rows if run.shop_id})
    listings = _by_id(db, Listing, {run.listing_id for run in rows if run.listing_id})
    steps = {}
    for step in db.query(WorkflowStep).filter(WorkflowStep.run_id.in_(run_ids)).populate_existing():
        steps.setdefault(step.run_id, []).append(step)
    attempts = {}
    if listings:
        for attempt in db.query(PlatformPublishAttempt).filter(
                PlatformPublishAttempt.listing_id.in_(list(listings))).populate_existing():
            attempts[attempt.listing_id] = attempt
    items = []
    for run in rows:
        product, shop = products.get(run.product_id), shops.get(run.shop_id)
        try:
            items.append(launch_list_item(db, run, current, product=product, shop=shop,
                                          attempt=attempts.get(run.listing_id),
                                          steps=steps.get(run.id, []), listing=listings.get(run.listing_id)))
        except (LaunchError, ValueError) as exc:
            items.append(_degraded(run, product, shop, getattr(exc, "code", "LAUNCH_DEFINITION_CORRUPT"),
                                   str(exc)))
    return items


def _by_id(db, model, ids):
    if not ids:
        return {}
    return {row.id: row for row in db.query(model).filter(model.id.in_(list(ids))).populate_existing()}


def _degraded(run, product, shop, code, message):
    """降级行：保留身份字段，阻断摘要为单条降级原因，下一动作引导进入详情刷新。"""
    return {"id": run.id, "environment": run.environment, "product": product_ref(product),
            "store": store_ref(shop), "market": run.market, "fulfillment_mode": run.fulfillment_mode,
            "execution_status": run.execution_status, "platform_status": run.platform_status,
            "verification_status": run.verification_status, "progress": {"completed": 0, "total": 0},
            "blocked_summary": [{"code": code, "message": message, "step_code": None, "owner_actor": None}],
            "next_action": {"action": None, "step_code": None, "executable": False,
                            "reason": "请进入详情刷新状态"},
            "owner": {"actor": None, "user_id": None},
            "profile": {"key": run.template_key, "version": run.workflow_version},
            "revision": run.revision, "is_history": run.active_slot is None,
            "created_at": fmt_dt(run.created_at)}
