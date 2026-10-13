"""Launch 共享状态内核：快照、纯函数 diff、事件、序号、AiAction 投影与回执落地。

执行框架（launch_actions）、刷新（launch_runtime）与读模型（launch_dto）共用本模块，
保证「同一事实 -> 同一状态迁移 -> 同一事件」只有一份实现（设计 D10）。
"""

import hashlib
import json
from copy import deepcopy

from sqlalchemy import func

from ..models import AiAction, WorkflowEvent, utcnow
from ..services.pii_redact import redact
from .launch_plan import recover_running_steps
from .launch_rules import WAITING, evaluate_readiness

# 可落地的等待态：规则对 WAITING 是粘滞的（设计 R1），回执/核验事实在此显式落地。
_LANDABLE_WAITS = frozenset(WAITING - {"FAILED"})

# AiAction 状态 -> 步骤状态投影（设计 D4）：SUCCESS 不投影，交给回执落地。
_ACTION_PROJECTION = {
    "PENDING_APPROVAL": "WAITING_APPROVAL",
    "APPROVED": "WAITING_APPROVAL",
    "EXECUTING": "RUNNING",
    "FAILED": "FAILED",
    "REJECTED": "READY",
}


def state_snapshot(run, steps) -> dict:
    """事件 before/after 的流程状态快照（自 launch_runtime._snapshot 迁出，语义不变）。"""
    return {"revision": run.revision, "execution_status": run.execution_status,
            "platform_status": run.platform_status, "verification_status": run.verification_status,
            "current_step": run.current_step, "blocked_reason": deepcopy(run.blocked_reason),
            "steps": {step.step_code: {"status": step.step_status,
                                       "blocking_reason": deepcopy(step.blocking_reason),
                                       "input_revision": step.input_revision} for step in steps}}


def plan_changes(run, steps, plan, *, overrides=None, run_overrides=None, receipt=None, now=None) -> dict:
    """纯计算 run/步骤 diff：{"run": {...}, "steps": {code: {...}}}（不碰 DB）。

    - run：execution_status/current_step/blocked_reason 取自 plan；platform_status 按 receipt
      投影（仅 NOT_SUBMITTED/UNKNOWN，绝不自动置 ACTIVE/VERIFIED）；转 COMPLETED 且
      completed_at 为空时补 completed_at；started_at 既有逻辑。
    - steps：plan 驱动 status/blocking_reason/input_revision，再合并 overrides 迁移：
      ``step_status``/``external_*`` 等标量为绝对值（断言覆盖计划），``result`` 浅合并，
      ``evidence_refs`` 去重追加，``attempts_delta`` 折算为绝对 attempts。
    - run_overrides：handler 断言的 run 级字段（如 platform_status/ended_at），后于 receipt 投影生效。
    抛 ValueError（计划与实例不一致时由调用方转换）。
    """
    values = {"execution_status": plan["execution_status"], "current_step": plan["current_step"],
              "blocked_reason": {"items": plan["blockers"]} if plan["blockers"] else {}}
    if receipt is not None and run.platform_status in {"NOT_SUBMITTED", "UNKNOWN"}:
        projected = receipt.get("platform_status")
        if projected:
            values["platform_status"] = projected
    for name, value in (run_overrides or {}).items():
        values[name] = value
    changed = {name: value for name, value in values.items() if getattr(run, name) != value}
    if changed.get("execution_status") == "COMPLETED" and run.completed_at is None:
        changed["completed_at"] = now or utcnow()
    step_changes = {}
    for step in steps:
        target = plan["steps"].get(step.step_code)
        if target is None:
            raise ValueError("就绪度计划缺少步骤：" + str(step.step_code))
        updates = {name: value for name, value in {"step_status": target["status"],
                   "blocking_reason": target["blocking_reason"]}.items() if getattr(step, name) != value}
        if target["invalidated"]:
            updates["input_revision"] = step.input_revision + 1
        updates.update(_step_override(step, (overrides or {}).get(step.step_code)))
        if updates:
            step_changes[step.step_code] = updates
    if (changed or step_changes) and run.started_at is None:
        changed["started_at"] = now or utcnow()
    return {"run": changed, "steps": step_changes}


def _step_override(step, override):
    """把投影/断言迁移折算为绝对字段值（result 合并、evidence_refs 追加、attempts 折算）。"""
    if not override:
        return {}
    updates = {}
    for name, value in override.items():
        if name == "result":
            updates["result"] = {**(step.result or {}), **value}
        elif name == "evidence_refs":
            existing = list(step.evidence_refs or [])
            updates["evidence_refs"] = existing + [ref for ref in value if ref not in existing]
        elif name == "attempts_delta":
            updates["attempts"] = step.attempts + value
        else:
            updates[name] = value
    return updates


def next_sequence(db, run_id: int) -> int:
    """下一个事件序号（uq_workflow_event_sequence 兜底并发写入）。"""
    value = db.query(func.coalesce(func.max(WorkflowEvent.sequence), 0) + 1).filter(
        WorkflowEvent.run_id == run_id).scalar()
    return int(value)


def append_event(db, run, *, event_type: str, idempotency_key: str, source: str,
                 actor_id: int | None, before: dict, after: dict, payload: dict,
                 sequence: int | None = None) -> WorkflowEvent:
    """写不可变事件；payload/before/after 深度脱敏后落库（AC-11.2），调用方负责事务。"""
    event = WorkflowEvent(
        tenant_id=run.tenant_id, workspace_id=run.workspace_id, run_id=run.id, actor_id=actor_id,
        sequence=next_sequence(db, run.id) if sequence is None else sequence,
        event_type=event_type, idempotency_key=idempotency_key, source=source,
        before=deep_redact(before), after=deep_redact(after), payload=deep_redact(payload),
        profile_version=run.workflow_version)
    db.add(event)
    db.flush()
    return event


def deep_redact(value):
    """递归脱敏：字符串按 pii_redact.redact 替换，容器结构与标量原样保留。"""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: deep_redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [deep_redact(item) for item in value]
    return value


def action_step_projection(db, run, steps) -> dict[str, dict]:
    """AiAction 状态 -> 步骤状态投影（只读）。

    经 ``evidence.launch_id``/``evidence.step_code`` 关联本流程步骤（参考 routers/actions.py
    的 JSON 查询模式）；仅返回与持久状态不同的迁移，保证 FAILED 时 attempts+1 只发生一次。
    """
    by_code = {step.step_code: step for step in steps}
    if not by_code:
        return {}
    rows = db.query(AiAction).filter(
        AiAction.tenant_id == run.tenant_id, AiAction.workspace_id == run.workspace_id,
        AiAction.evidence["launch_id"].as_integer() == run.id,
        AiAction.evidence["step_code"].as_string().in_(list(by_code))).order_by(AiAction.id).all()
    latest = {action.evidence.get("step_code"): action for action in rows}
    projections = {}
    for code, action in latest.items():
        target = _ACTION_PROJECTION.get(action.status)
        step = by_code.get(code)
        if target is None or step is None or step.step_status == target:
            continue
        migration = {"step_status": target}
        if action.status == "FAILED":
            migration["result"] = {"error": redact(
                str((action.outcome or {}).get("error") or "外部执行失败"))[:2000]}
            migration["attempts_delta"] = 1
        elif action.status == "REJECTED":
            migration["result"] = {"rejection_note": redact(
                str((action.outcome or {}).get("approval_note") or ""))[:500]}
        projections[code] = migration
    return projections


def land_completed_waits(db, run, steps, plan, facts) -> dict[str, dict]:
    """completion_satisfied 的等待态步骤按完成条件落地 COMPLETED（只读判定）。

    - PLATFORM_SUBMISSION：需 result.action_id 对应 AiAction.status==SUCCESS 且 facts 有
      submission_receipt；固定 receipt 进 result + evidence_refs=["attempt:{id}"]。
    - PLATFORM_ACTIVATION：需 result.activation_verification.current 存在。
    - 其他业务类型不落地（未接通无意图解析）。返回 {step_code: 迁移字典}。
    """
    receipt = platform_receipt(facts)
    landings = {}
    for step in steps:
        if step.step_status not in _LANDABLE_WAITS:
            continue
        target = plan["steps"].get(step.step_code) or {}
        if target.get("completion_satisfied") is not True:
            continue
        result = step.result or {}
        if step.business_type == "PLATFORM_SUBMISSION":
            action_id = result.get("action_id")
            action = db.get(AiAction, action_id) if type(action_id) is int else None
            if action is None or action.status != "SUCCESS" or receipt is None:
                continue
            landings[step.step_code] = {"step_status": "COMPLETED", "result": {"receipt": receipt},
                                        "evidence_refs": ["attempt:%s" % receipt["attempt_id"]]}
        elif step.business_type == "PLATFORM_ACTIVATION":
            if not ((result.get("activation_verification") or {}).get("current")):
                continue
            landings[step.step_code] = {"step_status": "COMPLETED"}
    return landings


def canonical_json(value) -> str:
    """规范化 JSON（与 profile_schema.fingerprint 同风格）：排序键、紧凑分隔、禁 NaN。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def facts_digest(facts: dict, predicates: dict) -> str:
    """事实指纹：sha256(canonical_json([facts, predicates]))，NBA evidence_fingerprint 基底。"""
    return hashlib.sha256(canonical_json([facts, predicates]).encode("utf-8")).hexdigest()


def platform_receipt(facts: dict) -> dict | None:
    """取提交回执（无则 None）；仅 succeeded 且匹配 listing+shop 的 Attempt 才会出现。"""
    platform = facts.get("platform") if isinstance(facts, dict) else None
    receipt = platform.get("submission_receipt") if isinstance(platform, dict) else None
    return receipt or None


def asserted_world(effect_run_fields, effect_result, step, facts, predicates):
    """handler 断言后的新世界事实（收敛重算基底）：run 字段镜像进 facts，核验记录派生谓词。

    plan_changes 仍以旧持久状态为基准，两者分工保证「断言 -> 重算 -> diff」不丢变更；
    当前只镜像 platform_status（facts.platform.status 的唯一来源）与 ACTIVATION 核验谓词。
    """
    world_facts, world_predicates = deepcopy(facts), deepcopy(predicates)
    for name, value in (effect_run_fields or {}).items():
        if name == "platform_status":
            world_facts.setdefault("platform", {})["status"] = value
    if step is not None and step.business_type == "PLATFORM_ACTIVATION":
        if ((effect_result or {}).get("activation_verification") or {}).get("current"):
            world_predicates.setdefault("verified_artifact", {})["ACTIVATION"] = True
    return world_facts, world_predicates


def merge_migration(base: dict | None, extra: dict) -> dict:
    """合并两步迁移：标量后者覆盖，result 浅合并，evidence_refs 去重追加，attempts_delta 求和。

    动作事务内「AiAction 投影 + 回执落地 + handler 断言」可能同时作用于同一步骤
    （如外部失败投影与重试断言），合并语义与 plan_changes._step_override 保持一致。
    """
    if not base:
        return dict(extra)
    merged = dict(base)
    for name, value in extra.items():
        if name == "result":
            merged[name] = {**(base.get(name) or {}), **value}
        elif name == "evidence_refs":
            existing = list(base.get(name) or [])
            merged[name] = existing + [ref for ref in value if ref not in existing]
        elif name == "attempts_delta":
            merged[name] = base.get(name, 0) + value
        else:
            merged[name] = value
    return merged


def converge(db, run, steps, plan, facts, predicates, definition, *, activated=False,
             cancelled=False, assertions=None):
    """状态收敛（设计 D10 第 2 步）：AiAction 投影 + 回执落地迭代至不动点。

    - assertions：handler 断言的迁移（{step_code: migration}），先于投影/落地进入状态；
    - 返回 (plan, overrides)：plan 为收敛后就绪度计划，overrides 为合并迁移字典，
      直接供 launch_state.plan_changes 消费；
    - 迭代上界为步骤数（DAG 无环必收敛），cancelled 时只按终态重算、不做落地。
    """
    overrides = {code: dict(migration) for code, migration in (assertions or {}).items()}
    states = {step.step_code: step.step_status for step in steps}
    for code, migration in overrides.items():
        if "step_status" in migration:
            states[code] = migration["step_status"]
    if overrides or cancelled:
        plan = evaluate_readiness(definition.model_dump(), states, facts, predicates,
                                  activated=activated, cancelled=cancelled)
    for _ in range(len(steps) + 1):
        if cancelled:
            break
        migrations = dict(action_step_projection(db, run, steps))
        migrations.update(land_completed_waits(db, run, steps, plan, facts))
        migrations.update(recover_running_steps(db, run, steps))
        settled = False
        for code, migration in migrations.items():
            merged = merge_migration(overrides.get(code), migration)
            if merged == overrides.get(code):
                continue
            overrides[code] = merged
            if "step_status" in migration:
                states[code] = migration["step_status"]
            settled = True
        if not settled:
            break
        plan = evaluate_readiness(definition.model_dump(), states, facts, predicates,
                                  activated=activated)
    return plan, overrides
