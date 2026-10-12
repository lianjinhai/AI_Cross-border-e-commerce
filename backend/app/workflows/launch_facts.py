"""Launch 服务端事实读取；未接入的领域事实保持 UNKNOWN，不能用请求载荷补齐。"""

from ..models import Listing, PlatformPublishAttempt, Product, Shop, WorkflowStep
from ..services.asset_rights import evaluate_asset_rights
from .launch_access import LaunchError


def load_launch_facts(db, run):
    """读取主行后计算事实（既有签名不变）；抛 LaunchError 同既有契约。"""
    product = db.get(Product, run.product_id, populate_existing=True)
    listing = db.get(Listing, run.listing_id, populate_existing=True)
    shop = db.get(Shop, run.shop_id, populate_existing=True)
    attempt = _attempt(db, run)
    return _facts(db, run, product, listing, shop, attempt)


def launch_facts_from_rows(db, run, product, listing, shop, attempt):
    """列表批预取复用：主行由调用方提供，仅保留 asset_rights 与核验步骤查询。"""
    return _facts(db, run, product, listing, shop, attempt)


def _facts(db, run, product, listing, shop, attempt):
    if (any(row is None or row.tenant_id != run.tenant_id for row in (product, listing, shop))
            or listing.product_id != product.id or listing.shop_id != shop.id):
        raise LaunchError("LAUNCH_TARGET_INVALID", "流程商品、店铺或派生稿关系不一致", 409)
    if (shop.archived_at is not None or shop.role != "sales" or shop.platform == "1688"
            or shop.platform != run.platform or shop.market != run.market
            or shop.fulfillment_mode != run.fulfillment_mode or listing.platform != run.platform):
        raise LaunchError("LAUNCH_CONTEXT_CHANGED", "店铺经营上下文已变化，需要核对当前流程", 409)
    facts = {"product": {"title": product.title, "category": product.category},
             "listing": {"title": listing.title}, "platform": {"status": run.platform_status}}
    receipt = _receipt(run, shop, attempt)
    if receipt is not None:
        # 提交回执只支持 submission 条件，绝不据此设置 ACTIVE/VERIFIED。
        facts["platform"]["submission_reference"] = attempt.external_id
        facts["platform"]["submission_receipt"] = receipt
    rights = evaluate_asset_rights(db, run.tenant_id, product, shop)
    facts["assets"] = {"rights_fingerprint": rights["fingerprint"], "versions": rights["versions"],
                       "reasons": rights["reasons"]}
    # PriceReview/StockPreparation 等尚未接入的领域事实，不读取 UI 勾选或旧 risk_level 代替核验。
    return facts, {"asset_rights_allowed": {"PUBLISHABLE": rights["allowed"]},
                   "verified_artifact": {"ACTIVATION": _activation_verified(db, run)}}


def _attempt(db, run):
    return db.query(PlatformPublishAttempt).filter_by(tenant_id=run.tenant_id, listing_id=run.listing_id,
                                                      shop_id=run.shop_id, platform=run.platform).first()


def _receipt(run, shop, attempt):
    """提交回执（设计 D4 回写基底）：仅匹配 listing+shop、succeeded 且 external_id 非空。"""
    if not (attempt and attempt.status == "succeeded" and attempt.external_id
            and attempt.listing_id == run.listing_id and attempt.shop_id == run.shop_id
            and attempt.platform == run.platform
            and (run.environment == "CONTRACT_TEST" or not shop.is_demo)):
        return None
    return {"attempt_id": attempt.id, "external_id": attempt.external_id,
            "platform_status": attempt.platform_status, "verification_status": attempt.verification_status,
            "external_object_type": attempt.external_object_type, "mapping_version": attempt.mapping_version,
            "received_at": attempt.received_at.isoformat() if attempt.received_at else None}


def _activation_verified(db, run):
    """据 PLATFORM_ACTIVATION 步骤的核验记录派生在售核验谓词（设计 D5）。"""
    step = db.query(WorkflowStep).filter_by(run_id=run.id, business_type="PLATFORM_ACTIVATION").first()
    if step is None:
        return False
    current = ((step.result or {}).get("activation_verification") or {}).get("current")
    return bool(current)
