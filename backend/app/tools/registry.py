"""Tool 注册表：名称 -> Tool 类，以及清单完整性自检（Agent OS §10.4）。

为什么必须有注册表
    Guardrail 要按名字找 Tool、Trace 要按名字记调用、测试要按名字比对清单。
    若各调用点直接 ``from ..tools.product import ProductTool``，「有哪些 Tool」
    就散落在各处的 import 语句里，改名或增删必然漏改（T-53）。注册表让这件事
    变成一份可遍历的数据。

为什么自检放在 import 期
    清单写错的代价必须是「进程起不来」，而不是「运行时少一道权限闸门」。
    与 ``agents/contracts.py`` 的 ``assert_frozen_count()`` 同一纪律。
"""

from __future__ import annotations

from .base import BaseTool
from .compliance import ComplianceTool
from .contract import ToolSpec
from .finance import FinanceTool
from .knowledge import KnowledgeTool
from .listing import ListingTool
from .market import MarketTool
from .memory import MemoryTool
from .order import OrderTool
from .product import ProductTool
from .store import StoreTool
from .supply import SupplyTool

# 顺序 = 架构文档 §10.4 / §10.4.1 表格顺序，便于人工比对（比对本身由
# tests/test_tool_layer.py::test_manifest_matches_architecture_doc 自动完成）。
TOOLS: dict[str, type[BaseTool]] = {
    cls.name: cls for cls in (ProductTool, StoreTool, OrderTool, SupplyTool,
                              FinanceTool, MarketTool, ComplianceTool,
                              MemoryTool, KnowledgeTool, ListingTool)
}


def get_tool(name: str) -> type[BaseTool]:
    """按名字取 Tool 类。名字不在册时报错并列出在册名单，而不是抛空泛的 KeyError。"""
    cls = TOOLS.get(name)
    if cls is None:
        raise KeyError("未登记的 Tool：%r；在册：%s" % (name, sorted(TOOLS)))
    return cls


def open_tool(name: str, context, db) -> BaseTool:
    """按名字实例化 Tool —— Agent 侧唯一的取用方式。"""
    return get_tool(name)(context=context, db=db)


def tool_specs() -> dict[str, ToolSpec]:
    """全量冻结清单：``"<tool>.<method>" -> ToolSpec``。"""
    return {spec.key: spec for cls in TOOLS.values() for spec in cls.specs}


def validate() -> None:
    """清单自检：每条 spec 的 tool 必须等于类名，且 key 不得重复。

    类名与 spec.tool 不一致意味着「按名字找 Tool」和「按清单查权限」会指向不同
    的东西——这类错必须当场炸，不能留到 Guardrail 判定时才发现。
    """
    seen: set[str] = set()
    for name, cls in TOOLS.items():
        for spec in cls.specs:
            if spec.tool != name:
                raise AssertionError("%s 的 spec.tool=%r 与注册名 %r 不符"
                                     % (cls.__name__, spec.tool, name))
            if spec.key in seen:
                raise AssertionError("Tool 方法 key 重复：%s" % spec.key)
            seen.add(spec.key)


validate()
