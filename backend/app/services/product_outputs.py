"""商品提案提交、范围恢复和业务结果组装；由 Orchestrator 调用。"""

from ..models import AiAction
from .action_system import execute_action, submit_action
from .ai_actions import ActionError


def recover_product(db, ctx, product_id, scope_key):
    action = db.query(AiAction).filter(
        AiAction.tenant_id == ctx.legacy_tenant_id,
        AiAction.workspace_id == ctx.workspace_id, AiAction.requested_by == ctx.user_id,
        AiAction.action_type == "UPDATE_PRODUCT_CONTENT", AiAction.target_id == product_id,
        AiAction.evidence["scope_key"].as_string() == str(scope_key)).first()
    return finish_product(db, ctx, action) if action is not None else None


def finish_product(db, ctx, action):
    if action.status in {"FAILED", "REJECTED", "EXECUTING"}:
        raise ActionError(409, "标准化 Action 已终止或正执行，请人工检查")
    action = execute_action(db, ctx, action.id)
    if action.status != "SUCCESS":
        raise ActionError(409, action.outcome.get("error", "商品标准化失败"))
    return {**action.outcome["result"], "action_id": action.id,
            "action_status": action.status}


def recover_range(db, ctx, scope_key, supplied):
    action = db.query(AiAction).filter(
        AiAction.tenant_id == ctx.legacy_tenant_id,
        AiAction.workspace_id == ctx.workspace_id, AiAction.requested_by == ctx.user_id,
        AiAction.action_type == "UPDATE_PRODUCT_CONTENT",
        AiAction.evidence["scope_manifest"]["scope"].as_string() == str(scope_key)).first()
    if action is None:
        return supplied
    ids = action.evidence["scope_manifest"]["product_ids"]
    if supplied is not None and list(dict.fromkeys(supplied[:200])) != ids:
        raise ActionError(409, "同一工作流范围的商品清单已变化")
    return ids


def finalize_product(db, ctx, output, scope_key, scope_manifest=None):
    proposal = output["_action_proposal"]
    # 范围清单（批量/工作流）必须落在各自的 Action 证据里，供断点恢复使用；
    # 因此只在单商品直接调用时启用「目标值未变→复用既有成功 Action」。
    same = _unchanged_success(db, ctx, proposal) if scope_manifest is None else None
    if same is not None:
        # 重复请求且目标值已等于上次成功结果：复用既有 Action，不再造第二个写动作。
        return {**same.outcome["result"], "action_id": same.id,
                "action_status": same.status, "idempotent_replay": True}
    action = submit_action(db, ctx, "product", proposal, scope_key,
                           scope_manifest=scope_manifest,
                           extra_evidence=output.get("_action_proposal_evidence"))
    return finish_product(db, ctx, action)


def _unchanged_success(db, ctx, proposal):
    """最近一次成功标准化写入的目标值，是否与本次提案完全一致。

    为什么按「目标值」而不是整份 payload 比较：payload.before 里含 ``updated_at``，
    每次读都不同；若按整份比较，同一商品的重复请求永远命中不了，会不断新建 Action。
    """
    payload = proposal.get("payload") or {}
    target_values = {key: value for key, value in payload.items() if key != "before"}
    if not target_values:
        return None
    previous = (db.query(AiAction)
                .filter(AiAction.tenant_id == ctx.legacy_tenant_id,
                        AiAction.workspace_id == ctx.workspace_id,
                        AiAction.requested_by == ctx.user_id,
                        AiAction.action_type == "UPDATE_PRODUCT_CONTENT",
                        AiAction.target_id == proposal["target_id"],
                        AiAction.status == "SUCCESS")
                .order_by(AiAction.id.desc()).first())
    if previous is None:
        return None
    previous_values = {key: value for key, value in
                       (previous.evidence.get("payload") or {}).items() if key != "before"}
    return previous if previous_values == target_values else None


def batch_result(results, errors, manifest):
    standardized = [row["product_id"] for row in results if not row["is_duplicate"]]
    duplicates = [row["product_id"] for row in results if row["is_duplicate"]]
    return {"standardized": standardized, "duplicates": duplicates, "results": results,
            "_standardization_manifest": manifest,
            "errors": errors, "business_status": "blocked" if errors else "success",
            "context_patch": {} if errors else {"product_ids": standardized,
                                                 "duplicate_product_ids": duplicates}}
