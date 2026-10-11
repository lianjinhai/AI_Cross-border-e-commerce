"""契约守护：真实Alembic调度身份升级/降级，仅使用临时隔离库。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_schedule_identity_upgrade_downgrade_preserves_legacy_data(tmp_path):
    target = tmp_path / "schedule-migration.db"
    with sqlite3.connect(target) as db:
        db.executescript("""
            CREATE TABLE tenants (id INTEGER PRIMARY KEY);
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE schedules (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL,
                name VARCHAR(128) NOT NULL, kind VARCHAR(16), workflow_key VARCHAR(64),
                interval_minutes INTEGER, enabled BOOLEAN, run_count INTEGER,
                last_run_at DATETIME, last_status VARCHAR(16), created_at DATETIME,
                CONSTRAINT fk_schedules_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants(id));
            CREATE INDEX ix_schedules_tenant_id ON schedules(tenant_id);
            INSERT INTO tenants VALUES(1);
            INSERT INTO users VALUES(1);
            INSERT INTO schedules VALUES(1,1,'legacy','trend_scan','',5,1,7,NULL,'',NULL);
            CREATE TABLE alembic_version(version_num VARCHAR(32));
            INSERT INTO alembic_version VALUES('20260930_18');
        """)
        before = db.execute("SELECT * FROM schedules").fetchall()
    env = {**os.environ, "ERP_DB_URL": "sqlite:///" + target.as_posix(), "PYTHONIOENCODING": "utf-8"}
    # 最小 schedules 夹具只验证身份迁移；不能假装包含后续发布表的历史全库。
    for direction, revision in (("upgrade", "20261001_19"), ("downgrade", "20260930_18"),
                                ("upgrade", "20261001_19")):
        result = subprocess.run([sys.executable, "-m", "alembic", direction, revision],
                                cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, result.stderr
        with sqlite3.connect(target) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(schedules)")]
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("SELECT * FROM schedules").fetchall() == (
                [(*before[0], None, None)] if direction == "upgrade" else before)
            assert db.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='schedules'").fetchall() == [
                ("ix_schedules_tenant_id",)]
            constraints = db.execute("PRAGMA foreign_key_list(schedules)").fetchall()
            assert {row[3] for row in constraints} == (
                {"tenant_id", "requested_by", "workspace_id"} if direction == "upgrade" else {"tenant_id"})
            assert ("requested_by" in columns) == (direction == "upgrade")
