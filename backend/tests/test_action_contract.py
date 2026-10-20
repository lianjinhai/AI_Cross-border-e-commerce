"""S3：Action 契约对齐（「全部」筛选 / 分页总量 / 单条详情 / 回执 / 能力矩阵 / 启动恢复）。

背景：前端过去必须为每种状态各查一页再拼接，且动作类型默认写死 ADJUST_AD_BUDGET，
「全部」根本查不出来；能力边界只能靠按钮试错。这里把口径钉在服务端并逐条验证。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal
from app.models import AiAction, Product, Tenant, User
from app.services.action_policy import POLICIES
from app.services.action_system import (
    HANDLERS,
    execute_action,
    recover_stuck_actions,
    submit_action,
)
from app.services.workspace_context import resolve_workspace_context


def _admin_ctx(db):
    user = db.query(User).filter(User.username == "admin").one()
    return resolve_workspace_context(db, user), user


def _submit(db, ctx, agent, action_type, target_id, step, payload=None):
    proposal = {"action_type": action_type, "target_type": POLICIES[action_type].target_type,
                "target_id": target_id, "reason": f"S3 契约探针 {action_type}",
                "payload": payload or {}}
    return submit_action(db, ctx, agent, proposal, step)


def _make_product(client, headers, sku):
    r = client.post("/api/products", headers=headers, json={"sku": sku, "title": f"S3 {sku}"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_list_supports_all_types_all_status_and_total(client, auth_headers):
    """「全部」= 本人有权限的类型集合；总数与分页必须服务端给，前端不拼接。"""
    pid = _make_product(client, auth_headers, "S3-LIST-1")
    with SessionLocal() as db:
        ctx, _ = _admin_ctx(db)
        draft = _submit(db, ctx, "listing", "CREATE_LISTING_DRAFT", pid, "s3-all-1",
                        {"title": "S3 草稿", "description": "d", "platform": "shopee",
                         "language": "en", "bullets": ["b"], "keywords": ["k"]})
        content = _submit(db, ctx, "product", "UPDATE_PRODUCT_CONTENT", pid, "s3-all-2",
                          {"title": "S3 标准化标题"})
        ids = [draft.id, content.id]

    r = client.get("/api/actions", headers=auth_headers,
                   params={"action_type": "ALL", "status": "ALL", "page_size": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(ids).issubset({item["id"] for item in body["items"]})
    assert body["total"] >= len(ids)
    assert body["page_size"] == 200
    assert {item["action_type"] for item in body["items"]} >= {"CREATE_LISTING_DRAFT",
                                                              "UPDATE_PRODUCT_CONTENT"}

    # 分页：page_size=1 时每页 1 条，但 total 不变（不是「第一页条数」）。
    one = client.get("/api/actions", headers=auth_headers,
                     params={"action_type": "ALL", "status": "ALL",
                             "page_num": 1, "page_size": 1}).json()
    assert len(one["items"]) == 1 and one["total"] == body["total"] and one["page_num"] == 1

    # 旧参数 limit 仍可用（兼容既有调用），等价 page_size。
    legacy = client.get("/api/actions", headers=auth_headers,
                        params={"action_type": "ALL", "status": "ALL", "limit": 2}).json()
    assert len(legacy["items"]) == 2 and legacy["page_size"] == 2

    assert client.get("/api/actions", headers=auth_headers,
                      params={"action_type": "NOT_A_TYPE"}).status_code == 400
    assert client.get("/api/actions", headers=auth_headers,
                      params={"status": "NOPE"}).status_code == 400


def test_action_detail_and_result_are_queryable(client, auth_headers):
    """单条详情 + 独立回执：刷新/重进页面能恢复同一 Action，不依赖列表行数据。"""
    pid = _make_product(client, auth_headers, "S3-DETAIL-1")
    with SessionLocal() as db:
        ctx, _ = _admin_ctx(db)
        action = _submit(db, ctx, "listing", "CREATE_LISTING_DRAFT", pid, "s3-detail",
                         {"title": "S3 详情草稿", "description": "d", "platform": "shopee",
                          "language": "en", "bullets": ["b"], "keywords": ["k"]})
        action_id = action.id
        expected_permission = action.required_permission

    detail = client.get(f"/api/actions/{action_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["required_permission"] == expected_permission == "listing:write"
    assert body["agent_type"] == "listing"
    assert body["created_at"] and body["status"] == "APPROVED"

    result = client.get(f"/api/actions/{action_id}/result", headers=auth_headers).json()
    assert result["status"] == "APPROVED" and result["terminal"] is False

    with SessionLocal() as db:
        ctx, _ = _admin_ctx(db)
        executed = execute_action(db, ctx, action_id)
        assert executed.status == "SUCCESS"

    result = client.get(f"/api/actions/{action_id}/result", headers=auth_headers).json()
    assert result["terminal"] is True and result["outcome"], result
    assert result["executed_at"] and result["executed_by"]

    assert client.get("/api/actions/99999999", headers=auth_headers).status_code == 404
    assert client.get("/api/actions/99999999/result", headers=auth_headers).status_code == 404


def test_capability_matrix_reports_blocked_reasons(client, auth_headers):
    """能力矩阵以注册表为准：动作总数=策略表、执行器已注册、只读身份全阻断且给原因。"""
    body = client.get("/api/ai/capabilities", headers=auth_headers).json()
    assert body["summary"]["total"] == len(POLICIES)
    assert body["summary"]["registered_handlers"] == len(HANDLERS)
    assert {a["action_type"] for a in body["actions"]} == set(POLICIES)
    assert all(a["handler_registered"] for a in body["actions"])
    # admin/owner 默认可执行低风险动作
    enabled = {a["action_type"] for a in body["actions"] if a["enabled"]}
    assert "UPDATE_PRODUCT_CONTENT" in enabled and "CREATE_LISTING_DRAFT" in enabled
    assert body["agents"] and all("action_types" in a for a in body["agents"])

    viewer = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
    assert viewer.status_code == 200, viewer.text
    vh = {"Authorization": f"Bearer {viewer.json()['token']}"}
    vbody = client.get("/api/ai/capabilities", headers=vh).json()
    assert vbody["summary"]["enabled"] == 0
    reasons = [r for a in vbody["actions"] for r in a["blocked_reasons"]]
    assert reasons and all("缺少权限" in r for r in reasons)
    # 只读身份查「全部」队列直接被拒（不是返回空列表冒充已筛选）
    assert client.get("/api/actions", headers=vh,
                      params={"action_type": "ALL", "status": "ALL"}).status_code == 403


def test_recover_stuck_actions_only_touches_stale_executing():
    """启动恢复：孤儿 EXECUTING → FAILED（可重试）；在途的（新）不动。"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="S3 恢复探针")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="s3-recover", password_hash="x", role="admin")
        product = Product(tenant_id=tenant.id, sku="S3-REC-1", title="恢复探针")
        db.add_all([user, product])
        db.commit()
        ctx = resolve_workspace_context(db, user)
        first = _submit(db, ctx, "product", "UPDATE_PRODUCT_CONTENT", product.id, "rec-1",
                        {"title": "A"})
        second = _submit(db, ctx, "product", "UPDATE_PRODUCT_CONTENT", product.id, "rec-2",
                         {"title": "B"})
        stale = datetime.utcnow() - timedelta(hours=2)
        db.query(AiAction).filter(AiAction.id == first.id).update(
            {"status": "EXECUTING", "updated_at": stale})
        db.query(AiAction).filter(AiAction.id == second.id).update(
            {"status": "EXECUTING", "updated_at": datetime.utcnow()})
        db.commit()

        assert recover_stuck_actions(db, older_than_minutes=10) == 1
        db.refresh(first)
        db.refresh(second)
        assert first.status == "FAILED" and first.outcome["recovered_on_startup"] is True
        assert "未确认业务对象" in first.outcome["error"]
        assert second.status == "EXECUTING", "在途执行不得被启动扫描误杀"

        # 收敛后允许重试：再执行一次仍会被「未获批」拦，但不再是 409「已被领取」。
        from app.services.ai_actions import ActionError

        with pytest.raises(ActionError) as exc:
            execute_action(db, ctx, first.id)
        assert exc.value.status_code == 409
        assert "尚未获批" in str(exc.value)
    engine.dispose()
