"""Profile 模板扩展的历史兼容、数据库唯一性和有损回滚拒绝。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from .migration_helpers import code_head

BACKEND = Path(__file__).resolve().parents[1]


def test_profile_expand_preserves_legacy_and_version_uniqueness(tmp_path):
    target = tmp_path / "profile-history.db"
    with sqlite3.connect(target) as db:
        db.executescript("""
            CREATE TABLE tenants(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE users(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), username TEXT, role TEXT);
            CREATE TABLE shops(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), platform TEXT, role TEXT);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), shop_id INTEGER REFERENCES shops(id), source TEXT);
            CREATE TABLE workflow_templates(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id),
                key TEXT, steps TEXT, flow_kind VARCHAR(32) NOT NULL DEFAULT 'LEGACY_AUTOMATION');
            CREATE INDEX ix_workflow_templates_flow_kind ON workflow_templates(flow_kind);
            CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES('20261012_24');
            INSERT INTO tenants VALUES(1, 'legacy');
            INSERT INTO users VALUES(1, 1, 'owner', 'admin');
            INSERT INTO workflow_templates(id,tenant_id,key,steps) VALUES(1,1,'reprice','[{"agent":"pricing"}]');
            INSERT INTO workflow_templates(id,tenant_id,key,steps) VALUES(2,1,'reprice','[]');
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
    command("-m", "alembic", "upgrade", "20261012_25")
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT profile_key,definition_hash,verification_status FROM workflow_templates").fetchall() == [
            (None, "", "UNKNOWN"), (None, "", "UNKNOWN")]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    command("-m", "alembic", "downgrade", "20261012_24")
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT * FROM workflow_templates ORDER BY id").fetchall() == [
            (1, 1, "reprice", '[{"agent":"pricing"}]', "LEGACY_AUTOMATION"),
            (2, 1, "reprice", "[]", "LEGACY_AUTOMATION")]
    command("-m", "alembic", "upgrade", "20261012_25")
    with sqlite3.connect(target) as db:
        db.execute("INSERT INTO workflow_templates(id,tenant_id,key,steps,flow_kind,profile_key,version) VALUES(3,1,'TEST','[]','PLATFORM_LAUNCH','TEST',1)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO workflow_templates(id,tenant_id,key,steps,flow_kind,profile_key,version) VALUES(4,1,'TEST','[]','PLATFORM_LAUNCH','TEST',1)")
        db.execute("INSERT INTO workflow_templates(id,tenant_id,key,steps,flow_kind,profile_key,version) VALUES(5,1,'TEST','[]','PLATFORM_LAUNCH','TEST',2)")
    refused = command("-m", "alembic", "downgrade", "20261012_24", success=False)
    assert "拒绝有损降级" in refused.stderr
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT version FROM workflow_templates WHERE profile_key='TEST' ORDER BY version").fetchall() == [(1,), (2,)]
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("20261012_25",)
