"""AI 能力矩阵（服务端唯一口径）：当前身份能用哪些 Action、不能用为什么。

为什么要单独成模块：前端过去只能靠「把架构里的动作全部渲染成按钮」来猜能力，
于是出现「按钮点了才知道没权限」和「不知道某个 Agent 到底有没有实现」。这里以
**代码注册表**为准（`action_policy.POLICIES` + `action_system.HANDLERS` +
`contracts.CONTRACTS` + `workspace_context` 的权限），一次性把
「能力 / 风险 / 是否需审批 / 当前身份是否可用 / 阻断原因」算清楚，前端只做展示，
不自行推断，也不把未注册能力渲染成可执行。

只读：不含任何凭证、不触发写库、不改变任何策略。
"""
from __future__ import annotations

from ..services.action_policy import POLICIES
from ..services.store_scope import StoreScopeError, resolve_store_scope

# 证据带 shop_id、受店铺数据范围约束的 Action 类型。
_SCOPED_ACTION_TYPE = "PUBLISH_LISTING"


def _action_entries(ctx):
    from ..services.action_system import HANDLERS  # 延迟导入：避免 policy → system 循环

    entries = []
    for action_type, policy in POLICIES.items():
        reasons: list[str] = []
        if action_type not in HANDLERS:
            reasons.append("执行器未注册：该动作当前不可执行")
        if not ctx.has(policy.permission):
            reasons.append(f"缺少权限 {policy.permission}")
        entries.append({
            "action_type": action_type,
            "agents": sorted(policy.agents),
            "target_type": policy.target_type,
            "risk": policy.risk,
            "approval_required": policy.approval,
            "required_permission": policy.permission,
            "handler_registered": action_type in HANDLERS,
            "rollback": policy.rollback,
            "enabled": not reasons,
            "blocked_reasons": reasons,
        })
    return entries


def _scope_blocked(db, ctx):
    """发布类动作需要销售店铺范围；拿不到就是明确的阻断原因，而不是静默失败。"""
    try:
        resolve_store_scope(db, ctx)
    except StoreScopeError as exc:
        return str(exc)
    return ""


def capability_matrix(db, ctx) -> dict:
    """返回 {identity, actions, agents, summary}；所有字段均来自注册表与当前上下文。"""
    from .contracts import CONTRACTS

    actions = _action_entries(ctx)
    scope_reason = _scope_blocked(db, ctx)
    for entry in actions:
        if entry["action_type"] != _SCOPED_ACTION_TYPE or not scope_reason:
            continue
        entry["enabled"] = False
        entry["blocked_reasons"].append(f"店铺范围不可用：{scope_reason}")

    agents = []
    for contract in CONTRACTS.values():
        agents.append({
            "agent_name": contract.agent_name,
            "domain": contract.domain,
            "risk_level": contract.risk_level,
            "required_permissions": sorted(contract.required_permissions),
            "required_data_scope": contract.required_data_scope,
            # 该 Agent 在服务端实际注册了哪些 Action（policy.agents 反查，不靠文档枚举）。
            "action_types": sorted(k for k, p in POLICIES.items()
                                   if contract.agent_name in p.agents),
            "known_gaps": list(contract.known_gaps),
        })

    enabled = sum(1 for entry in actions if entry["enabled"])
    return {
        "identity": {
            "workspace_id": ctx.workspace_id,
            "role": ctx.role,
            "data_scope": ctx.data_scope,
            "permissions": sorted(ctx.permissions),
        },
        "actions": actions,
        "agents": agents,
        "summary": {"total": len(actions), "enabled": enabled,
                    "blocked": len(actions) - enabled,
                    "registered_handlers": sum(1 for e in actions if e["handler_registered"])},
    }
