"""M2-E 标签包真机验收：真实后端 + 隔离副本库 + HTTP 闭环 + 只读库断言。

用法（在 backend 目录执行）：
    python scripts/label_e2e.py                 # 默认端口 8127
    python scripts/label_e2e.py --keep          # 保留副本库与日志（供截图/人工复核）

验什么（对应 M2-E 验收条目）：
    1. 依据缺失时 `GENERATE_LABEL` 被 **409** 阻断（不是 500、也不是静默成功），且零写入；
    2. 阻断项逐条点名缺哪条证据，补齐入口指向商品详情（`/app/products/{id}`）；
    3. 通过 HTTP 补录目的国合规证据后可以推进：落一版标签包、步骤 COMPLETED；
    4. 证据过期后已完成的步骤**重新阻断**（依据一变就失效，不是一次性通过永久生效）；
    5. 重新生成 = 追加新版本，旧版本一字不改（只增不改）；
    6. 只读端点只读：`GET .../labels` 有数据、`POST` 不被接受。

隔离基座直接复用 `scripts/launch_e2e.py`（冷备主库 → 副本库 → 迁移 → 真 uvicorn →
主库 SHA256 + 行数校验），不另写一套；本脚本只在副本库上写数据。

退出码：0 = 全部通过；1 = 断言失败；2 = 隔离失效（主库被改）；3 = 启动或种子失败。
"""
import argparse
import os
import pathlib
import subprocess
import sys
import time

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_ROOT_DIR = _BACKEND_DIR.parent
for _path in (_BACKEND_DIR, _BACKEND_DIR / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import launch_e2e as base  # noqa: E402  （同目录复用隔离基座；模块级只导入 httpx）

_PLATFORM = "labelprobe"
_PROFILE_KEY = "LABEL_E2E"
_MARKET = "DE"          # 德国 → 合规判定单元 EU（CE / EPR）
_REQUIREMENTS = ("CE", "EPR")


def _profile_definition(version: int = 1) -> dict:
    """本地契约流程：资料 → 标签准备 → 在售核验 → 监控（不含平台往返）。"""
    return {
        "profile_key": _PROFILE_KEY, "version": version, "name": "标签 E2E 本地契约样本",
        "description": "本地标签验证，不代表真实平台接入。",
        "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
        "platform": _PLATFORM, "market": _MARKET, "fulfillment_mode": "DROPSHIP",
        "category_scope": ["ANY"], "status_mapping": {"unknown": "BLOCK", "statuses": {}},
        "steps": [
            {"step_code": "INFORMATION", "step_name": "商品资料",
             "business_type": "DATA_PREPARATION", "execution_mode": "MANUAL_TASK",
             "actor": "USER", "sequence": 0, "required": True, "dependencies": [],
             "available_actions": ["COMPLETE_DATA"],
             "evidence_requirements": ["INFORMATION_EVIDENCE"],
             "completion_condition": {"all": [{"present": "product.title"},
                                              {"asset_rights_allowed": "PUBLISHABLE"}]}},
            {"step_code": "LABEL_PREPARATION", "step_name": "标签准备", "business_type": "LABEL",
             "execution_mode": "SYSTEM_TASK", "actor": "SYSTEM", "sequence": 1, "required": True,
             "dependencies": ["INFORMATION"],
             "available_actions": ["GENERATE_LABEL", "REGENERATE_LABEL"],
             "evidence_requirements": ["LABEL_PREPARATION_EVIDENCE"],
             "completion_condition": {"verified_artifact": "LABEL_PACKAGE"}},
            {"step_code": "ACTIVATION", "step_name": "在售核验",
             "business_type": "PLATFORM_ACTIVATION", "execution_mode": "EXTERNAL_WAIT",
             "actor": "PLATFORM", "sequence": 2, "required": True,
             "dependencies": ["LABEL_PREPARATION"],
             "available_actions": ["CONFIRM_ACTIVATION"],
             "evidence_requirements": ["ACTIVATION_EVIDENCE"],
             "completion_condition": {"all": [{"eq": {"field": "platform.status", "value": "ACTIVE"}},
                                              {"verified_artifact": "ACTIVATION"},
                                              {"asset_rights_allowed": "PUBLISHABLE"}]}},
            {"step_code": "MONITORING", "step_name": "经营监控", "business_type": "MONITORING",
             "execution_mode": "SYSTEM_TASK", "actor": "SYSTEM", "sequence": 3,
             "required": False, "dependencies": ["ACTIVATION"],
             "completion_condition": {"eq": {"field": "monitoring.registered", "value": True}}},
        ],
    }


def _seed_copy(env) -> dict:
    """启动服务之前把前置数据写进副本库（Profile 无 HTTP 端点，只能应用内写）。"""
    os.environ.update(env)
    import app.db as app_db
    from app.models import Product, ProductAsset, Shop, User
    from app.services.workspace_context import resolve_workspace_context
    from app.workflows.profiles import create_profile, publish_profile

    with app_db.SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").one()
        ctx = resolve_workspace_context(db, admin)
        tenant = ctx.legacy_tenant_id
        product = Product(tenant_id=tenant, sku="label-e2e", title="65W 氮化镓充电器",
                          category="电子", images=["https://example.com/main.jpg"],
                          attrs={"destination_country": _MARKET, "origin_country": "CN"},
                          hs_code="850440")
        shop = Shop(tenant_id=tenant, platform=_PLATFORM, shop_name="E2E label shop",
                    market=_MARKET, fulfillment_mode="DROPSHIP", role="sales", is_demo=True)
        db.add_all([product, shop])
        db.flush()
        db.add(ProductAsset(tenant_id=tenant, workspace_id=tenant, product_id=product.id,
                            asset_key="main", version=1, asset_type="MAIN_IMAGE",
                            uri=product.images[0], content_hash="f" * 64, rights_status="OWNED",
                            source="label e2e seed", rights_evidence_ref="evidence://e2e/source",
                            market=_MARKET, platform=_PLATFORM,
                            verification_status="MANUAL_REPORTED", created_by=admin.id))
        db.commit()
        profile = create_profile(db, ctx, _profile_definition())
        publish_profile(db, ctx, profile.id, profile.definition_hash)
        db.commit()
        ids = {"tenant_id": tenant, "product_id": product.id, "shop_id": shop.id,
               "profile_id": profile.id, "admin_user_id": admin.id}
    app_db.engine.dispose()
    print("=== 2c. 应用内种子 ===  产品 id=%s 店铺 id=%s Profile id=%s（%s / %s）"
          % (ids["product_id"], ids["shop_id"], ids["profile_id"], _PLATFORM, _MARKET))
    return ids


def _detail(body):
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, dict) else {}


def _http_loop(base_url, seed, record):
    """标签包闭环；返回 {run_id, revision, versions}。"""
    token = base._login(base_url)
    pid, sid = seed["product_id"], seed["shop_id"]

    status, created = base._api(base_url, "POST", "/launch", token=token,
                                headers={"Idempotency-Key": "label-e2e-create"},
                                json={"product_id": pid, "shop_id": sid,
                                      "environment": "CONTRACT_TEST"})
    run_id = created.get("id")
    record("1. 创建上线流程", status == 200 and isinstance(run_id, int),
           f"run_id={run_id} status={status}")
    if status != 200:
        raise RuntimeError(f"创建流程失败：{created}")

    def revision():
        _, steps = base._api(base_url, "GET", f"/launch/{run_id}/steps", token=token)
        return steps.get("revision"), {item["step_code"]: item for item in steps.get("items", [])}

    rev, steps = revision()
    status, acted = base._api(base_url, "POST", f"/launch/{run_id}/actions/COMPLETE_DATA",
                              token=token, headers={"Idempotency-Key": "label-e2e-complete"},
                              json={"step_code": "INFORMATION", "expected_revision": rev,
                                    "payload": {}})
    record("2. 资料步骤 COMPLETE_DATA", status == 200
           and (acted.get("step") or {}).get("step_status") == "COMPLETED",
           f"status={status} revision={rev}→{acted.get('revision')}")

    # ---- 依不足必须 409，且零写入 ----
    rev, steps = revision()
    body = {"step_code": "LABEL_PREPARATION", "expected_revision": rev, "payload": {}}
    status, blocked = base._api(base_url, "POST", f"/launch/{run_id}/actions/GENERATE_LABEL",
                                token=token, headers={"Idempotency-Key": "label-e2e-lack"},
                                json=body)
    detail = _detail(blocked)
    blockers = detail.get("blockers") or []
    codes = {item.get("code") for item in blockers}
    messages = " ".join(str(item.get("message", "")) for item in blockers)
    repair = (blockers[0] or {}).get("repair_action") or {}
    record("3. 依据不足时 GENERATE_LABEL 被 409 阻断",
           status == 409 and detail.get("code") == "ACTION_PRECONDITION_FAILED",
           f"status={status} code={detail.get('code')}（不是 500，也不是静默成功）")
    record("4. 阻断项逐条点名缺哪条证据",
           codes == {"LABEL_BASIS_MISSING"} and all(r in messages for r in _REQUIREMENTS),
           f"codes={sorted(codes)} 缺项命中={[r for r in _REQUIREMENTS if r in messages]}")
    record("5. 补齐入口指向商品详情合规证据区块",
           repair.get("path") == f"/app/products/{pid}" and repair.get("connected") is True,
           f"path={repair.get('path')} connected={repair.get('connected')}")
    _, labels = base._api(base_url, "GET", f"/cross-border/products/{pid}/labels", token=token,
                          params={"country": _MARKET, "shop_id": sid})
    record("6. 阻断时零写入（标签包仍为空）",
           labels.get("items") == [] and not labels.get("basis", {}).get("complete"),
           f"items={len(labels.get('items') or [])} "
           f"complete={labels.get('basis', {}).get('complete')}")

    # ---- 通过 HTTP 补录证据后可推进 ----
    for requirement in _REQUIREMENTS:
        status, saved = base._api(base_url, "POST", f"/cross-border/products/{pid}/compliance",
                                  token=token, json={"destination_country": _MARKET,
                                                     "requirement": requirement,
                                                     "evidence_ref": f"{requirement}-2026-E2E",
                                                     "valid_until": "2030-01-01",
                                                     "note": "E2E 登记"})
        record(f"7. 登记 {requirement} 证据", status == 200,
               f"status={status} 仍需={[item.get('requirement') for item in saved.get('missing') or []]}")
    _, basis = base._api(base_url, "GET", f"/cross-border/products/{pid}/labels", token=token,
                         params={"country": _MARKET, "shop_id": sid})
    record("8. 依据齐备且当前无标签包", basis.get("basis", {}).get("complete") is True
           and basis.get("basis", {}).get("package_current") in (None, False),
           f"complete={basis.get('basis', {}).get('complete')} "
           f"package_current={basis.get('basis', {}).get('package_current')}")

    rev, steps = revision()
    status, ok = base._api(base_url, "POST", f"/launch/{run_id}/actions/GENERATE_LABEL", token=token,
                           headers={"Idempotency-Key": "label-e2e-ok"},
                           json={"step_code": "LABEL_PREPARATION", "expected_revision": rev,
                                 "payload": {"note": "依据已齐"}})
    receipt = ok.get("receipt") or {}
    record("9. 补齐后 GENERATE_LABEL 成功",
           status == 200 and ok.get("status") == "EXECUTED"
           and (ok.get("step") or {}).get("step_status") == "COMPLETED" and receipt.get("version") == 1,
           f"status={status} step={(ok.get('step') or {}).get('step_status')} "
           f"version={receipt.get('version')} marks={receipt.get('marks')}")
    record("10. 回执声明「未打印/未上传/未发送」",
           "未打印" in str(receipt.get("note", "")), f"note={receipt.get('note')}")
    record("11. 印刷前待补项被显式列出", bool(receipt.get("open_items")),
           f"open_items={receipt.get('open_items')}")

    # ---- 证据过期 → 已完成的步骤重新阻断 ----
    base._api(base_url, "POST", f"/cross-border/products/{pid}/compliance", token=token,
              json={"destination_country": _MARKET, "requirement": "CE",
                    "evidence_ref": "CE-2026-E2E", "valid_until": "2020-01-01",
                    "note": "E2E 故意改成已过期"})
    status, after = base._api(base_url, "GET", f"/launch/{run_id}", token=token)
    # 连读两次：完成被撤销后步骤必须稳定停在 BLOCKED，不能「读一次就变回 READY」
    # （BLOCKED 不是粘滞态，撤销理由也不会自己消失；状态不能取决于被读了几次）。
    _, after_again = base._api(base_url, "GET", f"/launch/{run_id}", token=token)
    step = next((item for item in (after.get("steps") or [])
                 if item.get("step_code") == "LABEL_PREPARATION"), {})
    step_again = next((item for item in (after_again.get("steps") or [])
                       if item.get("step_code") == "LABEL_PREPARATION"), {})
    reason = step.get("blocking_reason") or {}
    _, labels_after = base._api(base_url, "GET", f"/cross-border/products/{pid}/labels",
                               token=token, params={"country": _MARKET, "shop_id": sid})
    current = labels_after.get("basis", {}).get("package_current")
    # 口径说明：步骤的 COMPLETED 被撤销，阻断原因以 LABEL_BASIS_MISSING 出现、运行状态转
    # BLOCKED，标签包 `package_current` 转 False。步骤本身仍允许执行（READY/BLOCKED 都在
    # GENERATE/REGENERATE 的来源状态里）——用户补好证据后要能立刻重新生成，不能是死端。
    record("12. 证据过期后标签不再成立（两次读取都阻断 + 原因 + package_current=false）",
           status == 200 and step.get("step_status") == "BLOCKED"
           and step_again.get("step_status") == "BLOCKED"
           and after.get("execution_status") == "BLOCKED"
           and reason.get("code") == "LABEL_BASIS_MISSING"
           and "已过期" in str(reason.get("message")) and current is False,
           f"step={step.get('step_status')}/{step_again.get('step_status')} "
           f"run={after.get('execution_status')} code={reason.get('code')} "
           f"package_current={current} msg={reason.get('message')}")

    # ---- 恢复证据 → 重新生成 = 追加新版本 ----
    base._api(base_url, "POST", f"/cross-border/products/{pid}/compliance", token=token,
              json={"destination_country": _MARKET, "requirement": "CE",
                    "evidence_ref": "CE-2026-E2E", "valid_until": "2031-12-31",
                    "note": "E2E 续期"})
    rev, _steps = revision()
    status, regen = base._api(base_url, "POST", f"/launch/{run_id}/actions/REGENERATE_LABEL",
                              token=token, headers={"Idempotency-Key": "label-e2e-regen"},
                              json={"step_code": "LABEL_PREPARATION", "expected_revision": rev,
                                    "payload": {"note": "证据续期后重新生成"}})
    receipt = regen.get("receipt") or {}
    record("13. 重新生成追加第 2 版",
           status == 200 and receipt.get("version") == 2,
           f"status={status} version={receipt.get('version')} step="
           f"{(regen.get('step') or {}).get('step_status')}")
    _, history = base._api(base_url, "GET", f"/cross-border/products/{pid}/labels", token=token,
                           params={"limit": 20})
    versions = [item.get("version") for item in history.get("items") or []]
    actions = [item.get("action") for item in history.get("items") or []]
    record("14. 版本历史只增不改", sorted(versions) == [1, 2]
           and set(actions) == {"GENERATE", "REGENERATE"}, f"versions={versions} actions={actions}")

    status, _ = base._api(base_url, "POST", f"/cross-border/products/{pid}/labels", token=token,
                          json={})
    record("15. 标签只读端点不接受写入", status == 405, f"status={status}")

    rev, _steps = revision()
    return {"run_id": run_id, "revision": rev, "versions": sorted(versions)}


def _db_assert(copy_db, run_id, product_id):
    """副本库只读断言（证明 HTTP 结果真的落库，而不是只在响应里）。"""
    import sqlite3

    con = sqlite3.connect(f"file:{copy_db.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT version, action, destination_country, content_digest, basis_fingerprint,"
            " open_items FROM label_packages WHERE product_id=? ORDER BY version",
            (product_id,)).fetchall()
        step = con.execute(
            "SELECT step_status, blocking_reason FROM workflow_steps WHERE run_id=? AND step_code=?",
            (run_id, "LABEL_PREPARATION")).fetchone()
        return {"versions": [row[0] for row in rows], "actions": [row[1] for row in rows],
                "country": rows[0][2] if rows else "",
                "digest_ok": bool(rows) and all(len(row[3]) == 64 for row in rows),
                "fingerprint_ok": bool(rows) and all(len(row[4]) == 64 for row in rows),
                "open_items": rows[-1][5] if rows else "",
                "step_status": step[0] if step else None,
                "blocking_reason": step[1] if step else None}
    finally:
        con.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M2-E 标签包真机闭环（不碰业务主库）")
    parser.add_argument("--port", type=int, default=8127)
    parser.add_argument("--keep", action="store_true", help="保留副本库与日志（默认清理）")
    args = parser.parse_args(argv)

    prod_db = _BACKEND_DIR / "erp.db"
    if not prod_db.is_file() or not base._port_free(args.port):
        print("[FAIL] 业务主库不存在或端口已被占用")
        return 3
    # 副本库必须落在 `launch_e2e._migrate_copy` 白名单目录里（它拒绝迁移白名单外的库，
    # 这是防止误把 alembic 指向业务主库的护栏）——所以复用同一个目录，只换文件名。
    work = _BACKEND_DIR / "backups" / "launch_e2e"
    copy_db = work / "label-e2e.db"
    work.mkdir(parents=True, exist_ok=True)
    for stale in (copy_db.name, "uvicorn.out.log", "uvicorn.err.log"):
        base._best_effort_unlink(work / stale)
    env = {
        **os.environ,
        "ERP_DB_URL": "sqlite:///" + copy_db.as_posix(),
        "ERP_ACCEPTANCE_ISOLATED": "1",
        "ERP_JWT_SECRET": "label-e2e-secret-at-least-32-bytes",
        "ERP_SUPERADMIN_PASSWORD": os.environ.get("ERP_SUPERADMIN_PASSWORD", "root-test-123"),
        "PYTHONIOENCODING": "utf-8",
    }

    print("=== 0. 记录主库基线（用于事后证明隔离性）===")
    before_hash, before_rows = base._sha256(prod_db), base._row_count(prod_db)
    print(f"  sha256={before_hash[:32]}  rows={before_rows}")

    results, ids, exit_code, proc = [], {}, 0, None
    out_log, err_log = work / "uvicorn.out.log", work / "uvicorn.err.log"
    try:
        base._prepare_copy(args, prod_db, copy_db)
        base._migrate_copy(copy_db, env)
        ids = _seed_copy(env)

        print("=== 3. 启动真实服务（uvicorn + 副本库）===")
        with open(out_log, "w", encoding="utf-8") as fo, open(err_log, "w", encoding="utf-8") as fe:
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app",
                 "--port", str(args.port), "--host", "127.0.0.1"],
                cwd=str(_BACKEND_DIR), stdout=fo, stderr=fe, env=env)
        if not base._wait_ready(args.port):
            print("[FAIL] 服务未在超时内就绪，日志尾部：")
            print(err_log.read_text(encoding="utf-8", errors="replace")[-1500:])
            exit_code = 3
        else:
            print(f"  服务已就绪：http://127.0.0.1:{args.port}")

            def record(name, ok, detail):
                results.append((name, ok, detail))
                print(("  PASS  " if ok else "  FAIL  ") + f"{name}：{detail}")

            print("=== 4. 标签包 HTTP 闭环 ===")
            out = _http_loop(f"http://127.0.0.1:{args.port}/api", ids, record)
            ids.update(out)

            print("=== 5. 数据库断言（副本库只读）===")
            facts = _db_assert(copy_db, ids["run_id"], ids["product_id"])
            record("16. label_packages 落库两版", facts["versions"] == [1, 2],
                   f"versions={facts['versions']} actions={facts['actions']}")
            record("17. 目的国归一为 EU", facts["country"] == "EU", f"country={facts['country']}")
            record("18. 内容摘要与依据指纹均为 sha256", facts["digest_ok"] and facts["fingerprint_ok"],
                   f"digest_ok={facts['digest_ok']} fingerprint_ok={facts['fingerprint_ok']}")
            record("19. 印刷待补项已落库", bool(facts["open_items"]),
                   f"open_items={facts['open_items']}")
            record("20. 标签步骤 COMPLETED",
                   facts["step_status"] == "COMPLETED", f"{facts['step_status']}")
            if not all(item[1] for item in results):
                exit_code = 1
            print(f"  副本库：{copy_db}")
    except (RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] {exc}")
        exit_code = 3
    finally:
        if proc is not None:
            print("=== 6. 关闭服务 ===")
            base._kill_tree(proc)
            time.sleep(1.5)

    print("=== 7. 隔离性校验（主库必须未被写入）===")
    after_hash, after_rows = base._sha256(prod_db), base._row_count(prod_db)
    same = (after_hash == before_hash and after_rows == before_rows)
    print(f"  before sha256={before_hash[:32]} rows={before_rows}")
    print(f"  after  sha256={after_hash[:32]} rows={after_rows}")
    if same:
        print("  PASS  业务主库未被写入（隔离性成立）")
    else:
        print("  FAIL  业务主库发生变化！隔离失效，必须排查")
        exit_code = 2

    failed = [item for item in results if not item[1]]
    print("\n==== 汇总 ====")
    print(f"共 {len(results)} 步：PASS {len(results) - len(failed)} / FAIL {len(failed)}")
    for name, _ok, detail in failed:
        print(f"  - {name}：{detail}")
    print(f"\n  run_id={ids.get('run_id')}  product_id={ids.get('product_id')}  "
          f"shop_id={ids.get('shop_id')}  终值 revision={ids.get('revision')}")
    print("  admin 登录：POST /api/auth/login  {\"username\":\"admin\",\"password\":\"admin123\"}")
    if args.keep:
        print(f"\n副本库与日志保留在：{work}")
    else:
        for stale in (copy_db.name, "uvicorn.out.log", "uvicorn.err.log"):
            base._best_effort_unlink(work / stale)
    print(f"\n==== 结果：{'全部通过' if exit_code == 0 else '存在失败'}（exit={exit_code}）====")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
