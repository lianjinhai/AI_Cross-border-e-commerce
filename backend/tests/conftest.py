"""共享测试夹具（会话级）：数据库隔离 + 客户端 + 认证头。

为什么放在 conftest.py 而不是 test_api.py：
    这些夹具此前定义在 ``test_api.py`` 内，其他测试文件靠 ``from .test_api import client``
    复用。该写法隐含「test_api.py 必须最先被收集」的顺序假设——一旦有文件名排序更靠前
    的模块（如 ``test_admin_*.py``）先 import ``app.db`` 建立连接，会话级 ``_fresh_db``
    就无法删除测试库文件（Windows: PermissionError WinError 32），整批用例报错。
    这违反规范 §8 T-2「测试不得依赖执行顺序」。

    pytest 保证 ``conftest.py`` 在收集任何测试模块之前加载，因此把夹具移到这里后，
    环境变量与库文件清理一定先于所有测试模块的 import 发生，顺序依赖被彻底消除。

环境变量必须在 import ``app.*`` 之前设置（config 在导入时读取），故此处采用
模块级赋值 + 函数体内 import 的写法，并显式标注 noqa: E402。

并发隔离：测试库路径可用环境变量 ``ERP_TEST_DB`` 覆盖（文件名或绝对路径，
相对路径按 ``backend/`` 解析）。默认 ``test_erp.db`` 是**单实例**资源——两个
pytest 进程同时跑会互相踩踏，症状是大量 ``UNIQUE constraint failed:
settings.key``。需要并行时各自指定独立库，例如：

```powershell
$env:ERP_TEST_DB='test_erp_worker2.db'; python -m pytest -q
```

安全防呆（P0）：``_remove_db_files()`` 是**删除操作**，因此 ``ERP_TEST_DB``
必须经过 ``_guard_test_db_path()`` 校验——任何解析结果等于 ``backend/erp.db``
（业务主库）或 ``backend/test_erp.db``（历史固定名，可能残留真实数据）的取值
都会直接抛错终止，避免"误设环境变量 → 测试夹具删掉主库"的数据丢失路径。
"""
import os
import pathlib

# 业务主库与历史固定测试库名：绝不允许作为测试库被删除。
_FORBIDDEN_DB_NAMES = {"erp.db", "test_erp.db"}


# 测试库默认 backend/test_erp.db；ERP_TEST_DB 可覆盖。
# 默认文件名带进程号：同一台机器上残留/并发的 pytest 进程互不踩踏
# （固定文件名时，上一轮未退干净的进程持有句柄会让下一轮删库失败并复用脏库，
# 症状是大量 "UNIQUE constraint failed: settings.key" 或随机 errors）。
_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_OVERRIDE = os.environ.get("ERP_TEST_DB", "").strip()
if _OVERRIDE:
    _DB_FILE = pathlib.Path(_OVERRIDE)
else:
    _DB_FILE = _BACKEND_DIR / f"test_erp_{os.getpid()}.db"
if not _DB_FILE.is_absolute():
    _DB_FILE = _BACKEND_DIR / _DB_FILE


def _guard_test_db_path(path: pathlib.Path) -> pathlib.Path:
    """拒绝会把业务主库/历史固定库当成测试库的取值（防误删数据）。"""
    resolved = path.resolve()
    forbidden = {(_BACKEND_DIR / name).resolve() for name in _FORBIDDEN_DB_NAMES}
    if resolved in forbidden:
        raise RuntimeError(
            f"ERP_TEST_DB 指向受保护数据库 {resolved}，测试夹具会删除该文件，已拒绝启动。"
            f"请改用独立的测试库名（例如 test_erp_worker2.db）。"
        )
    return path


_DB_FILE = _guard_test_db_path(_DB_FILE)


def _remove_db_files() -> None:
    """删除测试库及其 WAL 旁文件。

    **顺序要紧**：WAL 模式下必须连同 ``-wal`` / ``-shm`` 一起删。只删主库文件
    时，残留的 WAL 会在下次建库时被 SQLite 回放到新库上，把上一轮数据"复活"
    进来（典型症状：种子写入撞 ``UNIQUE constraint failed: settings.key``）。
    """
    for suffix in ("-wal", "-shm", "-journal", ""):
        try:
            pathlib.Path(str(_DB_FILE) + suffix).unlink(missing_ok=True)
        except PermissionError:
            pass  # 仍被其它进程占用：交由调用方容忍（并发跑测试属不支持场景）


os.environ["ERP_DB_URL"] = "sqlite:///" + _DB_FILE.as_posix()
os.environ["ERP_SYNC_WORKFLOW"] = "1"
os.environ["ERP_JWT_SECRET"] = "test-secret-at-least-32-bytes-long"
os.environ["ERP_SUPERADMIN_PASSWORD"] = "root-test-123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _upgrade_to_head() -> None:
    """把测试库推进到与生产库相同的 Alembic head（跑完整迁移链）。

    为什么必须跑**完整**链而不是挑几条：
      1. ``models.py`` 刻意不注册 ``WorkspaceMembership`` 等身份模型（注册后
         ``init_db()`` 的 ``create_all`` 会自动建表，绕过 Phase 1 要求的
         "维护窗口 + 备份 + 演练"门禁）。因此这些表只能由迁移建出来——只跑部分
         迁移时 ``membership_table_available()`` 恒为 False，MEMBERSHIP 生产
         路径在 API 层零覆盖（审计 P0-2）。
      2. 只补跑个别迁移会留下列级漂移：实测"create_all + 仅 07/08"与生产库有
         **21 处列定义差异**（如 ``shops.app_secret`` 生产 ``VARCHAR(256)``、
         测试 ``VARCHAR(1024)``），意味着测试能写入的值在生产会被截断/拒绝。
         全链推进后差异归零（测试库 = 生产结构）。

    安全性：所有迁移脚本都实现了幂等（建表/加列前先探测），在 ``create_all``
    已建好表的库上重复执行不会报错也不会丢数据（实测 exit=0、integrity ok）。

    必须在**独立子进程**里执行：``alembic.ini`` 的 ``[logger_root]`` 会给
    root logger 装 ``StreamHandler(stderr)``（``configure_logger=False`` 也挡不住），
    而 pytest 的 ``caplog`` 依赖它自己注入的 handler——root logger 一旦被动过，
    日志类断言会全部静默失败（实测 ``caplog.records`` 变空）。子进程隔离后
    父进程的日志配置完全不受影响，迁移的 stdout 一并转发出来便于排查。
    """
    import subprocess
    import sys

    backend_dir = pathlib.Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(backend_dir), capture_output=True, text=True,
        # Windows 默认用 GBK 解码子进程输出；alembic 输出含中文时会抛
        # UnicodeDecodeError，导致 result.stderr 变 None，迁移失败的真实原因丢失。
        encoding="utf-8", errors="replace",
        env={**os.environ},  # ERP_DB_URL 已在模块顶部设置，子进程据此连同一个库
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"测试库迁移失败（exit={result.returncode}）：\n{result.stderr[-2000:]}")


@pytest.fixture(scope="session", autouse=True)
def _fresh_db():
    """会话开始时删除测试库文件，结束时释放连接池并再次删除。

    删除失败（Windows 下仍有连接持有文件）不视为测试失败：下次会话开始时
    会再删一次，且 pytest 用的是独立测试库，不影响业务库。
    """
    _remove_db_files()
    yield
    from app.db import engine

    engine.dispose()  # 先释放连接池，Windows 才能删除文件
    _remove_db_files()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # startup 触发建表 + 种子
        # 身份表与全部结构必须与生产库一致。放在 startup 之后：迁移的回填
        # （Revision B 等）需要 tenants / users 已由种子建好。
        _upgrade_to_head()
        yield c


@pytest.fixture(scope="session")
def _admin_token_cache():
    """会话级 token 缓存容器（仅保存最近一次成功签发的 admin token）。"""
    return {"token": None}


@pytest.fixture
def fetch_all(client):
    """返回一个「分页遍历取回**全量**条目」的函数，供集合比对类断言使用。

    **为什么不能用 `page_size=500` 一把梭**（审计 #10 / DEBT-27）：

    接口对 `page_size` 有上限（`app/pagination.py` 的 `MAX_PAGE_SIZE=200`），
    超出返回 422；而即便没有上限，一次性大页也只是「看起来取全了」——
    实测测试库 `orders` 恰好 500 条、与硬编码的 500 相等，
    一旦数据增长，跨租户隔离比对会**静默漏掉多出来的记录**（假绿）。

    本函数按 `total` 逐页取完再合并，数据量增长也不会漏；
    若某页返回的条目数与 `total` 不一致（说明有并发写入），直接断言失败而非静默截断。

    用法::

        def test_x(client, auth_headers, fetch_all):
            orders = fetch_all("/api/orders", auth_headers, status="paid")
    """
    from app.pagination import MAX_PAGE_SIZE

    def _fetch_all(path: str, headers: dict, **params) -> list[dict]:
        items: list[dict] = []
        page_num = 1
        total = None
        while True:
            query = {**params, "page_num": page_num, "page_size": MAX_PAGE_SIZE}
            r = client.get(path, headers=headers, params=query)
            assert r.status_code == 200, f"{path} {query} -> {r.status_code} {r.text[:200]}"
            body = r.json()
            if total is None:
                total = body["total"]
            items.extend(body["items"])
            if len(items) >= total or not body["items"]:
                break
            page_num += 1
        assert len(items) == total, (
            f"{path} 分页遍历取回 {len(items)} 条，但 total={total}——"
            f"可能存在并发写入，或分页实现有缺陷")
        return items

    return _fetch_all


@pytest.fixture
def auth_headers(client, _admin_token_cache):
    """演示租户 admin 的认证头。

    刻意使用函数级作用域：个别用例会修改 admin 口令，而改口令会递增
    ``token_version``，使既有 token 立即失效（见 ``app/auth.py`` 的版本校验）。
    若把 token 固定在会话级，后续用例会拿到已撤销的凭证，形成「谁先跑谁通过」
    的顺序依赖（规范 §8 T-2）。

    这里仍复用缓存的 token，但每次先探测有效性，失效即重新登录；额外开销
    仅为一次只读 ``/api/auth/me``。
    """
    token = _admin_token_cache.get("token")
    if token:
        probe = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        if probe.status_code == 200:
            return {"Authorization": f"Bearer {token}"}
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    _admin_token_cache["token"] = token
    return {"Authorization": f"Bearer {token}"}
