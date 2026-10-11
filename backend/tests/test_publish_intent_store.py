"""P0-1：发布意图必须按目标店铺隔离，使用独立内存数据库。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import AiAction, Tenant
from app.services.action_system import _existing_intent, _intent_key, _scope_action
from app.services.ai_actions import ActionError


@pytest.fixture
def store_intents():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="Store intent isolation")
        db.add(tenant)
        db.flush()
        ctx = SimpleNamespace(legacy_tenant_id=tenant.id, workspace_id=17, user_id=23)
        yield db, ctx
    engine.dispose()


def record(db, ctx, shop_id, status="PENDING_APPROVAL", fingerprint="content-a"):
    action = AiAction(
        tenant_id=ctx.legacy_tenant_id, workspace_id=ctx.workspace_id,
        requested_by=ctx.user_id, agent_type="listing", action_type="PUBLISH_LISTING",
        target_type="listing", target_id=41, reason="contract test",
        evidence={"shop_id": shop_id, "payload": {"shop_id": shop_id},
                  "scope_key": "shared-task", "fingerprint": fingerprint},
        risk_level="HIGH", required_permission="listing:write",
        execution_mode="APPROVAL_REQUIRED", approval_required=True,
        status=status, idempotency_key=f"{shop_id}-{status}-{fingerprint}")
    db.add(action)
    db.flush()
    return action


@pytest.mark.parametrize("status", ["PENDING_APPROVAL", "SUCCESS"])
def test_other_store_does_not_block_publication(store_intents, status):
    db, ctx = store_intents
    record(db, ctx, 101, status)
    assert _existing_intent(db, ctx.legacy_tenant_id, ctx.workspace_id,
                            "PUBLISH_LISTING", 41,
                            {"shop_id": 102, "fingerprint": "content-b"}) is None


def test_same_store_replay_and_changed_content_guard(store_intents):
    db, ctx = store_intents
    own = record(db, ctx, 101)
    record(db, ctx, 102, fingerprint="other-store")
    evidence = {"shop_id": 101, "fingerprint": "content-a"}
    assert _existing_intent(db, ctx.legacy_tenant_id, ctx.workspace_id,
                            "PUBLISH_LISTING", 41, evidence).id == own.id
    with pytest.raises(ActionError):
        _existing_intent(db, ctx.legacy_tenant_id, ctx.workspace_id,
                         "PUBLISH_LISTING", 41, {**evidence, "fingerprint": "changed"})


def test_trace_scope_can_contain_two_stores(store_intents):
    db, ctx = store_intents
    record(db, ctx, 101)
    assert _scope_action(db, ctx, "PUBLISH_LISTING", 41, "shared-task",
                         {"shop_id": 102}) is None


def test_local_and_legacy_payload_store_remain_separate(store_intents):
    db, ctx = store_intents
    local = record(db, ctx, None)
    remote = record(db, ctx, 101)
    remote.evidence = {key: value for key, value in remote.evidence.items() if key != "shop_id"}
    db.flush()
    for shop_id, expected in ((None, local.id), (101, remote.id)):
        found = _existing_intent(db, ctx.legacy_tenant_id, ctx.workspace_id,
                                 "PUBLISH_LISTING", 41,
                                 {"shop_id": shop_id, "fingerprint": "content-a"})
        assert found.id == expected


def test_other_store_failure_does_not_change_retry_identity(store_intents):
    db, ctx = store_intents
    evidence = {"shop_id": 101, "fingerprint": "content-a"}
    before = _intent_key(db, ctx, "listing", "PUBLISH_LISTING", 41, "trace", "{}", evidence)
    record(db, ctx, 102, status="FAILED")
    assert _intent_key(db, ctx, "listing", "PUBLISH_LISTING", 41,
                       "trace", "{}", evidence) == before
    record(db, ctx, 101, status="FAILED")
    assert _intent_key(db, ctx, "listing", "PUBLISH_LISTING", 41,
                       "trace", "{}", evidence) != before
