"""契约守护：E2E只能迁移指定隔离副本，P0拒绝后不能继续启动。"""

import sqlite3
from types import SimpleNamespace

import pytest

from scripts import e2e_feasibility as e2e


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e, "_BACKEND_DIR", tmp_path)
    work = tmp_path / "backups" / "e2e_feasibility"
    work.mkdir(parents=True)
    target = work / "e2e.db"
    with sqlite3.connect(target) as db:
        db.executescript("CREATE TABLE alembic_version(version_num TEXT);"
                         "INSERT INTO alembic_version VALUES('20260930_18');")
    return target, {"ERP_DB_URL": "sqlite:///" + target.as_posix()}


@pytest.mark.parametrize("at_head", [False, True])
def test_copy_upgrade_and_current_head_both_require_preflight(isolated, monkeypatch, at_head):
    target, env = isolated
    if at_head:
        with sqlite3.connect(target) as db:
            db.execute("UPDATE alembic_version SET version_num='20261001_19'")
    calls = []

    def command(args, **kwargs):
        assert kwargs["env"]["ERP_DB_URL"] == env["ERP_DB_URL"]
        calls.append(args)
        if "upgrade" in args:
            with sqlite3.connect(target) as db:
                db.execute("UPDATE alembic_version SET version_num='20261001_19'")
        return SimpleNamespace(returncode=0, stdout="20261001_19 (head)\n", stderr="")

    monkeypatch.setattr(e2e.subprocess, "run", command)
    e2e._upgrade_isolated_db(target, env)
    preflights = [args for args in calls if "scripts/migration_preflight.py" in args]
    assert len(preflights) == 2
    assert ("--planned-upgrade" in preflights[0]) is (not at_head)
    assert "--planned-upgrade" not in preflights[-1]
    assert any("upgrade" in args for args in calls) is (not at_head)
    with sqlite3.connect(target.with_name("e2e-pre-migration.db")) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            "20261001_19" if at_head else "20260930_18")


def test_p0_preflight_stops_copy_upgrade(isolated, monkeypatch):
    target, env = isolated
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0 if "heads" in args else 2,
                               stdout="20261001_19 (head)\n", stderr="")

    monkeypatch.setattr(e2e.subprocess, "run", command)
    with pytest.raises(RuntimeError, match="预检失败"):
        e2e._upgrade_isolated_db(target, env)
    assert not any("upgrade" in args for args in calls)


def test_other_database_and_mismatched_env_never_migrate(isolated):
    target, env = isolated
    with pytest.raises(RuntimeError, match="拒绝迁移"):
        e2e._upgrade_isolated_db(target, {"ERP_DB_URL": "sqlite:///wrong.db"})
    other = target.parents[2] / "another-business.db"
    with pytest.raises(RuntimeError, match="拒绝迁移"):
        e2e._upgrade_isolated_db(other, {"ERP_DB_URL": "sqlite:///" + other.as_posix()})
    assert not other.exists()
