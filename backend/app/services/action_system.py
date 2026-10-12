"""统一 Action Guardrail 与 Executor：服务端策略、权限、审批、幂等事务。"""

import hashlib
import json
import logging
from datetime import datetime

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from ..models import AdCampaign, AiAction, Listing, Product, Tenant
from . import action_content
from .action_identity import (
    requester_context,
    require_action_permission,
    require_publish_action_scope,
    require_publish_approver,
    require_store_scope,
)
from .action_policy import POLICIES
from .action_publish import publish_facts, publish_listing
from .ai_actions import ActionError, _tenant_id, owned_action
from .compliance_risk import update_listing_compliance_risk, validate_risk_projection
from .pii_redact import redact
from .product_standardization import update_product_content
from .trend_refresh import lock_refresh, refresh_builtin_trends, validate_refresh

HANDLERS = {
    "REFRESH_BUILTIN_TRENDS": refresh_builtin_trends,
    "UPDATE_LISTING_COMPLIANCE_RISK": update_listing_compliance_risk,
    "UPDATE_PRODUCT_CONTENT": update_product_content,
    "CREATE_AD_CAMPAIGN_DRAFT": action_content.create_ad_campaign_draft,
    "CREATE_LISTING_DRAFT": action_content.create_listing_draft,
    "UPDATE_LISTING_CONTENT": action_content.update_listing_content,
    "ADJUST_AD_BUDGET": action_content.adjust_ad_budget,
    "PUBLISH_LISTING": publish_listing,
}

logger = logging.getLogger(__name__)


def _validate_target(db, tenant_id, policy, target_id, payload):
    if policy.target_type == "tenant":
        if target_id != tenant_id or db.get(Tenant, target_id) is None:
            raise ActionError(403, "趋势目标与可信租户不一致")
        return
    models = {"product": Product, "listing": Listing,
              "ad_campaign": AdCampaign}
    model = models.get(policy.target_type)
    if model is None:
        raise ActionError(400, "Action 目标类型无效")
    action_content.owned(db, model, tenant_id, target_id)


def _payload(action):
    """兼容 D47 已存量预算 Action，不修改原始审批证据。"""
    payload = (action.evidence or {}).get("payload")
    if payload is not None:
        return payload
    if action.action_type == "ADJUST_AD_BUDGET":
        return {"old_budget": action.evidence["old_budget"],
                "new_budget": action.expected_impact["new_budget"]}
    raise ActionError(400, "Action 缺少执行载荷")


def _policy(action_type):
    policy = POLICIES.get(action_type)
    if policy is None or action_type not in HANDLERS:
        raise ActionError(400, "不支持的 Action 类型：" + str(action_type))
    return policy


def _publish_store_scope(shop_id):
    """按服务端保存的店铺隔离；兼容仅在 payload 保存店铺的历史提案。"""
    stored_shop = func.coalesce(AiAction.evidence["shop_id"].as_integer(),
                                AiAction.evidence["payload"]["shop_id"].as_integer())
    return stored_shop.is_(None) if shop_id is None else stored_shop == shop_id


def _existing_intent(db, tenant_id, workspace_id, action_type, target_id, evidence):
    if action_type not in {"PUBLISH_LISTING", "ADJUST_AD_BUDGET"}:
        return None
    query = db.query(AiAction).filter(
        AiAction.tenant_id == tenant_id, AiAction.workspace_id == workspace_id,
        AiAction.action_type == action_type, AiAction.target_id == target_id,
        AiAction.status.in_(("PENDING_APPROVAL", "APPROVED", "EXECUTING", "SUCCESS")
                           if action_type == "PUBLISH_LISTING" else ("PENDING_APPROVAL", "APPROVED")))
    if action_type == "PUBLISH_LISTING":
        query = query.filter(_publish_store_scope(evidence.get("shop_id")))
    existing = query.order_by(AiAction.id.desc()).first()
    if existing is not None:
        same = (existing.evidence.get("fingerprint") == evidence.get("fingerprint")
                if action_type == "PUBLISH_LISTING" else
                existing.expected_impact.get("payload") == evidence.get("payload"))
        if not same:
            if existing.status == "SUCCESS":
                raise ActionError(409, "已发布内容或目标店铺发生变化，请通过人工业务流程处理")
            raise ActionError(409, "该对象已有内容不同的待处理 Action")
    return existing


def _scope_action(db, ctx, action_type, target_id, scope_key, payload):
    query = db.query(AiAction).filter(
        AiAction.tenant_id == ctx.legacy_tenant_id, AiAction.workspace_id == ctx.workspace_id,
        AiAction.requested_by == ctx.user_id, AiAction.action_type == action_type,
        AiAction.target_id == target_id,
        AiAction.evidence["scope_key"].as_string() == str(scope_key))
    if action_type == "PUBLISH_LISTING":
        query = query.filter(_publish_store_scope(payload.get("shop_id")))
    action = query.first()
    if action is not None and action.evidence.get("payload") != payload:
        raise ActionError(409, "同一执行范围的提案内容已变化，禁止创建重复副作用")
    return action


def _intent_key(db, ctx, agent_type, action_type, target_id, scope_key, encoded, evidence):
    if action_type == "PUBLISH_LISTING":
        # 同一发布意图不随 HTTP trace 改变：数据库唯一键兜住并发提交。
        terminal = (db.query(AiAction.id).filter(
            AiAction.workspace_id == ctx.workspace_id, AiAction.tenant_id == ctx.legacy_tenant_id,
            AiAction.action_type == action_type, AiAction.target_id == target_id,
            _publish_store_scope(evidence.get("shop_id")),
            AiAction.status.in_(("REJECTED", "FAILED"))).order_by(AiAction.id.desc()).first())
        raw = f"{ctx.workspace_id}:{action_type}:{target_id}:{evidence['fingerprint']}:{terminal[0] if terminal else 0}"
    else:
        raw = f"{ctx.workspace_id}:{ctx.user_id}:{agent_type}:{action_type}:{target_id}:{scope_key}:{encoded}"
    return hashlib.sha256(raw.encode()).hexdigest()


def submit_action(db, ctx, agent_type, proposal, scope_key, *, scope_manifest=None, commit=True,
                  extra_evidence=None):
    action_type = proposal["action_type"]
    policy = _policy(action_type)
    if not commit and action_type not in {"UPDATE_LISTING_COMPLIANCE_RISK", "PUBLISH_LISTING"}:
        raise ActionError(400, "外部原子事务仅支持合规风险投影与发布提案")
    if agent_type not in policy.agents or agent_type == "pricing":
        raise ActionError(403, "该 Agent 无权提出此类 Action")
    if action_type == "UPDATE_PRODUCT_CONTENT":
        table = Tenant.__table__
        db.execute(table.update().where(table.c.id == ctx.legacy_tenant_id).values(id=table.c.id))
    current = require_action_permission(db, ctx, policy.permission)
    tenant_id = _tenant_id(db, current)
    if proposal["target_type"] != policy.target_type:
        raise ActionError(400, "Action 目标类型与服务端目录不一致")
    target_id = int(proposal["target_id"])
    payload = proposal.get("payload") or {}
    if not isinstance(payload, dict):
        raise ActionError(400, "Action 载荷必须是对象")
    if action_type == "PUBLISH_LISTING":
        require_store_scope(db, current, payload.get("shop_id"))
    _validate_target(db, tenant_id, policy, target_id, payload)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(encoded.encode("utf-8")) > 100_000:
        raise ActionError(400, "Action 提案超出大小上限")
    scoped = _scope_action(db, current, action_type, target_id, scope_key, payload)
    if scoped is not None:
        return scoped
    evidence = {"payload": payload, "_impersonating": current.is_impersonating,
                "scope_key": str(scope_key)}
    if extra_evidence:
        evidence.update(extra_evidence)
    if scope_manifest is not None:
        if action_type != "UPDATE_PRODUCT_CONTENT":
            raise ActionError(400, "范围清单仅用于商品标准化")
        evidence["scope_manifest"] = scope_manifest
    if action_type == "PUBLISH_LISTING":
        evidence.update(publish_facts(db, tenant_id, target_id, payload.get("shop_id")))
    elif action_type == "ADJUST_AD_BUDGET":
        evidence.update(action_content.budget_facts(db, tenant_id, target_id, payload))
    existing = _existing_intent(db, tenant_id, current.workspace_id,
                                action_type, target_id, evidence)
    if existing is not None:
        return existing
    key = _intent_key(db, current, agent_type, action_type, target_id, scope_key, encoded, evidence)
    existing = db.query(AiAction).filter(AiAction.idempotency_key == key).first()
    if existing is not None:
        return existing
    now = datetime.utcnow()
    action = AiAction(
        tenant_id=tenant_id, workspace_id=current.workspace_id, task_id=None,
        agent_type=agent_type, action_type=action_type,
        target_type=policy.target_type, target_id=target_id,
        reason=str(proposal.get("reason") or "结构化业务提案")[:2000],
        evidence=evidence, expected_impact={"payload": payload,
                                           "new_budget": payload.get("new_budget")},
        risk_level=policy.risk, required_permission=policy.permission,
        execution_mode="APPROVAL_REQUIRED" if policy.approval else "AUTO_SAFE",
        approval_required=policy.approval,
        status="PENDING_APPROVAL" if policy.approval else "APPROVED",
        requested_by=current.user_id, outcome={}, idempotency_key=key,
        created_at=now, updated_at=now)
    db.add(action)
    if not commit:
        db.flush()
        return action
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        action = db.query(AiAction).filter(AiAction.idempotency_key == key).one()
    db.refresh(action)
    return action


def decide_action(db, ctx, action_id, approve, note):
    action = owned_action(db, ctx, action_id)
    policy = _policy(action.action_type)
    require_action_permission(db, ctx, policy.permission)
    requester = requester_context(db, action)
    require_publish_action_scope(db, ctx, action, requester)
    if not policy.approval or not action.approval_required:
        raise ActionError(409, "此 Action 不需要人工审批")
    if not note.strip():
        raise ActionError(400, "审批意见不能为空")
    status = "APPROVED" if approve else "REJECTED"
    changed = db.execute(update(AiAction).where(
        AiAction.id == action.id, AiAction.status == "PENDING_APPROVAL").values(
        status=status, approved_by=ctx.user_id if approve else None,
        outcome={"approval_note": note.strip()[:1000], "approval_impersonating": ctx.is_impersonating},
        updated_at=datetime.utcnow()))
    if changed.rowcount != 1:
        db.rollback()
        raise ActionError(409, "Action 已离开待审批状态")
    db.commit()
    db.refresh(action)
    return action


def execute_action(db, ctx, action_id, *, commit=True):
    action = owned_action(db, ctx, action_id)
    policy = _policy(action.action_type)
    if action.action_type == "UPDATE_LISTING_COMPLIANCE_RISK":
        table = Tenant.__table__
        db.execute(table.update().where(table.c.id == action.tenant_id).values(id=table.c.id))
    if action.action_type == "REFRESH_BUILTIN_TRENDS":
        lock_refresh(db, action.tenant_id)
    if not commit and action.action_type != "UPDATE_LISTING_COMPLIANCE_RISK":
        raise ActionError(400, "外部原子事务仅支持合规风险投影")
    if (action.agent_type not in policy.agents
            or action.required_permission != policy.permission
            or action.risk_level != policy.risk
            or action.approval_required != policy.approval
            or action.target_type != policy.target_type
            or action.execution_mode != ("APPROVAL_REQUIRED" if policy.approval else "AUTO_SAFE")):
        raise ActionError(409, "Action 与服务端策略不一致，禁止执行")
    require_action_permission(db, ctx, policy.permission)
    requester = requester_context(db, action)
    require_publish_action_scope(db, ctx, action, requester)
    if action.status == "SUCCESS":
        if action.action_type == "REFRESH_BUILTIN_TRENDS":
            validate_refresh(db, action, _payload(action), replay=True)
        if action.action_type == "UPDATE_LISTING_COMPLIANCE_RISK":
            validate_risk_projection(db, action, _payload(action))
        return action
    if action.status != "APPROVED":
        raise ActionError(409, "Action 尚未获批或已终止")
    if policy.approval and not action.approved_by:
        raise ActionError(409, "缺少人工审批记录")
    require_publish_approver(db, action)
    changed = db.execute(update(AiAction).where(
        AiAction.id == action.id, AiAction.status == "APPROVED").values(
        status="EXECUTING", updated_at=datetime.utcnow()))
    if changed.rowcount != 1:
        if not commit:
            raise ActionError(409, "Action 已被其他执行者领取")
        db.rollback()
        db.refresh(action)
        if action.status == "SUCCESS":
            return action
        raise ActionError(409, "Action 已被其他执行者领取")
    if action.action_type == "PUBLISH_LISTING" and _payload(action).get("shop_id") is not None:
        db.commit()  # 外部发布前先持久化已审批意图和领取状态。
    try:
        payload = _payload(action)
        if action.action_type == "ADJUST_AD_BUDGET":
            facts = action_content.budget_facts(db, action.tenant_id, action.target_id, payload)
            if any(facts[key] != action.evidence.get(key)
                   for key in ("old_budget", "spend", "revenue")):
                raise ActionError(409, "审批期间预算或经营数据已变化，请新建 Action")
        outcome = HANDLERS[action.action_type](db, action, payload)
        action.status = "SUCCESS"
        action.executed_by = ctx.user_id
        action.executed_at = datetime.utcnow()
        action.updated_at = action.executed_at
        action.outcome = {**(action.outcome or {}), **outcome}
        if commit:
            db.commit()
        else:
            db.flush()
    except Exception as exc:  # 执行器边界：意外数据库/平台异常也必须留失败终态。
        logger.error("Action %s 执行失败：%s", action.id, type(exc).__name__)
        if not commit:
            raise  # 可信保存服务整批回滚，失败不得留下报告与未完成风险副本。
        db.rollback()
        db.refresh(action)
        action.status = "FAILED"
        action.updated_at = datetime.utcnow()
        action.outcome = {**(action.outcome or {}), "error": redact(str(exc))[:2000],
                          "target_type": action.target_type, "target_id": action.target_id,
                          "target_snapshot": _snapshot(db, action)}
        db.commit()
    return action


def _snapshot(db, action):
    if action.target_type == "tenant":
        return {"tenant_id": action.tenant_id}
    model = {"product": Product, "listing": Listing, "ad_campaign": AdCampaign}[action.target_type]
    row = db.get(model, action.target_id)
    if row is None or row.tenant_id != action.tenant_id:
        return {"exists": False}
    fields = ("id", "status", "risk_level", "budget", "spend", "revenue", "updated_at")
    return {key: value.isoformat() if isinstance(value, datetime) else value
            for key in fields if (value := getattr(row, key, None)) is not None}
