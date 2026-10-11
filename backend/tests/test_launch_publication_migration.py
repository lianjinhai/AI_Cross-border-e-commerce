"""Expand 1a：合成历史结构的只读预检、升级、无损降级及拒绝丢失证据。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from .migration_helpers import code_head

BACKEND = Path(__file__).resolve().parents[1]


def test_historical_publication_upgrade_and_guarded_downgrade(tmp_path):
    path = tmp_path / "publication_history.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE tenants(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE users(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id),
                               username TEXT, role TEXT);
            CREATE TABLE shops(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id),
                               platform TEXT, role TEXT);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id),
                                shop_id INTEGER REFERENCES shops(id), source TEXT);
            CREATE TABLE listings(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id),
                                  status TEXT NOT NULL, external_id TEXT NOT NULL);
            CREATE INDEX ix_legacy_listing_tenant ON listings(tenant_id);
            CREATE TABLE platform_publish_attempts(id INTEGER PRIMARY KEY,
                tenant_id INTEGER REFERENCES tenants(id), listing_id INTEGER REFERENCES listings(id),
                shop_id INTEGER REFERENCES shops(id), status TEXT NOT NULL, external_id TEXT NOT NULL);
            CREATE UNIQUE INDEX uq_publish_listing_shop
                ON platform_publish_attempts(tenant_id, listing_id, shop_id);
            CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES('20261001_21');
            INSERT INTO tenants VALUES(1, 'history');
            INSERT INTO users VALUES(1, 1, 'owner', 'admin');
            INSERT INTO shops VALUES(1, 1, 'shopee', 'sales');
            INSERT INTO listings VALUES(1, 1, 'published', 'historical-id');
            INSERT INTO platform_publish_attempts VALUES(1, 1, 1, 1, 'succeeded', 'historical-id');
        """)
    before_bytes = path.read_bytes()
    preflight = subprocess.run([
        sys.executable, "scripts/migration_preflight.py", "--db", str(path),
        "--planned-upgrade", code_head(), "--json"], cwd=BACKEND,
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert preflight.returncode == 0, preflight.stdout + preflight.stderr
    assert path.read_bytes() == before_bytes, "预检必须只读"

    def migrate(direction, target, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", direction, target],
                                cwd=BACKEND, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env={**os.environ, "ERP_DB_URL": "sqlite:///" + path.as_posix()})
        assert (result.returncode == 0) == success, result.stdout + result.stderr

    migrate("upgrade", "20261011_22")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT status, external_id, platform_status, verification_status FROM listings").fetchone() == (
            "published", "historical-id", "UNKNOWN", "UNKNOWN")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    migrate("downgrade", "20261001_21")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM listings").fetchall() == [(1, 1, "published", "historical-id")]
        assert {row[1] for row in db.execute("PRAGMA index_list(platform_publish_attempts)")} == {"uq_publish_listing_shop"}
    migrate("upgrade", "20261011_22")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE platform_publish_attempts SET platform_status='SUBMITTED'")
    migrate("downgrade", "20261001_21", success=False)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT platform_status FROM platform_publish_attempts").fetchone() == ("SUBMITTED",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("20261011_22",)
