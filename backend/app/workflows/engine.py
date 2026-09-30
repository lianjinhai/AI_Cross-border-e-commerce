"""AI 工作流引擎（对应规划第十六章）：

模板步骤 -> 运行实例 -> 按序调度 Agent 动作，context_patch 在步骤间传递数据。
同步模式（settings.sync_workflow，测试用）或后台线程执行。
"""
import threading
import time
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import or_

from .. import config
from ..agents.orchestrator import (
    invoke_ad_drafts,
    invoke_discovery,
    invoke_listing,
    invoke_pricing,
    invoke_product,
)
from ..db import SessionLocal
from ..models import User, WorkflowRun, WorkflowStep, WorkflowTemplate, utcnow
from ..services.workspace_context import resolve_workspace_context

# (agent, action) 注册表： dispatch 时 lazy import，避免循环依赖
_KNOWN = [
    ("discovery", "pick_candidates"), ("discovery", "scan_trends"),
    ("product", "standardize_batch"),
    ("factory_opportunity", "scan_private_supply_batch"),
    ("supplier", "match_best_batch"), ("supplier", "forecast_batch"),
    ("compliance", "check_batch"),
    ("listing", "generate_batch"), ("listing_review", "review_batch"),
    ("listing", "publish_batch"),
    ("pricing", "reprice_batch"),
    ("ads", "draft_batch"),
]

_BATCH_ACTIONS = {"standardize_batch", "scan_private_supply_batch", "match_best_batch", "forecast_batch", "reprice_batch",
                  "draft_batch", "check_batch", "generate_batch", "review_batch", "publish_batch"}


class _LeaseHeartbeat:
    """长步骤租约心跳。使用独立 Session，且只在 worker_id 仍匹配时续租，
    避免旧 worker 覆盖新 worker 的所有权。
    """
    def __init__(self, run_id: int, worker_id: str, interval: float = 30.0):
        self.run_id, self.worker_id, self.interval = run_id, worker_id, interval
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self.stop.wait(self.interval):
            heartbeat_db = SessionLocal()
            try:
                heartbeat_db.query(WorkflowRun).filter(
                    WorkflowRun.id == self.run_id,
                    WorkflowRun.status == "running",
                    WorkflowRun.worker_id == self.worker_id,
                ).update({WorkflowRun.lease_until: datetime.utcnow() + timedelta(minutes=5)},
                         synchronize_session=False)
                heartbeat_db.commit()
            finally:
                heartbeat_db.close()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=1)


def _load_agent_class(agent_name: str):
    if agent_name == "discovery":
        from ..agents.discovery import DiscoveryAgent
        return DiscoveryAgent
    if agent_name == "product":
        from ..agents.discovery import ProductAgent
        return ProductAgent
    if agent_name == "supplier":
        from ..agents.supplier import SupplierAgent
        return SupplierAgent
    if agent_name == "factory_opportunity":
        from ..agents.factory_opportunity import FactoryOpportunityAgent
        return FactoryOpportunityAgent
    if agent_name == "compliance":
        from ..agents.compliance import ComplianceAgent
        return ComplianceAgent
    if agent_name == "listing":
        from ..agents.listing import ListingAgent
        return ListingAgent
    if agent_name == "listing_review":
        from ..agents.listing_review import ListingReviewAgent
        return ListingReviewAgent
    if agent_name == "pricing":
        from ..agents.pricing import PricingAgent
        return PricingAgent
    if agent_name == "ads":
        from ..agents.pricing import AdsAgent
        return AdsAgent
    raise ValueError(f"未知的 Agent: {agent_name}")


def run_step(agent_name: str, action: str, tenant_id: int, params: dict, context: dict) -> dict:
    """执行单个注册动作。"""
    if (agent_name, action) not in _KNOWN:
        raise ValueError(f"未注册的动作: {agent_name}.{action}")
    if (agent_name, action) in {("listing", "generate_batch"),
                                ("listing", "publish_batch"), ("ads", "draft_batch"),
                                ("pricing", "reprice_batch"), ("product", "standardize_batch"),
                                ("discovery", "pick_candidates")}:
        with SessionLocal() as action_db:
            requester_id = context.get("_action_requested_by")
            requester = action_db.get(User, requester_id) if requester_id is not None else None
            impersonating = bool(context.get("_action_impersonating"))
            if requester is not None and impersonating and requester.role == "superadmin":
                requester = SimpleNamespace(id=requester.id, username=requester.username,
                    display_name=requester.display_name, tenant_id=tenant_id, role="operator")
            if requester is None or requester.tenant_id != tenant_id:
                return {"business_status": "blocked", "context_patch": {},
                        "reason": "缺少可信 Action 发起者，请由人工恢复流程"}
            ctx = resolve_workspace_context(action_db, requester, is_impersonating=impersonating)
            if agent_name == "discovery":
                explicit = params.get("product_ids", context.get("product_ids"))
                return invoke_discovery(action_db, ctx, action, int(params.get("limit", 3)),
                    float(params.get("min_total", 60)), True, explicit,
                    scope_key=context.get("_action_scope"))
            if agent_name == "product":
                return invoke_product(action_db, ctx, action, params, context,
                                      scope_key=context.get("_action_scope"))
            if agent_name == "pricing":
                return invoke_pricing(action_db, ctx, action, params, context,
                                      scope_key=context.get("_action_scope"))
            if agent_name == "ads":
                return invoke_ad_drafts(action_db, ctx, params, context,
                                       scope_key=context.get("_action_scope"))
            return invoke_listing(action_db, ctx, action, params, context,
                                  scope_key=context.get("_action_scope"))
    cls = _load_agent_class(agent_name)
    with cls(tenant_id) as agent:
        method = getattr(agent, action)
        if action in _BATCH_ACTIONS:
            return method(params, context)
        if action == "scan_trends":
            return method()
    raise ValueError(f"动作调用失败: {agent_name}.{action}")


def start_run(tenant_id: int, template_key: str, context: dict | None = None,
              requested_by: int | None = None, is_impersonating: bool = False) -> dict:
    """按模板创建运行实例并派发执行，返回 run dict。"""
    db = SessionLocal()
    try:
        tpl = (db.query(WorkflowTemplate)
               .filter_by(tenant_id=tenant_id, key=template_key).first())
        if not tpl:
            raise ValueError(f"工作流模板 {template_key} 不存在")
        run_context = {key: value for key, value in (context or {}).items()
                       if not key.startswith("_action_")}
        # Action 发起人只接受服务端认证身份，不能从客户端 context 冒充。
        run_context.pop("_action_requested_by", None)
        run_context.pop("_action_impersonating", None)
        run_context.pop("_action_scope", None)
        if requested_by is not None:
            run_context["_action_requested_by"] = requested_by
            run_context["_action_impersonating"] = is_impersonating
        run = WorkflowRun(tenant_id=tenant_id, template_key=template_key, name=tpl.name,
                          status="queued", context=run_context)
        db.add(run)
        db.flush()
        for i, s in enumerate(tpl.steps or [], start=1):
            db.add(WorkflowStep(run_id=run.id, tenant_id=tenant_id, seq=i,
                                agent=s.get("agent", ""), action=s.get("action", ""),
                                params=s.get("params") or {}, status="pending"))
        db.commit()
        run_id = run.id
    finally:
        db.close()

    if config.settings.sync_workflow:
        run_workflow(run_id)
    else:
        threading.Thread(target=run_workflow, args=(run_id,), daemon=True).start()

    db2 = SessionLocal()
    try:
        from ..serialize import to_dict
        return to_dict(db2.get(WorkflowRun, run_id))
    finally:
        db2.close()


def _step_context(context, run_id, step):
    scoped = {key: value for key, value in context.items()
              if key != "_action_product_manifest"}
    scoped["_action_scope"] = f"workflow:{run_id}:step:{step.id}"
    if (step.agent, step.action) == ("product", "standardize_batch"):
        manifest = (step.output or {}).get("_standardization_manifest")
        if manifest is not None:
            scoped["_action_product_manifest"] = manifest
    return scoped


def run_workflow(run_id: int) -> None:
    """执行一次工作流运行：顺序执行 pending 步骤，失败即中止。"""
    db = SessionLocal()
    try:
        worker_id = uuid.uuid4().hex
        now = datetime.utcnow()
        claimed = (db.query(WorkflowRun).filter(
            WorkflowRun.id == run_id,
            or_(WorkflowRun.status == "queued",
                (WorkflowRun.status == "running") & (WorkflowRun.lease_until < now)))
            .update({WorkflowRun.status: "running", WorkflowRun.worker_id: worker_id,
                     WorkflowRun.lease_until: now + timedelta(minutes=5)},
                    synchronize_session=False))
        db.commit()
        if not claimed:
            return
        run = db.get(WorkflowRun, run_id)
        steps = (db.query(WorkflowStep).filter(WorkflowStep.run_id == run_id)
                 .order_by(WorkflowStep.seq).all())
        ctx = dict(run.context or {})
        overall_status = "success"
        for step in steps:
            # 断点续跑只执行未完成步骤。已成功步骤的 output/context 已在同一事务中
            # 持久化，重复执行会再次创建 Listing、报告、广告草稿等副作用。
            if step.status == "success":
                continue
            step.status = "running"
            step.attempts = int(step.attempts or 0) + 1
            step.started_at = utcnow()
            run.lease_until = datetime.utcnow() + timedelta(minutes=5)
            db.commit()
            try:
                with _LeaseHeartbeat(run_id, worker_id):
                    step_context = _step_context(ctx, run_id, step)
                    output = run_step(step.agent, step.action, run.tenant_id,
                                      dict(step.params or {}), step_context)
            except Exception as e:  # 步骤失败 -> 整个运行失败
                if step.attempts < int(step.max_attempts or 3):
                    step.status = "pending"
                    step.error = f"第 {step.attempts} 次失败，等待重试：{str(e)[:1500]}"
                    db.commit()
                    time.sleep(min(0.2 * (2 ** (step.attempts - 1)), 1.0))
                    return run_workflow(run_id) if _requeue(db, run) else None
                step.status = "failed"
                step.error = str(e)[:2000]
                step.finished_at = utcnow()
                run.status = "failed"
                run.error = f"步骤{step.seq} {step.agent}.{step.action} 失败: {e}"
                run.finished_at = utcnow()
                run.lease_until = None
                db.commit()
                return
            step.status = "success"
            patch = output.get("context_patch", {}) if isinstance(output, dict) else {}
            patch = {key: value for key, value in patch.items() if not key.startswith("_action_")}
            output_dict = output if isinstance(output, dict) else {"data": output}
            output_dict["_coordination"] = {
                "context_keys_read": sorted(ctx.keys()),
                "context_keys_written": sorted(patch.keys()),
                "upstream_step": step.seq - 1 if step.seq > 1 else None,
            }
            step.output = output_dict
            step.finished_at = utcnow()
            ctx.update(patch)
            run.context = dict(ctx)  # 新对象确保 ORM 检测到 JSON 变更
            business_status = output_dict.get("business_status")
            if business_status == "blocked":
                step.status = "blocked"
                run.status = "blocked"
                run.error = f"步骤{step.seq} {step.agent}.{step.action} 等待人工处理"
                run.finished_at = utcnow()
                run.lease_until = None
                for remaining in steps[step.seq:]:
                    remaining.status = "skipped"
                    remaining.error = "上游业务门禁阻断"
                db.commit()
                return
            if business_status == "partial":
                overall_status = "partial"
            db.commit()
        run.status = overall_status
        run.finished_at = utcnow()
        run.lease_until = None
        db.commit()
    finally:
        db.close()


def _requeue(db, run) -> bool:
    run.status = "queued"
    run.worker_id = ""
    run.lease_until = None
    db.commit()
    return True


def recover_incomplete_runs() -> int:
    """启动恢复：排队任务及租约已过期任务重新派发。"""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        ids = [r.id for r in db.query(WorkflowRun).filter(
            or_(WorkflowRun.status == "queued",
                (WorkflowRun.status == "running") & (WorkflowRun.lease_until < now))).all()]
        for run_id in ids:
            threading.Thread(target=run_workflow, args=(run_id,), daemon=True).start()
        return len(ids)
    finally:
        db.close()


def resume_run(run_id: int, tenant_id: int, requested_by: int | None = None,
               is_impersonating: bool = False) -> dict:
    db = SessionLocal()
    try:
        run = db.get(WorkflowRun, run_id)
        if not run or run.tenant_id != tenant_id:
            raise ValueError("工作流运行不存在")
        if run.status not in ("failed", "blocked", "partial"):
            raise ValueError(f"当前状态 {run.status} 不允许恢复")
        if requested_by is not None and not (run.context or {}).get("_action_requested_by"):
            run.context = {**(run.context or {}), "_action_requested_by": requested_by,
                           "_action_impersonating": is_impersonating}
        steps = db.query(WorkflowStep).filter(WorkflowStep.run_id == run.id).order_by(WorkflowStep.seq).all()
        for step in steps:
            if step.status in ("failed", "blocked", "skipped"):
                step.status, step.error = "pending", ""
        run.status, run.error, run.finished_at = "queued", "", None
        run.worker_id, run.lease_until = "", None
        db.commit()
    finally:
        db.close()
    if config.settings.sync_workflow:
        run_workflow(run_id)
    else:
        threading.Thread(target=run_workflow, args=(run_id,), daemon=True).start()
    db = SessionLocal()
    try:
        from ..serialize import to_dict
        return to_dict(db.get(WorkflowRun, run_id))
    finally:
        db.close()
