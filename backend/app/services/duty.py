"""关税与进口税引擎：目的国 × HS × 申报货值 → 关税 / 进口 VAT / 清关费（P0-1）。

为什么必须独立成服务：2026 年低值包裹免税全球退坡后，关税与进口税从「可忽略」
变成跨境直邮的第一成本项——

    - 美国 $800 de minimis 全球暂停（E.O. 14324 及后续 EO；CBP 终局规则），
      全部渠道需正式/非正式报关并缴税；
    - 欧盟 (EU) 2026/382 自 2026-07-01 起废除 €150 关税豁免，过渡期按 HS 税则
      子目「每件 €3」定额征收，2028-07-01 转正常税则；IOSS 只管增值税、不含关税；
    - 英国 £135 免税暂保留至 2026-12-31，最迟 2029-03 废除。

在此之前 ``costing.calc_profit`` 里完全没有任何关税项——算出来的利润是 2019 年
的口径，铺货越多亏得越多。

分层与边界：
    - 本模块是纯领域计算，**不建会话、不猜租户、不写库**；金额口径统一为人民币。
    - 币种换算由调用方以 ``fx(amount, currency) -> cny`` 可调用对象注入，
      从而不需要 import ``services/costing.py``（避免 services 之间循环依赖）。
    - 参考税率以代码内 ``DEFAULT_DUTY_RATES`` 兜底，数据库行（租户 / 平台内置）
      优先。**未配置到税率时不静默按 0 计**，而是显式标记 ``rate_configured=False``
      与 ``estimated=True``，让调用方与用户看得见缺口。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import DutyRate
from .regions import EU_MEMBER_STATES, normalize_country, region_code

# 关税判定口径的别名（地区归一化实现在 services/regions.py，此处保留同名导出，
# 供既有调用方与测试继续使用）。
duty_country = region_code

# 参考税率（代码兜底；数据库行优先）。政策依据已逐条写入 note / source_url，
# 目的国税率与 HS 归类随时效变化，租户应通过 /cross-border/duty-rates 维护自有版本。
DEFAULT_DUTY_RATES: tuple[dict, ...] = (
    {
        "destination_country": "EU", "hs_prefix": "", "rate_type": "fixed_per_item",
        "rate": 3.0, "currency": "EUR", "de_minimis": 0.0,
        "note": "(EU) 2026/382 过渡期按 HS 税则子目每件 €3 定额关税（2026-07-01~2028-07-01）",
        "source_url": "https://eur-lex.europa.eu/",
    },
    {
        "destination_country": "US", "hs_prefix": "", "rate_type": "ad_valorem",
        "rate": 0.0, "currency": "USD", "de_minimis": 0.0,
        "note": "de minimis 全球暂停，全部渠道报关缴税；具体从价税率须按 HS 与现行 301/IEEPA 措施维护",
        "source_url": "https://www.cbp.gov/",
    },
    {
        "destination_country": "GB", "hs_prefix": "", "rate_type": "ad_valorem",
        "rate": 0.0, "currency": "GBP", "de_minimis": 135.0,
        "note": "£135 以下免关税，暂保留至 2026-12-31（最迟 2029-03 废除）",
        "source_url": "https://www.gov.uk/",
    },
)

# 进口增值税标准税率（IOSS 场景由销售端代收代缴，但在 DDP 定价中须计入现金流）。
DEFAULT_IMPORT_VAT = {
    "DE": 0.19, "FR": 0.20, "IT": 0.22, "ES": 0.21, "NL": 0.21, "BE": 0.21,
    "AT": 0.20, "PL": 0.23, "SE": 0.25, "DK": 0.25, "FI": 0.24, "IE": 0.23,
    "PT": 0.23, "CZ": 0.21, "GR": 0.24, "HU": 0.27, "RO": 0.19,
    "GB": 0.20, "JP": 0.10, "KR": 0.10, "SG": 0.09, "AU": 0.10, "CA": 0.05,
    "MX": 0.16, "BR": 0.17,
}
# 欧盟未单列成员国时的兜底标准税率。
EU_VAT_FALLBACK = 0.21
# 清关/报关代理费（人民币/票），仅在有目的国时计入；可按租户覆盖。
DEFAULT_CLEARANCE_FEE_CNY = 12.0


def _active(row, at: datetime) -> bool:
    if row.effective_from and row.effective_from > at:
        return False
    return not (row.effective_to and row.effective_to <= at)


def _db_rows(db: Session, tenant_id: int | None, country: str) -> list:
    """读取该国可见的税率行：租户自有行 + 平台内置行（tenant_id IS NULL）。"""
    query = db.query(DutyRate).filter(DutyRate.destination_country == country)
    if tenant_id is None:
        query = query.filter(DutyRate.tenant_id.is_(None))
    else:
        query = query.filter(DutyRate.tenant_id.is_(None) | (DutyRate.tenant_id == tenant_id))
    return query.all()


def _row_to_dict(row) -> dict:
    return {
        "destination_country": row.destination_country, "hs_prefix": row.hs_prefix or "",
        "rate_type": row.rate_type, "rate": float(row.rate or 0),
        "currency": (row.currency or "USD").upper(),
        "de_minimis": None if row.de_minimis is None else float(row.de_minimis),
        "source_url": row.source_url or "", "note": row.note or "",
        "source": "tenant" if row.tenant_id is not None else "platform",
    }


def resolve_duty_rate(db: Session, tenant_id: int | None, country: str, hs_code: str = "",
                      at: datetime | None = None) -> dict:
    """解析适用的关税税率：HS 前缀最长匹配优先，租户行优先于平台内置行。

    返回含 ``found`` 的字典；未命中时 ``found=False``，由调用方决定如何提示。
    """
    at = at or datetime.utcnow()
    code = duty_country(country)
    if not code:
        return {"found": False, "reason": "missing_country"}
    hs = (hs_code or "").strip()
    candidates: list[dict] = [_row_to_dict(row) for row in _db_rows(db, tenant_id, code)
                             if _active(row, at)]
    if not candidates:
        candidates = [dict(item) for item in DEFAULT_DUTY_RATES
                      if item["destination_country"] == code]
        for item in candidates:
            item["source"] = "default"
    if not candidates:
        return {"found": False, "reason": "unconfigured_country", "country": code}

    def specificity(item: dict) -> tuple[int, int]:
        prefix = item["hs_prefix"]
        matches = bool(prefix) and hs.startswith(prefix)
        # 先按「是否匹配 HS」，再按前缀长度；tenant 优先由 source 权重体现。
        return (1 if matches else 0, len(prefix) if matches else 0)

    matched = [item for item in candidates if not item["hs_prefix"]
               or (hs and hs.startswith(item["hs_prefix"]))]
    pool = matched or [item for item in candidates if not item["hs_prefix"]]
    if not pool:
        return {"found": False, "reason": "no_matching_hs", "country": code, "hs_code": hs}
    pool.sort(key=lambda item: (0 if item["source"] == "tenant" else 1,
                                -specificity(item)[1], -specificity(item)[0]))
    best = dict(pool[0])
    best["found"] = True
    best["country"] = code
    return best


def import_vat_rate(db: Session, tenant_id: int | None, country: str) -> tuple[float, str]:
    """返回 (标准进口增值税率, 依据)。租户可通过 rules.import_vat_rates 覆盖。"""
    code = normalize_country(country)
    overrides = _rules(db, tenant_id).get("import_vat_rates") or {}
    if isinstance(overrides, dict) and code in overrides:
        try:
            return float(overrides[code]), "tenant"
        except (TypeError, ValueError):
            pass
    if code in DEFAULT_IMPORT_VAT:
        return DEFAULT_IMPORT_VAT[code], "default"
    if code == "EU" or code in EU_MEMBER_STATES:
        # 未单列成员国时按欧盟标准税率兜底（欧盟聚合口径）。
        return EU_VAT_FALLBACK, "default_eu_fallback"
    return 0.0, "unconfigured"


def _rules(db: Session, tenant_id: int | None) -> dict:
    """读取租户规则配置（延迟导入 settings_service，避免与 costing 形成环）。"""
    from . import settings_service
    return settings_service.get_setting(db, tenant_id, "rules")


def compute_landed_cost(db: Session, tenant_id: int | None, *, country: str, hs_code: str = "",
                        declared_value_cny: float = 0.0, qty: int = 1,
                        with_import_vat: bool = True, at: datetime | None = None) -> dict:
    """到岸成本三件套：关税 + 进口 VAT + 清关费（人民币口径）。

    参数：
        declared_value_cny：申报货值（人民币，含或不含运费由调用方口径决定，须一致）。
        fx：由调用方注入的币种换算函数 ``fx(amount, currency) -> cny``；
            默认为「原值返回」，仅在定额税币种与人民币一致时正确，生产须注入。
    """
    qty = max(int(qty or 1), 1)
    code = duty_country(country)
    base = {
        "country": code, "hs_code": (hs_code or "").strip(), "qty": qty,
        "declared_value_cny": round(float(declared_value_cny or 0), 2),
        "duty_cny": 0.0, "import_vat_cny": 0.0, "clearance_cny": 0.0,
        "total_cny": 0.0, "rate_type": "", "rate": 0.0, "rate_source": "none",
        "rate_configured": False, "de_minimis_exempt": False, "estimated": True,
        "vat_rate": 0.0, "vat_source": "none", "note": "",
    }
    if not code:
        base["note"] = "未指定目的国，无法计税（按 0 计并标记为未计算）"
        base["reason"] = "missing_country"
        return base

    rules = _rules(db, tenant_id)
    fx = _make_fx(db, tenant_id)
    clearance = float(rules.get("clearance_fee_cny", DEFAULT_CLEARANCE_FEE_CNY) or 0)

    rate = resolve_duty_rate(db, tenant_id, code, hs_code, at)
    if not rate.get("found"):
        # 未配置关税税率时不静默按 0 计：仍计入进口 VAT 与清关费，并显式标注原因。
        base["reason"] = rate.get("reason", "unconfigured")
        base["note"] = f"目的国 {code} 未配置关税税率，仅计入进口 VAT 与清关费；请维护税率表"
        base["import_vat_cny"] = _import_vat_amount(db, tenant_id, code, base, with_import_vat, 0.0)
        base["clearance_cny"] = round(clearance, 2)
        base["total_cny"] = round(base["duty_cny"] + base["import_vat_cny"]
                                  + base["clearance_cny"], 2)
        return base

    base["rate_type"] = rate["rate_type"]
    base["rate"] = rate["rate"]
    base["rate_source"] = rate["source"]
    base["rate_configured"] = rate["rate"] > 0
    base["note"] = rate.get("note", "")

    duty_cny = 0.0
    de_minimis = rate.get("de_minimis")
    if de_minimis is not None:
        threshold_cny = fx(float(de_minimis), rate["currency"])
        if base["declared_value_cny"] <= threshold_cny:
            base["de_minimis_exempt"] = True
    if not base["de_minimis_exempt"]:
        if rate["rate_type"] == "fixed_per_item":
            duty_cny = fx(float(rate["rate"]) * qty, rate["currency"])
        else:
            duty_cny = base["declared_value_cny"] * float(rate["rate"])
    base["duty_cny"] = round(duty_cny, 2)

    if with_import_vat:
        base["import_vat_cny"] = _import_vat_amount(db, tenant_id, code, base,
                                                    with_import_vat, duty_cny)

    base["clearance_cny"] = round(clearance, 2)
    base["total_cny"] = round(base["duty_cny"] + base["import_vat_cny"] + base["clearance_cny"], 2)
    # 只要命中了带正税率的税率行即为「已配置」；否则仍属估算。
    base["estimated"] = not base["rate_configured"]
    return base


def _import_vat_amount(db: Session, tenant_id: int | None, code: str, base: dict,
                       with_import_vat: bool, duty_cny: float) -> float:
    """进口 VAT = (申报货值 + 关税) × 目的国标准税率；同时写回税率与依据。"""
    if not with_import_vat:
        return 0.0
    vat_rate, vat_source = import_vat_rate(db, tenant_id, code)
    base["vat_rate"] = vat_rate
    base["vat_source"] = vat_source
    return round((base["declared_value_cny"] + duty_cny) * vat_rate, 2)


def _make_fx(db: Session, tenant_id: int | None):
    """构造币种换算函数（延迟导入 costing.to_cny，避免 services 之间循环 import）。"""
    from .costing import to_cny

    def fx(amount: float, currency: str) -> float:
        code = (currency or "CNY").upper()
        if not amount:
            return 0.0  # 金额为 0 时无需汇率，避免"缺汇率"在没有成本时也抛错
        if code == "CNY" or tenant_id is None:
            return float(amount)
        return to_cny(db, tenant_id, float(amount), code)

    return fx


def list_rates(db: Session, tenant_id: int | None, country: str = "",
               include_defaults: bool = True) -> list[dict]:
    """列出可见的关税税率行（租户自有 + 平台内置 + 未被覆盖的代码兜底参考值）。

    ``include_defaults`` 让配置页能看见"当前实际生效但尚未落库"的参考税率
    （``id=None``、``source="default"``），避免"页面空白但引擎却在计税"的困惑。
    """
    query = db.query(DutyRate)
    if tenant_id is None:
        query = query.filter(DutyRate.tenant_id.is_(None))
    else:
        query = query.filter(DutyRate.tenant_id.is_(None) | (DutyRate.tenant_id == tenant_id))
    if country:
        query = query.filter(DutyRate.destination_country == duty_country(country))
    rows = query.order_by(DutyRate.destination_country, DutyRate.hs_prefix).all()
    items = [_row_to_dict(row) | {"id": row.id, "tenant_id": row.tenant_id} for row in rows]
    if include_defaults:
        keys = {(item["destination_country"], item["hs_prefix"]) for item in items}
        wanted = duty_country(country) if country else ""
        for item in DEFAULT_DUTY_RATES:
            if wanted and item["destination_country"] != wanted:
                continue
            if (item["destination_country"], item["hs_prefix"]) in keys:
                continue
            items.append(dict(item) | {"id": None, "tenant_id": None, "source": "default"})
    return items
