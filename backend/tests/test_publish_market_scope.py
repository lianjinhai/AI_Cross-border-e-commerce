"""P0-3：以目标店铺市场校验，缺配置与故障不得放行真实发布。"""

from types import SimpleNamespace

import pytest

from app.services import publish_gate
from app.services.adapters.contract import PlatformError
from app.services.adapters.ebay import EbayAdapter


def test_target_store_market_overrides_product_and_adapter(monkeypatch):
    seen = []
    monkeypatch.setattr(publish_gate.compliance_registry, "check_evidence",
                        lambda db, tenant, product, country: seen.append(country) or {})
    result = publish_gate.evaluate(None, 1, product=SimpleNamespace(id=1, attrs={"destination_country": "US"}),
                                   platform="ebay", shop=SimpleNamespace(id=2, market="TR"), mode="enforce")
    assert seen == ["TR"] and result["destination_country"] == "TR"


@pytest.mark.parametrize("market", ["", "EU", "ZZ", "nonsense"])
def test_missing_or_unsupported_store_market_blocks_without_product_fallback(monkeypatch, market):
    def unexpected(*args):
        pytest.fail("未知店铺市场不应猜测目的地后继续校验")
    monkeypatch.setattr(publish_gate.compliance_registry, "check_evidence", unexpected)
    result = publish_gate.evaluate(None, 1, product=SimpleNamespace(id=1, attrs={"destination_country": "US"}),
                                   platform="ebay", shop=SimpleNamespace(id=2, market=market), mode="enforce")
    assert result["gate_status"] == "block"


def test_compliance_backend_failure_blocks_enforced_publish(monkeypatch):
    def broken(*args):
        raise RuntimeError("contract outage")
    monkeypatch.setattr(publish_gate.compliance_registry, "check_evidence", broken)
    result = publish_gate.evaluate(None, 1, product=SimpleNamespace(id=1, attrs={}),
                                   shop=SimpleNamespace(id=2, market="US"), mode="enforce")
    assert result["gate_status"] == "block"
    assert "跳过" not in "".join(result["reasons"])


def test_adapter_cannot_check_tr_but_submit_to_hardcoded_us(monkeypatch):
    adapter = EbayAdapter(None, SimpleNamespace(market="TR", tenant_id=1))
    monkeypatch.setattr(adapter, "_destination_access_issues", lambda product: [])
    with pytest.raises(PlatformError, match="发布范围"):
        adapter._enforce_publish_gate(None, SimpleNamespace(id=1), channel="contract")
