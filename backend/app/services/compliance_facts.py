"""可信合规依据读取：当前租户目标、关联商品及只读知识规则。"""

from ..ai.knowledge import _tf_retrieve
from ..models import ComplianceReport, Listing, Product
from .ai_actions import ActionError
from .compliance_analysis import QUERIES, inputs
from .review_analysis import digest

SOURCE = "compliance_analysis_v1"


def targets(db, tenant_id, target_type, ref_id):
    if target_type not in {"product", "listing"} or type(ref_id) is not int or ref_id <= 0:
        raise ActionError(400, "合规目标类型或 ID 无效")
    target = db.get(Product if target_type == "product" else Listing, ref_id, populate_existing=True)
    product = (target if target_type == "product" else
               db.get(Product, target.product_id, populate_existing=True) if target else None)
    if (target is None or target.tenant_id != tenant_id or product is None
            or product.tenant_id != tenant_id or product.status == "deleted"):
        raise ActionError(404, "合规目标或关联商品不存在")
    return target, product


def current_basis(db, ctx, item):
    target, product = targets(db, ctx.legacy_tenant_id, item["target_type"], item["ref_id"])
    knowledge = {"mode": "not_used", "brands": [], "platform": []}
    if ctx.has("ai:read"):
        knowledge = {"mode": "readonly_tf", **{
            key: _tf_retrieve(db, ctx.legacy_tenant_id, query, limit)
            for key, (query, limit) in zip(("brands", "platform"), QUERIES, strict=True)}}
    fields = {key: getattr(target, key) for key in ("id", "title")}
    fields.update({key: getattr(target, key) for key in
                   (("attrs", "images", "status") if item["target_type"] == "product" else
                    ("product_id", "platform", "description", "bullets", "keywords"))})
    product_fields = {key: getattr(product, key) for key in ("id", "title", "attrs", "images", "status")}
    # Tool 字典对空 JSON 字段统一为 []/{}。
    product_fields.update(attrs=product.attrs or {}, images=product.images or [])
    if item["target_type"] == "product":
        fields.update(attrs=target.attrs or {}, images=target.images or [])
    else:
        fields.update(bullets=target.bullets or [], keywords=target.keywords or [])
    return inputs(item["target_type"], fields, product_fields, knowledge)


def latest_report(db, tenant_id, item):
    field = ComplianceReport.product_id if item["target_type"] == "product" else ComplianceReport.listing_id
    return db.query(ComplianceReport).filter(ComplianceReport.tenant_id == tenant_id,
        ComplianceReport.target_type == item["target_type"], field == item["ref_id"]
    ).order_by(ComplianceReport.id.desc()).populate_existing().first()


def public_report(row):
    return {"id": row.id, "target_type": row.target_type, "product_id": row.product_id,
            "listing_id": row.listing_id, "risk_level": row.risk_level, "score": float(row.score),
            "issues": row.issues, "suggestions": row.suggestions, "model": row.model,
            "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S")}


def metadata(ctx, scope, items):
    return {"source": SOURCE, "scope": scope, "items": items, "workspace_id": ctx.workspace_id,
            "requested_by": ctx.user_id, "key": digest([ctx.workspace_id, ctx.user_id, scope]),
            "_impersonating": ctx.is_impersonating}
