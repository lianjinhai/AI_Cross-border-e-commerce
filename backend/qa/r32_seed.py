"""R3-2 统一 QA 隔离种子库（**仅用于 QA 验收，不碰业务主库 backend/erp.db**）。

覆盖情形（见任务卡 46）：
  1 零基础用户(NEW_USER)          -> 租户 qa_newbie，无店铺、无工厂供给、单成员
  2 已有店铺卖家(STORE_OWNER)     -> 租户 qa_store，2 个销售店铺 + 商品
  3 有商品无店铺                  -> 租户 qa_noshop，有商品无店铺
  4 单商品双店铺                  -> qa_store 的同一商品在两个店铺各一条上线流程
  5 有真实待办                    -> qa_store：上线/待审批动作/风险告警/人工复核
  6 无待办                        -> qa_newbie（各源为 ok 但计数为 0）
  7 部分数据源失败/信号缺失       -> 合规账号（只读部分域，signals 缺键 -> overview.partial）
  8 只读角色                      -> qa_viewer（viewer -> READ_ONLY）
  9 合规角色                      -> qa_compliance（compliance_approver -> COMPLIANCE）
 10 Workspace 切换                -> 多个租户/账号
 11 待办处理后返回                -> 依赖前端 return_to（无需额外种子）
 12 移动端宽度 / 全工具入口       -> 纯前端，无需额外种子

安全：本脚本只在 ERP_DB_URL 指向的隔离库上运行；默认库为 backend/qa_r32.db。
运行： python qa/r32_seed.py
"""
from __future__ import annotations

import os
import pathlib
import sys
from datetime import datetime, timedelta

_BACKEND = pathlib.Path(__file__).resolve().parent.parent
_DB_FILE = _BACKEND / "qa_r32.db"
os.environ["ERP_DB_URL"] = "sqlite:///" + _DB_FILE.as_posix()
os.environ["ERP_JWT_SECRET"] = "qa-r32-secret-at-least-32-bytes-long"
os.environ["ERP_SYNC_WORKFLOW"] = "1"
os.environ["ERP_SUPERADMIN_PASSWORD"] = "qa-root-123456"
os.environ.setdefault("ERP_ENV", "development")

sys.path.insert(0, str(_BACKEND))

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (  # noqa: E402
    AiAction,
    AlertEvent,
    Listing,
    ListingReviewDecision,
    Order,
    Product,
    Shop,
    Tenant,
    User,
)
from app.seed import seed_if_empty  # noqa: E402
from app.services.workspace_context import resolve_workspace_context  # noqa: E402
from app.workflows.launch_records import create_launch  # noqa: E402
from app.workflows.profiles import create_profile, publish_profile  # noqa: E402

PLATFORM = "qaj2"
CONTRACT = "QA_R32"
PASS = "qa123456"
OWNER = "qa_owner"
OPS = "qa_ops"
VIEWER = "qa_viewer"
COMPLIANCE = "qa_compliance"
NEWBIE = "qa_newbie"
NOSHOP = "qa_noshop"


def _profile(market="SG", version=1):
    """本地契约流程（与 test_qa_r31c_j1_e2e._profile 同源），平台 qaj2。"""
    steps = [
        {"step_code": "INFO", "step_name": "商品资料", "business_type": "DATA_PREPARATION",
         "execution_mode": "MANUAL_TASK", "actor": "USER", "sequence": 0, "required": True,
         "dependencies": [], "available_actions": ["COMPLETE_DATA"],
         "evidence_requirements": ["INFORMATION_EVIDENCE"],
         "completion_condition": {"all": [{"present": "product.title"},
                                          {"asset_rights_allowed": "PUBLISHABLE"}]}},
        {"step_code": "SUBMISSION", "step_name": "提交平台", "business_type": "PLATFORM_SUBMISSION",
         "execution_mode": "ADAPTER_TASK", "actor": "SYSTEM", "sequence": 1, "required": True,
         "dependencies": ["INFO"], "available_actions": ["SUBMIT_PLATFORM"],
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
    return {"profile_key": CONTRACT, "version": version, "name": "QA R3-2 本地契约样本",
            "description": "本地流程验证，不代表真实平台接入。",
            "environment": "CONTRACT_TEST", "verification_status": "UNVERIFIED",
            "platform": PLATFORM, "market": market, "fulfillment_mode": "DROPSHIP",
            "category_scope": ["ANY"], "status_mapping": {"unknown": "BLOCK", "statuses": {}},
            "steps": steps}


def _tenant(db, name) -> Tenant:
    row = Tenant(name=name, plan="pro", status="active")
    db.add(row)
    db.flush()
    return row


def _user(db, tenant, username, role, display) -> User:
    row = User(tenant_id=tenant.id, username=username, password_hash=hash_password(PASS),
               role=role, display_name=display, status="active")
    db.add(row)
    db.flush()
    return row


def _shop(db, tenant, platform, name, market) -> Shop:
    row = Shop(tenant_id=tenant.id, platform=platform, shop_name=name, market=market,
               fulfillment_mode="DROPSHIP", role="sales", status="authorized", is_demo=False)
    db.add(row)
    db.flush()
    return row


def _product(db, tenant, sku, title, category="家居") -> Product:
    row = Product(tenant_id=tenant.id, sku=sku, title=title, category=category,
                  images=["https://example.com/main.jpg"], attrs={"destination_country": "SG"})
    db.add(row)
    db.flush()
    return row


def main() -> None:
    if _DB_FILE.exists():
        for suffix in ("", "-wal", "-shm"):
            pathlib.Path(str(_DB_FILE) + suffix).unlink(missing_ok=True)
    init_db()
    seed_if_empty()  # 演示租户（admin/admin123）——不影响下面新建的 QA 租户

    with SessionLocal() as db:
        # ---------------------------------------------------------- 租户 A：已有店铺卖家
        t_store = _tenant(db, "QA 店铺租户")
        owner = _user(db, t_store, OWNER, "owner", "店主")
        _user(db, t_store, OPS, "operator", "运营")
        _user(db, t_store, VIEWER, "viewer", "只读账号")
        _user(db, t_store, COMPLIANCE, "compliance_approver", "合规审批")

        shop_sg = _shop(db, t_store, PLATFORM, "美国站一号店", "SG")
        shop_sg2 = _shop(db, t_store, PLATFORM, "美国站二号店", "SG")
        p1 = _product(db, t_store, "qa-r32-1", "弹力带 · 家用健身")
        p2 = _product(db, t_store, "qa-r32-2", "瑜伽垫 · 加厚防滑")

        # 订单（BI/GMV 口径；source=api 计入 order_count_30d）
        for i in range(6):
            db.add(Order(tenant_id=t_store.id, shop_id=shop_sg.id, platform=PLATFORM,
                         external_no=f"QA-R32-{i}", product_id=p1.id, qty=1 + i % 3,
                         amount=20.0 + i * 5, cost=12.0 + i * 2, profit=8.0 + i * 3,
                         currency="USD", status="paid", source="api", country="SG",
                         buyer_name=f"buyer{i}", created_at=datetime.utcnow() - timedelta(days=i)))

        # 风险告警（open）
        db.add(AlertEvent(tenant_id=t_store.id, rule_key="stockout_risk", level="high",
                          subject_type="product", subject_id=p1.id,
                          title="弹力带即将断货", detail="周需求 120 > 在手库存 60",
                          evidence={}, status="open"))
        db.add(AlertEvent(tenant_id=t_store.id, rule_key="ads_burning", level="mid",
                          subject_type="shop", subject_id=shop_sg.id,
                          title="广告 ROI 过低", detail="近 3 天 ROI 0.4 < 阈值 0.5",
                          evidence={}, status="open"))

        db.commit()

        # 待审批动作（PUBLISH_LISTING / PENDING_APPROVAL）
        db.add(AiAction(tenant_id=t_store.id, workspace_id=t_store.id, task_id=None,
                        agent_type="listing_agent", action_type="PUBLISH_LISTING",
                        target_type="listing", target_id=p1.id, reason="AI 建议上架美国站一号店",
                        evidence={"shop_id": shop_sg.id}, expected_impact={"gmv": "+"},
                        risk_level="mid", required_permission="listing:write",
                        execution_mode="APPROVAL", approval_required=True,
                        status="PENDING_APPROVAL", requested_by=owner.id,
                        idempotency_key="qa-r32-action-1"))
        db.commit()

        # 上线流程：商品 p1 在两个店铺各一条（单商品双店铺）
        ctx_owner = resolve_workspace_context(db, owner)
        profile = create_profile(db, ctx_owner, _profile())
        publish_profile(db, ctx_owner, profile.id, profile.definition_hash)
        db.commit()
        run_1 = create_launch(db, ctx_owner, p1.id, shop_sg.id, "qa-r32-run-1")
        run_2 = create_launch(db, ctx_owner, p1.id, shop_sg2.id, "qa-r32-run-2")
        run_3 = create_launch(db, ctx_owner, p2.id, shop_sg.id, "qa-r32-run-3")
        db.commit()

        # 物化步骤状态（等价于前端打开一次上线详情触发确定性刷新）：
        # 否则 WorkflowStep.step_status 仍为创建时的 PENDING，`mine=true` 待办查不到。
        from app.workflows import launch_dto
        for run in (run_1, run_2, run_3):
            launch_dto.load_detail(db, ctx_owner, run.id)
            db.commit()

        # 反例：把 p2 的上线流程 INFO 步骤置为 FAILED（未干系人待处理 -> 「被阻断」），
        # 用于验证计数条「被阻断」>0、阻断摘要、TaskCenter「受阻」视图（跨店不合并的反例）。
        from app.models import WorkflowStep
        fail_step = (db.query(WorkflowStep)
                     .filter_by(run_id=run_3.id, step_code="INFO").one())
        fail_step.step_status = "FAILED"
        db.commit()

        # 人工复核待办：制造一条 manual_required 复核决策
        listing = Listing(tenant_id=t_store.id, product_id=p2.id, shop_id=shop_sg.id,
                          platform=PLATFORM, title=p2.title, status="draft",
                          created_by=owner.id, last_edited_by=owner.id)
        db.add(listing)
        db.flush()
        db.add(ListingReviewDecision(tenant_id=t_store.id, listing_id=listing.id,
                                     product_id=p2.id, platform=PLATFORM,
                                     decision="manual_required", reasons=["含高风险词"],
                                     evidence={}, rule_version="qa", rule_source="qa"))
        db.commit()

        # ---------------------------------------------------------- 租户 B：零基础新手
        t_new = _tenant(db, "QA 新手租户")
        _user(db, t_new, NEWBIE, "owner", "新手店主")
        db.commit()

        # ---------------------------------------------------------- 租户 C：有商品无店铺
        t_noshop = _tenant(db, "QA 有货无店租户")
        _user(db, t_noshop, NOSHOP, "owner", "有货无店")
        _product(db, t_noshop, "qa-r32-noshop", "待上架商品 · 无店铺")
        db.commit()

        print("=== R3-2 QA SEED DONE ===")
        print(f"DB: {_DB_FILE}")
        print(f"store tenant id={t_store.id} ran runs: {run_1.id}, {run_2.id}, {run_3.id}")
        print(f"shops: {shop_sg.id}, {shop_sg2.id}  products: {p1.id}, {p2.id}")
        print("accounts (password=qa123456):")
        print("  qa_owner      STORE_OWNER/OWNER")
        print("  qa_ops        OWNER 域/OPERATOR")
        print("  qa_viewer     READ_ONLY")
        print("  qa_compliance COMPLIANCE")
        print("  qa_newbie     NEW_USER")
        print("  qa_noshop     有商品无店铺")
        print("  admin/admin123 演示租户（对照）")


if __name__ == "__main__":
    main()
