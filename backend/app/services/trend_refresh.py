"""内置趋势受限业务服务：原子刷新、真实来源保护及依据复核。"""

import math
from datetime import datetime

from ..models import AiAction, MarketTrend, Tenant
from .action_identity import require_action_permission
from .ai_actions import ActionError
from .trend_candidates import builtin_candidates

FIELDS = ("id", "keyword", "platform", "search_volume", "growth_30d", "competition", "note", "source")


def snapshot(row):
    """提案依据与执行结果共用的趋势快照。"""
    if row is None:
        return None
    return {**{key: getattr(row, key) for key in FIELDS},
            "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M:%S") if row.updated_at else ""}


def _rows(db, tenant_id, items):
    rows = []
    for item in items:
        candidate = item.get("candidate") or {}
        matched = db.query(MarketTrend).filter(
            MarketTrend.tenant_id == tenant_id, MarketTrend.keyword == candidate.get("keyword"),
            MarketTrend.platform == candidate.get("platform")).all()
        if len(matched) > 1:
            raise ActionError(409, "趋势自然键重复，请先人工整理")
        rows.append(matched[0] if matched else None)
    return rows


def validate_refresh(db, action, payload, *, replay=False):
    """锁内复核原依据；成功重放须仍对应执行后快照。"""
    if action.target_id != action.tenant_id:
        raise ActionError(403, "趋势执行目标与可信租户不一致")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 12:
        raise ActionError(400, "内置趋势批次必须包含12条")
    if not replay and payload.get("day") != datetime.utcnow().strftime("%Y%m%d"):
        raise ActionError(409, "日种子依据已过期，请重新扫描")
    keys = [(item.get("candidate", {}).get("keyword"),
             item.get("candidate", {}).get("platform")) for item in items]
    if len(set(keys)) != len(keys):
        raise ActionError(400, "内置趋势提案包含重复自然键")
    if [item.get("candidate") for item in items] != builtin_candidates(payload.get("day")):
        raise ActionError(400, "趋势候选与固定日种子算法不一致")
    for item in items:
        candidate = item["candidate"]
        if set(candidate) != set(FIELDS[1:]) or candidate.get("source") != "builtin":
            raise ActionError(400, "内置趋势载荷字段或来源无效")
        if (not isinstance(candidate["keyword"], str) or not candidate["keyword"].strip()
                or len(candidate["keyword"]) > 128 or not isinstance(candidate["platform"], str)
                or not 1 <= len(candidate["platform"]) <= 32 or not isinstance(candidate["note"], str)
                or len(candidate["note"]) > 256):
            raise ActionError(400, "内置趋势文本无效")
        if (type(candidate["search_volume"]) is not int or not 800 <= candidate["search_volume"] <= 50000
                or type(candidate["competition"]) is not int or not 20 <= candidate["competition"] <= 90
                or type(candidate["growth_30d"]) not in {int, float}
                or not math.isfinite(candidate["growth_30d"]) or not -15 <= candidate["growth_30d"] <= 180):
            raise ActionError(400, "内置趋势数值超出日种子估算范围")
    rows = _rows(db, action.tenant_id, items)
    expected = (action.outcome or {}).get("after") if replay else [item.get("before") for item in items]
    if expected != [snapshot(row) for row in rows]:
        raise ActionError(409, "趋势依据已变化，请重新扫描；不得恢复覆盖真实数据")
    return rows


def refresh_builtin_trends(db, action, payload):
    """只执行内置估算；任何异常由中央执行器整批回滚。"""
    rows = validate_refresh(db, action, payload)
    before = [snapshot(row) for row in rows]
    for index, (row, item) in enumerate(zip(rows, payload["items"], strict=True)):
        candidate = item["candidate"]
        if row is not None and row.source in {"csv", "api"}:
            continue
        if candidate.get("source") != "builtin":
            raise ActionError(400, "内置估算不能声明真实来源")
        if row is None:
            row = MarketTrend(tenant_id=action.tenant_id)
            db.add(row)
            rows[index] = row
        for field in FIELDS[1:]:
            setattr(row, field, candidate[field])
    db.flush()
    after = [snapshot(row) for row in rows]
    return {"before": before, "after": after,
            "items": [{key: item[key] for key in FIELDS} for item in after]}


def recover_refresh(db, ctx, scope):
    """固定范围重放原Action；终态失败禁止另建提案绕过。"""
    ctx = require_action_permission(db, ctx, "product:write")
    row = db.query(AiAction).filter(
        AiAction.tenant_id == ctx.legacy_tenant_id, AiAction.workspace_id == ctx.workspace_id,
        AiAction.requested_by == ctx.user_id, AiAction.action_type == "REFRESH_BUILTIN_TRENDS",
        AiAction.evidence["scope_key"].as_string() == str(scope)).first()
    return row


def lock_refresh(db, tenant_id):
    """租户写锁串行化刷新批次，避免自然键并发插入。"""
    table = Tenant.__table__
    db.execute(table.update().where(table.c.id == tenant_id).values(id=table.c.id))
