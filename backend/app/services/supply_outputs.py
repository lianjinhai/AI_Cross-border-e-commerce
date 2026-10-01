"""供应链域可信产物服务：供应商评分 / 销量预测 / 私域工厂机会匹配的原子保存。

§18.3 第 3 步（Agent OS）：Agent 只产出只读提案（经 Tool 层读取 + 规则计算），
写入由本服务在服务端校验后原子提交。所有写入都在同一事务内，失败整批回滚、
错误显式上抛，不吞批量异常。

人工报价保护策略（见 ``finalize_scan_private_supply_batch``）：选择「整行拒绝覆盖」
而非「保护字段」。理由：``supplier_offers`` 表没有来源标记列（约束禁止改表结构 /
新增迁移），无法可靠区分「人工经 POST /suppliers/offers 或 promote 录入」与
「Agent 上次扫描录入」的行；整行跳过写入既满足「不得覆盖人工/非本 Agent 来源
报价经营字段」的硬约束，又避免引入不可靠的来源推断。
"""
import math
from datetime import datetime

from ..models import (
    ForecastSnapshot,
    OpportunitySupplierMatch,
    Product,
    Supplier,
    SupplierCatalogProduct,
    SupplierOffer,
    SupplierScore,
    Tenant,
)
from .action_identity import require_action_permission
from .ai_actions import ActionError
from .commercial_analytics import forecast_monitoring
from .costing import calc_profit

SOURCE = "supply_outputs_v1"
_SCORE_FIELDS = ("quality", "cost", "delivery", "stability", "total")


def _scope(scope):
    if not isinstance(scope, str) or not scope or len(scope) > 512:
        raise ActionError(400, "供应链动作缺少有效服务端范围")


def _lock(db, ctx):
    """租户行锁 + 权限校验；与 discovery/review/compliance 产物服务保持一致。"""
    table = Tenant.__table__
    db.execute(table.update().where(table.c.id == ctx.legacy_tenant_id).values(id=table.c.id))
    return require_action_permission(db, ctx, "supply:write")


# ---------------------------------------------------------------- 供应商评分

def _owned_supplier(db, current, supplier_id):
    sup = db.get(Supplier, supplier_id, populate_existing=True)
    if sup is None or sup.tenant_id != current.legacy_tenant_id:
        raise ActionError(404, "评分供应商不存在")


def _validate_score(item):
    if not isinstance(item, dict):
        raise ActionError(400, "评分提案无效")
    supplier_id = item.get("supplier_id")
    if type(supplier_id) is not int or isinstance(supplier_id, bool) or supplier_id <= 0:
        raise ActionError(400, "评分供应商 ID 无效")
    for key in _SCORE_FIELDS:
        value = item.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 100):
            raise ActionError(400, "评分数值无效：" + key)
    reasons = item.get("reasons")
    if not isinstance(reasons, list) or not all(isinstance(v, str) for v in reasons):
        raise ActionError(400, "评分依据无效")
    model = item.get("model")
    if model not in ("llm", "rule"):
        raise ActionError(400, "评分模型无效")
    return supplier_id


def finalize_supplier_scores(db, ctx, items, scope):
    """原子保存一批供应商评分；服务端校验 + 租户隔离，失败整批回滚。"""
    _scope(scope)
    if not isinstance(items, list) or len(items) > 200:
        raise ActionError(400, "评分批次范围无效")
    try:
        current = _lock(db, ctx)
        results = []
        for item in items:
            supplier_id = _validate_score(item)
            _owned_supplier(db, current, supplier_id)
            row = SupplierScore(tenant_id=current.legacy_tenant_id, supplier_id=supplier_id,
                                **{key: item[key] for key in _SCORE_FIELDS},
                                reasons=item["reasons"], model=item["model"])
            db.add(row)
            db.flush()
            results.append({"supplier_id": supplier_id, "score_id": row.id,
                            "quality": row.quality, "cost": row.cost, "delivery": row.delivery,
                            "stability": row.stability, "total": row.total,
                            "reasons": row.reasons, "model": row.model})
        db.commit()
        return results
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------- 销量预测

def _validate_forecast(product_id, snap):
    if not isinstance(snap, dict) or snap.get("product_id") != product_id:
        raise ActionError(400, "预测提案无效")
    for key in ("version", "selected_model", "confidence"):
        if not isinstance(snap.get(key), str) or not snap[key]:
            raise ActionError(400, "预测版本/模型/置信度无效")
    for key in ("point_forecast", "lower_bound", "upper_bound"):
        value = snap.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ActionError(400, "预测数值无效：" + key)
    for key in ("wape", "bias"):
        value = snap.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value)):
            raise ActionError(400, "预测回测指标无效：" + key)
    if not isinstance(snap.get("training_cutoff"), datetime):
        raise ActionError(400, "预测训练截止时间无效")


def finalize_forecast(db, ctx, product_id, proposal, scope):
    """保存单条预测快照；commercial_gate 在服务端重算，响应兼容既有字段。"""
    _scope(scope)
    if not isinstance(product_id, int) or isinstance(product_id, bool) or product_id <= 0:
        raise ActionError(400, "预测商品 ID 无效")
    snap = proposal.get("_snapshot") if isinstance(proposal, dict) else None
    _validate_forecast(product_id, snap)
    try:
        current = _lock(db, ctx)
        product = db.get(Product, product_id, populate_existing=True)
        if product is None or product.tenant_id != current.legacy_tenant_id:
            raise ActionError(404, "预测商品不存在")
        # 服务端重算商用门禁（不信任 Agent 传入的 gate / automation_allowed）。
        commercial_gate = forecast_monitoring(db, current.legacy_tenant_id)["commercial_gate"]
        row = ForecastSnapshot(tenant_id=current.legacy_tenant_id, product_id=product_id,
                               version=snap["version"], training_cutoff=snap["training_cutoff"],
                               target_start=snap.get("target_start"), target_end=snap.get("target_end"),
                               dimensions=snap.get("dimensions") or {}, features=snap.get("features") or {},
                               candidates=snap.get("candidates") or [], selected_model=snap["selected_model"],
                               point_forecast=snap["point_forecast"], lower_bound=snap["lower_bound"],
                               upper_bound=snap["upper_bound"], wape=snap.get("wape"),
                               bias=snap.get("bias"), confidence=snap["confidence"])
        db.add(row)
        db.flush()
        automation_allowed = row.confidence == "high" and commercial_gate["passed"]
        result = {key: value for key, value in proposal.items() if key != "_snapshot"}
        result.update(snapshot_id=row.id, version=row.version,
                      training_cutoff=row.training_cutoff.isoformat() + "Z",
                      commercial_gate=commercial_gate, automation_allowed=automation_allowed)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def finalize_forecast_batch(db, ctx, proposals, scope):
    """批量预测保存；单条失败跳过（保持与原 forecast_batch 的宽容语义一致）。

    注意：本函数针对「预测」而非「机会扫描」，逐条独立提交；原子整批回滚的硬约束
    只适用于 ``finalize_scan_private_supply_batch``（见约束 #3）。
    """
    if not isinstance(proposals, list):
        raise ActionError(400, "预测批次无效")
    results = []
    for proposal in proposals:
        try:
            results.append(finalize_forecast(db, ctx, proposal["_snapshot"]["product_id"], proposal, scope))
        except (ActionError, ValueError):
            continue
    return results


# ---------------------------------------------------------------- 私域工厂机会扫描

def finalize_scan_private_supply_batch(db, ctx, params, proposal, scope):
    """原子保存私域工厂机会匹配与报价；人工/既有报价整行拒绝覆盖，同事务回滚。

    顺序与原 Agent 实现一致：先 upsert 报价（flush），再在同一会话内调用
    ``costing.calc_profit`` 取最低采购价——保证报价对成本计算可见；整批在末尾
    单次 commit，任何异常整批回滚、错误显式上抛。
    """
    _scope(scope)
    if not isinstance(proposal, dict):
        raise ActionError(400, "机会扫描提案无效")
    if not proposal.get("catalog_present"):
        return {"candidates": [], "ready": 0, "blocked": [],
                "skipped": proposal.get("skipped"),
                "context_patch": {"product_ids": list(proposal.get("product_ids", [])),
                                  "private_ready_product_ids": [],
                                  "factory_opportunity_matches": []}}
    min_margin = float(params.get("min_margin", 0.15)) if isinstance(params, dict) else 0.15
    try:
        current = _lock(db, ctx)
        tenant_id = current.legacy_tenant_id
        candidates, blocked, ready_ids = [], [], []
        for m in proposal["matches"]:
            pid = m["product_id"]
            # 租户隔离校验：商品 / 供应商 / 目录商品必须本租户可见。
            product = db.get(Product, pid, populate_existing=True)
            if product is None or product.tenant_id != tenant_id:
                raise ActionError(404, "机会扫描商品不存在")
            supplier = db.get(Supplier, m["supplier_id"], populate_existing=True)
            if supplier is None or supplier.tenant_id != tenant_id:
                raise ActionError(404, "机会扫描供应商不存在")
            catalog = db.get(SupplierCatalogProduct, m["catalog_product_id"], populate_existing=True)
            if catalog is None or catalog.tenant_id != tenant_id:
                raise ActionError(404, "机会扫描目录商品不存在")
            match = db.query(OpportunitySupplierMatch).filter(
                OpportunitySupplierMatch.tenant_id == tenant_id,
                OpportunitySupplierMatch.product_id == pid,
                OpportunitySupplierMatch.catalog_product_id == m["catalog_product_id"]).first()
            if match is None:
                match = OpportunitySupplierMatch(tenant_id=tenant_id, product_id=pid,
                    supplier_id=m["supplier_id"], catalog_product_id=m["catalog_product_id"])
                db.add(match)
            match.capability_score = m["capability_score"]
            match.readiness_score = m["readiness_score"]
            match.total_score = m["total_score"]
            match.matched_capabilities = m["matched_capabilities"]
            gaps = list(m["gaps"])
            match.gaps = gaps
            match.decision = "due_diligence"
            db.flush()
            economics = None
            if m["write_offer"] and m["offer"]:
                existing = db.query(SupplierOffer).filter(
                    SupplierOffer.tenant_id == tenant_id,
                    SupplierOffer.supplier_id == m["supplier_id"],
                    SupplierOffer.product_id == pid).first()
                if existing is not None:
                    # 人工报价保护：整行拒绝覆盖（见模块文档说明）。
                    gaps.append("供应商报价已由人工或既有流程录入，本次扫描不覆盖（保留原行）")
                    match.gaps = gaps
                else:
                    offer = SupplierOffer(tenant_id=tenant_id, supplier_id=m["supplier_id"],
                                          product_id=pid)
                    db.add(offer)
                    offer.price = float(m["offer"]["price"])
                    offer.currency = str(m["offer"]["currency"]).upper()
                    offer.moq = int(m["offer"]["moq"])
                    offer.ship_days = int(m["offer"]["ship_days"])
                    offer.in_stock = bool(m["offer"]["in_stock"])
                    # 先落库再算成本：calc_profit 经 best_purchase 取最低在库采购价。
                    db.flush()
                try:
                    economics = calc_profit(db, tenant_id, pid)
                except ValueError as exc:
                    gaps.append(str(exc))
                    match.gaps = gaps
                    economics = None
            if economics is not None:
                match.expected_price = economics["price"]
                match.expected_unit_profit = economics["profit"]
                match.expected_margin = economics["margin"]
                monthly_demand = max(float(m.get("forecast_point") or 0) * 4, 0)
                monthly_units = min(monthly_demand, max(m.get("available_qty") or 0, 0),
                                    max(m.get("monthly_capacity") or 0, 0))
                match.expected_monthly_revenue = round(monthly_units * economics["price"], 2)
                if existing is not None:
                    in_stock = bool(existing.in_stock)
                else:
                    in_stock = bool(m["offer"]["in_stock"])
                if economics["margin"] >= min_margin and economics["profit"] > 0 and in_stock:
                    match.decision = "ready"
                    ready_ids.append(pid)
                else:
                    gaps.append(f"预计利润率 {economics['margin']:.1%} 未达到 {min_margin:.1%} 或当前无库存")
                    match.gaps = gaps
            db.flush()
            item = {"match_id": match.id, "product_id": pid,
                    "supplier_id": m["supplier_id"], "catalog_product_id": m["catalog_product_id"],
                    "score": m["total_score"], "decision": match.decision,
                    "expected_margin": match.expected_margin, "gaps": match.gaps}
            candidates.append(item)
            if match.decision != "ready":
                blocked.append(item)
        db.commit()
        return {"candidates": candidates, "ready": len(ready_ids), "blocked": blocked,
                "context_patch": {"product_ids": list(dict.fromkeys(int(x) for x in proposal.get("product_ids", []))),
                                  "private_ready_product_ids": list(dict.fromkeys(ready_ids)),
                                  "factory_opportunity_matches": candidates}}
    except Exception:
        db.rollback()
        raise
