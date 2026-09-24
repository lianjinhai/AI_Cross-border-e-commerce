"""1688（货源平台）适配器

1688 授权、token 交换/刷新与代发订单拉取。
"""
from urllib.parse import urlencode

import httpx

from . import contract
from .base import BaseAdapter
from .contract import _TIMEOUT, _UA, NormalizedOrder, PlatformError, TokenPair


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
                  "redirect_uri": contract.redirect_uri_for(self.shop)}
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
            "redirect_uri": contract.redirect_uri_for(self.shop),
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
        from ..open_1688 import Api1688Error, call_api

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
