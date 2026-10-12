"""商品素材版本服务；权利声明不等于核验，审批人与提交人必须不同。"""

import hashlib
import json
from copy import deepcopy

from sqlalchemy.exc import IntegrityError

from ..models import Product, ProductAsset, Shop, utcnow
from ..workflows.transactions import ensure_write_transaction
from .action_identity import fresh_context
from .ai_actions import ActionError
from .asset_schema import AssetRegistration
from .store_scope import StoreScopeError, resolve_store_scope


class AssetError(ValueError):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def _context(db, ctx, product_id, shop_id, permission):
    try:
        current = fresh_context(db, ctx)
        resolve_store_scope(db, current).require(shop_id)
    except (ActionError, StoreScopeError) as exc:
        raise AssetError("ASSET_SCOPE_DENIED", str(exc), exc.status_code) from exc
    if not current.has(permission) or not current.has("product:read"):
        raise AssetError("ASSET_PERMISSION_DENIED", "当前身份不能执行素材操作", 403)
    product, shop = db.get(Product, product_id, populate_existing=True), db.get(Shop, shop_id, populate_existing=True)
    if (product is None or product.status == "deleted" or shop is None or product.tenant_id != current.legacy_tenant_id
            or shop.tenant_id != current.legacy_tenant_id or shop.archived_at is not None or shop.role != "sales"):
        raise AssetError("ASSET_TARGET_NOT_FOUND", "商品或目标店铺不存在", 404)
    if not shop.market:
        raise AssetError("ASSET_MARKET_REQUIRED", "目标店铺缺少市场配置")
    return current, shop


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _latest(db, tenant_id, product_id, asset_key):
    return db.query(ProductAsset).filter_by(tenant_id=tenant_id, product_id=product_id, asset_key=asset_key).order_by(
        ProductAsset.version.desc()).populate_existing().first()


def register_asset(db, ctx, product_id, shop_id, payload):
    request = AssetRegistration.model_validate(payload)
    ensure_write_transaction(db)
    current, shop = _context(db, ctx, product_id, shop_id, "product:write")
    if (request.market, request.platform) != (shop.market, shop.platform):
        raise AssetError("ASSET_USAGE_MISMATCH", "素材适用范围必须与目标店铺一致")
    values = request.model_dump(exclude={"expected_version"})
    fingerprint = _hash(values)
    parent = _latest(db, current.legacy_tenant_id, product_id, request.asset_key)
    if parent and (parent.market != shop.market or parent.platform != shop.platform or parent.asset_type != request.asset_type):
        raise AssetError("ASSET_FAMILY_MISMATCH", "已有素材系列不能改变适用范围或类型", 409)
    if parent and parent.version == request.expected_version + 1 and parent.manifest.get("_registration_hash") == fingerprint:
        return parent
    if (parent.version if parent else 0) != request.expected_version:
        raise AssetError("ASSET_VERSION_CONFLICT", "素材版本已变化，请刷新后提交", 409)
    values["manifest"] = {**values["manifest"], "_registration_hash": fingerprint, "_reported_by": current.user_id}
    return _append(db, current, product_id, parent, values)


def _append(db, ctx, product_id, parent, values):
    try:
        with db.begin_nested():
            row = ProductAsset(tenant_id=ctx.legacy_tenant_id, workspace_id=ctx.workspace_id,
                               product_id=product_id, parent_asset_id=parent.id if parent else None,
                               version=parent.version + 1 if parent else 1, created_by=ctx.user_id, **values)
            db.add(row)
            db.flush()
        return row
    except IntegrityError as exc:
        raise AssetError("ASSET_VERSION_CONFLICT", "素材版本发生并发冲突，请刷新后提交", 409) from exc


def verify_asset(db, ctx, asset_id, shop_id, expected_version, *, decision, evidence_ref, reason):
    if decision not in {"VERIFIED", "REJECTED"} or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise AssetError("ASSET_REVIEW_INVALID", "需要明确的核验决定和原因")
    if (type(expected_version) is not int or expected_version < 1 or not isinstance(evidence_ref, str)
            or not evidence_ref or len(evidence_ref) > 2048):
        raise AssetError("ASSET_REVIEW_INVALID", "需要素材版本和可追溯核验依据")
    try:
        AssetRegistration.safe_reference(evidence_ref)
    except ValueError as exc:
        raise AssetError("ASSET_REVIEW_INVALID", str(exc)) from exc
    ensure_write_transaction(db)
    asset = db.get(ProductAsset, asset_id, populate_existing=True)
    if asset is None or asset.tenant_id != ctx.legacy_tenant_id or asset.workspace_id != ctx.workspace_id:
        raise AssetError("ASSET_NOT_FOUND", "素材不存在", 404)
    current, shop = _context(db, ctx, asset.product_id, shop_id, "compliance:approve")
    if (asset.market, asset.platform) != (shop.market, shop.platform):
        raise AssetError("ASSET_NOT_FOUND", "素材不适用于目标店铺", 404)
    if asset.manifest.get("_reported_by", asset.created_by) == current.user_id:
        raise AssetError("ASSET_SELF_REVIEW", "提交人不能核验自己的权利证据", 403)
    latest = _latest(db, current.legacy_tenant_id, asset.product_id, asset.asset_key)
    if latest.id != asset.id or asset.version != expected_version:
        raise AssetError("ASSET_VERSION_CONFLICT", "仅可核验当前版本", 409)
    fields = ("asset_key", "asset_type", "uri", "content_hash", "rights_status", "source",
              "rights_evidence_ref", "market", "platform", "valid_from", "valid_until")
    values = {name: getattr(asset, name) for name in fields}
    manifest = deepcopy(asset.manifest)
    manifest.pop("_registration_hash", None)
    manifest["_review"] = {"decision": decision, "reason": reason, "evidence_ref": evidence_ref,
                           "reviewed_by": current.user_id, "reviewed_at": utcnow().isoformat()}
    values.update(verification_status=decision, manifest=manifest)
    return _append(db, current, asset.product_id, asset, values)


def asset_page(db, ctx, product_id, shop_id, page_num=1, page_size=20):
    if type(page_num) is not int or page_num < 1 or type(page_size) is not int or not 1 <= page_size <= 200:
        raise AssetError("ASSET_PAGE_INVALID", "素材分页参数无效")
    current, shop = _context(db, ctx, product_id, shop_id, "product:read")
    query = db.query(ProductAsset).filter_by(tenant_id=current.legacy_tenant_id, workspace_id=current.workspace_id,
                                           product_id=product_id, platform=shop.platform, market=shop.market)
    total = query.count()
    items = query.order_by(ProductAsset.asset_key, ProductAsset.version.desc()).offset((page_num - 1) * page_size).limit(page_size).all()
    return items, total


def list_assets(db, ctx, product_id, shop_id):
    """内部有限读取；完整前端遍历必须使用 asset_page。"""
    return asset_page(db, ctx, product_id, shop_id, page_size=200)[0]
