"""可信合规产物保存：整批报告、来源摘要与受限风险 Action 原子提交。"""

from ..models import AiAction, AiDecision, ComplianceReport, Tenant
from .action_identity import require_action_permission
from .action_system import execute_action, submit_action
from .ai_actions import ActionError
from .compliance_analysis import rule_analysis, validate_result
from .compliance_facts import current_basis, latest_report, metadata, public_report, targets
from .review_analysis import digest


def validate_items(items):
    if not isinstance(items, list) or len(items) > 100:
        raise ActionError(400, "合规批次范围无效")
    for item in items:
        if (not isinstance(item, dict) or set(item) != {"target_type", "ref_id"}
                or item["target_type"] not in {"product", "listing"}
                or type(item["ref_id"]) is not int or item["ref_id"] <= 0):
            raise ActionError(400, "合规目标结构无效")
    if len({(item["target_type"], item["ref_id"]) for item in items}) != len(items):
        raise ActionError(400, "合规批次不能重复目标")


def compliance_scope_items(params, context):
    items = params.get("items")
    if items is None:
        product_ids = params.get("product_ids", context.get("product_ids", []))
        listing_ids = params.get("listing_ids", context.get("listing_ids", []))
        if not isinstance(product_ids, list) or not isinstance(listing_ids, list):
            raise ActionError(400, "合规商品或 Listing 清单无效")
        items = ([{"target_type": "product", "ref_id": pid} for pid in product_ids]
                 + [{"target_type": "listing", "ref_id": lid} for lid in listing_ids])
    validate_items(items)
    return items


def _saved_batch(db, ctx, scope):
    return db.query(AiDecision).filter(AiDecision.tenant_id == ctx.legacy_tenant_id,
        AiDecision.agent == "compliance", AiDecision.action == "check_batch_output",
        AiDecision.evidence["scope"].as_string() == scope,
        AiDecision.evidence["requested_by"].as_integer() == ctx.user_id
    ).order_by(AiDecision.id.desc()).populate_existing().first()


def recover_compliance(db, ctx, scope, items):
    try:
        results = _recover_compliance(db, ctx, scope, items)
        if results is not None:
            db.commit()  # 重放全部快照在同一租户锁内验证，完成后释放锁。
        return results
    except Exception:
        db.rollback()
        raise


def _recover_compliance(db, ctx, scope, items):
    current = require_action_permission(db, ctx, "compliance:check")
    validate_items(items)
    saved = _saved_batch(db, current, scope)
    if saved is None:
        return None
    table = Tenant.__table__
    db.execute(table.update().where(table.c.id == current.legacy_tenant_id).values(id=table.c.id))
    current = require_action_permission(db, current, "compliance:check")
    saved = _saved_batch(db, current, scope)
    if saved.evidence != metadata(current, scope, items):
        raise ActionError(409, "同一合规范围的来源身份或目标清单已变化")
    records = saved.decision.get("records") if isinstance(saved.decision, dict) else None
    if not isinstance(records, list) or len(records) != len(items):
        raise ActionError(409, "合规恢复产物清单无效")
    results = []
    for item, record in zip(items, records, strict=True):
        if not isinstance(record, dict):
            raise ActionError(409, "合规恢复记录结构无效")
        row = latest_report(db, current.legacy_tenant_id, item)
        if (row is None or row.id != record.get("report_id")
                or record.get("basis_sha") != digest(current_basis(db, current, item))
                or record.get("report_sha") != digest(public_report(row))):
            raise ActionError(409, "合规恢复的内容、规则或最新报告已变化")
        if item["target_type"] == "listing":
            action = db.get(AiAction, record.get("action_id"), populate_existing=True)
            if (action is None or action.status != "SUCCESS" or action.tenant_id != current.legacy_tenant_id
                    or action.action_type != "UPDATE_LISTING_COMPLIANCE_RISK"):
                raise ActionError(409, "原风险 Action 未成功，禁止恢复绕过")
            execute_action(db, current, action.id, commit=False)
            listing, _ = targets(db, current.legacy_tenant_id, "listing", item["ref_id"])
            if listing.risk_level != row.risk_level:
                raise ActionError(409, "风险副本与原报告不一致，禁止重放覆盖")
        results.append(public_report(row))
    return results


def _prepare(db, ctx, outputs, items):
    if not isinstance(outputs, list) or len(outputs) != len(items):
        raise ActionError(400, "合规分析目标范围不完整")
    prepared = []
    for item, output in zip(items, outputs, strict=True):
        record = output.get("_compliance_analysis") if isinstance(output, dict) else None
        if not isinstance(record, dict) or any(record.get(key) != value for key, value in item.items()):
            raise ActionError(400, "合规分析目标字段无效")
        basis = current_basis(db, ctx, item)
        if record.get("basis") != basis:
            raise ActionError(409, "合规内容、关联商品或知识规则已变化")
        floor = rule_analysis(basis)
        result = validate_result(record, floor)
        if (record.get("model") not in {"rule", "llm"}
                or (record["model"] == "rule" and result != floor)
                or (result["risk_level"] == "high" and floor["risk_level"] != "high")):
            raise ActionError(409, "合规模型或高风险确定性依据无效")
        prepared.append((result, record["model"], digest(basis)))
    return prepared


def finalize_compliance(db, ctx, outputs, scope, items):
    if not isinstance(scope, str) or not scope or len(scope) > 512:
        raise ActionError(400, "合规缺少有效服务端执行范围")
    validate_items(items)
    try:
        table = Tenant.__table__
        db.execute(table.update().where(table.c.id == ctx.legacy_tenant_id).values(id=table.c.id))
        current = require_action_permission(db, ctx, "compliance:check")
        previous = recover_compliance(db, current, scope, items)
        if previous is not None:
            db.commit()
            return previous
        prepared = _prepare(db, current, outputs, items)
        rows, records = [], []
        for item, (result, model, basis_sha) in zip(items, prepared, strict=True):
            row = ComplianceReport(tenant_id=current.legacy_tenant_id, target_type=item["target_type"],
                product_id=item["ref_id"] if item["target_type"] == "product" else None,
                listing_id=item["ref_id"] if item["target_type"] == "listing" else None, model=model, **result)
            db.add(row)
            db.flush()
            rows.append(row)
            records.append({"report_id": row.id, "report_sha": digest(public_report(row)), "basis_sha": basis_sha})
        batch = AiDecision(tenant_id=current.legacy_tenant_id, agent="compliance", action="check_batch_output",
            subject_type="compliance_batch", subject_id=0, decision={"records": [dict(record) for record in records]},
            evidence=metadata(current, scope, items), model="trusted")
        db.add(batch)
        db.flush()
        for slot, (item, row) in enumerate(zip(items, rows, strict=True)):
            if item["target_type"] == "listing":
                listing, _ = targets(db, current.legacy_tenant_id, "listing", item["ref_id"])
                payload = {"report_id": row.id, "batch_id": batch.id, "slot": slot,
                           "risk_level": row.risk_level, "before": listing.risk_level}
                action = submit_action(db, current, "compliance", {"action_type": "UPDATE_LISTING_COMPLIANCE_RISK",
                    "target_type": "listing", "target_id": listing.id, "payload": payload,
                    "reason": "投影当前合规报告风险；不授权内容编辑或发布"}, f"{scope}:{slot}", commit=False)
                execute_action(db, current, action.id, commit=False)
                records[slot] = {**records[slot], "action_id": action.id}
        batch.decision = {"records": records}
        db.commit()
        return [public_report(row) for row in rows]
    except Exception:
        db.rollback()
        raise


def compliance_batch_result(reports, scope, items):
    high = [(item, report) for item, report in zip(items, reports, strict=True) if report["risk_level"] == "high"]
    return {"reports": reports, "business_status": "blocked" if high else "success",
            "context_patch": {"risk_high": [item["ref_id"] for item, _ in high],
                "blocked_product_ids": [item["ref_id"] for item, _ in high if item["target_type"] == "product"],
                "blocked_listing_ids": [item["ref_id"] for item, _ in high if item["target_type"] == "listing"],
                "_action_compliance_manifest": {"scope": scope, "items": items}}}
