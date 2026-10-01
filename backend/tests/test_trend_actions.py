"""契约守护：趋势提案只读、可信执行、来源保护与调度身份。"""

import copy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.discovery import DiscoveryAgent
from app.agents.orchestrator import OrchestratorAgent, invoke_discovery
from app.db import Base
from app.models import AiAction, MarketTrend, Schedule, Tenant, User
from app.services import scheduler
from app.services.action_system import execute_action, submit_action
from app.services.ai_actions import ActionError
from app.services.schedule_identity import bind_schedule, schedule_context
from app.services.scheduler import run_task
from app.services.trend_candidates import builtin_candidates
from app.services.workspace_context import resolve_workspace_context
from app.workflows.engine import run_scheduled_task, run_step


@pytest.fixture
def case(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="趋势隔离探针")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="trend-owner", password_hash="unused", role="admin")
        db.add(user)
        db.commit()
        for module in ("app.agents.base", "app.services.scheduler", "app.workflows.engine"):
            monkeypatch.setattr(module + ".SessionLocal", lambda: Session(engine))
        monkeypatch.setattr("app.tools.audit._session_factory", lambda: Session(engine))
        yield db, resolve_workspace_context(db, user), user
    engine.dispose()


def proposal(ctx):
    with DiscoveryAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        return agent.scan_trends()


def test_agent_is_readonly_and_daily_candidates(case):
    db, ctx, _ = case
    output = proposal(ctx)
    assert [item["candidate"] for item in output["payload"]["items"]] == builtin_candidates(
        datetime.utcnow().strftime("%Y%m%d"))
    assert db.query(MarketTrend).count() == 0
    assert db.query(AiAction).count() == 0
    assert output["target_id"] == ctx.legacy_tenant_id


def test_refresh_preserves_real_sources_and_replays_original(case):
    db, ctx, _ = case
    candidates = builtin_candidates(datetime.utcnow().strftime("%Y%m%d"))
    for item, source in zip(candidates[:2], ("csv", "api"), strict=True):
        db.add(MarketTrend(tenant_id=ctx.legacy_tenant_id, **{**item, "source": source, "search_volume": 123}))
    db.commit()
    items = invoke_discovery(db, ctx, "scan_trends", scope_key="same-scope")
    assert [item["source"] for item in items[:2]] == ["csv", "api"]
    assert [item["search_volume"] for item in items[:2]] == [123, 123]
    assert len(items) == 12 and all("updated_at" not in item for item in items)
    assert invoke_discovery(db, ctx, "scan_trends", scope_key="same-scope") == items
    assert db.query(AiAction).count() == 1


@pytest.mark.parametrize("field,value", [("search_volume", -1), ("growth_30d", float("inf")),
                                       ("competition", True), ("keyword", "forged"), ("source", "api")])
def test_forged_payload_never_changes_business_rows(case, field, value):
    db, ctx, _ = case
    output = proposal(ctx)
    output["payload"]["items"][-1]["candidate"][field] = value
    if field == "growth_30d":
        with pytest.raises(ValueError):
            submit_action(db, ctx, "discovery", output, "forged")
    else:
        action = submit_action(db, ctx, "discovery", output, "forged")
        assert execute_action(db, ctx, action.id).status == "FAILED"
    assert db.query(MarketTrend).count() == 0


def test_atomic_failure_and_terminal_recovery(case, monkeypatch):
    db, ctx, _ = case
    from app.services import action_system, trend_refresh

    original = trend_refresh.refresh_builtin_trends

    def broken(db, action, payload):
        original(db, action, payload)
        raise RuntimeError("模拟提交前故障")

    monkeypatch.setitem(action_system.HANDLERS, "REFRESH_BUILTIN_TRENDS", broken)
    with pytest.raises(ActionError):
        invoke_discovery(db, ctx, "scan_trends", scope_key="broken")
    assert db.query(MarketTrend).count() == 0
    assert db.query(AiAction).one().status == "FAILED"
    monkeypatch.setitem(action_system.HANDLERS, "REFRESH_BUILTIN_TRENDS", original)
    with pytest.raises(ActionError):
        invoke_discovery(db, ctx, "scan_trends", scope_key="broken")
    assert db.query(AiAction).count() == 1
    assert len(invoke_discovery(db, ctx, "scan_trends", scope_key="new-scope")) == 12


def test_stale_success_and_permission_revocation_block(case):
    db, ctx, user = case
    invoke_discovery(db, ctx, "scan_trends", scope_key="old")
    row = db.query(MarketTrend).first()
    row.source, row.search_volume = "csv", 777
    db.commit()
    with pytest.raises(ActionError, match="依据已变化"):
        invoke_discovery(db, ctx, "scan_trends", scope_key="old")
    assert row.source == "csv" and row.search_volume == 777
    user.role = "viewer"
    db.commit()
    with pytest.raises(ActionError, match="缺少权限"):
        invoke_discovery(db, ctx, "scan_trends", scope_key="new")


def test_duplicate_and_old_day_fail_before_writes(case):
    db, ctx, _ = case
    output = proposal(ctx)
    output["payload"]["items"][-1] = copy.deepcopy(output["payload"]["items"][0])
    action = submit_action(db, ctx, "discovery", output, "duplicate")
    assert execute_action(db, ctx, action.id).status == "FAILED"
    output = proposal(ctx)
    output["payload"]["day"] = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")
    action = submit_action(db, ctx, "discovery", output, "yesterday")
    assert execute_action(db, ctx, action.id).status == "FAILED"
    assert db.query(MarketTrend).count() == 0


def test_success_scope_recovery_does_not_regenerate_next_day(case, monkeypatch):
    db, ctx, _ = case
    original = invoke_discovery(db, ctx, "scan_trends", scope_key="frozen-day")

    def unexpected_scan(self):
        raise AssertionError("恢复不得重新生成日种子提案")

    monkeypatch.setattr(DiscoveryAgent, "scan_trends", unexpected_scan)
    assert invoke_discovery(db, ctx, "scan_trends", scope_key="frozen-day") == original
    assert db.query(AiAction).count() == 1


def test_scheduler_requires_persistent_real_identity(case):
    db, ctx, user = case
    task = Schedule(tenant_id=ctx.legacy_tenant_id, name="trend", kind="trend_scan", workflow_key="")
    db.add(task)
    db.commit()
    assert run_task(task.tenant_id, task.kind, "", schedule=task) == (
        False, "历史调度缺少可信发起者，请由真实用户重新启用")
    bind_schedule(db, task, ctx)
    db.commit()
    assert run_task(task.tenant_id, task.kind, "", schedule=task) == (True, "12 trends")
    action = db.query(AiAction).one()
    assert action.requested_by == user.id and action.workspace_id == ctx.workspace_id
    user.role = "viewer"
    db.commit()
    assert not run_task(task.tenant_id, task.kind, "", schedule=task)[0]
    with pytest.raises(ActionError):
        schedule_context(db, task)


def test_binding_impersonation_cross_tenant_and_forged_object(case):
    db, ctx, user = case
    task = Schedule(tenant_id=ctx.legacy_tenant_id, name="trend", kind="trend_scan", workflow_key="")
    with pytest.raises(ActionError):
        bind_schedule(db, task, replace(ctx, is_impersonating=True))
    db.add(task)
    db.commit()
    forged = Schedule(id=task.id, tenant_id=task.tenant_id, name="forged", kind="trend_scan",
                      requested_by=user.id, workspace_id=ctx.workspace_id)
    assert not run_task(task.tenant_id, task.kind, "", schedule=forged)[0]
    bind_schedule(db, task, ctx)
    db.commit()
    other = Tenant(name="other")
    db.add(other)
    db.flush()
    user.tenant_id = other.id
    db.commit()
    assert not run_task(task.tenant_id, task.kind, "", schedule=task)[0]
    assert db.query(MarketTrend).count() == 0


def test_scheduler_async_workflow_reports_dispatched(case, monkeypatch):
    db, ctx, _ = case
    task = Schedule(tenant_id=ctx.legacy_tenant_id, name="workflow", kind="workflow", workflow_key="probe")
    bind_schedule(db, task, ctx)
    monkeypatch.setattr("app.workflows.engine.start_run", lambda *a, **kw: {"id": 44, "status": "running"})
    assert run_scheduled_task(db, task) == (True, "run#44 (running)")


def test_tick_claims_only_once_and_real_execute_records_failure(case, monkeypatch):
    db, ctx, _ = case
    task = Schedule(tenant_id=ctx.legacy_tenant_id, name="legacy-due", kind="trend_scan",
                    workflow_key="", interval_minutes=5, created_at=datetime.utcnow() - timedelta(hours=1))
    db.add(task)
    db.commit()
    started = []

    class ThreadProbe:
        def __init__(self, target, args, daemon):
            self.args = args

        def start(self):
            started.append(self.args[0])

    monkeypatch.setattr(scheduler.threading, "Thread", ThreadProbe)
    scheduler._tick()
    scheduler._tick()
    assert started == [task.id]
    scheduler._execute(task.id)
    db.refresh(task)
    assert task.last_status == "failed" and task.run_count == 1
    assert task.last_run_at is not None and db.query(MarketTrend).count() == 0


def test_workflow_and_chat_use_trusted_orchestrator(case):
    db, ctx, user = case
    blocked = run_step("discovery", "scan_trends", ctx.legacy_tenant_id, {}, {})
    assert blocked["business_status"] == "blocked"
    output = run_step("discovery", "scan_trends", ctx.legacy_tenant_id, {},
                      {"_action_requested_by": user.id, "_action_scope": "workflow-scan"})
    assert output["business_status"] == "success" and len(output["items"]) == 12
    with OrchestratorAgent(ctx.legacy_tenant_id, context=ctx) as agent:
        output = agent.chat("看看市场趋势")
    assert output["intent"] == "trends" and len(output["data"]) == 5
    assert db.query(AiAction).count() == 2


def test_http_scan_and_schedule_ignore_client_identity(client, auth_headers):
    response = client.post("/api/discovery/trends/scan", headers=auth_headers)
    assert response.status_code == 200 and len(response.json()["items"]) == 12
    response = client.post("/api/schedules", headers=auth_headers, json={
        "name": "identity-probe", "kind": "trend_scan", "requested_by": 999,
        "workspace_id": 999, "interval_minutes": 5, "enabled": False})
    assert response.status_code == 200
    task = response.json()
    assert task["requested_by"] != 999 and task["workspace_id"] != 999
    try:
        response = client.post(f"/api/schedules/{task['id']}/run", headers=auth_headers)
        assert response.status_code == 200 and response.json()["ok"] is True
    finally:
        assert client.delete(f"/api/schedules/{task['id']}", headers=auth_headers).status_code == 200
