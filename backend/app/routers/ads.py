"""广告增长路由：ROI 报告 / 活动管理 / AI 选词 / 预算优化（第十二章）。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.pricing import AdsAgent
from ..auth import get_current_user, require_write
from ..db import get_db
from ..models import AdCampaign, User
from ..serialize import to_dict

router = APIRouter(prefix="/ads", tags=["ads"])


class CampaignIn(BaseModel):
    name: str
    platform: str = "facebook"
    product_id: int | None = None
    keywords: list[str] = []
    budget: float = 50


class SuggestIn(BaseModel):
    product_id: int
    platform: str = "facebook"


@router.get("/campaigns")
def campaigns(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    with AdsAgent(user.tenant_id) as a:
        return a.roi_report()


@router.post("/campaigns")
def create_campaign(body: CampaignIn, user: User = Depends(require_write),
                    db: Session = Depends(get_db)):
    c = AdCampaign(tenant_id=user.tenant_id, name=body.name, platform=body.platform,
                   product_id=body.product_id, keywords=body.keywords,
                   budget=body.budget, status="draft")
    db.add(c)
    db.commit()
    return to_dict(c)


@router.post("/campaigns/{campaign_id}/optimize")
def optimize(campaign_id: int, user: User = Depends(require_write), db: Session = Depends(get_db)):
    with AdsAgent(user.tenant_id) as a:
        try:
            return a.optimize_budget(campaign_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/suggest")
def suggest(body: SuggestIn, user: User = Depends(require_write), db: Session = Depends(get_db)):
    with AdsAgent(user.tenant_id) as a:
        try:
            return a.suggest_for_product(body.product_id, body.platform)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
