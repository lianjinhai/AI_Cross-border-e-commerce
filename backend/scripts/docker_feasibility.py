"""Docker 生产镜像可行性验证：真构建 + 真运行 + 真登录 + 真业务调用。

用法（在 backend 目录执行）：
    python scripts/docker_feasibility.py                # 完整验证（构建+运行）
    python scripts/docker_feasibility.py --skip-build   # 复用已有镜像，只跑运行部分
    python scripts/docker_feasibility.py --keep         # 保留镜像与容器便于排查

为什么需要这个脚本（D21 教训）：
    `e2e_feasibility.py` 验证的是「本机直接跑 uvicorn」，但**生产部署走的是容器**。
    构建链路（Dockerfile / 依赖锁定 / .gitattributes 行尾 / entrypoint 脚本）
    任一失效，都会造成「本地测试全绿、镜像起不来」。这类缺陷只有真构建 + 真运行才暴露。

本脚本验证 7 项：
    1. 前端构建产物存在（dist/index.html）
    2. 镜像可构建（--target runtime）
    3. 镜像内依赖版本与 requirements.lock.txt **逐项一致**
    4. 生产镜像**不含** pytest / ruff（测试工具不应进运行时）
    5. 入口脚本为 **LF** 行尾（CRLF 会让容器报 bad interpreter）
    6. 容器真实启动：健康检查 200 + 静态前端可访问
    7. 真实登录 + 真实业务接口调用（不是只看进程活着）
    8. compose 两个部署形态都显式声明了 TLS 位置（DEBT-23）

安全保证：
    - 端口**动态取空闲端口**（不写死）——本机并行跑着多个项目，
      写死常见端口会把「端口冲突」误判为「应用起不来」（D21 实测踩坑）；
    - 容器数据卷用临时目录，结束即删；镜像默认删除（--keep 保留）；
    - 使用生产模式 + 随机密钥，不触碰业务主库。

退出码：0 = 全部通过；1 = 有检查项 FAIL；2 = docker 不可用；3 = 构建/启动失败。
"""
import argparse
import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_ROOT_DIR = _BACKEND_DIR.parent
_IMAGE = "ai-erp-feasibility:verify"
_CONTAINER = "ai-erp-feasibility-run"

_PASS, _FAIL = "PASS", "FAIL"


def _run(cmd, **kw):
    """统一的子进程调用。

    Windows 默认按 GBK 解码子进程输出，遇中文会抛 UnicodeDecodeError
    并让 stdout 变 None（D17 教训）——必须显式指定 UTF-8。
    """
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def _free_port() -> int:
    """动态取一个空闲端口（DP-3：不得写死端口）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _docker_available() -> bool:
    r = _run(["docker", "info", "--format", "{{.ServerVersion}}"])
    return r.returncode == 0


def _wait_http(url: str, timeout: float = 90.0) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                return True, f"{resp.status} {resp.read().decode('utf-8', 'replace')[:90]}"
        except Exception as e:  # 就绪前连接被拒是正常的，继续等
            last = str(e)
            time.sleep(2)
    return False, last


def _expected_versions() -> dict:
    """读取锁定清单，得到「包名(小写) -> 版本」。"""
    lock = _BACKEND_DIR / "requirements.lock.txt"
    out = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "==" in line:
            name, ver = line.split("==", 1)
            out[name.strip().lower()] = ver.strip()
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Docker 生产镜像可行性验证")
    parser.add_argument("--skip-build", action="store_true", help="复用已有镜像")
    parser.add_argument("--keep", action="store_true", help="保留镜像与容器")
    args = parser.parse_args(argv)

    results = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))
        print(f"  [{_PASS if ok else _FAIL}] {name}：{detail}")

    print("=== 0. 前置检查 ===")
    if not _docker_available():
        print("[FAIL] docker 不可用（守护进程未运行或未安装）")
        return 2
    dist_index = _ROOT_DIR / "frontend" / "dist" / "index.html"
    record("前端构建产物", dist_index.is_file(),
           str(dist_index) if dist_index.is_file()
           else f"缺失 {dist_index}——请先 cd frontend && npm run build")
    if not dist_index.is_file():
        return 1

    # 结构检查：Dockerfile 必须真的引用锁定清单。
    # 只比对「装了什么」不够——实测把 Dockerfile 改回 `requirements.txt` 时，
    # 因兼容上限恰好解析出同样版本，版本比对会**通过**（回退法验证发现）。
    # 两项互补：本项验「装的是锁定清单」，后面验「装的版本对得上」。
    dockerfile = (_ROOT_DIR / "Dockerfile").read_text(encoding="utf-8")
    uses_lock = "requirements.lock.txt" in dockerfile
    record("Dockerfile 引用锁定清单", uses_lock,
           "已引用 requirements.lock.txt" if uses_lock
           else "未引用！镜像可能装出与验证环境不同的版本")
    if not uses_lock:
        return 1

    # DEBT-23：生产门禁要求显式声明 TLS 位置（见 app/config.py）。
    # 这里做**结构检查**而非运行检查：两个 compose 形态必须各自声明，
    # 否则对应部署路径会在容器启动时被门禁拒绝（实测：基础 compose 漏声明时
    # 本脚本第 6/7 项 FAIL，即 README 的「一键部署」实际不可用）。
    # 与 DP-4 同理——只验「容器能起来」不足以证明「配置声明是对的」。
    base_compose = (_ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
    tls_compose = (_ROOT_DIR / "docker-compose.tls.yml").read_text(encoding="utf-8")
    base_declares = "ERP_TLS_TERMINATED_ELSEWHERE" in base_compose
    tls_declares = "ERP_TRUST_PROXY_HEADERS" in tls_compose
    record("compose 声明 TLS 位置", base_declares and tls_declares,
           "基础=外部终止 / TLS 层=代理后" if (base_declares and tls_declares)
           else f"缺失声明：基础={base_declares} TLS层={tls_declares}")

    _run(["docker", "rm", "-f", _CONTAINER])

    if not args.skip_build:
        print("=== 1. 构建镜像（--target runtime）===")
        r = _run(["docker", "build", "--target", "runtime", "-t", _IMAGE, "."],
                 cwd=str(_ROOT_DIR))
        if r.returncode != 0:
            print(f"[FAIL] 构建失败（exit={r.returncode}）：\n{(r.stdout or '')[-2000:]}")
            return 3
        record("镜像构建", True, _IMAGE)

    print("=== 2. 镜像内依赖版本（须与锁定清单逐项一致）===")
    r = _run(["docker", "run", "--rm", "--entrypoint", "python", _IMAGE,
              "-m", "pip", "list", "--format=freeze"])
    if r.returncode != 0:
        print(f"[FAIL] 无法读取镜像内依赖：{(r.stderr or '')[-600:]}")
        return 3
    installed = {}
    for line in (r.stdout or "").splitlines():
        if "==" in line:
            name, ver = line.split("==", 1)
            installed[name.strip().lower()] = ver.strip()
    expected = _expected_versions()
    mismatch = [(n, v, installed.get(n)) for n, v in sorted(expected.items())
                if installed.get(n) != v]
    record("依赖版本一致", not mismatch,
           f"{len(expected)} 项全部匹配" if not mismatch
           else f"{len(mismatch)} 项不一致，如 {mismatch[:3]}")

    print("=== 3. 生产镜像纯净性（不应含测试工具）===")
    bad = [n for n in ("pytest", "ruff") if n in installed]
    record("不含 pytest/ruff", not bad,
           "均不存在" if not bad else f"不应存在：{bad}")

    print("=== 4. 入口脚本行尾（必须 LF）===")
    r = _run(["docker", "run", "--rm", "--entrypoint", "sh", _IMAGE,
              "-c", "head -c 20 /usr/local/bin/docker-entrypoint.sh | od -An -c"])
    out = (r.stdout or "")
    has_crlf = "\\r" in out
    record("入口脚本为 LF", not has_crlf,
           "LF（无 CRLF）" if not has_crlf else f"检测到 CRLF！容器会报 bad interpreter：{out.strip()[:80]}")

    print("=== 5. 启动容器（生产模式）===")
    port = _free_port()
    tmpdir = tempfile.mkdtemp(prefix="ai_erp_docker_")
    r = _run(["docker", "run", "-d", "--name", _CONTAINER,
              "-p", f"{port}:8000",
              "-v", f"{tmpdir}:/data",
              "-e", "ERP_ENV=production",
              # 与 docker-compose.yml 的声明保持一致：本脚本验证的是
              # **无 TLS 基线**（容器自己起、宿主机直连 8000），TLS 由外部终止。
              # 不声明则生产门禁拒绝启动（DEBT-23 新增校验）——
              # 实测漏掉这一项时，本脚本第 6/7 项会 FAIL。
              "-e", "ERP_TLS_TERMINATED_ELSEWHERE=1",
              "-e", "ERP_JWT_SECRET=" + "x" * 48,
              "-e", "ERP_ADMIN_PASSWORD=Docker-Feasibility-Pass-2026",
              "-e", "ERP_CREDENTIAL_KEY=" + "A" * 43 + "=",
              _IMAGE])
    if r.returncode != 0:
        print(f"[FAIL] 容器启动失败：{(r.stderr or '')[-800:]}")
        return 3
    record("容器启动", True, f"端口 {port}（动态分配）")

    exit_code = 0
    try:
        print("=== 6. 健康检查 + 静态前端 ===")
        ok, detail = _wait_http(f"http://127.0.0.1:{port}/api/health")
        record("健康检查 /api/health", ok, detail)
        if not ok:
            logs = _run(["docker", "logs", "--tail", "20", _CONTAINER])
            print((logs.stdout or "")[-1500:] + (logs.stderr or "")[-800:])
            exit_code = 1
        else:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
                    size = len(resp.read())
                    record("静态前端托管", resp.status == 200, f"{resp.status}，{size} 字节")
            except Exception as e:
                record("静态前端托管", False, str(e))
                exit_code = 1

        print("=== 7. 真实登录 + 真实业务调用 ===")
        try:
            body = json.dumps({"username": "admin",
                               "password": "Docker-Feasibility-Pass-2026"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/auth/login", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                token = data.get("token", "")
                record("真实登录", resp.status == 200 and bool(token),
                       f"{resp.status}，user={data.get('user', {}).get('username')}")
            req2 = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/products?page_size=5",
                headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                body2 = json.loads(resp2.read().decode("utf-8"))
                record("业务接口调用", resp2.status == 200,
                       f"/api/products total={body2.get('total')} "
                       f"取回={len(body2.get('items', []))}")
        except Exception as e:
            record("真实登录/业务调用", False, str(e))
            exit_code = 1
    finally:
        print("=== 8. 清理 ===")
        _run(["docker", "rm", "-f", _CONTAINER])
        import shutil as _sh
        _sh.rmtree(tmpdir, ignore_errors=True)
        if not args.keep:
            _run(["docker", "rmi", "-f", _IMAGE])
            print("  容器与镜像已清理（--keep 可保留）")
        else:
            print(f"  已保留镜像 {_IMAGE}（容器已删）")

    print()
    print("==== 汇总 ====")
    for name, ok, _detail in results:
        print(f"  [{_PASS if ok else _FAIL}] {name}")
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"\n失败项：{failed}")
        exit_code = exit_code or 1
    else:
        print("\n全部通过")
    print(f"==== 结果：{'全部通过' if exit_code == 0 else '存在失败'}（exit={exit_code}）====")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
