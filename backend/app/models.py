"""ORM 数据模型 —— 全系统的数据契约（对应规划书第18-21章数据库设计）。

多租户约定：业务表均带 tenant_id；演示部署默认单租户。
"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .secure_types import EncryptedString


def utcnow() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------- 账户/租户

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    plan: Mapped[str] = mapped_column(String(32), default="pro")          # trial/pro/enterprise
    status: Mapped[str] = mapped_column(String(16), default="active")     # active/suspended
    license_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)  # 服务授权到期
    license_note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TenantAccessLog(Base):
    """平台服务商（superadmin）代客访问审计——每次进入租户留痕。"""
    __tablename__ = "tenant_access_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(index=True)   # superadmin user id
    operator_name: Mapped[str] = mapped_column(String(64), default="")
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_tenant_access_logs_tenant_id_tenants"), index=True)
    action: Mapped[str] = mapped_column(String(64), default="enter")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    # 平台服务商（superadmin）不属于任何租户，故 tenant_id 可为 NULL。
    # 该可空性由迁移 20260923_09 引入，模型必须保持一致，否则 create_all 建出的
    # 新库与迁移后的 schema 不一致（曾导致全新部署无法插入 superadmin）。
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id"), index=True, nullable=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default="operator")  # admin/operator/viewer
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/disabled
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    """键值配置：llm / platform_fees / fx / rules 等，值为 JSON。"""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TenantSetting(Base):
    """租户级配置覆盖（P1-10 作用域隔离）。

    settings 表主键只有 key、无租户维度，若租户管理员直接写全局 key 会污染其他
    租户的定价与利润计算。本表承载 platform_fees / fx / rules 的租户级覆盖，
    读取顺序：tenant_settings → settings（平台默认）→ 代码默认。
    平台级 key（llm / 1688_api）仍只存 settings，不进入本表。
    """
    __tablename__ = "tenant_settings"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_tenant_setting"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------- 商品中心

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_products_tenant_id_tenants"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    category: Mapped[str] = mapped_column(String(64), default="")
    brand: Mapped[str] = mapped_column(String(128), default="")
    attrs: Mapped[dict] = mapped_column(JSON, default=dict)      # 标准化属性
    images: Mapped[list] = mapped_column(JSON, default=list)     # 图片 URL 列表
    source_platform: Mapped[str] = mapped_column(String(32), default="1688")  # 1688/amazon/shopee/...
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/paused/deleted
    dedupe_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_products_tenant_cat", "tenant_id", "category"),)


class ProductScore(Base):
    """选品评分（DiscoveryAgent 产出）——对应规划书第七章。"""
    __tablename__ = "product_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_product_scores_tenant_id_tenants"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    demand: Mapped[float] = mapped_column(Float, default=0)        # 需求 0-100
    competition: Mapped[float] = mapped_column(Float, default=0)   # 竞争度 0-100（越高越卷）
    profit: Mapped[float] = mapped_column(Float, default=0)        # 利润空间 0-100
    risk: Mapped[float] = mapped_column(Float, default=0)          # 风险 0-100（越高越危险）
    total: Mapped[float] = mapped_column(Float, default=0)         # 综合机会分
    reasons: Mapped[list] = mapped_column(JSON, default=list)      # 评分依据说明
    model: Mapped[str] = mapped_column(String(64), default="rule") # rule/llm:<model>
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MarketTrend(Base):
    """市场趋势/关键词（对应第六章数据采集 + 第七章机会发现）。"""
    __tablename__ = "market_trends"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_market_trends_tenant_id_tenants"), index=True)
    keyword: Mapped[str] = mapped_column(String(128))
    platform: Mapped[str] = mapped_column(String(32), default="google")
    search_volume: Mapped[int] = mapped_column(Integer, default=0)
    growth_30d: Mapped[float] = mapped_column(Float, default=0)   # 30天增长率 %
    competition: Mapped[int] = mapped_column(Integer, default=50)  # 0-100
    note: Mapped[str] = mapped_column(String(256), default="")
    source: Mapped[str] = mapped_column(String(16), default="builtin", index=True)  # api/csv/builtin
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- 供应链

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_suppliers_tenant_id_tenants"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    region: Mapped[str] = mapped_column(String(64), default="")
    rating: Mapped[float] = mapped_column(Float, default=4.5)     # 平台评分 0-5
    ship_days: Mapped[int] = mapped_column(Integer, default=7)
    settlement_days: Mapped[int] = mapped_column(Integer, default=30)  # 账期天数
    stability: Mapped[float] = mapped_column(Float, default=80)   # 稳定性 0-100
    supplier_type: Mapped[str] = mapped_column(String(32), default="trader")  # factory/trader/platform
    verification_status: Mapped[str] = mapped_column(String(24), default="verified")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    certifications: Mapped[list] = mapped_column(JSON, default=list)
    source_kind: Mapped[str] = mapped_column(String(32), default="manual")
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    source_checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("uq_supplier_source", "tenant_id", "name", "source_url", unique=True),)


class SupplierEvidence(Base):
    """供应商证据链；公开目录只证明被收录，不等同于工商/产能尽调。"""
    __tablename__ = "supplier_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_supplier_evidence_tenant_id_tenants"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32))
    source_url: Mapped[str] = mapped_column(String(1024))
    source_title: Mapped[str] = mapped_column(String(256), default="")
    observed_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("uq_supplier_evidence", "tenant_id", "supplier_id",
                            "source_url", unique=True),)


class SupplierPortalMember(Base):
    """工厂门户账号与单一供应商的最小权限绑定。"""
    __tablename__ = "supplier_portal_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_supplier_portal_members_tenant_id_tenants"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SupplierCatalogProduct(Base):
    """由工厂自维护的真实供给目录；进入销售商品池前仍需机会和合规复核。"""
    __tablename__ = "supplier_catalog_products"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_supplier_catalog_products_tenant_id_tenants"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    factory_sku: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512))
    category: Mapped[str] = mapped_column(String(128), default="")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    attrs: Mapped[dict] = mapped_column(JSON, default=dict)
    images: Mapped[list] = mapped_column(JSON, default=list)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    moq: Mapped[int] = mapped_column(Integer, default=1)
    lead_days: Mapped[int] = mapped_column(Integer, default=7)
    monthly_capacity: Mapped[int] = mapped_column(Integer, default=0)
    available_qty: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("uq_supplier_catalog_sku", "tenant_id", "supplier_id",
                            "factory_sku", unique=True),)


class OpportunitySupplierMatch(Base):
    """市场商品机会与候选工厂的可解释匹配快照。"""
    __tablename__ = "opportunity_supplier_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_opportunity_supplier_matches_tenant_id_tenants"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    catalog_product_id: Mapped[int] = mapped_column(ForeignKey("supplier_catalog_products.id"), index=True)
    capability_score: Mapped[float] = mapped_column(Float, default=0)
    readiness_score: Mapped[float] = mapped_column(Float, default=0)
    total_score: Mapped[float] = mapped_column(Float, default=0)
    expected_price: Mapped[float] = mapped_column(Float, default=0)
    expected_unit_profit: Mapped[float] = mapped_column(Float, default=0)
    expected_margin: Mapped[float] = mapped_column(Float, default=0)
    expected_monthly_revenue: Mapped[float] = mapped_column(Float, default=0)
    matched_capabilities: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(String(24), default="due_diligence")
    promoted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("uq_opportunity_supplier_match", "tenant_id", "product_id",
                            "catalog_product_id", unique=True),)


class SupplierOffer(Base):
    __tablename__ = "supplier_offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_supplier_offers_tenant_id_tenants"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    price: Mapped[float] = mapped_column(Float, default=0)        # 采购价（人民币）
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    moq: Mapped[int] = mapped_column(Integer, default=1)
    ship_days: Mapped[int] = mapped_column(Integer, default=7)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SupplierScore(Base):
    __tablename__ = "supplier_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_supplier_scores_tenant_id_tenants"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    quality: Mapped[float] = mapped_column(Float, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    delivery: Mapped[float] = mapped_column(Float, default=0)
    stability: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float, default=0)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(64), default="rule")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- Listing / 合规

class Listing(Base):
    __tablename__ = "listings"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_listings_tenant_id_tenants"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_edited_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    platform: Mapped[str] = mapped_column(String(32), default="shopee")
    language: Mapped[str] = mapped_column(String(8), default="en")
    title: Mapped[str] = mapped_column(String(1024), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    bullets: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(16), default="rule")  # llm/rule（文案生成方式）
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/published/offline
    risk_level: Mapped[str] = mapped_column(String(16), default="unknown")  # low/mid/high/unknown
    external_id: Mapped[str] = mapped_column(String(64), default="")
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PlatformPublishAttempt(Base):
    """真实平台发布幂等日志；平台成功、本地响应中断后可从 checkpoint 恢复。"""
    __tablename__ = "platform_publish_attempts"
    __table_args__ = (Index("uq_publish_listing_shop", "tenant_id", "listing_id", "shop_id", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_platform_publish_attempts_tenant_id_tenants"), index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="processing")
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    external_id: Mapped[str] = mapped_column(String(128), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ForecastSnapshot(Base):
    """预测版本快照：保存训练截止点、特征、候选模型、回测和最终预测。"""
    __tablename__ = "forecast_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_forecast_snapshots_tenant_id_tenants"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    version: Mapped[str] = mapped_column(String(32))
    training_cutoff: Mapped[datetime] = mapped_column(DateTime)
    target_start: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    target_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    selected_model: Mapped[str] = mapped_column(String(64))
    point_forecast: Mapped[float] = mapped_column(Float, default=0)
    lower_bound: Mapped[float] = mapped_column(Float, default=0)
    upper_bound: Mapped[float] = mapped_column(Float, default=0)
    wape: Mapped[float] = mapped_column(Float, nullable=True)
    bias: Mapped[float] = mapped_column(Float, nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ForecastOutcome(Base):
    """预测到期后的真实销量评估；每个预测版本只生成一份可重复刷新快照。"""
    __tablename__ = "forecast_outcomes"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_forecast_outcomes_tenant_id_tenants"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("forecast_snapshots.id"), unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    target_start: Mapped[datetime] = mapped_column(DateTime)
    target_end: Mapped[datetime] = mapped_column(DateTime)
    forecast_qty: Mapped[float] = mapped_column(Float, default=0)
    actual_qty: Mapped[float] = mapped_column(Float, default=0)
    absolute_error: Mapped[float] = mapped_column(Float, default=0)
    bias: Mapped[float] = mapped_column(Float, nullable=True)
    covered: Mapped[bool] = mapped_column(Boolean, default=False)
    source_order_count: Mapped[int] = mapped_column(Integer, default=0)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OpportunityAttribution(Base):
    """已推进工厂机会的销售与利润归因快照。"""
    __tablename__ = "opportunity_attributions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_opportunity_attributions_tenant_id_tenants"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("opportunity_supplier_matches.id"), unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    attribution_start: Mapped[datetime] = mapped_column(DateTime)
    listing_ids: Mapped[list] = mapped_column(JSON, default=list)
    order_ids: Mapped[list] = mapped_column(JSON, default=list)
    published_listing_count: Mapped[int] = mapped_column(Integer, default=0)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[int] = mapped_column(Integer, default=0)
    gmv_usd: Mapped[float] = mapped_column(Float, default=0)
    net_revenue_usd: Mapped[float] = mapped_column(Float, default=0)
    contribution_profit_usd: Mapped[float] = mapped_column(Float, default=0)
    settled_net_usd: Mapped[float] = mapped_column(Float, default=0)
    lineage_method: Mapped[str] = mapped_column(String(32), default="product_after_promotion")
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ListingReviewDecision(Base):
    """上架复核记忆：保存规则版本、证据、结论及人工裁决。"""
    __tablename__ = "listing_review_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_listing_review_decisions_tenant_id_tenants"), index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(24))  # approved/rejected/manual_required
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    rule_version: Mapped[str] = mapped_column(String(32), default="")
    rule_source: Mapped[str] = mapped_column(String(512), default="")
    reviewer: Mapped[str] = mapped_column(String(32), default="listing_review_agent")
    human_override: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ComplianceReport(Base):
    """合规检测报告（ComplianceAgent 产出）——对应第十章侵权检测。"""
    __tablename__ = "compliance_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_compliance_reports_tenant_id_tenants"), index=True)
    target_type: Mapped[str] = mapped_column(String(16))          # product/listing
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")  # low/mid/high
    score: Mapped[float] = mapped_column(Float, default=100)      # 合规分 0-100
    issues: Mapped[list] = mapped_column(JSON, default=list)      # [{type, level, detail, evidence}]
    suggestions: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(64), default="rule")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- 定价 / 广告

class PricingRecord(Base):
    """成本拆解与动态定价（PricingAgent 产出）——对应第十一章。"""
    __tablename__ = "pricing_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_pricing_records_tenant_id_tenants"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    purchase_cost: Mapped[float] = mapped_column(Float, default=0)     # 采购价 CNY
    logistics_cost: Mapped[float] = mapped_column(Float, default=0)    # 物流 CNY
    platform_fee_rate: Mapped[float] = mapped_column(Float, default=0.06)
    ads_cost: Mapped[float] = mapped_column(Float, default=0)          # 单件广告费
    price: Mapped[float] = mapped_column(Float, default=0)             # 当前售价（外币）
    suggested_price: Mapped[float] = mapped_column(Float, default=0)   # 建议售价
    profit: Mapped[float] = mapped_column(Float, default=0)            # 单件真实利润（外币）
    margin: Mapped[float] = mapped_column(Float, default=0)            # 利润率 0-1
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    reason: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String(64), default="rule")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_ad_campaigns_tenant_id_tenants"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    platform: Mapped[str] = mapped_column(String(32), default="facebook")
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    budget: Mapped[float] = mapped_column(Float, default=0)       # 日预算
    spend: Mapped[float] = mapped_column(Float, default=0)
    revenue: Mapped[float] = mapped_column(Float, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/running/paused
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------- 订单 / 客服

# ---------------------------------------------------------------- 店铺授权

class Shop(Base):
    """授权店铺（多平台 OAuth）。真实授权后订单/商品从平台 API 拉取。"""
    __tablename__ = "shops"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_shops_tenant_id_tenants"), index=True)
    platform: Mapped[str] = mapped_column(String(32))            # 1688/shopee/tiktok/amazon
    shop_name: Mapped[str] = mapped_column(String(128), default="")
    shop_id: Mapped[str] = mapped_column(String(128), default="")
    app_key: Mapped[str] = mapped_column(String(128), default="")
    app_secret: Mapped[str] = mapped_column(EncryptedString(1024), default="")
    access_token: Mapped[str] = mapped_column(EncryptedString(2048), default="")
    refresh_token: Mapped[str] = mapped_column(EncryptedString(2048), default="")
    token_expire_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/authorized/expired/failed
    role: Mapped[str] = mapped_column(String(16), default="sales")  # source=货源(1688搜品/代发) sales=销售(上架/订单)
    auth_message: Mapped[str] = mapped_column(String(512), default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)  # 演示店铺（模拟拉单）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # 归档时间（软删除）：店铺被"删除"后置位，业务数据（订单/采购单/结算）仍保留引用，
    # 仅从默认列表与所有可写入口隐藏。NULL = 正常可用。
    archived_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class OAuthState(Base):
    """一次性 OAuth 回调绑定，数据库只保存 state 摘要。"""
    __tablename__ = "oauth_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_oauth_states_tenant_id_tenants"), index=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoginAttempt(Base):
    """按用户名摘要记录失败窗口，避免明文用户名进入安全日志。"""
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    identifier_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    locked_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PlatformRulePack(Base):
    """平台规则包（按平台公开文档整理，带版本号可更新）。

    发布前强制按此校验，避免违规导致店铺被处罚/封店（底线要求）。
    rules 结构：{title_max, desc_max, image_min, image_max, banned_words[],
                 banned_categories[], public_image_required, rate_limit_per_sec, notes[]}
    """
    __tablename__ = "platform_rule_packs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", name="fk_platform_rule_packs_tenant_id_tenants"), index=True, nullable=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[str] = mapped_column(String(32))             # 如 2026-09-19
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    source_url: Mapped[str] = mapped_column(String(512), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CategoryMapping(Base):
    """系统类目 -> 平台类目映射（上架前置条件，各平台类目体系不同）。"""
    __tablename__ = "category_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_category_mappings_tenant_id_tenants"), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    system_category: Mapped[str] = mapped_column(String(64))
    platform_category_id: Mapped[str] = mapped_column(String(128))
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- 采购 / 发货

class PurchaseOrder(Base):
    """采购单（对应规划第十四章"自动采购"）：

    补货预警 → 生成采购单(草稿) → 提交供应商 → 收货入库（虚拟库存增加）。
    """
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_purchase_orders_tenant_id_tenants"), index=True)
    po_no: Mapped[str] = mapped_column(String(64))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    settlement_id: Mapped[int] = mapped_column(Integer, nullable=True)  # 关联结算单，空=未结算
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    source_shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=True, unique=True)
    platform_trade_no: Mapped[str] = mapped_column(String(128), default="")
    purchase_type: Mapped[str] = mapped_column(String(24), default="stock")
    qty: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[float] = mapped_column(Float, default=0)      # 采购单价 CNY
    total: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/submitted/received/cancelled
    expected_date: Mapped[str] = mapped_column(String(32), default="")  # 预计到货（供应商发货天数推算）
    note: Mapped[str] = mapped_column(String(512), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RefundOrder(Base):
    """售后逆向流程：退款单（客服售后 + 财务闭环）。

    状态机：pending(待审核) -> approved(已同意) -> returned(已退货) -> refunded(已退款)
                                  \\-> rejected(已拒绝)
    退款完成后原订单状态流转为 refunded；退货商品可选回补虚拟库存。
    """
    __tablename__ = "refund_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_refund_orders_tenant_id_tenants"), index=True)
    refund_no: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    type: Mapped[str] = mapped_column(String(16), default="refund_only")  # refund_only/return_refund
    qty: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[float] = mapped_column(Float, default=0)               # 退款金额 USD
    reason: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")    # pending/approved/returned/refunded/rejected
    restock: Mapped[bool] = mapped_column(Boolean, default=True)          # 退货是否回补库存
    note: Mapped[str] = mapped_column(String(512), default="")
    refunded_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Settlement(Base):
    """供应商账期结算单：汇总已收货未结算采购单 -> 对账确认 -> 付款完成。"""
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_settlements_tenant_id_tenants"), index=True)
    settle_no: Mapped[str] = mapped_column(String(64))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    po_count: Mapped[int] = mapped_column(Integer, default=0)
    total_amount: Mapped[float] = mapped_column(Float, default=0)   # 应付总额 CNY
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/confirmed/paid
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_orders_tenant_id_tenants"), index=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(32))
    external_no: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[float] = mapped_column(Float, default=0)       # 销售额（USD）
    cost: Mapped[float] = mapped_column(Float, default=0)         # 采购+物流成本（USD）
    profit: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/paid/shipped/delivered/refunded
    tracking_no: Mapped[str] = mapped_column(String(64), default="")  # 物流单号（发货时生成）
    source: Mapped[str] = mapped_column(String(16), default="seed")  # seed=种子 import=CSV api=平台拉单 demo=演示 manual=手动
    country: Mapped[str] = mapped_column(String(32), default="")
    buyer_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_orders_tenant_created", "tenant_id", "created_at"),
                      Index("uq_orders_shop_external", "tenant_id", "shop_id", "platform",
                            "external_no", unique=True))


class OrderLine(Base):
    """平台订单行：保留 SKU、数量、成交价与成本快照，订单头不再承担明细粒度。"""
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_order_lines_tenant_id_tenants"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    external_line_no: Mapped[str] = mapped_column(String(128), default="")
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), nullable=True)
    sku: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    product_cost: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("uq_order_external_line", "tenant_id", "order_id",
                            "external_line_no", unique=True),)


class OrderFee(Base):
    """订单费用事实：平台佣金、支付费、税、物流、仓储及其他调整。"""
    __tablename__ = "order_fees"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_order_fees_tenant_id_tenants"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    fee_type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    source: Mapped[str] = mapped_column(String(16), default="platform")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExchangeRate(Base):
    """日级汇率版本：1 base_currency = rate quote_currency。"""
    __tablename__ = "exchange_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_exchange_rates_tenant_id_tenants"), index=True)
    base_currency: Mapped[str] = mapped_column(String(8))
    quote_currency: Mapped[str] = mapped_column(String(8), default="USD")
    rate: Mapped[float] = mapped_column(Numeric(20, 8))
    effective_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("uq_fx_tenant_pair_date", "tenant_id", "base_currency",
                            "quote_currency", "effective_at", unique=True),)


class PlatformSettlementRecord(Base):
    """销售平台结算事实，用于订单应收与实际到账对账。"""
    __tablename__ = "platform_settlement_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_platform_settlement_records_tenant_id_tenants"), index=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(32))
    external_settlement_no: Mapped[str] = mapped_column(String(128))
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    gross_amount: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    fee_amount: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    refund_amount: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    net_amount: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("uq_platform_settlement", "tenant_id", "platform",
                            "external_settlement_no", unique=True),)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_conversations_tenant_id_tenants"), index=True)
    platform: Mapped[str] = mapped_column(String(32), default="shopee")
    buyer_name: Mapped[str] = mapped_column(String(64), default="")
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open/closed
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_messages_tenant_id_tenants"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))                 # buyer/agent/operator
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(32), default="")   # order_status/logistics/refund/product_qa/other
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- AI 工作流

class Schedule(Base):
    """自主经营定时任务：到点自动执行工作流或趋势扫描（AI 运营中心）。"""
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_schedules_tenant_id_tenants"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), default="workflow")  # workflow / trend_scan
    workflow_key: Mapped[str] = mapped_column(String(64), default="")  # kind=workflow 时必填
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="")  # success/failed/running
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_workflow_templates_tenant_id_tenants"), index=True)
    key: Mapped[str] = mapped_column(String(64))                  # auto_listing / reprice / restock
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")
    steps: Mapped[list] = mapped_column(JSON, default=list)       # [{agent, action, params}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_workflow_runs_tenant_id_tenants"), index=True)
    template_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued/running/success/partial/blocked/failed
    context: Mapped[dict] = mapped_column(JSON, default=dict)     # 步骤间共享上下文
    error: Mapped[str] = mapped_column(Text, default="")
    worker_id: Mapped[str] = mapped_column(String(64), default="")
    lease_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_workflow_steps_tenant_id_tenants"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    agent: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)   # 模板步骤参数快照
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/running/success/blocked/skipped/failed
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------- 知识库 / AI 日志

class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_knowledge_docs_tenant_id_tenants"), index=True)
    title: Mapped[str] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(128), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 向量缓存（embedding 模型产出）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AiLog(Base):
    """AI 调用审计：每次 Agent/LLM 调用一条（对应第21章 AI 日志数据库）。"""
    __tablename__ = "ai_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_ai_logs_tenant_id_tenants"), index=True)
    agent: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64), default="")
    mode: Mapped[str] = mapped_column(String(16), default="rule")  # rule/llm
    prompt: Mapped[str] = mapped_column(Text, default="")
    response: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ================================================================ AI 原生能力（M1/M3/M6）

class ProductPerformance(Base):
    """商品真实经营表现（M1 选品数据飞轮）。

    仅统计真实来源订单（source in api/import/manual），演示数据不进飞轮——
    延续 commercial_analytics 的 real_only 口径（方案红线 3）。
    """
    __tablename__ = "product_performances"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_product_performances_tenant_id_tenants"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    window_days: Mapped[int] = mapped_column(Integer, default=30)
    units_sold: Mapped[int] = mapped_column(Integer, default=0)
    revenue: Mapped[float] = mapped_column(Float, default=0)
    profit: Mapped[float] = mapped_column(Float, default=0)
    margin: Mapped[float] = mapped_column(Float, default=0)          # 毛利率 0-1
    refund_rate: Mapped[float] = mapped_column(Float, default=0)     # 退款率 0-1
    sell_through: Mapped[float] = mapped_column(Float, default=0)    # 售罄率 0-1
    performance_score: Mapped[float] = mapped_column(Float, default=50)  # 归一化表现分 0-100
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AiDecision(Base):
    """AI 决策解释层（M6）：每个关键决策留依据链，可追溯、只增不删（红线 4）。

    evidence 存**引用**（订单号/趋势 id/知识文档 id/规则版本），不存全量快照。
    """
    __tablename__ = "ai_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_ai_decisions_tenant_id_tenants"), index=True)
    agent: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    subject_type: Mapped[str] = mapped_column(String(32), index=True)   # product/listing/order/...
    subject_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    decision: Mapped[dict] = mapped_column(JSON, default=dict)          # 决策结果
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)          # 依据链（引用）
    model: Mapped[str] = mapped_column(String(64), default="rule")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AiAction(Base):
    """Agent 提议的业务动作；Guardrail 审批后才可由 Executor 执行。"""

    __tablename__ = "ai_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_ai_actions_tenant_id_tenants"), index=True)
    workspace_id: Mapped[int] = mapped_column(Integer, index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_type: Mapped[str] = mapped_column(String(64))
    action_type: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_impact: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(16))
    required_permission: Mapped[str] = mapped_column(String(64))
    execution_mode: Mapped[str] = mapped_column(String(24))
    approval_required: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(24), default="CREATED", index=True)
    requested_by: Mapped[int] = mapped_column(Integer)
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    executed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AlertRule(Base):
    """主动巡检规则（M3）：阈值可配置、可单独启停。"""
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_alert_rules_tenant_id_tenants"), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)   # stockout_risk / ads_burning / ...
    name: Mapped[str] = mapped_column(String(128))
    level: Mapped[str] = mapped_column(String(16), default="mid")  # high/mid/low
    threshold: Mapped[dict] = mapped_column(JSON, default=dict)    # 可调阈值
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AlertEvent(Base):
    """巡检告警实例（M3）：只告警不执行——决策权在人（红线 1）。"""
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_alert_events_tenant_id_tenants"), index=True)
    rule_key: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16), default="mid")
    subject_type: Mapped[str] = mapped_column(String(32), default="")
    subject_id: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(256))
    detail: Mapped[str] = mapped_column(Text, default="")     # 含具体数值
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open/acked
    acked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

class KnowledgeCandidate(Base):
    """客服知识候选（M4）：未命中问题沉淀，人工验证过的答案可自动固化。

    安全红线（方案 §3-修正1）：只沉淀**人工验证过的答案**，AI 不自行编答案。
      answer_source = "operator"（客服人工回复过，可信）| "none"（无答案，永不可入库）
    时序设计（方案 §8-修正8）：候选先记录问题，operator 后续回复时回填答案，
    因为 auto_reply 与 reply 是两个独立触发端点，无法在同一时刻拿到答案。
    """
    __tablename__ = "knowledge_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_knowledge_candidates_tenant_id_tenants"), index=True)
    question_hash: Mapped[str] = mapped_column(String(32), index=True)   # 归一化哈希
    question_text: Mapped[str] = mapped_column(String(512))
    intent: Mapped[str] = mapped_column(String(32), default="other")
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=1)
    answer_source: Mapped[str] = mapped_column(String(16), default="none")  # operator/none
    answer_draft: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approved/rejected/auto_learned
    doc_id: Mapped[int] = mapped_column(ForeignKey("knowledge_docs.id"), nullable=True)
    auto_learned: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("uq_knowledge_candidate_hash", "tenant_id", "question_hash",
                            unique=True),)
