"""Shopee 适配器

v2 HMAC-SHA256 签名、订单拉取、上架预检与两步发布。
"""
import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx

from . import catmap, contract
from .base import BaseAdapter
from .contract import _TIMEOUT, _UA, NormalizedOrder, PlatformError, PublishResult, TokenPair


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
                  "redirect_uri": contract.redirect_uri_for(self.shop),
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
        category_id = catmap.category_mapping_for(
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
        category_id = catmap.category_mapping_for(self.db, self.shop.tenant_id,
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
