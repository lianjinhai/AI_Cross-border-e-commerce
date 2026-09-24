"""ERP_ADMIN_PASSWORD 必须真正生效（回归测试）。

背景（真实安全缺陷）：
    ``auth.admin_bootstrap_password()`` 定义了却从未被调用，而种子固定写入
    ``hash_password("admin123")``。结果是：生产环境 ``validate_production_settings()``
    要求配置强 ``ERP_ADMIN_PASSWORD``（否则拒绝启动），但该口令从未用于创建或更新
    admin 账号——门禁"看起来合规"，实际仍可用 ``admin123`` 登录。

    修复：``seed._ensure_admin_password()`` 在启动时把演示租户 admin 的口令对齐为
    ``ERP_ADMIN_PASSWORD``；未配置或仍为 admin123 时保持演示默认，不做改动。

本文件固化三条契约：配置生效、默认值不破坏演示、只影响 admin 账号。

会话级夹具由 tests/conftest.py 自动注入（pytest 保证 conftest 先于所有测试模块
加载），故本文件即使排序在 test_api.py 之前，也不会出现「先建连接导致测试库
无法删除」的 Windows WinError 32 问题（规范 §8 T-2）。

数据隔离：本文件的用例会改写 admin 口令并递增 ``token_version``（改口令即撤销
既有 token）。两者都由自动夹具 ``_isolate_admin_account`` 在每个用例结束后还原，
即使断言失败也不会把污染留给同会话内的其它文件（规范 §8 T-2）。
"""
import pytest


def _ensure_admin_password(db):
    from app.seed import _ensure_admin_password as fn

    return fn(db)


@pytest.fixture(autouse=True)
def _isolate_admin_account(client):  # noqa: ARG001  依赖 client 以确保种子已就绪
    """快照并还原演示 admin 的口令散列与 token 版本号。

    显式关闭会话：Windows 下残留未关闭的 SQLite 连接会让会话级夹具无法删除
    测试库文件（PermissionError: WinError 32）。
    """
    from app.db import SessionLocal
    from app.models import User

    def _admin(db):
        return db.query(User).filter(User.username == "admin",
                                     User.role == "admin").first()

    with SessionLocal() as db:
        admin = _admin(db)
        assert admin is not None, "种子数据缺少演示 admin 账号"
        snapshot = (admin.password_hash, int(admin.token_version or 0))

    yield

    with SessionLocal() as db:
        admin = _admin(db)
        admin.password_hash, admin.token_version = snapshot
        db.commit()


def test_admin_password_env_is_applied_and_default_rejected(client, monkeypatch):
    """设置 ERP_ADMIN_PASSWORD 后：新口令可登录，默认口令被拒。"""
    from app.db import SessionLocal

    monkeypatch.setenv("ERP_ADMIN_PASSWORD", "Strong-Admin-Pass-987")
    with SessionLocal() as db:
        _ensure_admin_password(db)

    ok = client.post("/api/auth/login",
                     json={"username": "admin", "password": "Strong-Admin-Pass-987"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["token"]

    denied = client.post("/api/auth/login",
                         json={"username": "admin", "password": "admin123"})
    assert denied.status_code == 400, "默认口令必须失效（否则门禁形同虚设）"


def test_admin_password_unset_keeps_demo_default(client, monkeypatch):
    """未配置 ERP_ADMIN_PASSWORD：保持演示默认口令，不得把 admin 锁死。"""
    from app.db import SessionLocal

    monkeypatch.delenv("ERP_ADMIN_PASSWORD", raising=False)
    with SessionLocal() as db:
        _ensure_admin_password(db)

    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text


def test_admin_password_change_bumps_token_version(client, monkeypatch):
    """改口令必须使既有 token 失效（token_version 递增），避免旧会话残留。"""
    from app.db import SessionLocal
    from app.models import User

    before = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    old_headers = {"Authorization": f"Bearer {before.json()['token']}"}
    assert client.get("/api/auth/me", headers=old_headers).status_code == 200

    monkeypatch.setenv("ERP_ADMIN_PASSWORD", "Another-Strong-Pass-654")
    with SessionLocal() as db:
        _ensure_admin_password(db)
        version_after = db.query(User).filter(User.username == "admin").first().token_version
    assert int(version_after or 0) >= 1

    assert client.get("/api/auth/me", headers=old_headers).status_code == 401
