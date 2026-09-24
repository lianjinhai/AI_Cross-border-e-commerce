"""生产 TLS / 反向代理配置门禁契约测试（DEBT-23）。

## 为什么需要这个文件

DEBT-23 的上一版改动引入了三个**真实缺陷**，全部由本次实测发现：

1. **`main.py` 直接 import `starlette.middleware.proxy_headers`**——该模块在
   starlette 1.x 中已被移除（实测本机 1.3.1 与镜像内 1.7.0 均为
   `ModuleNotFoundError`）。一旦设 `ERP_TRUST_PROXY_HEADERS=1`，容器会在
   import 阶段崩溃。**这个"修复"比不改更糟**：开关关着时一切正常，
   打开就死，且只有真部署才会触发。
2. **`ERP_TLS_TERMINATED_ELSEWHERE` 用「非空即真」判断**——运维写
   `=0`（本意关闭）会被当成「已声明 TLS」而放行门禁。
3. **门禁打断了既有部署路径**——基础 `docker-compose.yml` 未声明 TLS 位置，
   于是 `docker_feasibility.py` 实测 FAIL 2 项，README 里的「Docker 一键部署」
   实际已不可用。

本文件锁死修复后的契约。**这些断言都对应实测行为，不是对实现的复述。**

## 测试策略

门禁逻辑读的是模块级 `settings`（import 时求值），因此无法用 monkeypatch
环境变量来测——必须**在子进程里**用干净解释器重新 import，才能得到真实结果。
这也顺带验证了「运维真实使用方式」：进程启动那一刻读环境变量。
"""
import os
import pathlib
import subprocess
import sys

import pytest

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent

# 子进程跑 config 门禁的最小探针：只导入 config 并调用校验，不拉起整个应用。
_PROBE = """
import sys
sys.path.insert(0, {backend!r})
from app import config
try:
    config.validate_production_settings()
except RuntimeError as e:
    print("GATE_REJECTED:" + str(e))
    raise SystemExit(0)
print("GATE_PASSED")
"""


def _run_gate(env_overrides: dict) -> str:
    """在子进程里以给定环境变量跑一次生产门禁，返回 stdout。"""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("ERP_")}  # 清掉父进程的 ERP_*，避免污染
    env.update({
        "ERP_ENV": "production",
        "ERP_JWT_SECRET": "x" * 48,
        "ERP_ADMIN_PASSWORD": "Strong-Admin-Pass-987",
        "ERP_CREDENTIAL_KEY": "A" * 43 + "=",
        "ERP_CORS_ORIGINS": "https://erp.example.com",
    })
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(backend=str(_BACKEND_DIR))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    assert result.returncode == 0, f"探针异常退出：{result.stderr[-800:]}"
    return result.stdout


def test_gate_rejects_when_tls_position_undeclared():
    """未声明 TLS 位置 → 拒绝启动（默认态就是拒绝，不是静默放行）。"""
    out = _run_gate({})
    assert "GATE_REJECTED" in out, f"未声明 TLS 位置却放行：{out}"
    assert "TLS" in out


def test_gate_accepts_proxy_headers_mode():
    """声明「在反向代理之后」→ 放行。"""
    out = _run_gate({"ERP_TRUST_PROXY_HEADERS": "1",
                     "ERP_TRUSTED_PROXY_HOSTS": "172.31.240.0/24"})
    assert "GATE_PASSED" in out, out


def test_gate_accepts_tls_terminated_elsewhere():
    """声明「TLS 由外部设施终止」→ 放行。"""
    out = _run_gate({"ERP_TLS_TERMINATED_ELSEWHERE": "1"})
    assert "GATE_PASSED" in out, out


@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_gate_treats_falsy_flag_as_undeclared(value):
    """`ERP_TLS_TERMINATED_ELSEWHERE=0`（本意关闭）不得被当成已声明。

    这是 DEBT-23 实测发现的判别漏洞：`bool(os.getenv(...))` 非空即真，
    写 0 反而放行——门禁形同虚设。
    """
    out = _run_gate({"ERP_TLS_TERMINATED_ELSEWHERE": value})
    assert "GATE_REJECTED" in out, f"取值 {value!r} 被误判为已声明：{out}"


def test_gate_rejects_http_public_base_url():
    """生产环境公网回调地址必须是 https。

    OAuth 回跳与前端跳转都依赖它；留 http 会被浏览器/平台判定为不安全连接，
    授权链路直接失败（且只有真授权时才暴露，属高代价缺陷）。
    """
    out = _run_gate({"ERP_TLS_TERMINATED_ELSEWHERE": "1",
                     "ERP_PUBLIC_BASE_URL": "http://erp.example.com"})
    assert "GATE_REJECTED" in out, out
    assert "https" in out


def test_gate_rejects_empty_trusted_proxy_hosts():
    """开启转发头信任却不给可信来源 → 拒绝（避免退化成信任所有来源）。"""
    out = _run_gate({"ERP_TRUST_PROXY_HEADERS": "1",
                     "ERP_TRUSTED_PROXY_HOSTS": ""})
    assert "GATE_REJECTED" in out, out


def test_gate_skipped_outside_production():
    """开发/测试环境不启用这些门禁（否则本地与 CI 全部起不来）。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ERP_")}
    env["ERP_ENV"] = "development"
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(backend=str(_BACKEND_DIR))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    assert result.returncode == 0, result.stderr[-800:]
    assert "GATE_PASSED" in result.stdout


# ---------------------------------------------------------------------------
# 中间件功能测试
#
# 上面测的是「门禁判得对不对」；下面测的是「开关打开后**真的能用**」。
# 两者缺一不可：DEBT-23 上一版的门禁逻辑本身是通的，但开关一打开就
# ModuleNotFoundError 崩溃（import 了 starlette 1.x 已移除的模块）。
# 只测门禁会漏掉这类缺陷——必须真正走一遍中间件装配路径。
# ---------------------------------------------------------------------------

def _probe_app(monkeypatch, *, enabled: bool, trusted: str):
    """按给定配置装配一个最小应用，返回 (TestClient 工厂, 中间件是否装上)。

    不 import app.main：那会在 import 时创建完整应用并跑 lifespan（连数据库）。
    这里只测 `install_proxy_headers_middleware` 这一个单元。
    """
    from fastapi import FastAPI, Request

    from app import config
    from app.proxy_headers import install_proxy_headers_middleware

    monkeypatch.setattr(config.settings, "trust_proxy_headers", enabled, raising=False)
    monkeypatch.setattr(config.settings, "trusted_proxy_hosts", [trusted], raising=False)

    app = FastAPI()

    @app.get("/probe")
    def probe(request: Request):
        return {"scheme": request.url.scheme,
                "client": request.client.host if request.client else None}

    installed = install_proxy_headers_middleware(app)
    return app, installed


def test_middleware_installs_and_honors_forwarded_headers(monkeypatch):
    """开启后：转发头生效（scheme=https、client=真实客户端）。

    这条断言同时是 starlette 回归的守卫——若有人改回
    `from starlette.middleware.proxy_headers import ...`，本用例会以
    ModuleNotFoundError 失败，而不是等到生产部署才暴露。
    """
    from fastapi.testclient import TestClient

    app, installed = _probe_app(monkeypatch, enabled=True, trusted="10.0.0.5")
    assert installed is True, "开关打开却没装上中间件"
    client = TestClient(app, client=("10.0.0.5", 1234))
    r = client.get("/probe", headers={"X-Forwarded-Proto": "https",
                                      "X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 200, r.text
    assert r.json() == {"scheme": "https", "client": "203.0.113.9"}, r.json()


def test_middleware_ignores_headers_from_untrusted_source(monkeypatch):
    """可信来源之外：转发头**必须被忽略**（否则任何人可伪造客户端 IP）。

    实测背景：uvicorn 在 `FORWARDED_ALLOW_IPS=*` 下会无条件采信 XFF，
    直连即可把客户端 IP 伪造成任意值。`ERP_TRUSTED_PROXY_HOSTS` 就是为
    收敛这一点而存在，本用例锁死它确实生效。
    """
    from fastapi.testclient import TestClient

    app, _ = _probe_app(monkeypatch, enabled=True, trusted="10.0.0.5")
    client = TestClient(app, client=("10.0.0.6", 1234))  # 非可信来源
    r = client.get("/probe", headers={"X-Forwarded-Proto": "https",
                                      "X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 200, r.text
    assert r.json() == {"scheme": "http", "client": "10.0.0.6"}, r.json()


def test_middleware_not_installed_when_disabled(monkeypatch):
    """默认关闭：不装中间件，转发头一律不采信。"""
    from fastapi.testclient import TestClient

    app, installed = _probe_app(monkeypatch, enabled=False, trusted="10.0.0.5")
    assert installed is False
    client = TestClient(app, client=("10.0.0.5", 1234))
    r = client.get("/probe", headers={"X-Forwarded-Proto": "https",
                                      "X-Forwarded-For": "203.0.113.9"})
    assert r.json() == {"scheme": "http", "client": "10.0.0.5"}, r.json()
