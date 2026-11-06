"""确定性 Next Best Action（B02）：纯函数，输入仅服务端事实，同输入双算一致（设计 D6）。

不读时钟、不随机、不访问 DB；排序键完全确定：
``(外部确认者, 是否解除阻断, 到期时间, sequence, step_code)``。
AI 层只能在 ``allowed_actions`` 内解释或重排（子集），不得新增动作（PRD §5.3）。
"""

from datetime import datetime

from .launch_action_catalog import PRICE_STOCK_ACTIONS, action_meta
from .launch_status import is_verified_online

# 外部确认者 actor：不依赖外部确认者的动作优先（安全依赖排序，设计 D6/PRD §5.2）。
_EXTERNAL_ACTORS = frozenset({"PLATFORM", "REVIEWER", "FACTORY"})
# run 级动作：不在任何步骤词表内、始终按 run 级评估（CANCEL 可用性供前端渲染按钮）。
_RUN_LEVEL_ACTIONS = ("CANCEL",)
_MAX_DT = datetime.max
_RUN_RANK = 10 ** 6   # run 级动作排序垫底，不抢占步骤动作的 next_best_action
_ROLE_HINTS = {"USER": "运营", "AI": "智能助手", "SYSTEM": "系统",
               "PLATFORM": "平台", "REVIEWER": "复核人", "FACTORY": "工厂门户"}


def cancellable(run) -> bool:
    """run 是否可取消（AC-8.3/8.4/7.6）：已结束/已完成/已核验在售一律不可取消。"""
    if run is None or run.ended_at is not None or run.execution_status == "CANCELLED":
        return False
    if run.execution_status == "COMPLETED":
        return False
    return not is_verified_online(run)


def action_block_reason(action, meta, effective_status, plan_step, permissions, run):
    """动作不可执行的确定性原因；None 表示可执行（NBA 与 StepDTO 共用，零 DB 访问）。"""
    if not meta.connected:
        return meta.disabled_reason or "动作尚未接通"
    missing = [key for key in meta.permissions if key not in permissions]
    if missing:
        return "缺少权限：" + missing[0]
    if effective_status is not None and effective_status not in meta.source_states:
        return "步骤当前状态不允许该动作"
    if action == "COMPLETE_DATA" and (plan_step or {}).get("completion_satisfied") is not True:
        return "完成条件尚未被服务端事实满足"
    if meta.target == "run" and not cancellable(run):
        return "当前流程不能取消"
    return None


def compute_nba(plan, steps, definitions, permissions, *, role, revision, facts_digest, run):
    """计算确定性 NBA；输入仅服务端事实，输出结构见设计 §3.1/PRD §5.2。"""
    by_code = {step.step_code: step for step in steps}
    plan_steps = plan.get("steps") or {}
    ordered, disabled = [], []
    for code in sorted(plan_steps, key=lambda item: (_sequence(definitions, item), item)):
        step, definition, plan_step = by_code.get(code), definitions.get(code), plan_steps[code]
        if step is None or definition is None or plan_step.get("status") != "READY":
            continue   # 仅 READY 步骤进入候选（AC-9.8：并行 READY 分支都在）
        for action in definition.available_actions:
            if role == "COMPLIANCE" and action in PRICE_STOCK_ACTIONS:
                continue   # COMPLIANCE 投影剔除：完全移除，不是置灰（设计 D8）
            meta = action_meta(action)
            reason = action_block_reason(action, meta, "READY", plan_step, permissions, run)
            if reason is None:
                entry = _allowed(action, meta, step.step_code, revision, facts_digest)
                ordered.append((_order_key(definition, plan_step, meta, step), entry))
            else:
                disabled.append(_disabled(action, step.step_code, reason))
    ordered.extend(_run_level(permissions, role, revision, facts_digest, run, disabled))
    ranked = [entry for _, entry in sorted(ordered, key=lambda pair: pair[0])]
    return {"allowed_actions": ranked, "disabled_actions": disabled,
            "blocked_reason": list(plan.get("blockers") or []),
            "owner": owner_of(plan, by_code, run),
            "next_best_action": _next_best(ranked, disabled), "ordering": "rule"}


def owner_of(plan, by_code, run):
    """当前焦点步骤的负责人（AC-9.4）：actor + assigned_user_id（USER 兜底创建者）。"""
    step = by_code.get(plan.get("current_step")) or _focus_fallback(by_code)
    if step is None:
        return {"actor": None, "user_id": None}
    actor = step.actor or "USER"
    user_id = step.assigned_user_id
    if user_id is None and actor == "USER":
        user_id = run.created_by
    return {"actor": actor, "user_id": user_id, "role_hint": _ROLE_HINTS.get(actor, actor)}


def recommendations(nba, plan):
    """确定性解释条目（source=rule，无 AI 生成内容，AC-2.4）：每个 allowed_action 与 blocker 各一条。"""
    items = [{"target": entry["step_code"], "reason": "可执行动作：" + entry["action"], "source": "rule"}
             for entry in nba["allowed_actions"]]
    items += [{"target": blocker.get("step_code") or "",
               "reason": blocker.get("message") or "存在阻断", "source": "rule"}
              for blocker in nba["blocked_reason"]]
    return items


def next_action_summary(nba):
    """列表用精简下一动作 {action, step_code, executable, reason?, owner}。"""
    best = nba.get("next_best_action") or {}
    return {"action": best.get("action"), "step_code": best.get("step_code"),
            "executable": bool(best.get("executable")), "reason": best.get("disabled_reason"),
            "owner": nba.get("owner")}


def _run_level(permissions, role, revision, facts_digest, run, disabled):
    """run 级动作（CANCEL）：可用则入候选（排序垫底），不可用则入禁用清单。"""
    pairs = []
    for action in _RUN_LEVEL_ACTIONS:
        if role == "COMPLIANCE" and action in PRICE_STOCK_ACTIONS:
            continue
        meta = action_meta(action)
        reason = action_block_reason(action, meta, None, {}, permissions, run)
        if reason is None:
            pairs.append(((_RUN_RANK, 1, _MAX_DT, _RUN_RANK, ""),
                          _allowed(action, meta, "", revision, facts_digest)))
        else:
            disabled.append(_disabled(action, "", reason))
    return pairs


def _sequence(definitions, code):
    definition = definitions.get(code)
    return definition.sequence if definition is not None else 0


def _order_key(definition, plan_step, meta, step):
    external = 1 if (meta.approval_required or definition.actor in _EXTERNAL_ACTORS) else 0
    unblocks = 0 if plan_step.get("blocking_reason") else 1
    return (external, unblocks, step.deadline_at or _MAX_DT, definition.sequence, definition.step_code)


def _focus_fallback(by_code):
    if not by_code:
        return None
    return min(by_code.values(), key=lambda step: (getattr(step, "seq", 0), step.step_code))


def _allowed(action, meta, step_code, revision, facts_digest):
    return {"action": action, "step_code": step_code,
            "permission": meta.permissions[0] if meta.permissions else "",
            "approval_required": meta.approval_required, "risk": meta.risk,
            "expected_revision": revision, "evidence_fingerprint": facts_digest}


def _disabled(action, step_code, reason):
    return {"action": action, "step_code": step_code, "disabled_reason": reason}


def _next_best(ranked, disabled):
    if ranked:
        return {"action": ranked[0]["action"], "step_code": ranked[0]["step_code"], "executable": True}
    if disabled:
        return {"action": disabled[0]["action"], "step_code": disabled[0]["step_code"],
                "executable": False, "disabled_reason": disabled[0]["disabled_reason"]}
    return {"action": None, "step_code": None, "executable": False}
