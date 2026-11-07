"""Launch 真机闭环端到端验收（AC-18.3）：真实后端 + 隔离副本库 + API/数据库断言。

用法（在 backend 目录执行）：
    python scripts/launch_e2e.py                 # 默认端口 8125
    python scripts/launch_e2e.py --port 8126     # 自定义端口
    python scripts/launch_e2e.py --keep          # 保留副本库与日志（供人工/Playwright 复核）

为什么需要这个脚本（AC-18.3）：
    既有 `live_acceptance.py` 只能验证「服务已启动之后」的既有业务闭环，而项目**没有
    Profile 管理的 HTTP 端点**（`create_profile` / `publish_profile` 只在 `app/workflows/
    profiles.py`，未在 routers 暴露）。因此 Launch 的前置数据（tenant / product / 销售店铺 /
    已发布 CONTRACT_TEST Profile）**必须**在启动 uvicorn 之前用应用内服务直接写进隔离副本库。
    本脚本把「Launch 真机闭环」固化为一条命令：迁移副本 → 应用内种子 → 启动真实 uvicorn →
    HTTP 闭环（幂等 / 契约 / 脱敏 / 动作 / sync / 事件）→ **sqlite3 只读副本库断言持久化事实**
    → 关闭服务 → 校验业务主库未被写入。

安全保证（与 `e2e_feasibility.py` 同源，不改动后者）：
    - 业务主库 `erp.db` 只被**只读**读取（算 SHA256 与行数基线）；所有写操作发生在副本库上；
    - 结束后比对主库指纹，不一致则退出码为 2（隔离失效，必须排查）；
    - 副本库与日志默认清理，`--keep` 可保留。

退出码：0 = 全部通过；1 = 断言失败；2 = 隔离失效（主库被改）；3 = 启动或种子失败。
"""
import argparse
import hashlib
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import time

import httpx

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_ROOT_DIR = _BACKEND_DIR.parent
# `python scripts/launch_e2e.py` 只把 scripts/ 放进 sys.path，import app 需显式补 backend/。
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# 本地契约样本参数（独立平台/Profile key，避免与其它 Profile 交叉匹配导致 PROFILE_AMBIGUOUS）。
_PLATFORM = "launchprobe"
_PROFILE_KEY = "ACTION_PROBE"
_STEP_CODE = "INFO"
_CREATE_KEY = "launch-e2e-create"
# 双 Profile 真机（P0-4）：`contract_profiles` 里的简单/复杂样本各跑一遍。
# 注意 step_code 必须是该 Profile 里第一个可 COMPLETE_DATA 的资料步骤。
_PROFILE_STEP_CODES = {"probe": _STEP_CODE, "simple": "INFORMATION",
                       "complex": "PRODUCT_INFORMATION"}
_PROFILE_KEYS = {"probe": _PROFILE_KEY, "simple": "SIMPLE_CONTRACT", "complex": "COMPLEX_CONTRACT"}
_CREATE_KEYS = {"probe": _CREATE_KEY, "simple": "launch-e2e-simple", "complex": "launch-e2e-complex"}
# DTO 契约：响应中绝不出现价格/成本/利润率/备货数量字段（AC-3.2/AC-9，递归断言）。
_FORBIDDEN_KEYS = frozenset({"price", "cost", "margin", "profit", "stock", "stock_qty",
                             "supply_price", "cost_price", "profit_rate", "cost_snapshot"})


# --------------------------------------------------------------- 隔离基座（复用 e2e_feasibility 模式）

def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_count(path: pathlib.Path) -> int:
    """只读统计总行数（用于证明主库未被写入）。"""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        total = 0
        for (name,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"):
            total += con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        return total
    finally:
        con.close()


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _best_effort_unlink(path: pathlib.Path) -> None:
    """尽力删除单个产物文件；被安全删除护栏拦截时跳过（后续写入会覆盖同名文件）。"""
    try:
        path.unlink(missing_ok=True)
    except (OSError, SystemExit):
        pass


def _wait_ready(port: int, timeout: float = 40.0) -> bool:
    """轮询 /api/health 直到服务就绪（比固定 sleep 可靠）。"""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(1.0)
    return False


def _kill_tree(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _prepare_copy(args, prod_db, copy_db) -> None:
    """从一致性冷备准备独立副本库（回退也使用 SQLite 只读备份 API）。"""
    backup_file = None
    print("=== 1. 冷备业务主库 ===")
    r = subprocess.run(
        [sys.executable, "scripts/backup_restore_drill.py", "backup", "--db", "erp.db"],
        cwd=str(_BACKEND_DIR), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        raise RuntimeError(f"冷备失败（exit={r.returncode}）：\n{r.stderr[-1500:]}")
    line = next((ln for ln in (r.stdout or "").splitlines()
                 if "[PASS] backup_created" in ln), "")
    print("  " + line.strip() if line else "  冷备完成")
    marker = "backup_created:"
    if marker in line:
        backup_file = pathlib.Path(line.split(marker, 1)[1].split("(")[0].strip())

    print("=== 2. 准备副本库 ===")
    source_path = backup_file if backup_file and backup_file.is_file() else prod_db
    with open(copy_db, "wb") as f:
        f.truncate(0)
    with sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True) as source:
        with sqlite3.connect(copy_db) as target:
            source.backup(target)
    print(f"  副本库：{copy_db}（{copy_db.stat().st_size} 字节）")


def _migrate_copy(copy_db, env) -> None:
    """逐级 planned-upgrade 把副本升到 head（主库落后多版属正常）。

    副本是一次性隔离库，此处只做「预检 → alembic upgrade → 预检」；真正的数据安全保证
    是主库隔离性校验（§隔离性），而不是副本行数守恒。
    """
    protected = (_BACKEND_DIR / "erp.db").resolve()
    allowed = (_BACKEND_DIR / "backups" / "launch_e2e").resolve()
    if (copy_db.resolve() == protected or copy_db.resolve().parent != allowed
            or env.get("ERP_DB_URL") != "sqlite:///" + copy_db.as_posix()):
        raise RuntimeError("拒绝迁移主库或数据库配置不一致的副本")
    common = {"cwd": str(_BACKEND_DIR), "capture_output": True, "text": True,
              "encoding": "utf-8", "errors": "replace", "env": env}
    heads = subprocess.run([sys.executable, "-m", "alembic", "heads"], **common)
    lines = heads.stdout.strip().splitlines()
    if heads.returncode or len(lines) != 1:
        raise RuntimeError("迁移 head 无法唯一确认")
    head = lines[0].split()[0]
    with sqlite3.connect(f"file:{copy_db.as_posix()}?mode=ro", uri=True) as source:
        current = source.execute("SELECT version_num FROM alembic_version").fetchall()
    command = [sys.executable, "scripts/migration_preflight.py", "--db", str(copy_db)]
    if current != [(head,)]:
        command += ["--planned-upgrade", head]
    preflight = subprocess.run(command, **common)
    if preflight.returncode:
        raise RuntimeError("副本迁移预检失败：" + preflight.stdout[-1500:])
    if current != [(head,)]:
        upgrade = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], **common)
        if upgrade.returncode:
            raise RuntimeError("副本迁移失败：" + upgrade.stderr[-1500:])
    after = subprocess.run([sys.executable, "scripts/migration_preflight.py", "--db", str(copy_db)], **common)
    if after.returncode:
        raise RuntimeError("副本迁移后预检失败：" + after.stdout[-1500:])
    print(f"=== 2b. 副本迁移 ===\n  PASS current={current[0][0] if current else '?'} → head={head}")


# ------------------------------------------------------------------------------ 应用内种子

def _probe_profile(version: int = 1) -> dict:
    """本地契约流程：资料(INFO) -> 提交 -> 在售核验 -> 监控。

    仅本地流程验证，不代表任何真实平台接入；与 tests/test_launch_api.py 的 _api_profile 同构，
    但使用独立平台/Profile key 避免与库内既有定义交叉。
    """
    steps = [
        {"step_code": _STEP_CODE, "step_name": "商品资料", "business_type": "DATA_PREPARATION",
         "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 0, "required": True,
         "dependencies": [], "available_actions": ["COMPLETE_DATA"],
         "evidence_requirements": ["INFORMATION_EVIDENCE"],
         "completion_condition": {"all": [{"present": "product.title"},
                                          {"asset_rights_allowed": "PUBLISHABLE"}]}},
        {"step_code": "SUBMISSION", "step_name": "提交平台", "business_type": "PLATFORM_SUBMISSION",
         "execution_mode": "ADAPTER_TASK", "actor": "SYSTEM", "sequence": 1, "required": True,
         "dependencies": [_STEP_CODE], "available_actions": ["SUBMIT_PLATFORM"],
         "completion_condition": {"present": "platform.submission_reference"}},
        {"step_code": "ACTIVE", "step_name": "在售核验", "business_type": "PLATFORM_ACTIVATION",
         "execution_mode": "EXTERNAL_WAIT", "actor": "PLATFORM", "sequence": 2, "required": True,
         "dependencies": ["SUBMISSION"], "available_actions": ["CONFIRM_ACTIVATION"],
         "completion_condition": {"all": [{"eq": {"field": "platform.status", "value": "ACTIVE"}},
                                          {"verified_artifact": "ACTIVATION"},
                                          {"asset_rights_allowed": "PUBLISHABLE"}]}},
        {"step_code": "MONITORING", "step_name": "经营监控", "business_type": "MONITORING",
         "execution_mode": "SYSTEM_TASK", "actor": "SYSTEM", "sequence": 3, "required": False,
         "dependencies": ["ACTIVE"],
         "completion_condition": {"eq": {"field": "monitoring.registered", "value": True}}},
    ]
    return {"profile_key": _PROFILE_KEY, "version": version, "name": "Launch E2E 本地契约样本",
            "description": "本地流程验证，不代表真实平台接入。",
            "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
            "platform": _PLATFORM, "market": "SG", "fulfillment_mode": "DROPSHIP",
            "category_scope": ["ANY"], "status_mapping": {"unknown": "BLOCK", "statuses": {}},
            "steps": steps}


def _seed_copy(env, profile_name="probe") -> dict:
    """在启动 uvicorn 之前，用应用内服务把 Launch 前置数据写进隔离副本库。

    必须在**首次** import app.* 之前设置 ERP_DB_URL，否则 `app.db` 的引擎会绑定到主库。
    本函数是脚本内唯一 import app.* 的地方（`contract_profiles` 也在 env 生效后才导入，
    否则会把 `app.config` 提前求值，隔离基座失效）。
    """
    os.environ.update(env)  # ERP_DB_URL / ERP_JWT_SECRET / ... 生效于 app.config 类体求值之前
    import app.db as app_db
    from app.models import Product, ProductAsset, Shop, User
    from app.services.workspace_context import resolve_workspace_context
    from app.workflows.profiles import create_profile, publish_profile

    definition = _profile_definition(profile_name)
    platform = definition["platform"]
    # Profile 里写 "ANY" 的维度取一个具体值：店铺必须给出明确市场与履约模式才能创建流程。
    market = "SG" if definition["market"] == "ANY" else definition["market"]
    fulfillment = ("DROPSHIP" if definition["fulfillment_mode"] == "ANY"
                   else definition["fulfillment_mode"])
    business_mode = definition.get("business_mode") or ""
    business_mode = "" if business_mode == "ANY" else business_mode

    with app_db.SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").one()
        ctx = resolve_workspace_context(db, admin)
        tenant = ctx.legacy_tenant_id
        product = Product(tenant_id=tenant, sku=f"launch-e2e-{profile_name}",
                          title="Launch E2E product", category="家居",
                          images=["https://example.com/main.jpg"],
                          attrs={"destination_country": market})
        shop = Shop(tenant_id=tenant, platform=platform, shop_name="E2E sales",
                    market=market, fulfillment_mode=fulfillment, business_mode=business_mode,
                    role="sales", is_demo=True)
        db.add_all([product, shop])
        db.flush()
        db.add(ProductAsset(tenant_id=tenant, workspace_id=tenant, product_id=product.id,
                            asset_key="main", version=1, asset_type="MAIN_IMAGE",
                            uri=product.images[0], content_hash="e" * 64, rights_status="OWNED",
                            source="launch e2e seed", rights_evidence_ref="evidence://e2e/source",
                            market=market, platform=platform, verification_status="MANUAL_REPORTED",
                            created_by=admin.id))
        db.commit()
        profile = create_profile(db, ctx, definition)
        publish_profile(db, ctx, profile.id, profile.definition_hash)
        db.commit()
        ids = {"tenant_id": tenant, "product_id": product.id, "shop_id": shop.id,
               "profile_id": profile.id, "admin_user_id": admin.id,
               "profile_name": profile_name, "platform": platform, "market": market}
    app_db.engine.dispose()  # 释放副本库连接，避免与随后的 uvicorn 进程争用
    print("=== 2c. 应用内种子===  产品 id=%s 店铺 id=%s Profile id=%s（%s / %s / %s）"
          % (ids["product_id"], ids["shop_id"], ids["profile_id"],
             profile_name, platform, market))
    return ids


def _profile_definition(profile_name):
    """按 `--profile` 取流程定义；契约样本在 env 生效后才导入，避免过早求值 app.config。"""
    if profile_name == "probe":
        return _probe_profile()
    from app.workflows.contract_profiles import complex_contract, simple_contract
    return {"simple": simple_contract, "complex": complex_contract}[profile_name]()


# ---------------------------------------------------------------------------------- HTTP 闭环

def _api(base_url, method, path, token=None, headers=None, **kw):
    merged = dict(headers or {})
    if token:
        merged["Authorization"] = "Bearer " + token
    response = httpx.request(method, base_url + path, headers=merged, timeout=30, **kw)
    try:
        data = response.json()
    except Exception:
        data = {"_raw": response.text[:300]}
    return response.status_code, data


def _login(base_url) -> str:
    status, body = _api(base_url, "POST", "/auth/login",
                        json={"username": "admin", "password": "admin123"})
    if status != 200 or not body.get("token"):
        raise RuntimeError(f"admin 登录失败（status={status}）：{body}")
    return body["token"]


def _find_forbidden(node):
    """递归查找价格/成本/备货字段键；命中返回该键，否则 None（AC-3.2/AC-9）。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key.lower() in _FORBIDDEN_KEYS:
                return key
            hit = _find_forbidden(value)
            if hit:
                return hit
    elif isinstance(node, list):
        for item in node:
            hit = _find_forbidden(item)
            if hit:
                return hit
    return None


def _http_loop(base_url, seed, record):
    """执行 Launch HTTP 闭环，返回最终 revision 与 run_id。"""
    token = _login(base_url)
    step_code = _PROFILE_STEP_CODES[seed["profile_name"]]
    create_key = _CREATE_KEYS[seed["profile_name"]]

    status, ctx = _api(base_url, "GET", "/launch/context", token=token)
    perms = set(ctx.get("permissions", []))
    need = {"launch:read", "launch:create", "launch:manage"}
    record("1. GET /launch/context", status == 200 and ctx.get("can_create") is True
           and bool(ctx.get("shops")) and need <= perms,
           f"can_create={ctx.get('can_create')} shops={len(ctx.get('shops', []))} "
           f"缺少权限={sorted(need - perms)}")
    if perms < need or not ctx.get("shops"):
        raise RuntimeError("上下文前置不满足，后续闭环无法继续")

    body = {"product_id": seed["product_id"], "shop_id": seed["shop_id"],
            "environment": "CONTRACT_TEST"}
    head = {"Idempotency-Key": create_key}
    status, created = _api(base_url, "POST", "/launch", token=token, headers=head, json=body)
    run_id = created.get("id")
    record("2. POST /launch 创建", status == 200 and isinstance(run_id, int)
           and created.get("store", {}).get("id") == seed["shop_id"],
           f"run_id={run_id} revision={created.get('revision')} status={status}")
    if status != 200:
        raise RuntimeError(f"创建失败：{created}")
    status, replay = _api(base_url, "POST", "/launch", token=token, headers=head, json=body)
    record("2b. 同幂等键重放", status == 200 and replay.get("id") == run_id,
           f"replay_id={replay.get('id')} status={status}")

    status, listing = _api(base_url, "GET", "/launch", token=token,
                           params={"product_id": seed["product_id"]})
    ids = [item["id"] for item in listing.get("items", [])]
    record("3. GET /launch 列表", status == 200 and run_id in ids
           and listing.get("page_num") == 1,
           f"page_num={listing.get('page_num')} total={listing.get('total')} 含本 run={run_id in ids}")
    status, bad = _api(base_url, "GET", "/launch", token=token, params={"bogus": 1})
    code = (bad.get("detail") or {}).get("code") if isinstance(bad.get("detail"), dict) else None
    record("3b. 未知查询参数 422", status == 422 and code == "FILTER_INVALID",
           f"status={status} code={code}")

    status, detail = _api(base_url, "GET", f"/launch/{run_id}", token=token)
    offending = _find_forbidden(detail)
    record("4. GET /launch/{id} 详情", status == 200 and detail.get("id") == run_id
           and offending is None,
           f"status={status} route_keys_ok={'profile' in detail} 违禁字段={offending}")

    status, steps = _api(base_url, "GET", f"/launch/{run_id}/steps", token=token)
    profile = steps.get("profile", {})
    step_map = {item["step_code"]: item for item in steps.get("items", [])}
    record("5. GET /launch/{id}/steps", status == 200 and "revision" in steps
           and {"key", "version", "hash"} <= set(profile)
           and profile.get("key") == _PROFILE_KEYS[seed["profile_name"]]
           and step_map.get(step_code, {}).get("available_actions", [{}])[0].get("action")
           == "COMPLETE_DATA",
           f"status={status} revision={steps.get('revision')} profile={profile} "
           f"期望 profile_key={_PROFILE_KEYS[seed['profile_name']]}")

    revision = steps.get("revision")
    action_body = {"step_code": step_code, "expected_revision": revision, "payload": {}}
    status, acted = _api(base_url, "POST", f"/launch/{run_id}/actions/COMPLETE_DATA", token=token,
                         headers={"Idempotency-Key": "launch-e2e-complete"},
                         json=action_body)
    step_status = (acted.get("step") or {}).get("step_status")
    record("6. POST actions/COMPLETE_DATA",
           status == 200 and acted.get("status") == "EXECUTED"
           and acted.get("revision") == revision + 1 and step_status == "COMPLETED",
           f"status={status} revision={revision}→{acted.get('revision')} step={step_status}")
    if status != 200:
        raise RuntimeError(f"COMPLETE_DATA 失败：{acted}")
    current_revision = (acted.get("launch") or {}).get("revision", acted.get("revision"))

    # P0-4：阻断不能只给原因。逐项检查「阻断码 + 原因 + 补齐动作」三要素，
    # 且补齐入口必须指向应用内真实页面（`/app/...`），不允许退回 `repair_action: None`。
    status, after = _api(base_url, "GET", f"/launch/{run_id}", token=token)
    blockers = after.get("blockers") or []
    broken = [b for b in blockers
              if not isinstance(b, dict) or not b.get("code")
              or not str(b.get("message", "")).strip()
              or not isinstance(b.get("repair_action"), dict)
              or not str((b.get("repair_action") or {}).get("path", "")).startswith("/app")]
    sample = blockers[0] if blockers else {}
    record("6b. 阻断项三要素齐全", status == 200 and not broken,
           f"阻断数={len(blockers)} 缺要素={len(broken)} "
           f"首项={sample.get('code')}→{(sample.get('repair_action') or {}).get('path')}")

    status, synced = _api(base_url, "POST", f"/launch/{run_id}/sync", token=token,
                          json={"mode": "refresh", "expected_revision": current_revision})
    record("7. POST /launch/{id}/sync", status == 200 and synced.get("refreshed") is True
           and synced.get("launch", {}).get("last_synced_at") is not None,
           f"status={status} refreshed={synced.get('refreshed')} "
           f"last_synced_at={synced.get('launch', {}).get('last_synced_at')}")
    final_revision = synced.get("revision", current_revision)

    status, events = _api(base_url, "GET", f"/launch/{run_id}/events", token=token)
    sequences = [item["sequence"] for item in events.get("items", [])]
    types = {item["event_type"] for item in events.get("items", [])}
    record("8. GET /launch/{id}/events", status == 200 and sequences == sorted(sequences)
           and "LaunchActionExecuted" in types,
           f"status={status} 事件数={len(sequences)} 升序={sequences == sorted(sequences)} "
           f"含 LaunchActionExecuted={'LaunchActionExecuted' in types}")
    return run_id, final_revision


# --------------------------------------------------------------------------- 数据库断言

def _db_assert(*, copy_db, run_id, step_code, expected_revision) -> dict:
    """sqlite3 只读打开副本库，断言持久化事实（AC-18.3 的「数据库断言」部分）。"""
    con = sqlite3.connect(f"file:{copy_db.as_posix()}?mode=ro", uri=True)
    try:
        run = con.execute("SELECT revision, execution_status FROM workflow_runs WHERE id=?",
                          (run_id,)).fetchone()
        step = con.execute("SELECT step_status, result FROM workflow_steps WHERE run_id=? AND step_code=?",
                           (run_id, step_code)).fetchone()
        events = con.execute("SELECT event_type FROM workflow_events WHERE run_id=?", (run_id,)).fetchall()
    finally:
        con.close()
    if run is None or step is None:
        raise RuntimeError("副本库缺少 run 或目标步骤行")
    result_json = step[1] or "{}"
    has_evidence = any(token in result_json for token in ("completed_by", "completed_at", "facts_digest"))
    types = [row[0] for row in events]
    return {"revision": run[0], "expected_revision": expected_revision, "revision_ok": run[0] == expected_revision,
            "step_status": step[0], "step_ok": step[0] == "COMPLETED", "evidence_ok": has_evidence,
            "action_event_ok": "LaunchActionExecuted" in types, "event_count": len(types)}


# ---------------------------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Launch 真机闭环端到端验收（不碰业务主库）")
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--keep", action="store_true", help="保留副本库与日志（默认清理）")
    parser.add_argument("--profile", choices=["probe", "simple", "complex"], default="probe",
                        help="跑哪条 Profile：probe=ACTION_PROBE（默认）；simple/complex=契约样本")
    args = parser.parse_args(argv)

    prod_db = _BACKEND_DIR / "erp.db"
    if not prod_db.is_file() or not _port_free(args.port):
        print("[FAIL] 业务主库不存在或端口已被占用")
        return 3
    work = _BACKEND_DIR / "backups" / "launch_e2e"
    copy_db = work / f"launch-{args.profile}.db"
    if work.exists():
        for stale in (copy_db.name, "uvicorn.out.log", "uvicorn.err.log"):
            _best_effort_unlink(work / stale)
    work.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "ERP_DB_URL": "sqlite:///" + copy_db.as_posix(),
        "ERP_ACCEPTANCE_ISOLATED": "1",
        "ERP_JWT_SECRET": "launch-e2e-secret-at-least-32-bytes",
        "ERP_SUPERADMIN_PASSWORD": os.environ.get("ERP_SUPERADMIN_PASSWORD", "root-test-123"),
        "PYTHONIOENCODING": "utf-8",
    }

    print("=== 0. 记录主库基线（用于事后证明隔离性）===")
    before_hash, before_rows = _sha256(prod_db), _row_count(prod_db)
    print(f"  sha256={before_hash[:32]}  rows={before_rows}")

    results = []
    run_ids = {}
    exit_code = 0
    proc = None
    out_log, err_log = work / "uvicorn.out.log", work / "uvicorn.err.log"
    try:
        _prepare_copy(args, prod_db, copy_db)
        _migrate_copy(copy_db, env)
        run_ids = _seed_copy(env, args.profile)

        print("=== 3. 启动真实服务（uvicorn + 副本库）===")
        with open(out_log, "w", encoding="utf-8") as fo, open(err_log, "w", encoding="utf-8") as fe:
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app",
                 "--port", str(args.port), "--host", "127.0.0.1"],
                cwd=str(_BACKEND_DIR), stdout=fo, stderr=fe, env=env)
        if not _wait_ready(args.port):
            print("[FAIL] 服务未在超时内就绪，日志尾部：")
            print(err_log.read_text(encoding="utf-8", errors="replace")[-1500:])
            exit_code = 3
        else:
            print(f"  服务已就绪：http://127.0.0.1:{args.port}")
            base_url = f"http://127.0.0.1:{args.port}/api"

            def record(name, ok, detail):
                results.append((name, ok, detail))
                print(("  PASS  " if ok else "  FAIL  ") + f"{name}：{detail}")

            print("=== 4. Launch HTTP 闭环 ===")
            run_id, final_revision = _http_loop(base_url, run_ids, record)
            run_ids["run_id"] = run_id
            run_ids["revision"] = final_revision

            print("=== 5. 数据库断言（副本库只读）===")
            step_code = _PROFILE_STEP_CODES[run_ids["profile_name"]]
            facts = _db_assert(copy_db=copy_db, run_id=run_id, step_code=step_code,
                               expected_revision=final_revision)
            db_ok = all((facts["revision_ok"], facts["step_ok"], facts["evidence_ok"], facts["action_event_ok"]))
            record("9. workflow_runs.revision == HTTP 终值",
                   facts["revision_ok"], f"db={facts['revision']} http={facts['expected_revision']}")
            record("10. 目标步骤 COMPLETED", facts["step_ok"], f"{step_code}={facts['step_status']}")
            record("11. 步骤 result 含完成证据", facts["evidence_ok"], "completed_by/at/facts_digest")
            record("12. 存在 LaunchActionExecuted 事件", facts["action_event_ok"],
                   f"事件数={facts['event_count']}")
            if not db_ok:
                exit_code = 1
            print(f"  副本库：{copy_db}")
    except (RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] {exc}")
        exit_code = 3
    finally:
        if proc is not None:
            print("=== 6. 关闭服务 ===")
            _kill_tree(proc)
            time.sleep(1.5)

    print("=== 7. 隔离性校验（主库必须未被写入）===")
    after_hash, after_rows = _sha256(prod_db), _row_count(prod_db)
    same = (after_hash == before_hash and after_rows == before_rows)
    print(f"  before sha256={before_hash[:32]} rows={before_rows}")
    print(f"  after  sha256={after_hash[:32]} rows={after_rows}")
    if same:
        print("  PASS  业务主库未被写入（隔离性成立）")
    else:
        print("  FAIL  业务主库发生变化！隔离失效，必须排查")
        exit_code = 2

    failed = [r for r in results if not r[1]]
    print("\n==== 汇总 ====")
    print(f"共 {len(results)} 步：PASS {len(results) - len(failed)} / FAIL {len(failed)}")
    for name, _ok, detail in failed:
        print(f"  - {name}：{detail}")
    print(f"\n  run_id={run_ids.get('run_id')}  product_id={run_ids.get('product_id')}  "
          f"shop_id={run_ids.get('shop_id')}  终值 revision={run_ids.get('revision')}")
    print("  admin 登录：POST /api/auth/login  {\"username\":\"admin\",\"password\":\"admin123\"}")

    if args.keep:
        print(f"\n副本库与日志保留在：{work}")
    else:
        for stale in (copy_db.name, "uvicorn.out.log", "uvicorn.err.log"):
            _best_effort_unlink(work / stale)

    print(f"\n==== 结果：{'全部通过' if exit_code == 0 else '存在失败'}（exit={exit_code}）====")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
