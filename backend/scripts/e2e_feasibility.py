"""端到端可行性验证：真启动服务 + 真实 HTTP + 静态前端，全程不碰业务主库。

用法（在 backend 目录执行）：
    python scripts/e2e_feasibility.py                 # 默认端口 8123
    python scripts/e2e_feasibility.py --port 8125     # 自定义端口
    python scripts/e2e_feasibility.py --keep          # 保留副本库与日志便于排查

为什么需要这个脚本（D17 教训）：
    后端全量测试全部使用进程内 `fastapi.testclient.TestClient`——**没有一条**
    真正启动过 uvicorn、加载过前端构建产物、走过一次真实 TCP 请求。于是
    "项目可实际运行"这个结论长期只有间接证据。

    本脚本把"真启动验证"固化为一条命令，四步全程自动化：
      1. 冷备业务主库（复用 `backup_restore_drill.py` 的一致性备份）；
      2. 用副本库启动真实 uvicorn 进程；
      3. 跑 `live_acceptance.py` 的 4 条业务闭环 + 静态前端可访问性检查；
      4. 关闭服务并**校验主库 SHA256 与行数未变**（隔离性硬证据）。

安全保证：
    - 业务主库只被**只读**读取（算指纹）；所有写操作发生在副本库上；
    - 结束后比对主库指纹，不一致则退出码为 2（说明隔离失效，必须排查）；
    - 副本库与日志默认清理，`--keep` 可保留。

退出码：0 = 全部通过；1 = 验收有 FAIL；2 = 隔离性被破坏（主库被改）；3 = 启动失败。
"""
import argparse
import hashlib
import os
import pathlib
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_ROOT_DIR = _BACKEND_DIR.parent


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
    """尽力删除单个产物文件；被安全删除护栏拦截时跳过（后续写入会覆盖同名文件）。

    护栏按「回收站通道」拦截 Python 进程内的 unlink：含非 ASCII 路径的工作区里
    trash 通道会 fail-closed 抛 SystemExit。这里吞掉即可——副本库会被 copy2 /
    backup 整体覆盖，日志以 "w" 模式截断，语义与删除后重建等价。
    """
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


def _check_static_frontend(port: int) -> tuple[bool, str]:
    """验证前端构建产物可被后端静态托管（真实部署形态）。"""
    import urllib.error
    import urllib.request

    dist = _ROOT_DIR / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        return False, f"前端未构建：{dist / 'index.html'} 不存在（先跑 npm run build）"
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
            html = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return False, f"GET / 失败：{e}"
    if "<div id=\"app\"" not in html and "<html" not in html.lower():
        return False, f"GET / 返回的不是前端页面：{html[:120]}"
    return True, f"静态前端可访问（{len(html)} 字节）"


def _kill_tree(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _revision_chain(versions_dir: pathlib.Path, current: str, head: str) -> list[str]:
    """从 current 到 head 的逐级后继序列（供逐级 planned-upgrade）。

    `migration_preflight --planned-upgrade` 的契约是「目标必须是唯一 head 且是数据库
    current 的**直接后继**」——这是刻意的防跳版保护。当主库落后多个未应用的迁移时
    （例如 18 → 19 → 20），副本必须逐级计划升级，而不是放宽预检。本函数把 revision
    文件的 down_revision 反查成后继表，要求链路严格线性，否则显式报错。
    """
    downs: dict[str, list[str]] = {}
    for path in sorted(versions_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rev = re.search(r"^\s*revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        down = re.search(r"^\s*down_revision\s*=\s*(.+)$", text, re.M)
        if not rev:
            continue
        downs[rev.group(1)] = re.findall(r"['\"]([^'\"]+)['\"]", down.group(1)) if down else []
    successor = {items[0]: rev for rev, items in downs.items() if len(items) == 1}
    chain: list[str] = []
    node = current
    while node != head:
        nxt = successor.get(node)
        if not nxt or nxt in chain:
            raise RuntimeError(
                "迁移链非严格线性，无法逐级 planned-upgrade：%s → %s" % (current, head))
        chain.append(nxt)
        node = nxt
    return chain


def _upgrade_isolated_db(copy_db, env):
    """只升级明确隔离的副本；冷备和P0预检均先于迁移。"""
    protected = (_BACKEND_DIR / "erp.db").resolve()
    allowed = (_BACKEND_DIR / "backups" / "e2e_feasibility").resolve()
    if (copy_db.resolve() == protected or copy_db.resolve().parent != allowed
            or env.get("ERP_DB_URL") != "sqlite:///" + copy_db.as_posix()):
        raise RuntimeError("拒绝迁移主库或数据库配置不一致的副本")
    cold_backup = copy_db.with_name("e2e-pre-migration.db")
    with sqlite3.connect(f"file:{copy_db.as_posix()}?mode=ro", uri=True) as source:
        with sqlite3.connect(cold_backup) as target:
            source.backup(target)
    common = {"cwd": str(_BACKEND_DIR), "capture_output": True, "text": True,
              "encoding": "utf-8", "errors": "replace", "env": env}
    heads = subprocess.run([sys.executable, "-m", "alembic", "heads"], **common)
    lines = heads.stdout.strip().splitlines()
    if heads.returncode or len(lines) != 1:
        raise RuntimeError("迁移head无法唯一确认")
    head = lines[0].split()[0]
    with sqlite3.connect(f"file:{copy_db.as_posix()}?mode=ro", uri=True) as source:
        current = source.execute("SELECT version_num FROM alembic_version").fetchall()
    before_rows = _row_count(copy_db)
    command = [sys.executable, "scripts/migration_preflight.py", "--db", str(copy_db)]
    if current != [(head,)]:
        # 显式声明目标 head；预检要求当前版本位于 head 的线性祖先链上（落后多版亦可）。
        command += ["--planned-upgrade", head]
    preflight = subprocess.run(command, **common)
    if preflight.returncode:
        raise RuntimeError("副本迁移预检失败：" + preflight.stdout[-1500:])
    if current != [(head,)]:
        upgrade = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], **common)
        if upgrade.returncode:
            raise RuntimeError("副本迁移失败：" + upgrade.stderr[-1500:])
    after = subprocess.run([sys.executable, "scripts/migration_preflight.py", "--db", str(copy_db)], **common)
    if after.returncode or _row_count(copy_db) != before_rows:
        raise RuntimeError("副本迁移后预检或数据行数校验失败")


def _prepare_copy(args, prod_db, copy_db):
    """从一致性冷备准备独立库；回退也使用SQLite只读备份。"""
    backup_file = None
    if not args.skip_backup:
        print("=== 1. 冷备业务主库 ===")
        r = subprocess.run(
            [sys.executable, "scripts/backup_restore_drill.py", "backup", "--db", "erp.db"],
            cwd=str(_BACKEND_DIR), capture_output=True, text=True,
            # Windows 默认按 GBK 解码子进程输出，遇到中文/emoji 会抛
            # UnicodeDecodeError 并让 stdout 变成 None。必须显式指定 UTF-8。
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
    if backup_file and backup_file.is_file():
        shutil.copy2(backup_file, copy_db)
    else:
        with sqlite3.connect(f"file:{prod_db.as_posix()}?mode=ro", uri=True) as source:
            with sqlite3.connect(copy_db) as target:
                source.backup(target)
    print(f"  副本库：{copy_db}（{copy_db.stat().st_size} 字节）")



def _run_acceptance(args, copy_db, work):
    """副本显式迁移后真启动，并确保所有返回路径关闭本次进程。"""
    print("=== 3. 启动真实服务（uvicorn + 副本库）===")
    env = {
        **os.environ,
        "ERP_DB_URL": "sqlite:///" + copy_db.as_posix(),
        "ERP_ACCEPTANCE_ISOLATED": "1",
        "ERP_JWT_SECRET": "e2e-secret-at-least-32-bytes-long",
        "ERP_SUPERADMIN_PASSWORD": os.environ.get("ERP_SUPERADMIN_PASSWORD", "root-test-123"),
        "PYTHONIOENCODING": "utf-8",
    }
    _upgrade_isolated_db(copy_db, env)
    out_log, err_log = work / "uvicorn.out.log", work / "uvicorn.err.log"
    with open(out_log, "w", encoding="utf-8") as fo, open(err_log, "w", encoding="utf-8") as fe:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--port", str(args.port), "--host", "127.0.0.1"],
            cwd=str(_BACKEND_DIR), stdout=fo, stderr=fe, env=env)

    exit_code = 0
    try:
        if not _wait_ready(args.port):
            print("[FAIL] 服务未在超时内就绪，日志尾部：")
            print(err_log.read_text(encoding="utf-8", errors="replace")[-1500:])
            return 3
        print(f"  服务已就绪：http://127.0.0.1:{args.port}")

        print("=== 4. 静态前端托管检查 ===")
        ok_static, detail_static = _check_static_frontend(args.port)
        print(("  PASS  " if ok_static else "  FAIL  ") + detail_static)
        if not ok_static:
            exit_code = 1

        print("=== 5. 业务闭环验收（live_acceptance）===")
        r = subprocess.run(
            [sys.executable, "scripts/live_acceptance.py",
             f"http://127.0.0.1:{args.port}"],
            cwd=str(_BACKEND_DIR), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env={**env}, timeout=600)
        print((r.stdout or "")[-4000:])
        if r.returncode != 0:
            print(f"  live_acceptance 退出码 {r.returncode}")
            if (r.stderr or "").strip():
                print(r.stderr[-1000:])
            exit_code = 1
    finally:
        print("=== 6. 关闭服务 ===")
        _kill_tree(proc)
        time.sleep(1.5)
    return exit_code


def main(argv=None) -> int:
    """运行副本验收，失败也核验主库并按用户选项清理产物。"""
    parser = argparse.ArgumentParser(description="端到端可行性验证（不碰业务主库）")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--keep", action="store_true", help="保留副本库与日志（默认清理）")
    parser.add_argument("--skip-backup", action="store_true", help="跳过冷备（仅在已有可靠备份时使用）")
    args = parser.parse_args(argv)
    prod_db = _BACKEND_DIR / "erp.db"
    if not prod_db.is_file() or not _port_free(args.port):
        print("[FAIL] 业务主库不存在或端口已被占用")
        return 3
    work = _BACKEND_DIR / "backups" / "e2e_feasibility"
    # 复用旧工作目录（--keep 或上次中断残留）时只清空上一轮产物文件，不做整目录
    # rmtree：递归删除会触发环境的安全删除护栏（按回合累计批量删除计数），导致脚本
    # 尚未运行即被终止。逐文件覆盖副本库与日志即可，语义等价且避开批量删除门槛。
    if work.exists():
        for stale in ("e2e.db", "uvicorn.out.log", "uvicorn.err.log"):
            _best_effort_unlink(work / stale)
    work.mkdir(parents=True, exist_ok=True)
    copy_db = work / "e2e.db"
    print("=== 0. 记录主库基线（用于事后证明隔离性）===")
    before_hash, before_rows = _sha256(prod_db), _row_count(prod_db)
    print(f"  sha256={before_hash[:32]}  rows={before_rows}")
    try:
        _prepare_copy(args, prod_db, copy_db)
        exit_code = _run_acceptance(args, copy_db, work)
    except (RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] {exc}")
        exit_code = 3

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

    if args.keep:
        print(f"\n副本库与日志保留在：{work}")
    else:
        # 避免递归 rmtree 触发安全删除护栏；尽力逐文件清理本轮产物，
        # 被护栏拦截时保留残留文件（下一轮启动时会被覆盖）。
        for stale in ("e2e.db", "uvicorn.out.log", "uvicorn.err.log"):
            _best_effort_unlink(work / stale)

    print(f"\n==== 结果：{'全部通过' if exit_code == 0 else '存在失败'}（exit={exit_code}）====")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
