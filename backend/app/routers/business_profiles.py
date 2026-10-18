"""经营画像 API（D63）：GET / PUT /api/business-profile。

读写一律以服务端 Workspace Context 为准，**绝不信任客户端传入的 workspace_id**
（请求体 Schema 不含该字段；即便客户端多传，也会被忽略，文档见下）。

两类字段与两类行的映射：
  - 个人偏好（user_id 非空行）：direction、budget_amount、budget_currency；
  - Workspace 共享（user_id 为空行）：target_market、risk，写权限复用既有
    ``workspace:write`` 能力 key（不新造权限 key）。

合并视图的「完成」判定集中在 ``is_profile_complete``：direction / budget_amount /
budget_currency / target_market / risk 全部非空即视为完成（新手起步闭环口径）。
"""
from __future__ import annotations

import math
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..auth import get_current_user, is_impersonating_user, require_write
from ..db import get_db
from ..models import BusinessProfile, ExchangeRate, Setting, User
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/business-profile", tags=["business-profile"])

# 必填字段：全部非空时画像视为「已完成」。集中在这一处，GET 与 PUT 共用同一判定。
_REQUIRED_FIELDS = ("direction", "budget_amount", "budget_currency",
                    "target_market", "risk")


def is_profile_complete(direction, budget_amount, budget_currency,
                        target_market, risk) -> bool:
    """完成的唯一判定（新手起步闭环口径）。

    所有必填字段都非 None 才算完成。budget_amount == 0.0 是合法值（非 None），
    与「未填写（null）」严格区分。
    """
    return all(v is not None
               for v in (direction, budget_amount, budget_currency, target_market, risk))


def _known_currencies(db: Session, tenant_id: int) -> set[str]:
    """系统已知的币种集合（FX 子系统权威来源 + 系统基线币种）。

    取自 ``exchange_rates`` 表的 base/quote 币种（本租户 + 平台内置 ``tenant_id IS NULL``）
    与 ``Setting('fx')`` 的键，并**恒定并入系统基线 {USD, EUR, CNY}**——订单默认币种
    USD、定价以 CNY 计价，二者是系统本位币，不应因某个环境没配汇率而被 422 拒绝。
    基线之外的未知币种一律 422 拒绝，不静默强制。
    """
    codes: set[str] = {"USD", "EUR", "CNY"}
    rows = (db.query(ExchangeRate.base_currency, ExchangeRate.quote_currency)
            .filter((ExchangeRate.tenant_id == tenant_id)
                    | (ExchangeRate.tenant_id.is_(None)))
            .all())
    for base, quote in rows:
        if base:
            codes.add(base)
        if quote:
            codes.add(quote)
    fx = db.get(Setting, "fx")
    if fx and isinstance(fx.value, dict):
        codes.update(str(k) for k in fx.value.keys())
    return codes


def _max_dt(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _build_view(personal: BusinessProfile | None,
                shared: BusinessProfile | None) -> dict:
    """合并个人行 + 共享行，产出对外视图（GET 与 PUT 共用，保证读回一致）。"""
    direction = personal.direction if personal else None
    budget_amount = personal.budget_amount if personal else None
    budget_currency = personal.budget_currency if personal else None
    target_market = shared.target_market if shared else None
    risk = shared.risk if shared else None
    completed = is_profile_complete(direction, budget_amount, budget_currency,
                                    target_market, risk)
    updated_at = _max_dt(personal.updated_at if personal else None,
                         shared.updated_at if shared else None)
    completed_at = updated_at if completed else None
    return {
        "direction": direction,
        "budget": {"amount": budget_amount, "currency": budget_currency},
        "target_market": target_market,
        "risk": risk,
        "completed": completed,
        "completed_at": (completed_at.strftime("%Y-%m-%d %H:%M:%S")
                         if completed_at else None),
        "updated_at": (updated_at.strftime("%Y-%m-%d %H:%M:%S")
                       if updated_at else None),
        "sources": {
            "direction": "USER" if (personal and personal.direction is not None) else None,
            "target_market": ("WORKSPACE" if (shared and shared.target_market is not None)
                              else None),
            "risk": ("WORKSPACE" if (shared and shared.risk is not None) else None),
        },
    }


class BusinessProfileIn(BaseModel):
    """经营画像写入体。**不含 workspace_id**：Workspace 由服务端 Context 决定。

    ``model_fields_set`` 用于区分「显式置空（null = 清除）」与「缺省（保持不变）」：
    只有显式出现在请求体中的字段才会被写入/清除，未提供的字段保持原值。
    """

    direction: str | None = Field(default=None, description="资源起点 A/B/C（个人偏好）")
    budget_amount: float | None = Field(default=None, description="预算金额（个人偏好）")
    budget_currency: str | None = Field(default=None, description="3 位大写币种代码（个人偏好）")
    target_market: str | None = Field(default=None, max_length=64,
                                      description="目标市场（Workspace 共享）")
    risk: str | None = Field(default=None, description="风险偏好 低/中/高（Workspace 共享）")
    # 服务端按必填字段推导 completed；此字段仅占位兼容，不被信任、不覆盖推导值。
    completed: bool | None = Field(default=None, description="只读推导值，服务端忽略")

    @field_validator("budget_amount")
    @classmethod
    def _chk_amount(cls, v):
        if v is None:
            return v
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("预算金额必须是数字")
        if not math.isfinite(v):
            raise ValueError("预算金额必须是有限数")
        if v < 0:
            raise ValueError("预算金额不能为负数")
        return float(v)

    @field_validator("budget_currency")
    @classmethod
    def _chk_currency_format(cls, v):
        if v is None:
            return v
        if not isinstance(v, str) or not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError("币种必须是 3 位大写字母代码（例如 USD）")
        return v

    @field_validator("risk")
    @classmethod
    def _chk_risk(cls, v):
        if v is None:
            return v
        if v not in ("低", "中", "高"):
            raise ValueError("风险偏好只能是 低/中/高")
        return v


def _resolve_scope(db: Session, user: User):
    """统一从服务端 Workspace Context 取 (tenant_id, workspace_id)。

    这是写/读隔离的唯一事实来源；客户端无法注入 workspace_id。
    """
    ctx = resolve_workspace_context(
        db, user, is_impersonating=is_impersonating_user(user))
    return user.tenant_id, ctx.workspace_id


def _load_rows(db: Session, tenant_id: int, workspace_id: int | None, user_id: int):
    """读取当前用户的个人行与当前空间的共享行（按 tenant+workspace 隔离）。"""
    personal = (db.query(BusinessProfile)
                .filter(BusinessProfile.tenant_id == tenant_id,
                        BusinessProfile.workspace_id == workspace_id,
                        BusinessProfile.user_id == user_id)
                .first())
    shared = (db.query(BusinessProfile)
              .filter(BusinessProfile.tenant_id == tenant_id,
                      BusinessProfile.workspace_id == workspace_id,
                      BusinessProfile.user_id.is_(None))
              .first())
    return personal, shared


@router.get("")
def get_business_profile(user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """读取当前用户 + 当前 Workspace 的合并经营画像。

    缺失字段返回 null（绝不臆造）。个人字段来自该用户的个人行，共享字段来自
    (tenant, workspace) 的共享行；sources 标注每段数据的来源（USER / WORKSPACE / null）。
    """
    tenant_id, workspace_id = _resolve_scope(db, user)
    personal, shared = _load_rows(db, tenant_id, workspace_id, user.id)
    return _build_view(personal, shared)


@router.put("")
def upsert_business_profile(body: BusinessProfileIn,
                            user: User = Depends(require_write),
                            db: Session = Depends(get_db)):
    """幂等 upsert：仅写入请求体显式提供的字段；显式 null 表示清除。

    - 个人字段（direction / budget_*）写入该用户的个人行；
    - 共享字段（target_market / risk）写入 (tenant, workspace) 的共享行，
      且要求 ``workspace:write`` 能力（复用既有权限 key，不新造）；
    - 预算币种必须落在 FX 子系统已知币种内，未知则 422（不静默强制）；
    - 等价两次 PUT 命中同一行，不产生重复行，仅刷新 updated_at。
    """
    tenant_id, workspace_id = _resolve_scope(db, user)
    provided = body.model_fields_set

    # 共享字段写权限：复用既有 workspace:write 能力 key。
    if ("target_market" in provided or "risk" in provided):
        ctx = resolve_workspace_context(
            db, user, is_impersonating=is_impersonating_user(user))
        if not ctx.has("workspace:write"):
            raise HTTPException(
                status_code=403,
                detail="缺少权限：workspace:write（共享字段需 Workspace 写权限）")

    # 币种归属校验：未知币种直接 422，不静默强制。
    if body.budget_currency is not None \
            and body.budget_currency not in _known_currencies(db, tenant_id):
        raise HTTPException(
            status_code=422,
            detail=(f"budget_currency: 币种 {body.budget_currency} 不在已知币种列表"
                    f"（FX 子系统未配置该汇率）"))

    personal, shared = _load_rows(db, tenant_id, workspace_id, user.id)

    # 个人偏好行
    if "direction" in provided or "budget_amount" in provided \
            or "budget_currency" in provided:
        if personal is None:
            personal = BusinessProfile(tenant_id=tenant_id, workspace_id=workspace_id,
                                      user_id=user.id)
            db.add(personal)
        if "direction" in provided:
            personal.direction = body.direction
        if "budget_amount" in provided:
            personal.budget_amount = body.budget_amount
        if "budget_currency" in provided:
            personal.budget_currency = body.budget_currency

    # Workspace 共享行
    if "target_market" in provided or "risk" in provided:
        if shared is None:
            shared = BusinessProfile(tenant_id=tenant_id, workspace_id=workspace_id,
                                    user_id=None)
            db.add(shared)
        if "target_market" in provided:
            shared.target_market = body.target_market
        if "risk" in provided:
            shared.risk = body.risk

    # 推导「完成」并回填两行（审计一致性）。API 响应始终以合并值推导为准。
    direction = personal.direction if personal else None
    budget_amount = personal.budget_amount if personal else None
    budget_currency = personal.budget_currency if personal else None
    target_market = shared.target_market if shared else None
    risk = shared.risk if shared else None
    completed = is_profile_complete(direction, budget_amount, budget_currency,
                                    target_market, risk)
    now = datetime.utcnow()
    completed_at = now if completed else None
    for row in (r for r in (personal, shared) if r is not None):
        row.completed = completed
        row.completed_at = completed_at
        row.updated_at = now

    db.commit()
    if personal is not None:
        db.refresh(personal)
    if shared is not None:
        db.refresh(shared)
    return _build_view(personal, shared)
