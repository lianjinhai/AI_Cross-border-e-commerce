"""由 Orchestrator 调用的输出落库适配器；Agent 本身不调用 Guardrail。"""

from ..models import AiDecision
from .action_system import execute_action, submit_action
from .ai_actions import ActionError


def finalize_ad_drafts(db, ctx, output, scope_key):
    drafts = []
    for index, item in enumerate(output["campaign_drafts"]):
        result = dict(item)
        slot = result.pop("_proposal_slot", index)
        proposal = result.pop("_action_proposal")
        action = submit_action(db, ctx, "ads", proposal, f"{scope_key}:{slot}")
        action = execute_action(db, ctx, action.id)
        if action.status != "SUCCESS":
            raise ActionError(409, (action.outcome or {}).get("error", "广告草稿执行失败"))
        result.update(action.outcome["result"])
        drafts.append({**result, "action_id": action.id, "action_status": action.status})
    return {"campaign_drafts": drafts, "business_status": "success",
            "context_patch": {"campaign_ids": [item["id"] for item in drafts]}}


def finalize_listing_output(db, ctx, output, scope_key):
    """接管草稿、内容优化和发布；人工审批动作绝不在这里自动执行。"""
    if "published" in output:
        items = [finalize_listing_output(db, ctx, item, f"{scope_key}:{index}")
                 for index, item in enumerate(output["published"])]
        published = [item for item in items if item["action_status"] == "SUCCESS"]
        pending = [item for item in items if item["action_status"] != "SUCCESS"]
        return {"published": published, "pending": pending, "blocked": output["blocked"],
                "business_status": "blocked" if pending or output["blocked"] else "success",
                "context_patch": {"published_product_ids": [item["product_id"] for item in published],
                                  "pending_action_ids": [item["action_id"] for item in pending]}}
    if "listings" in output:
        listings = [finalize_listing_output(db, ctx, item, f"{scope_key}:{item.get('_proposal_slot', index)}")
                    for index, item in enumerate(output["listings"])]
        return {**output, "listings": listings,
                "business_status": "blocked" if output.get("errors") else "success",
                "context_patch": {"listing_ids": [item["id"] for item in listings]}}
    result = dict(output)
    result.pop("_proposal_slot", None)
    proposal = result.pop("_action_proposal")
    decision = result.pop("_decision_record", None)
    action = submit_action(db, ctx, "listing", proposal, scope_key)
    if action.approval_required:
        if action.status == "SUCCESS":
            result.update(action.outcome["result"])
            result["idempotent_replay"] = True
        else:
            result["status"] = action.status
        return {**result, "action_id": action.id, "action_status": action.status,
                "approval_required": True}
    action = execute_action(db, ctx, action.id)
    if action.status != "SUCCESS":
        raise ActionError(409, (action.outcome or {}).get("error", "Action 执行失败"))
    result.update(action.outcome["result"])
    result.update(action_id=action.id, action_status=action.status)
    if decision and not db.query(AiDecision).filter_by(
            tenant_id=action.tenant_id, agent="listing", action="generate_listing",
            subject_type="listing", subject_id=result["id"]).first():
        db.add(AiDecision(tenant_id=action.tenant_id, agent="listing", action="generate_listing",
                          subject_type="listing", subject_id=result["id"],
                          model=result["model"], **decision))
        db.commit()
    return result
