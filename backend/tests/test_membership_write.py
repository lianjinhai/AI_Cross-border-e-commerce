"""Membership 写入侧契约测试（Phase 1.8 收口）。

为什么单独建文件：本轮修的是**三个同源缺陷**，根因都是「身份表只有读取侧、
没有写入侧」。把它们放在一起，是为了让后来者一眼看到「写侧是成套的」，
避免只补其中一个（例如只补新建、漏掉改角色同步）。

三个缺陷（均为真服务/真库实测）：
    1. `POST /api/admin/tenants` 不建 `workspace_profiles`
       → 新租户永远 `source=LEGACY_FALLBACK`；
    2. `POST /api/auth/users` 不建 `workspace_memberships` → 新用户同上；
    3. `PUT /api/auth/users/{id}` 改角色只写 `users.role`
       → MEMBERSHIP 是权威路径，**降权被静默忽略**（安全缺陷）；
    4. `DELETE /api/auth/users/{id}` 撞 `FK → users.id` → 500。

规范约束：模块规模 300 行警戒；本文件按「一个缺陷一组断言」组织。
"""
from sqlalchemy import text

from app.db import SessionLocal
from app.models import User


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _context(client, username: str, password: str) -> dict:
    r = client.get("/api/me/workspace-context", headers=_login(client, username, password))
    assert r.status_code == 200, r.text
    return r.json()


def _membership_rows(user_id: int) -> list[tuple]:
    with SessionLocal() as db:
        return list(db.execute(text(
            "SELECT role_key, status, source FROM workspace_memberships WHERE user_id = :u"),
            {"u": user_id}).all())


def _user_id(username: str) -> int:
    with SessionLocal() as db:
        row = db.query(User).filter(User.username == username).first()
        assert row is not None, f"用户 {username} 不存在"
        return row.id


def _delete_user(client, headers: dict, username: str) -> None:
    """清理探针账号（幂等：不存在则跳过）。"""
    with SessionLocal() as db:
        row = db.query(User).filter(User.username == username).first()
        if row is None:
            return
        uid = row.id
    client.delete(f"/api/auth/users/{uid}", headers=headers)


def test_new_tenant_gets_membership_context(client, auth_headers):
    """新开通的租户必须有 MEMBERSHIP Context（不能掉到 LEGACY_FALLBACK）。

    判别力说明（DP-5）：修复前该租户无 `workspace_profiles` 行，
    `source` 恒为 `LEGACY_FALLBACK`，断言必然失败。
    """
    root = _login(client, "root", "root-test-123")
    r = client.post("/api/admin/tenants", headers=root, json={
        "name": "mt-new-tenant", "license_days": 30,
        "admin_username": "mt_new_admin", "admin_password": "mt-pass-123"})
    assert r.status_code == 200, r.text
    tenant_id = r.json()["id"]

    ctx = _context(client, "mt_new_admin", "mt-pass-123")
    assert ctx["source"] == "MEMBERSHIP", f"新租户未拿到 MEMBERSHIP Context: {ctx}"
    assert ctx["role"] == "OWNER", ctx
    assert ctx["workspace_id"] == tenant_id, ctx
    assert ctx["permissions"], "OWNER 必须有权限集合"


def test_new_user_gets_membership(client, auth_headers):
    """租户内新建用户必须同时建 Membership（否则新账号失去身份来源）。"""
    r = client.post("/api/auth/users", headers=auth_headers, json={
        "username": "mt_new_user", "password": "mt-pass-123", "role": "operator"})
    assert r.status_code == 200, r.text
    try:
        rows = _membership_rows(r.json()["id"])
        assert len(rows) == 1, f"新建用户 Membership 行数应为 1: {rows}"
        assert rows[0][0] == "OPERATOR", rows
        assert rows[0][1] == "ACTIVE", rows

        ctx = _context(client, "mt_new_user", "mt-pass-123")
        assert ctx["source"] == "MEMBERSHIP", ctx
        assert ctx["role"] == "OPERATOR", ctx
    finally:
        _delete_user(client, auth_headers, "mt_new_user")


def test_role_change_propagates_to_membership(client, auth_headers):
    """改角色必须同步 Membership.role_key——否则降权被静默忽略（安全缺陷）。

    判别力说明（DP-5）：修复前只写 `users.role`，MEMBERSHIP 权威路径继续下发
    **旧角色**权限（实测 operator 降为 viewer 后 Context 仍返回 OPERATOR）。
    """
    r = client.post("/api/auth/users", headers=auth_headers, json={
        "username": "mt_role_user", "password": "mt-pass-123", "role": "operator"})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    try:
        assert _context(client, "mt_role_user", "mt-pass-123")["role"] == "OPERATOR"

        put = client.put(f"/api/auth/users/{uid}", headers=auth_headers,
                         json={"role": "viewer"})
        assert put.status_code == 200, put.text

        rows = _membership_rows(uid)
        assert rows and rows[0][0] == "READ_ONLY", f"降权未同步到 Membership: {rows}"
        ctx = _context(client, "mt_role_user", "mt-pass-123")
        assert ctx["role"] == "READ_ONLY", f"降权未生效（仍下发旧角色）: {ctx}"
        assert "order:write" not in ctx["permissions"], ctx
    finally:
        _delete_user(client, auth_headers, "mt_role_user")


def test_delete_user_with_membership_succeeds(client, auth_headers):
    """删除有 Membership 的用户必须成功（FK → users.id 需先清理身份行）。

    判别力说明（DP-5）：修复前直接 `DELETE FROM users` 触发
    `FOREIGN KEY constraint failed`（实测 500）。
    """
    r = client.post("/api/auth/users", headers=auth_headers, json={
        "username": "mt_del_user", "password": "mt-pass-123", "role": "viewer"})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    assert _membership_rows(uid), "前置条件：该用户应有 Membership"

    d = client.delete(f"/api/auth/users/{uid}", headers=auth_headers)
    assert d.status_code == 200, f"删除撞外键: {d.text}"

    with SessionLocal() as db:
        assert db.query(User).filter(User.id == uid).first() is None
        left = db.execute(text(
            "SELECT COUNT(*) FROM workspace_memberships WHERE user_id = :u"),
            {"u": uid}).scalar()
    assert left == 0, f"身份行未随账号清理，残留 {left} 行"


def test_factory_account_has_no_membership_and_deletes(client, auth_headers):
    """工厂门户账号不生成 Membership（它不属于业务 Workspace），且能正常删除。

    与迁移 20260923_08 的回填规则一致：`supplier` 不回填 Membership。
    删账号时 `supplier_portal_members.user_id`（同样 FK → users.id）也必须清理。
    """
    suppliers = client.get("/api/suppliers", headers=auth_headers,
                           params={"page_size": 1}).json()["items"]
    assert suppliers, "测试库缺少供应商种子数据"
    r = client.post(
        f"/api/factory-network/suppliers/{suppliers[0]['id']}/portal-account",
        headers=auth_headers,
        json={"username": "mt_portal", "password": "mt-pass-123"})
    assert r.status_code == 200, r.text
    uid = r.json()["user_id"]
    try:
        assert _membership_rows(uid) == [], "工厂账号不应有 Membership"
    finally:
        d = client.delete(f"/api/auth/users/{uid}", headers=auth_headers)
        assert d.status_code == 200, f"删除工厂账号撞外键: {d.text}"

    with SessionLocal() as db:
        left = db.execute(text(
            "SELECT COUNT(*) FROM supplier_portal_members WHERE user_id = :u"),
            {"u": uid}).scalar()
    assert left == 0, f"门户绑定未随账号清理，残留 {left} 行"
