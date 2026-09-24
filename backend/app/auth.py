"""认证与权限：PBKDF2 口令散列 + JWT，角色 superadmin/admin/operator/viewer。

superadmin = 平台服务商（SaaS 运营方），可管理租户与代客访问（带审计）；
license 门禁：租户停用/服务到期后业务请求一律 403。
"""
import hashlib
import os
import time

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import Tenant, User, utcnow
from .serialize import to_dict

_LEGACY_SALT = b"erp-static-salt-v1"
_PBKDF2_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    import hmac
    if password_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_hex, expected = password_hash.split("$", 3)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex),
                                         int(iterations)).hex()
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False
    # 兼容旧库；登录成功后由路由自动升级为随机盐格式。
    legacy = hashlib.pbkdf2_hmac("sha256", password.encode(), _LEGACY_SALT, 120_000).hex()
    return hmac.compare_digest(legacy, password_hash)


def datetime_otp(minutes: int) -> int:
    return int(time.time()) + minutes * 60


def create_token(user: User, tenant_override: int | None = None) -> str:
    """签发 JWT。tenant_override 仅限 superadmin 代客访问使用（payload 带 imp 标记）。"""
    from . import config

    payload = {
        "uid": user.id,
        "tid": tenant_override if tenant_override is not None else user.tenant_id,
        "role": "operator" if tenant_override is not None else user.role,
        "imp": 1 if tenant_override is not None else 0,
        "ver": int(getattr(user, "token_version", 0) or 0),
        "exp": datetime_otp(config.settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, config.settings.jwt_secret, algorithm="HS256")


class _ImpersonatedUser:
    """superadmin 代客访问时的用户上下文：以目标租户的 operator 身份执行业务。

    权限语义（与产品设计一致，勿改）：代客进入是**可写**会话——平台服务商进入
    租户工作台的目的就是替客户排查与修复，因此 role 降为 ``operator``（含写权限）。
    安全边界靠三层而非只读：① 每次进入/退出写 ``TenantAccessLog`` 审计；
    ② token 带 ``imp=1`` 且 ``tenant_id`` 指向目标租户；③ Context 标记
    ``is_impersonating=True``，前端据此显示「返回平台控制台」。
    """

    # 代客标记：下游（如 me.py 的 Workspace Context）靠它区分「真 operator」
    # 与「平台账号代客」。此前只能靠 role 字符串推断，两者都是 "operator"，
    # 导致 Context 的 is_impersonating 恒为 False，前端无法显示「返回平台控制台」。
    #
    # 命名与冻结契约对齐：docs/phase1_interfaces.md 第 6 节的 Context 字段是
    # ``is_impersonating``。内部标记若另起名（历史上的 ``is_impersonated``），
    # 就会在同一会话里出现两个只差后缀的标记，排查时极易看错，故统一。
    is_impersonating = True

    def __init__(self, operator: User, tenant_id: int):
        self.id = operator.id
        self.tenant_id = tenant_id
        self.role = "operator"
        self.display_name = f"{operator.display_name}(平台服务)"
        self.username = operator.username
        self._operator = operator

    def to_public_dict(self) -> dict:
        """对外身份快照（``/api/auth/login``、``/api/auth/me`` 的响应契约）。

        为什么必须显式覆写：本对象是**鸭子类型替身**，没有 ``__table__``，
        直接喂给 ``serialize.to_dict`` 会 AttributeError——历史缺陷就是代客态
        ``GET /api/auth/me`` 直接 500（普通登录态测不出来，因为那时拿的是真 ORM 行）。

        为什么在 ``to_dict(operator)`` 之上覆写而不是手写白名单：字段集与普通
        登录响应**天然一致**，``users`` 表加列时不会漂移出两套身份快照。

        安全语义（勿改）：``role`` 与 ``tenant_id`` 必须钉成**目标租户**的值。
        若这里返回平台账号的 ``superadmin``，前端 legacy 兜底会把代客会话当平台
        本尊放行到 ``/platform-admin``，代客隔离失效（见 docs/DECISIONS.md D19）。
        """
        data = to_dict(self._operator, exclude=["password_hash"])
        data["tenant_id"] = self.tenant_id
        data["role"] = self.role
        data["display_name"] = self.display_name
        data["is_impersonating"] = True
        return data


def identity_snapshot(user) -> dict:
    """把「当前身份对象」序列化成对外快照（``password_hash`` 一律剔除）。

    两种形态必须都能吃：
      * ORM ``User`` 行——普通登录、用户管理列表；
      * ``_ImpersonatedUser`` 替身——superadmin 代客访问。

    统一收敛在这里的原因：调用点若各自做鸭子类型判断，就会重演「某个端点漏判、
    代客态 500」这类只在代客链路上暴露的缺陷。新增身份形态时只改本函数。
    """
    to_public_dict = getattr(user, "to_public_dict", None)
    if callable(to_public_dict):
        return to_public_dict()
    return to_dict(user, exclude=["password_hash"])


def is_impersonating_user(user) -> bool:
    """当前身份是否处于「平台代客」态（**唯一判定点**）。

    为什么必须收敛成一个函数：代客标记此前散落在各调用点用
    ``getattr(user, "is_impersonated", False)`` 手写，历史上漏过两次
    （``me.py`` 的两个端点、``require_permission``），而漏传的后果很隐蔽——
    ``resolve_workspace_context`` 会把代客态误判成 Platform 身份。

    为什么是「脆弱」而非「已坏」：代客替身当前的 ``role`` 恰好是 ``operator``，
    即使漏传标记也会走 LEGACY 分支拿到正确的租户 Workspace。但一旦替身角色
    改为保留原角色（或改名），漏传就会解析成 ``PLATFORM_ADMIN`` +
    ``workspace_id=None``，代客业务端点全线错乱。故显式判定，不依赖巧合。
    """
    return bool(getattr(user, "is_impersonating", False))


def _decode(token: str) -> dict:
    from . import config

    try:
        return jwt.decode(token, config.settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录") from e


def get_current_user(
    request: Request,
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    payload = _decode(authorization.split(" ", 1)[1].strip())
    operator = db.get(User, payload.get("uid"))
    if not operator:
        raise HTTPException(status_code=401, detail="用户不存在")
    if operator.status != "active":
        raise HTTPException(status_code=403, detail="账号已停用")
    if int(payload.get("ver", -1)) != int(operator.token_version or 0):
        raise HTTPException(status_code=401, detail="登录凭证已撤销，请重新登录")
    tid = payload.get("tid")
    imp = payload.get("imp")
    if imp and operator.role == "superadmin":
        # 代客访问：以目标租户上下文执行，但同样受该租户服务授权门禁约束
        tenant = db.get(Tenant, tid)
        if tenant and tenant.status != "active":
            raise HTTPException(status_code=403, detail="该租户服务已停用，无法代客访问")
        if tenant and tenant.license_until and tenant.license_until < utcnow():
            raise HTTPException(status_code=403, detail="该租户服务授权已到期，请续期后代客访问")
        return _ImpersonatedUser(operator, tid)
    user = operator
    if user.role == "supplier" and not _is_factory_scope_path(request.url.path):
        raise HTTPException(status_code=403, detail="工厂门户账号仅可维护本厂资料")
    if user.role == "superadmin":
        # 平台身份没有业务 Workspace：直接调用租户业务 API 会以空 tenant 写入，
        # 产生 tenant_id 为空的孤儿数据（历史事故：37 行业务表残留）。
        # 需要操作租户业务时，必须先经 /api/admin/tenants/{id}/enter 进入租户（带审计）。
        if not _is_platform_scope_path(request.url.path):
            raise HTTPException(
                status_code=403,
                detail="平台服务商身份无业务 Workspace，请先「进入租户」后代客操作")
        return user
    # 服务授权门禁：租户被停用/到期后所有请求 403
    tenant = db.get(Tenant, user.tenant_id)
    if tenant and tenant.status != "active":
        raise HTTPException(status_code=403, detail="租户服务已停用，请联系平台服务商")
    if tenant and tenant.license_until and tenant.license_until < utcnow():
        raise HTTPException(status_code=403, detail="服务授权已到期，请联系平台服务商续期")
    return user


# 平台身份（superadmin 本尊）允许直接访问的端点：仅限不涉及任何租户业务数据的平台级能力。
_PLATFORM_SCOPE_PREFIXES = ("/api/admin/", "/api/me/")
_PLATFORM_SCOPE_PATHS = {
    "/api/auth/me",
    "/api/health",
    "/api/shops/platforms",
    "/api/shops/platform_rules",
    "/api/ai/settings",
}


def _is_platform_scope_path(path: str) -> bool:
    if path in _PLATFORM_SCOPE_PATHS:
        return True
    if path.startswith("/api/shops/platform_rules"):
        return True
    return any(path.startswith(prefix) for prefix in _PLATFORM_SCOPE_PREFIXES)


# 工厂门户账号允许直接访问的端点。
#
# G-3（工厂 Context 通道）：在原有「门户资料」之外，额外放行 `/api/me/*`
# 的**只读**端点，让工厂账号能取到自己的 Workspace Context。
#
# 为什么必须放行：前端 `permissions.js` 的身份解析以 Context 为权威源、
# legacy `localStorage` 仅作兜底。工厂账号取不到 Context 时，其全部权限判断
# 都只能落在 legacy 分支上——这正是 Phase 1.8「删除旧入口」卡住的唯一前置。
#
# 为什么**只放行读**：`/api/me/workspaces/{id}/switch` 是写语义端点
# （会审计 + 未来会持久化活动 Workspace）。工厂账号的活动 Workspace 由
# `SupplierPortalMember` 唯一确定，不存在「可切换」的第二个 Workspace，
# 放行它既无业务意义，又会扩大攻击面。因此这里用**精确白名单**而非前缀匹配。
_FACTORY_SCOPE_PATHS = {
    "/api/auth/me",
    "/api/me/workspaces",
    "/api/me/workspace-context",
}


def _is_factory_scope_path(path: str) -> bool:
    """工厂门户账号的可达路径判定（门户资料 + 只读身份查询）。"""
    if path.startswith("/api/factory-network/portal/"):
        return True
    return path in _FACTORY_SCOPE_PATHS


def require_write(user: User = Depends(get_current_user)) -> User:
    """写操作权限：admin/operator 可写，viewer 只读。

    注意：superadmin **不在**此处放行——平台身份在 ``get_current_user`` 阶段就
    已被要求「先进入租户」（代客态 role 降为 operator），因此不会走到这里。
    这个分工是刻意的：平台账号直接写租户数据会产生 tenant_id 空值孤儿数据。
    """
    if user.role in ("admin", "operator"):
        return user
    raise HTTPException(status_code=403, detail="只读账号无写权限")


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role == "admin":
        return user
    raise HTTPException(status_code=403, detail="需要管理员权限")


def require_permission(permission: str, legacy_roles: tuple[str, ...]):
    """构造一个按「权限 key」校验的依赖（权威矩阵见 workspace_context.ROLE_PERMISSIONS）。

    设计意图（复核修正 9）：避免为每个新能力都硬编码一份角色名单——
    角色名单散落各处是权限漂移的根源。此处以权限 key 为准，legacy 角色仅作兜底
    （工厂账号等拿不到 Workspace Context 的场景）。

    用法：
        @router.post("/check", dependencies=[Depends(require_permission(
            "compliance:check", ("admin", "compliance_approver")))])
    """
    from .services.workspace_context import (
        ROLE_PERMISSIONS,
        normalize_legacy_role,
        resolve_workspace_context,
    )

    def _dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        # 1) 解析 Workspace Context：按权限 key 判定（权威路径）
        try:
            ctx = resolve_workspace_context(
                db, user, is_impersonating=is_impersonating_user(user))
        except Exception:
            ctx = None
        if ctx is not None and ctx.permissions:
            if ctx.has(permission):
                return user
            raise HTTPException(status_code=403, detail=f"缺少权限：{permission}")
        # 2) Context 不可用（工厂账号/代客/解析失败）：按 legacy 角色兜底
        if user.role in legacy_roles:
            return user
        # 3) legacy 角色经「角色→权限」映射间接获得
        mapped = ROLE_PERMISSIONS.get(normalize_legacy_role(user.role), frozenset())
        if permission in mapped:
            return user
        raise HTTPException(status_code=403, detail=f"缺少权限：{permission}")

    return _dep


def require_compliance_approver(user: User = Depends(get_current_user)) -> User:
    if user.role in ("admin", "compliance_approver"):
        return user
    raise HTTPException(status_code=403, detail="需要合规审批权限")


def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    """平台服务商专属操作（平台级配置 / 平台规则）。

    仅用于**不涉及任何租户业务数据**的平台级能力；租户业务接口一律不接受
    superadmin 本尊（其 tenant_id 无对应业务 Workspace，写入会产生孤儿数据）。
    """
    if user.role == "superadmin":
        return user
    raise HTTPException(status_code=403, detail="需要平台服务商权限")


def require_admin_or_platform_admin(user: User = Depends(get_current_user)) -> User:
    """平台级配置接口：平台服务商或租户管理员均可。

    用于同时承载「平台级 key（llm/open_1688）」与「租户级 key（fx/rules/platform_fees）」
    的配置端点；key 级别的写入分流由 P1-10 Setting 隔离任务负责。
    """
    if user.role in ("admin", "superadmin"):
        return user
    raise HTTPException(status_code=403, detail="需要管理员权限")


def admin_bootstrap_password() -> str:
    return os.getenv("ERP_ADMIN_PASSWORD", "admin123")
