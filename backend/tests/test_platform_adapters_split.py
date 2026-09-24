"""DEBT-05：平台适配器拆包后的对外契约守护。

**为什么必须有这个文件**（T-29 同类陷阱，实测已复现）：
`platform_adapters.py` 由 1303 行单文件按 DEBT-05 拆为 `adapters/` 包。拆包后
适配器内部调用的是 `contract.request_with_retry(...)`，而测试用
`monkeypatch.setattr("app.services.platform_adapters.request_with_retry", ...)`
只改**门面模块**的属性。若两者不是同一个对象，补丁会**静默失效**——
测试照旧全绿，但实际发出的是真实 HTTP 请求（实测：第一版实现下
`test_ebay_offset_pagination` 打到 api.sandbox.ebay.com 并抛 401）。

本文件把「门面属性必须代理到调用点」固化为契约，防止后人重构时再次踩坑。
"""
from types import SimpleNamespace

import pytest

from app.services import platform_adapters as facade
from app.services.adapters import catmap, contract


def test_facade_reexports_full_public_surface():
    """门面必须重新导出原单文件的全部公共名字（导入路径不变）。"""
    expected = [
        "ADAPTERS", "Ali1688Adapter", "AliExpressAdapter", "AmazonAdapter",
        "BaseAdapter", "CategoryMappingRegistry", "EbayAdapter", "LazadaAdapter",
        "MercadoLibreAdapter", "NormalizedOrder", "PlatformError",
        "PlannedSalesAdapter", "PublishResult", "SheinAdapter", "ShopeeAdapter",
        "ShopifyAdapter", "TemuAdapter", "TikTokAdapter", "TokenPair",
        "WalmartAdapter", "category_mapping_for", "get_adapter",
        "platform_base_url", "platform_environment", "platform_meta",
        "redirect_uri_for", "request_with_retry",
    ]
    missing = [n for n in expected if not hasattr(facade, n)]
    assert not missing, "门面缺少以下对外名字（导入路径会断）：%s" % missing


@pytest.mark.parametrize("name,owner", [
    ("request_with_retry", contract),
    ("platform_environment", contract),
    ("platform_base_url", contract),
    ("redirect_uri_for", contract),
    ("category_mapping_for", catmap),
])
def test_patchable_names_are_proxied_to_call_site(name, owner):
    """可打补丁的名字必须是**调用点模块**的同一个对象。

    这是补丁能生效的根因：适配器内部写的是 `contract.<name>`，
    门面读到的也必须是同一个对象，否则 monkeypatch 落在空处。
    """
    assert getattr(facade, name) is getattr(owner, name), (
        "facade.%s 未代理到 %s.%s——monkeypatch 会静默失效"
        % (name, owner.__name__.split(".")[-1], name))


def test_patching_facade_reaches_adapter_call_site(monkeypatch):
    """端到端判别力：patch 门面后，适配器内部必须用到被替换的实现。

    判别力设计：fake 会记录调用并返回**可识别**的数据。若补丁失效，
    适配器会走真实 HTTP（测试环境必然失败），而不是静默通过。
    """
    from app.services.adapters.ebay import EbayAdapter

    shop = SimpleNamespace(app_key="k", app_secret="s", access_token="t",
                           refresh_token="r", shop_id="X", status="authorized",
                           token_expire_at=None, tenant_id=1)
    offsets = []

    class _Resp:
        content = b"{}"

        def raise_for_status(self):
            pass

        def json(self):
            return {"total": 2, "orders": [
                {"orderId": str(offsets[-1] + 1), "orderPaymentStatus": "PAID"}]}

    def fake_request(method, url, **kwargs):
        offsets.append(kwargs["params"]["offset"])
        return _Resp()

    monkeypatch.setattr("app.services.platform_adapters.request_with_retry",
                        fake_request)
    assert len(EbayAdapter(None, shop).fetch_orders()) == 2
    assert offsets == [0, 1], (
        "补丁未到达适配器调用点——monkeypatch 静默失效（会打到真实平台）")


def test_patching_category_mapping_changes_readiness_result(monkeypatch):
    """类目映射补丁必须影响 missing_publish_requirements 的结果。"""
    from app.services.adapters.shopee import ShopeeAdapter

    shop = SimpleNamespace(app_key="k", app_secret="s", access_token="t",
                           refresh_token="r", shop_id="10001", status="authorized",
                           token_expire_at=None, tenant_id=1)
    adapter = ShopeeAdapter(None, shop)
    listing = SimpleNamespace(keywords=["x"])
    product = SimpleNamespace(category="家居", images=["https://cdn.example.com/1.jpg"],
                              attrs={"sale_price": 9.9, "onhand": 5, "weight_kg": 0.5})

    monkeypatch.setattr("app.services.platform_adapters.category_mapping_for",
                        lambda *args: "")
    without = adapter.missing_publish_requirements(listing, product)
    monkeypatch.setattr("app.services.platform_adapters.category_mapping_for",
                        lambda *args: "100642")
    with_mapping = adapter.missing_publish_requirements(listing, product)

    assert any("类目" in m for m in without), "查不到映射时必须报缺类目映射"
    assert not any("类目" in m for m in with_mapping), "有映射时不应再报缺类目映射"


def test_split_modules_do_not_import_each_others_platforms():
    """拆包后各平台模块之间不得互相 import（保持正交，避免回到上帝模块）。"""
    import pathlib

    pkg = pathlib.Path(facade.__file__).parent / "adapters"
    platform_files = ["ali1688.py", "shopee.py", "tiktok.py", "ebay.py",
                      "walmart.py", "lazada.py", "planned.py"]
    offenders = []
    for name in platform_files:
        text = (pkg / name).read_text(encoding="utf-8")
        for other in platform_files:
            if other == name:
                continue
            stem = other[:-3]
            if ("from .%s import" % stem) in text or ("import %s" % stem) in text:
                offenders.append("%s -> %s" % (name, other))
    assert not offenders, "平台适配器之间出现互相 import：%s" % offenders


def test_adapters_package_modules_stay_under_hard_limit():
    """拆包目的之一就是消除超长文件——各模块必须都在硬上限内。"""
    import pathlib

    from app.services.platform_adapters import ADAPTERS  # noqa: F401  确保已导入

    pkg = pathlib.Path(facade.__file__).parent / "adapters"
    oversized = []
    for path in sorted(pkg.glob("*.py")):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > 500:
            oversized.append("%s (%d 行)" % (path.name, lines))
    assert not oversized, "拆分后仍有模块超 500 行硬上限：%s" % oversized
