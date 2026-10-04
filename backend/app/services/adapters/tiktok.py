"""TikTok Shop 适配器

token 端点、签名、图片预上传与商品发布（含断点续传）。
"""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx

from . import catmap, contract
from .base import BaseAdapter
from .contract import _TIMEOUT, _UA, NormalizedOrder, PlatformError, PublishResult, TokenPair


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
        return contract.platform_base_url("tiktok", "https://open-api-sandbox.tiktokglobalshop.com",
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
            resp = contract.request_with_retry(method, f"{self.api_host}{path}", params=params,
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
        # 合规闸门：与 shopee/ebay 同一入口，缺目的国准入证据时按租户开关拦截。
        # 放在 listing_readiness 之前——法规准入优先于平台字段完整性。
        self._enforce_publish_gate(listing, product, channel="tiktok")
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
            "environment": contract.platform_environment("tiktok"), "global_product": created,
            "publish": published, "verification": "awaiting_real_shop_acceptance"})

    def authorize_url(self) -> str:
        params = {"app_key": self.shop.app_key, "state": self.shop.id,
                  "redirect_uri": contract.redirect_uri_for(self.shop)}
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
        category_id = catmap.category_mapping_for(
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
