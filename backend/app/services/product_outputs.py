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
    action = submit_action(db, ctx, "product", proposal, scope_key,
                           scope_manifest=scope_manifest)
    return finish_product(db, ctx, action)


def batch_result(results, errors, manifest):
    standardized = [row["product_id"] for row in results if not row["is_duplicate"]]
    duplicates = [row["product_id"] for row in results if row["is_duplicate"]]
    return {"standardized": standardized, "duplicates": duplicates, "results": results,
            "_standardization_manifest": manifest,
            "errors": errors, "business_status": "blocked" if errors else "success",
            "context_patch": {} if errors else {"product_ids": standardized,
                                                 "duplicate_product_ids": duplicates}}
