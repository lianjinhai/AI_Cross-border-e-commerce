"""Agent 层架构红线守护（L-1 / L-3）：防止 Agent 间 P2P 与越层依赖回潮。

**为什么必须用静态扫描而不是跑一遍接口**：
    L-3（Agent 之间禁止互相调用）是**架构约束**，不是运行时行为。P2P 调用在
    功能上是「能跑通」的——`FactoryOpportunityAgent` 直接 `PricingAgent(...)`
    照样算出利润、测试照样绿。但被调 Agent 用自己的会话与租户上下文执行，
    调用方无从控制，权限 / 审计 / Trace 三道闸全部失效。**只有读源码才能发现**。

实测背景：`agents/factory_opportunity.py` 曾直接 `from .pricing import PricingAgent`
再 `calc_profit()`（绕过 Orchestrator），且**未被登记为债务**——规范只登记了
scheduler / supplier 两处，说明「靠评审把关」漏掉了它。本测试把它固化成门禁。

**允许清单（不是放水，是架构要求）**：
    - `from .base import BaseAgent`：所有 Agent 的共同基类，不是 Agent 间调用；
    - `orchestrator.py` 内的 import：Orchestrator **就是**负责编排 Agent 的，
      它的调用是架构规定的唯一合法路径（Agent OS §4）。

**判别力设计**：`test_detector_catches_real_p2p_sample` 用一段**真实出现过的
违规代码**喂给检测器，断言它真能抓到——否则「扫描 0 处」可能只是检测器失灵
（恒真断言），而不是真的干净。
"""
import ast
import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = BACKEND_DIR / "app" / "agents"

# 允许的 Agent 包内同级引用：**不含 Agent 类**的共享模块。
#   base      —— 所有 Agent 的共同基类（不是「另一个 Agent」）；
#   contracts —— Agent 契约声明（Agent OS §6.2），纯词汇表 + frozen dataclass，
#                无 I/O、无业务逻辑、无 Agent 类。
# 豁免清单不能变成后门：`test_allowed_internal_modules_contain_no_agent_classes`
# 会用 AST 断言这两个模块里**没有任何 BaseAgent 子类**，所以它们不可能是
# 「被偷偷调用的另一个 Agent」。
_ALLOWED_INTERNAL = {"base", "contracts"}
# 负责编排的模块：架构规定它才可以引用其它 Agent。
_ORCHESTRATOR = "orchestrator"
# 已登记债务（规范 §11 DEBT-09）：scheduler 反向依赖 agents，Phase 2 事件总线时解决。
# 登记在此是为了「不假装它不存在」——新出现的越层依赖仍会被拦下。
_KNOWN_SERVICE_TO_AGENT_DEBT = {"scheduler.py"}


def _iter_relative_imports(source: str, *, level: int):
    """产出 (行号, 模块名) —— 仅取指定相对层级的 import，覆盖函数体内延迟 import。

    为什么必须用 AST 而不是正则：延迟 import（函数体内 `from .pricing import ...`）
    正是本次违规的形态（`factory_opportunity.py` 就是在方法体内 import 的）。
    只扫顶层 import 会**漏掉整类违规**，这也是它此前没被发现的原因之一。

    为什么要区分 `level`：`agents/` 里的 `from .base import X`（level=1）是包内
    同级引用，而 `from ..models import Y`（level=2）是**跨层**引用（models 在
    app/ 下）。若不加区分，后者的模块名会被误当成 Agent 名，检测器直接变成
    恒真告警（实测第一版就把 `.ai` / `.db` / `.models` 全报了出来）。
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == level and node.module:
            yield node.lineno, node.module.split(".")[0]


def _p2p_violations(source: str, filename: str) -> list[str]:
    """返回该文件里违反 L-3 的引用（模块名 + 行号）。"""
    if filename == f"{_ORCHESTRATOR}.py":
        return []
    found = []
    for lineno, module in _iter_relative_imports(source, level=1):
        if module in _ALLOWED_INTERNAL:
            continue
        found.append(f"{filename}:{lineno} -> .{module}")
    return found


def test_no_agent_to_agent_p2p_imports():
    """L-3：除 Orchestrator 外，任何 Agent 不得 import 其他 Agent。"""
    violations: list[str] = []
    for path in sorted(AGENTS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        violations.extend(_p2p_violations(path.read_text(encoding="utf-8"), path.name))

    assert not violations, (
        "检测到 Agent 间 P2P 引用（违反 Agent OS §3 / 规范 L-3）：\n  "
        + "\n  ".join(violations)
        + "\n修法：把共享能力下沉到 services/（例如 costing.py），"
          "或由 Orchestrator 编排后传参，不要让 Agent 直接互相调用。"
    )


def test_detector_catches_real_p2p_sample():
    """判别力：用真实出现过的违规代码验证检测器有效（防止恒真断言）。

    样本取自本次修复前的 `factory_opportunity.py`——注意它是**方法体内的
    延迟 import**，只扫顶层 import 的写法会漏掉它。
    """
    violating = (
        "from .base import BaseAgent\n"
        "\n"
        "class FactoryOpportunityAgent(BaseAgent):\n"
        "    def scan(self):\n"
        "        from .pricing import PricingAgent\n"
        "        with PricingAgent(1) as pricing:\n"
        "            return pricing.calc_profit(1)\n"
    )
    found = _p2p_violations(violating, "factory_opportunity.py")

    assert found == ["factory_opportunity.py:5 -> .pricing"], found


def test_detector_ignores_cross_layer_imports():
    """判别力反向：跨层引用（`from ..models`，level=2）不得被误报成 P2P。

    第一版检测器没区分 level，把 `.ai` / `.db` / `.models` 全报成 P2P，
    门禁直接变成噪音（真正违规会被淹没）。
    """
    source = "from ..models import Product\nfrom ..services import costing\n"
    assert _p2p_violations(source, "pricing.py") == []


def test_detector_allows_base_and_orchestrator():
    """判别力反向：基类引用与 Orchestrator 编排不得被误报（否则门禁过严而失效）。"""
    assert _p2p_violations("from .base import BaseAgent\n", "pricing.py") == []
    orchestrated = "from .pricing import PricingAgent\nfrom .supplier import SupplierAgent\n"
    assert _p2p_violations(orchestrated, "orchestrator.py") == []


def test_allowed_internal_modules_contain_no_agent_classes():
    """白名单不得变成 P2P 后门：被豁免的模块里不许出现任何 BaseAgent 子类。

    为什么必须反向断言：`_ALLOWED_INTERNAL` 是**按模块名**豁免的。若哪天有人把
    一个真 Agent（例如 `.pricing`）塞进豁免清单，门禁会**静默失效**——
    「扫描 0 处违规」就退化成恒真断言，而这正是 L-3 曾经漏掉
    `factory_opportunity -> pricing` 的同一种失败模式。

    用 AST 而非字符串匹配：`base.py` 里必然出现 `class BaseAgent` 字样，
    字符串匹配无法区分「定义基类」与「继承基类」。
    """
    for name in sorted(_ALLOWED_INTERNAL):
        source = (AGENTS_DIR / f"{name}.py").read_text(encoding="utf-8")
        subclasses = [
            node.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ClassDef)
            and any(
                (isinstance(base, ast.Name) and base.id == "BaseAgent")
                or (isinstance(base, ast.Attribute) and base.attr == "BaseAgent")
                for base in node.bases
            )
        ]
        assert not subclasses, (
            f"agents/{name}.py 被 L-3 门禁豁免，却定义了 Agent 类 {subclasses}——"
            "豁免清单已变成 P2P 后门，请移除该豁免，或改由 Orchestrator 编排"
        )



def test_services_do_not_import_agents():
    """L-1 的镜像方向：services/ 不得反向依赖 agents/（会造成分层倒挂）。

    `agents -> services` 是规范 §4 的正向依赖；反过来会让 services 无法脱离
    Agent 独立测试（`costing.py` 抽出的意义之一就是可被非 Agent 场景复用）。

    例外：`scheduler.py` 是规范 §11 已登记债务 DEBT-09（Phase 2 事件总线时解决）。
    登记而非忽略——新增的越层依赖仍会被拦下。
    """
    violations = []
    for path in sorted((BACKEND_DIR / "app" / "services").rglob("*.py")):
        if path.name in _KNOWN_SERVICE_TO_AGENT_DEBT:
            continue
        source = path.read_text(encoding="utf-8")
        for lineno, module in _iter_relative_imports(source, level=2):
            if module == "agents":
                violations.append(f"{path.name}:{lineno}")
    assert not violations, "services/ 反向依赖 agents/：" + ", ".join(violations)


def test_known_service_to_agent_debt_is_still_present():
    """债务「仍存在」也要断言：债务被修掉后本测试会红，提醒同步更新台账。

    为什么反过来断言：若只写「已知债务被豁免」，那么债务修好后豁免清单会
    悄悄失效成死代码，台账与实际长期脱节（规范 Doc-5 禁止文档与代码脱节）。
    """
    source = (BACKEND_DIR / "app" / "services" / "scheduler.py").read_text(encoding="utf-8")
    imports = list(_iter_relative_imports(source, level=2))
    assert any(module == "agents" for _lineno, module in imports), (
        "DEBT-09 似已修复——请同步更新规范 §11 台账与本测试的豁免清单")


@pytest.mark.parametrize("name", ["costing.py"])
def test_costing_service_has_no_agent_dependency(name):
    """共享成本实现必须与 Agent 解耦：不得 import agents 或自建 Session。"""
    source = (BACKEND_DIR / "app" / "services" / name).read_text(encoding="utf-8")
    modules = {module for _lineno, module in _iter_relative_imports(source, level=2)}

    assert "agents" not in modules, "costing.py 不得依赖 agents/"
    assert not re.search(r"SessionLocal\s*\(", source), (
        "costing.py 不得自建会话（必须由调用方传入 Session + tenant_id，"
        "避免出现无上下文计算）"
    )
