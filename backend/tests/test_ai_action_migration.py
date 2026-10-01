"""D47 AI Action 迁移在隔离临时库上的升级/回滚验证。"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.db import Base
from app.models import AiAction

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_ai_actions_migration_roundtrip(tmp_path):
    """从迁移前 schema 升级，降级删表，再升级；不使用业务主库。"""
    path = tmp_path / "action_migration.db"
    url = "sqlite:///" + path.as_posix()
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    AiAction.__table__.drop(engine)
    engine.dispose()

    env = {**os.environ, "ERP_DB_URL": url}

    def alembic(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR,
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert result.returncode == 0, result.stdout + result.stderr

    alembic("stamp", "20260927_17")
    alembic("upgrade", "head")
    engine = create_engine(url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("ai_actions")}
        assert {"workspace_id", "tenant_id", "idempotency_key", "status",
                "approved_by", "executed_at"} <= columns
        foreign_keys = inspect(engine).get_foreign_keys("ai_actions")
        assert any(key["constrained_columns"] == ["tenant_id"]
                   and key["referred_table"] == "tenants"
                   and key["referred_columns"] == ["id"] for key in foreign_keys)
    finally:
        engine.dispose()

    # 新增迁移后 head 的直接前驱不再是 Action 建表前版本，固定验证 D47 回滚边界。
    alembic("downgrade", "20260927_17")
    engine = create_engine(url)
    try:
        assert not inspect(engine).has_table("ai_actions")
    finally:
        engine.dispose()

    alembic("upgrade", "head")
    engine = create_engine(url)
    try:
        assert inspect(engine).has_table("ai_actions")
    finally:
        engine.dispose()
