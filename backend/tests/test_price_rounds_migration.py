"""Revision 32（M2-A 报价轮次）迁移可逆性：建表可回滚、重复轮次号被唯一约束挡住、
有数据时拒绝有损降级。

为什么要单独验：核价历史是审计凭据，迁错了不是「少一列」，而是**报价记录丢失**。
这里用合成历史库走真实 alembic，不碰业务主库。
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


def test_price_rounds_migration_is_reversible(tmp_path):
    assert code_head() == "20261107_32" or code_head() > "20261107_32"
    target = tmp_path / "price-rounds.db"
    with sqlite3.connect(target) as db:
        db.executescript("""
            CREATE TABLE tenants(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE products(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), title TEXT);
            CREATE TABLE workflow_runs(id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id));
            CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
            INSERT INTO alembic_version VALUES('20261106_31');
            INSERT INTO tenants VALUES(1,'price history');
            INSERT INTO products VALUES(1,1,'核价商品');
            INSERT INTO workflow_runs VALUES(1,1);
        """)

    _command(target, "-m", "alembic", "upgrade", "20261107_32")
    with sqlite3.connect(target) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(price_rounds)")}
        assert {"tenant_id", "product_id", "run_id", "round_no", "action", "price", "currency",
                "margin", "min_margin", "margin_ok", "cost_snapshot", "cost_fingerprint",
                "decision", "created_by", "created_at"} <= columns
        refs = {(row[3], row[2], row[4]) for row in db.execute("PRAGMA foreign_key_list(price_rounds)")}
        assert ("tenant_id", "tenants", "id") in refs
        assert ("run_id", "workflow_runs", "id") in refs
        db.execute("""INSERT INTO price_rounds(tenant_id,product_id,run_id,step_code,round_no,action,
                   price,currency,margin,min_margin,margin_ok,cost_snapshot,cost_fingerprint,
                   decision,created_by,created_at)
                   VALUES(1,1,1,'PRICE_REVIEW',1,'REPORT',9.9,'USD',0.3,0.15,1,'{}','fp','{}',1,'2026-11-07')""")
        # 同一商品同一轮次号必须被唯一约束挡住（并发下的兜底）
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute("""INSERT INTO price_rounds(tenant_id,product_id,run_id,step_code,round_no,
                       action,price,currency,margin,min_margin,margin_ok,cost_snapshot,
                       cost_fingerprint,decision,created_by,created_at)
                       VALUES(1,1,1,'PRICE_REVIEW',1,'COUNTER',10.9,'USD',0.32,0.15,1,'{}','fp2','{}',1,'2026-11-07')""")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    # 有报价历史 → 拒绝有损降级
    refused = _command(target, "-m", "alembic", "downgrade", "20261106_31", success=False)
    assert "拒绝有损降级" in refused.stderr
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT count(*) FROM price_rounds").fetchone() == (1,)

    # 清空后可以真正回滚，表消失；再次升级仍然成功（幂等）
    with sqlite3.connect(target) as db:
        db.execute("DELETE FROM price_rounds")
    _command(target, "-m", "alembic", "downgrade", "20261106_31")
    with sqlite3.connect(target) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "price_rounds" not in names
    _command(target, "-m", "alembic", "upgrade", "20261107_32")
    with sqlite3.connect(target) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "price_rounds" in names
