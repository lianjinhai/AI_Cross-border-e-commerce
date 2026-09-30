"""统一执行器的权限、归属、幂等与事务测试；全部使用独立内存库。"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import AiAction, Listing, Product, Tenant, User
from app.services.action_system import HANDLERS, decide_action, execute_action, submit_action
from app.services.ai_actions import ActionError
from app.services.workspace_context import resolve_workspace_context


@pytest.fixture
def case():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="Action 独立探针")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="action-owner", password_hash="not-used", role="admin")
        product = Product(tenant_id=tenant.id, sku="ACTION-1", title="Desk organizer", category="家居")
        db.add_all([user, product])
        db.commit()
        ctx = resolve_workspace_context(db, user)
        proposal = {"action_type": "CREATE_LISTING_DRAFT", "target_type": "product",
                    "target_id": product.id, "reason": "只创建草稿，不发布",
                    "payload": {"title": "Desk organizer", "description": "Storage",
                                "platform": "shopee", "language": "en",
                                "bullets": ["Durable"], "keywords": ["desk"]}}
        yield db, ctx, user, product, proposal
    engine.dispose()


def test_draft_is_only_created_by_executor_and_replay_is_idempotent(case):
    db, ctx, user, _, proposal = case
    action = submit_action(db, ctx, "listing", proposal, "same-step")
    assert action.status == "APPROVED" and action.risk_level == "MEDIUM"
    assert not action.approval_required and db.query(Listing).count() == 0
    replay = submit_action(db, ctx, "listing", proposal, "same-step")
    assert replay.id == action.id and db.query(AiAction).count() == 1
    result = execute_action(db, ctx, action.id)
    assert result.status == "SUCCESS"
    row = db.query(Listing).one()
    assert row.status == "draft" and row.created_by == row.last_edited_by == user.id
    assert result.outcome["result"]["id"] == row.id
    assert execute_action(db, ctx, action.id).outcome == result.outcome
    assert db.query(Listing).count() == 1


@pytest.mark.parametrize("agent", ["pricing", "discovery", "unregistered"])
def test_agent_cannot_claim_another_domain_action(case, agent):
    db, ctx, _, _, proposal = case
    with pytest.raises(ActionError, match="无权"):
        submit_action(db, ctx, agent, proposal, "forged-agent")
    assert db.query(AiAction).count() == db.query(Listing).count() == 0


@pytest.mark.parametrize("change", ["disabled", "viewer", "expired", "suspended"])
def test_current_identity_is_revalidated_at_execution(case, change):
    db, ctx, user, _, proposal = case
    action = submit_action(db, ctx, "listing", proposal, "revoked")
    tenant = db.get(Tenant, user.tenant_id)
    if change == "disabled":
        user.status = "disabled"
    elif change == "viewer":
        user.role = "viewer"
    elif change == "expired":
        tenant.license_until = datetime.utcnow() - timedelta(seconds=1)
    else:
        tenant.status = "suspended"
    db.commit()
    with pytest.raises(ActionError):
        execute_action(db, ctx, action.id)
    assert db.query(Listing).count() == 0 and action.status == "APPROVED"


def test_cross_tenant_target_is_rejected_before_action_creation(case):
    db, ctx, _, _, proposal = case
    other = Tenant(name="隔离租户")
    db.add(other)
    db.flush()
    product = Product(tenant_id=other.id, sku="FOREIGN", title="Foreign", category="家居")
    db.add(product)
    db.commit()
    proposal["target_id"] = product.id
    with pytest.raises(ActionError, match="不存在"):
        submit_action(db, ctx, "listing", proposal, "foreign")
    assert db.query(AiAction).count() == 0


def test_failed_transaction_rolls_back_business_write_and_keeps_terminal_action(case, monkeypatch):
    db, ctx, _, _, proposal = case
    action = submit_action(db, ctx, "listing", proposal, "failure")

    def fail_after_write(db, action, payload):
        db.add(Listing(tenant_id=action.tenant_id, product_id=action.target_id,
                       platform="shopee", language="en", title="Must roll back"))
        db.flush()
        raise RuntimeError("模拟业务写入后异常")

    monkeypatch.setitem(HANDLERS, "CREATE_LISTING_DRAFT", fail_after_write)
    result = execute_action(db, ctx, action.id)
    assert result.status == "FAILED" and "异常" in result.outcome["error"]
    assert db.query(Listing).count() == 0
    with pytest.raises(ActionError, match="终止"):
        execute_action(db, ctx, action.id)
    assert submit_action(db, ctx, "listing", proposal, "failure").id == action.id
    assert submit_action(db, ctx, "listing", proposal, "new-intent").id != action.id


def test_auto_safe_action_cannot_be_artificially_approved(case):
    db, ctx, _, _, proposal = case
    action = submit_action(db, ctx, "listing", proposal, "auto")
    with pytest.raises(ActionError, match="不需要"):
        decide_action(db, ctx, action.id, True, "伪造审批")


def test_optimized_content_requires_unchanged_draft(case):
    db, ctx, _, _, proposal = case
    created = execute_action(db, ctx, submit_action(db, ctx, "listing", proposal, "create").id)
    row = db.get(Listing, created.outcome["result"]["id"])
    optimize = {"action_type": "UPDATE_LISTING_CONTENT", "target_type": "listing",
                "target_id": row.id, "payload": {"title": "Optimized", "keywords": ["new"],
                    "before": {"title": row.title, "keywords": row.keywords}}}
    action = submit_action(db, ctx, "listing", optimize, "optimize")
    row.title = "Human edit"
    db.commit()
    assert execute_action(db, ctx, action.id).status == "FAILED"
    assert row.title == "Human edit"
    optimize["payload"]["before"]["title"] = row.title
    next_action = submit_action(db, ctx, "listing", optimize, "next-optimize")
    row.status = "published"
    db.commit()
    assert execute_action(db, ctx, next_action.id).status == "FAILED"
    assert row.title == "Human edit"


def test_proposal_cannot_override_server_policy(case):
    db, ctx, _, _, proposal = case
    proposal.update(required_permission="none", risk_level="LOW", approval_required=True)
    action = submit_action(db, ctx, "listing", proposal, "policy")
    assert action.required_permission == "listing:write" and action.risk_level == "MEDIUM"
    assert not action.approval_required
    action.required_permission = "ai:read"
    db.commit()
    with pytest.raises(ActionError, match="策略不一致"):
        execute_action(db, ctx, action.id)
    assert db.query(Listing).count() == 0
