"""趋势数据源（M5）：真实数据接入 + 如实标记来源。

设计红线（方案 §4.4）：`source` 字段如实标记数据出处，**不伪装数据来源**。
  api     —— 1688 开放平台行业关键词接口（有 AppKey 时真实可用）
  csv     —— 从平台后台/第三方工具导出的真实趋势数据（无 API 时的可行路径）
  builtin —— 内置演示词池（降级兜底，前端可识别并提示）
"""
import csv
import io

from sqlalchemy.orm import Session

from ..models import MarketTrend, utcnow

VALID_SOURCES = ("api", "csv", "builtin")

# CSV 表头别名（兼容各平台导出格式）
_ALIASES = {
    "keyword": ("keyword", "关键词", "search_term", "词"),
    "volume": ("volume", "search_volume", "搜索量", "月搜索量"),
    "growth": ("growth", "growth_30d", "增长率", "30天增长"),
    "competition": ("competition", "竞争度", "竞争"),
    "platform": ("platform", "平台"),
    "note": ("note", "备注"),
}


def _pick(row: dict, field: str, default=None):
    for key in _ALIASES[field]:
        if key in row and str(row[key]).strip() != "":
            return row[key]
    return default


def import_csv(db: Session, tenant_id: int, csv_text: str,
               platform_default: str = "csv") -> dict:
    """导入真实趋势数据（CSV）。按 keyword+platform 更新或新增，source 标记为 csv。

    表头需含：关键词/keyword；可选：搜索量/volume、增长率/growth、竞争度/competition、平台/platform。
    """
    text = (csv_text or "").strip().lstrip("\ufeff")
    if not text:
        raise ValueError("CSV 内容为空")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头")

    def norm(row: dict) -> dict:
        return {k.strip().lower(): v for k, v in row.items() if k}

    imported, updated, errors = 0, 0, []
    for idx, raw in enumerate(reader, start=2):
        row = norm(raw)
        keyword = str(_pick(row, "keyword") or "").strip()
        if not keyword:
            errors.append(f"第{idx}行: 缺少关键词")
            continue
        try:
            volume = int(float(str(_pick(row, "volume", 0) or 0).replace(",", "")))
        except ValueError:
            volume = 0
        try:
            growth = float(str(_pick(row, "growth", 0) or 0).replace("%", ""))
        except ValueError:
            growth = 0.0
        try:
            competition = int(float(str(_pick(row, "competition", 50) or 50)))
        except ValueError:
            competition = 50
        platform = str(_pick(row, "platform", platform_default) or platform_default)
        note = str(_pick(row, "note", "") or "")

        existing = (db.query(MarketTrend)
                    .filter(MarketTrend.tenant_id == tenant_id,
                            MarketTrend.keyword == keyword,
                            MarketTrend.platform == platform).first())
        if existing:
            existing.search_volume = volume
            existing.growth_30d = growth
            existing.competition = max(0, min(100, competition))
            existing.note = note or existing.note
            existing.source = "csv"
            existing.updated_at = utcnow()
            updated += 1
        else:
            db.add(MarketTrend(tenant_id=tenant_id, keyword=keyword, platform=platform,
                               search_volume=volume, growth_30d=growth,
                               competition=max(0, min(100, competition)),
                               note=note, source="csv"))
            imported += 1
    db.commit()
    return {"imported": imported, "updated": updated, "errors": errors[:20],
            "source": "csv"}


def fetch_from_1688(db: Session, tenant_id: int, keywords: list[str]) -> dict:
    """从 1688 开放平台拉真实行业趋势（需已配置 AppKey 与授权店铺）。

    说明：1688 行业关键词接口需申请对应权限，未配置/无权限时明确抛错，
    由调用方降级到 CSV 或内置池——不伪装成真实数据。
    """
    from .open_1688 import Api1688Error, call_api

    try:
        raw = call_api(db, "alibaba.keyword.getKeywordList", {"keywords": ",".join(keywords[:20])})
    except Api1688Error as e:
        raise ValueError(f"1688 趋势接口不可用：{e}") from e
    rows = ((raw.get("result") or {}).get("keywordList") or [])
    saved = 0
    for r in rows:
        kw = str(r.get("keyword") or "").strip()
        if not kw:
            continue
        existing = (db.query(MarketTrend)
                    .filter(MarketTrend.tenant_id == tenant_id,
                            MarketTrend.keyword == kw).first())
        volume = int(float(r.get("searchVolume") or 0))
        growth = float(r.get("growthRate") or 0)
        if existing:
            existing.search_volume = volume
            existing.growth_30d = growth
            existing.source = "api"
            existing.updated_at = utcnow()
        else:
            db.add(MarketTrend(tenant_id=tenant_id, keyword=kw, platform="1688",
                               search_volume=volume, growth_30d=growth,
                               competition=50, note="1688 行业关键词", source="api"))
        saved += 1
    db.commit()
    return {"saved": saved, "source": "api"}


def trend_source_summary(db: Session, tenant_id: int) -> dict:
    """趋势数据来源分布（前端据此提示哪些是演示数据）。"""
    rows = (db.query(MarketTrend.source, MarketTrend.id)
            .filter(MarketTrend.tenant_id == tenant_id).all())
    counts = {"api": 0, "csv": 0, "builtin": 0}
    for src, _ in rows:
        counts[src if src in counts else "builtin"] = counts.get(
            src if src in counts else "builtin", 0) + 1
    total = sum(counts.values())
    real = counts["api"] + counts["csv"]
    return {"counts": counts, "total": total, "real_count": real,
            "has_real_data": real > 0,
            "hint": ("当前趋势数据全部来自内置演示词池，请导入真实数据（CSV 或配置 1688 API）"
                     if real == 0 else f"真实趋势数据 {real} 条，演示数据 {counts['builtin']} 条")}
