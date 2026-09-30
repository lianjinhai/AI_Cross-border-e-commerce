"""不可变选品分析产物：既有评分和依据链原子保存，无经营 Action。"""

import hashlib
import json
import math

from ..models import AiDecision, MarketTrend, Product, ProductScore, Tenant
from .action_identity import require_action_permission
from .ai_actions import ActionError

NUMBERS = ("demand", "competition", "profit", "risk", "total")
FIELDS = {"product_id", "reasons", "model", *NUMBERS}
SOURCE = "discovery_analysis_v1"


def _scope(scope):
    if not isinstance(scope, str) or not scope or len(scope) > 512:
        raise ActionError(400, "评分缺少有效服务端范围")


def _key(ctx, scope, pid):
    return hashlib.sha256(json.dumps(
        [ctx.workspace_id, ctx.user_id, scope, pid]).encode()).hexdigest()


def _owned(db, ctx, pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ActionError(400, "评分商品 ID 无效")
    product = db.get(Product, pid, populate_existing=True)
    if product is None or product.tenant_id != ctx.legacy_tenant_id or product.status == "deleted":
        raise ActionError(404, "评分商品不存在")


def _lock(db, ctx):
    table = Tenant.__table__
    db.execute(table.update().where(table.c.id == ctx.legacy_tenant_id).values(id=table.c.id))
    return require_action_permission(db, ctx, "product:write")


def _recover(db, ctx, pid, scope):
    _owned(db, ctx, pid)
    decision = db.query(AiDecision).filter(
        AiDecision.tenant_id == ctx.legacy_tenant_id,
        AiDecision.agent == "discovery", AiDecision.action == "score_product",
        AiDecision.subject_type == "product", AiDecision.subject_id == pid,
        AiDecision.evidence["_persistence"]["key"].as_string() == _key(ctx, scope, pid),
        AiDecision.evidence["_persistence"]["source"].as_string() == SOURCE).first()
    if decision is None:
        return None
    metadata = decision.evidence["_persistence"]
    if (metadata.get("workspace_id") != ctx.workspace_id
            or metadata.get("requested_by") != ctx.user_id or metadata.get("scope") != scope):
        raise ActionError(409, "评分恢复来源无效")
    row = db.get(ProductScore, metadata.get("score_id"), populate_existing=True)
    if row is None or row.product_id != pid or row.tenant_id != ctx.legacy_tenant_id:
        raise ActionError(409, "评分恢复产物已失效")
    result = _result(row)
    if metadata.get("snapshot_sha") != _digest({k: result[k] for k in FIELDS}):
        raise ActionError(409, "评分恢复产物内容已变化")
    return result


def _digest(record):
    canonical = {**record, **{key: float(record[key]) for key in NUMBERS}}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def recover_discovery_score(db, ctx, pid, scope):
    """重放前复核身份/归属，避免调用 Agent 重算原分析。"""
    _scope(scope)
    try:
        current = _lock(db, ctx)
        result = _recover(db, current, pid, scope)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def _result(row):
    return {"product_id": row.product_id, **{k: getattr(row, k) for k in NUMBERS},
            "reasons": row.reasons or [], "model": row.model, "score_id": row.id}


def _validate(item):
    record = item.get("_score_analysis") if isinstance(item, dict) else None
    evidence = item.get("_score_evidence", {}) if isinstance(item, dict) else None
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ActionError(400, "评分分析字段无效")
    for key in NUMBERS:
        value = record[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 100):
            raise ActionError(400, "评分数值无效：" + key)
    if (record["model"] not in ("llm", "rule") or not isinstance(record["reasons"], list)
            or not all(isinstance(v, str) for v in record["reasons"])
            or not isinstance(evidence, dict) or not set(evidence) <= {
                "trend_id", "category", "performance_source", "performance_score",
                "has_performance_data", "window_days"}):
        raise ActionError(400, "评分依据无效")
    trend_id = evidence.get("trend_id")
    if trend_id is not None and (isinstance(trend_id, bool) or not isinstance(trend_id, int) or trend_id <= 0):
        raise ActionError(400, "评分趋势引用无效")
    if evidence.get("performance_source") not in ("real_orders", "not_used"):
        raise ActionError(400, "评分经营表现来源无效")
    if evidence.get("performance_source") == "real_orders":
        score = evidence.get("performance_score")
        if (isinstance(score, bool) or not isinstance(score, (float, int))
                or not math.isfinite(score) or not 0 <= score <= 100
                or not isinstance(evidence.get("has_performance_data"), bool)
                or type(evidence.get("window_days")) is not int
                or not 1 <= evidence["window_days"] <= 365):
            raise ActionError(400, "评分经营表现摘要无效")
    try:
        raw = json.dumps([record, evidence], allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ActionError(400, "评分分析必须为有限 JSON") from exc
    if len(raw.encode("utf-8")) > 100_000:
        raise ActionError(400, "评分分析过大")
    return record, evidence


def finalize_discovery_scores(db, ctx, items, scope):
    """锁内去重并保存整批；任何错误回滚评分与决策两张表。"""
    _scope(scope)
    try:
        current = _lock(db, ctx)
        results = []
        for item in items:
            record, evidence = _validate(item)
            pid = record["product_id"]
            trend_id = evidence.get("trend_id")
            if trend_id is not None:
                trend = db.get(MarketTrend, trend_id, populate_existing=True)
                if trend is None or trend.tenant_id != current.legacy_tenant_id:
                    raise ActionError(404, "评分趋势依据不存在")
            saved = _recover(db, current, pid, scope)
            if saved is not None:
                results.append(saved)
                continue
            row = ProductScore(tenant_id=current.legacy_tenant_id, **record)
            db.add(row)
            db.flush()
            metadata = {"source": SOURCE, "key": _key(current, scope, pid),
                        "workspace_id": current.workspace_id, "requested_by": current.user_id,
                        "scope": scope, "score_id": row.id, "trace_id": current.trace_id,
                        "snapshot_sha": _digest(record)}
            db.add(AiDecision(tenant_id=current.legacy_tenant_id, agent="discovery",
                              action="score_product", subject_type="product", subject_id=pid,
                              decision={k: record[k] for k in NUMBERS},
                              evidence={**evidence, "reasons": record["reasons"],
                                        "_persistence": metadata}, model=record["model"]))
            db.flush()
            results.append(_result(row))
        db.commit()
        return results
    except Exception:
        db.rollback()
        raise
