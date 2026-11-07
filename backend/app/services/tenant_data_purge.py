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
    3. 全程单事务提交，失败整体回滚，不留下半清空状态；
    4. **审批记录（`ai_actions`）随被审批对象一起清**（D65）：它对 listings/products
       只有松散引用（无外键），单独留下会在行号被复用后让新对象撞上旧提案。
       上线流程的审批证据另有保护——存在 PLATFORM_LAUNCH 运行时本函数直接拒绝清理。

复用方：routers/shops.py 的 POST /api/shops/purge_demo_data。
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    AdCampaign,
    AiAction,
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
    PriceRound,
    PricingRecord,
    Product,
    ProductAsset,
    ProductComplianceEvidence,
    ProductPerformance,
    ProductScore,
    PurchaseOrder,
    RefundOrder,
    SupplierOffer,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
)
from ..workflows.kinds import PLATFORM_LAUNCH


class DemoPurgeBlocked(ValueError):
    """上线历史不能通过旧演示清理入口删除。"""


# 外键闭环（无纯拓扑解）：products.selected_offer_id → supplier_offers.id，
# 而 supplier_offers.product_id → products.id。无论先删哪张表都会被另一条边拦住，
# 因此必须显式断环——清理前先把本租户商品的 selected_offer_id 置空。
# 新增同类互引时，同步登记在此并在 purge_tenant_demo_data 里补对应的置空语句。
_CYCLE_BREAKS = frozenset({
    ("products", "selected_offer_id", "supplier_offers"),
})

# 删除顺序 = 外键拓扑序（被引用者必须后删）。每一项都含 tenant_id，按租户隔离。
_PURGE_PLAN = (
    # 审批记录排在业务对象之前：它的 target_id 是指向 listings/products 的**松散引用**
    # （没有外键），若跟着对象一起留下，SQLite 删表后会**复用行号**，新建对象拿到同一个 id
    # 时发布意图守卫 `_existing_intent` 会把「另一个实体」判成「已发布内容变了」→ 409。
    # 见 D65。它只有 tenants 一条外键，位置不受拓扑约束，这里放最前面一是语义（连同被
    # 审批的对象一起清），二是让计数先于任何业务表。
    (AiAction, "ai_actions"),
    (WorkflowEvent, "workflow_events"),                     # → workflow_steps / workflow_runs
    (WorkflowStep, "workflow_steps"),                       # → workflow_runs
    (PriceRound, "price_rounds"),                           # → workflow_runs / products（M2-A 核价轮次）
    (WorkflowRun, "workflow_runs"),                         # → listings / products
    (ProductAsset, "product_assets"),                       # → products；有素材时门禁拒绝清理
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
    if db.query(WorkflowRun.id).filter_by(tenant_id=tenant_id, flow_kind=PLATFORM_LAUNCH).first():
        raise DemoPurgeBlocked("已有上线流程与审计记录，不能执行演示数据清理")
    if db.query(ProductAsset.id).filter_by(tenant_id=tenant_id).first():
        raise DemoPurgeBlocked("已有素材版本与权利记录，不能执行演示数据清理")
    counts: dict[str, int] = {}
    # 显式断环：products ↔ supplier_offers 互引，先把选定报价引用置空（见 _CYCLE_BREAKS）。
    # 只改引用列，商品行本身仍在计划末尾由 Product 删除。
    db.query(Product).filter(
        Product.tenant_id == tenant_id, Product.selected_offer_id.isnot(None)
    ).update({Product.selected_offer_id: None}, synchronize_session=False)
    for model, label in _PURGE_PLAN:
        counts[label] = int(
            db.query(func.count(model.id)).filter(model.tenant_id == tenant_id).scalar() or 0)
        (db.query(model)
         .filter(model.tenant_id == tenant_id)
         .delete(synchronize_session=False))
    db.commit()
    return counts
