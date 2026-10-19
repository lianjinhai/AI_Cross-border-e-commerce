"""首页经营工作台只读 BFF 路由（薄编排）：`GET /workbench/todo`、`GET /workbench/overview`。

只做参数校验 + 身份解析，聚合逻辑全部落在 `services/workbench.py`（只读、不写库）。
随 `main.py` 的 `prefix="/api"` 注册 → 实际路径 `/api/workbench/*`。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import get_current_user, is_impersonating_user
from ..db import get_db
from ..models import User
from ..services import workbench
from ..services.workspace_context import resolve_workspace_context

router = APIRouter(prefix="/workbench", tags=["workbench"])


def _ctx(db: Session, user: User):
    return resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))


@router.get("/todo")
def workbench_todo(limit: int = Query(50, gt=0, le=200), include_history: bool = False,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """跨域待办聚合（launch / action / alert / review）。"""
    return workbench.build_todo(db, _ctx(db, user), limit=limit, include_history=include_history)


@router.get("/overview")
def workbench_overview(limit: int = Query(50, gt=0, le=200),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """首页 6 问只读聚合（在做什么 / 进展如何 / 今天最重要 / 哪些要人工 / AI 完成 / 异常）。"""
    return workbench.build_overview(db, _ctx(db, user), limit=limit)
