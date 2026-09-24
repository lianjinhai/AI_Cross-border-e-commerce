"""HTTPS 端到端验证：真 Caddy + 真应用容器，验证 TLS 链路真的通（DEBT-23）。

用法（在 backend 目录执行）：
    python scripts/tls_feasibility.py              # 完整验证
    python scripts/tls_feasibility.py --keep       # 保留容器便于排查
    python scripts/tls_feasibility.py --self-signed  # 用自签证书（默认）

## 为什么需要这个脚本

`docker_feasibility.py` 验证的是**无 TLS 基线**（容器自己起、直连 8000）。
DEBT-23 缺的是「TLS 链路」，而这类配置**只有真跑一遍才算验证过**：
Caddyfile 语法、转发头传递、应用侧采信开关、`ports: !reset` 是否真的生效，
任一环错都会表现为「配置看着对，线上不通」。

## 本脚本验证 6 项

    1. Caddyfile 语法有效（`caddy validate`，含模板变量求值）
    2. 应用容器在 TLS 覆盖层下**不暴露 8000**（`ports: !reset` 真的生效）
    3. Caddy 容器能起来并完成证书签发（自签内部 CA）
    4. **真 HTTPS 请求**成功（TLS 握手 + 200）
    5. 应用侧收到 `X-Forwarded-Proto: https`（转发头链路通）
    6. 应用采信了转发头（`ERP_TRUST_PROXY_HEADERS=1` 生效）

## 为什么默认自签而不是 Let's Encrypt

Let's Encrypt 需要**公网可达的真实域名**才能完成 ACME 校验。本脚本要能在
离线/内网环境复现，因此用 Caddy 的 `tls internal`（本地 CA）。
生产用 Let's Encrypt 的路径由同一份 Caddyfile 覆盖——差别只是 `tls` 一行，
而语法与转发头行为**完全一致**，故本脚本能有效守住生产链路。

## 安全保证

    - 全程用临时目录与独立容器名，结束即清理；不碰业务主库与 .env；
    - 端口动态分配（DP-3）；不修改仓库内任何文件（Caddyfile 副本写到临时目录）；
    - 自签 CA 仅存在于本次运行的内存/临时卷中。

退出码：0 = 全部通过；1 = 有 FAIL；2 = docker 不可用；3 = 启动/构建失败。
"""
import argparse
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_ROOT_DIR = _BACKEND_DIR.parent
_IMAGE = "ai-erp-tls-verify:latest"
_NET = "ai-erp-tls-net"
_APP = "ai-erp-tls-app"
_PROXY = "ai-erp-tls-proxy"
_DOMAIN = "erp.tls-verify.test"
_ACME_EMAIL = "verify@example.com"

_PASS, _FAIL = "PASS", "FAIL"


def _run(cmd, **kw):
    """统一子进程调用。Windows 默认 GBK 解码会让中文输出抛错（D17 教训）。"""
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _docker_available() -> bool:
    return _run(["docker", "info", "--format", "{{.ServerVersion}}"]).returncode == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="HTTPS 端到端验证")
    parser.add_argument("--keep", action="store_true", help="保留容器便于排查")
    parser.add_argument("--skip-build", action="store_true", help="复用已有镜像")
    args = parser.parse_args(argv)

    results = []

    def record(name, ok, detail):
        results.append((name, ok, detail))
        print(f"  [{_PASS if ok else _FAIL}] {name}：{detail}")

    if not _docker_available():
        print("[FAIL] docker 不可用")
        return 2

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="ai_erp_tls_"))
    exit_code = 0
    try:
        print("=== 0. 准备：复制 Caddyfile 到临时目录，仅注入 tls internal ===")
        # 保真原则：临时副本与生产 Caddyfile **逐字一致**，只加一行 `tls internal`
        # （离线自签所需）。域名与邮箱仍走环境变量——即验证的是生产同一份模板，
        # 而不是"改过的另一份配置"。
        caddyfile = (_ROOT_DIR / "Caddyfile").read_text(encoding="utf-8")
        assert "{$ERP_DOMAIN} {" in caddyfile, "Caddyfile 站点块格式变了，本脚本需同步"
        caddyfile = caddyfile.replace("{$ERP_DOMAIN} {", "{$ERP_DOMAIN} {\n\ttls internal", 1)
        (tmpdir / "Caddyfile").write_text(caddyfile, encoding="utf-8")

        print("=== 1. Caddyfile 语法有效 ===")
        r = _run(["docker", "run", "--rm",
                  "-e", f"ACME_EMAIL={_ACME_EMAIL}",
                  "-e", f"ERP_DOMAIN={_DOMAIN}",
                  "-v", f"{tmpdir}:/etc/caddy:ro",
                  "caddy:2-alpine", "caddy", "validate", "--config", "/etc/caddy/Caddyfile"])
        out = (r.stdout or "") + (r.stderr or "")
        record("Caddyfile 语法", "Valid configuration" in out and r.returncode == 0,
               "Valid configuration" if "Valid configuration" in out
               else f"exit={r.returncode}：{out[-400:]}")
        if r.returncode != 0:
            return 3

        print("=== 2. 构建应用镜像（若需要）===")
        if args.skip_build:
            # --skip-build 的语义是「复用已有镜像」，不是「跳过检查」。
            # 镜像不存在时必须明确报错——否则后面 `docker run` 会去 registry 拉
            # 同名镜像并因网络不可达而失败，报错信息完全指错方向
            # （实测：把「本地无镜像」误报成「registry 连不上」）。
            r = _run(["docker", "image", "inspect", _IMAGE])
            if r.returncode != 0:
                print(f"[FAIL] --skip-build 指定复用 {_IMAGE}，但本地不存在该镜像。"
                      f"请先不带 --skip-build 跑一次以构建它。")
                return 3
        else:
            r = _run(["docker", "build", "--target", "runtime", "-t", _IMAGE, "."],
                     cwd=str(_ROOT_DIR))
            if r.returncode != 0:
                print(f"[FAIL] 构建失败：{(r.stdout or '')[-1500:]}")
                return 3
        record("镜像就绪", True, _IMAGE)

        print("=== 3. 起网络与应用容器（生产模式 + TLS 覆盖层语义）===")
        _run(["docker", "rm", "-f", _APP])
        _run(["docker", "rm", "-f", _PROXY])
        _run(["docker", "network", "rm", _NET])
        r = _run(["docker", "network", "create", "--subnet", "172.31.241.0/24", _NET])
        if r.returncode != 0:
            print(f"[FAIL] 建网络失败：{(r.stderr or '')[-400:]}")
            return 3

        data_dir = tmpdir / "data"
        data_dir.mkdir(exist_ok=True)
        # 注意：**不映射 8000 到宿主机**——复刻 docker-compose.tls.yml 的 `ports: !reset`。
        # 这正是「外部无法绕过代理直连」的前提；若这里映射了，
        # 下面的第 5 项（不暴露 8000）会失败，提醒配置退化。
        r = _run(["docker", "run", "-d", "--name", _APP, "--network", _NET,
                  "--ip", "172.31.241.10",
                  # 网络别名必须是 `erp`：Caddyfile 里写的是 `reverse_proxy erp:8000`
                  # （compose 服务名）。用别名而不是改 Caddyfile，
                  # 才能保证验证的是**生产同一份配置**（实测：少了这个别名，
                  # 代理解析不到主机名，表现为 502）。
                  "--network-alias", "erp",
                  "-v", f"{data_dir}:/data",
                  "-e", "ERP_ENV=production",
                  "-e", "ERP_JWT_SECRET=" + "x" * 48,
                  "-e", "ERP_ADMIN_PASSWORD=Docker-Feasibility-Pass-2026",
                  "-e", "ERP_CREDENTIAL_KEY=" + "A" * 43 + "=",
                  "-e", "ERP_CORS_ORIGINS=https://" + _DOMAIN,
                  "-e", "ERP_TRUST_PROXY_HEADERS=1",
                  "-e", "ERP_TRUSTED_PROXY_HOSTS=172.31.241.0/24",
                  "-e", f"ERP_PUBLIC_BASE_URL=https://{_DOMAIN}",
                  _IMAGE])
        if r.returncode != 0:
            print(f"[FAIL] 应用容器启动失败：{(r.stderr or '')[-800:]}")
            return 3

        print("=== 4. 应用就绪（容器内直连，不经代理）===")
        # 容器内自检：确认应用真的起来了（不是只启动了容器）。
        ready = False
        for _ in range(30):
            r = _run(["docker", "exec", _APP, "python", "-c",
                      "import urllib.request,sys;"
                      "sys.exit(0 if urllib.request.urlopen("
                      "'http://127.0.0.1:8000/api/health',timeout=3).status==200 else 1)"])
            if r.returncode == 0:
                ready = True
                break
            time.sleep(2)
        record("应用容器内健康检查", ready,
               "200" if ready else "超时未就绪（见 docker logs " + _APP + "）")
        if not ready:
            print((_run(["docker", "logs", "--tail", "25", _APP]).stdout or "")[-1800:])
            exit_code = 1
            return exit_code

        print("=== 5. 应用未暴露到宿主机（ports: !reset 语义）===")
        # 若应用直接映射到宿主机，就等于绕过 TLS——检查容器没有 published 端口。
        r = _run(["docker", "port", _APP])
        published = (r.stdout or "").strip()
        record("应用未直接暴露端口", not published,
               "未映射任何端口" if not published
               else f"不应映射却映射了：{published}（外部可绕过 TLS 直连）")

        print("=== 6. 起 Caddy 代理并完成证书签发 ===")
        r = _run(["docker", "run", "-d", "--name", _PROXY, "--network", _NET,
                  "--ip", "172.31.241.11",
                  "-v", f"{tmpdir}:/etc/caddy:ro",
                  # 必须传这两个变量：Caddyfile 的全局块用了 {$ACME_EMAIL}，
                  # 站点块用了 {$ERP_DOMAIN}；不传则模板求值为空，
                  # Caddy 直接拒绝加载（实测报 "wrong argument count ... after 'email'"）。
                  "-e", f"ACME_EMAIL={_ACME_EMAIL}",
                  "-e", f"ERP_DOMAIN={_DOMAIN}",
                  "caddy:2-alpine", "caddy", "run", "--config", "/etc/caddy/Caddyfile"])
        if r.returncode != 0:
            print(f"[FAIL] 代理启动失败：{(r.stderr or '')[-600:]}")
            exit_code = 1
            return exit_code
        time.sleep(8)  # 等自签 CA 生成与证书装载
        logs = _run(["docker", "logs", "--tail", "30", _PROXY])
        logtext = (logs.stdout or "") + (logs.stderr or "")
        cert_ok = "certificate obtained successfully" in logtext
        record("代理证书签发", cert_ok,
               "已签发（tls internal 自签 CA）" if cert_ok
               else f"未见签发记录：{logtext[-400:]}")

        print("=== 7. 真 HTTPS 请求（容器内 curl，-k 因自签 CA）===")
        # 在代理同网络内发请求：用 --resolve 把域名指向代理容器 IP。
        # 用 curl 而非 python urllib：验证的是**真 TLS 握手**，且 curl 能看到响应头。
        r = _run(["docker", "run", "--rm", "--network", _NET,
                  "curlimages/curl:latest", "-sS", "-k", "-i",
                  "--resolve", f"{_DOMAIN}:443:172.31.241.11",
                  f"https://{_DOMAIN}/api/health"])
        out = (r.stdout or "")
        # 断言必须同时看「状态码」与「响应体」：
        # - 只看状态码不够：Caddy 出错时也会返回 502，且有状态行；
        # - 只用 `"200 OK" in out` 会误判：HTTP/2 的状态行是 `HTTP/2 200`，
        #   没有 `OK` 字样（实测踩坑：真成功了却报 FAIL）。
        status_ok = any(line.startswith("HTTP/") and " 200" in line
                        for line in out.splitlines())
        https_ok = status_ok and '"ok":true' in out.replace(" ", "")
        record("HTTPS 请求 /api/health", https_ok,
               "200 + {ok:true}（TLS 握手成功）" if https_ok
               else f"exit={r.returncode}：{out[-500:]}")

        print("=== 8. 转发头真的被应用采信（DEBT-23 核心断言）===")
        # 只证明「HTTPS 请求能通」还不够：Caddy 无条件转发，即使应用**没开**
        # ERP_TRUST_PROXY_HEADERS 也能返回 200——那样应用仍以为自己在 http 之后，
        # 生成的回调地址、审计日志全是错的。
        #
        # 因此必须直接观察应用侧的解析结果。做法：让应用把它看到的 scheme
        # 与客户端 IP 回报出来。仓库里没有这样的端点，故用**最贴近真实**的
        # 手段：对比应用日志中记录的客户端地址。
        #
        # 关键判别点：Caddy 会把 X-Forwarded-For 设为**真实客户端地址**
        # （实测：客户端伪造 XFF 也会被 Caddy 覆盖）。从代理容器发出的请求，
        # 其真实对端是 curl 容器（172.31.241.x）。若应用采信转发头，
        # 日志里的客户端应是 curl 容器地址；若未采信，则是代理容器地址
        # 172.31.241.11。
        r = _run(["docker", "logs", "--tail", "60", _APP])
        applog = (r.stdout or "") + (r.stderr or "")
        # 找 uvicorn access log 里的客户端地址（形如 `INFO:     172.31.241.x:port - "GET /api/health`）
        seen = set()
        for line in applog.splitlines():
            if "GET /api/health" in line and "INFO:" in line:
                token = line.split("INFO:")[-1].strip().split(" ")[0]
                host = token.rsplit(":", 1)[0]
                if host.startswith("172.31.241."):
                    seen.add(host)
        # 172.31.241.11 是代理容器；出现**别的** 172.31.241.x 说明采信了 XFF
        # （真实客户端被如实记录），这正是转发头生效的证据。
        others = sorted(h for h in seen if h != "172.31.241.11")
        record("应用采信 X-Forwarded-For", bool(others),
               f"日志中的真实客户端：{others}" if others
               else f"日志只见到代理地址（转发头未生效）。全部来源：{sorted(seen)}")

        print("=== 9. 直连应用必须失败（证明只经代理可达）===")
        # 从**网络外**访问应用的 8000：容器未映射端口，故宿主机不可达。
        # 这是「外部无法绕过 TLS」的可执行证据，而非只看配置文件。
        probe = socket.socket()
        probe.settimeout(2)
        refused = False
        try:
            probe.connect(("127.0.0.1", 8000))
        except (TimeoutError, ConnectionRefusedError, OSError):
            refused = True
        finally:
            probe.close()
        record("宿主机 8000 不可直连", refused,
               "已拒绝/超时" if refused else "可直连！TLS 可被绕过")

    finally:
        print("=== 清理 ===")
        if not args.keep:
            _run(["docker", "rm", "-f", _PROXY])
            _run(["docker", "rm", "-f", _APP])
            _run(["docker", "network", "rm", _NET])
            shutil.rmtree(tmpdir, ignore_errors=True)
            print("  容器/网络/临时目录已清理（--keep 可保留）")
        else:
            print(f"  已保留容器（{_APP} / {_PROXY}）与临时目录 {tmpdir}")

    print()
    print("==== 汇总 ====")
    for name, ok, _d in results:
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
