"""Listing 提案、审批执行与工作流断点恢复的闭环验证。"""

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.db import SessionLocal
from app.models import AiAction, Listing, PlatformRulePack, User, WorkflowTemplate
from app.services.platform_rules import DEFAULT_RULE_PACKS

from .action_helpers import approve_and_execute


@pytest.fixture
def _fresh_rule_pack():
    """发布链测试不应被「内置规则包超过 30 天未更新」策略影响。

    这是**时间函数**：内置包版本写死（2026-09-19），一旦系统日期走过 30 天，
    所有发布都会被判 manual_required 并 409——测试会在某天集体变红而与代码无关。
    过期策略本身由 test_stale_rule_pack_blocks_publish 单独锁定。
    仅发布链测试显式请求本夹具（纯函数测试不需要数据库）。
    """
    base = DEFAULT_RULE_PACKS["shopee"]

    def _seed(version: str, updated_at=None):
        with SessionLocal() as db:
            db.query(PlatformRulePack).filter(PlatformRulePack.platform == "shopee").delete()
            db.add(PlatformRulePack(
                tenant_id=None, platform="shopee", version=version,
                rules=base["rules"], source_url=base["source_url"],
                updated_at=updated_at or datetime.utcnow()))
            db.commit()

    _seed(datetime.utcnow().strftime("%Y-%m-%d"))
    yield _seed
    with SessionLocal() as db:
        db.query(PlatformRulePack).filter(PlatformRulePack.platform == "shopee").delete()
        db.commit()


def make_listing(client, headers):
    product = client.post("/api/products", headers=headers, json={
        "title": "Approval Desk Organizer", "category": "家居",
        "images": ["https://example.com/action.jpg"]})
    assert product.status_code == 200, product.text
    draft = client.post("/api/listings/generate", headers=headers,
                        json={"product_id": product.json()["id"], "platform": "shopee"})
    assert draft.status_code == 200, draft.text
    assert draft.json()["action_status"] == "SUCCESS" and draft.json()["status"] == "draft"
    return product.json()["id"], draft.json()["id"]


def test_listing_module_cannot_write_orm():
    source = Path(__file__).resolve().parents[1] / "app/agents/listing.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    forbidden = {"add", "add_all", "commit", "flush", "delete", "execute", "query", "get", "rollback"}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr in forbidden
             and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "db"]
    assert not calls, "Listing Agent 不能读取或写入 ORM，必须通过 Tool/提案"


# ---------------------------------------------------------------- 多语言 copy（D60）
def test_fallback_copy_supports_major_destination_languages():
    """覆盖 zh/ja/ko/de/fr/es/th/vi 八个目的国语种的 fallback 文案（D60）。

    之前只有 zh / en 两分支，日韩德法西泰越等目的国一律落进 en——卖到日本
    页面全是英文。本测试守护扩展不被回退。
    """
    from app.agents.listing import ListingAgent

    product = {"title": "测试商品", "category": "家居",
               "attrs": {"material": "棉", "color": "白", "scene": "客厅"}}
    for lang in ("zh", "ja", "ko", "de", "fr", "es", "th", "vi"):
        copy = ListingAgent._fallback_copy(product.__class__(), "shopee", lang, None) \
            if False else ListingAgent._localized_copy(
                lang, product["title"], "Test Product",
                product["attrs"]["material"], product["attrs"]["color"],
                product["attrs"]["scene"], "Hot Sale", product, None)
        assert copy[0], f"{lang} 标题为空"
        assert copy[1], f"{lang} 描述为空"
        assert len(copy[2]) >= 3, f"{lang} bullets 不足"
        assert len(copy[3]) >= 3, f"{lang} keywords 不足"
    # 未覆盖语种回退到 en
    en = ListingAgent._localized_copy("xx", "测试", "Test", "cotton", "white",
                                        "living room", "Hot Sale", product, None)
    assert "Upgrade your" in en[1], "未覆盖语种应回退到 en 模板"


# ---------------------------------------------------------------- 广告接口骨架（D60）
def test_advert_skeleton_raises_without_external_account():
    """广告 API 骨架：can_advert 默认 False，调用应显式抛错而非静默成功。"""
    from app.services.adapters.base import BaseAdapter, PlatformError

    assert BaseAdapter.can_advert is False
    assert BaseAdapter.advert_protocol_status == "planned"
    adapter = BaseAdapter.__new__(BaseAdapter)
    with pytest.raises(PlatformError, match="广告 API 未接入"):
        adapter.create_ad_campaign(product_id=1, daily_budget=10.0)
    with pytest.raises(PlatformError, match="广告状态查询未接入"):
        adapter.ad_campaign_status("cmp-1")


def test_pending_publish_does_not_change_listing_and_reuses_intent(
        client, auth_headers, _fresh_rule_pack):
    _, lid = make_listing(client, auth_headers)
    first = client.post(f"/api/listings/{lid}/publish", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "PENDING_APPROVAL"
    with SessionLocal() as db:
        assert db.get(Listing, lid).status == "draft"
    replay = client.post(f"/api/listings/{lid}/publish", headers=auth_headers)
    assert replay.json()["action_id"] == first.json()["action_id"]
    published = approve_and_execute(client, auth_headers, first.json())
    assert published["status"] == "published" and published["source"] == "local"
    replay = client.post(f"/api/listings/{lid}/publish", headers=auth_headers).json()
    assert replay["action_id"] == first.json()["action_id"] and replay["idempotent_replay"]
    optimized = client.post(f"/api/listings/{lid}/optimize", headers=auth_headers)
    assert optimized.status_code == 409, "已发布内容禁止 AI 自动覆盖"


def test_publication_rechecks_approved_content_and_preserves_failure_scene(
        client, auth_headers, _fresh_rule_pack):
    _, lid = make_listing(client, auth_headers)
    pending = client.post(f"/api/listings/{lid}/publish", headers=auth_headers).json()
    action_id = pending["action_id"]
    approved = client.post(f"/api/actions/{action_id}/approve", headers=auth_headers,
                           json={"note": "批准当前内容"})
    assert approved.status_code == 200
    edited = client.put(f"/api/listings/{lid}", headers=auth_headers,
                        json={"title": "Changed after approval", "description": "Changed",
                              "bullets": [], "keywords": []})
    assert edited.status_code == 200
    failed = client.post(f"/api/actions/{action_id}/execute", headers=auth_headers).json()
    assert failed["status"] == "FAILED" and failed["outcome"]["target_snapshot"]["status"] == "draft"
    with SessionLocal() as db:
        assert db.get(Listing, lid).external_id == ""
    assert client.post(f"/api/actions/{action_id}/execute", headers=auth_headers).status_code == 409


@pytest.mark.parametrize("reject", [False, True])
def test_workflow_pauses_before_publish_and_resumes_only_after_execution(
        client, auth_headers, _fresh_rule_pack, reject):
    pid, _ = make_listing(client, auth_headers)
    key = "action-rejection-probe" if reject else "action-approval-probe"
    with SessionLocal() as db:
        user = db.query(User).filter_by(username="admin").one()
        db.add(WorkflowTemplate(tenant_id=user.tenant_id, key=key, name="审批暂停探针", steps=[
            {"agent": "listing", "action": "generate_batch", "params": {"platform": "shopee"}},
            {"agent": "listing_review", "action": "review_batch"},
            {"agent": "listing", "action": "publish_batch"},
            {"agent": "listing", "action": "generate_batch", "params": {"platform": "shopee"}},
        ]))
        db.commit()
    started = client.post("/api/workflows/run", headers=auth_headers,
                          json={"template_key": key, "context": {"product_ids": [pid]}})
    assert started.status_code == 200, started.text
    run_id = started.json()["id"]
    detail = client.get(f"/api/workflows/runs/{run_id}", headers=auth_headers).json()
    assert detail["status"] == "blocked" and detail["steps"][2]["status"] == "blocked", (
        "工作流应在发布步暂停等待审批；实际 status=%s，各步=%s"
        % (detail["status"],
           [(s["status"], (s.get("error") or "")[:200]) for s in detail["steps"]]))
    assert detail["steps"][3]["status"] == "skipped"
    pending = detail["steps"][2]["output"]["pending"][0]
    action_id, lid = pending["action_id"], pending["id"]
    with SessionLocal() as db:
        count = db.query(AiAction).filter_by(action_type="PUBLISH_LISTING", target_id=lid).count()
        assert db.get(Listing, lid).status == "draft"
    premature = client.post(f"/api/workflows/runs/{run_id}/resume", headers=auth_headers).json()
    assert premature["status"] == "blocked"
    if reject:
        response = client.post(f"/api/actions/{action_id}/reject", headers=auth_headers,
                               json={"note": "不允许本次上架"})
        assert response.status_code == 200
    else:
        approve_and_execute(client, auth_headers, pending)
    resumed = client.post(f"/api/workflows/runs/{run_id}/resume", headers=auth_headers).json()
    assert resumed["status"] == ("blocked" if reject else "success"), resumed
    detail = client.get(f"/api/workflows/runs/{run_id}", headers=auth_headers).json()
    assert detail["steps"][0]["attempts"] == detail["steps"][1]["attempts"] == 1
    assert detail["steps"][3]["status"] == ("skipped" if reject else "success")
    with SessionLocal() as db:
        assert db.query(AiAction).filter_by(action_type="PUBLISH_LISTING", target_id=lid).count() == count
        assert db.get(Listing, lid).status == ("draft" if reject else "published")


def test_stale_rule_pack_blocks_publish_with_reason(client, auth_headers, _fresh_rule_pack):
    """规则包超过 30 天必须阻断发布并说明原因（不静默放行、不伪装成可上架）。

    这条锁定的是策略本身；其余发布链测试用新鲜规则包，避免「测试随时间腐烂」。
    """
    _, lid = make_listing(client, auth_headers)
    stale_version = (datetime.utcnow() - timedelta(days=45)).strftime("%Y-%m-%d")
    _fresh_rule_pack(stale_version, updated_at=datetime.utcnow() + timedelta(seconds=5))

    response = client.post(f"/api/listings/{lid}/publish", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert "平台规则已超过30天未更新" in response.json()["detail"]
    with SessionLocal() as db:
        assert db.get(Listing, lid).status == "draft", "阻断时不得改动 Listing"
        assert db.query(AiAction).filter_by(action_type="PUBLISH_LISTING", target_id=lid).count() == 0
