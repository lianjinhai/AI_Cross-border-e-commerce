"""Expand 1b：旧店铺缺值不猜，预检只读，无数据丢失回滚。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from .migration_helpers import code_head

BACKEND = Path(__file__).resolve().parents[1]


def test_shop_context_migration_preserves_legacy_and_refuses_data_loss(tmp_path):
    target = tmp_path / "shop-context-history.db"
    with sqlite3.connect(target) as db:
        db.executescript("""
            CREATE TABLE tenants(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE users(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), username TEXT, role TEXT);
            CREATE TABLE shops(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), platform TEXT, role TEXT);
            CREATE INDEX ix_shops_tenant_id ON shops(tenant_id);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id),
                                shop_id INTEGER REFERENCES shops(id), source TEXT);
            CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES('20261011_22');
            INSERT INTO tenants VALUES(1, 'legacy');
            INSERT INTO users VALUES(1, 1, 'owner', 'admin');
            INSERT INTO shops VALUES(1, 1, 'ebay', 'sales');
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
    command("-m", "alembic", "upgrade", "20261011_23")
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT market, fulfillment_mode, capability_revision FROM shops").fetchone() == ("", "", 0)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    command("-m", "alembic", "downgrade", "20261011_22")
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT * FROM shops").fetchall() == [(1, 1, "ebay", "sales")]
        assert db.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='shops'").fetchall() == [("ix_shops_tenant_id",)]
        assert db.execute("PRAGMA foreign_key_list(shops)").fetchone()[3:5] == ("tenant_id", "id")
    command("-m", "alembic", "upgrade", "20261011_23")
    with sqlite3.connect(target) as db:
        db.execute("UPDATE shops SET market='TR'")
    refused = command("-m", "alembic", "downgrade", "20261011_22", success=False)
    assert "拒绝有损降级" in refused.stderr
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT market FROM shops").fetchone() == ("TR",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("20261011_23",)
