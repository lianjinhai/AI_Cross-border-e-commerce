"""UX-04a：只读 BFF（workbench）契约与权限矩阵验收。

覆盖：
  * 只读性：仅 GET、且调用后库行数不变；
  * 权限矩阵：OWNER/OPERATOR/READ_ONLY 的逐源放行/剔除（skipped）；
  * COMPLIANCE 投影剥离价格/库存动作（复用 launch_action_catalog.PRICE_STOCK_ACTIONS）；
  * FACTORY_COLLABORATOR 空待办（items 空、sources 全 skipped）；
  * 单源失败 → 200 且 partial=true；
  * route.return_to 白名单拦截；
  * counts 与 items 自洽。
"""
import pytest

from app.db import SessionLocal
from app.main import app
from app.models import AiAction, AlertEvent, WorkflowRun
from app.services import workbench
from app.services.workspace_context import (
    ROLE_COMPLIANCE,
    ROLE_FACTORY_COLLABORATOR,
    ROLE_OWNER,
    ROLE_PERMISSIONS,
    SOURCE_FACTORY,
    SOURCE_LEGACY,
    WorkspaceContext,
)
from app.workflows.launch_action_catalog import PRICE_STOCK_ACTIONS


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def role_headers(client):
    return {"admin": _login(client, "admin", "admin123"),
            "operator": _login(client, "ops", "ops123"),
            "viewer": _login(client, "viewer", "viewer123")}


def _row_counts():
    with SessionLocal() as db:
        return {"ai_actions": db.query(AiAction).count(),
                "alert_events": db.query(AlertEvent).count(),
                "workflow_runs": db.query(WorkflowRun).count()}


def _fabricated_context(role, permissions, *, workspace_id=1, source=SOURCE_LEGACY,
                        workspace_kind="ORGANIZATION", data_scope="WORKSPACE_ALL"):
    return WorkspaceContext(
        user_id=1, username="probe", display_name="probe", workspace_id=workspace_id,
        workspace_name="probe", workspace_kind=workspace_kind, membership_id=None,
        role=role, permissions=permissions, data_scope=data_scope, source=source,
        trace_id="probe-trace", legacy_tenant_id=1)


# ---------------------------------------------------------------- 只读性

def test_workbench_routes_are_get_only():
    # 经 OpenAPI 模式枚举本仓库实际注册的端点（`include_router` 的聚合实现不保证
    # 展平进 `app.routes`），断言两端点存在且**只暴露 GET**（只读红线）。
    paths = app.openapi().get("paths", {})
    for path in ("/api/workbench/todo", "/api/workbench/overview"):
        assert path in paths, f"未注册 {path}"
        assert set(paths[path]) == {"get"}, f"{path} 仅允许只读，实际方法：{set(paths[path])}"


def test_workbench_readonly_no_writes(client, auth_headers):
    before = _row_counts()
    assert client.get("/api/workbench/todo", headers=auth_headers).status_code == 200
    assert client.get("/api/workbench/overview", headers=auth_headers).status_code == 200
    assert _row_counts() == before, "只读 BFF 不得写库"


# ---------------------------------------------------------------- 信封与自洽

def test_todo_envelope_and_counts_consistent(client, auth_headers):
    body = client.get("/api/workbench/todo", headers=auth_headers).json()
    assert set(body) == {"items", "counts", "generated_at", "partial", "sources"}
    assert set(body["counts"]) == {"launch", "action", "alert", "review"}
    assert set(body["sources"]) == {"launch", "action", "alert", "review"}
    assert body["generated_at"].endswith("Z")
    assert isinstance(body["partial"], bool)
    for kind in ("launch", "action", "alert", "review"):
        matching = [it for it in body["items"] if it["type"] == kind]
        expected = sum(int(it["count"]) for it in matching)
        assert body["counts"][kind] == expected, f"{kind} 计数与 items 不自洽"
        for item in matching:
            assert item["severity"] in {"low", "mid", "high"}
            assert item["route"]["path"].startswith("/")


def test_overview_envelope(client, auth_headers):
    body = client.get("/api/workbench/overview", headers=auth_headers).json()
    assert set(body["sections"]) == {"metrics", "in_progress", "top_today",
                                     "need_human", "ai_done", "exceptions"}
    assert set(body["sources"]) == {"bi", "launch", "alert", "review", "workflow", "todo"}
    assert set(body["signals"]) == {"has_sales_shop", "sales_shop_count", "has_factory",
                                    "factory_match_count", "has_1688_credential",
                                    "member_count", "order_count_30d"}
    # v1.2：画像判定在前端纯函数（后端不产出 persona 标签）
    assert "persona" not in body
    assert isinstance(body["next_actions"], list)
    assert body["generated_at"].endswith("Z")
    # 1688 凭证信号只返回存在性布尔，绝不泄露密钥值
    assert isinstance(body["signals"]["has_1688_credential"], bool)


# ---------------------------------------------------------------- 权限矩阵

def test_permission_matrix_sources(client, role_headers):
    admin = client.get("/api/workbench/todo", headers=role_headers["admin"]).json()
    operator = client.get("/api/workbench/todo", headers=role_headers["operator"]).json()
    viewer = client.get("/api/workbench/todo", headers=role_headers["viewer"]).json()
    # OWNER/OPERATOR 有 listing:write 与 compliance:check → action/review 可读
    assert admin["sources"]["action"] == "ok"
    assert admin["sources"]["review"] == "ok"
    assert operator["sources"]["action"] == "ok"
    # READ_ONLY 无 listing:write / compliance:check → 该两源剔除（skipped，不报错）
    assert viewer["sources"]["action"] == "skipped"
    assert viewer["sources"]["review"] == "skipped"
    assert viewer["sources"]["launch"] == "ok"


def test_factory_collaborator_empty_todo():
    ctx = _fabricated_context(ROLE_FACTORY_COLLABORATOR, frozenset(), workspace_id=None,
                              source=SOURCE_FACTORY, workspace_kind="FACTORY",
                              data_scope="FACTORY_SELF")
    with SessionLocal() as db:
        todo = workbench.build_todo(db, ctx)
        overview = workbench.build_overview(db, ctx)
    assert todo["items"] == []
    assert all(value == 0 for value in todo["counts"].values())
    assert all(state == "skipped" for state in todo["sources"].values())
    assert all(state == "skipped" for state in overview["sources"].values())
    assert all(section is None for section in overview["sections"].values())
    assert all(value is None for value in overview["signals"].values())
    assert overview["partial"] is False


def test_platform_identity_not_tenant_workspace():
    ctx = _fabricated_context("PLATFORM_ADMIN", frozenset({"platform:admin"}),
                              workspace_id=None, source="PLATFORM", workspace_kind="PLATFORM")
    assert workbench._is_tenant_workspace(ctx) is False


# ---------------------------------------------------------------- COMPLIANCE 投影

def test_compliance_strips_price_stock_actions():
    price_action = {"action": "REPORT_PRICE", "step_code": "PRICE_REVIEW", "executable": True}
    assert "REPORT_PRICE" in PRICE_STOCK_ACTIONS
    projected = workbench.strip_price_stock_next_action(price_action, ROLE_COMPLIANCE)
    assert projected["action"] is None
    assert projected["executable"] is False
    # 非合规角色不受影响
    assert workbench.strip_price_stock_next_action(price_action, ROLE_OWNER) == price_action
    # 非价格/库存动作对合规角色保留
    keep = {"action": "COMPLETE_DATA", "step_code": "DATA", "executable": True}
    assert workbench.strip_price_stock_next_action(keep, ROLE_COMPLIANCE) == keep
    # 合规角色确实不持 listing:write（授权 Action 源对其为 skipped 的根因）
    assert not ROLE_PERMISSIONS[ROLE_COMPLIANCE].issuperset({"listing:write"})


# ---------------------------------------------------------------- 降级

def test_single_source_failure_still_200(client, auth_headers, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("模拟源故障")

    monkeypatch.setattr(workbench, "_todo_alert", _boom)
    monkeypatch.setattr(workbench, "_exceptions_section", _boom)
    todo = client.get("/api/workbench/todo", headers=auth_headers)
    assert todo.status_code == 200
    body = todo.json()
    assert body["partial"] is True
    assert body["sources"]["alert"] == "failed"
    overview = client.get("/api/workbench/overview", headers=auth_headers)
    assert overview.status_code == 200
    assert overview.json()["partial"] is True
    assert overview.json()["sources"]["alert"] == "failed"


# ---------------------------------------------------------------- return_to 白名单

def test_return_to_whitelist():
    assert workbench.safe_return_to("/launch") == "/launch"
    assert workbench.safe_return_to("/launch?mine=true") == "/launch?mine=true"
    assert workbench.safe_return_to("/listings/3?x=1") == "/listings/3?x=1"
    assert workbench.safe_return_to("/products") == "/products"
    assert workbench.safe_return_to("/shops") == "/shops"
    assert workbench.safe_return_to("//evil.com") is None
    assert workbench.safe_return_to("https://x") is None
    assert workbench.safe_return_to("/etc/../a") is None
    assert workbench.safe_return_to("/launcha") is None
    assert workbench.safe_return_to("") is None
    assert workbench.safe_return_to(None) is None
