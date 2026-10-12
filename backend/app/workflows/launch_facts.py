"""Launch 服务端事实读取；未接入的领域事实保持 UNKNOWN，不能用请求载荷补齐。"""

from ..models import Listing, PlatformPublishAttempt, Product, Shop
from ..services.asset_rights import evaluate_asset_rights
from .launch_access import LaunchError


def load_launch_facts(db, run):
    product = db.get(Product, run.product_id, populate_existing=True)
    listing = db.get(Listing, run.listing_id, populate_existing=True)
    shop = db.get(Shop, run.shop_id, populate_existing=True)
    if (any(row is None or row.tenant_id != run.tenant_id for row in (product, listing, shop))
            or listing.product_id != product.id or listing.shop_id != shop.id):
        raise LaunchError("LAUNCH_TARGET_INVALID", "流程商品、店铺或派生稿关系不一致", 409)
    if (shop.archived_at is not None or shop.role != "sales" or shop.platform == "1688"
            or shop.platform != run.platform or shop.market != run.market
            or shop.fulfillment_mode != run.fulfillment_mode or listing.platform != run.platform):
        raise LaunchError("LAUNCH_CONTEXT_CHANGED", "店铺经营上下文已变化，需要核对当前流程", 409)
    facts = {"product": {"title": product.title, "category": product.category},
             "listing": {"title": listing.title}, "platform": {"status": run.platform_status}}
    attempt = db.query(PlatformPublishAttempt).filter_by(tenant_id=run.tenant_id, listing_id=run.listing_id,
                                                        shop_id=run.shop_id, platform=run.platform).first()
    if (attempt and attempt.status == "succeeded" and attempt.external_id
            and (run.environment == "CONTRACT_TEST" or not shop.is_demo)):
        # 提交回执只支持 submission 条件，绝不据此设置 ACTIVE/VERIFIED。
        facts["platform"]["submission_reference"] = attempt.external_id
    rights = evaluate_asset_rights(db, run.tenant_id, product, shop)
    facts["assets"] = {"rights_fingerprint": rights["fingerprint"], "versions": rights["versions"]}
    # PriceReview/StockPreparation 等尚未接入的领域事实，不读取 UI 勾选或旧 risk_level 代替核验。
    return facts, {"asset_rights_allowed": {"PUBLISHABLE": rights["allowed"]}}
