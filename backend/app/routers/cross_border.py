"""跨境到岸成本配置路由：关税税率 / 物流路由 / 平台费率 / 目的国合规（D58）。

权限：读 = ``finance:read``（OWNER/OPERATOR/READ_ONLY），写 = ``finance:write``
（OWNER/OPERATOR）。配置行的写入永远落在**当前租户**名下（``tenant_id =
user.tenant_id``）；``tenant_id IS NULL`` 的行是平台内置口径，租户只能读，
不能改也不能删（避免一个租户改掉所有租户共享的税率）。

计算端点不重复实现口径：``/landed-cost`` 直接转调 ``services/costing.calc_profit``，
保证"配置页看到的成本"与"利润页用的成本"是同一份实现（T-53 口径唯一）。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_permission
from ..db import get_db
from ..models import (
    DestinationComplianceRule,
    DutyRate,
    LogisticsRoute,
    PlatformFeeSchedule,
    Product,
    ProductComplianceEvidence,
    User,
)
from ..serialize import to_dict
from ..services import compliance_registry, costing, duty, label_packages, logistics, platform_fees

router = APIRouter(prefix="/cross-border", tags=["cross-border"])

# 权威矩阵见 services/workspace_context.ROLE_PERMISSIONS；legacy 角色仅作兜底。
_READ = Depends(require_permission("finance:read", ("admin", "operator", "viewer")))
_WRITE = Depends(require_permission("finance:write", ("admin", "operator")))


class DutyRateIn(BaseModel):
    destination_country: str
    hs_prefix: str = ""
    rate_type: str = "ad_valorem"          # ad_valorem / fixed_per_item
    rate: float = 0
    currency: str = "USD"
    de_minimis: float | None = None
    effective_from: str = ""
    effective_to: str | None = None
    source_url: str = ""
    note: str = ""


class LogisticsRouteIn(BaseModel):
    name: str
    channel_type: str = "direct_mail"
    destination_country: str = ""
    billing_method: str = "per_kg"         # per_kg / per_cbm / per_item
    first_weight_kg: float = 0.5
    first_weight_fee: float = 0
    additional_per_kg: float = 0
    per_cbm: float = 0
    per_item: float = 0
    volumetric_divisor: int = 6000
    min_charge: float = 0
    fuel_surcharge_rate: float = 0
    peak_surcharge_rate: float = 0
    active: bool = True
    note: str = ""


class PlatformFeeIn(BaseModel):
    platform: str
    category: str = ""
    site: str = ""
    commission_rate: float = 0
    transaction_rate: float = 0
    service_rate: float = 0
    effective_from: str = ""
    effective_to: str | None = None
    note: str = ""


class ComplianceRuleIn(BaseModel):
    destination_country: str
    category: str = ""
    requirement: str
    mandatory: bool = True
    source_url: str = ""
    note: str = ""


class EvidenceIn(BaseModel):
    destination_country: str
    requirement: str
    evidence_ref: str = ""
    valid_until: str = ""
    note: str = ""


class LandedCostIn(BaseModel):
    product_id: int
    destination_country: str = ""
    price: float | None = None
    channel_type: str = ""
    site: str = ""
    qty: int = 1


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"时间格式无效：{value}") from exc


def _owned(db: Session, model, tenant_id: int, row_id: int):
    row = db.get(model, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="配置不存在或非本租户所有")
    return row


def _apply(row, payload: dict, *, dates: tuple[str, ...] = ()) -> None:
    for key, value in payload.items():
        if key in dates:
            parsed = _parse_dt(value)
            # effective_from 为 NOT NULL 且是"起始生效时间"：未提交时保留原值，
            # 避免 PUT 只改费率就把生效时间清空（进而违反非空约束）。
            if parsed is None and key != "effective_to":
                continue
            setattr(row, key, parsed)
        elif key == "destination_country":
            # 目的国统一归一化：欧盟成员国按 EU 判定关税口径（€3/件）。
            setattr(row, key, duty.duty_country(value) if value else "")
        else:
            setattr(row, key, value)


# ---------------------------------------------------------------- 关税税率
@router.get("/duty-rates")
def list_duty_rates(country: str = "", user: User = _READ, db: Session = Depends(get_db)):
    return {"items": duty.list_rates(db, user.tenant_id, country)}


@router.post("/duty-rates")
def create_duty_rate(body: DutyRateIn, user: User = _WRITE, db: Session = Depends(get_db)):
    row = DutyRate(tenant_id=user.tenant_id)
    _apply(row, body.model_dump(), dates=("effective_from", "effective_to"))
    row.effective_from = row.effective_from or datetime.utcnow()
    db.add(row)
    db.commit()
    return to_dict(row)


@router.put("/duty-rates/{row_id}")
def update_duty_rate(row_id: int, body: DutyRateIn, user: User = _WRITE,
                     db: Session = Depends(get_db)):
    row = _owned(db, DutyRate, user.tenant_id, row_id)
    _apply(row, body.model_dump(), dates=("effective_from", "effective_to"))
    db.commit()
    return {"ok": True, "id": row.id}


@router.delete("/duty-rates/{row_id}")
def delete_duty_rate(row_id: int, user: User = _WRITE, db: Session = Depends(get_db)):
    db.delete(_owned(db, DutyRate, user.tenant_id, row_id))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 物流路由
@router.get("/logistics-routes")
def list_logistics_routes(user: User = _READ, db: Session = Depends(get_db)):
    return {"items": logistics.list_routes(db, user.tenant_id)}


@router.post("/logistics-routes")
def create_logistics_route(body: LogisticsRouteIn, user: User = _WRITE,
                           db: Session = Depends(get_db)):
    row = LogisticsRoute(tenant_id=user.tenant_id, effective_from=datetime.utcnow())
    _apply(row, body.model_dump())
    db.add(row)
    db.commit()
    return to_dict(row)


@router.put("/logistics-routes/{row_id}")
def update_logistics_route(row_id: int, body: LogisticsRouteIn, user: User = _WRITE,
                           db: Session = Depends(get_db)):
    row = _owned(db, LogisticsRoute, user.tenant_id, row_id)
    _apply(row, body.model_dump())
    db.commit()
    return {"ok": True, "id": row.id}


@router.delete("/logistics-routes/{row_id}")
def delete_logistics_route(row_id: int, user: User = _WRITE, db: Session = Depends(get_db)):
    db.delete(_owned(db, LogisticsRoute, user.tenant_id, row_id))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 平台费率
@router.get("/platform-fees")
def list_platform_fees(platform: str = "", user: User = _READ, db: Session = Depends(get_db)):
    return {"items": platform_fees.list_schedules(db, user.tenant_id, platform)}


@router.post("/platform-fees")
def create_platform_fee(body: PlatformFeeIn, user: User = _WRITE, db: Session = Depends(get_db)):
    row = PlatformFeeSchedule(tenant_id=user.tenant_id)
    _apply(row, body.model_dump(), dates=("effective_from", "effective_to"))
    row.effective_from = row.effective_from or datetime.utcnow()
    db.add(row)
    db.commit()
    return to_dict(row)


@router.put("/platform-fees/{row_id}")
def update_platform_fee(row_id: int, body: PlatformFeeIn, user: User = _WRITE,
                        db: Session = Depends(get_db)):
    row = _owned(db, PlatformFeeSchedule, user.tenant_id, row_id)
    _apply(row, body.model_dump(), dates=("effective_from", "effective_to"))
    db.commit()
    return {"ok": True, "id": row.id}


@router.delete("/platform-fees/{row_id}")
def delete_platform_fee(row_id: int, user: User = _WRITE, db: Session = Depends(get_db)):
    db.delete(_owned(db, PlatformFeeSchedule, user.tenant_id, row_id))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 目的国合规要求
@router.get("/compliance-rules")
def list_compliance_rules(country: str = "", user: User = _READ, db: Session = Depends(get_db)):
    return {"items": compliance_registry.list_rules(db, user.tenant_id, country)}


@router.post("/compliance-rules")
def create_compliance_rule(body: ComplianceRuleIn, user: User = _WRITE,
                           db: Session = Depends(get_db)):
    row = DestinationComplianceRule(tenant_id=user.tenant_id, effective_from=datetime.utcnow())
    _apply(row, body.model_dump())
    db.add(row)
    db.commit()
    return to_dict(row)


@router.put("/compliance-rules/{row_id}")
def update_compliance_rule(row_id: int, body: ComplianceRuleIn, user: User = _WRITE,
                           db: Session = Depends(get_db)):
    row = _owned(db, DestinationComplianceRule, user.tenant_id, row_id)
    _apply(row, body.model_dump())
    db.commit()
    return {"ok": True, "id": row.id}


@router.delete("/compliance-rules/{row_id}")
def delete_compliance_rule(row_id: int, user: User = _WRITE, db: Session = Depends(get_db)):
    db.delete(_owned(db, DestinationComplianceRule, user.tenant_id, row_id))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 商品合规证据与到岸成本
def _get_product(db: Session, tenant_id: int, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if not product or product.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    return product


@router.get("/products/{product_id}/compliance")
def check_product_compliance(product_id: int, country: str = "", user: User = _READ,
                             db: Session = Depends(get_db)):
    product = _get_product(db, user.tenant_id, product_id)
    return compliance_registry.check_evidence(db, user.tenant_id, product, country)


@router.post("/products/{product_id}/compliance")
def upsert_compliance_evidence(product_id: int, body: EvidenceIn, user: User = _WRITE,
                               db: Session = Depends(get_db)):
    product = _get_product(db, user.tenant_id, product_id)
    code = compliance_registry.normalize_evidence_country(body.destination_country)
    row = (db.query(ProductComplianceEvidence)
           .filter(ProductComplianceEvidence.tenant_id == user.tenant_id,
                   ProductComplianceEvidence.product_id == product.id,
                   ProductComplianceEvidence.destination_country == code,
                   ProductComplianceEvidence.requirement == body.requirement).first())
    if row is None:
        row = ProductComplianceEvidence(tenant_id=user.tenant_id, product_id=product.id,
                                        destination_country=code, requirement=body.requirement)
        db.add(row)
    row.evidence_ref = body.evidence_ref
    row.valid_until = _parse_dt(body.valid_until)
    row.note = body.note
    db.commit()
    return compliance_registry.check_evidence(db, user.tenant_id, product,
                                              body.destination_country)


# ---------------------------------------------------------------- 标签包（M2-E，只读）
@router.get("/products/{product_id}/labels")
def list_label_packages(product_id: int, shop_id: int = 0, country: str = "", limit: int = 50,
                        user: User = _READ, db: Session = Depends(get_db)):
    """标签包版本历史（只读）；给 ``country`` 时附带该目的国的当前依据判定。

    **写入入口不在这里**：标签包只能由 Launch 动作 `GENERATE_LABEL` / `REGENERATE_LABEL`
    生成（要经过依据门禁与 revision CAS）。这里只回答「印出去过哪几版、依据还能不能对上」，
    避免出现绕过门禁的第二个写入口。
    """
    product = _get_product(db, user.tenant_id, product_id)
    rows = label_packages.history(db, user.tenant_id, product.id, limit)
    if shop_id:
        rows = [row for row in rows if row.shop_id == shop_id]
    items = [{"id": row.id, "shop_id": row.shop_id, "version": row.version,
              "action": row.action, "destination_country": row.destination_country,
              "content_digest": row.content_digest, "basis_fingerprint": row.basis_fingerprint,
              "created_at": row.created_at.isoformat() if row.created_at else None,
              "open_items": list(row.open_items or []), "content": row.content or {}}
             for row in rows]
    payload = {"items": items}
    if country:
        # 依据（要求 + 证据 + 缺项）与店铺无关，因此只给国家就能取；
        # 「这一版标签是否仍当前」才需要 shop_id（标签按店铺隔离）。
        basis = label_packages.resolve_basis(db, user.tenant_id, product, country)
        payload["basis"] = basis
        if shop_id:
            basis["package_current"] = label_packages.basis_current(
                db, user.tenant_id, product, shop_id, country)
    return payload


@router.post("/landed-cost")
def landed_cost(body: LandedCostIn, user: User = _READ, db: Session = Depends(get_db)):
    """到岸成本试算：与利润页同一套口径（services/costing.calc_profit）。"""
    _get_product(db, user.tenant_id, body.product_id)
    try:
        return costing.calc_profit(db, user.tenant_id, body.product_id, body.price,
                                   destination_country=body.destination_country,
                                   channel_type=body.channel_type, site=body.site,
                                   qty=max(int(body.qty or 1), 1))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
