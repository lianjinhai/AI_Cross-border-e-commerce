"""P0-7：旧自动化不得领取、修补或暴露平台生命周期记录。"""

from datetime import datetime, timedelta

import pytest

from app.db import SessionLocal
from app.models import User, WorkflowRun, WorkflowStep, WorkflowTemplate
from app.seed import ensure_listing_review_workflow
from app.workflows import engine
from app.workflows.kinds import LEGACY_AUTOMATION, PLATFORM_LAUNCH


@pytest.fixture
def launch_records(client):
    with SessionLocal() as db:
        tenant_id = db.query(User).filter_by(username="admin").one().tenant_id
        template = WorkflowTemplate(tenant_id=tenant_id, key="auto_listing", name="Protected launch",
                                    flow_kind=PLATFORM_LAUNCH, steps=[{"step_code": "DATA"}])
        run = WorkflowRun(tenant_id=tenant_id, template_key="launch-only", name="Protected launch",
                          flow_kind=PLATFORM_LAUNCH, status="queued")
        db.add_all([template, run])
        db.flush()
        step = WorkflowStep(tenant_id=tenant_id, run_id=run.id, agent="listing", action="publish", seq=1)
        db.add(step)
        db.commit()
        ids = tenant_id, template.id, run.id
    yield ids
    with SessionLocal() as db:
        db.query(WorkflowStep).filter_by(run_id=ids[2]).delete()
        db.query(WorkflowRun).filter_by(id=ids[2]).delete()
        db.query(WorkflowTemplate).filter_by(id=ids[1]).delete()
        db.commit()


@pytest.mark.parametrize("status", ["queued", "running"])
def test_legacy_claim_and_recovery_skip_launch(client, launch_records, monkeypatch, status):
    _, _, run_id = launch_records
    dispatched = []

    class RecordingThread:
        def __init__(self, *, target, args, daemon):
            self.args = args

        def start(self):
            dispatched.append(self.args[0])

    monkeypatch.setattr(engine.threading, "Thread", RecordingThread)
    with SessionLocal() as db:
        run = db.get(WorkflowRun, run_id)
        run.status = status
        run.lease_until = datetime.utcnow() - timedelta(hours=1)
        db.commit()
        assert engine._claim_run(db, run_id, "legacy-worker") == 0
    engine.recover_incomplete_runs()
    assert run_id not in dispatched
    engine.run_workflow(run_id)
    with SessionLocal() as db:
        assert db.get(WorkflowRun, run_id).status == status
        assert db.query(WorkflowStep).filter_by(run_id=run_id).one().attempts == 0


def test_legacy_seed_and_http_do_not_touch_launch(client, auth_headers, launch_records):
    tenant_id, template_id, run_id = launch_records
    with SessionLocal() as db:
        ensure_listing_review_workflow(db)
        assert db.get(WorkflowTemplate, template_id).steps == [{"step_code": "DATA"}]
        db.get(WorkflowRun, run_id).status = "blocked"
        db.get(WorkflowTemplate, template_id).key = "launch-only"
        db.commit()
    with pytest.raises(ValueError, match="不存在"):
        engine.resume_run(run_id, tenant_id)
    with pytest.raises(ValueError, match="不存在"):
        engine.start_run(tenant_id, "launch-only")
    templates = client.get("/api/workflows/templates", headers=auth_headers).json()["items"]
    assert template_id not in {row["id"] for row in templates}
    assert all(row["flow_kind"] == LEGACY_AUTOMATION for row in templates)
    runs = client.get("/api/workflows/runs", headers=auth_headers).json()["items"]
    assert run_id not in {row["id"] for row in runs}
    assert client.get(f"/api/workflows/runs/{run_id}", headers=auth_headers).status_code == 404
    scheduled = client.post("/api/schedules", headers=auth_headers,
                            json={"name": "Wrong engine", "workflow_key": "launch-only"})
    assert scheduled.status_code == 404, scheduled.text
