"""租户演示数据清理：按外键依赖顺序删除，保证 FK 约束下也能成功。

为什么需要本模块：
    开启 SQLite 外键强制（app/db.py）后，原先「Order → Conversation →
    AdCampaign → Listing → Product」的删除顺序会被外键拦截：
    conversations.order_id / refund_orders.order_id / order_fees.order_id /
    order_lines.order_id 引用 orders；messages.conversation_id 引用
    conversations；supplier_offers / listings / product_scores /
    pricing_records / compliance_reports / purchase_orders 等引用 products。
    任一引用未先清理，DELETE 就会 IntegrityError（接口 500）。

设计原则：
    1. 子表在前、父表在后（严格按外键拓扑序，见 _PURGE_PLAN 注释）；
    2. 只删演示业务数据，不碰账号、设置、店铺授权配置与知识库；
    3. 全程单事务提交，失败整体回滚，不留下半清空状态。

复用方：routers/shops.py 的 POST /api/shops/purge_demo_data。
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    AdCampaign,
    ComplianceReport,
    Conversation,
    ForecastOutcome,
    ForecastSnapshot,
    InventorySnapshot,
    KnowledgeCandidate,
    Listing,
    ListingReviewDecision,
    Message,
    OpportunityAttribution,
    OpportunitySupplierMatch,
    Order,
    OrderFee,
    OrderLine,
    PlatformPublishAttempt,
    PricingRecord,
    Product,
    ProductComplianceEvidence,
    ProductPerformance,
    ProductScore,
    PurchaseOrder,
    RefundOrder,
    SupplierOffer,
)

# 删除顺序 = 外键拓扑序（被引用者必须后删）。每一项都含 tenant_id，按租户隔离。
_PURGE_PLAN = (
    (Message, "messages"),                                   # → conversations
    (RefundOrder, "refunds"),                                # → orders
    (OrderFee, "order_fees"),                                # → orders
    (OrderLine, "order_lines"),                              # → orders / listings / products
    (KnowledgeCandidate, "knowledge_candidates"),             # → conversations / knowledge_docs
    (Conversation, "conversations"),                         # → orders / products
    (PlatformPublishAttempt, "publish_attempts"),            # → listings / shops
    (ListingReviewDecision, "listing_reviews"),              # → listings / products
    (ComplianceReport, "compliance_reports"),                # → products / listings
    (AdCampaign, "ad_campaigns"),                            # → products
    (OpportunityAttribution, "opportunity_attributions"),    # → opportunity_supplier_matches
    (OpportunitySupplierMatch, "opportunity_supplier_matches"),  # → products / suppliers
    (ForecastOutcome, "forecast_outcomes"),                  # → forecast_snapshots
    (ForecastSnapshot, "forecast_snapshots"),                # → products
    (PurchaseOrder, "purchase_orders"),                      # → products / orders / shops
    (SupplierOffer, "supplier_offers"),                      # → products / suppliers
    (ProductScore, "product_scores"),                        # → products
    (PricingRecord, "pricing_records"),                      # → products
    (Order, "orders"),                                       # → products / listings / shops
    (Listing, "listings"),                                   # → products
    (ProductPerformance, "product_performances"),            # → products（M1 飞轮缓存）
    (ProductComplianceEvidence, "product_compliance_evidence"),  # → products（目的国合规证据，D58）
    (InventorySnapshot, "inventory_snapshots"),                # → products / warehouses（海外仓在库快照，D59）
    (Product, "products"),                                   # 最上层，最后删
)


def purge_tenant_demo_data(db: Session, tenant_id: int) -> dict[str, int]:
    """删除某租户的全部演示业务数据，返回各表删除条数。

    调用方负责事务语义：本函数只在末尾 commit 一次，异常时整体回滚。
    """
    counts: dict[str, int] = {}
    for model, label in _PURGE_PLAN:
        counts[label] = int(
            db.query(func.count(model.id)).filter(model.tenant_id == tenant_id).scalar() or 0)
        (db.query(model)
         .filter(model.tenant_id == tenant_id)
         .delete(synchronize_session=False))
    db.commit()
    return counts
