"""AI Action 的独立提交、审批和幂等执行入口（D47）。

当前只开放 ADJUST_AD_BUDGET；动作目录按显式白名单扩展，不能接受 Agent
自报的风险等级、权限或执行模式。业务写入只在 execute() 中发生。
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import AdCampaign, AiAction, User
from .ad_campaigns import apply_budget_change
from .workspace_context import SOURCE_LEGACY, WorkspaceContext, resolve_workspace_context


class ActionError(ValueError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _tenant_id(db: Session, ctx: WorkspaceContext) -> int:
    """由服务端身份解析租户；Membership 的 workspace id 不能当 tenant id。"""
    if ctx.workspace_id is None or ctx.is_platform_identity():
        raise ActionError(403, "当前身份没有业务 Workspace")
    if ctx.source == SOURCE_LEGACY:
        tenant_id = ctx.legacy_tenant_id
    else:
        tenant_id = db.execute(text(
            "SELECT tenant_id FROM workspace_profiles WHERE id = :workspace_id"),
            {"workspace_id": ctx.workspace_id}).scalar_one_or_none()
    if tenant_id is None or tenant_id != ctx.legacy_tenant_id:
        raise ActionError(403, "Workspace 与租户归属不一致")
    return tenant_id


def _require_finance(db: Session, ctx: WorkspaceContext) -> int:
    tenant_id = _tenant_id(db, ctx)
    if not ctx.has("finance:write"):
        raise ActionError(403, "缺少权限：finance:write")
    return tenant_id


def finance_scope(db: Session, ctx: WorkspaceContext) -> int:
    """供 Action API 使用的服务端租户与权限校验。"""
    return _require_finance(db, ctx)


def _target(db: Session, tenant_id: int, campaign_id: int) -> AdCampaign:
    campaign = db.get(AdCampaign, campaign_id)
    if campaign is None or campaign.tenant_id != tenant_id:
        raise ActionError(404, "广告活动不存在")
    return campaign


def _suggested_budget(campaign: AdCampaign) -> tuple[float, float]:
    roi = ((campaign.revenue - campaign.spend) / campaign.spend
           if campaign.spend else 0.0)
    if roi > 2:
        return roi, min(500.0, round(campaign.budget * 1.3, 2))
    if roi < 0.8:
        return roi, max(5.0, round(campaign.budget * 0.6, 2))
    return roi, campaign.budget


def submit_budget_action(db: Session, ctx: WorkspaceContext, proposal: dict) -> AiAction | None:
    """四道闸前两道在服务端复核；HIGH 风险固定进入人工审批。"""
    tenant_id = _require_finance(db, ctx)
    campaign_id = int(proposal["campaign_id"])
    campaign = _target(db, tenant_id, campaign_id)
    roi, expected = _suggested_budget(campaign)
    old = float(proposal["old_budget"])
    new = float(proposal["new_budget"])
    if not all(math.isfinite(value) for value in (old, new, roi)):
        raise ActionError(400, "预算或 ROI 数值无效")
    if abs(old - campaign.budget) > 0.001 or abs(new - expected) > 0.001:
        raise ActionError(409, "建议与当前预算或经营数据不一致，请重新计算")
    if new == old:
        return None  # 维持预算没有业务写入，不创建空 Action
    existing = (db.query(AiAction).filter(
        AiAction.tenant_id == tenant_id,
        AiAction.action_type == "ADJUST_AD_BUDGET",
        AiAction.target_id == campaign_id,
        AiAction.status.in_(("PENDING_APPROVAL", "APPROVED")))
        .order_by(AiAction.id.desc()).first())
    if existing is not None:
        if (existing.evidence.get("old_budget") == old
                and existing.expected_impact.get("new_budget") == new):
            return existing
        raise ActionError(409, "该广告活动已有待处理的预算审批")
    now = datetime.utcnow()
    action = AiAction(
        tenant_id=tenant_id, workspace_id=ctx.workspace_id, task_id=None,
        agent_type="ads", action_type="ADJUST_AD_BUDGET",
        target_type="ad_campaign", target_id=campaign_id,
        reason=str(proposal["reason"])[:2000],
        evidence={"old_budget": old, "roi": round(roi, 4),
                  "spend": campaign.spend, "revenue": campaign.revenue},
        expected_impact={"new_budget": new, "delta": round(new - old, 2)},
        risk_level="HIGH", required_permission="finance:write",
        execution_mode="APPROVAL_REQUIRED", approval_required=True,
        status="PENDING_APPROVAL", requested_by=ctx.user_id,
        outcome={}, idempotency_key=uuid.uuid4().hex,
        created_at=now, updated_at=now)
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def owned_action(db: Session, ctx: WorkspaceContext, action_id: int) -> AiAction:
    tenant_id = _tenant_id(db, ctx)
    action = db.get(AiAction, action_id)
    if (action is None or action.tenant_id != tenant_id
            or action.workspace_id != ctx.workspace_id):
        raise ActionError(404, "Action 不存在")
    return action


def decide_budget_action(db: Session, ctx: WorkspaceContext, action_id: int,
                         approve: bool, note: str) -> AiAction:
    _require_finance(db, ctx)
    action = owned_action(db, ctx, action_id)
    if action.action_type != "ADJUST_AD_BUDGET":
        raise ActionError(400, "不支持的 Action 类型")
    if action.status != "PENDING_APPROVAL":
        raise ActionError(409, "Action 已离开待审批状态")
    if not note.strip():
        raise ActionError(400, "审批意见不能为空")
    action.status = "APPROVED" if approve else "REJECTED"
    action.approved_by = ctx.user_id if approve else None
    action.outcome = {"approval_note": note.strip()[:1000]}
    action.updated_at = datetime.utcnow()
    db.commit()
    return action


def execute_budget_action(db: Session, ctx: WorkspaceContext, action_id: int) -> AiAction:
    _require_finance(db, ctx)
    action = owned_action(db, ctx, action_id)
    if action.action_type != "ADJUST_AD_BUDGET":
        raise ActionError(400, "不支持的 Action 类型")
    if action.status == "SUCCESS":
        return action  # 同一 Action 重复调用不产生第二次副作用
    if action.status != "APPROVED":
        raise ActionError(409, "Action 尚未获批或已终止")
    requester = db.get(User, action.requested_by)
    if requester is None or requester.status != "active":
        raise ActionError(403, "发起者身份已失效")
    requester_ctx = resolve_workspace_context(db, requester)
    if (requester_ctx.workspace_id != action.workspace_id
            or not requester_ctx.has(action.required_permission)):
        raise ActionError(403, "发起者已失去执行权限")
    campaign = _target(db, action.tenant_id, action.target_id)
    old = float(action.evidence["old_budget"])
    new = float(action.expected_impact["new_budget"])
    _, expected = _suggested_budget(campaign)
    if abs(campaign.budget - old) > 0.001 or abs(expected - new) > 0.001:
        action.status = "FAILED"
        action.outcome = {"error": "审批期间预算或经营数据已变化，请新建 Action"}
        action.updated_at = datetime.utcnow()
        db.commit()
        return action
    # 业务行和 Action 终态在同一事务提交；崩溃时整体回滚，可安全重试。
    action.status = "EXECUTING"
    db.flush()
    apply_budget_change(db, action.tenant_id, campaign.id, old, new)
    action.status = "SUCCESS"
    action.executed_by = ctx.user_id
    action.executed_at = datetime.utcnow()
    action.updated_at = action.executed_at
    action.outcome = {**(action.outcome or {}), "old_budget": old,
                      "new_budget": new, "campaign_id": campaign.id}
    db.commit()
    return action


def action_dict(action: AiAction) -> dict:
    return {"id": action.id, "action_type": action.action_type,
            "target_type": action.target_type, "target_id": action.target_id,
            "reason": action.reason, "evidence": action.evidence,
            "expected_impact": action.expected_impact, "risk_level": action.risk_level,
            "execution_mode": action.execution_mode, "approval_required": action.approval_required,
            "status": action.status, "requested_by": action.requested_by,
            "approved_by": action.approved_by, "outcome": action.outcome}
