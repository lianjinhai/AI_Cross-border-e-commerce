"""ORM 数据模型 —— 全系统的数据契约（对应规划书第18-21章数据库设计）。

多租户约定：业务表均带 tenant_id；演示部署默认单租户。
"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
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
    # HS 归类（国际统一商品编码），关税与进口税计算的唯一依据。
    # 无编码时关税引擎按「目的国兜底税率」处理并显式标记为估算，不静默按 0 计。
    hs_code: Mapped[str] = mapped_column(String(16), default="")
    attrs: Mapped[dict] = mapped_column(JSON, default=dict)      # 标准化属性
    images: Mapped[list] = mapped_column(JSON, default=list)     # 图片 URL 列表
    source_platform: Mapped[str] = mapped_column(String(32), default="1688")  # 1688/amazon/shopee/...
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/paused/deleted
    dedupe_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    # 用户显式选定的报价（costing 优先使用，即使缺货也以该报价为准）。None = 未选定。
    # costing.best_purchase 命中 selected_offer_id 时直接采用其 to_cny 价格，覆盖「最低在库价」逻辑。
    selected_offer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("supplier_offers.id",
                            name="fk_products_selected_offer_id_supplier_offers"),
        nullable=True)
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
    # 报价有效期（人工录入/抓取来源的时效标注）。None = 长期有效。
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 来源种类：manual=人工录入（视为已核实来源）；scraped=爬虫抓取；imported=批量导入；api=接口回写。
    source_kind: Mapped[str] = mapped_column(String(32), default="manual", server_default="manual")
    # 核实状态：manual=人工已核实；verified=系统已核实；unverified=待核实；scraped=抓取待核实。
    # 注意：manual 来源在业务上即视为已核实来源（人工录入可追责），scraped/imported 默认待核实。
    verification_status: Mapped[str] = mapped_column(String(24), default="unverified", server_default="unverified")
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

class ProductAsset(Base):
    """版本化商品素材和权利证据；新版本追加，既有版本不得原地重写。"""
    __tablename__ = "product_assets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "asset_key", "version", name="uq_product_asset_version"),
        CheckConstraint("version > 0", name="ck_product_asset_version"),
        Index("ix_product_asset_usage", "tenant_id", "product_id", "market", "platform", "asset_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", name="fk_product_assets_tenant_id_tenants"), index=True)
    workspace_id: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", name="fk_product_assets_product_id_products"))
    parent_asset_id: Mapped[int | None] = mapped_column(ForeignKey("product_assets.id", name="fk_product_assets_parent_asset_id_product_assets"), nullable=True)
    asset_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    asset_type: Mapped[str] = mapped_column(String(32))
    uri: Mapped[str] = mapped_column(String(2048))
    content_hash: Mapped[str] = mapped_column(String(64))
    rights_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    source: Mapped[str] = mapped_column(String(256))
    rights_evidence_ref: Mapped[str] = mapped_column(String(2048), default="")
    market: Mapped[str] = mapped_column(String(8))
    platform: Mapped[str] = mapped_column(String(32))
    verification_status: Mapped[str] = mapped_column(String(24), default="MANUAL_REPORTED")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", name="fk_product_assets_created_by_users"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Listing(Base):
    __tablename__ = "listings"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_listings_tenant_id_tenants"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id", name="fk_listings_shop_id_shops"), nullable=True, index=True)
    parent_listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id", name="fk_listings_parent_listing_id_listings"), nullable=True)
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
    # 旧 status 仅作兼容投影；平台在售必须有独立核验证据。
    platform_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN", server_default="UNKNOWN")
    verification_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN", server_default="UNKNOWN")
    external_object_type: Mapped[str] = mapped_column(String(32), default="UNKNOWN", server_default="UNKNOWN")
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
    platform_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN", server_default="UNKNOWN")
    verification_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN", server_default="UNKNOWN")
    external_object_type: Mapped[str] = mapped_column(String(32), default="UNKNOWN", server_default="UNKNOWN")
    raw_status: Mapped[str] = mapped_column(String(256), default="", server_default="")
    # 外部事件来源留痕（状态模型 §5）：source=API/MANUAL/DEMO；source_time 为平台侧时间，
    # received_at 为本地接收时间；source_revision 用于丢弃乱序旧事件，不回退状态。
    source: Mapped[str] = mapped_column(String(32), default="", server_default="")
    source_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    external_reference: Mapped[str] = mapped_column(String(128), default="", server_default="")
    source_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mapping_version: Mapped[str] = mapped_column(String(64), default="", server_default="")
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


class PriceRound(Base):
    """核价报价轮次（M2-A）：只增不改的报价历史，每轮绑定当时的成本来源快照。

    「不得覆盖已有报价历史」的落法：本表**没有 update/delete 代码路径**，每次报价/还价
    都是插入新行；``round_no`` 按 ``(tenant_id, product_id)`` 递增且有唯一约束兜底，
    并发下不会出现两轮同号。

    ``cost_fingerprint`` 是「这一轮用的成本是不是还是当前成本」的唯一判据：采购价、
    报价来源 offer、汇率、佣金率、成本合计或毛利门槛任一变化，旧轮次的指纹就对不上，
    ``cost_snapshot_current`` 立刻转 False，核价需要重新走一遍——不是一次性通过永久生效。

    ``PricingRecord`` 是 PricingAgent 的成本拆解快照，与本表不是一回事：那张表记录
    「算过一次利润」，本表记录「报过一个价、谁批的、依据哪份成本」。
    """
    __tablename__ = "price_rounds"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "round_no", name="uq_price_rounds_tenant_product_no"),
        Index("ix_price_rounds_product_created", "tenant_id", "product_id", "id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_price_rounds_tenant_id_tenants"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    # 轮次归属的流程（可空：定价页手工试报的轮次不属于任何 run）。
    run_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_runs.id", name="fk_price_rounds_run_id_workflow_runs"),
        nullable=True, index=True)
    step_code: Mapped[str] = mapped_column(String(48), default="")
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    action: Mapped[str] = mapped_column(String(16), default="REPORT")  # REPORT/ACCEPT/COUNTER
    price: Mapped[float] = mapped_column(Float, default=0)             # 申报价（外币）
    currency: Mapped[str] = mapped_column(String(8), default="")       # 必带，空串表示未知
    margin: Mapped[float] = mapped_column(Float, default=0)            # 本轮售价的利润率 0-1
    min_margin: Mapped[float] = mapped_column(Float, default=0)        # 本轮适用的毛利门槛
    margin_ok: Mapped[bool] = mapped_column(Boolean, default=False)    # 是否过低价门禁
    cost_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)    # 成本来源快照
    cost_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    decision: Mapped[dict] = mapped_column(JSON, default=dict)         # 人工决定留痕
    created_by: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LabelPackage(Base):
    """标签包（M2-E）：按「商品 × 店铺 × 目的国」逐版生成，只增不改。

    为什么必须有这张表：``LABEL_PREPARATION`` 的完成条件是
    ``verified_artifact: LABEL_PACKAGE``，但全仓此前**没有任何生产者**——条件永远为
    UNKNOWN，步骤永远只能「未完成」，而动作 ``GENERATE_LABEL`` 又是 ``connected=False``。
    结果是：要么伪造一个布尔值让它看起来完成，要么永远卡住。两条路都不能走。

    三条不可让步的口径：

    1. **标签上的认证声明只能来自已核验证据**。``content["marks"]`` 的每一项都对应
       ``product_compliance_evidence`` 里一条 ``evidence_ref`` 非空且未过期的记录；
       缺证据就不生成，绝不用「大概是 CE」之类的推测填充。
    2. **依据变了，旧包立刻失效**。``basis_fingerprint`` 是「这一版依据的指纹」：
       要求集、每条要求的证据引用、有效期任一变化即失配，``verified_artifact`` 转
       False，标签步骤重新阻断。不靠人去记「上次是什么时候生成的」。
    3. **没有 update / delete 代码路径**。重生成 = 追加新 ``version``，旧版本永久保留，
       这样才能回答「当时印出去的那一版，依据是什么」。

    边界：``open_items`` 记录本系统**没有数据源**的字段（如进口商/欧盟责任人信息）。
    它们不阻断生成（那些信息属于店铺授权材料，不是合规证据），但会同时写进
    ``content`` 与回执，前端必须显示——不把「缺进口商信息」悄悄当成已齐备。
    """
    __tablename__ = "label_packages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "shop_id", "destination_country", "version",
                         name="uq_label_packages_tenant_product_shop_country_version"),
        Index("ix_label_packages_product_created", "tenant_id", "product_id", "id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_label_packages_tenant_id_tenants"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    # 标签按店铺隔离：不同店铺的市场/平台不同，标签不能互相顶替。
    shop_id: Mapped[int] = mapped_column(
        ForeignKey("shops.id", name="fk_label_packages_shop_id_shops"), index=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_runs.id", name="fk_label_packages_run_id_workflow_runs"),
        nullable=True, index=True)
    step_code: Mapped[str] = mapped_column(String(48), default="")
    # 归一化后的业务判定单元（欧盟成员国统一落 EU），与合规证据同一口径。
    destination_country: Mapped[str] = mapped_column(String(8), default="", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    action: Mapped[str] = mapped_column(String(16), default="GENERATE")  # GENERATE/REGENERATE
    content: Mapped[dict] = mapped_column(JSON, default=dict)           # 标签字段（不含虚构值）
    content_digest: Mapped[str] = mapped_column(String(64), default="")
    basis: Mapped[dict] = mapped_column(JSON, default=dict)             # 依据快照（要求 + 证据）
    basis_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    open_items: Mapped[list] = mapped_column(JSON, default=list)        # 无数据源、需人工补全
    created_by: Mapped[int] = mapped_column(Integer, nullable=True)
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
    market: Mapped[str] = mapped_column(String(8), default="", server_default="")
    store_type: Mapped[str] = mapped_column(String(64), default="", server_default="")
    account_type: Mapped[str] = mapped_column(String(64), default="", server_default="")
    business_mode: Mapped[str] = mapped_column(String(64), default="", server_default="")
    fulfillment_mode: Mapped[str] = mapped_column(String(32), default="", server_default="")
    capability_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    capability_evidence: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
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


# ---------------------------------------------------------------- 跨境成本：关税/物流/合规
#
# 为什么单开一节：2026 年低值包裹免税全球退坡后，关税、进口税与目的国准入认证
# 从「可忽略」变成跨境直邮的第一成本项与第一封店原因，而在此之前全库没有任何
# 关务/物流/目的国合规建模（利润算出来的是 2019 年的口径）。本节四张配置表 +
# 一张证据表构成「到岸成本」的数据底座。
#
# 配置表统一约定（与 settings_service 的三级回退同构）：
#   tenant_id = NULL  → 平台内置口径（所有租户可见，由平台服务商维护）
#   tenant_id = <id>  → 该租户的自有覆盖，优先级高于平台内置
#   两者皆无          → 代码内 DEFAULT_* 兜底（见 services/duty.py 等）
# 这样「主库尚未灌数据」时系统依旧可用，且不把参考数据硬塞进迁移。

class DutyRate(Base):
    """目的国关税税率：目的国 × HS 前缀 × 生效期。

    美国 $800 de minimis 全球暂停（E.O. 14324 及后续 EO）后全部渠道需报关缴税；
    欧盟 (EU) 2026/382 自 2026-07-01 起废除 €150 关税豁免，过渡期按 HS 税则子目
    「每件 €3」定额征收，2028-07-01 转正常税则。税率随目的国/归类/时间变化，
    因此必须是带生效期的数据表，不能写死成公式。
    """
    __tablename__ = "duty_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", name="fk_duty_rates_tenant_id_tenants"),
        nullable=True, index=True)
    destination_country: Mapped[str] = mapped_column(String(8), index=True)   # US/EU/GB/…
    hs_prefix: Mapped[str] = mapped_column(String(12), default="")            # "" = 该国兜底
    rate_type: Mapped[str] = mapped_column(String(16), default="ad_valorem")  # ad_valorem/fixed_per_item
    rate: Mapped[float] = mapped_column(Float, default=0)        # 从价：0.075；每件定额：3.0
    currency: Mapped[str] = mapped_column(String(8), default="USD")           # 定额税的币种
    de_minimis: Mapped[float | None] = mapped_column(Float, nullable=True)    # 申报货值低于此值免税
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_url: Mapped[str] = mapped_column(String(512), default="")
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("ix_duty_rates_lookup", "destination_country", "hs_prefix"),)


class LogisticsRoute(Base):
    """物流渠道计费方案（直邮/快递/头程/海外仓/FBA）。

    把物流成本从一条线性公式升级为可配置费率：计费重取
    ``max(实重, 体积重=长×宽×高/体积系数)``，再按首重 + 续重/按立方/按件计费，
    并叠加燃油与旺季附加率。泡货（体积重大于实重）此前完全未计价。
    """
    __tablename__ = "logistics_routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", name="fk_logistics_routes_tenant_id_tenants"),
        nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    channel_type: Mapped[str] = mapped_column(String(24), default="direct_mail")
    destination_country: Mapped[str] = mapped_column(String(8), default="")   # "" = 通用
    billing_method: Mapped[str] = mapped_column(String(16), default="per_kg")  # per_kg/per_cbm/per_item
    first_weight_kg: Mapped[float] = mapped_column(Float, default=0.5)
    first_weight_fee: Mapped[float] = mapped_column(Float, default=0)
    additional_per_kg: Mapped[float] = mapped_column(Float, default=0)
    per_cbm: Mapped[float] = mapped_column(Float, default=0)
    per_item: Mapped[float] = mapped_column(Float, default=0)
    volumetric_divisor: Mapped[int] = mapped_column(Integer, default=6000)
    min_charge: Mapped[float] = mapped_column(Float, default=0)
    fuel_surcharge_rate: Mapped[float] = mapped_column(Float, default=0)
    peak_surcharge_rate: Mapped[float] = mapped_column(Float, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("ix_logistics_routes_lookup", "destination_country", "channel_type"),)


class PlatformFeeSchedule(Base):
    """平台费率：平台 × 类目 × 站点 × 生效期。

    替代硬编码的 ``DEFAULT_FEES`` 单一费率。真实费率是「佣金 + 交易手续费 +
    服务费」的结构，且随类目/站点/卖家等级分层；用一个数字代表一个平台的
    费率结构，结论必然偏。
    """
    __tablename__ = "platform_fee_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", name="fk_platform_fee_schedules_tenant_id_tenants"),
        nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(64), default="")   # "" = 该平台默认
    site: Mapped[str] = mapped_column(String(16), default="")       # "" = 全部站点
    commission_rate: Mapped[float] = mapped_column(Float, default=0)
    transaction_rate: Mapped[float] = mapped_column(Float, default=0)
    service_rate: Mapped[float] = mapped_column(Float, default=0)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("ix_platform_fee_lookup", "platform", "category", "site"),)


class DestinationComplianceRule(Base):
    """目的国产品准入合规要求：目的国 × 类目 × 认证项。

    补上「只审平台规则、不审目的国法规」的缺口。CE/UKCA/FCC/FDA/CPC/PSE/KC、
    EPR/REACH/RoHS、电池 UN38.3/MSDS —— 封店/下架/罚没九成死在这些上。
    """
    __tablename__ = "destination_compliance_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", name="fk_destination_compliance_rules_tenant_id_tenants"),
        nullable=True, index=True)
    destination_country: Mapped[str] = mapped_column(String(8), index=True)
    category: Mapped[str] = mapped_column(String(64), default="")   # "" = 全部类目
    requirement: Mapped[str] = mapped_column(String(32))            # CE/FCC/FDA/EPR/UN38.3…
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_url: Mapped[str] = mapped_column(String(512), default="")
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("ix_destination_compliance_lookup",
                            "destination_country", "category"),)


class ProductComplianceEvidence(Base):
    """商品的目的国合规证据：某商品在目的国已取得某项认证及其有效期。

    没有证据表，合规门禁就只能「提示要求」而无法判定「是否已具备」——
    上架前必须能回答「这个 SKU 卖到德国，CE 和 EPR 齐了吗、过期了吗」。
    """
    __tablename__ = "product_compliance_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_product_compliance_evidence_tenant_id_tenants"),
        index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    destination_country: Mapped[str] = mapped_column(String(8), default="")
    requirement: Mapped[str] = mapped_column(String(32))
    evidence_ref: Mapped[str] = mapped_column(String(512), default="")   # 证书编号或文件 URL
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "product_id", "destination_country",
                                       "requirement", name="uq_product_compliance_evidence"),)


class Warehouse(Base):
    """海外仓 / FBA 库位：把海外仓持有成本从「路由计费」升级为库存模型。

    没有 Warehouse 表时，costing 只能把海外仓费用塞进 logistics 路由的 ``per_item``
    里——结果是把「仓储费率 × 在库天数」这种与库龄强相关的成本，错误地按出库件数
    平摊，长期库存的真实持有成本被严重低估。本表定义库位费率，``InventorySnapshot``
    记录时点库存量，二者组合出 ``holding_cost_cny = daily_fee × days_in_stock``。
    """
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", name="fk_warehouses_tenant_id_tenants"),
        nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(32))                       # 内部编码，如 FBA-US-USE1
    name: Mapped[str] = mapped_column(String(64))
    warehouse_type: Mapped[str] = mapped_column(String(16), default="overseas")  # overseas/fba/3pl
    country: Mapped[str] = mapped_column(String(8), default="")
    daily_fee_per_unit: Mapped[float] = mapped_column(Float, default=0)  # 单件日仓储费（CNY）
    inbound_fee_per_unit: Mapped[float] = mapped_column(Float, default=0)  # 入库操作费/件
    outbound_fee_per_unit: Mapped[float] = mapped_column(Float, default=0)  # 出库操作费/件
    long_term_threshold_days: Mapped[int] = mapped_column(Integer, default=90)
    long_term_surcharge_rate: Mapped[float] = mapped_column(Float, default=0.5)  # 超期附加费率
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_warehouses_tenant_code"),)


class InventorySnapshot(Base):
    """海外仓在库快照（商品 × 库位 × 时点）：用于推算库龄与持有成本。

    跨境海外仓的真实利润杀手是「库龄」：货发到海外仓卖不出去，每天扣仓储费，
    库龄超 90 天还要叠加长期库存附加费甚至销毁费。把 Medicinev 单价 × 在库
    天数算出来，才能让定价覆盖这部分成本。本表只记事实，不做计费——计费在
    ``services/inventory_service.py`` 里用快照 × Warehouse 费率推算。
    """
    __tablename__ = "inventory_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", name="fk_inventory_snapshots_tenant_id_tenants"),
        nullable=True, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    sku: Mapped[str] = mapped_column(String(64), default="")
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)  # 入库时点，库龄起算
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    note: Mapped[str] = mapped_column(String(256), default="")
    __table_args__ = (Index("ix_inventory_snapshots_lookup",
                            "tenant_id", "warehouse_id", "product_id"),)


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
    kind: Mapped[str] = mapped_column(String(16), default="workflow")  # workflow / trend_scan / alert_scan
    workflow_key: Mapped[str] = mapped_column(String(64), default="")  # kind=workflow 时必填
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_schedules_requested_by_users"), nullable=True)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", name="fk_schedules_workspace_id_tenants"), nullable=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="")  # success/failed/running/dispatched
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"
    __table_args__ = (Index("uq_workflow_profile_version", "tenant_id", "profile_key", "version", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_workflow_templates_tenant_id_tenants"), index=True)
    key: Mapped[str] = mapped_column(String(64))                  # auto_listing / reprice / restock
    flow_kind: Mapped[str] = mapped_column(String(32), default="LEGACY_AUTOMATION", server_default="LEGACY_AUTOMATION", index=True)
    profile_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    definition_status: Mapped[str] = mapped_column(String(16), default="DRAFT", server_default="DRAFT")
    environment: Mapped[str] = mapped_column(String(16), default="CONTRACT_TEST", server_default="CONTRACT_TEST")
    verification_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN", server_default="UNKNOWN")
    platform: Mapped[str] = mapped_column(String(32), default="", server_default="")
    market: Mapped[str] = mapped_column(String(8), default="", server_default="")
    store_type: Mapped[str] = mapped_column(String(64), default="", server_default="")
    account_type: Mapped[str] = mapped_column(String(64), default="", server_default="")
    business_mode: Mapped[str] = mapped_column(String(64), default="", server_default="")
    fulfillment_mode: Mapped[str] = mapped_column(String(32), default="", server_default="")
    category_scope: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    definition_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    status_mapping: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")
    steps: Mapped[list] = mapped_column(JSON, default=list)       # [{agent, action, params}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("uq_launch_active_slot", "tenant_id", "product_id", "shop_id", "active_slot", unique=True),
        Index("uq_launch_request_key", "tenant_id", "idempotency_key", unique=True),
        Index("ix_launch_workspace_shop", "tenant_id", "workspace_id", "shop_id"),
        CheckConstraint("active_slot IS NULL OR active_slot = 1", name="ck_workflow_runs_active_slot"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_workflow_runs_tenant_id_tenants"), index=True)
    template_key: Mapped[str] = mapped_column(String(64))
    flow_kind: Mapped[str] = mapped_column(String(32), default="LEGACY_AUTOMATION", server_default="LEGACY_AUTOMATION", index=True)
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", name="fk_workflow_runs_product_id_products"), nullable=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id", name="fk_workflow_runs_shop_id_shops"), nullable=True)
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id", name="fk_workflow_runs_listing_id_listings"), nullable=True)
    definition_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_templates.id", name="fk_workflow_runs_definition_id_workflow_templates"), nullable=True)
    previous_run_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_runs.id", name="fk_workflow_runs_previous_run_id_workflow_runs"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_workflow_runs_created_by_users"), nullable=True)
    workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    definition_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    definition_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    environment: Mapped[str] = mapped_column(String(16), default="CONTRACT_TEST", server_default="CONTRACT_TEST")
    platform: Mapped[str] = mapped_column(String(32), default="", server_default="")
    market: Mapped[str] = mapped_column(String(8), default="", server_default="")
    fulfillment_mode: Mapped[str] = mapped_column(String(32), default="", server_default="")
    execution_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED", server_default="NOT_STARTED")
    platform_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN", server_default="UNKNOWN")
    verification_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN", server_default="UNKNOWN")
    current_step: Mapped[str] = mapped_column(String(64), default="", server_default="")
    blocked_reason: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    next_action: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    __table_args__ = (Index("uq_launch_step_code", "run_id", "step_code", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_workflow_steps_tenant_id_tenants"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    step_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_type: Mapped[str] = mapped_column(String(32), default="", server_default="")
    execution_mode: Mapped[str] = mapped_column(String(24), default="", server_default="")
    actor: Mapped[str] = mapped_column(String(16), default="", server_default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    step_status: Mapped[str] = mapped_column(String(24), default="PENDING", server_default="PENDING")
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_workflow_steps_assigned_user_id_users"), nullable=True)
    assigned_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", name="fk_workflow_steps_assigned_supplier_id_suppliers"), nullable=True)
    external_status: Mapped[str] = mapped_column(String(128), default="", server_default="")
    external_reference: Mapped[str] = mapped_column(String(128), default="", server_default="")
    external_type: Mapped[str] = mapped_column(String(32), default="UNKNOWN", server_default="UNKNOWN")
    blocking_reason: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    data_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    result: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    input_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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


class WorkflowEvent(Base):
    """不可变业务事件主体；投递状态由 Outbox worker 独立维护。"""
    __tablename__ = "workflow_events"
    __table_args__ = (
        Index("uq_workflow_event_sequence", "run_id", "sequence", unique=True),
        Index("uq_workflow_event_key", "tenant_id", "idempotency_key", unique=True),
        Index("ix_workflow_event_delivery", "delivery_status", "next_attempt_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", name="fk_workflow_events_tenant_id_tenants"), index=True)
    workspace_id: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id", name="fk_workflow_events_run_id_workflow_runs"))
    step_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_steps.id", name="fk_workflow_events_step_id_workflow_steps"), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_workflow_events_actor_id_users"), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32), default="SYSTEM")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_version: Mapped[int] = mapped_column(Integer)
    mapping_version: Mapped[str] = mapped_column(String(64), default="")
    delivery_status: Mapped[str] = mapped_column(String(24), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_owner: Mapped[str] = mapped_column(String(64), default="")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consumer_receipts: Mapped[dict] = mapped_column(JSON, default=dict)


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


# ---------------------------------------------------------------- 经营画像（D63）

class BusinessProfile(Base):
    """经营画像（D63 服务端持久化，替代原型 02 的会话内/草稿方案）。

    一张表同时承载「个人偏好」与「Workspace 共享」两类字段，靠 ``user_id`` 是否为空区分：

      - ``user_id`` 非空  = 个人偏好行：承载 ``direction``（资源起点 A/B/C）、
        ``budget_amount`` / ``budget_currency``；
      - ``user_id`` 为空  = 空间共享行：承载 ``target_market``（目标市场）、``risk``（风险偏好），
        归属 (tenant_id, workspace_id)，写权限复用既有的 ``workspace:write`` 能力 key。

    同一个 (tenant, workspace) 内两类行共存：
      - 个人行按 (tenant_id, workspace_id, user_id) 唯一（``uq_business_profile_personal``）；
      - 共享行按 (tenant_id, workspace_id) 唯一，由部分唯一索引
        ``ix_business_profiles_shared``（WHERE user_id IS NULL）约束。

    ``completed`` / ``completed_at`` 是审计列；API 的「完成」判定由合并视图按"必填字段齐全"
    推导（见 routers/business_profiles.py 的 ``is_profile_complete``），落库时回填两行以保持一致。
    """

    __tablename__ = "business_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workspace_id", "user_id", name="uq_business_profile_personal"),
        # 部分唯一索引：同一 (tenant, workspace) 仅允许一份共享画像（user_id IS NULL）。
        Index(
            "ix_business_profiles_shared", "tenant_id", "workspace_id",
            unique=True, sqlite_where=text("user_id IS NULL")),
        Index("ix_business_profiles_tenant", "tenant_id"),
        Index("ix_business_profiles_workspace", "workspace_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", name="fk_business_profiles_tenant_id_tenants"), index=True)
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_business_profiles_user_id_users"), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    budget_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    target_market: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
