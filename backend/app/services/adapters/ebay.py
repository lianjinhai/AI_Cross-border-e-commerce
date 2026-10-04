"""eBay 适配器

eBay OAuth、订单归一化与上架。
"""
import base64
import logging
import time
from urllib.parse import urlencode

import httpx

from . import contract
from .base import BaseAdapter
from .contract import _TIMEOUT, NormalizedOrder, PlatformError, PublishResult, TokenPair

logger = logging.getLogger(__name__)


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
        return contract.platform_base_url("ebay", "https://api.sandbox.ebay.com", self._API)

    @property
    def auth_host(self) -> str:
        return ("https://auth.sandbox.ebay.com" if contract.platform_environment("ebay") == "sandbox"
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
                resp = contract.request_with_retry("GET", f"{self.api_host}/sell/fulfillment/v1/order",
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
            response = contract.request_with_retry(method, f"{self.api_host}{path}", json=body,
                                     headers=headers, timeout=_TIMEOUT)
            response.raise_for_status()
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as e:
            detail = getattr(getattr(e, "response", None), "text", "")
            raise PlatformError(f"eBay Inventory API 失败: {e} {detail[:300]}") from e

    def publish_listing(self, listing, product, *, resume=None, checkpoint=None) -> PublishResult:
        self._ensure_authorized()
        self._pre_publish_checks(listing, product)
        # 合规闸门：与 shopee/lazada/tiktok/walmart 同一入口（基类
        # `_enforce_publish_gate`）。2026-10 之前这里只 logger.warning，
        # 等于租户显式开启了 destination_compliance_enforce 之后，eBay 仍照发
        # 不误——开关亮着、平台放行，开关本身成了谎话；且 eBay 是当时唯一
        # 不设防的 can_publish 平台。阻断口径 raise，告警口径只记日志。
        advisory = self._enforce_publish_gate(listing, product, channel="ebay")
        attrs = product.attrs or {}
        required = {"ebay_category_id": "eBay 类目ID", "ebay_location_key": "库存地点",
                    "ebay_fulfillment_policy_id": "履约策略", "ebay_payment_policy_id": "付款策略",
                    "ebay_return_policy_id": "退货策略", "sale_price": "销售价", "onhand": "库存"}
        missing = [label for key, label in required.items() if not attrs.get(key)]
        if missing:
            detail = "、".join(missing)
            if advisory:
                detail += "；另需注意（不阻断本次发布）：" + "；".join(advisory)
            raise PlatformError("eBay 发布前置校验未通过，缺少：" + detail)
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
            "environment": contract.platform_environment("ebay"), "offer_id": offer_id,
            "publish": published, "verification": "awaiting_real_shop_acceptance"})
