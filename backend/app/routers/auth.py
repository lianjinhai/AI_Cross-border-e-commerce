"""认证与用户管理路由。"""
import hashlib
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import create_token, get_current_user, hash_password, require_admin, verify_password
from ..db import get_db
from ..models import LoginAttempt, User
from ..serialize import page, to_dict

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "operator"
    display_name: str = ""


class UserUpdate(BaseModel):
    role: str | None = None
    display_name: str | None = None
    password: str | None = None
    status: str | None = None


def _safe(u: User) -> dict:
    return to_dict(u, exclude=["password_hash"])


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    identity = hashlib.sha256(body.username.strip().lower().encode()).hexdigest()
    attempt = db.query(LoginAttempt).filter(LoginAttempt.identifier_hash == identity).first()
    now = datetime.utcnow()
    if attempt and attempt.locked_until and attempt.locked_until > now:
        raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后重试")
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        if not attempt:
            attempt = LoginAttempt(identifier_hash=identity, failures=0, window_started_at=now)
            db.add(attempt)
        if (now - attempt.window_started_at).total_seconds() > 900:
            attempt.failures, attempt.window_started_at = 0, now
        attempt.failures += 1
        if attempt.failures >= 5:
            attempt.locked_until = now + timedelta(minutes=15)
        db.commit()
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已停用")
    if attempt:
        attempt.failures, attempt.locked_until = 0, None
    if not user.password_hash.startswith("pbkdf2_sha256$"):
        user.password_hash = hash_password(body.password)
    db.commit()
    return {"token": create_token(user), "user": _safe(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _safe(user)


@router.get("/users")
def list_users(page_num: int = 1, page_size: int = 20,
               user: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(User).filter(User.tenant_id == user.tenant_id)
    total = q.count()
    items = q.order_by(User.id).offset((page_num - 1) * page_size).limit(page_size).all()
    return page([_safe(u) for u in items], total, page_num, page_size)


@router.post("/users")
def create_user(body: UserIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.role not in ("admin", "compliance_approver", "operator", "viewer"):
        raise HTTPException(status_code=400, detail="角色必须是 admin/compliance_approver/operator/viewer")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    u = User(tenant_id=user.tenant_id, username=body.username,
             password_hash=hash_password(body.password),
             display_name=body.display_name or body.username, role=body.role)
    db.add(u)
    db.commit()
    return _safe(u)


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate,
                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u or u.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.role:
        if body.role not in ("admin", "compliance_approver", "operator", "viewer"):
            raise HTTPException(status_code=400, detail="角色不合法")
        u.role = body.role
    if body.display_name is not None:
        u.display_name = body.display_name
    if body.password:
        u.password_hash = hash_password(body.password)
        u.token_version = int(u.token_version or 0) + 1
    if body.status is not None:
        if body.status not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="账号状态不合法")
        u.status = body.status
        if body.status == "disabled":
            u.token_version = int(u.token_version or 0) + 1
    db.commit()
    return _safe(u)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    u = db.get(User, user_id)
    if not u or u.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.delete(u)
    db.commit()
    return {"ok": True}
