"""身份快照契约测试：`/api/auth/*` 的响应形状与代客态隔离。

为什么单独建文件而不是塞进 test_security.py / test_api.py：
    这两个文件已分别到 262 / 1137 行，`test_api.py` 早已越过 500 行硬上限。
    规范 §6 的模块规模要求「只减不增」，新用例必须另开文件。

本模块守的缺陷（历史 P0）：
    代客访问时 `get_current_user` 返回的是 `_ImpersonatedUser`（鸭子类型替身，
    没有 `__table__`），而 `/api/auth/me` 直接把它喂给 `serialize.to_dict`，
    于是**代客态一调就 500**。普通登录态测不出来——那时拿到的是真 ORM 行，
    所以这条路径长期零覆盖，直到真启动服务走代客链路才暴露。
"""
from app.db import SessionLocal
from app.models import User


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _impersonated_headers(client) -> tuple[dict, int]:
    """root 代客进入演示租户，返回（代客请求头, 目标租户 id）。"""
    root = _login(client, "root", "root-test-123")
    tenants = client.get("/api/admin/tenants", headers=root).json()
    tenant_id = tenants["items"][0]["id"]
    entered = client.post(f"/api/admin/tenants/{tenant_id}/enter", headers=root)
    assert entered.status_code == 200, entered.text
    return {"Authorization": f"Bearer {entered.json()['token']}"}, tenant_id


def test_impersonated_auth_me_does_not_crash(client):
    """P0 回归：代客态 `/api/auth/me` 必须 200，且身份钉在目标租户。

    判别力说明（DP-5）：修复前此断言必然失败（500 AttributeError），
    回退验证见 docs/DECISIONS.md 本轮记录。
    """
    headers, tenant_id = _impersonated_headers(client)

    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "operator", body
    assert body["tenant_id"] == tenant_id, body
    assert body["is_impersonating"] is True, body


def test_impersonated_auth_me_does_not_leak_platform_identity(client):
    """代客态不得泄露平台 superadmin 身份（否则前端会放行 /platform-admin）。

    前端 legacy 兜底按 `role` 判定：若这里返回 `superadmin`，代客会话会被当成
    平台本尊，代客隔离失效（见 docs/DECISIONS.md D19）。
    """
    headers, _ = _impersonated_headers(client)
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "password_hash" not in body, body
    assert body["role"] != "superadmin", body
    # 平台账号的用户名会出现在 username 字段（审计需要），但角色绝不能是平台角色
    assert "superadmin" not in r.text.replace("is_impersonating", ""), r.text


def test_plain_auth_me_has_no_impersonation_marker(client, auth_headers):
    """普通登录态不得带 `is_impersonating`（否则前端会误显示「返回平台控制台」）。"""
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "is_impersonating" not in body, body
    assert "password_hash" not in body, body
    assert body["role"] == "admin", body


def test_identity_snapshot_handles_both_identity_shapes(client):
    """`identity_snapshot()` 必须同时吃 ORM 行与代客替身（统一收口点）。

    直接测函数而非只测端点：这是「新增身份形态时唯一要改的地方」，
    端点测试无法防止将来新增第三种形态时漏改。
    """
    from app.auth import _ImpersonatedUser, identity_snapshot

    with SessionLocal() as db:
        operator = db.query(User).filter(User.username == "root").first()
        assert operator is not None
        orm_snapshot = identity_snapshot(operator)
        impersonated = _ImpersonatedUser(operator, tenant_id=1)
        imp_snapshot = identity_snapshot(impersonated)

    # 两种形态的字段集必须一致（除代客标记），避免前端要分情况解析
    assert set(orm_snapshot) | {"is_impersonating"} == set(imp_snapshot), (
        f"身份快照字段集漂移: {set(orm_snapshot) ^ set(imp_snapshot)}")
    assert "password_hash" not in orm_snapshot
    assert "password_hash" not in imp_snapshot
    # 代客快照必须钉在目标租户，且角色降为 operator
    assert imp_snapshot["tenant_id"] == 1
    assert imp_snapshot["role"] == "operator"
    assert orm_snapshot["role"] == "superadmin"  # 本尊仍是平台角色


def test_impersonation_flag_is_detected_by_single_entry_point(client):
    """代客标记的唯一判定点必须对两种身份都给出正确答案。

    为什么单独测这个函数：代客标记曾散落在各调用点手写 ``getattr``，
    历史上漏过两次（``me.py`` 两个端点、``require_permission``）。漏传时
    ``resolve_workspace_context`` 会把代客态误判成 Platform 身份
    （``workspace_id=None`` + ``permissions=['platform:admin']``）。

    当前漏传**恰好**不出事，因为替身 ``role`` 正好是 ``operator``；
    这是「依赖巧合」而非「正确」。本用例把判定点钉死，防止将来替身
    角色改名/改语义时静默错乱。
    """
    from app.auth import _ImpersonatedUser, is_impersonating_user
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        operator = db.query(User).filter(User.username == "root").first()
        assert operator is not None
        assert is_impersonating_user(operator) is False, "本尊被误判为代客"
        assert is_impersonating_user(_ImpersonatedUser(operator, tenant_id=1)) is True


def test_require_permission_sees_impersonated_context(client):
    """`require_permission` 必须把代客标记透传给 Context 解析（结构性契约）。

    为什么用「拦截解析调用」而不是走端点断言：代客替身的 `role` 当前**恰好**
    是 `operator`，漏传标记时 `resolve_workspace_context` 会落到 LEGACY 分支，
    算出的权限集合与透传时**完全相同**——端点状态码毫无差异（实测：把透传删掉
    后 `POST /api/compliance/check` 仍是 404，断言抓不到）。换句话说，
    「今天不出事」靠的是巧合，而非正确。

    唯一有判别力的写法是**直接调用依赖函数本身**（`require_permission(...)`
    返回的 `_dep`）：透传标记时放行，漏传时代客态被解析成 Platform 身份
    （`permissions={'platform:admin'}`）、`compliance:check` 不在集合内 → 403。
    回退验证：删掉透传 → 本用例立刻变红。

    为什么不用真实端点断言：端点返回值**无法区分**这两种情况（实测漏传时
    `POST /api/compliance/check` 仍返回 404），因为 legacy 兜底恰好也算出
    OPERATOR 权限。这正是「依赖巧合」的实证。

    危害说明（为何值得守）：一旦替身角色改为保留原角色（或改名），漏传标记
    会让代客态解析成 `PLATFORM_ADMIN` + `workspace_id=None` +
    `permissions={'platform:admin'}`，代客业务端点全线 403/错乱。
    """
    headers, _ = _impersonated_headers(client)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["is_impersonating"] is True, me

    from app.auth import _ImpersonatedUser, require_permission
    from app.services import workspace_context as wc
    from app.services.workspace_context import (
        ROLE_OPERATOR,
        ROLE_PLATFORM_ADMIN,
    )

    with SessionLocal() as db:
        operator = db.query(User).filter(User.username == "root").first()
        impersonated = _ImpersonatedUser(operator, tenant_id=1)

        # 1) 结构性断言：捕获 `require_permission` 实际传给解析函数的标记。
        #
        # 补丁必须在**创建依赖之前**打：`require_permission` 在自身函数体内
        # `from .services.workspace_context import resolve_workspace_context`，
        # 该名字在调用 `require_permission(...)` 时绑定为 `_dep` 的闭包变量。
        # 在依赖已创建后再打补丁不会生效（实测：捕获为空）。
        original = wc.resolve_workspace_context
        captured = {}

        def _spy(db_, user_, trace_id=None, is_impersonating=False):
            captured["flag"] = is_impersonating
            return original(db_, user_, trace_id, is_impersonating=is_impersonating)

        wc.resolve_workspace_context = _spy
        try:
            dep = require_permission("compliance:check",
                                     ("admin", "operator", "compliance_approver"))
            assert dep(user=impersonated, db=db) is impersonated
        finally:
            wc.resolve_workspace_context = original
        assert captured.get("flag") is True, (
            "require_permission 未透传代客标记：代客态 Context 会被解析成平台身份")

        # 2) 语义证据：漏传标记时**当前**就可观测到的错误。
        #
        # 替身 role 固定为 operator，故漏传时仍会落到 LEGACY 分支、算出同样的
        # OPERATOR 权限（这就是「依赖巧合」：权限结果对，但语义错），唯一差异
        # 是 `is_impersonating` 恒为 False —— 前端据此无法显示「返回平台控制台」。
        real_no_flag = wc.resolve_workspace_context(db, impersonated)
        assert real_no_flag.is_impersonating is False, real_no_flag
        real_with_flag = wc.resolve_workspace_context(
            db, impersonated, is_impersonating=True)
        assert real_with_flag.is_impersonating is True, real_with_flag
        assert real_with_flag.role == ROLE_OPERATOR, real_with_flag
        assert real_with_flag.workspace_id == 1, real_with_flag
        assert real_with_flag.has("compliance:check"), real_with_flag

        # 3) 未来风险证据：一旦替身改为**保留平台角色**，漏传标记会直接解析成
        # 平台身份（workspace_id=None + 只有 platform:admin），代客业务端点全线
        # 403/错乱。本断言把这个「巧合失效」的后果固定下来。
        class _RolePreservingProxy(_ImpersonatedUser):
            def __init__(self, op, tenant_id):
                super().__init__(op, tenant_id)
                self.role = op.role  # 保留 superadmin

        proxy = _RolePreservingProxy(operator, tenant_id=1)
        leaked = wc.resolve_workspace_context(db, proxy)
        assert leaked.role == ROLE_PLATFORM_ADMIN, leaked
        assert leaked.workspace_id is None, leaked
        assert not leaked.has("compliance:check"), leaked

    # 3) 端到端兜底：代客态调该端点不得被权限层拦下（403）
    r = client.post("/api/compliance/check", headers=headers,
                    json={"target_type": "product", "ref_id": 999999})
    assert r.status_code != 403, (
        f"代客态被当成平台身份拦下（require_permission 漏传代客标记）: {r.text}")
