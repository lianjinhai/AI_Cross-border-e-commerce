"""首页经营工作台只读聚合（BFF 服务层）。

只读红线：**仅 SELECT**，不写库、不新增表/迁移、不新增写端点。
单一实现：聚合只组合既有 `services/`、`workflows/` 函数
（`launch_list.list_launches` / `commercial_analytics.metric_summary`、`quality_report` /
`alerting.list_alerts` / `action_queue` / `review_outputs.review_queue_count` /
`open_1688.get_config`），不在此重写其 SQL；原先内联在 router 的查询已抽到对应服务。

降级语义（契约 §3.0）：
  * 未持某源读权限 → 该源 `skipped`（从结果剔除，不报错）；
  * 单源失败 → 端点仍 200，`partial=true`、`sources[源]='failed'`，对应 section 缺省。
角色投影：`COMPLIANCE` 剥离价格/库存动作（复用 `launch_action_catalog.PRICE_STOCK_ACTIONS`）；
`FACTORY_COLLABORATOR` 返回空待办（`items` 空、`sources` 全 `skipped`）。

`signals` 为只读派生（`derived:true, authoritative:false`）：任一键不可得即 `None`，
**不猜测、不默认填值**；`has_1688_credential` 仅返回存在性，绝不返回密钥值。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func

from ..models import (
    OpportunitySupplierMatch,
    Order,
    Shop,
    SupplierCatalogProduct,
    User,
    WorkflowRun,
)
from ..workflows.kinds import LEGACY_AUTOMATION
from ..workflows.launch_access import launch_context
from ..workflows.launch_action_catalog import PRICE_STOCK_ACTIONS
from ..workflows.launch_list import list_launches
from . import alerting, open_1688
from .action_identity import require_action_permission
from .action_policy import POLICIES
from .action_queue import count_actions
from .commercial_analytics import metric_summary, quality_report
from .review_outputs import review_queue_count
from .workspace_context import ROLE_COMPLIANCE

logger = logging.getLogger("erp.workbench")

# 站内回跳白名单（与前端 `frontend/src/utils/navigationReturn.js` 同源）。
RETURN_WHITELIST = ("/launch", "/listings", "/products", "/shops")

# 待办类别（契约 §3.1 items[].type）与 overview 数据源（契约 §3.2 sources）。
_TODO_TYPES = ("launch", "action", "alert", "review")
_OVERVIEW_SOURCES = ("bi", "launch", "alert", "review", "workflow", "todo")
_SIGNAL_KEYS = ("has_sales_shop", "sales_shop_count", "has_factory", "factory_match_count",
                "has_1688_credential", "member_count", "order_count_30d")
# 复核队列读权限（与 frontend/src/permissions.js 的 APPROVER 语义同源）。
_REVIEW_PERMISSIONS = ("compliance:check", "compliance:approve")
# 待审批 Action 的权限来源（复用 PUBLISH_LISTING 的策略，不新造口径）。
_APPROVAL_ACTION_TYPE = "PUBLISH_LISTING"
_APPROVAL_PERMISSION = POLICIES[_APPROVAL_ACTION_TYPE].permission


def _utc_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _clamp(value, default=50) -> int:
    return max(1, min(200, int(value or default)))


# ---------------------------------------------------------------- 纯函数（可直测）

def safe_return_to(path) -> str | None:
    """站内回跳白名单校验：仅接受 /launch|/listings|/products|/shops 前缀。

    拒绝 scheme-relative（`//evil.com`）、绝对 URL、路径穿越与非白名单前缀，
    校验失败返回 None（前端消费时还会再经 `isSafeReturnTo()` 二次校验）。
    """
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        return None
    if ".." in path:
        return None
    base = path.split("?", 1)[0]
    if any(base == prefix or base.startswith(prefix + "/") for prefix in RETURN_WHITELIST):
        return path
    return None


def strip_price_stock_next_action(next_action, role):
    """COMPLIANCE 投影：剥离价格/库存类下一动作（复用 `PRICE_STOCK_ACTIONS`）。

    `list_launches` 已按 role 对 `available_actions`/`next_action` 做过投影；此处再兜
    一层，保证 BFF 输出在任何调用路径下都不会向合规角色泄露价格/库存动作（不新造口径）。
    """
    if role != ROLE_COMPLIANCE or not isinstance(next_action, dict):
        return next_action
    if next_action.get("action") in PRICE_STOCK_ACTIONS:
        return {"action": None, "step_code": next_action.get("step_code"),
                "executable": False, "reason": "该动作对合规角色不可见"}
    return next_action


def _is_tenant_workspace(current) -> bool:
    """是否为承载租户业务数据的 Workspace（平台身份与工厂身份都不承载）。"""
    return (current.workspace_id is not None
            and not current.is_platform_identity()
            and not current.is_factory_collaborator())


# ---------------------------------------------------------------- signals（只读派生）

def _sales_shop_count(db, tenant_id: int) -> int:
    return int(db.query(func.count(Shop.id)).filter(
        Shop.tenant_id == tenant_id, Shop.role == "sales",
        Shop.archived_at.is_(None)).scalar() or 0)


def _factory_supply_count(db, tenant_id: int) -> int:
    """已登记的源头工厂供给目录条数（存在性判定用）。"""
    return int(db.query(func.count(SupplierCatalogProduct.id)).filter(
        SupplierCatalogProduct.tenant_id == tenant_id).scalar() or 0)


def _factory_match_count(db, tenant_id: int) -> int:
    return int(db.query(func.count(OpportunitySupplierMatch.id)).filter(
        OpportunitySupplierMatch.tenant_id == tenant_id).scalar() or 0)


def _member_count(db, tenant_id: int) -> int:
    return int(db.query(func.count(User.id)).filter(User.tenant_id == tenant_id).scalar() or 0)


def _order_count_30d(db, tenant_id: int) -> int:
    cutoff = datetime.utcnow() - timedelta(days=30)
    return int(db.query(func.count(Order.id)).filter(
        Order.tenant_id == tenant_id, Order.created_at >= cutoff,
        Order.source.in_(("api", "import", "manual"))).scalar() or 0)


def build_signals(db, current) -> dict:
    """逐键只读派生信号；无权限/不可得 → 该键 None（不猜测、不默认填值）。"""
    signals: dict = dict.fromkeys(_SIGNAL_KEYS)
    if not _is_tenant_workspace(current) or current.legacy_tenant_id is None:
        return signals
    tenant_id = current.legacy_tenant_id
    if current.has("order:read"):
        shop_count = _sales_shop_count(db, tenant_id)
        signals["sales_shop_count"] = shop_count
        signals["has_sales_shop"] = shop_count > 0
        signals["order_count_30d"] = _order_count_30d(db, tenant_id)
    if current.has("supply:read"):
        signals["factory_match_count"] = _factory_match_count(db, tenant_id)
        signals["has_factory"] = _factory_supply_count(db, tenant_id) > 0
    if current.has("product:read"):
        cfg = open_1688.get_config(db)  # 只读存在性：绝不下发 app_secret/access_token
        signals["has_1688_credential"] = bool(cfg.get("app_key") and cfg.get("app_secret"))
    if current.has("workspace:read"):
        signals["member_count"] = _member_count(db, tenant_id)
    return signals


# ---------------------------------------------------------------- todo（跨域待办）

def _todo_item(kind, title, count, severity, path, return_to, ref=None, due_at=None) -> dict:
    return {"type": kind, "title": title, "count": int(count), "severity": severity,
            "due_at": due_at, "route": {"path": path, "return_to": return_to}, "ref": ref}


def _todo_launch(db, current, limit, include_history) -> dict:
    live, scope = launch_context(db, current, "launch:read")
    result = list_launches(db, live, scope, page_num=1, page_size=limit, mine=True,
                           include_history=include_history)
    rows = result.get("items") or []
    total = int(result.get("total", 0) or 0)
    severity = "high" if any(row.get("execution_status") in ("BLOCKED", "FAILED")
                             for row in rows) else "mid"
    item = None
    if total > 0:
        item = _todo_item("launch", "待你处理的上线流程", total, severity,
                          "/launch", safe_return_to("/launch?mine=true"))
    return {"count": total, "item": item}


def _todo_action(db, current, limit) -> dict:
    require_action_permission(db, current, _APPROVAL_PERMISSION)
    total = count_actions(db, current, _APPROVAL_ACTION_TYPE, "PENDING_APPROVAL")
    item = None
    if total > 0:
        item = _todo_item("action", "待审批的发布动作", total, "mid", "/listings", None)
    return {"count": total, "item": item}


def _todo_alert(db, current) -> dict:
    tenant_id = current.legacy_tenant_id
    total = alerting.alert_total(db, tenant_id, status="open")
    counts = alerting.alert_counts(db, tenant_id)
    severity = "high" if counts.get("high") else ("mid" if counts.get("mid") else "low")
    item = None
    if total > 0:
        item = _todo_item("alert", "待处理风险告警", total, severity, "/alerts", None)
    return {"count": total, "item": item}


def _todo_review(db, current) -> dict:
    total = review_queue_count(db, current.legacy_tenant_id, "manual_required")
    item = None
    if total > 0:
        item = _todo_item("review", "待人工复核的 Listing", total, "high",
                          "/compliance-workbench", None)
    return {"count": total, "item": item}


def _collect(items, counts, sources, kind, permitted, producer) -> None:
    if not permitted:
        sources[kind] = "skipped"
        return
    try:
        produced = producer()
    except Exception:  # 单源失败不整体失败（降级语义）
        logger.warning("workbench todo source failed", exc_info=True, extra={"source": kind})
        sources[kind] = "failed"
        return
    sources[kind] = "ok"
    counts[kind] = int(produced.get("count", 0) or 0)
    if produced.get("item") is not None:
        items.append(produced["item"])


def build_todo(db, current, *, limit=50, include_history=False) -> dict:
    """跨域待办（契约 §3.1）。"""
    limit = _clamp(limit)
    counts = {kind: 0 for kind in _TODO_TYPES}
    items: list[dict] = []
    sources: dict[str, str] = {}
    if not _is_tenant_workspace(current):
        for kind in _TODO_TYPES:
            sources[kind] = "skipped"
        return {"items": items, "counts": counts, "generated_at": _utc_iso(),
                "partial": False, "sources": sources}
    _collect(items, counts, sources, "launch", current.has("launch:read"),
             lambda: _todo_launch(db, current, limit, include_history))
    _collect(items, counts, sources, "action", current.has(_APPROVAL_PERMISSION),
             lambda: _todo_action(db, current, limit))
    _collect(items, counts, sources, "alert", current.has("ai:read"),
             lambda: _todo_alert(db, current))
    _collect(items, counts, sources, "review",
             any(current.has(p) for p in _REVIEW_PERMISSIONS),
             lambda: _todo_review(db, current))
    partial = any(state == "failed" for state in sources.values())
    return {"items": items, "counts": counts, "generated_at": _utc_iso(),
            "partial": partial, "sources": sources}


# ---------------------------------------------------------------- overview（首页 6 问）

def _bi_section(db, current) -> dict:
    tenant_id = current.legacy_tenant_id
    metrics = metric_summary(db, tenant_id, 30, True)   # 与 /bi/dashboard 同源，不新造口径
    quality = quality_report(db, tenant_id)
    return {
        "metrics": {"gmv": metrics["gmv"], "orders": metrics["orders"],
                    "contribution_profit": metrics["contribution_profit"],
                    "net_revenue": metrics["net_revenue"], "refund_rate": metrics["refund_rate"],
                    "ad_spend": metrics["ad_spend"], "roi": metrics["roi"],
                    "metric_scope": metrics["scope"], "currency": metrics["currency"]},
        "data_quality": {"grade": quality["grade"],
                         "commercial_ready": quality["commercial_ready"],
                         "freshness_hours": quality["freshness_hours"],
                         "real_order_count": quality["real_order_count"]},
    }


def _in_progress_section(db, current, limit) -> list[dict]:
    live, scope = launch_context(db, current, "launch:read")
    result = list_launches(db, live, scope, page_num=1, page_size=limit, mine=True)
    items = []
    for row in result.get("items") or []:
        progress = row.get("progress") or {}
        items.append({
            "id": row.get("id"),
            "product": row.get("product"),
            "store": row.get("store"),
            "execution_status": row.get("execution_status"),
            "progress": {"completed": progress.get("completed", 0),
                         "total": progress.get("total", 0)},
            "next_action": strip_price_stock_next_action(row.get("next_action"), current.role),
            "market": row.get("market"),
        })
    return items


def _exceptions_section(db, current) -> dict:
    tenant_id = current.legacy_tenant_id
    rows = alerting.list_alerts(db, tenant_id, status="open", limit=100)
    items = [{"id": row.id, "level": row.level, "rule_key": row.rule_key, "title": row.title,
              "detail": row.detail, "subject_type": row.subject_type,
              "subject_id": row.subject_id, "status": row.status,
              "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None}
             for row in rows]
    return {"items": items, "total": alerting.alert_total(db, tenant_id, status="open"),
            "counts": alerting.alert_counts(db, tenant_id)}


def _ai_done_section(db, current, limit) -> dict:
    """近 24h 成功完成的旧自动化运行（投影 /workflows/runs）。"""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    rows = (db.query(WorkflowRun)
            .filter(WorkflowRun.tenant_id == current.legacy_tenant_id,
                    WorkflowRun.flow_kind == LEGACY_AUTOMATION,
                    WorkflowRun.status == "success",
                    WorkflowRun.finished_at >= cutoff)
            .order_by(WorkflowRun.finished_at.desc())
            .limit(_clamp(limit)).all())
    items = [{"id": row.id, "title": row.name or row.template_key, "status": row.status,
              "finished_at": row.finished_at.strftime("%Y-%m-%d %H:%M:%S")
              if row.finished_at else None}
             for row in rows]
    return {"count": len(items), "items": items}


def _need_human_section(db, current) -> dict:
    """待人工处理计数（契约 §3.2：`need_human` 仅 `{"count": int}`）。

    v1.2 已**撤回** `approvals[]`（避免与 `items` 双事实源）；审批类由
    `items.type == 'action'` 派生、复核类由 `items.type == 'review'` 派生。
    """
    action_count = 0
    if current.has(_APPROVAL_PERMISSION):
        require_action_permission(db, current, _APPROVAL_PERMISSION)
        action_count = count_actions(db, current, _APPROVAL_ACTION_TYPE, "PENDING_APPROVAL")
    review_count = 0
    if any(current.has(p) for p in _REVIEW_PERMISSIONS):
        review_count = review_queue_count(db, current.legacy_tenant_id, "manual_required")
    return {"count": action_count + review_count}


def _produce(sources, kind, permitted, producer):
    if not permitted:
        sources[kind] = "skipped"
        return None
    try:
        value = producer()
    except Exception:
        logger.warning("workbench overview source failed", exc_info=True, extra={"source": kind})
        sources[kind] = "failed"
        return None
    sources[kind] = "ok"
    return value


def build_overview(db, current, *, limit=50) -> dict:
    """首页 6 问只读聚合（契约 §3.2）。"""
    limit = _clamp(limit)
    sections = {key: None for key in
                ("metrics", "in_progress", "top_today", "need_human", "ai_done", "exceptions")}
    sources: dict[str, str] = {}
    signals = build_signals(db, current)
    if not _is_tenant_workspace(current):
        for key in _OVERVIEW_SOURCES:
            sources[key] = "skipped"
        return {"sections": sections, "data_quality": None,
                "next_actions": [], "signals": signals, "generated_at": _utc_iso(),
                "partial": False, "sources": sources}

    bi = _produce(sources, "bi", current.has("finance:read"), lambda: _bi_section(db, current))
    if bi is not None:
        sections["metrics"] = bi["metrics"]
    sections["in_progress"] = _produce(
        sources, "launch", current.has("launch:read"),
        lambda: _in_progress_section(db, current, limit))
    sections["exceptions"] = _produce(
        sources, "alert", current.has("ai:read"), lambda: _exceptions_section(db, current))
    sections["ai_done"] = _produce(
        sources, "workflow", current.has("ai:read"), lambda: _ai_done_section(db, current, limit))
    sections["need_human"] = _produce(
        sources, "review", any(current.has(p) for p in _REVIEW_PERMISSIONS),
        lambda: _need_human_section(db, current))

    todo = build_todo(db, current, limit=limit)
    sources["todo"] = "failed" if any(v == "failed" for v in todo["sources"].values()) else "ok"
    sections["top_today"] = todo["items"]

    data_quality = bi["data_quality"] if bi is not None else None
    partial = (any(state == "failed" for state in sources.values())
               or any(value is None for value in signals.values()))
    return {"sections": sections, "data_quality": data_quality,
            "next_actions": todo["items"], "signals": signals, "generated_at": _utc_iso(),
            "partial": partial, "sources": sources}
