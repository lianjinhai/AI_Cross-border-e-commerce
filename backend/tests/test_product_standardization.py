"""商品标准化 Action：隔离、字段保护、恢复、执行事务与真实入口。"""

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.discovery import ProductAgent
from app.agents.orchestrator import invoke_product
from app.db import Base, SessionLocal
from app.models import AiAction, AiLog, Product, Tenant, User, WorkflowTemplate
from app.services.action_system import HANDLERS, execute_action, submit_action
from app.services.ai_actions import ActionError
from app.services.product_standardization import safe_fields, snapshot
from app.services.workspace_context import resolve_workspace_context
from app.tools.product import product_dict


@pytest.fixture
def case(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="商品标准化独立探针")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="product-owner", password_hash="unused", role="admin")
        product = Product(tenant_id=tenant.id, sku="STANDARD-1", title="Desk organizer",
                          category="旧类目", status="active",
                          attrs={"sale_price": 25, "supplier_price": 8, "stock": 7,
                                 "private": {"keep": True}})
        db.add_all([user, product])
        db.commit()
        ctx = resolve_workspace_context(db, user)
        monkeypatch.setattr("app.agents.base.SessionLocal", lambda: Session(engine))
        monkeypatch.setattr(ProductAgent, "ask_json", lambda *args, **kwargs: ({"attrs": {
            "material": "PP", "color": "红色", "weight_kg": 0.3, "sale_price": 1,
            "stock": 0}, "dedupe_hash": "forged", "is_duplicate": True}, "llm"))
        yield db, ctx, user, product
    engine.dispose()


def proposal(product):
    data = product_dict(product)
    return {"action_type": "UPDATE_PRODUCT_CONTENT", "target_type": "product",
            "target_id": product.id, "reason": "标准化测试",
            "payload": {"before": snapshot(data), **safe_fields(data, "家居")}}


@pytest.mark.parametrize("title,weight,expected", [
    ("2000kg product", None, 0.3), ("9" * 400 + "kg product", None, 0.3),
    ("Product", "0.8", 0.8), ("Product", float("inf"), 0.3),
    ("Product", True, 0.3), ("Product", -2, 0.3)])
def test_safe_weight_defaults_and_legacy_numeric_strings(title, weight, expected):
    data = {"title": title, "attrs": {"weight_kg": weight}}
    fields = safe_fields(data, "3C配件")
    assert fields["category"] == "3C配件" and fields["attrs_patch"]["weight_kg"] == expected
    assert safe_fields(data, {})["category"] == "家居"


def test_product_agent_never_reads_or_writes_business_orm(case):
    db, ctx, _, product = case
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app/agents/discovery.py")
                     .read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "ProductAgent")
    assert not [node for node in ast.walk(cls) if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute) and node.value.attr == "db"]
    before = product_dict(product)
    with ProductAgent(product.tenant_id, context=ctx) as agent:
        output = agent.standardize(product.id)
        batch = agent.standardize_batch({"product_ids": []}, {})
    db.refresh(product)
    assert product_dict(product) == before and db.query(AiAction).count() == 0
    assert output["_action_proposal"]["action_type"] == "UPDATE_PRODUCT_CONTENT"
    assert output["dedupe_hash"] != "forged" and batch == {"proposals": [], "errors": []}


def test_executor_protects_business_fields_and_replays_original_result(case, monkeypatch):
    db, ctx, _, product = case
    protected = dict(product.attrs)
    first = invoke_product(db, ctx, "standardize", product.id, scope_key="same")
    monkeypatch.setattr(ProductAgent, "standardize", lambda *args: pytest.fail("重放不应调用模型"))
    replay = invoke_product(db, ctx, "standardize", product.id, scope_key="same")
    assert first == replay and first["action_status"] == "SUCCESS"
    assert not first["is_duplicate"] and first["duplicate_of"] == 0
    db.refresh(product)
    assert all(product.attrs[key] == value for key, value in protected.items())
    action = db.query(AiAction).one()
    assert (action.risk_level, action.required_permission, action.execution_mode) == (
        "LOW", "product:write", "AUTO_SAFE")
    assert action.outcome["before"]["attrs"] == protected


@pytest.mark.parametrize("tamper", ["extra", "attrs", "hash", "category", "price"])
def test_executor_rejects_unsafe_or_forged_payload(case, tamper):
    db, ctx, _, product = case
    item = proposal(product)
    payload = item["payload"]
    if tamper == "extra":
        payload["attrs"] = {"sale_price": 1}
    elif tamper == "attrs":
        payload["attrs_patch"]["stock"] = 0
    elif tamper == "hash":
        payload["dedupe_hash"] = "forged"
    elif tamper == "category":
        payload["category"] = "unrestricted"
    else:
        payload["sale_price"] = 1
    before = product_dict(product)
    action = submit_action(db, ctx, "product", item, tamper)
    assert execute_action(db, ctx, action.id).status == "FAILED"
    db.refresh(product)
    assert product_dict(product) == before


def test_stale_proposal_and_failed_transaction_preserve_product(case, monkeypatch):
    db, ctx, _, product = case
    action = submit_action(db, ctx, "product", proposal(product), "stale")
    product.attrs = {**product.attrs, "stock": 9}
    db.commit()
    assert execute_action(db, ctx, action.id).status == "FAILED"
    assert product.attrs["stock"] == 9
    action = submit_action(db, ctx, "product", proposal(product), "failure")
    before = product_dict(product)
    original = HANDLERS["UPDATE_PRODUCT_CONTENT"]

    def fail(db, action, payload):
        original(db, action, payload)
        raise RuntimeError("模拟执行后故障")

    monkeypatch.setitem(HANDLERS, "UPDATE_PRODUCT_CONTENT", fail)
    assert execute_action(db, ctx, action.id).status == "FAILED"
    db.refresh(product)
    assert product_dict(product) == before
    with pytest.raises(ActionError):
        invoke_product(db, ctx, "standardize", product.id, scope_key="failure")


def test_foreign_target_and_revoked_requester_are_denied(case):
    db, ctx, user, product = case
    tenant = Tenant(name="标准化其他租户")
    db.add(tenant)
    db.flush()
    foreign = Product(tenant_id=tenant.id, sku="FOREIGN", title=product.title)
    db.add(foreign)
    db.commit()
    with pytest.raises(ActionError, match="不存在"):
        submit_action(db, ctx, "product", proposal(foreign), "foreign")
    action = submit_action(db, ctx, "product", proposal(product), "revoke")
    user.role = "viewer"
    db.commit()
    with pytest.raises(ActionError, match="权限"):
        execute_action(db, ctx, action.id)
    assert action.status == "APPROVED" and product.category == "旧类目"


def test_batch_recovery_keeps_range_and_duplicate_facts(case, monkeypatch):
    db, ctx, _, product = case
    second = Product(tenant_id=product.tenant_id, sku="STANDARD-2", title=product.title,
                     category=product.category, status="active", attrs=product.attrs)
    db.add(second)
    db.commit()
    ids = [product.id, second.id]
    first = invoke_product(db, ctx, "standardize_batch", {"product_ids": ids}, {}, scope_key="batch")
    assert first["standardized"] == [product.id] and first["duplicates"] == [second.id]
    assert first["results"][1]["duplicate_of"] == product.id
    monkeypatch.setattr(ProductAgent, "standardize", lambda *args: pytest.fail("不能重新生成"))
    replay = invoke_product(db, ctx, "standardize_batch", {}, {}, scope_key="batch")
    assert first == replay and db.query(AiAction).count() == 2
    with pytest.raises(ActionError, match="清单已变化"):
        invoke_product(db, ctx, "standardize_batch", {"product_ids": [product.id]}, {}, scope_key="batch")
    empty = invoke_product(db, ctx, "standardize_batch", {"product_ids": []}, {}, scope_key="empty")
    assert empty["standardized"] == empty["duplicates"] == empty["results"] == []


@pytest.mark.parametrize("status", ["FAILED", "REJECTED", "EXECUTING"])
def test_recovery_never_bypasses_terminal_or_claimed_action(case, monkeypatch, status):
    db, ctx, _, product = case
    action = submit_action(db, ctx, "product", proposal(product), "blocked:product:1",
        scope_manifest={"scope": "blocked", "product_ids": [product.id]})
    action.evidence = {**action.evidence, "scope_key": f"blocked:product:{product.id}"}
    action.status = status
    db.commit()
    monkeypatch.setattr(ProductAgent, "standardize", lambda *args: pytest.fail("禁止重提案绕过终态"))
    result = invoke_product(db, ctx, "standardize_batch", {"product_ids": [product.id]}, {},
                            scope_key="blocked")
    assert result["business_status"] == "blocked" and len(result["errors"]) == 1
    assert result["results"] == [] and db.query(AiAction).count() == 1
    db.refresh(action)
    assert action.status == status


def test_concurrent_duplicate_execution_is_serialized(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'standardization.db').as_posix()}",
                           connect_args={"timeout": 10, "check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="并发标准化")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="concurrent-product", password_hash="unused", role="admin")
        products = [Product(tenant_id=tenant.id, sku=f"CONCURRENT-{i}", title="Desk organizer")
                    for i in range(2)]
        db.add_all([user, *products])
        db.commit()
        ctx = resolve_workspace_context(db, user)
        actions = [submit_action(db, ctx, "product", proposal(row), f"concurrent:{i}").id
                   for i, row in enumerate(products)]
    barrier = Barrier(2)

    def execute(action_id):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            action = execute_action(db, ctx, action_id)
            assert action.status == "SUCCESS"
            return action.outcome["result"]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(execute, actions))
        assert sorted(result["is_duplicate"] for result in results) == [False, True]
        first = next(result for result in results if not result["is_duplicate"])
        duplicate = next(result for result in results if result["is_duplicate"])
        assert duplicate["duplicate_of"] == first["product_id"]
    finally:
        engine.dispose()


def test_concurrent_different_payloads_cannot_create_two_actions_for_same_scope(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'scope.db').as_posix()}",
                           connect_args={"timeout": 10, "check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="并发范围")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, username="scope-product", password_hash="unused", role="admin")
        row = Product(tenant_id=tenant.id, sku="SCOPE-1", title="Desk organizer")
        db.add_all([user, row])
        db.commit()
        ctx = resolve_workspace_context(db, user)
        data = product_dict(row)
        items = [{"action_type": "UPDATE_PRODUCT_CONTENT", "target_type": "product",
                  "target_id": row.id, "payload": {"before": snapshot(data),
                      **safe_fields(data, "家居", {"color": color})}}
                 for color in ("红色", "蓝色")]
    barrier = Barrier(2)

    def submit(item):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                return submit_action(db, ctx, "product", item, "same-scope").id
            except ActionError as exc:
                db.rollback()
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, items))
        assert 409 in results
        with Session(engine) as db:
            assert db.query(AiAction).count() == 1
            assert db.query(AiAction).one().status == "APPROVED"
    finally:
        engine.dispose()


def test_http_and_workflow_execute_through_actions(client, auth_headers):
    product = client.post("/api/products", headers=auth_headers,
                          json={"title": "Standardization HTTP", "attrs": {"sale_price": 29}}).json()
    response = client.post(f"/api/products/{product['id']}/standardize", headers=auth_headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["action_status"] == "SUCCESS" and result["attrs"]["sale_price"] == 29
    with SessionLocal() as db:
        row = db.get(Product, product["id"])
        template = WorkflowTemplate(tenant_id=row.tenant_id, key="standardize-probe", name="标准化闭环",
            steps=[{"agent": "product", "action": "standardize_batch", "params": {"product_ids": [row.id]}}])
        db.add(template)
        db.commit()
    run = client.post("/api/workflows/run", headers=auth_headers,
                      json={"template_key": "standardize-probe", "context": {
                          "_action_scope": "forged", "_action_requested_by": 999999,
                          "scope_manifest": {"product_ids": []}}})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "success" and body["steps"][0]["status"] == "success", body
    assert body["context"]["product_ids"] == [product["id"]]
    with SessionLocal() as db:
        actions = db.query(AiAction).filter_by(action_type="UPDATE_PRODUCT_CONTENT", target_id=product["id"]).all()
        assert len(actions) == 2 and all(action.status == "SUCCESS" for action in actions)
        assert all(action.evidence["scope_key"] != "forged" for action in actions)
        workflow_action = next(action for action in actions if "scope_manifest" in action.evidence)
        assert workflow_action.evidence["scope_manifest"]["product_ids"] == [product["id"]]


def test_real_workflow_partial_failure_resume_retains_input_scope(client, auth_headers):
    product = client.post("/api/products", headers=auth_headers,
                          json={"title": "Partial standardization workflow"}).json()
    with SessionLocal() as db:
        row = db.get(Product, product["id"])
        db.add(WorkflowTemplate(tenant_id=row.tenant_id, key="standardize-partial", name="部分失败",
            steps=[{"agent": "product", "action": "standardize_batch", "params": {}}]))
        db.commit()
    ids = [product["id"], 99999999]
    response = client.post("/api/workflows/run", headers=auth_headers,
        json={"template_key": "standardize-partial", "context": {"product_ids": ids}})
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["status"] == "blocked" and first["context"]["product_ids"] == ids
    with SessionLocal() as db:
        before = product_dict(db.get(Product, product["id"]))
        action_ids = [action.id for action in db.query(AiAction).filter_by(
            action_type="UPDATE_PRODUCT_CONTENT", target_id=product["id"]).all()]
    response = client.post(f"/api/workflows/runs/{first['id']}/resume", headers=auth_headers)
    assert response.status_code == 200, response.text
    replay = response.json()
    assert replay["status"] == "blocked" and replay["context"]["product_ids"] == ids
    with SessionLocal() as db:
        assert product_dict(db.get(Product, product["id"])) == before
        assert [action.id for action in db.query(AiAction).filter_by(
            action_type="UPDATE_PRODUCT_CONTENT", target_id=product["id"]).all()] == action_ids


def test_workflow_with_zero_actions_retains_failed_auto_selected_range(client, auth_headers, monkeypatch):
    product = client.post("/api/products", headers=auth_headers,
                          json={"title": "Zero Action recovery"}).json()
    with SessionLocal() as db:
        row = db.get(Product, product["id"])
        row.status = "active"
        db.add(WorkflowTemplate(tenant_id=row.tenant_id, key="standardize-zero", name="零提案失败",
            steps=[{"agent": "product", "action": "standardize_batch", "params": {}}]))
        db.commit()
    monkeypatch.setattr(ProductAgent, "standardize", lambda self, pid: (_ for _ in ()).throw(
        ValueError("提案生成失败")))
    response = client.post("/api/workflows/run", headers=auth_headers,
        json={"template_key": "standardize-zero", "context": {
            "_action_product_manifest": {"scope": "forged", "product_ids": []}}})
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["status"] == "blocked"
    assert "_action_product_manifest" not in first["context"]
    ids = first["steps"][0]["output"]["_standardization_manifest"]["product_ids"]
    assert product["id"] in ids
    with SessionLocal() as db:
        # 本用例把 standardize 整体 mock 成失败，没有改动任何商品；
        # 原先这里把「全部活跃商品」标记 deleted 做清理，会让后续用例
        # 查不到商品（如 test_ai_native_p1 取 products[0] 直接 IndexError）。
        assert db.query(AiAction).filter_by(action_type="UPDATE_PRODUCT_CONTENT",
                                           target_id=product["id"]).count() == 0
    response = client.post(f"/api/workflows/runs/{first['id']}/resume", headers=auth_headers)
    assert response.status_code == 200 and response.json()["status"] == "blocked", response.text
    detail = client.get(f"/api/workflows/runs/{first['id']}", headers=auth_headers).json()
    assert detail["steps"][0]["output"]["_standardization_manifest"]["product_ids"] == ids
    assert len(detail["steps"][0]["output"]["errors"]) == len(ids)


def test_action_evidence_records_proposal_source(case):
    """建议来源必须落进 Action 证据：mode=llm 时不能标成 rule，反之亦然。"""
    db, ctx, _, product = case
    result = invoke_product(db, ctx, "standardize", product.id, scope_key="s4-source")
    db.expire_all()
    action = db.query(AiAction).filter_by(id=result["action_id"]).one()
    assert action.evidence["source"] == "llm"
    assert action.evidence["model_mode"] == "llm"


def test_invalid_model_output_degrades_to_rule_and_is_traced(monkeypatch):
    """模型返回非结构化内容：降级规则引擎，且审计里留下「llm 失败」痕迹。

    S4 要求「无效结构不造成功建议」——降级本身可接受（离线可用），
    但事后必须能看出模型确实失败过，不能只剩一条 rule 日志。
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="模型降级探针")
        db.add(tenant)
        db.commit()
        tenant_id = tenant.id

    class FakeRouter:
        available = True

        def ask_json(self, *args, **kwargs):
            return {"parsed": {}, "raw": {"model": "fake-model",
                                          "content": "not json", "latency_ms": 7}}

    monkeypatch.setattr("app.agents.base.SessionLocal", lambda: Session(engine))
    monkeypatch.setattr("app.agents.base.ModelRouter", lambda _db: FakeRouter())
    agent = ProductAgent(tenant_id)
    try:
        result, mode = agent.ask_json("standardize", "system", "prompt",
                                      fallback=lambda: {"attrs": {"color": "白"}})
    finally:
        agent.close()

    assert mode == "rule" and result == {"attrs": {"color": "白"}}
    with Session(engine) as fresh:
        logs = fresh.query(AiLog).filter(AiLog.action == "standardize").order_by(AiLog.id).all()
        assert [(row.mode, row.ok) for row in logs] == [("llm", False), ("rule", True)]
        assert logs[0].response == "not json" and logs[0].model == "fake-model"
    engine.dispose()


def test_repeat_standardize_reuses_success_action(case):
    """同一商品、目标值未变化的重复请求必须复用既有 Action（不产生第二次写）。"""
    db, ctx, _, product = case
    first = invoke_product(db, ctx, "standardize", product.id, scope_key="s4-replay-1")
    second = invoke_product(db, ctx, "standardize", product.id, scope_key="s4-replay-2")
    assert second["action_id"] == first["action_id"]
    assert second.get("idempotent_replay") is True
    assert db.query(AiAction).filter_by(action_type="UPDATE_PRODUCT_CONTENT",
                                        target_id=product.id).count() == 1
