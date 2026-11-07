"""Revision 33（M2-E 标签包）迁移可逆性：建表可回滚、版本号唯一、有数据时拒绝有损降级。

为什么要单独验：标签包是「印出去的那一版依据是什么」的审计凭据。迁错了不是「少一列」，
而是**合规历史丢失**。这里用合成历史库走真实 alembic，不碰业务主库。
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from .migration_helpers import code_head


def _command(target, *args, success=True):
    env = {**os.environ, "ERP_DB_URL": "sqlite:///" + target.as_posix(), "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, *args], cwd=Path(__file__).resolve().parents[1],
                            env=env, capture_output=True, text=True, encoding="utf-8")
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result


def test_label_packages_migration_is_reversible(tmp_path):
    assert code_head() == "20261107_33" or code_head() > "20261107_33"
    target = tmp_path / "label-packages.db"
    with sqlite3.connect(target) as db:
        db.executescript("""
            CREATE TABLE tenants(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE products(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), title TEXT);
            CREATE TABLE shops(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), name TEXT);
            CREATE TABLE workflow_runs(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id));
            CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES('20261107_32');
            INSERT INTO tenants VALUES(1,'label history');
            INSERT INTO products VALUES(1,1,'标签商品');
            INSERT INTO shops VALUES(1,1,'标签店铺');
            INSERT INTO workflow_runs VALUES(1,1);
        """)

    _command(target, "-m", "alembic", "upgrade", "20261107_33")
    with sqlite3.connect(target) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(label_packages)")}
        assert {"tenant_id", "product_id", "shop_id", "run_id", "step_code", "destination_country",
                "version", "action", "content", "content_digest", "basis", "basis_fingerprint",
                "open_items", "created_by", "created_at"} <= columns
        refs = {(row[3], row[2], row[4]) for row in db.execute("PRAGMA foreign_key_list(label_packages)")}
        assert ("tenant_id", "tenants", "id") in refs
        assert ("product_id", "products", "id") in refs
        assert ("shop_id", "shops", "id") in refs
        assert ("run_id", "workflow_runs", "id") in refs
        db.execute("""INSERT INTO label_packages(tenant_id,product_id,shop_id,run_id,step_code,
                   destination_country,version,action,content,content_digest,basis,
                   basis_fingerprint,open_items,created_by,created_at)
                   VALUES(1,1,1,1,'LABEL_PREPARATION','EU',1,'GENERATE','{}','d1','{}','fp1','[]',1,'2026-11-07')""")
        # 同一 (商品, 店铺, 目的国, 版本号) 必须被唯一约束挡住（并发下的兜底）
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute("""INSERT INTO label_packages(tenant_id,product_id,shop_id,run_id,step_code,
                       destination_country,version,action,content,content_digest,basis,
                       basis_fingerprint,open_items,created_by,created_at)
                       VALUES(1,1,1,1,'LABEL_PREPARATION','EU',1,'REGENERATE','{}','d2','{}','fp2','[]',1,'2026-11-07')""")
        # 版本号递增即可写入（只增不改）
        db.execute("""INSERT INTO label_packages(tenant_id,product_id,shop_id,run_id,step_code,
                   destination_country,version,action,content,content_digest,basis,
                   basis_fingerprint,open_items,created_by,created_at)
                   VALUES(1,1,1,1,'LABEL_PREPARATION','EU',2,'REGENERATE','{}','d2','{}','fp2','[]',1,'2026-11-07')""")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    # 有标签包历史 → 拒绝有损降级
    refused = _command(target, "-m", "alembic", "downgrade", "20261107_32", success=False)
    assert "拒绝有损降级" in refused.stderr
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT count(*) FROM label_packages").fetchone() == (2,)

    # 清空后可以真正回滚，表消失；再次升级仍然成功（幂等）
    with sqlite3.connect(target) as db:
        db.execute("DELETE FROM label_packages")
    _command(target, "-m", "alembic", "downgrade", "20261107_32")
    with sqlite3.connect(target) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "label_packages" not in names
    _command(target, "-m", "alembic", "upgrade", "20261107_33")
    with sqlite3.connect(target) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "label_packages" in names
