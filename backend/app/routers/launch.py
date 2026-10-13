"""Launch Center API：八端点 + 统一错误 envelope（薄编排，设计 §3.2）。

错误体统一为 ``HTTPException.detail`` 对象 ``{code, message, blockers, current_revision?,
existing_launch_id?}``；写路径服务函数不 commit，由本层统一 commit/rollback。
路由声明顺序：``/context`` 必须早于 ``/{run_id}``，否则 ``context`` 会被当作 run_id。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, is_impersonating_user
from ..db import get_db
from ..models import User, WorkflowEvent, utcnow
from ..pagination import PageNum, PageSize
from ..services.workspace_context import resolve_workspace_context
from ..workflows import launch_dto, launch_list
from ..workflows.launch_access import LaunchError, launch_context, owned_launch
from ..workflows.launch_actions import execute_launch_action
from ..workflows.launch_records import create_launch
from ..workflows.launch_runtime import refresh_launch

router = APIRouter(prefix="/launch", tags=["launch"])

# 列表端点已识别的查询参数；额外参数一律 422 FILTER_INVALID（AC-1.6，不静默忽略）。
_LIST_KEYS = frozenset({"page_num", "page_size", "product_id", "shop_id", "platform", "market",
                        "execution_status", "owner_user_id", "mine", "waiting_platform",
                        "blocked_only", "include_history"})


class LaunchCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    product_id: int = Field(gt=0)
    shop_id: int = Field(gt=0)
    parent_listing_id: int | None = None
    previous_run_id: int | None = None
    environment: Literal["CONTRACT_TEST", "PRODUCTION"] = "CONTRACT_TEST"


class ActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_code: str = ""
    expected_revision: int
    payload: dict = Field(default_factory=dict)


class SyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str
    expected_revision: int


def _ctx(db, user):
    return resolve_workspace_context(db, user, is_impersonating=is_impersonating_user(user))


def _envelope(exc: LaunchError) -> dict:
    detail = {"code": exc.code, "message": str(exc), "blockers": exc.blockers or []}
    if exc.current_revision is not None:
        detail["current_revision"] = exc.current_revision
    if exc.existing_launch_id is not None:
        detail["existing_launch_id"] = exc.existing_launch_id
    return detail


def _fail(db, exc):
    """写路径失败：回滚当前事务后抛统一 envelope（零状态变更）。"""
    db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=_envelope(exc)) from exc


@router.get("/context")
def get_context(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        current, scope = launch_context(db, _ctx(db, user))
        return launch_dto.context_dto(db, current, scope)
    except LaunchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_envelope(exc)) from exc


@router.post("")
def create(body: LaunchCreateIn, idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx = _ctx(db, user)
    try:
        run = create_launch(db, ctx, body.product_id, body.shop_id, idempotency_key or "",
                            environment=body.environment, parent_listing_id=body.parent_listing_id,
                            previous_run_id=body.previous_run_id)
        db.commit()
    except LaunchError as exc:
        _fail(db, exc)
    try:
        detail = launch_dto.load_detail(db, ctx, run.id)
        db.commit()
    except LaunchError as exc:
        _fail(db, exc)
    return detail


@router.get("")
def list_launches(request: Request, page_num: int = PageNum, page_size: int = PageSize,
                  product_id: int | None = Query(None, gt=0), shop_id: int | None = Query(None, gt=0),
                  platform: str | None = None, market: str | None = None,
                  execution_status: str | None = None, owner_user_id: int | None = Query(None, gt=0),
                  mine: bool = False, waiting_platform: bool = False, blocked_only: bool = False,
                  include_history: bool = False,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    extra = set(request.query_params.keys()) - _LIST_KEYS
    try:
        current, scope = launch_context(db, _ctx(db, user))
        return launch_list.list_launches(db, current, scope, page_num=page_num, page_size=page_size,
                                         product_id=product_id, shop_id=shop_id, platform=platform,
                                         market=market, execution_status=execution_status,
                                         owner_user_id=owner_user_id, mine=mine,
                                         waiting_platform=waiting_platform, blocked_only=blocked_only,
                                         include_history=include_history, extra_params=extra)
    except LaunchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_envelope(exc)) from exc


@router.get("/{run_id}")
def detail(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        result = launch_dto.load_detail(db, _ctx(db, user), run_id)
        db.commit()
        return result
    except LaunchError as exc:
        _fail(db, exc)


@router.get("/{run_id}/steps")
def steps(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        result = launch_dto.load_steps(db, _ctx(db, user), run_id)
        db.commit()
        return result
    except LaunchError as exc:
        _fail(db, exc)


@router.post("/{run_id}/actions/{action}")
def act(run_id: int, action: str, body: ActionIn,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx = _ctx(db, user)
    try:
        out = execute_launch_action(db, ctx, run_id, action, body.model_dump(), idempotency_key or "")
        db.commit()
        result = {"revision": out["revision"], "action": out["action"], "status": out["status"],
                  "step": out["step"], "receipt": out["receipt"], "event_id": out["event_id"]}
        result["launch"] = launch_dto.load_detail(db, ctx, run_id)
        db.commit()
    except LaunchError as exc:
        _fail(db, exc)
    return result


@router.post("/{run_id}/sync")
def sync(run_id: int, body: SyncIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx = _ctx(db, user)
    if body.mode != "refresh":
        raise HTTPException(status_code=422, detail={"code": "SYNC_MODE_UNSUPPORTED",
                                                     "message": "仅支持 refresh 同步模式",
                                                     "supported": ["refresh"]})
    try:
        run, _plan = refresh_launch(db, ctx, run_id, body.expected_revision)
        run.last_synced_at = utcnow()
        db.commit()
        launch = launch_dto.load_detail(db, ctx, run_id)
        db.commit()
        return {"refreshed": True, "revision": run.revision, "launch": launch}
    except LaunchError as exc:
        _fail(db, exc)


@router.get("/{run_id}/events")
def events(run_id: int, page_num: int = PageNum, page_size: int = PageSize,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        current, scope = launch_context(db, _ctx(db, user))
        run = owned_launch(db, current, scope, run_id)
        query = db.query(WorkflowEvent).filter(WorkflowEvent.run_id == run.id)
        total = query.count()
        rows = (query.order_by(WorkflowEvent.sequence)
                .offset((page_num - 1) * page_size).limit(page_size).all())
        return {"items": [launch_dto.event_dto(event) for event in rows], "total": total,
                "page_num": page_num, "page_size": page_size}
    except LaunchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_envelope(exc)) from exc
