"""适配器注册表：平台名 → 适配器类，以及前端消费的平台元数据。"""
from .ali1688 import Ali1688Adapter
from .base import BaseAdapter
from .catmap import CategoryMappingRegistry
from .contract import PlatformError
from .ebay import EbayAdapter
from .lazada import LazadaAdapter
from .planned import (
    AliExpressAdapter,
    AmazonAdapter,
    MercadoLibreAdapter,
    SheinAdapter,
    ShopifyAdapter,
    TemuAdapter,
)
from .shopee import ShopeeAdapter
from .tiktok import TikTokAdapter
from .walmart import WalmartAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    a.platform: a for a in (
        Ali1688Adapter, TikTokAdapter, ShopeeAdapter, AmazonAdapter, EbayAdapter,
        WalmartAdapter, LazadaAdapter, AliExpressAdapter, TemuAdapter,
        ShopifyAdapter, MercadoLibreAdapter, SheinAdapter)
}


def get_adapter(db, shop) -> BaseAdapter:
    cls = ADAPTERS.get(shop.platform)
    if not cls:
        raise PlatformError(f"不支持的平台 {shop.platform}")
    return cls(db, shop)


def platform_meta() -> list[dict]:
    """平台元数据（能力清单），前端据此禁用不可用操作。"""
    out = []
    for name, cls in ADAPTERS.items():
        out.append({
            "platform": name, "label": cls.label, "role": cls.role,
            "docs": cls.docs,
            "can_order_sync": cls.can_order_sync,
            "can_publish": cls.can_publish,
            "can_refresh": cls.can_refresh,
            "can_listing_readiness": cls.can_listing_readiness,
            "publish_requires_category_mapping": cls.publish_requires_category_mapping,
            "category_mapping_hint": CategoryMappingRegistry.hint(name),
            "integration_status": cls.integration_status,
            "markets": cls.markets,
            "auth_model": cls.auth_model,
            "limitations": cls.limitations,
        })
    return out
