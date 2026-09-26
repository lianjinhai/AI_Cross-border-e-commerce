"""Tool 基类：所有 Tool 的唯一调用入口与调用管线（Agent OS §10）。

管线（顺序不可调换，每一步都对应一条冻结条款）：
    1. 方法在册？        —— 不在冻结清单里的方法一律拒绝，禁止 Tool 私自长接口
    2. 是否写操作？      —— §10.5：写操作必须经 Action System，本层一律拒绝
    3. 权限是否满足？    —— §10.2：由 Tool 自身 ToolSpec 判定，调用方无权传权限
    4. 委派子类只读实现  —— 子类只提供 ``_<method>()``，返回值必须是 Reading
    5. 记录 Audit        —— §10.2：谁、哪个 Agent、读/写了什么、耗时、结果
    6. 归一为 ToolResult —— §10.3 冻结结构

为什么管线写在基类而不是各 Tool 里
    权限、写闸、审计、降级标记是**横切**要求。散在每个 Tool 的每个方法里，
    迟早有方法漏掉其中一项，而漏掉的那一项恰好是安全项。集中在 ``call()``
    意味着子类**没有机会**绕过闸门：子类只写 ``_method()`` 纯读取实现，
    外部只能经 ``call()`` 进入。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from . import audit
from .contract import (
    ERR_BAD_PARAM,
    ERR_INTERNAL,
    ERR_NOT_IMPLEMENTED,
    ERR_PERMISSION,
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reading:
    """只读方法的返回值：数据 + 证据 + 新鲜度（§10.3 的 evidence / freshness）。

    证据只存**引用**（id / 版本 / 时间），不存全量快照——Action 层需要的是
    「凭什么这么建议」的可回溯指针，不是第二份数据副本（T-53）。
    """

    data: object = None
    evidence: dict = field(default_factory=dict)
    freshness: datetime | None = None


def reading(data, **evidence) -> Reading:
    """常用构造：只关心数据与证据时用它，省掉一层 Reading(...)。"""
    return Reading(data=data, evidence=evidence)


def ts(value) -> str:
    """统一时间口径：Tool 返回的时间一律是 ``YYYY-mm-dd HH:MM:SS`` 字符串。

    为什么不让各 Tool 各写一份 strftime：前端与 Agent 都按同一格式解析，
    两处格式不同会产生「有的字段能排序、有的不能」这类隐性缺陷（T-53）。
    空值统一返回 ""，不返回 None——省掉调用方到处写 ``x or ""``。
    """
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def as_int(value, name: str = "参数") -> int:
    """统一整数参数口径：非整数一律 BAD_PARAM。

    为什么收在基类而不是各 Tool 各写一份：这段判定出现在 6 个模块里时，任何一次
    措辞或边界调整都会漏改其中几个（T-53），而「有的模块报 BAD_PARAM、有的报
    INTERNAL」会让调用方无法按码分支。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ToolError(ERR_BAD_PARAM, "%s 必须是整数，实际 %r" % (name, value)) from None


def clamp_limit(value, default: int = 50, maximum: int = 200, name: str = "limit") -> int:
    """统一 limit 口径：非法值报 BAD_PARAM，超限值截断到 maximum。

    为什么非法值报错、超限值只截断：超限是「要得太多」，截断即可满足意图；
    非法值（负数、非整数）是「调用方写错了」，静默改成默认值会让错误长期潜伏
    ——把 -1 悄悄当成 50 之后，调用方永远不知道自己传错了。

    `name` 让同一个函数也能服务 days 之类的窗口参数，错误信息才不会张冠李戴。
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ToolError(ERR_BAD_PARAM, "%s 必须是整数，实际 %r" % (name, value)) from None
    if n < 1:
        raise ToolError(ERR_BAD_PARAM, "%s 必须 >= 1，实际 %r" % (name, value)) from None
    return min(n, maximum)


class BaseTool:
    """领域 Tool 基类。子类声明 ``name`` 与 ``specs``，实现 ``_<method>()``。"""

    name: str = ""
    specs: tuple[ToolSpec, ...] = ()

    def __init__(self, context: ToolContext, db):
        if not self.name:
            raise ValueError("%s 未声明 name" % type(self).__name__)
        self.context = context
        self.db = db

    # ---------------------------------------------------------- 清单
    @classmethod
    def spec_map(cls) -> dict[str, ToolSpec]:
        return {s.method: s for s in cls.specs}

    def spec(self, method: str) -> ToolSpec | None:
        return self.spec_map().get(method)

    @property
    def degraded(self) -> bool:
        """§10.3：兼容期上下文无法校验权限——放行，但必须显式标记降级。"""
        return not self.context.permission_checked

    # ---------------------------------------------------------- 唯一入口
    def call(self, method: str, **params) -> ToolResult:
        """执行一次 Tool 调用。**这是外部唯一允许的入口。**"""
        started = time.perf_counter()
        spec = self.spec(method)
        if spec is None:
            return self._fail(method, params, ERR_NOT_IMPLEMENTED,
                              "方法不在 %s 的冻结清单内：%r" % (self.name, method),
                              started)
        if spec.writes:
            return self._fail(method, params, ERR_NOT_IMPLEMENTED,
                              "写操作必须经 Action System（§10.5），不得直接调用 %s"
                              % spec.key, started)
        if not self._permitted(spec):
            return self._fail(method, params, ERR_PERMISSION,
                              "缺少权限 %s（上下文来源 %s）"
                              % (spec.permission, self.context.source), started)
        try:
            out = getattr(self, "_" + method)(**params)
        except ToolError as exc:
            return self._fail(method, params, exc.code, exc.detail, started)
        except Exception as exc:  # 只读实现内部任何故障都归一为 INTERNAL
            logger.exception("tool %s 执行失败", spec.key)
            return self._fail(method, params, ERR_INTERNAL,
                              "%s: %s" % (type(exc).__name__, exc), started)
        if not isinstance(out, Reading):
            return self._fail(method, params, ERR_INTERNAL,
                              "%s 的只读实现必须返回 Reading，实际 %s"
                              % (spec.key, type(out).__name__), started)
        result = ToolResult(ok=True, data=out.data, evidence=out.evidence,
                            freshness=out.freshness, degraded=self.degraded)
        audit.record(self.context, self.name, method, params, result, _ms(started))
        return result

    # ---------------------------------------------------------- 内部
    def _permitted(self, spec: ToolSpec) -> bool:
        if self.context.permission_checked:
            return self.context.has(spec.permission)
        # 兼容期（legacy_context）：Tool 层拿不到权限集合，**无法**校验。此处刻意
        # 选择「放行 + 标记 degraded」，而不是「一律拒绝」——理由与代价见
        # docs/DECISIONS.md D37。缺口由三重可见性兜底：ToolResult.degraded、
        # 审计行的 mode/agent、以及测试对 legacy_context 调用点数量的递减断言。
        return True

    def _fail(self, method: str, params: dict, code: str, detail: str,
              started: float) -> ToolResult:
        result = ToolResult(ok=False, degraded=self.degraded,
                            error={"code": code, "detail": detail})
        audit.record(self.context, self.name, method, params, result, _ms(started))
        return result


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
