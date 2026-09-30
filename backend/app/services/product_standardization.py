"""商品安全标准化规则与 Action 执行业务边界。"""

import hashlib
import math
import re
from datetime import datetime

from ..models import Product, Tenant
from .action_identity import requester_context
from .ai_actions import ActionError

SAFE_ATTRS = {"weight_kg", "material", "color"}
CATEGORIES = {"家居", "3C配件", "宠物用品", "户外运动", "美妆工具", "母婴用品", "厨房用品", "服饰配件"}


def _weight(value, fallback=0.3):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return number if not isinstance(value, bool) and math.isfinite(number) and 0 < number <= 1000 else fallback


def snapshot(product):
    return {key: product.get(key) for key in
            ("title", "category", "attrs", "dedupe_hash", "status", "updated_at")}


def safe_fields(product, category, suggested=None):
    """只补安全属性；已有属性保留，经营字段不接受模型建议。"""
    attrs = product.get("attrs") or {}
    suggested = suggested if isinstance(suggested, dict) else {}
    match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|千克)", product["title"].lower())
    defaults = {"weight_kg": _weight(match.group(1)) if match else 0.3,
                "material": "PP", "color": "多色"}
    patch = {}
    for key in SAFE_ATTRS:
        value = attrs.get(key) or suggested.get(key) or defaults[key]
        if key == "weight_kg":
            value = _weight(value, defaults[key])
        elif not isinstance(value, str) or not value.strip() or len(value) > 128:
            value = defaults[key]
        patch[key] = value
    category = category if isinstance(category, str) and category in CATEGORIES else "家居"
    norm = re.sub(r"\s+", "", product["title"].lower())[:20]
    digest = hashlib.sha256(
        f"{category}|{norm}|{patch['material']}|{patch['color']}".encode()).hexdigest()[:16]
    return {"category": category, "attrs_patch": patch, "dedupe_hash": digest}


def update_product_content(db, action, payload):
    # 按租户串行化查重与更新；跨不同商品的并发提案也必须看见前一笔结果。
    table = Tenant.__table__
    db.execute(table.update().where(table.c.id == action.tenant_id).values(id=table.c.id))
    requester_context(db, action)
    row = db.query(Product).filter(Product.id == action.target_id,
        Product.tenant_id == action.tenant_id).populate_existing().with_for_update().one_or_none()
    if row is None:
        raise ActionError(404, "商品不存在")
    current = {"title": row.title, "category": row.category, "attrs": row.attrs or {},
               "dedupe_hash": row.dedupe_hash, "status": row.status,
               "updated_at": row.updated_at.isoformat() if row.updated_at else None}
    if set(payload) != {"before", "category", "attrs_patch", "dedupe_hash"}:
        raise ActionError(400, "商品标准化载荷字段无效")
    if payload["before"] != current or row.status == "deleted":
        raise ActionError(409, "商品已变化，请重新生成标准化提案")
    patch = payload["attrs_patch"]
    if not isinstance(patch, dict) or set(patch) != SAFE_ATTRS:
        raise ActionError(400, "商品标准化仅允许安全属性")
    validated = safe_fields(current, payload["category"], patch)
    if validated != {key: payload[key] for key in validated}:
        raise ActionError(400, "商品标准化字段或指纹无效")
    candidates = db.query(Product).filter(
        Product.tenant_id == action.tenant_id, Product.id != row.id,
        Product.status != "deleted", Product.dedupe_hash == validated["dedupe_hash"]
    ).order_by(Product.id).all()
    duplicate = next((candidate.id for candidate in candidates
        if safe_fields({"title": candidate.title, "attrs": candidate.attrs},
                       candidate.category)["dedupe_hash"] == validated["dedupe_hash"]), None)
    row.category = validated["category"]
    row.attrs = {**(row.attrs or {}), **patch}
    row.dedupe_hash = validated["dedupe_hash"]
    row.updated_at = datetime.utcnow()
    db.flush()
    return {"before": current, "result": {
        "product_id": row.id, "category": row.category, "attrs": row.attrs,
        "dedupe_hash": row.dedupe_hash, "is_duplicate": bool(duplicate),
        "duplicate_of": duplicate or 0}}
