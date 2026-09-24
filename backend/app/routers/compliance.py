"""合规检测路由：检测报告查询 / 发起检测（第十章侵权检测）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.compliance import ComplianceAgent
from ..auth import get_current_user, require_permission
from ..db import get_db
from ..models import ComplianceReport, User
from ..serialize import page, to_dict

router = APIRouter(prefix="/compliance", tags=["compliance"])


class CheckIn(BaseModel):
    target_type: str  # product / listing
    ref_id: int


@router.get("/reports")
def list_reports(target_type: str = "", ref_id: int | None = None,
                 risk_level: str = "", page_num: int = 1, page_size: int = 20,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """合规报告列表。

    ``risk_level`` 过滤供合规工作台「高风险优先」视图使用（只返回该等级报告）。
    """
    q = db.query(ComplianceReport).filter(ComplianceReport.tenant_id == user.tenant_id)
    if target_type:
        q = q.filter(ComplianceReport.target_type == target_type)
    if risk_level:
        if risk_level not in ("low", "mid", "high"):
            raise HTTPException(status_code=400, detail="risk_level 必须是 low/mid/high")
        q = q.filter(ComplianceReport.risk_level == risk_level)
    if ref_id is not None:
        if target_type == "product":
            q = q.filter(ComplianceReport.product_id == ref_id)
        elif target_type == "listing":
            q = q.filter(ComplianceReport.listing_id == ref_id)
    total = q.count()
    items = (q.order_by(ComplianceReport.created_at.desc())
             .offset((page_num - 1) * page_size).limit(page_size).all())
    return page([to_dict(r) for r in items], total, page_num, page_size)


@router.get("/reports/{report_id}")
def report_detail(report_id: int, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    r = db.get(ComplianceReport, report_id)
    if not r or r.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="报告不存在")
    return to_dict(r)


@router.post("/check")
def check(body: CheckIn,
          user: User = Depends(require_permission("compliance:check",
                                                  ("admin", "operator", "compliance_approver"))),
          db: Session = Depends(get_db)):
    """发起合规检测。

    权限：``compliance:check``（OWNER/OPERATOR/COMPLIANCE 拥有）——合规员的职责
    就是做合规，此前只能审批别人提交的检测结果，无法主动发起，属职责缺口。
    """
    if body.target_type not in ("product", "listing"):
        raise HTTPException(status_code=400, detail="target_type 必须是 product 或 listing")
    with ComplianceAgent(user.tenant_id) as a:
        try:
            return a.check(body.target_type, body.ref_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
