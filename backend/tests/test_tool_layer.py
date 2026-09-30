"""Tool Layer 的回归测试（Agent OS §10 / §18.3 第 2 步）。

**为什么必须有**：Tool Layer 的全部价值都在「闸门真的拦得住」。
若只是把查询包一层、没有任何检查，那么：
  - 少声明一个 permission → 该 Tool 变成无门槛的万能查询口；
  - 写方法能被 Agent 直接调用 → §9.1「Agent 不得直接改业务数据」当场失效；
  - 审计没落库 → §19 验收项 5「全部可追溯」无法成立；
  - 清单漏项 → 架构文档与代码分叉，且没有任何人会发现。

因此本文件的重点不是「Tool 能返回数据」，而是**判别力**：每条断言都要能构造出
违规并证明它会被抓到（规范 T-55：豁免与放行必须配反向断言）。

**与架构文档的关系**：`test_manifest_matches_architecture_doc` 直接解析
`docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` 的 §10.4 + §10.4.1 两张表格
并与注册表比对——「文档改了、代码没改」会在 CI 变红，而不是靠人工核对。
"""
import re
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
ARCH_DOC = REPO_DIR / "docs" / "AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md"

sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_context import ROLE_PERMISSIONS  # noqa: E402
from app.tools import audit as tool_audit  # noqa: E402
from app.tools import registry  # noqa: E402
from app.tools.contract import (  # noqa: E402
    ERR_BAD_PARAM,
    ERR_INTERNAL,
    ERR_NOT_FOUND,
    ERR_NOT_IMPLEMENTED,
    ERR_PERMISSION,
    SOURCE_CONTEXT,
    TRIGGER_USER_GOAL,
    ToolContext,
    ToolResult,
    ToolSpec,
    legacy_context,
)

# ---------------------------------------------------------------- §10.4 清单一致性


def _doc_manifest() -> dict:
    """解析架构文档 §10.4 + §10.4.1 两张表格 -> ``{"<tool>.<method>": {permission, writes}}``。

    表格形态（Tool 名只在首行出现，后续行首列为空即续行）：
        | **Product Tool** | `get_products()` | `product:read` | 读 |
        |                  | `analyze_product()` | `product:read` | 读 |
        | **Memory Tool**  | `recall()` / `remember()` | `ai:read` / `ai:write` | 读/写 |
    一行里出现多个方法/权限时按出现顺序一一对应。
    """
    text = ARCH_DOC.read_text(encoding="utf-8")
    # 区段取「§10.4 标题 → §10.5 标题」之间：§10.4.1（第二批清单）夹在其中，
    # 因此无需再切一刀。若哪天把第二批挪出这个区间，本测试会因数量不符立刻变红。
    section = text.split("### 10.4", 1)[1].split("### 10.5", 1)[0]
    out: dict = {}
    tool = ""
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        head, methods, perms, mode = cells[0], cells[1], cells[2], cells[3]
        if head.startswith("**"):
            tool = head.strip("*").replace(" Tool", "").strip().lower()
        if not tool or not methods.startswith("`"):
            continue  # 表头行 / 分隔行
        names = re.findall(r"`([a-z_]+)\(\)`", methods)
        keys = re.findall(r"`([a-z_]+:[a-z_:]+)`", perms)
        flags = ["写" in part for part in mode.split("/")]
        assert len(names) == len(keys) == len(flags), (
            "§10.4 行内方法/权限/读写三列数量不齐：%r" % (line,))
        for name, key, writes in zip(names, keys, flags):
            out["%s.%s" % (tool, name)] = {"permission": key, "writes": writes}
    return out


def test_manifest_matches_architecture_doc():
    """注册表必须与 §10.4 + §10.4.1 冻结清单**逐条一致**（数量、权限、读写属性）。"""
    doc = _doc_manifest()
    assert len(doc) == 43, "§10.4 + §10.4.1 应含 43 个方法，解析到 %d 个：%s" % (len(doc), sorted(doc))
    assert "listing.get_listings" in doc, "§10.4.1 第二批表格未被解析到（区段边界写错？）"
    assert "conversation.get_conversations" in doc, "§10.4.1 的 Conversation Tool 未被解析到"
    assert "compliance.get_review_decisions" in doc, "§10.4.1 的 Compliance Tool 补批未被解析到"
    assert "supply.get_catalog_products" in doc, "§10.4.1 的 Supply Tool 目录补批未被解析到"
    assert "supply.get_forecast_snapshot" in doc, "§10.4.1 的 Supply Tool 预测补批未被解析到"
    assert "finance.get_campaigns" in doc, "§10.4.1 的 Finance Tool 广告补批未被解析到"
    assert "listing.get_published_product_ids" in doc, "§10.4.1 的 Listing Tool 补批未被解析到"
    assert "conversation.count_conversations" in doc, "§10.4.1 的 Conversation Tool 计数补批未被解析到"
    assert "order.get_sales_summary" in doc, "§10.4.1 的 Order Tool 汇总补批未被解析到"
    assert "market.get_latest_scores" in doc, "§10.4.1 的 Market Tool 批量评分补批未被解析到"
    assert "product.find_duplicate" in doc, "§10.4.1 的 Product Tool 查重补批未被解析到"

    got = registry.tool_specs()
    assert set(got) == set(doc), (
        "注册表与 §10.4 不一致\n  只在文档：%s\n  只在代码：%s"
        % (sorted(set(doc) - set(got)), sorted(set(got) - set(doc))))

    mismatches = []
    for key, want in doc.items():
        spec = got[key]
        if spec.permission != want["permission"]:
            mismatches.append("%s 权限：文档 %s / 代码 %s"
                              % (key, want["permission"], spec.permission))
        if spec.writes != want["writes"]:
            mismatches.append("%s 读写：文档 %s / 代码 %s"
                              % (key, want["writes"], spec.writes))
    assert not mismatches, "注册表与架构文档不一致：\n  " + "\n  ".join(mismatches)


def test_doc_parser_has_discriminating_power():
    """判别力：提取器必须真读出内容（防止「解析到空字典所以永不报错」）。"""
    doc = _doc_manifest()
    assert doc["product.get_products"] == {"permission": "product:read", "writes": False}
    assert doc["product.create_listing_draft"]["writes"] is True
    assert doc["listing.get_listings"] == {"permission": "listing:read", "writes": False}
    assert doc["conversation.get_conversations"] == {"permission": "support:read",
                                                     "writes": False}
    assert doc["order.get_sales_summary"] == {"permission": "order:read", "writes": False}
    assert doc["product.find_duplicate"] == {"permission": "product:read", "writes": False}
    assert doc["market.pick_trend"] == {"permission": "product:read", "writes": False}
    assert doc["memory.recall"] == {"permission": "ai:read", "writes": False}
    assert doc["memory.remember"] == {"permission": "ai:write", "writes": True}


def test_every_read_spec_has_implementation():
    """声明了只读方法却忘了写 `_<method>`，必须在这里被抓住而不是运行时才发现。"""
    missing = [spec.key for cls in registry.TOOLS.values() for spec in cls.specs
               if not spec.writes and not callable(getattr(cls, "_" + spec.method, None))]
    assert not missing, "只读方法缺少实现：%s" % missing


def test_registry_get_tool_rejects_unknown_name():
    """取不存在的 Tool 必须报错并列出在册名单，而不是返回 None 让调用方空指针。"""
    with pytest.raises(KeyError) as exc:
        registry.get_tool("nonexistent")
    assert "product" in str(exc.value)


# ---------------------------------------------------------------- 契约不变量


def test_permission_catalog_is_derived_not_copied():
    """权限目录必须是 `ROLE_PERMISSIONS` 的并集，而不是另抄一份清单（T-53）。"""
    from app.tools.contract import _ALL_KNOWN_PERMISSIONS

    want = frozenset(p for perms in ROLE_PERMISSIONS.values() for p in perms)
    assert _ALL_KNOWN_PERMISSIONS == want


def test_toolspec_rejects_permission_outside_frozen_catalog():
    """写错权限 key（如 products:read）必须在构造期就报错——否则该 Tool 无人可授权。"""
    with pytest.raises(ValueError) as exc:
        ToolSpec(tool="product", method="x", permission="products:read",
                 writes=False, summary="")
    assert "冻结目录" in str(exc.value)


def test_toolresult_requires_error_when_not_ok():
    with pytest.raises(ValueError):
        ToolResult(ok=False)


def test_toolresult_rejects_error_when_ok():
    with pytest.raises(ValueError):
        ToolResult(ok=True, error={"code": "X", "detail": "y"})


def test_conversation_tool_dict_excludes_buyer_pii():
    """字段口径不得含买家 PII：Tool 结果会被审计落库（§15.4）。

    这是**结构性**防泄漏：审计层只能按模式脱敏（手机号/邮箱），认不出「张三」是
    人名。所以 PII 必须在字段口径处就排除，而不是指望下游拦。
    """
    from app.models import Conversation
    from app.tools.conversation import conversation_dict

    data = conversation_dict(Conversation(tenant_id=1, platform="shopee",
                                          buyer_name="张三", order_id=7, product_id=8,
                                          status="open"))
    assert "buyer_name" not in data, "买家姓名属 PII，不得进 Tool 返回体（会被审计落库）"
    assert data["order_id"] == 7 and data["product_id"] == 8
    assert data["platform"] == "shopee" and data["status"] == "open"


def test_context_requires_workspace_id():
    """§17.1 禁止无上下文 Agent：workspace_id 缺失必须拒绝构造，不降级放行。"""
    with pytest.raises(ValueError) as exc:
        ToolContext(tenant_id=1, workspace_id=0, agent_type="market_intelligence")
    assert "禁止无上下文" in str(exc.value)


def test_context_rejects_unknown_trigger():
    with pytest.raises(ValueError):
        ToolContext(tenant_id=1, workspace_id=1, agent_type="a", trigger="SOMETHING")


def test_unverified_context_is_fail_closed_for_has():
    """`permissions=None` 是「未校验」不是「无权限」：has() 一律 False（fail-closed）。"""
    ctx = legacy_context(tenant_id=1, agent_type="a")
    assert ctx.permission_checked is False
    assert ctx.has("product:read") is False


# ---------------------------------------------------------------- 调用管线


@pytest.fixture
def recorded(monkeypatch):
    """把审计替换成内存记录器：纯管线测试不必真连库。"""
    rows: list = []

    def _record(context, tool, method, params, result, latency_ms):
        rows.append({"tool": tool, "method": method, "params": params,
                     "ok": result.ok, "degraded": result.degraded,
                     "error": result.error, "latency_ms": latency_ms})

    monkeypatch.setattr(tool_audit, "record", _record)
    return rows


@pytest.fixture
def legacy_ctx():
    return legacy_context(tenant_id=1, agent_type="market_intelligence")


@pytest.fixture
def owner_ctx():
    return ToolContext(tenant_id=1, workspace_id=1, agent_type="market_intelligence",
                       permissions=ROLE_PERMISSIONS["OWNER"], source=SOURCE_CONTEXT,
                       trigger=TRIGGER_USER_GOAL)


def test_permission_denied_before_delegation(recorded):
    """权威上下文缺权限 → PERMISSION_DENIED。

    `db=None` 是刻意的：只读实现一旦被委派就会 AttributeError 变成 INTERNAL。
    断言错误码是 PERMISSION_DENIED 即证明**实现根本没被执行**。
    """
    ctx = ToolContext(tenant_id=1, workspace_id=1, agent_type="risk_compliance",
                      permissions=frozenset({"compliance:read"}), source=SOURCE_CONTEXT)
    result = registry.open_tool("product", ctx, db=None).call("get_products")
    assert result.ok is False
    assert result.error["code"] == ERR_PERMISSION
    assert result.degraded is False
    assert recorded[0]["ok"] is False


def test_authoritative_context_with_permission_passes_gate(recorded):
    """反向断言：有权限时必须放行到实现（用 db=None 触发的 INTERNAL 作为「已放行」的证据）。"""
    ctx = ToolContext(tenant_id=1, workspace_id=1, agent_type="product_intelligence",
                      permissions=frozenset({"product:read"}), source=SOURCE_CONTEXT)
    result = registry.open_tool("product", ctx, db=None).call("get_products")
    assert result.error["code"] == ERR_INTERNAL
    assert result.degraded is False


def test_legacy_context_is_allowed_but_marked_degraded(recorded, legacy_ctx):
    """兼容期上下文：放行但**必须**标记 degraded——缺口可见，而不是假装已校验。"""
    result = registry.open_tool("product", legacy_ctx, db=None).call("get_products")
    assert result.degraded is True
    assert result.error["code"] == ERR_INTERNAL
    assert recorded[0]["degraded"] is True


@pytest.mark.parametrize("tool,method", [
    ("product", "create_listing_draft"),
    ("store", "sync_orders"),
    ("supply", "create_purchase_order"),
    ("memory", "remember"),
])
def test_write_methods_are_refused_even_for_owner(recorded, owner_ctx, tool, method):
    """§10.5：写操作必须经 Action System。OWNER 持有全部权限也必须被拒。"""
    result = registry.open_tool(tool, owner_ctx, db=None).call(method)
    assert result.ok is False
    assert result.error["code"] == ERR_NOT_IMPLEMENTED
    assert "Action" in result.error["detail"]


def test_unknown_method_is_refused(recorded, owner_ctx):
    result = registry.open_tool("product", owner_ctx, db=None).call("drop_everything")
    assert result.error["code"] == ERR_NOT_IMPLEMENTED


def test_call_cannot_reach_internal_attributes(recorded, owner_ctx):
    """`call()` 只认冻结清单里的方法；`spec` / `_permitted` 之类的内部件不可触达。"""
    result = registry.open_tool("product", owner_ctx, db=None).call("spec")
    assert result.error["code"] == ERR_NOT_IMPLEMENTED


def test_memory_recall_reports_not_implemented(recorded, owner_ctx):
    """Phase 6 未到：recall 必须显式 NOT_IMPLEMENTED，不得静默返回空列表。

    静默返回空会让 Agent 把「记忆系统还没建」当成「确实没经验」，并据此下结论
    ——这是最危险的一类错误：错得毫无痕迹（§15.4）。
    """
    result = registry.open_tool("memory", owner_ctx, db=None).call("recall")
    assert result.ok is False
    assert result.error["code"] == ERR_NOT_IMPLEMENTED


# ---------------------------------------------------------------- 真连库：审计与隔离


def test_audit_row_lands_in_ai_logs(client):
    """§10.2「必须记录 Audit」的落地验证：调用后 ai_logs 真的多了一行。"""
    from app.db import SessionLocal
    from app.models import AiLog, Tenant

    db = SessionLocal()
    try:
        tenant_id = db.query(Tenant).order_by(Tenant.id).first().id
        before = db.query(AiLog).filter(AiLog.action == "tool:knowledge.search").count()
    finally:
        db.close()

    ctx = legacy_context(tenant_id=tenant_id, agent_type="market_intelligence")
    tool = registry.open_tool("knowledge", ctx, db=SessionLocal())
    try:
        result = tool.call("search", query="商标 侵权", top_k=2)
    finally:
        tool.db.close()
    assert result.ok is True, result.error
    assert result.degraded is True  # legacy 上下文无法校验权限

    db = SessionLocal()
    try:
        rows = (db.query(AiLog).filter(AiLog.action == "tool:knowledge.search")
                .order_by(AiLog.id.desc()).all())
    finally:
        db.close()
    assert len(rows) == before + 1, "Tool 调用未落审计"
    row = rows[0]
    assert row.mode == "tool"
    assert row.agent == "market_intelligence"
    assert row.tenant_id == tenant_id
    assert row.ok is True


def test_get_products_does_not_leak_across_tenants(client):
    """§10.2「禁止跨 Workspace 读取」的落地验证：另一个租户的商品读不到。"""
    from app.db import SessionLocal
    from app.models import Product, Tenant

    db = SessionLocal()
    try:
        tenant_a = db.query(Tenant).order_by(Tenant.id).first().id
        other = Tenant(name="ToolLayer隔离测试租户")
        db.add(other)
        db.commit()
        foreign = Product(tenant_id=other.id, sku="TOOL-ISOLATION-SKU",
                          title="不该被别的租户看到的商品")
        db.add(foreign)
        db.commit()
        other_id, foreign_id = other.id, foreign.id
    finally:
        db.close()

    try:
        ctx = legacy_context(tenant_id=tenant_a, agent_type="product_intelligence")
        tool = registry.open_tool("product", ctx, db=SessionLocal())
        try:
            result = tool.call("get_products", keyword="TOOL-ISOLATION-SKU")
        finally:
            tool.db.close()
        assert result.ok is True, result.error
        assert result.data == [], "跨租户数据泄漏：读到了其它租户的商品"
    finally:  # 测试库是会话级共享资源，构造的数据必须清干净（T-2 不制造顺序依赖）
        db = SessionLocal()
        try:
            db.query(Product).filter(Product.id == foreign_id).delete()
            db.query(Tenant).filter(Tenant.id == other_id).delete()
            db.commit()
        finally:
            db.close()


@pytest.fixture
def probe_tenant(client):
    """自带租户 + 商品 + 评分 + 合规报告 + 汇率：不依赖演示数据。

    为什么不能用演示租户：`test_api.py` 的 purge_demo_data 会在全量跑中清空演示
    数据，于是本用例「单跑通过、全量失败」——这正是规范 T-2 要消灭的顺序依赖。
    探针数据在本夹具里建、在本夹具里删，跑与不跑都不改变库的最终状态。
    """
    from datetime import datetime, timedelta

    from app.db import SessionLocal
    from app.models import (
        AiDecision,
        AiLog,
        ComplianceReport,
        ExchangeRate,
        ForecastSnapshot,
        Listing,
        MarketTrend,
        Product,
        ProductPerformance,
        ProductScore,
        Tenant,
    )

    db = SessionLocal()
    try:
        tenant = Tenant(name="ToolLayer真库探针租户")
        db.add(tenant)
        db.commit()
        product = Product(tenant_id=tenant.id, sku="TOOL-PROBE-1",
                          title="Tool Layer 真库探针商品",
                          attrs={"sale_price": 19.99, "weight_kg": 0.3})
        db.add(product)
        db.commit()
        listing = Listing(tenant_id=tenant.id, product_id=product.id, platform="shopee",
                          language="en", title="Tool Layer 真库探针 Listing",
                          description="probe listing", bullets=["bullet"],
                          keywords=["probe"], status="draft")
        db.add(listing)
        db.commit()
        db.add(ProductScore(tenant_id=tenant.id, product_id=product.id,
                            demand=70, competition=40, profit=65, risk=20, total=72))
        db.add(ComplianceReport(tenant_id=tenant.id, target_type="product",
                                product_id=product.id, risk_level="low", score=95))
        db.add(ExchangeRate(tenant_id=tenant.id, base_currency="USD",
                            quote_currency="CNY", rate=7.12,
                            effective_at=datetime.utcnow() - timedelta(days=1)))
        db.add(ForecastSnapshot(tenant_id=tenant.id, product_id=product.id,
                                version="probe-1",
                                training_cutoff=datetime.utcnow() - timedelta(days=1),
                                selected_model="probe", point_forecast=12.0,
                                confidence="high"))
        # 趋势与经营表现两行也让新补批方法（pick_trend / get_latest_performance）
        # 走成功分支——否则它们只会以 NOT_FOUND 通过覆盖测试，等于没测实现。
        db.add(MarketTrend(tenant_id=tenant.id, keyword="probe trend", platform="google",
                           search_volume=1000, growth_30d=50, competition=40))
        db.add(ProductPerformance(tenant_id=tenant.id, product_id=product.id,
                                  window_days=30, units_sold=1, revenue=19.99,
                                  profit=12.0, margin=0.2, refund_rate=0.0,
                                  sell_through=0.1, performance_score=62))
        db.commit()
        ids = {"tenant_id": tenant.id, "product_id": product.id,
               "listing_id": listing.id}
    finally:
        db.close()
    yield ids
    db = SessionLocal()
    try:  # 清干净：探针租户不留在测试库里，避免给后续用例制造隐含前提
        # 审计行必须一起删：Tool 调用会写入 ai_logs(tenant_id=探针租户)，
        # 它是 tenants 的外键子表，不清掉就删不掉租户（FK constraint failed）。
        db.query(AiLog).filter(AiLog.tenant_id == ids["tenant_id"]).delete()
        db.query(AiDecision).filter(AiDecision.tenant_id == ids["tenant_id"]).delete()
        db.query(ProductScore).filter(ProductScore.tenant_id == ids["tenant_id"]).delete()
        db.query(ComplianceReport).filter(
            ComplianceReport.tenant_id == ids["tenant_id"]).delete()
        db.query(ExchangeRate).filter(
            ExchangeRate.tenant_id == ids["tenant_id"]).delete()
        db.query(ForecastSnapshot).filter(
            ForecastSnapshot.tenant_id == ids["tenant_id"]).delete()
        db.query(MarketTrend).filter(MarketTrend.tenant_id == ids["tenant_id"]).delete()
        db.query(ProductPerformance).filter(
            ProductPerformance.tenant_id == ids["tenant_id"]).delete()
        db.query(Listing).filter(Listing.id == ids["listing_id"]).delete()
        db.query(Product).filter(Product.id == ids["product_id"]).delete()
        db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
        db.commit()
    finally:
        db.close()


def test_every_read_method_runs_against_real_db(probe_tenant):
    """§10.4 的每个只读方法都要能在真实库上跑通（含**成功路径**）。

    判定口径：`ok=True`，或**预期内**的数据缺失（NOT_FOUND）。
    INTERNAL / BAD_PARAM 一律算失败——它们意味着实现有缺陷，而不是数据不存在。
    探针夹具刻意把评分/合规报告/汇率/预测快照/趋势/经营表现都造齐，使
    `score_opportunity`、`check_product`、`get_fx_rate`、`get_forecast_snapshot`、
    `pick_trend`、`get_latest_performance` 走的是成功分支而不是 NOT_FOUND 分支。
    """
    from app.db import SessionLocal

    tenant_id = probe_tenant["tenant_id"]
    product_id = probe_tenant["product_id"]
    listing_id = probe_tenant["listing_id"]
    ctx = legacy_context(tenant_id=tenant_id, agent_type="market_intelligence")
    calls = [
        ("product", "get_products", {"limit": 5}),
        ("product", "get_product_ids", {"status": "active", "limit": 5}),
        ("product", "analyze_product", {"product_id": product_id}),
        ("market", "get_trends", {"limit": 5}),
        ("market", "score_opportunity", {"product_id": product_id}),
        ("supply", "search_suppliers", {"limit": 5}),
        ("supply", "get_supplier_offers", {"limit": 5}),
        ("supply", "get_offer_stats", {}),
        ("supply", "get_catalog_products", {"limit": 5}),
        ("supply", "get_forecast_snapshot", {"product_id": product_id}),
        ("compliance", "get_platform_rules", {}),
        ("compliance", "check_product", {"product_id": product_id}),
        ("order", "get_orders", {"limit": 5}),
        ("order", "analyze_sales", {"days": 30}),
        ("order", "get_daily_sales", {"product_id": product_id, "days": 30}),
        ("store", "list_connected_stores", {}),
        ("store", "get_store_metrics", {"days": 30}),
        ("finance", "calculate_profit", {"product_id": product_id}),
        ("finance", "get_unit_economics", {"product_id": product_id}),
        ("finance", "get_fx_rate", {"base": "USD", "quote": "CNY"}),
        ("knowledge", "search", {"query": "选品 合规"}),
        ("listing", "get_listings", {"limit": 5}),
        ("compliance", "check_listing", {"listing_id": listing_id}),
        ("conversation", "get_conversations", {"limit": 5}),
        ("compliance", "get_review_decisions", {"limit": 5}),
        ("finance", "get_campaigns", {"limit": 5}),
        ("listing", "get_published_product_ids", {}),
        ("product", "count_products", {"status": "active"}),
        ("product", "get_categories", {"status": "active"}),
        ("product", "get_latest_performance", {"product_id": product_id}),
        ("product", "get_sold_product_ids", {}),
        ("product", "find_duplicate", {"dedupe_hash": "probe-dedupe-none"}),
        ("order", "get_sales_summary", {"days": 30}),
        ("finance", "get_campaign_totals", {}),
        ("market", "get_latest_scores", {}),
        ("market", "pick_trend", {}),
        ("listing", "count_listings", {"status": "draft"}),
        ("conversation", "count_conversations", {"status": "open"}),
    ]
    assert len(calls) == 38, "真库覆盖清单应为 38 条，实际 %d" % len(calls)
    # 完整性（T-53）：除 memory.recall（Phase 6 未到，实现显式 NOT_IMPLEMENTED）外，
    # 冻结清单里的每个只读方法都必须在这里真跑一遍——否则第二批新增的方法会静默漏测。
    expected = {spec.key for spec in registry.tool_specs().values()
                if not spec.writes and spec.key != "memory.recall"}
    covered = {"%s.%s" % (tool_name, method) for tool_name, method, _ in calls}
    assert covered == expected, (
        "真库覆盖清单与冻结清单不一致：漏测 %s / 多测 %s"
        % (sorted(expected - covered), sorted(covered - expected)))

    failures = []
    ok_count = 0
    for tool_name, method, params in calls:
        tool = registry.open_tool(tool_name, ctx, db=SessionLocal())
        try:
            result = tool.call(method, **params)
        finally:
            tool.db.close()
        if result.ok:
            ok_count += 1
            continue
        if result.error["code"] == ERR_NOT_FOUND:
            continue  # NOT_FOUND = 这条记录不存在，不是实现缺陷
        failures.append("%s.%s -> %s: %s" % (tool_name, method,
                                             result.error["code"], result.error["detail"]))
    assert not failures, "只读方法在真实库上执行失败：\n  " + "\n  ".join(failures)
    # 反向断言：若哪天实现整体退化成「一律 NOT_FOUND」，上一条断言仍会全绿。
    # 探针数据（商品/Listing/评分/合规报告/汇率/预测快照/趋势/经营表现）齐备时，
    # 38 个方法应全部走成功分支。
    assert ok_count == 38, (
        "只读方法成功 %d/38——是否有实现静默退化成 NOT_FOUND？" % ok_count)


def test_compliance_agent_reads_go_through_tool_layer(probe_tenant):
    """判别力：compliance 的读取已迁到 Tool 层——每次读取必须留下 `mode=tool` 审计。

    为什么断言审计行而不是返回值：把实现改回 `self.db.get(Product, ...)` 时返回值
    完全相同，只有审计行会消失——没有这条，「已迁移」就只能靠人工看代码（T-55）。
    """
    from app.agents.compliance import ComplianceAgent
    from app.db import SessionLocal
    from app.models import AiLog, Listing

    tenant_id = probe_tenant["tenant_id"]
    agent = ComplianceAgent(tenant_id)
    try:
        report = agent.check_product(probe_tenant["product_id"])
        listing_report = agent.check_listing(probe_tenant["listing_id"])
    finally:
        agent.close()
    assert report["product_id"] == probe_tenant["product_id"]
    assert listing_report["listing_id"] == probe_tenant["listing_id"]

    db = SessionLocal()
    try:
        actions = {r.action for r in db.query(AiLog)
                   .filter(AiLog.tenant_id == tenant_id, AiLog.mode == "tool").all()}
        listing = db.get(Listing, probe_tenant["listing_id"])
        risk_written = listing.risk_level
    finally:
        db.close()
    assert {"tool:product.get_products", "tool:listing.get_listings",
            "tool:knowledge.search"} <= actions, (
        "compliance 的读取没有全部走 Tool 层——§18.3 第 2 步的迁移被回退了？"
        "实际审计到的 Tool 调用：%s" % sorted(actions))
    # 反向断言：`_sync_listing_risk` 的回写必须仍然生效——它是 §18.3 第 3 步的欠账，
    # 但在迁移期间不得被顺手删掉（删掉等于「高风险 Listing 可发布」）。
    assert risk_written == listing_report["risk_level"]


def test_support_agent_reads_go_through_tool_layer(client):
    """判别力：support 的会话/订单读取必须留下 `mode=tool` 审计（§18.3 第 2 步）。

    自带探针租户（会话 + 买家消息 + 订单），夹具内建内删：不依赖演示数据，
    不给后续用例制造隐含前提（规范 T-2）。审计行与知识候选都是 `tenants` 的
    外键子表，必须一并回收，否则删不掉租户。参数 `client` 只为拉起会话级建库
    夹具（T-2：单跑本用例时也要有表结构，不能靠同文件其它用例先跑）。
    """
    from app.agents.support import SupportAgent
    from app.db import SessionLocal
    from app.models import AiLog, Conversation, KnowledgeCandidate, Message, Order, Tenant

    db = SessionLocal()
    try:
        tenant = Tenant(name="ToolLayer客服探针租户")
        db.add(tenant)
        db.commit()
        order = Order(tenant_id=tenant.id, platform="shopee", external_no="TOOL-SUPPORT-1",
                      status="paid", qty=2)
        db.add(order)
        db.commit()
        conv = Conversation(tenant_id=tenant.id, platform="shopee", buyer_name="探针买家",
                            order_id=order.id, status="open")
        db.add(conv)
        db.commit()
        db.add(Message(tenant_id=tenant.id, conversation_id=conv.id, role="buyer",
                       content="我的订单什么时候发货？", intent="order_status"))
        db.commit()
        ids = {"tenant_id": tenant.id, "order_id": order.id, "conversation_id": conv.id}
    finally:
        db.close()

    try:
        agent = SupportAgent(ids["tenant_id"])
        try:
            out = agent.auto_reply(ids["conversation_id"])
        finally:
            agent.close()
        assert out["conversation_id"] == ids["conversation_id"] and out["auto"] is True

        db = SessionLocal()
        try:
            actions = {r.action for r in db.query(AiLog)
                       .filter(AiLog.tenant_id == ids["tenant_id"],
                               AiLog.mode == "tool").all()}
        finally:
            db.close()
        assert {"tool:conversation.get_conversations", "tool:order.get_orders"} <= actions, (
            "support 的读取没有全部走 Tool 层——§18.3 第 2 步的迁移被回退了？"
            "实际审计到的 Tool 调用：%s" % sorted(actions))
    finally:
        db = SessionLocal()
        try:
            db.query(AiLog).filter(AiLog.tenant_id == ids["tenant_id"]).delete()
            db.query(KnowledgeCandidate).filter(
                KnowledgeCandidate.tenant_id == ids["tenant_id"]).delete()
            db.query(Message).filter(Message.tenant_id == ids["tenant_id"]).delete()
            db.query(Conversation).filter(Conversation.id == ids["conversation_id"]).delete()
            db.query(Order).filter(Order.id == ids["order_id"]).delete()
            db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
            db.commit()
        finally:
            db.close()


def test_listing_agent_reads_go_through_tool_layer(client):
    """判别力：listing 的商品/Listing/规则/知识/合规读取必须留下 `mode=tool` 审计。

    自带探针租户（商品带图 + Listing + 合规报告），夹具内建内删（规范 T-2）：
    不依赖演示数据，不给后续用例制造隐含前提。参数 `client` 只为拉起会话级建库
    夹具（T-2：单跑本用例时也要有表结构，不能靠同文件其它用例先跑）。
    """
    from app.agents.listing import ListingAgent
    from app.db import SessionLocal
    from app.models import AiLog, ComplianceReport, Listing, Product, Tenant

    db = SessionLocal()
    try:
        tenant = Tenant(name="ToolLayer上架探针租户")
        db.add(tenant)
        db.commit()
        product = Product(tenant_id=tenant.id, sku="TOOL-LISTING-1",
                          title="Tool Layer 上架探针商品", category="家居",
                          images=["https://cdn.example.com/probe.jpg"],
                          attrs={"material": "cotton", "color": "blue"})
        db.add(product)
        db.commit()
        listing = Listing(tenant_id=tenant.id, product_id=product.id, platform="shopee",
                          language="en", title="Tool Layer 上架探针 Listing",
                          description="probe listing", bullets=["bullet"],
                          keywords=["probe"], status="draft")
        db.add(listing)
        db.commit()
        db.add(ComplianceReport(tenant_id=tenant.id, target_type="listing",
                                listing_id=listing.id, risk_level="low", score=90))
        db.commit()
        ids = {"tenant_id": tenant.id, "product_id": product.id, "listing_id": listing.id}
    finally:
        db.close()

    try:
        agent = ListingAgent(ids["tenant_id"])
        try:
            opt = agent.optimize(ids["listing_id"])
            pub = agent.publish(ids["listing_id"])
        finally:
            agent.close()
        assert opt["id"] == ids["listing_id"]
        assert opt["status"] == "PROPOSED"
        assert opt["_action_proposal"]["action_type"] == "UPDATE_LISTING_CONTENT"
        assert pub["status"] == "PROPOSED"
        assert pub["_action_proposal"]["action_type"] == "PUBLISH_LISTING"

        db = SessionLocal()
        try:
            actions = {r.action for r in db.query(AiLog)
                       .filter(AiLog.tenant_id == ids["tenant_id"],
                               AiLog.mode == "tool").all()}
            row = db.get(Listing, ids["listing_id"])
            status_after, title_after = row.status, row.title
        finally:
            db.close()
        expected = {"tool:product.get_products", "tool:listing.get_listings",
                    "tool:knowledge.search", "tool:compliance.get_platform_rules",
                    "tool:compliance.check_listing"}
        assert expected <= actions, (
            "listing 的读取没有全部走 Tool 层——§18.3 第 2 步的迁移被回退了？缺失：%s"
            % sorted(expected - actions))
        # 两个 Agent 方法都只能提案，不能产生任何 Listing 业务副作用。
        assert status_after == "draft" and title_after == "Tool Layer 上架探针 Listing"
    finally:
        db = SessionLocal()
        try:
            db.query(AiLog).filter(AiLog.tenant_id == ids["tenant_id"]).delete()
            db.query(ComplianceReport).filter(
                ComplianceReport.tenant_id == ids["tenant_id"]).delete()
            db.query(Listing).filter(Listing.id == ids["listing_id"]).delete()
            db.query(Product).filter(Product.id == ids["product_id"]).delete()
            db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
            db.commit()
        finally:
            db.close()


def test_listing_review_agent_reads_go_through_tool_layer(client):
    """判别力：listing_review 的 Listing/商品/规则/合规读取必须留下 `mode=tool` 审计。

    自带探针租户（带图商品 + Listing + 低风险合规报告 + 当日版本规则包），夹具内建
    内删（规范 T-2）：不依赖演示数据。参数 `client` 只为拉起会话级建库夹具（单跑本
    用例也要有表结构）。规则包刻意用「当前日期版本 + 探针平台名」：内置规则包版本
    会随日期推移触发 30 天新鲜度门禁（manual_required），把断言押在「今天恰好
    approved」上等于埋定时炸弹（规范 §8 T-8）。
    """
    from datetime import datetime

    from app.agents.listing_review import ListingReviewAgent
    from app.db import SessionLocal
    from app.models import (
        AiLog,
        ComplianceReport,
        Listing,
        ListingReviewDecision,
        PlatformRulePack,
        Product,
        Tenant,
    )

    platform = "probe_review"
    db = SessionLocal()
    try:
        tenant = Tenant(name="ToolLayer复核探针租户")
        db.add(tenant)
        db.commit()
        product = Product(tenant_id=tenant.id, sku="TOOL-REVIEW-1",
                          title="Tool Layer 复核探针商品", category="家居",
                          images=["https://cdn.example.com/probe.jpg"])
        db.add(product)
        db.commit()
        listing = Listing(tenant_id=tenant.id, product_id=product.id, platform=platform,
                          language="en", title="Tool Layer 复核探针 Listing",
                          description="probe listing", bullets=["bullet"],
                          keywords=["probe"], status="draft")
        db.add(listing)
        db.commit()
        db.add_all([
            ComplianceReport(tenant_id=tenant.id, target_type="listing",
                             listing_id=listing.id, risk_level="low", score=90),
            PlatformRulePack(platform=platform,
                             version=datetime.utcnow().strftime("%Y-%m-%d"),
                             rules={"title_max": 200, "desc_max": 3000, "image_min": 1,
                                    "banned_words": [], "banned_categories": []},
                             source_url="https://example.com/probe-rules"),
        ])
        db.commit()
        ids = {"tenant_id": tenant.id, "product_id": product.id, "listing_id": listing.id}
    finally:
        db.close()

    try:
        agent = ListingReviewAgent(ids["tenant_id"])
        try:
            result = agent.review(ids["listing_id"])
        finally:
            agent.close()
        # 规则源齐备（origin=db、来源 URL、当日版本）、低风险报告、无违规 →
        # 必须走 approved 成功分支；manual_required 说明规则源判读被改坏。
        assert result["decision"] == "approved", result["reasons"]

        db = SessionLocal()
        try:
            actions = {r.action for r in db.query(AiLog)
                       .filter(AiLog.tenant_id == ids["tenant_id"],
                               AiLog.mode == "tool").all()}
            rows = db.query(ListingReviewDecision).filter(
                ListingReviewDecision.tenant_id == ids["tenant_id"]).all()
            decision_rows = [(r.listing_id, r.decision, bool(r.human_override))
                             for r in rows]
        finally:
            db.close()
        expected = {"tool:listing.get_listings", "tool:product.get_products",
                    "tool:compliance.get_platform_rules", "tool:compliance.check_listing",
                    "tool:compliance.get_review_decisions"}
        assert expected <= actions, (
            "listing_review 的读取没有全部走 Tool 层——§18.3 第 2 步的迁移被回退了？缺失：%s"
            % sorted(expected - actions))
        # 反向断言：写路径（复核结论落库）必须仍然生效——它是第 3 步欠账，
        # 迁移期间不得被顺手删掉（删掉等于「复核点了没反应」）。
        assert decision_rows == [(ids["listing_id"], "approved", False)], decision_rows
    finally:
        db = SessionLocal()
        try:
            db.query(AiLog).filter(AiLog.tenant_id == ids["tenant_id"]).delete()
            db.query(ListingReviewDecision).filter(
                ListingReviewDecision.tenant_id == ids["tenant_id"]).delete()
            db.query(ComplianceReport).filter(
                ComplianceReport.tenant_id == ids["tenant_id"]).delete()
            db.query(Listing).filter(Listing.id == ids["listing_id"]).delete()
            db.query(Product).filter(Product.id == ids["product_id"]).delete()
            db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
            db.query(PlatformRulePack).filter(
                PlatformRulePack.platform == platform).delete()
            db.commit()
        finally:
            db.close()


def test_listing_publish_blocks_rule_violation(client):
    """反向断言：发布门禁必须拦下违规文案（迁到字段级核心后语义不变）。

    shopee 内置规则包禁用「no.1」，标题命中即拒绝，且拒绝后状态必须保持 draft
    ——先写后拦等于门禁失效。同时守住 `validate_listing_fields` 的核心判定：
    若它被改坏成「永远返回空清单」，本用例立刻红。
    """
    from app.agents.listing import ListingAgent
    from app.db import SessionLocal
    from app.models import AiLog, Listing, Product, Tenant

    db = SessionLocal()
    try:
        tenant = Tenant(name="ToolLayer规则门禁探针租户")
        db.add(tenant)
        db.commit()
        product = Product(tenant_id=tenant.id, sku="TOOL-RULE-1",
                          title="Tool Layer 规则门禁商品", category="家居",
                          images=["https://cdn.example.com/probe.jpg"], attrs={})
        db.add(product)
        db.commit()
        listing = Listing(tenant_id=tenant.id, product_id=product.id, platform="shopee",
                          language="en", title="Best no.1 Seller 探针 Listing",
                          description="probe", bullets=["bullet"], keywords=["probe"],
                          status="draft")
        db.add(listing)
        db.commit()
        ids = {"tenant_id": tenant.id, "product_id": product.id, "listing_id": listing.id}
    finally:
        db.close()

    try:
        agent = ListingAgent(ids["tenant_id"])
        try:
            with pytest.raises(ValueError, match="平台规则校验未通过"):
                agent.publish(ids["listing_id"])
        finally:
            agent.close()

        db = SessionLocal()
        try:
            status = db.get(Listing, ids["listing_id"]).status
        finally:
            db.close()
        assert status == "draft", "被规则拦下的 Listing 不得发生任何写入（先写后拦=门禁失效）"
    finally:
        db = SessionLocal()
        try:
            db.query(AiLog).filter(AiLog.tenant_id == ids["tenant_id"]).delete()
            db.query(Listing).filter(Listing.id == ids["listing_id"]).delete()
            db.query(Product).filter(Product.id == ids["product_id"]).delete()
            db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
            db.commit()
        finally:
            db.close()


def test_supplier_agent_reads_go_through_tool_layer(client):
    """判别力：supplier 的报价/供应商/商品/销量读取必须留下 `mode=tool` 审计。

    自带探针租户（商品 + 两个供应商 + 在库报价 + 近 12 周订单），夹具内建内删
    （规范 T-2）。参数 `client` 只为拉起会话级建库夹具（单跑本用例也要有表）。
    """
    from datetime import datetime, timedelta

    from app.agents.supplier import SupplierAgent
    from app.db import SessionLocal
    from app.models import (
        AiLog,
        ForecastSnapshot,
        Order,
        Product,
        Supplier,
        SupplierOffer,
        SupplierScore,
        Tenant,
    )

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        tenant = Tenant(name="ToolLayer供应链探针租户")
        db.add(tenant)
        db.commit()
        product = Product(tenant_id=tenant.id, sku="TOOL-SUPPLY-1",
                          title="Tool Layer 供应链探针商品", status="active",
                          attrs={"onhand": 10, "sale_price": 19.9})
        dear = Supplier(tenant_id=tenant.id, name="探针供应商甲", region="深圳",
                        rating=4.5, ship_days=3, stability=90.0)
        cheap = Supplier(tenant_id=tenant.id, name="探针供应商乙", region="义乌",
                         rating=3.0, ship_days=9, stability=60.0)
        db.add_all([product, dear, cheap])
        db.commit()
        db.add_all([
            SupplierOffer(tenant_id=tenant.id, supplier_id=dear.id, product_id=product.id,
                          price=12.0, currency="CNY", moq=10, ship_days=3, in_stock=True),
            SupplierOffer(tenant_id=tenant.id, supplier_id=cheap.id, product_id=product.id,
                          price=9.0, currency="CNY", moq=50, ship_days=9, in_stock=True),
        ])
        for days_ago, qty in ((7, 20), (14, 15), (21, 5)):
            db.add(Order(tenant_id=tenant.id, platform="shopee",
                         external_no="TOOL-SUP-%d" % days_ago, product_id=product.id,
                         qty=qty, amount=100.0, currency="USD", status="paid",
                         source="api", created_at=now - timedelta(days=days_ago)))
        db.commit()
        ids = {"tenant_id": tenant.id, "product_id": product.id, "supplier_id": dear.id}
    finally:
        db.close()

    try:
        agent = SupplierAgent(ids["tenant_id"])
        try:
            best = agent.match_best(ids["product_id"])
            score = agent.score_supplier(ids["supplier_id"])
            fc = agent.forecast(ids["product_id"])
        finally:
            agent.close()
        # 综合分：乙 = 0.4×100(价) + 0.3×28(时效) + 0.3×60(口碑) = 66.4 > 甲 49.8。
        # 口径写死在这里是刻意的：分项权重若被改动，本断言立刻红。
        assert best["supplier"]["id"] != ids["supplier_id"], "低价侧报价应胜出"
        assert best["offer"]["price"] == 9.0
        assert best["supplier"]["name"] == "探针供应商乙"
        assert score["total"] > 0
        assert fc["product_id"] == ids["product_id"]

        db = SessionLocal()
        try:
            actions = {r.action for r in db.query(AiLog)
                       .filter(AiLog.tenant_id == ids["tenant_id"],
                               AiLog.mode == "tool").all()}
            score_rows = db.query(SupplierScore).filter(
                SupplierScore.tenant_id == ids["tenant_id"]).count()
            snap_rows = db.query(ForecastSnapshot).filter(
                ForecastSnapshot.tenant_id == ids["tenant_id"]).count()
        finally:
            db.close()
        expected = {"tool:supply.get_supplier_offers", "tool:supply.search_suppliers",
                    "tool:supply.get_offer_stats", "tool:product.get_products",
                    "tool:order.get_daily_sales"}
        assert expected <= actions, (
            "supplier 的读取没有全部走 Tool 层——§18.3 第 2 步的迁移被回退了？缺失：%s"
            % sorted(expected - actions))
        # 反向断言：两处写路径（评分快照 / 预测快照）必须仍然落库——它们是第 3 步欠账，
        # 迁移期间不得被顺手删掉（删掉等于「评分/预测点了没反应」）。
        assert score_rows == 1 and snap_rows == 1
    finally:
        db = SessionLocal()
        try:
            db.query(AiLog).filter(AiLog.tenant_id == ids["tenant_id"]).delete()
            db.query(SupplierScore).filter(
                SupplierScore.tenant_id == ids["tenant_id"]).delete()
            db.query(ForecastSnapshot).filter(
                ForecastSnapshot.tenant_id == ids["tenant_id"]).delete()
            db.query(SupplierOffer).filter(
                SupplierOffer.tenant_id == ids["tenant_id"]).delete()
            db.query(Order).filter(Order.tenant_id == ids["tenant_id"]).delete()
            db.query(Supplier).filter(Supplier.tenant_id == ids["tenant_id"]).delete()
            db.query(Product).filter(Product.id == ids["product_id"]).delete()
            db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
            db.commit()
        finally:
            db.close()


def test_factory_opportunity_agent_reads_go_through_tool_layer(client):
    """判别力：factory_opportunity 的私域目录/商品/预测读取必须留下 `mode=tool` 审计。

    自带探针租户（商品 + 已尽调供应商 + 活跃目录商品 + 高可信预测快照），夹具内建
    内删（规范 T-2）。参数 `client` 只为拉起会话级建库夹具（单跑本用例也要有表）。
    """
    from datetime import datetime, timedelta

    from app.agents.factory_opportunity import FactoryOpportunityAgent
    from app.db import SessionLocal
    from app.models import (
        AiLog,
        ForecastSnapshot,
        OpportunitySupplierMatch,
        Product,
        Supplier,
        SupplierCatalogProduct,
        SupplierOffer,
        Tenant,
    )

    db = SessionLocal()
    try:
        tenant = Tenant(name="ToolLayer工厂机会探针租户")
        db.add(tenant)
        db.commit()
        product = Product(tenant_id=tenant.id, sku="TOOL-FACTORY-1",
                          title="Tool Layer 工厂机会探针商品", category="家居",
                          attrs={"sale_price": 29.9, "material": "cotton"})
        db.add(product)
        db.commit()
        supplier = Supplier(tenant_id=tenant.id, name="探针私域工厂",
                            verification_status="verified",
                            capabilities=["cotton", "家居"])
        db.add(supplier)
        db.commit()
        catalog = SupplierCatalogProduct(
            tenant_id=tenant.id, supplier_id=supplier.id, factory_sku="F-1",
            title="Tool Layer 工厂机会探针商品", category="家居",
            capabilities=["cotton", "家居"], images=["https://cdn.example.com/f.jpg"],
            unit_price=30.0, currency="CNY", moq=10, lead_days=5,
            monthly_capacity=1000, available_qty=500, status="active",
            confirmed_at=datetime.utcnow() - timedelta(days=1))
        db.add(catalog)
        db.commit()
        db.add(ForecastSnapshot(tenant_id=tenant.id, product_id=product.id,
                                version="probe-1",
                                training_cutoff=datetime.utcnow() - timedelta(days=1),
                                selected_model="probe", point_forecast=50.0,
                                confidence="high"))
        db.commit()
        ids = {"tenant_id": tenant.id, "product_id": product.id,
               "supplier_id": supplier.id, "catalog_id": catalog.id}
    finally:
        db.close()

    try:
        agent = FactoryOpportunityAgent(ids["tenant_id"])
        try:
            result = agent.scan_private_supply_batch({"product_ids": [ids["product_id"]]})
        finally:
            agent.close()
        assert len(result["candidates"]) == 1, result
        assert result["candidates"][0]["score"] > 0

        db = SessionLocal()
        try:
            actions = {r.action for r in db.query(AiLog)
                       .filter(AiLog.tenant_id == ids["tenant_id"],
                               AiLog.mode == "tool").all()}
            match_rows = db.query(OpportunitySupplierMatch).filter(
                OpportunitySupplierMatch.tenant_id == ids["tenant_id"]).count()
            offer_rows = db.query(SupplierOffer).filter(
                SupplierOffer.tenant_id == ids["tenant_id"]).count()
        finally:
            db.close()
        expected = {"tool:supply.get_catalog_products", "tool:product.get_products",
                    "tool:supply.get_forecast_snapshot"}
        assert expected <= actions, (
            "factory_opportunity 的读取没有全部走 Tool 层——§18.3 第 2 步的迁移被回退了？缺失：%s"
            % sorted(expected - actions))
        # 反向断言：两处写路径（匹配快照 / 报价 upsert）必须仍然生效——它们是
        # 第 3 步欠账，迁移期间不得被顺手删掉（删掉等于「扫描点了没反应」）。
        assert match_rows == 1 and offer_rows == 1
    finally:
        db = SessionLocal()
        try:
            db.query(AiLog).filter(AiLog.tenant_id == ids["tenant_id"]).delete()
            db.query(OpportunitySupplierMatch).filter(
                OpportunitySupplierMatch.tenant_id == ids["tenant_id"]).delete()
            db.query(SupplierOffer).filter(
                SupplierOffer.tenant_id == ids["tenant_id"]).delete()
            db.query(ForecastSnapshot).filter(
                ForecastSnapshot.tenant_id == ids["tenant_id"]).delete()
            db.query(SupplierCatalogProduct).filter(
                SupplierCatalogProduct.tenant_id == ids["tenant_id"]).delete()
            db.query(Product).filter(Product.id == ids["product_id"]).delete()
            db.query(Supplier).filter(Supplier.id == ids["supplier_id"]).delete()
            db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
            db.commit()
        finally:
            db.close()


def test_pricing_and_ads_agents_reads_go_through_tool_layer(client):
    """判别力：pricing / ads 两个 Agent 的读取必须留下 `mode=tool` 审计。

    自带探针租户（商品 + 机会评分 + 已发布 Listing + 在投广告），夹具内建内删
    （规范 T-2）。覆盖定价侧（`suggest_price` / `reprice_batch`）与广告侧
    （`roi_report` / `draft_batch` / `optimize_budget`）。参数 `client` 只为拉起
    会话级建库夹具（单跑本用例也要有表结构）。
    """
    from app.agents.pricing import AdsAgent, PricingAgent
    from app.db import SessionLocal
    from app.models import (
        AdCampaign,
        AiLog,
        Listing,
        PricingRecord,
        Product,
        ProductScore,
        Tenant,
    )

    db = SessionLocal()
    try:
        tenant = Tenant(name="ToolLayer定价广告探针租户")
        db.add(tenant)
        db.commit()
        product = Product(tenant_id=tenant.id, sku="TOOL-PRICING-1",
                          title="Tool Layer 定价探针商品", category="家居",
                          status="active",
                          attrs={"sale_price": 29.9, "color": "blue", "weight_kg": 0.3})
        db.add(product)
        db.commit()
        db.add_all([
            ProductScore(tenant_id=tenant.id, product_id=product.id,
                         demand=70, competition=40, profit=65, risk=20, total=72),
            Listing(tenant_id=tenant.id, product_id=product.id, platform="shopee",
                    language="en", title="Tool Layer 定价探针 Listing",
                    status="published"),
            AdCampaign(tenant_id=tenant.id, name="探针在投广告", platform="facebook",
                       product_id=product.id, keywords=["probe"], budget=50.0,
                       spend=10.0, revenue=50.0, impressions=1000, clicks=50,
                       orders=5, status="running"),
        ])
        db.commit()
        campaign_id = db.query(AdCampaign).filter(
            AdCampaign.tenant_id == tenant.id).one().id
        ids = {"tenant_id": tenant.id, "product_id": product.id,
               "campaign_id": campaign_id}
    finally:
        db.close()

    try:
        pricing = PricingAgent(ids["tenant_id"])
        try:
            quote = pricing.suggest_price(ids["product_id"])
            repriced = pricing.reprice_batch()
        finally:
            pricing.close()
        assert quote["suggested_price"] > 0
        assert repriced["repriced"], "reprice_batch 应至少复价 1 个活跃商品"

        ads = AdsAgent(ids["tenant_id"])
        try:
            report = ads.roi_report()
            drafts = ads.draft_batch()
            budget = ads.optimize_budget(ids["campaign_id"])
        finally:
            ads.close()
        # ROI=(50-10)/10=4 > 2 → 加预算 30%：50 → 65。口径写死在这里是刻意的。
        assert report["summary"]["total_spend"] == 10.0
        assert report["campaigns"][0]["roi"] == 4.0
        assert drafts["campaign_drafts"], "draft_batch 应从已发布 Listing 回退取商品"
        assert budget["action"] == "加预算", budget

        db = SessionLocal()
        try:
            actions = {r.action for r in db.query(AiLog)
                       .filter(AiLog.tenant_id == ids["tenant_id"],
                               AiLog.mode == "tool").all()}
            pricing_rows = db.query(PricingRecord).filter(
                PricingRecord.tenant_id == ids["tenant_id"]).count()
            draft_rows = db.query(AdCampaign).filter(
                AdCampaign.tenant_id == ids["tenant_id"],
                AdCampaign.status == "draft").count()
            budget_after = db.get(AdCampaign, ids["campaign_id"]).budget
        finally:
            db.close()
        expected = {"tool:product.get_products", "tool:market.score_opportunity",
                    "tool:finance.get_unit_economics", "tool:product.get_product_ids",
                    "tool:listing.get_published_product_ids", "tool:finance.get_campaigns"}
        assert expected <= actions, (
            "pricing/ads 的读取没有全部走 Tool 层——§18.3 第 2 步的迁移被回退了？缺失：%s"
            % sorted(expected - actions))
        # 预算优化现在只提出 HIGH 风险建议，不能由 Agent 直接落库。
        assert pricing_rows == 0, "PricingAgent 只输出分析，不能直接持久化记录"
        assert "_analysis_record" in quote and "_action_proposal" not in quote
        assert draft_rows == 0 and budget["new_budget"] == 65.0
        assert drafts["campaign_drafts"][0]["_action_proposal"]["action_type"] == "CREATE_AD_CAMPAIGN_DRAFT"
        assert budget_after == 50.0, "Agent 不能直接修改广告预算"
    finally:
        db = SessionLocal()
        try:
            db.query(AiLog).filter(AiLog.tenant_id == ids["tenant_id"]).delete()
            db.query(PricingRecord).filter(
                PricingRecord.tenant_id == ids["tenant_id"]).delete()
            db.query(AdCampaign).filter(
                AdCampaign.tenant_id == ids["tenant_id"]).delete()
            db.query(Listing).filter(Listing.tenant_id == ids["tenant_id"]).delete()
            db.query(ProductScore).filter(
                ProductScore.tenant_id == ids["tenant_id"]).delete()
            db.query(Product).filter(Product.id == ids["product_id"]).delete()
            db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
            db.commit()
        finally:
            db.close()


def test_orchestrator_reads_go_through_tool_layer(probe_tenant):
    """判别力：orchestrator 的经营概况/铺货/客服/供应商读取必须留下 `mode=tool` 审计。

    为什么断言审计行而不是返回值：把实现改回 `self.db.query(...)` 时返回值几乎
    相同（同一批数据），只有审计行会消失——没有这条，「已迁移」就只能靠人工看
    代码（T-55）。
    """
    from app.agents.orchestrator import OrchestratorAgent
    from app.db import SessionLocal
    from app.models import AiLog

    tenant_id = probe_tenant["tenant_id"]
    agent = OrchestratorAgent(tenant_id)
    try:
        bi = agent.chat("经营情况")
        listing = agent.chat("铺货建议")
        support = agent.chat("客服消息")
        supplier = agent.chat("供应商评分")
    finally:
        agent.close()
    assert bi["intent"] == "bi" and listing["intent"] == "listing"
    assert support["intent"] == "support" and supplier["intent"] == "supplier"
    assert listing["data"]["draft_listings"] == 1, listing
    assert bi["data"]["orders"] == 0, bi

    db = SessionLocal()
    try:
        actions = {r.action for r in db.query(AiLog)
                   .filter(AiLog.tenant_id == tenant_id, AiLog.mode == "tool").all()}
        chat_logs = db.query(AiLog).filter(
            AiLog.tenant_id == tenant_id, AiLog.agent == "orchestrator",
            AiLog.action == "chat").count()
    finally:
        db.close()
    expected = {"tool:order.get_sales_summary", "tool:finance.get_campaign_totals",
                "tool:product.count_products", "tool:listing.count_listings",
                "tool:conversation.count_conversations", "tool:supply.search_suppliers"}
    assert expected <= actions, (
        "orchestrator 的读取没有全部走 Tool 层——§18.3 第 2 步的迁移被回退了？"
        "缺失：%s" % sorted(expected - actions))
    # 反向断言：chat 的 AiLog 写路径（第 3 步欠账）必须仍然生效——删掉等于对话
    # 不再留痕。
    assert chat_logs == 4, chat_logs


def test_discovery_reads_go_through_tool_layer(probe_tenant):
    """选品与标准化的读取必须产生 Tool 审计；写路径仍能正常落库。"""
    from app.agents.discovery import DiscoveryAgent, ProductAgent
    from app.db import SessionLocal
    from app.models import AiLog

    tenant_id = probe_tenant["tenant_id"]
    product_id = probe_tenant["product_id"]
    with DiscoveryAgent(tenant_id) as agent:
        sold = agent.tool("product").call("get_sold_product_ids")
        assert sold.ok and product_id in sold.data, "卖出 1 件的商品必须算已有销量"
        agent.scan_trends()
        score = agent.score_product(product_id)
        picked = agent.pick_candidates(limit=1, min_total=0, explore=False)
    with ProductAgent(tenant_id) as agent:
        standardized = agent.standardize(product_id)

    assert score["product_id"] == product_id
    assert picked["picked_product_ids"] == [product_id]
    assert standardized["dedupe_hash"]
    db = SessionLocal()
    try:
        actions = {row.action for row in db.query(AiLog).filter(
            AiLog.tenant_id == tenant_id, AiLog.mode == "tool").all()}
    finally:
        db.close()
    expected = {"tool:product.get_categories", "tool:product.get_products",
                "tool:product.count_products", "tool:product.get_latest_performance",
                "tool:product.get_product_ids", "tool:product.find_duplicate",
                "tool:market.get_trends", "tool:market.get_latest_scores"}
    assert expected <= actions, "discovery 读取未全部经 Tool：%s" % sorted(expected - actions)


def test_read_methods_reject_bad_params_without_touching_db(recorded, legacy_ctx):
    """参数校验必须是 BAD_PARAM，而不是把脏值送进查询后炸成 INTERNAL。

    `db=None` 让「已进入实现」这件事变得可观测：若校验没拦住，错误码会变成
    INTERNAL（实现里访问 None 报错）而不是 BAD_PARAM。
    """
    cases = [
        ("product", "get_products", {"limit": -1}),
        ("product", "get_products", {"limit": "abc"}),
        ("product", "analyze_product", {"product_id": "abc"}),
        ("order", "analyze_sales", {"days": 0}),
        ("store", "get_store_metrics", {"days": "x"}),
            ("supply", "get_supplier_offers", {"supplier_id": "abc"}),
            ("order", "get_orders", {"shop_id": "abc"}),
            ("knowledge", "search", {"query": "   "}),
        ("knowledge", "search", {"query": "x", "top_k": 999}),
        ("conversation", "count_conversations", {"status": "bogus"}),
        ("listing", "count_listings", {"status": "bogus"}),
        ("product", "get_sold_product_ids", {"min_units": -1}),
        ("product", "find_duplicate", {"dedupe_hash": "   "}),
        ("product", "get_latest_performance", {"product_id": "abc"}),
        ("order", "get_sales_summary", {"days": 0}),
    ]
    for tool_name, method, params in cases:
        result = registry.open_tool(tool_name, legacy_ctx, db=None).call(method, **params)
        assert result.ok is False, "%s.%s 应被拒绝" % (tool_name, method)
        assert result.error["code"] == ERR_BAD_PARAM, (
            "%s.%s 参数校验未生效：%s" % (tool_name, method, result.error))


# ---------------------------------------------------------------- 分层红线 L-7

def _imports_agents(module: str) -> bool:
    """模块路径中任一段等于 `agents` 即算越层（覆盖 `..agents` 与 `app.agents.x`）。"""
    return "agents" in (module or "").split(".")


def _iter_agent_imports(source: str) -> list:
    """返回源码中 import `agents` 的行号（AST，**含函数体内延迟 import**）。

    用 AST 而不是只扫顶层 import：DEBT-28 的教训是违规恰好藏在方法体内的延迟
    import 里，只扫顶层的写法看不见它。
    """
    import ast

    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if _imports_agents(node.module):
                lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _imports_agents(alias.name):
                    lines.append(node.lineno)
    return lines


def test_tools_never_import_agents():
    """L-7：`tools/` 禁止 import `agents/`。

    依赖方向是 `routers -> agents -> tools -> services -> models`。反向 import 会
    成环，并让 Tool 层无法脱离 Agent 独立测试——而「能独立测试」正是它作为
    Agent 唯一数据通道的前提。
    """
    offenders = []
    for path in sorted((BACKEND_DIR / "app" / "tools").glob("*.py")):
        for lineno in _iter_agent_imports(path.read_text(encoding="utf-8")):
            offenders.append("%s:%d" % (path.name, lineno))
    assert not offenders, "tools/ 反向依赖 agents/：" + ", ".join(offenders)


def test_agent_import_detector_has_discriminating_power():
    """判别力：检测器必须能抓到真实形态的越层 import，含**函数体内**的那种。"""
    top_level = "from ..agents import discovery\n"
    lazy = "def f():\n    from app.agents.discovery import DiscoveryAgent\n"
    absolute = "import app.agents.listing\n"
    clean = "from ..services.costing import calc_profit\n"
    assert _iter_agent_imports(top_level) == [1]
    assert _iter_agent_imports(lazy) == [2]
    assert _iter_agent_imports(absolute) == [1]
    assert _iter_agent_imports(clean) == []
