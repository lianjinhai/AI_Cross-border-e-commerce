"""类目映射：系统类目 → 平台类目。

各平台类目树格式不同（Shopee 纯 ID、TikTok 路径、Amazon PCP 代码），映射值存原样。
"""
from ...models import CategoryMapping


def category_mapping_for(db, tenant_id: int, platform: str, category: str) -> str:

    row = (db.query(CategoryMapping)
           .filter(CategoryMapping.tenant_id == tenant_id,
                   CategoryMapping.platform == platform,
                   CategoryMapping.system_category == category).first())
    return row.platform_category_id if row else ""


class CategoryMappingRegistry:
    """各平台类目树格式不同（Shopee 纯 ID、TikTok 路径、Amazon PCP 代码），映射值存原样。"""

    @staticmethod
    def hint(platform: str) -> str:
        return {
            "shopee": "Shopee 类目ID（seller center 或 get_categories 接口获取，如 100642）",
            "tiktok": "TikTok Shop 美国站 v2 叶子类目 ID（7 级类目树）",
            "amazon": "Amazon product_type 代码（PCP）",
            "1688": "1688 类目ID",
        }.get(platform, "平台类目ID")
