"""旧三表/Listing 与新关系的迁移契约：隔离历史库，主库不参与。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from .migration_helpers import code_head

BACKEND = Path(__file__).resolve().parents[1]


def test_launch_runtime_migration_roundtrip_and_guard(tmp_path):
    target = tmp_path / "launch-runtime-history.db"
    with sqlite3.connect(target) as db:
        db.executescript("""
            CREATE TABLE tenants(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE users(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), username TEXT, role TEXT);
            CREATE TABLE shops(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), platform TEXT, role TEXT);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), shop_id INTEGER REFERENCES shops(id), source TEXT);
            CREATE TABLE products(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), title TEXT);
            CREATE TABLE suppliers(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id));
            CREATE TABLE listings(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), product_id INTEGER REFERENCES products(id), status TEXT, external_id TEXT);
            CREATE TABLE workflow_templates(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), key TEXT);
            CREATE TABLE workflow_runs(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), status TEXT,
                context TEXT, flow_kind VARCHAR(32) NOT NULL DEFAULT 'LEGACY_AUTOMATION');
            CREATE TABLE workflow_steps(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), run_id INTEGER REFERENCES workflow_runs(id),
                status TEXT, output TEXT);
            CREATE INDEX ix_workflow_steps_run_id ON workflow_steps(run_id);
            CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES('20261012_25');
            INSERT INTO tenants VALUES(1,'legacy');
            INSERT INTO users VALUES(1,1,'owner','admin');
            INSERT INTO shops VALUES(1,1,'shopee','sales');
            INSERT INTO products VALUES(1,1,'history');
            INSERT INTO listings VALUES(1,1,1,'published','old-ref');
            INSERT INTO workflow_templates VALUES(1,1,'reprice');
            INSERT INTO workflow_runs VALUES(1,1,'blocked','{"product_ids":[1]}','LEGACY_AUTOMATION');
            INSERT INTO workflow_steps VALUES(1,1,1,'blocked','{"business_status":"blocked"}');
        """)
        legacy = {table: db.execute(f"SELECT * FROM {table}").fetchall()
                  for table in ("listings", "workflow_runs", "workflow_steps")}
    env = {**os.environ, "ERP_DB_URL": "sqlite:///" + target.as_posix(), "PYTHONIOENCODING": "utf-8"}

    def command(*args, success=True):
        result = subprocess.run([sys.executable, *args], cwd=BACKEND, env=env,
                                capture_output=True, text=True, encoding="utf-8")
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result

    before = target.read_bytes()
    command("scripts/migration_preflight.py", "--db", str(target), "--planned-upgrade", code_head(), "--json")
    assert target.read_bytes() == before
    command("-m", "alembic", "upgrade", "20261012_26")
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT shop_id,parent_listing_id,status,external_id FROM listings").fetchone() == (None, None, "published", "old-ref")
        assert db.execute("SELECT active_slot,definition_id,platform_status FROM workflow_runs").fetchone() == (None, None, "UNKNOWN")
        assert db.execute("SELECT step_code,status FROM workflow_steps").fetchone() == (None, "blocked")
        assert db.execute("SELECT count(*) FROM workflow_events").fetchone() == (0,)
        event_keys = {(row[3], row[2], row[4]) for row in db.execute("PRAGMA foreign_key_list(workflow_events)")}
        assert {("tenant_id", "tenants", "id"), ("run_id", "workflow_runs", "id"),
                ("step_id", "workflow_steps", "id"), ("actor_id", "users", "id")} <= event_keys
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    command("-m", "alembic", "downgrade", "20261012_25")
    with sqlite3.connect(target) as db:
        for table, rows in legacy.items():
            assert db.execute(f"SELECT * FROM {table}").fetchall() == rows
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    command("-m", "alembic", "upgrade", "20261012_26")
    with sqlite3.connect(target) as db:
        db.execute("UPDATE listings SET shop_id=1")
    refused = command("-m", "alembic", "downgrade", "20261012_25", success=False)
    assert "拒绝有损降级" in refused.stderr
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT shop_id FROM listings").fetchone() == (1,)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("20261012_26",)
