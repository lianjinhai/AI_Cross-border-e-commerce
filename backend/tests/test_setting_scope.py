"""P1-10 配置作用域隔离回归测试。

固化「settings 表无租户维度」这一历史漏洞的修复效果：
  - 租户管理员改写 platform_fees / fx / rules 只影响本租户；
  - 平台级 key（llm / open_1688）仅平台服务商可写；
  - 读取按「租户覆盖 → 平台默认 → 代码默认」三级回退。

会话级夹具由 tests/conftest.py 自动注入，本模块不 import 其它测试模块（规范 §8 T-2）。
"""


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _superadmin(client):
    return _login(client, "root", "root-test-123")


def test_tenant_setting_write_is_isolated(client, auth_headers):
    """租户 A 改 rules 不得影响租户 B（历史漏洞的核心回归点）。"""
    sa = _superadmin(client)
    # 开一个新租户 B
    r = client.post("/api/admin/tenants", headers=sa,
                    json={"name": "配置隔离B", "license_days": 365,
                          "admin_username": "cfg_b", "admin_password": "cfg-b-pass-123"})
    assert r.status_code == 200, r.text
    hb = _login(client, "cfg_b", "cfg-b-pass-123")

    # B 先确认基线（继承平台默认值）
    base_b = client.get("/api/ai/settings", headers=hb).json()["rules"]
    assert base_b["target_margin"] == 0.35

    # A（演示租户 admin）改本租户 rules
    r = client.put("/api/ai/settings", headers=auth_headers,
                   json={"rules": {"target_margin": 0.99}})
    assert r.status_code == 200, r.text
    assert r.json()["rules"]["target_margin"] == 0.99

    # B 的 rules 必须**不受影响**
    after_b = client.get("/api/ai/settings", headers=hb).json()["rules"]
    assert after_b["target_margin"] == 0.35, f"跨租户污染：B 的 target_margin={after_b['target_margin']}"

    # A 自己读到的仍是 0.99（覆盖生效）
    assert client.get("/api/ai/settings", headers=auth_headers).json()["rules"]["target_margin"] == 0.99

    # 还原 A 的覆盖，避免影响其他用例
    client.put("/api/ai/settings", headers=auth_headers,
               json={"rules": {"target_margin": 0.35}})


def test_platform_key_write_requires_superadmin(client, auth_headers):
    """平台级 key（llm / open_1688）租户管理员不可写。"""
    for payload, label in (({"llm": {"model": "x"}}, "llm"),
                           ({"open_1688": {"app_key": "k"}}, "open_1688")):
        r = client.put("/api/ai/settings", headers=auth_headers, json=payload)
        assert r.status_code == 403, f"{label} 应被拒绝，实际 {r.status_code}"
        assert "平台" in r.json()["detail"]


def test_setting_three_level_fallback(client, auth_headers):
    """三级回退：租户无覆盖时读平台默认值；平台未设置时读代码默认。"""
    from app.db import SessionLocal
    from app.models import Setting, TenantSetting
    from app.services import settings_service

    db = SessionLocal()
    try:
        # 找一个没有租户覆盖的 key（用 fx 的 EUR，测试库中通常无覆盖）
        tenant_id = 1
        row = (db.query(TenantSetting)
               .filter(TenantSetting.tenant_id == tenant_id, TenantSetting.key == "fx")
               .first())
        # 删除前先快照：原实现直接 db.delete 且不还原，会永久破坏"租户级覆盖"
        # 状态，导致后续断言租户覆盖生效的用例误判（规范 §8 T-2 隔离要求）。
        snapshot = None
        if row is not None:
            snapshot = {"tenant_id": row.tenant_id, "key": row.key,
                        "value": row.value}
        if row is not None:
            db.delete(row)
            db.commit()
        # 平台级 fx 存在 → 来源应为 platform
        assert settings_service.get_setting_source(db, tenant_id, "fx") in ("platform", "default")
        # 无租户覆盖时应回退到平台级（settings 表）的值
        platform_fx = db.get(Setting, "fx")
        got = settings_service.get_setting(db, tenant_id, "fx")
        if platform_fx and isinstance(platform_fx.value, dict):
            for k, v in platform_fx.value.items():
                assert got[k] == v
        # 未知 key 走代码默认（空字典）
        assert settings_service.get_setting(db, tenant_id, "__not_exist__") == {}
    finally:
        if snapshot is not None:
            db.add(TenantSetting(**snapshot))
            db.commit()
        db.close()


def test_tenant_setting_rejects_platform_key(client):
    """服务层必须拒绝把平台级 key 写入 tenant_settings（防止绕过路由直调）。"""
    from app.db import SessionLocal
    from app.services import settings_service

    db = SessionLocal()
    try:
        for key in ("llm", "1688_api", "__unknown__"):
            try:
                settings_service.set_tenant_setting(db, 1, key, {"x": 1})
                raise AssertionError(f"{key} 不应允许写入 tenant_settings")
            except ValueError:
                pass
        db.rollback()
    finally:
        db.close()


def test_platform_default_is_inherited_by_new_tenant(client):
    """平台服务商改写平台默认值后，未覆盖的租户应继承该新默认值。"""
    sa = _superadmin(client)
    original = client.get("/api/ai/settings", headers=sa).json()["fx"]
    try:
        r = client.put("/api/ai/settings", headers=sa, json={"fx": {"USD": 7.77}})
        assert r.status_code == 200, r.text
        # 开新租户 C，未做任何覆盖，应继承 7.77
        r = client.post("/api/admin/tenants", headers=sa,
                        json={"name": "配置继承C", "license_days": 365,
                              "admin_username": "cfg_c", "admin_password": "cfg-c-pass-123"})
        assert r.status_code == 200, r.text
        hc = _login(client, "cfg_c", "cfg-c-pass-123")
        assert client.get("/api/ai/settings", headers=hc).json()["fx"]["USD"] == 7.77
    finally:
        client.put("/api/ai/settings", headers=sa, json={"fx": original})
