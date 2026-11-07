"""标签包（M2-E）：目的国准入依据解析 → 标签包逐版生成 → 依据时效判定。

为什么需要这个模块
------------------
``LABEL_PREPARATION`` 的完成条件是 ``verified_artifact: LABEL_PACKAGE``，但**全仓没有任何
生产者**：``launch_facts`` 只给 ``ACTIVATION``，``GENERATE_LABEL`` 又挂在
``connected=False`` 上。于是这个步骤只有两种命运——永远「未完成」，或者被人塞一个
假布尔值让它「看起来完成了」。本模块给出第三条路：标签包是**真实落库的工件**，
带上它的依据快照与指纹；依据一变就当场失效，步骤自动重新阻断。

三条不可让步的口径
------------------
1. **认证声明只能来自已核验证据**（``content["marks"]``）：每一项都必须对应
   ``product_compliance_evidence`` 里一条 ``evidence_ref`` 非空且未过期的记录。
   缺证据就不生成——绝不用「大概是 CE」这类推测把标签填满。
2. **「没查到要求」≠「没有要求」**：``compliance_registry.check_evidence`` 对未收录
   要求的国家返回 ``required=[]`` 且 ``passed=True``。若照抄这个 True，任何没做过
   目的国调研的市场都会拿到一张「无需认证」的绿灯标签。这里把 ``required == []``
   显式判为**依据缺失**（``covered=False``），阻断并说明「未收录」。
3. **依据变了，旧包立刻失效**：``basis_fingerprint`` 覆盖「要求集 + 每条要求的证据引用 +
   有效期」。有效期属于指纹的一部分还不够——到期当天指纹不会自己变，所以每次判定都
   用 ``at=now`` 重新解析，让过期要求从 ``satisfied`` 挪进 ``expired``，指纹自然失配。

边界（写在这里，避免以后被读大）
--------------------------------
* 本模块**不打印、不上传、不向平台发送**任何东西：只生成可核对的标签字段。
* ``open_items`` 记录本系统没有数据源的字段（进口商/责任人/批号等）。它们不阻断生成
  （那属于店铺授权材料，不是合规证据），但必须同时出现在回执与界面上，不能当成已齐备。
* 一切写入都是**追加**：没有 update/delete 代码路径，重生成 = 新 ``version``。
"""

import hashlib
import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import LabelPackage
from . import compliance_registry
from .regions import normalize_country as iso_country

#: 目的国一条要求都没收录时的原因。必须说清「未知 ≠ 无需认证」。
UNCOVERED_REASON = ("目的国准入要求未收录：系统里 {country} 一条适用要求都没有。"
                    "这是「未知」而不是「无需认证」，不能据此生成标签——"
                    "请先录入该国/该类目的准入要求，或由合规员书面确认后再补录")
#: 本系统永远给不出的印刷字段（无数据源）。不阻断生成，但必须显示。
PRINT_ONLY_GAP = ("印刷信息（进口商 / 责任人或授权代表 / 批号 / 生产日期）不在本系统数据范围，"
                  "印刷前需人工补全")
ORIGIN_GAP = "原产国未登记（product.attrs.origin_country 为空），原产地标识需人工确认"
ACTIONS = frozenset({"GENERATE", "REGENERATE"})


class LabelBasisError(ValueError):
    """依据不足，禁止生成。携带逐条原因与缺失项，供 handler 翻成 409。"""

    def __init__(self, code: str, message: str, *, reasons=None, basis=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.reasons = list(reasons or [message])
        self.basis = basis or {}


def normalize_country(country: str | None) -> str:
    """标签归属国家码：与合规证据同一口径（欧盟成员国统一落 EU）。"""
    return compliance_registry.normalize_evidence_country(country or "")


def _fingerprint(basis: dict) -> str:
    """依据指纹：要求集 + 每条要求的证据引用与有效期。任一变化即失配。"""
    payload = {
        "country": basis.get("country") or "",
        "requirements": [[item.get("requirement"), bool(item.get("mandatory", True))]
                         for item in basis.get("requirements") or []],
        "satisfied": [[item.get("requirement"), item.get("evidence_ref") or "",
                       item.get("valid_until") or ""]
                      for item in basis.get("satisfied") or []],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def resolve_basis(db: Session, tenant_id: int, product, country: str,
                  at: datetime | None = None) -> dict:
    """解析某商品在某目的国的标签依据（要求 + 证据 + 缺项 + 是否可生成）。

    返回 ``{country, covered, requirements, satisfied, missing, expired, blocking,
    reasons, complete, fingerprint, checked_at}``。**不写库、不抛 HTTP 错误**。
    """
    at = at or datetime.utcnow()
    code = normalize_country(country)
    if not code:
        return {"country": "", "covered": False, "requirements": [], "satisfied": [],
                "missing": [], "expired": [], "blocking": [], "complete": False,
                "reasons": ["目的国为空：没有目的国就无法确定标签要声明什么"],
                "fingerprint": "", "checked_at": at.isoformat()}
    # 唯一要求来源：已有 HTTP 入口的合规档案服务，不在这里另写一份要求表。
    report = compliance_registry.check_evidence(db, tenant_id, product, code, at)
    requirements = list(report.get("required") or [])
    basis = {"country": code, "requirements": requirements,
             "satisfied": list(report.get("satisfied") or []),
             "missing": list(report.get("missing") or []),
             "expired": list(report.get("expired") or []),
             "blocking": list(report.get("blocking") or []),
             "covered": bool(requirements), "checked_at": at.isoformat()}
    reasons = []
    if not requirements:
        reasons.append(UNCOVERED_REASON.format(country=code))
    for item in basis["missing"]:
        if item.get("mandatory", True):
            reasons.append("缺 %s 证据：%s" % (item.get("requirement"),
                                             item.get("note") or "尚无证据记录"))
    for item in basis["expired"]:
        if item.get("mandatory", True):
            reasons.append("%s 证据已过期（有效期至 %s）" % (item.get("requirement"),
                                                          item.get("valid_until") or "未知"))
    basis["reasons"] = reasons
    basis["complete"] = bool(requirements) and not reasons
    basis["fingerprint"] = _fingerprint(basis)
    return basis


def _content(product, basis: dict, at: datetime) -> tuple[dict, list[str]]:
    """从真实数据拼标签字段；拿不到来源的一律进 ``open_items``，不编造。"""
    origin = str(((getattr(product, "attrs", None) or {}).get("origin_country")) or "").strip()
    open_items = [PRINT_ONLY_GAP]
    if not origin:
        open_items.insert(0, ORIGIN_GAP)
    marks = [{"requirement": item.get("requirement"),
              "evidence_ref": item.get("evidence_ref") or "",
              "valid_until": item.get("valid_until") or ""}
             for item in basis["satisfied"]]
    content = {
        "destination_country": basis["country"],
        "sku": getattr(product, "sku", "") or "",
        "product_name": getattr(product, "title", "") or "",
        "category": getattr(product, "category", "") or "",
        "origin_country": iso_country(origin) if origin else "",
        "marks": marks,
        "requirement_notes": [{"requirement": item.get("requirement"),
                               "note": item.get("note") or ""}
                              for item in basis["requirements"]],
        "open_items": open_items,
        "basis_fingerprint": basis["fingerprint"],
        "generated_at": at.isoformat(),
    }
    return content, open_items


def _digest(content: dict) -> str:
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def next_version(db: Session, tenant_id: int, product_id: int, shop_id: int, country: str) -> int:
    """下一版号 = 当前最大值 + 1；唯一约束兜底并发（冲突由调用方回 409 重试）。"""
    current = (db.query(func.max(LabelPackage.version))
               .filter(LabelPackage.tenant_id == tenant_id,
                       LabelPackage.product_id == product_id,
                       LabelPackage.shop_id == shop_id,
                       LabelPackage.destination_country == country)
               .scalar())
    return int(current or 0) + 1


def latest(db: Session, tenant_id: int, product_id: int, shop_id: int,
           country: str) -> LabelPackage | None:
    """取该「商品 × 店铺 × 目的国」的最新一版标签包。"""
    return (db.query(LabelPackage)
            .filter(LabelPackage.tenant_id == tenant_id,
                    LabelPackage.product_id == product_id,
                    LabelPackage.shop_id == shop_id,
                    LabelPackage.destination_country == normalize_country(country))
            .order_by(LabelPackage.version.desc(), LabelPackage.id.desc()).first())


def history(db: Session, tenant_id: int, product_id: int, limit: int = 50) -> list[LabelPackage]:
    """标签包版本历史（新→旧，只读）；``limit`` 有上界，防止一次拉全表。"""
    limit = max(1, min(int(limit or 50), 200))
    return (db.query(LabelPackage)
            .filter(LabelPackage.tenant_id == tenant_id, LabelPackage.product_id == product_id)
            .order_by(LabelPackage.id.desc()).limit(limit).all())


def generate(db: Session, *, tenant_id: int, product, shop_id: int, country: str,
             run_id: int | None = None, step_code: str = "", action: str = "GENERATE",
             created_by: int | None = None, require_existing: bool = False) -> LabelPackage:
    """生成一版标签包（追加）；依据不足抛 :class:`LabelBasisError`，**零写入**。

    :param require_existing: ``REGENERATE`` 用；没有旧版时拒绝，避免「重新生成」凭空
             一版全新的标签却被当成「改过一版」。
    """
    if action not in ACTIONS:
        raise LabelBasisError("LABEL_ACTION_INVALID", "未知的标签动作：" + str(action)[:16])
    code = normalize_country(country)
    basis = resolve_basis(db, tenant_id, product, code)
    if require_existing and latest(db, tenant_id, product.id, shop_id, code) is None:
        raise LabelBasisError("LABEL_PACKAGE_ABSENT", "还没有标签包：请先生成，再谈重新生成",
                              basis=basis)
    if not basis["complete"]:
        raise LabelBasisError("LABEL_BASIS_MISSING", "标签依据不足，不能生成标签包",
                              reasons=basis["reasons"], basis=basis)
    at = datetime.utcnow()
    content, open_items = _content(product, basis, at)
    row = LabelPackage(
        tenant_id=tenant_id, product_id=product.id, shop_id=shop_id, run_id=run_id,
        step_code=step_code or "", destination_country=code,
        version=next_version(db, tenant_id, product.id, shop_id, code),
        action=action, content=content, content_digest=_digest(content),
        basis=basis, basis_fingerprint=basis["fingerprint"],
        open_items=open_items, created_by=created_by, created_at=at)
    db.add(row)
    db.flush()
    return row


def basis_current(db: Session, tenant_id: int, product, shop_id: int,
                  country: str) -> bool | None:
    """最新标签包的依据是否仍是当前依据；无标签包时返回 None（UNKNOWN）。

    返回 None 而不是 False：无包是「还没有」，不是「已失效」，两者对用户的下一步不同。
    """
    code = normalize_country(country)
    row = latest(db, tenant_id, product.id, shop_id, code)
    if row is None or not row.basis_fingerprint:
        return None
    basis = resolve_basis(db, tenant_id, product, code)
    return bool(basis["fingerprint"]) and basis["fingerprint"] == row.basis_fingerprint


def label_facts(db: Session, tenant_id: int, product, shop_id: int, country: str) -> dict | None:
    """供 Launch 条件求值与阻断文案的标签事实（``label.*``）；无目的国返回 None。"""
    code = normalize_country(country)
    if not code:
        return None
    basis = resolve_basis(db, tenant_id, product, code)
    row = latest(db, tenant_id, product.id, shop_id, code)
    facts = {"country": code, "covered": basis["covered"], "complete": basis["complete"],
             "reasons": list(basis["reasons"]),
             "missing": [item.get("requirement") for item in basis["missing"]],
             "expired": [item.get("requirement") for item in basis["expired"]]}
    if row is not None:
        facts.update({"package_id": row.id, "version": row.version,
                      "content_digest": row.content_digest,
                      "basis_fingerprint": row.basis_fingerprint,
                      "open_items": list(row.open_items or [])})
        # 依据是否仍当前：过期/证据被改/要求变了都会让指纹对不上。
        facts["package_current"] = bool(basis["fingerprint"]) and \
            basis["fingerprint"] == row.basis_fingerprint
    else:
        facts["package_current"] = False
    return facts


def summary(row: LabelPackage | None, basis: dict) -> dict:
    """列表/详情共用的只读摘要（不泄漏 content 之外的内部字段）。"""
    return {"country": basis.get("country") or "", "covered": bool(basis.get("covered")),
            "complete": bool(basis.get("complete")), "reasons": list(basis.get("reasons") or []),
            "missing": basis.get("missing") or [], "expired": basis.get("expired") or [],
            "package": None if row is None else {
                "id": row.id, "version": row.version, "action": row.action,
                "content_digest": row.content_digest,
                "basis_fingerprint": row.basis_fingerprint,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "open_items": list(row.open_items or []),
                "content": row.content or {}}
            }
