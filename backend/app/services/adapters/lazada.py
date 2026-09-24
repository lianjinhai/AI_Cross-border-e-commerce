"""Lazada 适配器

Lazada 签名、偏移分页订单与上架。
"""
import hashlib
import hmac
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import httpx

from . import contract
from .base import BaseAdapter
from .contract import _TIMEOUT, NormalizedOrder, PlatformError, PublishResult, TokenPair


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
        return contract.platform_base_url("lazada", "https://api-sandbox.lazada.com/rest", production)

    def _signed(self, path: str, params: dict) -> dict:
        merged = {"app_key": self.shop.app_key, "timestamp": str(int(time.time() * 1000)),
                  "sign_method": "sha256", **params}
        source = path + "".join(f"{k}{merged[k]}" for k in sorted(merged))
        merged["sign"] = hmac.new(self.shop.app_secret.encode(), source.encode(), hashlib.sha256).hexdigest().upper()
        return merged

    def authorize_url(self) -> str:
        return "https://auth.lazada.com/oauth/authorize?" + urlencode({
            "response_type": "code", "force_auth": "true", "redirect_uri": contract.redirect_uri_for(self.shop),
            "client_id": self.shop.app_key, "state": str(self.shop.id)})

    def _call(self, method: str, path: str, params: dict) -> dict:
        signed = self._signed(path, params)
        try:
            response = contract.request_with_retry(method, self.api_host + path, params=signed if method == "GET" else None,
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
