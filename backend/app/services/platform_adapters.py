"""平台适配器层：把每个电商平台的一切差异封装在各自的 Adapter 里。

设计要点（响应"平台不一致性"）：
1. BaseAdapter 定义统一契约：authorize_url / exchange_code / refresh /
   fetch_orders / publish_listing，以及 capabilities 能力清单与 role 角色。
2. 数据在适配器边界完成"规范化"：
   - TokenPair：各平台 token 响应字段不同（expires_in / expire_in / expire_time…）；
   - NormalizedOrder：金额币种、状态枚举（waitsellerdeliver vs UNPAID vs AWAITING_SHIPMENT）、
     单号字段（idOfStr vs order_sn）全部在适配器内转换成统一结构；
   - PublishResult：平台返回的 item_id 字段不同（item_id vs product_id vs sku）。
3. 发布前置校验：每个平台必填字段不同（Shopee 必须类目/品牌/物流模板，Amazon 需要
   PCP product_type……），适配器先声明 missing_publish_requirements()，系统缺什么就
   明确报什么，绝不盲目调用平台 API。
4. 签名差异全部内聚：1688 HMAC-SHA1(path+sorted)、Shopee base64(HMAC-SHA256(path|ts))、
   TikTok sha256(app_key+ts+token)。
"""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx

_TIMEOUT = 20.0
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def platform_environment(platform: str) -> str:
    """平台环境统一开关：sandbox/production，默认 sandbox 防止误写生产。"""
    value = os.getenv(f"ERP_{platform.upper()}_ENV", "sandbox").strip().lower()
    if value not in ("sandbox", "production"):
        raise PlatformError(f"ERP_{platform.upper()}_ENV 只能是 sandbox 或 production")
    return value


def platform_base_url(platform: str, sandbox: str, production: str) -> str:
    override = os.getenv(f"ERP_{platform.upper()}_BASE_URL", "").strip()
    return override.rstrip("/") or (sandbox if platform_environment(platform) == "sandbox" else production)


def request_with_retry(method: str, url: str, **kwargs):
    """只重试安全方法或带明确幂等键的请求；429/5xx 指数退避。"""
    headers = kwargs.get("headers") or {}
    safe = method.upper() in ("GET", "HEAD", "PUT", "DELETE") or bool(
        headers.get("Idempotency-Key") or headers.get("X-Request-ID"))
    attempts = 3 if safe else 1
    response = None
    for attempt in range(attempts):
        try:
            response = httpx.request(method, url, **kwargs)
        except httpx.TransportError:
            if not safe or attempt == attempts - 1:
                raise
            time.sleep(min(0.25 * (2 ** attempt), 2.0))
            continue
        if response.status_code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
            return response
        retry_after = response.headers.get("Retry-After")
        time.sleep(min(float(retry_after) if retry_after else 0.25 * (2 ** attempt), 2.0))
    return response


class PlatformError(Exception):
    pass


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str = ""
    expires_in: int = 86400
    raw: dict = field(default_factory=dict)


@dataclass
class NormalizedOrder:
    external_no: str
    amount: float          # 统一折算 USD
    qty: int = 1
    status: str = "paid"   # pending/paid/shipped/delivered/refunded
    currency: str = "USD"
    country: str = ""
    buyer_name: str = ""


@dataclass
class PublishResult:
    external_id: str
    url: str = ""
    raw: dict = field(default_factory=dict)


def _shop_role_default(platform: str) -> str:
    return "source" if platform == "1688" else "sales"


def redirect_uri_for(shop) -> str:
    """授权回调地址。本地默认与 shops.py 注册的回调路由一致；
    生产部署需公网回调时，用 ERP_PUBLIC_BASE_URL 环境变量覆盖主机部分。"""
    import os

    base = os.getenv("ERP_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/api/shops/callback/{shop.platform}/{shop.id}"


class BaseAdapter:
    """统一契约。子类只实现平台差异。"""
    platform = ""
    label = ""
    docs = ""
    role = "sales"
    # 能力清单：明确声明该平台支持什么，UI 按此禁用不可用操作
    can_order_sync = False
    can_publish = False
    can_refresh = False
    can_listing_readiness = False
    # 发布必需的外部资源（如类目映射）
    publish_requires_category_mapping = False
    publish_required_system_fields: list[str] = []
    integration_status = "planned"  # ready/partial/planned/restricted
    markets: list[str] = []
    auth_model = ""
    limitations: list[str] = []

    def __init__(self, db, shop):
        self.db = db
        self.shop = shop

    # ---- 通用守卫 ----
    def _ensure_authorized(self):
        s = self.shop
        if s.status != "authorized":
            raise PlatformError(f"店铺未授权（当前 {s.status}），请先完成 OAuth 授权")
        if s.token_expire_at and s.token_expire_at and s.token_expire_at.year and \
                s.token_expire_at.strftime("%Y%m%d%H%M%S") < time.strftime("%Y%m%d%H%M%S"):
            raise PlatformError("access_token 已过期，请刷新或重新授权")

    def _limiter(self):
        """平台级调用节流（规则包 rate_limit_per_sec），防频控封店。"""
        from .platform_rules import RateLimiter, get_active_rules

        rules = get_active_rules(self.db, self.platform)["rules"]
        return RateLimiter(rules.get("rate_limit_per_sec", 10))

    def _pre_publish_checks(self, listing, product) -> None:
        """发布三道关之一：平台规则包强制校验（违禁词/长度/禁售类目/图片要求）。"""
        from .platform_rules import validate_against_rules

        violations = validate_against_rules(self.db, self.platform, listing, product)
        if violations:
            raise PlatformError("平台规则校验未通过（为保护店铺拒绝发布）：" + "；".join(violations))

    # ---- 授权 ----
    def authorize_url(self) -> str:
        raise PlatformError(f"{self.label} 授权未实现")

    def exchange_code(self, code: str) -> TokenPair:
        raise PlatformError(f"{self.label} token 交换未实现")

    def refresh(self) -> TokenPair:
        raise PlatformError(f"{self.label} 不支持 token 刷新，请重新授权")

    # ---- 业务 ----
    def fetch_orders(self, days: int = 7) -> list[NormalizedOrder]:
        raise PlatformError(f"{self.label} 拉单协议待接入")

    def missing_publish_requirements(self, listing, product) -> list[str]:
        """发布前置校验：返回缺失项中文清单（空=可发布）。"""
        missing = []
        if self.publish_requires_category_mapping:
            if not product.category:
                missing.append("商品类目为空，无法映射平台类目")
            elif not category_mapping_for(self.db, self.shop.tenant_id,
                                          self.platform, product.category):
                missing.append(f"缺少「{product.category} → {self.label} 类目ID」映射，"
                               "请到店铺授权页维护类目映射")
        # 系统必填字段：由适配器声明字段名，逐项在 product.attrs 中校验
        attrs = product.attrs or {}
        for required in self.publish_required_system_fields:
            value = attrs.get(required)
            if required == "images":
                if not [u for u in (product.images or []) if str(u).startswith("http")]:
                    missing.append("缺少可公网访问的商品图片（images）")
            elif required == "stock":
                if int(attrs.get("onhand") or 0) <= 0:
                    missing.append("可售库存 onhand 必须大于 0")
            elif required == "price":
                if float(attrs.get("sale_price") or 0) <= 0:
                    missing.append("缺少有效销售价 sale_price")
            elif value in (None, "", [], {}):
                missing.append(f"缺少必填字段 {required}")
        if not (listing.keywords or []):
            missing.append("Listing 缺少关键词")
        return missing

    def publish_listing(self, listing, product, *, resume=None, checkpoint=None) -> PublishResult:
        raise PlatformError(f"{self.label} 上架协议待接入")

    def listing_readiness(self, listing, product) -> dict:
        raise PlatformError(f"{self.label} 尚未接入真实上架预检")

    def submission_status(self, submission_id: str) -> dict:
        raise PlatformError(f"{self.label} 不支持异步提交状态查询")


# ---------------------------------------------------------------- 类目映射

def category_mapping_for(db, tenant_id: int, platform: str, category: str) -> str:
    from ..models import CategoryMapping

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


# ---------------------------------------------------------------- 1688（货源平台）

class Ali1688Adapter(BaseAdapter):
    platform = "1688"
    label = "1688（阿里巴巴）"
    docs = "https://open.1688.com/api/apidocdetail.htm"
    role = "source"
    can_order_sync = True    # 代发/分销订单
    can_publish = False      # 1688 是采购平台，不支持销售上架
    can_refresh = True
    integration_status = "partial"
    markets = ["CN"]
    auth_model = "OAuth 2.0"

    # 授权页与 token 端点均按 open.1688.com 官方文档实现：
    # 授权页 auth.1688.com/oauth/authorize；token 为 POST form 到
    # gw.open.1688.com/openapi/oauth2/getToken/{appKey}，grant_type=authorization_code。
    def authorize_url(self) -> str:
        params = {"client_id": self.shop.app_key, "site": "1688",
                  "redirect_uri": redirect_uri_for(self.shop)}
        return f"https://auth.1688.com/oauth/authorize?{urlencode(params)}"

    def _token_call(self, grant: dict) -> TokenPair:
        url = f"https://gw.open.1688.com/openapi/oauth2/getToken/{self.shop.app_key}"
        try:
            resp = httpx.post(url, data=grant, timeout=_TIMEOUT,
                              headers={"User-Agent": _UA,
                                       "Content-Type": "application/x-www-form-urlencoded"})
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise PlatformError(f"1688 token 接口调用失败: {e}") from e
        if not data.get("access_token"):
            raise PlatformError(f"1688 未返回 access_token: {str(data)[:200]}")
        return TokenPair(access_token=data["access_token"],
                         refresh_token=data.get("refresh_token", ""),
                         expires_in=int(data.get("expires_in") or 36000), raw=data)

    def exchange_code(self, code: str) -> TokenPair:
        return self._token_call({
            "grant_type": "authorization_code",
            "client_id": self.shop.app_key, "client_secret": self.shop.app_secret,
            "redirect_uri": redirect_uri_for(self.shop),
            "code": code,
        })

    def refresh(self) -> TokenPair:
        if not self.shop.refresh_token:
            raise PlatformError("无 refresh_token，请重新授权")
        return self._token_call({
            "grant_type": "refresh_token",
            "client_id": self.shop.app_key, "client_secret": self.shop.app_secret,
            "refresh_token": self.shop.refresh_token,
        })

    def fetch_orders(self, days: int = 7) -> list[NormalizedOrder]:
        self._ensure_authorized()
        from .open_1688 import Api1688Error, call_api

        try:
            raw = call_api(self.db, "alibaba.trade.getSellerOrderList", {
                "webSite": "1688", "sellerLoginId": self.shop.shop_id or self.shop.app_key,
                "pageSize": "20", "page": "1",
            })
        except Api1688Error as e:
            raise PlatformError(f"1688 平台返回错误：{e}（请检查应用权限/Token）") from e
        out = []
        for t in (raw.get("result") or {}).get("result") or []:
            ext = str(t.get("idOfStr") or t.get("id") or "")
            if not ext:
                continue
            amount_cny = float((t.get("totalPaymentAmount") or {}).get("value") or 0)
            status_map = {"waitsellerdeliver": "paid", "waitsellerdelivergoods": "paid",
                          "signed": "delivered", "delivered": "delivered",
                          "refund": "refunded", "waitsellerreceivegoods": "shipped"}
            out.append(NormalizedOrder(
                external_no=ext,
                amount=round(amount_cny / 7.12, 2),   # 1688 人民币 -> 统一 USD
                qty=int(float((t.get("totalOrderQuantity") or {}).get("value") or 1)),
                status=status_map.get(str(t.get("currentStatus")).lower(), "paid"),
                buyer_name=str((t.get("buyer") or {}).get("loginId", ""))[:64]))
        return out


# ---------------------------------------------------------------- Shopee

class ShopeeAdapter(BaseAdapter):
    """签名与端点均按 open.shopee.com v2 官方文档实现：
    - Shop API：sign = HMAC-SHA256(partner_key, partner_id+path+timestamp+access_token+shop_id)
      输出 hex；partner_id/timestamp/access_token/shop_id/sign 均放 query，业务字段在 body。
    - Public API（token/get、refresh_token）：sign base 不含 access_token/shop_id。
    - 图片必须先经 /api/v2/media_space/upload_image 取 image_info，外链不可直接用；
      上架端点为 v2 /api/v2/product/add_item（post_item 是 v1 已废弃）。
    """
    platform = "shopee"
    label = "Shopee"
    docs = "https://open.shopee.com/documents/v2/v2.product.add_item"
    role = "sales"
    can_order_sync = True
    can_publish = True
    can_refresh = True       # /api/v2/auth/refresh_token（access_token 约 4 小时需刷新）
    can_listing_readiness = True
    publish_requires_category_mapping = True
    publish_required_system_fields = ["price", "stock", "images"]
    integration_status = "partial"
    markets = ["SG"]
    auth_model = "Shopee Open Platform v2 OAuth"

    _HOST = "https://openplatform.shopee.com"

    def _sign(self, base: str) -> str:
        return hmac.new(self.shop.app_secret.encode(), base.encode(),
                        hashlib.sha256).hexdigest()

    def _call(self, path: str, body: dict | None = None,
              api_type: str = "shop", extra_form=None, method: str = "POST",
              business_query: dict | None = None) -> dict:
        ts = int(time.time())
        if api_type == "shop":
            base = f"{self.shop.app_key}{path}{ts}{self.shop.access_token}{self.shop.shop_id}"
            query = {"partner_id": self.shop.app_key, "timestamp": ts,
                     "access_token": self.shop.access_token,
                     "shop_id": self.shop.shop_id, "sign": self._sign(base)}
        else:  # public：token 交换/刷新
            base = f"{self.shop.app_key}{path}{ts}"
            query = {"partner_id": self.shop.app_key, "timestamp": ts,
                     "sign": self._sign(base)}
        url = f"{self._HOST}{path}?{urlencode({**query, **(business_query or {})})}"
        try:
            if extra_form is not None:  # 图片 multipart
                resp = httpx.post(url, files=extra_form, timeout=_TIMEOUT)
            elif method.upper() == "GET":
                resp = httpx.get(url, timeout=_TIMEOUT)
            else:
                resp = httpx.post(url, json=body or {}, timeout=_TIMEOUT)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise PlatformError(f"Shopee 接口调用失败: {e}") from e
        data = resp.json()
        err = data.get("error") or data.get("msg")
        if err and str(err).lower() not in ("success", "none", ""):
            raise PlatformError(f"Shopee 返回错误 {data.get('error', '')}: {err}")
        return data.get("response", {})

    def authorize_url(self) -> str:
        params = {"client_id": self.shop.app_key,
                  "redirect_uri": redirect_uri_for(self.shop),
                  "path": "/api/v2/shop/auth_partner"}
        return f"https://open.shopee.com/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenPair:
        self._ensure_authorized_key()
        resp = self._call("/api/v2/auth/token/get",
                          {"code": code, "shop_id": int(self.shop.shop_id or 0)},
                          api_type="public")
        return TokenPair(access_token=resp.get("access_token", ""),
                         refresh_token=resp.get("refresh_token", ""),
                         expires_in=int(resp.get("expire_in") or 3600 * 4), raw=resp)

    def refresh(self) -> TokenPair:
        if not self.shop.refresh_token:
            raise PlatformError("无 refresh_token，请重新授权")
        resp = self._call("/api/v2/auth/refresh_token",
                          {"refresh_token": self.shop.refresh_token,
                           "shop_id": int(self.shop.shop_id or 0)},
                          api_type="public")
        return TokenPair(access_token=resp.get("access_token", ""),
                         refresh_token=resp.get("refresh_token", self.shop.refresh_token),
                         expires_in=int(resp.get("expire_in") or 3600 * 4), raw=resp)

    def _ensure_authorized_key(self):
        if not (self.shop.app_key and self.shop.app_secret):
            raise PlatformError("请先在店铺设置中填写 App Key / Partner Key")

    def fetch_orders(self, days: int = 7) -> list[NormalizedOrder]:
        self._ensure_authorized()
        ts = int(time.time())
        resp = self._call("/api/v2/order/get_order_list", method="GET", business_query={
            "time_range_field": "create_time", "time_from": ts - days * 86400,
            "time_to": ts, "page_size": 20,
        })
        out = []
        for t in resp.get("order_list") or []:
            if not t.get("order_sn"):
                continue
            status_map = {"UNPAID": "pending", "READY_TO_SHIP": "paid",
                          "PROCESSED": "shipped", "SHIPPED": "shipped",
                          "COMPLETED": "delivered", "IN_CANCEL": "refunded",
                          "CANCELLED": "refunded"}
            out.append(NormalizedOrder(
                external_no=str(t["order_sn"]),
                amount=round(float(t.get("total_amount") or 0), 2),
                status=status_map.get(str(t.get("order_status")), "paid"),
                country=str(t.get("region") or ""),
                buyer_name=str(t.get("buyer_username") or "")[:64]))
        return out

    def listing_readiness(self, listing, product) -> dict:
        """Shopee SG 上架只读预检：验证店铺、物流渠道及类目必填属性。"""
        self._ensure_authorized()
        blockers = []
        warnings = []
        if listing.platform != self.platform:
            blockers.append("Listing 平台与店铺平台不一致")
        category_id = category_mapping_for(
            self.db, self.shop.tenant_id, self.platform, product.category)
        if not category_id:
            blockers.append(f"缺少「{product.category} → Shopee SG 类目ID」映射")
        attrs = product.attrs or {}
        images = [url for url in (product.images or []) if str(url).startswith("https://")]
        if not images:
            blockers.append("至少需要 1 张 HTTPS 商品图片")
        if float(attrs.get("sale_price") or 0) <= 0:
            blockers.append("缺少有效销售价 sale_price")
        if int(attrs.get("onhand") or 0) <= 0:
            blockers.append("可售库存 onhand 必须大于 0")
        if float(attrs.get("weight_kg") or 0) <= 0:
            blockers.append("包装重量 weight_kg 必须大于 0")

        shop_info = self._call("/api/v2/shop/get_shop_info", method="GET")
        region = str(shop_info.get("region") or shop_info.get("region_code") or "").upper()
        if region and region != "SG":
            blockers.append(f"当前阶段仅验收 Shopee SG，实际授权站点为 {region}")
        logistics = self._call("/api/v2/logistics/get_channel_list", method="GET")
        enabled_channels = [row for row in (logistics.get("logistics_channel_list") or [])
                            if row.get("enabled") is not False]
        if not enabled_channels:
            blockers.append("店铺没有已启用的物流渠道")

        required_attributes = []
        if category_id:
            response = self._call(
                "/api/v2/product/get_attributes", method="GET",
                business_query={"category_id": int(category_id), "language": "en"})
            required_attributes = [
                row for row in (response.get("attribute_list") or [])
                if row.get("is_mandatory") is True
            ]
            supplied = attrs.get("shopee_attributes") or []
            supplied_ids = {
                str(row.get("attribute_id")) for row in supplied if isinstance(row, dict)
            }
            missing_names = [
                str(row.get("original_attribute_name") or row.get("display_attribute_name")
                    or row.get("attribute_id"))
                for row in required_attributes
                if str(row.get("attribute_id")) not in supplied_ids
            ]
            if missing_names:
                blockers.append("缺少 Shopee 类目必填属性：" + "、".join(missing_names))

        if len(images) < 3:
            warnings.append("建议提供至少 3 张商品图片以改善转化")
        return {
            "ready": not blockers,
            "mode": "shopee_sg_item",
            "market": "SG",
            "shop_region": region or "unknown",
            "category_id": category_id,
            "enabled_logistics": [row.get("logistics_channel_id") for row in enabled_channels],
            "required_attribute_count": len(required_attributes),
            "blockers": blockers,
            "warnings": warnings,
            "next_action": ("可以进入受控发布验收" if not blockers
                            else "请先补齐阻断项，系统不会调用发布接口"),
        }

    def publish_listing(self, listing, product, *, resume=None, checkpoint=None) -> PublishResult:
        """v2 上架两步：media_space 上传图片 -> product/add_item（字段结构以
        open.shopee.com 文档为准；类目属性 attribute_list 需按 get_attributes 补全，
        平台的精确报错会原样透传给用户）。"""
        self._ensure_authorized()
        self._pre_publish_checks(listing, product)
        missing = self.missing_publish_requirements(listing, product)
        if missing:
            raise PlatformError("Shopee 上架前置校验未通过：" + "；".join(missing))
        attrs = product.attrs or {}
        category_id = category_mapping_for(self.db, self.shop.tenant_id,
                                           self.platform, product.category)
        images = [i for i in (product.images or []) if i.startswith("http")]
        if not images:
            raise PlatformError("Shopee 要求至少 1 张可公网访问的商品图片")
        limiter = self._limiter()
        # 1) 上传主图到 Shopee 媒体空间（外链图平台不接收）
        limiter.wait()
        try:
            img_bytes = httpx.get(images[0], timeout=_TIMEOUT, follow_redirects=True,
                                  headers={"User-Agent": _UA}).content
        except httpx.HTTPError as e:
            raise PlatformError(f"下载商品图片失败（media_space 需上传原图）: {e}") from e
        image_info = self._call("/api/v2/media_space/upload_image",
                                extra_form={"image": ("item.jpg", img_bytes, "image/jpeg")})
        if not (image_info.get("image_info") or {}).get("image_id"):
            raise PlatformError(f"Shopee 图片上传失败: {str(image_info)[:200]}")
        # 2) add_item
        limiter.wait()
        resp = self._call("/api/v2/product/add_item", {
            "category_id": int(category_id),
            "item_name": listing.title[:255],
            "description": (listing.description or "")[:3000],
            "item_sku": product.sku,
            "image_info": image_info.get("image_info"),
            "logistics_information": {"weight": round(float(attrs.get("weight_kg") or 0.3), 3)},
            "model_list": [{"model_sku": product.sku,
                            "original_price": round(float(attrs.get("sale_price") or 19.99), 2),
                            "stock": int(attrs.get("onhand") or 1)}],
        })
        return PublishResult(external_id=str(resp.get("item_id") or ""), raw=resp)


# ---------------------------------------------------------------- TikTok Shop

class TikTokAdapter(BaseAdapter):
    """TikTok Shop Open API（202309+ 风格）。

    ``shop.shop_id`` 对 TikTok 保存官方 ``shop_cipher``，不是 Seller Center
    展示名称。业务请求使用版本化路径、``x-tts-access-token`` 请求头，并按
    官方规则对 path、排序后的 query 和 body 做 HMAC-SHA256 签名。
    """
    platform = "tiktok"
    label = "TikTok Shop"
    docs = "https://partner.tiktokshop.com/docv2/page/6507ead7b99d5302be949ba9"
    role = "sales"
    can_order_sync = True
    can_publish = True
    can_refresh = True
    can_listing_readiness = True
    publish_requires_category_mapping = True
    publish_required_system_fields = ["price", "stock", "images"]
    integration_status = "protocol_ready_unverified"
    markets = ["US"]
    auth_model = "TikTok Shop OAuth 2.0"
    limitations = ["官方协议已实现，等待 Development Shop/真实店铺验收"]
    _HOST = "https://open-api.tiktokglobalshop.com"

    @property
    def api_host(self) -> str:
        return platform_base_url("tiktok", "https://open-api-sandbox.tiktokglobalshop.com",
                                 self._HOST)

    @staticmethod
    def _expiry_seconds(value, default: int = 86400) -> int:
        """Token API 历史响应可能给剩余秒数，也可能给 Unix 到期时间。"""
        try:
            expires = int(value)
        except (TypeError, ValueError):
            return default
        now = int(time.time())
        return max(1, expires - now) if expires > now else max(1, expires)

    def _sign(self, path: str, query: dict, body_json: str = "") -> str:
        """生成 202309+ API 签名；sign/access_token 不参与 query 拼接。"""
        pairs = "".join(
            f"{key}{query[key]}" for key in sorted(query)
            if key not in ("sign", "access_token")
        )
        payload = f"{self.shop.app_secret}{path}{pairs}{body_json}{self.shop.app_secret}"
        return hmac.new(self.shop.app_secret.encode(), payload.encode(),
                        hashlib.sha256).hexdigest()

    def _call(self, method: str, path: str, *, query: dict | None = None,
              body: dict | None = None, access_token: str | None = None) -> dict:
        ts = int(time.time())
        params = {"app_key": self.shop.app_key, "timestamp": ts, **(query or {})}
        body_json = (json.dumps(body, ensure_ascii=False, separators=(",", ":"))
                     if body is not None else "")
        params["sign"] = self._sign(path, params, body_json)
        headers = {"Content-Type": "application/json", "User-Agent": _UA,
                   "x-tts-access-token": access_token or self.shop.access_token}
        try:
            resp = request_with_retry(method, f"{self.api_host}{path}", params=params,
                                 content=body_json or None, headers=headers,
                                 timeout=_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PlatformError(f"TikTok Shop 接口调用失败: {e}") from e
        if str(payload.get("code", "0")) not in ("0", "success"):
            raise PlatformError(
                f"TikTok Shop 返回错误 {payload.get('code')}: "
                f"{payload.get('message') or payload.get('msg') or '未知错误'}")
        return payload.get("data") or {}

    def _upload_image(self, url: str) -> dict:
        try:
            image = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True,
                              headers={"User-Agent": _UA})
            image.raise_for_status()
        except httpx.HTTPError as e:
            raise PlatformError(f"下载 TikTok 商品图片失败: {e}") from e
        path = "/product/202309/images/upload"
        query = {"app_key": self.shop.app_key, "timestamp": int(time.time()),
                 "shop_cipher": self.shop.shop_id, "use_case": "MAIN_IMAGE"}
        query["sign"] = self._sign(path, query)
        try:
            response = httpx.post(f"{self.api_host}{path}", params=query,
                                  headers={"x-tts-access-token": self.shop.access_token},
                                  files={"data": ("product.jpg", image.content, "image/jpeg")},
                                  timeout=_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PlatformError(f"TikTok 图片上传失败: {e}") from e
        if str(payload.get("code", "0")) not in ("0", "success"):
            raise PlatformError(f"TikTok 图片上传错误: {payload.get('message') or payload}")
        return payload.get("data") or {}

    def publish_listing(self, listing, product, *, resume=None, checkpoint=None) -> PublishResult:
        readiness = self.listing_readiness(listing, product)
        if not readiness["ready"]:
            raise PlatformError("TikTok Global Product 前置校验未通过：" +
                                "；".join(readiness["blockers"]))
        attrs = product.attrs or {}
        resume = resume or {}
        image_uris = resume.get("image_uris") or []
        if not image_uris:
            for url in (product.images or [])[:9]:
                uploaded = self._upload_image(url)
                uri = uploaded.get("uri") or uploaded.get("url") or uploaded.get("image_uri")
                if not uri:
                    raise PlatformError(f"TikTok 图片上传未返回 URI: {str(uploaded)[:200]}")
                image_uris.append({"uri": uri})
            if checkpoint: checkpoint({"image_uris": image_uris})
        sku = product.sku or f"ERP-{product.id}"
        created = ({"global_product_id": resume["global_product_id"]}
                   if resume.get("global_product_id") else self._call("POST", "/product/202309/global_products",
            query={"shop_cipher": self.shop.shop_id}, body={
                "title": listing.title[:255], "description": listing.description or "",
                "category_id": readiness["category_id"], "category_version": "v2",
                "main_images": image_uris,
                "product_attributes": attrs.get("tiktok_product_attributes") or [],
                "skus": [{"seller_sku": sku,
                          "sales_attributes": attrs.get("tiktok_sales_attributes") or [],
                          "inventory": [{"quantity": int(attrs["onhand"])}],
                          "price": {"amount": str(attrs["sale_price"]), "currency": "USD"}}],
                "package_weight": {"value": str(attrs["weight_kg"]), "unit": "KILOGRAM"},
                "package_dimensions": {"length": str(attrs["length_cm"]),
                                       "width": str(attrs["width_cm"]),
                                       "height": str(attrs["height_cm"]), "unit": "CENTIMETER"}}))
        global_id = str(created.get("global_product_id") or created.get("id") or "")
        if not global_id:
            raise PlatformError(f"TikTok 创建 Global Product 未返回 ID: {str(created)[:200]}")
        if checkpoint: checkpoint({"global_product_id": global_id})
        published = self._call("POST",
            f"/product/202309/global_products/{global_id}/publish",
            query={"shop_cipher": self.shop.shop_id},
            body={"target_shops": [{"shop_cipher": self.shop.shop_id}]})
        return PublishResult(external_id=global_id, raw={
            "environment": platform_environment("tiktok"), "global_product": created,
            "publish": published, "verification": "awaiting_real_shop_acceptance"})

    def authorize_url(self) -> str:
        params = {"app_key": self.shop.app_key, "state": self.shop.id,
                  "redirect_uri": redirect_uri_for(self.shop)}
        return f"https://auth.tiktok-shops.com/oauth/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> TokenPair:
        if not (self.shop.app_key and self.shop.app_secret):
            raise PlatformError("请先填写 App Key / App Secret")
        try:
            resp = httpx.post("https://auth.tiktok-shops.com/api/v2/token/get",
                              json={"app_key": self.shop.app_key,
                                    "app_secret": self.shop.app_secret,
                                    "auth_code": code, "grant_type": "authorized_code"},
                              timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except httpx.HTTPError as e:
            raise PlatformError(f"TikTok token 接口调用失败: {e}") from e
        if not data.get("access_token"):
            raise PlatformError(f"TikTok 未返回 access_token: {str(data)[:200]}")
        token = TokenPair(access_token=data["access_token"],
                          refresh_token=data.get("refresh_token", ""),
                          expires_in=self._expiry_seconds(data.get("access_token_expire_in")),
                          raw=data)
        shops = self._call("GET", "/authorization/202309/shops",
                           access_token=token.access_token).get("shops") or []
        us_shops = [s for s in shops if str(s.get("region", "")).upper() == "US"]
        selected = (us_shops or shops)[0] if (us_shops or shops) else {}
        token.raw["shop_cipher"] = selected.get("cipher") or ""
        token.raw["shop_region"] = selected.get("region") or ""
        if not token.raw["shop_cipher"]:
            raise PlatformError("授权成功但未取得 TikTok Shop shop_cipher，请确认应用拥有 seller.authorization.info 权限")
        if token.raw["shop_region"] and str(token.raw["shop_region"]).upper() != "US":
            raise PlatformError("当前阶段仅支持 TikTok Shop 美国站，请授权美国站店铺")
        return token

    def refresh(self) -> TokenPair:
        if not self.shop.refresh_token:
            raise PlatformError("无 refresh_token，请重新授权")
        try:
            resp = httpx.post("https://auth.tiktok-shops.com/api/v2/token/refresh",
                              json={"app_key": self.shop.app_key,
                                    "app_secret": self.shop.app_secret,
                                    "refresh_token": self.shop.refresh_token,
                                    "grant_type": "refresh_token"},
                              timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except httpx.HTTPError as e:
            raise PlatformError(f"TikTok 刷新失败: {e}") from e
        if not data.get("access_token"):
            raise PlatformError(f"TikTok 刷新未返回 access_token: {str(data)[:200]}")
        return TokenPair(access_token=data["access_token"],
                         refresh_token=data.get("refresh_token", self.shop.refresh_token),
                         expires_in=self._expiry_seconds(data.get("access_token_expire_in")),
                         raw=data)

    def fetch_orders(self, days: int = 7) -> list[NormalizedOrder]:
        self._ensure_authorized()
        if not self.shop.shop_id:
            raise PlatformError("缺少 TikTok Shop shop_cipher，请重新授权美国站店铺")
        path = "/order/202309/orders/search"
        out = []
        status_map = {"UNPAID": "pending", "AWAITING_SHIPMENT": "paid",
                      "AWAITING_COLLECTION": "paid", "PARTIALLY_SHIPPING": "shipped",
                      "IN_TRANSIT": "shipped", "SHIPPED": "shipped",
                      "DELIVERED": "delivered", "COMPLETED": "delivered",
                      "CANCELLED": "refunded"}
        cursor = ""
        for _ in range(100):
            query = {"shop_cipher": self.shop.shop_id, "page_size": 100}
            if cursor: query["page_token"] = cursor
            data = self._call("POST", path, query=query,
                              body={"create_time_ge": int(time.time()) - days * 86400})
            for t in data.get("orders") or data.get("order_list") or []:
                if t.get("id"):
                    payment = t.get("payment") or {}; lines = t.get("line_items") or []
                    out.append(NormalizedOrder(str(t["id"]), round(float(payment.get("total_amount") or 0), 2),
                        sum(int(i.get("quantity") or 1) for i in lines) or 1,
                        status_map.get(str(t.get("status") or t.get("order_status")), "paid"),
                        str(payment.get("currency") or "USD"), "US",
                        str((t.get("recipient_address") or {}).get("name") or "")[:64]))
            next_cursor = str(data.get("next_page_token") or data.get("next_cursor") or "")
            if not next_cursor or next_cursor == cursor: break
            cursor = next_cursor
        return out

    def listing_readiness(self, listing, product) -> dict:
        """跨境 Global Product 上架前的只读预检，不创建或修改平台商品。"""
        self._ensure_authorized()
        category_id = category_mapping_for(
            self.db, self.shop.tenant_id, self.platform, product.category)
        attrs = product.attrs or {}
        blockers = []
        warnings = []
        if listing.platform != self.platform:
            blockers.append("Listing 平台与店铺平台不一致")
        if listing.language.lower() not in ("en", "en-us"):
            blockers.append("TikTok Shop 美国站 Listing 必须使用英文（en-US）")
        if not category_id:
            blockers.append(f"缺少「{product.category} → TikTok Shop 美国站 v2 叶子类目」映射")
        images = [url for url in (product.images or []) if str(url).startswith("https://")]
        if not images:
            blockers.append("至少需要 1 张 HTTPS 商品图片，发布时必须上传到 TikTok Shop 图片空间")
        elif len(images) < 5:
            warnings.append("TikTok Shop 建议主图至少 5 张，当前图片数量不足 5 张")
        required_values = {
            "sale_price": "缺少美国站销售价 sale_price（USD）",
            "onhand": "缺少可售库存 onhand",
            "weight_kg": "缺少包装后重量 weight_kg",
            "length_cm": "跨境商品缺少包装长度 length_cm",
            "width_cm": "跨境商品缺少包装宽度 width_cm",
            "height_cm": "跨境商品缺少包装高度 height_cm",
        }
        for key, message in required_values.items():
            if attrs.get(key) is None or attrs.get(key) == "":
                blockers.append(message)
        if not attrs.get("tiktok_product_attributes"):
            blockers.append("缺少 TikTok 类目必填属性 tiktok_product_attributes")

        rules = {}
        if category_id:
            rules = self._call(
                "GET", f"/product/202309/categories/{category_id}/global_rules",
                query={"category_version": "v2", "locale": "en-US"})
            required_certifications = [
                item for item in (rules.get("product_certifications") or [])
                if item.get("is_required")
            ]
            if required_certifications and not attrs.get("tiktok_certifications"):
                names = "、".join(str(i.get("name") or i.get("id"))
                                  for i in required_certifications)
                blockers.append(f"该类目要求商品认证：{names}")
            size_chart = rules.get("size_chart") or {}
            if size_chart.get("is_required") and not attrs.get("tiktok_size_chart"):
                blockers.append("该类目要求 TikTok 尺码表")

        return {
            "ready": not blockers,
            "mode": "cross_border_global_product",
            "market": "US",
            "category_version": "v2",
            "category_id": category_id,
            "blockers": blockers,
            "warnings": warnings,
            "required_scopes": [
                "seller.global_product.category.info",
                "seller.global_product.write",
                "seller.product.basic",
            ],
            "next_action": ("可以进入 Global Product 创建与美国站发布阶段"
                            if not blockers else "请先补齐阻断项，系统不会调用发布接口"),
        }


# ---------------------------------------------------------------- eBay

class EbayAdapter(BaseAdapter):
    """eBay Sell Fulfillment API：User OAuth + 订单同步。"""
    platform = "ebay"
    label = "eBay 美国站"
    docs = "https://developer.ebay.com/api-docs/sell/fulfillment/overview.html"
    role = "sales"
    can_order_sync = True
    can_publish = True
    can_refresh = True
    integration_status = "protocol_ready_unverified"
    markets = ["EBAY_US"]
    auth_model = "OAuth 2.0 Authorization Code"
    limitations = ["shop_id 配置项需填写 eBay RuName", "官方协议已实现，等待 Sandbox 验收"]
    _SCOPE = ("https://api.ebay.com/oauth/api_scope/sell.fulfillment "
              "https://api.ebay.com/oauth/api_scope/sell.inventory")
    _API = "https://api.ebay.com"

    @property
    def api_host(self) -> str:
        return platform_base_url("ebay", "https://api.sandbox.ebay.com", self._API)

    @property
    def auth_host(self) -> str:
        return ("https://auth.sandbox.ebay.com" if platform_environment("ebay") == "sandbox"
                else "https://auth.ebay.com")

    def _ensure_keys(self):
        if not (self.shop.app_key and self.shop.app_secret and self.shop.shop_id):
            raise PlatformError("eBay 需要 Client ID、Client Secret 与 RuName（填在店铺 ID）")

    def authorize_url(self) -> str:
        self._ensure_keys()
        return f"{self.auth_host}/oauth2/authorize?" + urlencode({
            "client_id": self.shop.app_key,
            "redirect_uri": self.shop.shop_id,
            "response_type": "code",
            "scope": self._SCOPE,
            "state": str(self.shop.id),
        })

    def _token_call(self, form: dict) -> TokenPair:
        self._ensure_keys()
        basic = base64.b64encode(
            f"{self.shop.app_key}:{self.shop.app_secret}".encode()).decode()
        try:
            resp = httpx.post(
                f"{self.api_host}/identity/v1/oauth2/token",
                data=form,
                headers={"Authorization": f"Basic {basic}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PlatformError(f"eBay token 接口调用失败: {e}") from e
        if not data.get("access_token"):
            raise PlatformError(f"eBay 未返回 access_token: {str(data)[:200]}")
        return TokenPair(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", self.shop.refresh_token or ""),
            expires_in=int(data.get("expires_in") or 7200), raw=data)

    def exchange_code(self, code: str) -> TokenPair:
        return self._token_call({
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": self.shop.shop_id,
        })

    def refresh(self) -> TokenPair:
        if not self.shop.refresh_token:
            raise PlatformError("无 eBay refresh_token，请重新授权")
        return self._token_call({
            "grant_type": "refresh_token",
            "refresh_token": self.shop.refresh_token,
            "scope": self._SCOPE,
        })

    @staticmethod
    def _normalize_order(order: dict) -> NormalizedOrder | None:
        if not order.get("orderId"):
            return None
        summary = order.get("pricingSummary") or {}
        total = summary.get("total") or {}
        items = order.get("lineItems") or []
        fulfillment = str(order.get("orderFulfillmentStatus") or "")
        payment = str(order.get("orderPaymentStatus") or "")
        if payment not in ("PAID", "FULLY_REFUNDED", "PARTIALLY_REFUNDED"):
            status = "pending"
        elif payment == "FULLY_REFUNDED":
            status = "refunded"
        elif fulfillment == "FULFILLED":
            status = "shipped"
        else:
            status = "paid"
        country = ""
        instructions = order.get("fulfillmentStartInstructions") or []
        if instructions:
            address = ((instructions[0].get("shippingStep") or {})
                       .get("shipTo", {}).get("contactAddress", {}))
            country = str(address.get("countryCode") or "")
        return NormalizedOrder(
            external_no=str(order["orderId"]),
            amount=round(float(total.get("value") or 0), 2),
            qty=sum(int(item.get("quantity") or 1) for item in items) or 1,
            status=status,
            currency=str(total.get("currency") or "USD"),
            country=country,
            buyer_name=str((order.get("buyer") or {}).get("username") or "")[:64],
        )

    def fetch_orders(self, days: int = 7) -> list[NormalizedOrder]:
        self._ensure_authorized()
        start = time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                              time.gmtime(time.time() - days * 86400))
        end = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        out=[]; offset=0
        for _ in range(100):
            try:
                resp = request_with_retry("GET", f"{self.api_host}/sell/fulfillment/v1/order",
                    params={"filter": f"creationdate:[{start}..{end}]", "limit": 200, "offset": offset},
                    headers={"Authorization": f"Bearer {self.shop.access_token}", "Accept": "application/json"}, timeout=_TIMEOUT)
                resp.raise_for_status(); data=resp.json()
            except (httpx.HTTPError, ValueError) as e: raise PlatformError(f"eBay 拉单失败: {e}") from e
            rows=data.get("orders") or []
            out.extend(n for raw in rows if (n := self._normalize_order(raw)) is not None)
            offset += len(rows)
            if not rows or offset >= int(data.get("total") or offset): break
        return out

    def _api_call(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.shop.access_token}",
                   "Content-Type": "application/json", "Accept": "application/json",
                   "Content-Language": "en-US", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
        try:
            response = request_with_retry(method, f"{self.api_host}{path}", json=body,
                                     headers=headers, timeout=_TIMEOUT)
            response.raise_for_status()
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as e:
            detail = getattr(getattr(e, "response", None), "text", "")
            raise PlatformError(f"eBay Inventory API 失败: {e} {detail[:300]}") from e

    def publish_listing(self, listing, product, *, resume=None, checkpoint=None) -> PublishResult:
        self._ensure_authorized()
        self._pre_publish_checks(listing, product)
        attrs = product.attrs or {}
        required = {"ebay_category_id": "eBay 类目ID", "ebay_location_key": "库存地点",
                    "ebay_fulfillment_policy_id": "履约策略", "ebay_payment_policy_id": "付款策略",
                    "ebay_return_policy_id": "退货策略", "sale_price": "销售价", "onhand": "库存"}
        missing = [label for key, label in required.items() if not attrs.get(key)]
        if missing:
            raise PlatformError("eBay 发布前置校验未通过，缺少：" + "、".join(missing))
        sku = product.sku or f"ERP-{product.id}"
        from urllib.parse import quote
        self._api_call("PUT", f"/sell/inventory/v1/inventory_item/{quote(sku, safe='')}", {
            "availability": {"shipToLocationAvailability": {"quantity": int(attrs["onhand"])}},
            "condition": attrs.get("ebay_condition", "NEW"),
            "product": {"title": listing.title[:80], "description": listing.description or "",
                        "imageUrls": list(product.images or []), "aspects": attrs.get("ebay_aspects") or {}}})
        resume = resume or {}
        offer = ({"offerId": resume["offer_id"]} if resume.get("offer_id") else self._api_call("POST", "/sell/inventory/v1/offer", {
            "sku": sku, "marketplaceId": "EBAY_US", "format": "FIXED_PRICE",
            "availableQuantity": int(attrs["onhand"]), "categoryId": str(attrs["ebay_category_id"]),
            "merchantLocationKey": attrs["ebay_location_key"],
            "listingDescription": listing.description or "",
            "listingPolicies": {"fulfillmentPolicyId": attrs["ebay_fulfillment_policy_id"],
                                "paymentPolicyId": attrs["ebay_payment_policy_id"],
                                "returnPolicyId": attrs["ebay_return_policy_id"]},
            "pricingSummary": {"price": {"value": str(attrs["sale_price"]), "currency": "USD"}}}))
        offer_id = str(offer.get("offerId") or "")
        if not offer_id:
            raise PlatformError(f"eBay 创建 Offer 未返回 offerId: {str(offer)[:200]}")
        if checkpoint: checkpoint({"offer_id": offer_id})
        published = self._api_call("POST", f"/sell/inventory/v1/offer/{offer_id}/publish")
        return PublishResult(external_id=str(published.get("listingId") or offer_id), raw={
            "environment": platform_environment("ebay"), "offer_id": offer_id,
            "publish": published, "verification": "awaiting_real_shop_acceptance"})


# ---------------------------------------------------------------- 已调研、待分阶段接入的平台

class PlannedSalesAdapter(BaseAdapter):
    role = "sales"
    integration_status = "planned"
    limitations = ["已确认官方开放平台，授权与业务接口待实现"]


class WalmartAdapter(BaseAdapter):
    platform, label = "walmart", "Walmart 美国站"
    docs = "https://developer.walmart.com/us-marketplace/docs/introduction-to-marketplace-apis"
    markets, auth_model = ["US"], "OAuth 2.0（Solution Provider）"
    role = "sales"
    can_order_sync = True
    can_publish = True
    can_refresh = True
    integration_status = "protocol_ready_unverified"
    limitations = ["官方协议已实现，异步 Feed 必须继续查询商品级结果；等待 Sandbox 验收"]

    @property
    def api_host(self) -> str:
        return platform_base_url("walmart", "https://sandbox.walmartapis.com",
                                 "https://marketplace.walmartapis.com")

    def authorize_url(self) -> str:
        return "https://login.account.wal-mart.com/authorize?" + urlencode({
            "responseType": "code", "clientId": self.shop.app_key,
            "redirectUri": redirect_uri_for(self.shop), "clientType": "seller",
            "nonce": uuid.uuid4().hex, "state": str(self.shop.id)})

    def _token(self, form: dict) -> TokenPair:
        basic = base64.b64encode(f"{self.shop.app_key}:{self.shop.app_secret}".encode()).decode()
        try:
            response = httpx.post(f"{self.api_host}/v3/token", data=form,
                headers={"Authorization": f"Basic {basic}", "Accept": "application/json",
                         "Content-Type": "application/x-www-form-urlencoded",
                         "WM_QOS.CORRELATION_ID": str(uuid.uuid4())}, timeout=_TIMEOUT)
            response.raise_for_status(); data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PlatformError(f"Walmart Token API 失败: {e}") from e
        return TokenPair(data.get("access_token", ""), data.get("refresh_token", ""),
                         int(data.get("expires_in") or 900), data)

    def exchange_code(self, code: str) -> TokenPair:
        return self._token({"grant_type": "authorization_code", "code": code,
                            "redirect_uri": redirect_uri_for(self.shop)})

    def refresh(self) -> TokenPair:
        return self._token({"grant_type": "refresh_token", "refresh_token": self.shop.refresh_token})

    def _call(self, method: str, path: str, *, params=None, body=None, files=None) -> dict:
        headers = {"WM_SEC.ACCESS_TOKEN": self.shop.access_token,
                   "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
                   "WM_SVC.NAME": "Walmart Marketplace", "WM_MARKET": "us",
                   "Accept": "application/json"}
        try:
            response = request_with_retry(method, f"{self.api_host}{path}", params=params,
                                     json=None if files else body, files=files,
                                     headers=headers, timeout=_TIMEOUT)
            response.raise_for_status(); return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as e:
            detail = getattr(getattr(e, "response", None), "text", "")
            raise PlatformError(f"Walmart API 失败: {e} {detail[:300]}") from e

    def fetch_orders(self, days: int = 7) -> list[NormalizedOrder]:
        self._ensure_authorized(); out=[]; params={"limit": 200}
        for _ in range(100):
            data=self._call("GET", "/v3/orders", params=params)
            rows=(((data.get("list") or {}).get("elements") or {}).get("order") or [])
            for order in rows:
                lines=((order.get("orderLines") or {}).get("orderLine") or []); amount=qty=0
                for line in lines:
                    qty += int(float((line.get("orderLineQuantity") or {}).get("amount") or 1))
                    amount += sum(float((c.get("chargeAmount") or {}).get("amount") or 0) for c in ((line.get("charges") or {}).get("charge") or []) if c.get("chargeType")=="PRODUCT")
                status=str((((lines[0].get("orderLineStatuses") or {}).get("orderLineStatus") or [{}])[0]).get("status") or "Created") if lines else "Created"
                out.append(NormalizedOrder(str(order.get("purchaseOrderId")), round(amount,2), qty or 1,
                    {"Created":"paid","Acknowledged":"paid","Shipped":"shipped","Delivered":"delivered","Cancelled":"refunded"}.get(status,"paid"), "USD","US",str(((order.get("shippingInfo") or {}).get("postalAddress") or {}).get("name") or "")[:64]))
            cursor=((data.get("list") or {}).get("meta") or {}).get("nextCursor")
            if not cursor: break
            from urllib.parse import parse_qsl
            params=dict(parse_qsl(str(cursor).lstrip("?")))
        return out

    def publish_listing(self, listing, product, *, resume=None, checkpoint=None) -> PublishResult:
        self._ensure_authorized(); attrs = product.attrs or {}
        payload = attrs.get("walmart_mp_item")
        if not isinstance(payload, dict):
            raise PlatformError("Walmart Full Item Setup 需要 attrs.walmart_mp_item 官方 MP_ITEM 5.x 结构")
        resume = resume or {}
        if resume.get("feed_id"):
            return PublishResult(resume["feed_id"], raw={"feed_id": resume["feed_id"],
                "status": "submitted", "idempotent_replay": True})
        raw = json.dumps(payload, ensure_ascii=False).encode()
        result = self._call("POST", "/v3/feeds", params={"feedType": "MP_ITEM"},
                            files={"file": ("mp_item.json", raw, "application/json")})
        feed_id = str(result.get("feedId") or result.get("feed_id") or "")
        if not feed_id: raise PlatformError(f"Walmart 未返回 feedId: {str(result)[:200]}")
        if checkpoint: checkpoint({"feed_id": feed_id})
        return PublishResult(feed_id, raw={"feed_id": feed_id, "status": "submitted",
            "verification": "awaiting_real_shop_acceptance", "note": "必须继续查询 Feed 及商品级结果"})

    def submission_status(self, submission_id: str) -> dict:
        self._ensure_authorized()
        return self._call("GET", "/v3/feeds", params={"feedId": submission_id,
                                                       "includeDetails": "true", "limit": 50})


class LazadaAdapter(BaseAdapter):
    platform, label = "lazada", "Lazada 东南亚"
    docs = "https://open.lazada.com/apps/doc/doc?docId=108260&nodeId=10533"
    markets, auth_model = ["SG", "MY", "TH", "VN", "ID", "PH"], "OAuth 2.0"
    role = "sales"
    can_order_sync = True
    can_publish = True
    can_refresh = True
    integration_status = "protocol_ready_unverified"
    limitations = ["官方协议已实现，需按站点类目 Schema 提供 lazada_product XML 字段并待实店验收"]

    @property
    def api_host(self) -> str:
        market = str(self.shop.shop_id or "SG").upper()
        production = {"SG": "https://api.lazada.sg/rest", "MY": "https://api.lazada.com.my/rest",
                      "TH": "https://api.lazada.co.th/rest", "VN": "https://api.lazada.vn/rest",
                      "ID": "https://api.lazada.co.id/rest", "PH": "https://api.lazada.com.ph/rest"}.get(market, "https://api.lazada.sg/rest")
        return platform_base_url("lazada", "https://api-sandbox.lazada.com/rest", production)

    def _signed(self, path: str, params: dict) -> dict:
        merged = {"app_key": self.shop.app_key, "timestamp": str(int(time.time() * 1000)),
                  "sign_method": "sha256", **params}
        source = path + "".join(f"{k}{merged[k]}" for k in sorted(merged))
        merged["sign"] = hmac.new(self.shop.app_secret.encode(), source.encode(), hashlib.sha256).hexdigest().upper()
        return merged

    def authorize_url(self) -> str:
        return "https://auth.lazada.com/oauth/authorize?" + urlencode({
            "response_type": "code", "force_auth": "true", "redirect_uri": redirect_uri_for(self.shop),
            "client_id": self.shop.app_key, "state": str(self.shop.id)})

    def _call(self, method: str, path: str, params: dict) -> dict:
        signed = self._signed(path, params)
        try:
            response = request_with_retry(method, self.api_host + path, params=signed if method == "GET" else None,
                                     data=signed if method != "GET" else None, timeout=_TIMEOUT)
            response.raise_for_status(); data = response.json()
        except (httpx.HTTPError, ValueError) as e: raise PlatformError(f"Lazada API 失败: {e}") from e
        if data.get("code") not in (None, "0", 0): raise PlatformError(f"Lazada 返回错误: {data.get('message') or data}")
        return data.get("data") or data

    def exchange_code(self, code: str) -> TokenPair:
        data = self._call("POST", "/auth/token/create", {"code": code})
        return TokenPair(data.get("access_token", ""), data.get("refresh_token", ""), int(data.get("expires_in") or 604800), data)

    def refresh(self) -> TokenPair:
        data = self._call("POST", "/auth/token/refresh", {"refresh_token": self.shop.refresh_token})
        return TokenPair(data.get("access_token", ""), data.get("refresh_token", self.shop.refresh_token), int(data.get("expires_in") or 604800), data)

    def fetch_orders(self, days: int = 7) -> list[NormalizedOrder]:
        self._ensure_authorized(); start = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time()-days*86400))
        out=[]; offset=0
        for _ in range(100):
            data=self._call("GET", "/orders/get", {"access_token": self.shop.access_token,
                "created_after": start, "limit": "100", "offset": str(offset)})
            rows=data.get("orders") or []
            for row in rows:
                out.append(NormalizedOrder(str(row.get("order_number") or row.get("order_id")), float(row.get("price") or 0), 1,
                    {"pending":"paid","shipped":"shipped","delivered":"delivered","canceled":"refunded"}.get(str(row.get("statuses", [""])[0]).lower(), "paid"),
                    str(row.get("currency") or "USD"), str(row.get("address_shipping", {}).get("country") or ""), str(row.get("customer_first_name") or "")[:64]))
            offset += len(rows)
            if not rows or offset >= int(data.get("countTotal") or data.get("total_count") or offset): break
        return out

    def publish_listing(self, listing, product, *, resume=None, checkpoint=None) -> PublishResult:
        self._ensure_authorized(); attrs = product.attrs or {}; payload = attrs.get("lazada_product")
        if not isinstance(payload, dict): raise PlatformError("Lazada 发布需要 attrs.lazada_product（按站点类目 Schema）")
        root = ET.Element("Request")
        def append(parent, value):
            for key, item in value.items():
                node = ET.SubElement(parent, str(key))
                if isinstance(item, dict): append(node, item)
                else: node.text = str(item)
        append(root, payload)
        data = self._call("POST", "/product/create", {"access_token": self.shop.access_token,
                                                       "payload": ET.tostring(root, encoding="unicode")})
        return PublishResult(str(data.get("item_id") or data.get("batch_id") or product.sku),
                             raw={"response": data, "verification": "awaiting_real_shop_acceptance"})


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


# ---------------------------------------------------------------- Amazon（路线图）

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
