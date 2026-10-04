"""Walmart 适配器

Walmart OAuth、游标分页订单与上架。
"""
import base64
import json
import uuid
from urllib.parse import urlencode

import httpx

from . import contract
from .base import BaseAdapter
from .contract import _TIMEOUT, NormalizedOrder, PlatformError, PublishResult, TokenPair


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
        return contract.platform_base_url("walmart", "https://sandbox.walmartapis.com",
                                 "https://marketplace.walmartapis.com")

    def authorize_url(self) -> str:
        return "https://login.account.wal-mart.com/authorize?" + urlencode({
            "responseType": "code", "clientId": self.shop.app_key,
            "redirectUri": contract.redirect_uri_for(self.shop), "clientType": "seller",
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
                            "redirect_uri": contract.redirect_uri_for(self.shop)})

    def refresh(self) -> TokenPair:
        return self._token({"grant_type": "refresh_token", "refresh_token": self.shop.refresh_token})

    def _call(self, method: str, path: str, *, params=None, body=None, files=None) -> dict:
        headers = {"WM_SEC.ACCESS_TOKEN": self.shop.access_token,
                   "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
                   "WM_SVC.NAME": "Walmart Marketplace", "WM_MARKET": "us",
                   "Accept": "application/json"}
        try:
            response = contract.request_with_retry(method, f"{self.api_host}{path}", params=params,
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
        self._ensure_authorized()
        # 合规闸门：与 shopee/ebay 同一入口，缺目的国准入证据时按租户开关拦截。
        self._enforce_publish_gate(listing, product, channel="walmart")
        attrs = product.attrs or {}
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
