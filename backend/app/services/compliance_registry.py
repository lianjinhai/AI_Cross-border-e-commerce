"""目的国合规档案服务：目的国 × 类目 × 认证要求 → 准入检查（P1-4）。

补齐「只审平台规则、不审目的国法规」的缺口。原合规 Agent 是四维扣分（商标侵权 /
违禁宣称 / 图片风险 / 平台规则），而封店、下架、罚没九成死在**目的国产品准入**上：

    - 产品准入认证：CE（欧盟）、UKCA（英国）、FCC（美国电子）、FDA（美国食品/化妆品/
      医疗）、CPC（美国儿童）、PSE（日本）、KC（韩国）；
    - 环保与注册：EPR（德国包装法/法国 EPR）、REACH / RoHS；
    - 特殊运输资质：电池 UN38.3 / MSDS；
    - 标签与能效：能效标签、原产地标识。

本模块提供「要求解析 + 证据核验」，把准入从"提示有要求"变成"判定是否已具备"。
默认只做检查与提示，是否强制阻断由 ``rules.destination_compliance_enforce`` 决定
（默认 False），避免在证据尚未录入时误伤既有上架流程。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import DestinationComplianceRule, ProductComplianceEvidence
from .duty import duty_country, normalize_country

# 参考要求（代码兜底）。``applies_to`` 为关键词列表：命中商品类目或标题即适用；
# 空列表表示该目的国全类目适用。租户/平台可写入 destination_compliance_rules 覆盖。
#
# **关键词表必须随类目扩展同步维护（2026-10 P0 教训）**：本表逐条手写、各自漂移，
# 曾出现 FCC(US) 只认「电子/无线/蓝牙/射频」而不认 charger / adapter / 充电，
# 导致 65W 氮化镓充电器在美国站 required=[] → 系统误报「无缺失、可上架」，
# 而同一件商品卖日本因 PSE 命中「充电」被正确拦下。**误报绿灯比漏报更危险**：
# 它会让运营照系统提示上架无认证商品，代价是下架甚至封店。
# 改动本表时必须同时回答两个问题：新类目是否漏词（漏=误报绿灯）、
# 新词是否过宽（宽=凭空要求合规证据）。两侧都有回归用例锁定。
DEFAULT_REQUIREMENTS: tuple[dict, ...] = (
    {"destination_country": "EU", "requirement": "CE", "applies_to": [
        "电子", "electronic", "玩具", "toy", "机械", "machin", "灯具", "lamp",
        "家电", "appliance", "无线", "wireless", "充电", "charger", "适配器", "adapter",
        "电源", "power supply", "usb-c", "usb c"],
     "note": "欧盟 CE 标志：电子/玩具/机械/无线电设备等强制要求"},
    {"destination_country": "EU", "requirement": "EPR", "applies_to": [
        "包装", "packag", "电子", "electronic", "电池", "battery", "纺织", "textile"],
     "note": "欧盟 EPR（生产者责任延伸）：德国包装法 / 法国 EPR 注册号"},
    {"destination_country": "EU", "requirement": "REACH", "applies_to": [
        "纺织", "textile", "玩具", "toy", "化妆", "cosmetic", "塑料", "plastic"],
     "note": "REACH / RoHS：化学物质与有害物质限制"},
    {"destination_country": "GB", "requirement": "UKCA", "applies_to": [
        "电子", "electronic", "玩具", "toy", "机械", "machin", "家电", "appliance",
        "充电", "charger", "适配器", "adapter", "电源", "power supply"],
     "note": "英国 UKCA 标志（UKCA 已延长接受 CE 至另行通知，须逐类目确认）"},
    # FCC Part 15B 是美国**法定强制**准入：数字设备与电源装置均在范围内。
    # 「充电 / charger / adapter / 电源」四组词是 2026-10 补的漏词，
    # 缺失会让充电器类目在美国站直接返回 required=[]（误报绿灯）。
    {"destination_country": "US", "requirement": "FCC", "applies_to": [
        "电子", "electronic", "无线", "wireless", "蓝牙", "bluetooth", "射频", "rf",
        "充电", "charger", "chargers", "adapter", "适配器", "电源",
        "power supply", "power adapter", "usb-c", "usb c"],
     "note": "美国 FCC：无线电与电磁兼容设备准入（Part 15B 含电源/充电装置）"},
    {"destination_country": "US", "requirement": "FDA", "applies_to": [
        "食品", "food", "化妆", "cosmetic", "医疗", "medical", "保健", "supplement"],
     "note": "美国 FDA：食品/化妆品/医疗器械注册"},
    {"destination_country": "US", "requirement": "CPC", "applies_to": [
        "儿童", "child", "kids", "婴儿", "baby", "玩具", "toy"],
     "note": "美国 CPC：儿童产品证书（CPSC 强制）"},
    {"destination_country": "JP", "requirement": "PSE", "applies_to": [
        "电子", "electronic", "电源", "power", "充电", "charger", "电器", "appliance",
        "适配器", "adapter"],
     "note": "日本 PSE：电气用品安全法"},
    {"destination_country": "KR", "requirement": "KC", "applies_to": [
        "电子", "electronic", "玩具", "toy", "儿童", "child",
        "充电", "charger", "适配器", "adapter", "电源", "power supply"],
     "note": "韩国 KC 认证"},
    # UN38.3 是**锂电池运输**资质，充电器本体不含电池，因此这里刻意不含
    # 「充电 / charger / adapter」——否则纯充电器会被凭空要求电池运输报告。
    # 2026-10 修复 FCC 漏词时特意复核了这条边界（有用例锁定）。
    {"destination_country": "US", "requirement": "UN38.3", "applies_to": [
        "电池", "battery", "移动电源", "power bank", "powerbank", "锂电池", "lithium",
        "充电宝", "蓄电", "储能"],
     "note": "锂电池 UN38.3 运输测试报告 + MSDS（空运强制）"},
)


def _matches(rule_category: str, applies_to, category: str, text: str) -> bool:
    if rule_category:
        return rule_category.lower() in (category or "").lower()
    if not applies_to:
        return True
    haystack = f"{category or ''} {text or ''}".lower()
    return any(keyword.lower() in haystack for keyword in applies_to)


def _rule_dict(row) -> dict:
    return {"id": row.id, "destination_country": row.destination_country,
            "category": row.category or "", "requirement": row.requirement,
            "mandatory": bool(row.mandatory), "note": row.note or "",
            "source_url": row.source_url or "",
            "source": "tenant" if row.tenant_id is not None else "platform"}


def requirements_for(db: Session, tenant_id: int | None, country: str, category: str = "",
                     text: str = "", at: datetime | None = None) -> list[dict]:
    """返回该目的国 + 类目下适用的准入要求（数据库覆盖优先，其次代码兜底）。"""
    at = at or datetime.utcnow()
    code = duty_country(country)
    if not code:
        return []
    query = db.query(DestinationComplianceRule).filter(
        DestinationComplianceRule.destination_country == code)
    if tenant_id is None:
        query = query.filter(DestinationComplianceRule.tenant_id.is_(None))
    else:
        query = query.filter(DestinationComplianceRule.tenant_id.is_(None)
                             | (DestinationComplianceRule.tenant_id == tenant_id))
    rows = [row for row in query.all()
            if (not row.effective_from or row.effective_from <= at)
            and not (row.effective_to and row.effective_to <= at)]
    if rows:
        return [_rule_dict(row) for row in rows
                if _matches(row.category or "", None, category, text)]
    return [dict(item) | {"id": None, "mandatory": True, "source": "default", "source_url": ""}
            for item in DEFAULT_REQUIREMENTS
            if item["destination_country"] == code
            and _matches("", item.get("applies_to"), category, text)]


def check_evidence(db: Session, tenant_id: int | None, product, country: str,
                   at: datetime | None = None) -> dict:
    """核验某商品在目的国的合规证据是否齐备、是否过期。"""
    at = at or datetime.utcnow()
    code = duty_country(country)
    if not code:
        return {"country": "", "required": [], "missing": [], "expired": [],
                "satisfied": [], "passed": True, "note": "未指定目的国，未做准入检查"}
    category = getattr(product, "category", "") or ""
    text = " ".join([str(getattr(product, "title", "") or ""),
                     str((getattr(product, "attrs", None) or {}).get("source_desc") or "")])
    requirements = requirements_for(db, tenant_id, code, category, text, at)
    evidence = {}
    if tenant_id is not None:
        rows = (db.query(ProductComplianceEvidence)
                .filter(ProductComplianceEvidence.tenant_id == tenant_id,
                        ProductComplianceEvidence.product_id == getattr(product, "id", None),
                        ProductComplianceEvidence.destination_country == code)
                .all())
        evidence = {row.requirement: row for row in rows}
    required, missing, expired, satisfied = [], [], [], []
    for item in requirements:
        entry = {"requirement": item["requirement"], "mandatory": item.get("mandatory", True),
                 "note": item.get("note", "")}
        required.append(entry)
        row = evidence.get(item["requirement"])
        if row is None or not (row.evidence_ref or "").strip():
            missing.append(entry)
        elif row.valid_until and row.valid_until <= at:
            expired.append(entry | {"valid_until": row.valid_until.strftime("%Y-%m-%d")})
        else:
            satisfied.append(entry | {"evidence_ref": row.evidence_ref})
    blocking = [item for item in missing + expired if item["mandatory"]]
    return {"country": code, "required": required, "missing": missing, "expired": expired,
            "satisfied": satisfied, "passed": not blocking, "blocking": blocking,
            "note": "" if not blocking else "存在未满足或已过期的目的国准入要求"}


def list_rules(db: Session, tenant_id: int | None, country: str = "") -> list[dict]:
    """列出可见的准入要求行（租户自有 + 平台内置）。"""
    query = db.query(DestinationComplianceRule)
    if tenant_id is None:
        query = query.filter(DestinationComplianceRule.tenant_id.is_(None))
    else:
        query = query.filter(DestinationComplianceRule.tenant_id.is_(None)
                             | (DestinationComplianceRule.tenant_id == tenant_id))
    if country:
        query = query.filter(DestinationComplianceRule.destination_country == duty_country(country))
    return [_rule_dict(row) for row in
            query.order_by(DestinationComplianceRule.destination_country,
                           DestinationComplianceRule.requirement).all()]


def normalize_evidence_country(country: str) -> str:
    """证据归属的规范化国家码（欧盟成员国统一落 EU）。"""
    return duty_country(country) or normalize_country(country)
