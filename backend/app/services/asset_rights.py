"""发布素材权利门禁：只用适用范围内的当前版本，UNKNOWN/RESTRICTED 不放行。"""

import hashlib
import json

from ..models import ProductAsset, utcnow
from .asset_schema import IMAGE_TYPES, RIGHTS_ALLOWED


def evaluate_asset_rights(db, tenant_id, product, shop, *, now=None):
    now = now or utcnow()
    if product.tenant_id != tenant_id or shop.tenant_id != tenant_id or not shop.market:
        return {"allowed": False, "reasons": ["素材目标归属或市场不完整"], "versions": [], "fingerprint": ""}
    rows = db.query(ProductAsset).filter_by(tenant_id=tenant_id, product_id=product.id).order_by(
        ProductAsset.asset_key, ProductAsset.version.desc()).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.asset_key, row)
    applicable = [row for row in latest.values() if row.market == shop.market and row.platform == shop.platform]
    reasons, versions = [], []
    images = product.images or []
    if not images:
        reasons.append("缺少可发布图片")
    for uri in images:
        matches = [row for row in applicable if row.uri == uri and row.asset_type in IMAGE_TYPES]
        if len(matches) != 1:
            reasons.append("图片缺少唯一的当前权利记录：" + str(uri)[:160])
            continue
        row = matches[0]
        versions.append({"id": row.id, "version": row.version, "hash": row.content_hash,
                         "rights_status": row.rights_status, "verification_status": row.verification_status,
                         "evidence": row.rights_evidence_ref})
        if (row.rights_status not in RIGHTS_ALLOWED or not row.source.strip()
                or (row.rights_status in {"SUPPLIER_AUTHORIZED", "LICENSED"} and not row.rights_evidence_ref)):
            reasons.append("图片权利未知、受限或缺授权证据：" + row.asset_key)
        if row.verification_status not in {"MANUAL_REPORTED", "VERIFIED"}:
            reasons.append("图片来源或权利记录已被驳回、失效或状态未知：" + row.asset_key)
        if (row.valid_from and now < row.valid_from) or (row.valid_until and now >= row.valid_until):
            reasons.append("图片授权不在有效期内：" + row.asset_key)
    fingerprint = hashlib.sha256(json.dumps({"images": images, "versions": versions, "reasons": reasons,
                                             "market": shop.market, "platform": shop.platform},
                                            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"allowed": not reasons, "reasons": reasons, "versions": versions, "fingerprint": fingerprint}
