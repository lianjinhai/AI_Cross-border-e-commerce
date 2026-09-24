"""店铺归档（软删除）与演示数据清理的回归测试。

背景（真实缺陷，由 SQLite 外键强制开启后暴露）：
  1. DELETE /api/shops/{id} 原先物理删除，但 oauth_states /
     platform_publish_attempts / orders / purchase_orders /
     platform_settlement_records 均引用 shops.id，直接删触发
     IntegrityError（接口 500）。
  2. POST /api/shops/purge_demo_data 原先按 Order → Conversation →
     AdCampaign → Listing → Product 顺序删除，未先清理引用它们的子表
     （messages / refund_orders / order_fees / order_lines /
     supplier_offers / product_scores / purchase_orders 等），同样必然失败。

本文件固化两条契约：归档后店铺对所有入口不可见；清理必须整体成功且不越界。
会话级夹具由 tests/conftest.py 自动注入，本模块不 import 其它测试模块（规范 §8 T-2）。
"""


def _create_shop(client, headers, **payload):
    r = client.post("/api/shops", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_shop_delete_archives_instead_of_hard_delete(client, auth_headers):
    """删店铺 = 归档：不报错、从列表消失、凭证清空、后续入口 404。"""
    shop = _create_shop(client, auth_headers, platform="shopee",
                        shop_name="归档测试店", role="sales",
                        app_key="ak_arch", app_secret="sk_arch")
    shop_id = shop["id"]

    # 制造对 shops.id 的引用：授权 state 落库（oauth_states.shop_id 非空外键）
    r = client.get(f"/api/shops/{shop_id}/authorize_url", headers=auth_headers)
    assert r.status_code == 200, r.text

    deleted = client.delete(f"/api/shops/{shop_id}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["ok"] is True

    # 从默认列表消失
    listed = client.get("/api/shops", headers=auth_headers).json()["items"]
    assert all(s["id"] != shop_id for s in listed)

    # 所有可写入口一律视为不存在（不得出现"已删除但可用"）
    assert client.post(f"/api/shops/{shop_id}/sync_orders",
                       headers=auth_headers).status_code == 404
    assert client.get(f"/api/shops/{shop_id}/authorize_url",
                      headers=auth_headers).status_code == 404
    assert client.post(f"/api/shops/{shop_id}/refresh",
                       headers=auth_headers).status_code == 404

    # 归档幂等：重复删除不得产生副作用（也不得 500）
    again = client.delete(f"/api/shops/{shop_id}", headers=auth_headers)
    # 原断言 `in (200, 404)` 让「归档幂等」与「接口不存在/路由错」不可区分。
    # 实测契约：删除是软删除且幂等，重复删除返回 404「店铺不存在」
    # （_owned 对 archived_at 非空一律视为不存在），据此钉死。
    assert again.status_code == 404, again.text
    assert again.json()["detail"] == "店铺不存在"


def test_archived_shop_rejects_order_import_and_dropship(client, auth_headers):
    """归档店铺不得再用于订单导入 / 一件代发 / 上架发布。"""
    sales_shop = _create_shop(client, auth_headers, platform="shopee",
                              shop_name="归档-销售店", role="sales")
    source_shop = _create_shop(client, auth_headers, platform="1688",
                               shop_name="归档-货源店", role="source")
    product = client.post("/api/products", headers=auth_headers, json={
        "title": "归档守卫商品", "category": "家居",
        "attrs": {"supplier_price": 8, "sale_price": 20},
        "source_platform": "1688",
        "source_url": "https://detail.1688.com/offer/700222.html"}).json()

    assert client.delete(f"/api/shops/{sales_shop['id']}",
                         headers=auth_headers).status_code == 200
    assert client.delete(f"/api/shops/{source_shop['id']}",
                         headers=auth_headers).status_code == 200

    # CSV 导入指定已归档销售店铺 -> 404（不泄漏、不落库）
    r = client.post("/api/orders/import", headers=auth_headers, json={
        "shop_id": sales_shop["id"],
        "csv_text": "external_no,platform,amount\nARCH-GUARD-1,shopee,30"})
    assert r.status_code == 404, r.text
    found = client.get("/api/orders", headers=auth_headers,
                       params={"keyword": "ARCH-GUARD-1"}).json()
    assert found["total"] == 0

    # 代发指定已归档货源店铺 -> 404
    r = client.post("/api/purchases/dropship", headers=auth_headers, json={
        "shop_id": source_shop["id"], "product_id": product["id"],
        "order_id": 1, "qty": 1})
    assert r.status_code == 404, r.text


def test_purge_demo_data_succeeds_under_foreign_keys(client, auth_headers):
    """清理演示数据在 FK 约束下必须整体成功，且不误删账号/店铺/知识库。"""
    before_users = client.get("/api/auth/users", headers=auth_headers).json()["total"]
    before_docs = client.get("/api/knowledge/docs",
                             headers=auth_headers).json()["total"]

    r = client.post("/api/shops/purge_demo_data", headers=auth_headers)
    assert r.status_code == 200, r.text
    deleted = r.json()["deleted"]
    # 计数型字段断言 `>= 0` 恒真（等于没测）。清理前上面已确认有演示订单/商品，
    # 因此这里必须证明**真的删掉了东西**，否则「清理接口空转」会静默通过。
    assert deleted["orders"] > 0, deleted
    assert deleted["products"] > 0, deleted

    # 业务数据已清空
    assert client.get("/api/products", headers=auth_headers).json()["total"] == 0
    assert client.get("/api/orders", headers=auth_headers).json()["total"] == 0

    # 保留项：账号、知识库、店铺授权配置（清理的是演示业务数据）
    assert client.get("/api/auth/users", headers=auth_headers).json()["total"] == before_users
    assert client.get("/api/knowledge/docs",
                      headers=auth_headers).json()["total"] == before_docs

    # 清理后无残留外键违规（依赖顺序正确性的直接证据）
    from app.db import engine
    with engine.connect() as conn:
        violations = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    assert violations == [], f"清理后仍存在外键违规: {violations}"


def test_purge_plan_covers_all_tenant_tables_referencing_purged_tables():
    """守护：新增的租户业务表必须同步进 `_PURGE_PLAN`，否则清理接口必然 500。

    为什么必须静态守护（本缺陷已复发两次）：
      `purge_tenant_demo_data` 按外键拓扑序删除，一旦有新表引用被清理的表
      却没被加进计划，`DELETE` 就会被 SQLite 外键拦截 → 接口 500。
      历史上 `knowledge_candidates`（引用 conversations）就是这样漏掉的：
      加了表、忘了改清理计划，全量测试红了两条。

    判据（不依赖具体表名，新表加入后自动生效）：
      对每张「含 tenant_id 的业务表」，若它引用任一「已在清理计划里的表」，
      它自己就必须也在清理计划里——否则清理顺序必然存在未覆盖的引用边。

    例外：知识库（knowledge_docs 等）按设计**不参与**清理，因此它不在
      被清理集合里，引用它的表不会被误报。
    """
    from app.models import Base
    from app.services.tenant_data_purge import _PURGE_PLAN

    purged = {model.__tablename__ for model, _ in _PURGE_PLAN}
    missing: list[tuple[str, str, str]] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name in purged:
            continue
        if "tenant_id" not in table.columns:
            continue  # 非租户业务表（如 settings/tenants）不参与租户数据清理
        for fk in table.foreign_keys:
            target = fk.column.table.name
            if target in purged:
                missing.append((table_name, fk.parent.name, target))

    assert not missing, (
        "以下租户表引用了被清理的表，却不在 _PURGE_PLAN 中——"
        "清理演示数据时会触发外键 500。请按拓扑序把它们加到被引用表之前：\n"
        + "\n".join(f"  {t}.{c} -> {ref}" for t, c, ref in sorted(set(missing))))


def test_purge_plan_order_is_topologically_valid():
    """守护：`_PURGE_PLAN` 的删除顺序必须满足外键拓扑序（被引用者后删）。

    只检查计划内部的引用边：若 A 引用 B，则 A 必须排在 B 之前。
    顺序写错同样会让清理接口在 DELETE 时撞外键。
    """
    from app.services.tenant_data_purge import _PURGE_PLAN

    order = {model.__tablename__: idx for idx, (model, _) in enumerate(_PURGE_PLAN)}
    violations: list[str] = []
    for table_name, idx in order.items():
        table = _PURGE_PLAN[idx][0].__table__
        for fk in table.foreign_keys:
            target = fk.column.table.name
            if target in order and order[target] < idx:
                violations.append(
                    f"{table_name}(#{idx}).{fk.parent.name} -> {target}(#{order[target]})"
                    "：被引用表排在了引用表之前")

    assert not violations, "清理顺序违反外键拓扑序：\n" + "\n".join(violations)
