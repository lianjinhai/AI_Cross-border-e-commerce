"""Listing 提案、审批执行与工作流断点恢复的闭环验证。"""

import ast
from pathlib import Path

import pytest

from app.db import SessionLocal
from app.models import AiAction, Listing, User, WorkflowTemplate

from .action_helpers import approve_and_execute


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


def test_pending_publish_does_not_change_listing_and_reuses_intent(client, auth_headers):
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


def test_publication_rechecks_approved_content_and_preserves_failure_scene(client, auth_headers):
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
def test_workflow_pauses_before_publish_and_resumes_only_after_execution(client, auth_headers, reject):
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
    assert detail["status"] == "blocked" and detail["steps"][2]["status"] == "blocked"
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
