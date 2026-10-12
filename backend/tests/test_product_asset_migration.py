"""素材迁移使用合成历史库，核对旧图片原样保留及有数据拒绝降级。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from .migration_helpers import code_head


def test_asset_migration_preserves_history_and_refuses_loss(tmp_path):
    target = tmp_path / "asset-history.db"
    with sqlite3.connect(target) as db:
        db.executescript("""
            CREATE TABLE tenants(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE users(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), username TEXT, role TEXT);
            CREATE TABLE products(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), images TEXT);
            CREATE TABLE shops(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), platform TEXT, role TEXT);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), shop_id INTEGER REFERENCES shops(id), source TEXT);
            CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES('20261012_27');
            INSERT INTO tenants VALUES(1,'history');
            INSERT INTO users VALUES(1,1,'owner','admin');
            INSERT INTO products VALUES(1,1,'["https://example.com/unknown.jpg"]');
        """)
        old = db.execute("SELECT * FROM products").fetchall()
    env = {**os.environ, "ERP_DB_URL": "sqlite:///" + target.as_posix(), "PYTHONIOENCODING": "utf-8"}

    def command(*args, success=True):
        result = subprocess.run([sys.executable, *args], cwd=Path(__file__).resolve().parents[1],
                                env=env, capture_output=True, text=True, encoding="utf-8")
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result

    before = target.read_bytes()
    command("scripts/migration_preflight.py", "--db", str(target), "--planned-upgrade", code_head(), "--json")
    assert target.read_bytes() == before
    command("-m", "alembic", "upgrade", "20261012_28")
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT * FROM products").fetchall() == old
        assert db.execute("SELECT count(*) FROM product_assets").fetchone() == (0,)
        refs = {(row[3], row[2], row[4]) for row in db.execute("PRAGMA foreign_key_list(product_assets)")}
        assert refs == {("tenant_id", "tenants", "id"), ("product_id", "products", "id"),
                        ("parent_asset_id", "product_assets", "id"), ("created_by", "users", "id")}
    command("-m", "alembic", "downgrade", "20261012_27")
    command("-m", "alembic", "upgrade", "20261012_28")
    with sqlite3.connect(target) as db:
        db.execute("""INSERT INTO product_assets(tenant_id,workspace_id,product_id,asset_key,version,asset_type,
                   uri,content_hash,rights_status,source,rights_evidence_ref,market,platform,verification_status,
                   manifest,created_by,created_at)
                   VALUES(1,1,1,'history',1,'MAIN_IMAGE','https://example.com/unknown.jpg',?,'UNKNOWN','history',
                   '','SG','shopee','UNKNOWN','{}',1,'2026-10-12')""", ("a" * 64,))
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        cursor = db.execute("SELECT * FROM product_assets")
        values = dict(zip((column[0] for column in cursor.description), cursor.fetchone(), strict=True))
        values.pop("id")
        insert = "INSERT INTO product_assets(" + ",".join(values) + ") VALUES(" + ",".join("?" for _ in values) + ")"
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute(insert, tuple(values.values()))
        values.update(asset_key="invalid-version", version=0)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            db.execute(insert, tuple(values.values()))
    result = command("-m", "alembic", "downgrade", "20261012_27", success=False)
    assert "拒绝有损降级" in result.stderr
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT * FROM products").fetchall() == old
        assert db.execute("SELECT count(*) FROM product_assets").fetchone() == (1,)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("20261012_28",)
