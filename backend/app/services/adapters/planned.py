"""已调研 / 待接入平台适配器

PlannedSalesAdapter 基类 + 5 个路线图平台 + Amazon（能力清单全空，不做假实现）。
"""
from urllib.parse import urlencode

from .base import BaseAdapter


class PlannedSalesAdapter(BaseAdapter):
    role = "sales"
    integration_status = "planned"
    limitations = ["已确认官方开放平台，授权与业务接口待实现"]


class AliExpressAdapter(PlannedSalesAdapter):
    platform, label = "aliexpress", "AliExpress"
    docs = "https://developer.alibaba.com/docs/doc.htm?articleId=120688&docType=1&treeId=727"
    markets, auth_model = ["GLOBAL"], "AliExpress Open Platform OAuth"


class TemuAdapter(PlannedSalesAdapter):
    platform, label = "temu", "Temu 跨境店"
    docs = "https://partner.temu.com/documentation?menu_code=38e79b35d2cb463d85619c1c786dd303"
    markets, auth_model = ["US", "EU", "GLOBAL"], "卖家后台手动授权"
    integration_status = "restricted"
    limitations = ["跨境卖家当前采用后台手动授权，站点使用不同 API Host"]


class ShopifyAdapter(PlannedSalesAdapter):
    platform, label = "shopify", "Shopify Markets 独立站"
    docs = "https://shopify.dev/docs/api/admin-graphql/latest"
    markets, auth_model = ["GLOBAL"], "Shopify App OAuth"
    limitations = ["独立站渠道，不属于第三方 marketplace；使用版本化 GraphQL Admin API"]


class MercadoLibreAdapter(PlannedSalesAdapter):
    platform, label = "mercadolibre", "Mercado Libre 拉美"
    docs = "https://developers.mercadolibre.com.ar/autenticacion-y-autorizacion"
    markets, auth_model = ["MX", "BR", "AR", "CL", "CO"], "OAuth 2.0 Authorization Code"


class SheinAdapter(PlannedSalesAdapter):
    platform, label = "shein", "SHEIN Marketplace"
    docs = "https://open.sheincorp.cn/zh"
    markets, auth_model = ["GLOBAL"], "应用审核后授权"
    integration_status = "restricted"
    limitations = ["需先完成开发者入驻和应用审核，再按获批解决方案接入"]


class AmazonAdapter(BaseAdapter):
    """Amazon SP-API：LWA(OAuth2)+SigV4 签名、按 marketplace 的 PCP 体系，
    接入门槛最高，能力清单当前为空（UI 自动禁用，不做假实现）。"""
    platform = "amazon"
    label = "Amazon SP-API"
    docs = "https://developer-docs.amazon.com/sp-api/"
    role = "sales"
    can_order_sync = False
    can_publish = False
    can_refresh = False
    integration_status = "planned"
    markets = ["US"]
    auth_model = "LWA OAuth 2.0 + AWS SigV4"
    limitations = ["需要 SP-API 应用审核、LWA 与 IAM/SigV4 配置"]

    def authorize_url(self) -> str:
        params = {"application_id": self.shop.app_key, "state": self.shop.id,
                  "version": "beta"}
        return (f"https://sellercentral.amazon.com/apps/authorize/consent?{urlencode(params)}")
