"""平台适配器契约层：常量、环境开关、统一重试、异常与归一化数据结构。

本模块由原 `services/platform_adapters.py`（1303 行单文件）按 DEBT-05 拆分而来。
对外契约**不变**：`app.services.platform_adapters` 仍是唯一导入入口。

为什么把契约单独成层：`BaseAdapter` 与全部 13 个平台适配器都依赖这组名字，
把它放在最底层可消除循环依赖（原单文件靠"定义顺序"隐式满足）。
"""
import os
import time
from dataclasses import dataclass, field

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


def redirect_uri_for(shop) -> str:
    """授权回调地址。本地默认与 shops.py 注册的回调路由一致；
    生产部署需公网回调时，用 ERP_PUBLIC_BASE_URL 环境变量覆盖主机部分。"""
    import os

    base = os.getenv("ERP_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/api/shops/callback/{shop.platform}/{shop.id}"
