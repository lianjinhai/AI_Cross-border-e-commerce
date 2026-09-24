"""平台适配器层（兼容门面）——把每个电商平台的一切差异封装在各自的 Adapter 里。

**本模块是唯一对外入口**。原 1303 行单文件已按 DEBT-05 拆为 `adapters/` 包，
本文件只做「重新导出 + 可打补丁点转发」，因此：

- `from app.services.platform_adapters import X` 全部照旧；
- 测试里的 `monkeypatch.setattr("app.services.platform_adapters.<name>", ...)`
  **必须继续生效**——见下面的 `_FORWARDED` 说明。

设计要点（响应"平台不一致性"）：
1. BaseAdapter 定义统一契约：authorize_url / exchange_code / refresh /
   fetch_orders / publish_listing，以及 capabilities 能力清单与 role 角色。
2. 数据在适配器边界完成"规范化"：
   - TokenPair：各平台 token 响应字段不同（expires_in / expire_in / expire_time…）；
   - NormalizedOrder：金额币种、状态枚举、单号字段全部在适配器内转成统一结构；
   - PublishResult：平台返回的 item_id 字段不同（item_id vs product_id vs sku）。
3. 发布前置校验：每个平台必填字段不同，适配器先声明 missing_publish_requirements()，
   系统缺什么就明确报什么，绝不盲目调用平台 API。
4. 签名差异全部内聚：1688 HMAC-SHA1(path+sorted)、Shopee base64(HMAC-SHA256(path|ts))、
   TikTok sha256(app_key+ts+token)。

包结构（各文件职责）：
    adapters/contract.py  常量 / 环境开关 / 重试 / 异常 / 三个归一化数据结构
    adapters/catmap.py    类目映射查询与提示
    adapters/base.py      BaseAdapter 统一契约与通用守卫（发布三道关、限流）
    adapters/<platform>.py 各平台适配器（1688 / shopee / tiktok / ebay / walmart / lazada / planned）
    adapters/registry.py  ADAPTERS 注册表 + get_adapter + platform_meta
"""
import sys
import time  # noqa: F401  历史补丁点：monkeypatch.setattr(...platform_adapters.time.sleep)
import types

import httpx  # noqa: F401  历史补丁点：monkeypatch.setattr(...platform_adapters.httpx.request)

from .adapters import catmap as _catmap
from .adapters import contract as _contract
from .adapters.ali1688 import Ali1688Adapter
from .adapters.base import BaseAdapter
from .adapters.catmap import CategoryMappingRegistry, category_mapping_for
from .adapters.contract import (
    NormalizedOrder,
    PlatformError,
    PublishResult,
    TokenPair,
    platform_base_url,
    platform_environment,
    redirect_uri_for,
    request_with_retry,
)
from .adapters.ebay import EbayAdapter
from .adapters.lazada import LazadaAdapter
from .adapters.planned import (
    AliExpressAdapter,
    AmazonAdapter,
    MercadoLibreAdapter,
    PlannedSalesAdapter,
    SheinAdapter,
    ShopifyAdapter,
    TemuAdapter,
)
from .adapters.registry import ADAPTERS, get_adapter, platform_meta
from .adapters.shopee import ShopeeAdapter
from .adapters.tiktok import TikTokAdapter
from .adapters.walmart import WalmartAdapter

__all__ = [
    "ADAPTERS", "Ali1688Adapter", "AliExpressAdapter", "AmazonAdapter", "BaseAdapter",
    "CategoryMappingRegistry", "EbayAdapter", "LazadaAdapter", "MercadoLibreAdapter",
    "NormalizedOrder", "PlatformError", "PlannedSalesAdapter", "PublishResult",
    "SheinAdapter", "ShopeeAdapter", "ShopifyAdapter", "TemuAdapter", "TikTokAdapter",
    "TokenPair", "WalmartAdapter", "category_mapping_for", "get_adapter",
    "platform_base_url", "platform_environment", "platform_meta", "redirect_uri_for",
    "request_with_retry",
]


# ---------------------------------------------------------------- 可打补丁点转发
#
# **问题**：拆包后适配器内部调用的是 `contract.request_with_retry(...)`，
# 而测试用 `monkeypatch.setattr("app.services.platform_adapters.request_with_retry", ...)`
# 只改了**本门面模块**的属性——两处不是同一个对象，补丁会**静默失效**
# （测试照旧全绿，但实际没测到目标代码，属 T-29 同类陷阱；实测已复现：
# 打补丁后 eBay 适配器仍然发出真实 HTTP 请求）。
#
# **解法**：用模块级 `__getattr__` 做**读取代理**，并用**同名函数**做写入代理。
# 关键是「补丁必须落在调用点上」：
#   - `getattr(facade, name)`   → 始终读 `contract` / `catmap` 的当前值
#   - `setattr(facade, name, x)` → 直接写 `contract` / `catmap`
# 这样适配器内部的 `contract.request_with_retry` 与被补丁的名字是**同一个对象**。
#
# 为什么不用 `setattr` 装转发器（第一版做法，已废弃）：那只在导入时装一次，
# 之后 monkeypatch 的 setattr 会把门面属性**重新绑定成普通值**，代理关系即被破坏。
_FORWARDED = ("request_with_retry", "category_mapping_for", "platform_environment",
              "platform_base_url", "redirect_uri_for")


def _owner_of(name: str):
    """返回该名字的**真实归属模块**（适配器的实际调用点）。"""
    return _catmap if name == "category_mapping_for" else _contract


class _ForwardingModule(types.ModuleType):
    """模块级属性代理：把 _FORWARDED 的读写都转到真实归属模块。"""

    def __getattr__(self, name: str):
        if name in _FORWARDED:
            return getattr(_owner_of(name), name)
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value) -> None:
        if name in _FORWARDED:
            setattr(_owner_of(name), name, value)
        else:
            super().__setattr__(name, value)


def _install_forwarding() -> None:
    """把本模块替换为转发模块实例（保留已导入的名字）。"""
    module = sys.modules[__name__]
    if isinstance(module, _ForwardingModule):
        return
    proxy = _ForwardingModule(module.__name__, module.__doc__)
    proxy.__dict__.update(module.__dict__)
    proxy.__dict__["_ForwardingModule"] = _ForwardingModule
    proxy.__dict__["_FORWARDED"] = _FORWARDED
    proxy.__dict__["_owner_of"] = _owner_of
    proxy.__dict__["_install_forwarding"] = _install_forwarding
    sys.modules[__name__] = proxy


_install_forwarding()
