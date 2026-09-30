"""可自动执行的草稿与商品内容业务校验；不自行提交事务。"""

import math
from datetime import datetime

from ..models import AdCampaign, Listing, Product
from ..serialize import to_dict
from .ad_campaigns import apply_budget_change
from .ai_actions import ActionError


def owned(db, model, tenant_id, target_id):
    row = db.get(model, int(target_id), populate_existing=True)
    if row is None or row.tenant_id != tenant_id:
        raise ActionError(404, "目标对象不存在")
    return row


def create_listing_draft(db, action, payload):
    owned(db, Product, action.tenant_id, action.target_id)
    title = str(payload.get("title") or "").strip()
    if not title or len(title) > 1024:
        raise ActionError(400, "Listing 标题无效")
    row = Listing(
        tenant_id=action.tenant_id, product_id=action.target_id,
        platform=str(payload["platform"])[:32], language=str(payload["language"])[:8],
        title=title, description=str(payload.get("description") or ""),
        bullets=list(payload.get("bullets") or [])[:10],
        keywords=list(payload.get("keywords") or [])[:20],
        model=payload.get("model", "rule"), status="draft", risk_level="unknown",
        created_by=action.requested_by, last_edited_by=action.requested_by)
    db.add(row)
    db.flush()
    return {"result": to_dict(row)}


def update_listing_content(db, action, payload):
    row = owned(db, Listing, action.tenant_id, action.target_id)
    if row.status != "draft":
        raise ActionError(409, "AI 自动优化只允许修改草稿 Listing")
    if payload.get("before") != {"title": row.title, "keywords": row.keywords or []}:
        raise ActionError(409, "Listing 已被编辑，请重新生成优化提案")
    title = str(payload.get("title") or "").strip()
    if not title or len(title) > 1024:
        raise ActionError(400, "Listing 标题无效")
    before = {"title": row.title, "keywords": row.keywords or []}
    row.title = title
    row.keywords = list(payload.get("keywords") or [])[:20]
    row.last_edited_by = action.requested_by
    row.updated_at = datetime.utcnow()
    db.flush()
    return {"result": to_dict(row), "before": before}




def budget_facts(db, tenant_id, campaign_id, payload):
    row = owned(db, AdCampaign, tenant_id, campaign_id)
    roi = (row.revenue - row.spend) / row.spend if row.spend else 0.0
    expected = (min(500.0, round(row.budget * 1.3, 2)) if roi > 2 else
                max(5.0, round(row.budget * 0.6, 2)) if roi < 0.8 else row.budget)
    old, new = float(payload["old_budget"]), float(payload["new_budget"])
    if not all(math.isfinite(value) for value in (old, new, roi)):
        raise ActionError(400, "预算或 ROI 数值无效")
    if abs(old - row.budget) > 0.001 or abs(new - expected) > 0.001:
        raise ActionError(409, "当前预算或经营数据已变化，请重新计算")
    return {"old_budget": old, "roi": round(roi, 4),
            "spend": row.spend, "revenue": row.revenue}


def adjust_ad_budget(db, action, payload):
    budget_facts(db, action.tenant_id, action.target_id, payload)
    row = apply_budget_change(db, action.tenant_id, action.target_id,
                              float(payload["old_budget"]), float(payload["new_budget"]))
    return {"result": {"campaign_id": row.id, "old_budget": payload["old_budget"],
                       "new_budget": row.budget}, "old_budget": payload["old_budget"],
            "new_budget": row.budget, "campaign_id": row.id}
