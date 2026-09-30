"""定价分析产物持久化：不创建 Action，不修改商品售价。"""

import hashlib
import json
import math

from ..models import PricingRecord, Product, Tenant
from ..serialize import to_dict
from .action_identity import require_action_permission
from .ai_actions import ActionError

NUMBERS = {"purchase_cost", "logistics_cost", "platform_fee_rate", "ads_cost",
           "price", "suggested_price", "profit", "margin"}
FIELDS = NUMBERS | {"product_id", "currency", "reason", "model"}


def _validated(item):
    if not isinstance(item, dict):
        raise ActionError(400, "定价分析产物必须为对象")
    record = item.get("_analysis_record")
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ActionError(400, "定价分析产物字段无效")
    if (not isinstance(record["product_id"], int) or isinstance(record["product_id"], bool)
            or record["product_id"] <= 0):
        raise ActionError(400, "定价商品 ID 无效")
    for key in NUMBERS:
        value = record[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ActionError(400, "定价分析数值无效：" + key)
    if (any(record[key] < 0 for key in ("purchase_cost", "logistics_cost", "ads_cost"))
            or not 0 <= record["platform_fee_rate"] < 1
            or record["price"] <= 0 or record["suggested_price"] <= 0):
        raise ActionError(400, "定价分析成本、费率或价格无效")
    if record["currency"] != "USD" or record["model"] not in ("llm", "rule"):
        raise ActionError(400, "定价分析币种或来源无效")
    reason = record["reason"]
    if not isinstance(reason, dict) or "_persistence" in reason:
        raise ActionError(400, "定价分析原因无效")
    try:
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ActionError(400, "定价分析产物必须为有限 JSON") from exc
    if len(encoded.encode("utf-8")) > 100_000:
        raise ActionError(400, "定价分析产物过大")
    return record


def _persist(db, ctx, record, scope_key):
    product_id = record["product_id"]
    product = db.get(Product, product_id, populate_existing=True)
    if product is None or product.tenant_id != ctx.legacy_tenant_id:
        raise ActionError(404, "定价商品不存在")
    raw = json.dumps([ctx.workspace_id, ctx.user_id, "pricing", scope_key, product_id])
    key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    row = db.query(PricingRecord).filter(
        PricingRecord.tenant_id == ctx.legacy_tenant_id,
        PricingRecord.product_id == product_id,
        PricingRecord.reason["_persistence"]["key"].as_string() == key).with_for_update().first()
    if row is None:
        metadata = {"key": key, "workspace_id": ctx.workspace_id,
                    "requested_by": ctx.user_id, "scope_key": scope_key,
                    "trace_id": ctx.trace_id, "agent_type": "pricing"}
        row = PricingRecord(tenant_id=ctx.legacy_tenant_id, **{
            **record, "reason": {**record["reason"], "_persistence": metadata}})
        db.add(row)
        db.flush()
    return to_dict(row)


def finalize_pricing_output(db, ctx, output, scope_key):
    """整批原子提交；同一服务端范围复用原分析，不覆盖已存快照。"""
    if not isinstance(scope_key, str) or not scope_key or len(scope_key) > 512:
        raise ActionError(400, "定价分析缺少有效服务端范围")
    batch = "repriced" in output
    items = output["repriced"] if batch else [output]
    records = [_validated(item) for item in items]
    try:
        # Core 自赋值不改变租户字段；取得跨进程事务写锁，SQLite 不支持 FOR UPDATE。
        # 锁持有至整批提交/回滚；服务端权限复核与去重查询必须位于锁内。
        table = Tenant.__table__
        db.execute(table.update().where(table.c.id == ctx.legacy_tenant_id).values(id=table.c.id))
        current = require_action_permission(db, ctx, "finance:write")
        results = [_persist(db, current, record, scope_key) for record in records]
        db.commit()
    except Exception:
        db.rollback()
        raise
    if not batch:
        return results[0]
    return {"repriced": results, "errors": output.get("errors", []),
            "business_status": "blocked" if output.get("errors") else "success",
            "context_patch": {"pricing_record_ids": [row["id"] for row in results]}}
