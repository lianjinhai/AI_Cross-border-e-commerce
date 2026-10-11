"""合成历史库：旧流程不变、新类型阻止有损降级；主库不参与。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from .migration_helpers import code_head

BACKEND = Path(__file__).resolve().parents[1]


def test_workflow_kind_migration_preserves_history(tmp_path):
    target = tmp_path / "workflow-kind-history.db"
    with sqlite3.connect(target) as db:
        db.executescript("""
            CREATE TABLE tenants(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE users(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), username TEXT, role TEXT);
            CREATE TABLE shops(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), platform TEXT, role TEXT);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), shop_id INTEGER REFERENCES shops(id), source TEXT);
            CREATE TABLE workflow_templates(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), key TEXT, steps TEXT);
            CREATE TABLE workflow_runs(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), status TEXT, context TEXT);
            CREATE INDEX ix_workflow_runs_tenant_id ON workflow_runs(tenant_id);
            CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES('20261011_23');
            INSERT INTO tenants VALUES(1, 'legacy');
            INSERT INTO users VALUES(1, 1, 'owner', 'admin');
            INSERT INTO workflow_templates VALUES(1, 1, 'reprice', '[{"agent":"pricing"}]');
            INSERT INTO workflow_runs VALUES(1, 1, 'blocked', '{"product_ids":[42]}');
        """)
    env = {**os.environ, "ERP_DB_URL": "sqlite:///" + target.as_posix(), "PYTHONIOENCODING": "utf-8"}

    def command(*args, success=True):
        result = subprocess.run([sys.executable, *args], cwd=BACKEND, env=env,
                                capture_output=True, text=True, encoding="utf-8")
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result

    before = target.read_bytes()
    command("scripts/migration_preflight.py", "--db", str(target), "--planned-upgrade", code_head(), "--json")
    assert target.read_bytes() == before
    command("-m", "alembic", "upgrade", "20261012_24")
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT status,context,flow_kind FROM workflow_runs").fetchone() == (
            "blocked", '{"product_ids":[42]}', "LEGACY_AUTOMATION")
        assert db.execute("SELECT flow_kind FROM workflow_templates").fetchone() == ("LEGACY_AUTOMATION",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    command("-m", "alembic", "downgrade", "20261011_23")
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT * FROM workflow_runs").fetchall() == [(1, 1, "blocked", '{"product_ids":[42]}')]
        assert db.execute("SELECT steps FROM workflow_templates").fetchone() == ('[{"agent":"pricing"}]',)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    command("-m", "alembic", "upgrade", "20261012_24")
    with sqlite3.connect(target) as db:
        db.execute("UPDATE workflow_runs SET flow_kind='PLATFORM_LAUNCH'")
    refused = command("-m", "alembic", "downgrade", "20261011_23", success=False)
    assert "拒绝有损降级" in refused.stderr
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT flow_kind FROM workflow_templates").fetchone() == ("LEGACY_AUTOMATION",)
        assert db.execute("SELECT flow_kind FROM workflow_runs").fetchone() == ("PLATFORM_LAUNCH",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("20261012_24",)
