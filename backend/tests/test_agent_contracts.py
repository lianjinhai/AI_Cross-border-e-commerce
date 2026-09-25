"""Agent 契约声明的回归测试（Agent OS §6.2 / §18.3 第 1 步）。

**为什么必须有**：契约声明的价值全在「能被机器读取并校验」。
若只是把文档里的表格抄进代码、没有任何检查，那么：
  - 有人新增 Agent 忘了声明 → 无人发现；
  - 有人改了架构文档的必填字段 → 代码不跟着改，两份事实分叉；
  - 有人声明了权限目录外的 key（例如把 `product:read` 写成 `products:read`）
    → 声明「看起来合理」，但没有任何角色拥有该权限，Guardrail 永远拒绝执行。

因此本文件的重点不是「契约存在」，而是**判别力**：
每条断言都要能构造出违规并证明它会被抓到。

**与架构文档的关系**：`test_output_fields_match_architecture_doc` 直接解析
`docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` 的 §7.2~§7.9 并与契约比对
——这样「文档改了、代码没改」会在 CI 变红，而不是靠人工核对（T-52 同类教训）。
"""
import re
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
ARCH_DOC = REPO_DIR / "docs" / "AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md"

sys.path.insert(0, str(BACKEND_DIR))

from app.agents import contracts as c  # noqa: E402
from app.agents.base import BaseAgent  # noqa: E402

# ---------------------------------------------------------------- 冻结清单一致性

def test_frozen_count_is_eight():
    """§7.1 冻结 8 个 Agent；增删必须走 §20 变更评审。"""
    assert len(c.CONTRACTS) == 8, sorted(c.CONTRACTS)
    assert c.FROZEN_AGENT_COUNT == 8


def test_assert_frozen_count_detects_wrong_size(monkeypatch):
    """判别力：契约表条数不对时必须抛错，而不是静默通过。

    构造方式：把 FROZEN_AGENT_COUNT 改成 9（模拟「有人加了 Agent 却忘了
    更新架构文档」），断言自检真的会拦住。
    """
    monkeypatch.setattr(c, "FROZEN_AGENT_COUNT", 9)
    with pytest.raises(AssertionError) as exc:
        c.assert_frozen_count()
    assert "必须恰好 9 条" in str(exc.value)


def test_domains_match_frozen_enum():
    """每个契约的 domain 必须落在 §6.2 的 8 个领域枚举内，且互不重复。"""
    domains = [ct.domain for ct in c.CONTRACTS.values()]
    assert set(domains) == c.DOMAINS, sorted(domains)
    assert len(domains) == len(set(domains)), "领域出现重复：%s" % domains


# ---------------------------------------------------------------- 八项声明齐全

@pytest.mark.parametrize("name", sorted(c.CONTRACTS))
def test_every_contract_declares_all_eight_fields(name):
    """§6.2 的八项声明必须全部非空（缺一项即不合格）。"""
    ct = c.CONTRACTS[name]
    assert ct.domain
    assert ct.capabilities, "capabilities 不得为空"
    assert ct.input_schema
    assert ct.output_schema
    assert ct.required_permissions, "required_permissions 不得为空"
    assert ct.required_data_scope
    assert ct.risk_level in c.RISK_LEVELS
    assert ct.max_budget >= 0
    assert ct.required_output_fields, "§7.2~§7.9 为每个 Agent 冻结了必填输出字段"


def test_contract_is_immutable():
    """契约必须不可变——运行时改写会让 Guardrail 读到的与架构记载不一致。"""
    ct = c.CONTRACTS["listing"]
    with pytest.raises(FrozenInstanceError):
        ct.risk_level = c.RISK_LOW  # type: ignore[misc]


# ---------------------------------------------------------------- 判别力（核心）

def test_contract_rejects_unknown_permission():
    """判别力：声明权限目录外的 key 必须**构建期**报错。

    为什么关键：权限 key 拼错（`products:read`）不会让任何测试变红，
    但 Guardrail 会永远拒绝执行——属于「静默失效」，比报错更危险。
    """
    with pytest.raises(ValueError) as exc:
        c.AgentContract(
            agent_name="x", domain=c.DOMAIN_LISTING, capabilities=("a",),
            input_schema="i", output_schema="o",
            required_permissions=frozenset({"products:read"}),   # 拼错：应为 product:read
            required_data_scope=c.SCOPE_WORKSPACE_ALL,
            risk_level=c.RISK_LOW, max_budget=0.01,
            required_output_fields=("f",),
        )
    assert "权限目录外的 key" in str(exc.value)
    assert "products:read" in str(exc.value)


def test_contract_rejects_unknown_domain():
    """判别力：domain 不在 §6.2 枚举内必须报错（防止自造领域）。"""
    with pytest.raises(ValueError) as exc:
        c.AgentContract(
            agent_name="x", domain="marketing", capabilities=("a",),
            input_schema="i", output_schema="o",
            required_permissions=frozenset({c.PERM_AI_READ}),
            required_data_scope=c.SCOPE_WORKSPACE_ALL,
            risk_level=c.RISK_LOW, max_budget=0.01,
            required_output_fields=("f",),
        )
    assert "domain 不在冻结枚举内" in str(exc.value)


def test_contract_rejects_unknown_risk_level():
    """判别力：risk_level 必须是 LOW / MEDIUM / HIGH。"""
    with pytest.raises(ValueError) as exc:
        c.AgentContract(
            agent_name="x", domain=c.DOMAIN_RISK, capabilities=("a",),
            input_schema="i", output_schema="o",
            required_permissions=frozenset({c.PERM_AI_READ}),
            required_data_scope=c.SCOPE_WORKSPACE_ALL,
            risk_level="CRITICAL", max_budget=0.01,
            required_output_fields=("f",),
        )
    assert "risk_level 不在冻结枚举内" in str(exc.value)


def test_contract_rejects_empty_capabilities():
    """判别力：能力清单为空必须报错（§6.2 要求「动词 + 对象」）。"""
    with pytest.raises(ValueError) as exc:
        c.AgentContract(
            agent_name="x", domain=c.DOMAIN_RISK, capabilities=(),
            input_schema="i", output_schema="o",
            required_permissions=frozenset({c.PERM_AI_READ}),
            required_data_scope=c.SCOPE_WORKSPACE_ALL,
            risk_level=c.RISK_LOW, max_budget=0.01,
            required_output_fields=("f",),
        )
    assert "capabilities 不得为空" in str(exc.value)


# ---------------------------------------------------------------- 与架构文档比对

def _doc_output_fields() -> dict[str, list[str]]:
    """从架构文档 §7.2~§7.9 提取「必填输出字段」的顶层字段名。

    去掉全角括号内的嵌套说明（如 `candidates[]`（含 `supplier_id` / ...）），
    只取顶层字段——否则嵌套字段会被误当成顶层必填项。
    """
    text = ARCH_DOC.read_text(encoding="utf-8")
    section, found = None, {}
    for line in text.split("\n"):
        match = re.match(r"^### (7\.\d+) ", line)
        if match:
            section = match.group(1)
            continue
        if section and "必填输出字段" in line:
            cleaned = re.sub(r"（[^）]*）", "", line)
            found[section] = re.findall(r"`([^`]+)`", cleaned)
            section = None
    return found


def test_output_fields_match_architecture_doc():
    """契约的必填输出字段必须与架构文档 §7.2~§7.9 **逐条一致**。

    这是本文件最重要的一条：它让「文档改了、代码没改」在 CI 变红。
    """
    doc = _doc_output_fields()
    assert len(doc) == 8, "架构文档应含 §7.2~§7.9 共 8 节，实际 %d" % len(doc)

    mismatches = []
    for name, ct in c.CONTRACTS.items():
        section = ct.spec_section.lstrip("§")
        want = doc.get(section, [])
        got = list(ct.required_output_fields)
        if want != got:
            mismatches.append("%s（%s）\n    文档: %s\n    契约: %s"
                              % (name, section, want, got))
    assert not mismatches, "契约与架构文档不一致：\n  " + "\n  ".join(mismatches)


def test_doc_extractor_has_discriminating_power(monkeypatch):
    """判别力：字段提取器必须真能读出内容（防止「提取到空列表所以永不报错」）。"""
    doc = _doc_output_fields()
    assert doc["7.2"][0] == "opportunity_id", doc["7.2"]
    assert "evidence[]" in doc["7.2"], doc["7.2"]
    assert doc["7.9"] == ["target_type", "target_id", "risk_level",
                          "violations[]", "required_actions[]"], doc["7.9"]


def test_doc_extractor_catches_field_removed_from_contract(monkeypatch):
    """判别力：从契约里删掉一个必填字段，比对必须失败。"""
    doc = _doc_output_fields()
    ct = c.CONTRACTS["listing"]
    truncated = ct.required_output_fields[:-1]     # 去掉最后一个字段
    assert list(truncated) != doc["7.5"], "构造样本无效：截断后仍与文档相同"


# ---------------------------------------------------------------- Agent 类挂载

def test_all_implemented_agents_declare_contract():
    """已实现的领域 Agent 必须挂上契约（否则 §6.2 在代码层没有落点）。

    映射依据架构文档附录 B「Specialist Agents 按 8 个冻结 Agent 归并重构」。
    """
    from app.agents.compliance import ComplianceAgent
    from app.agents.discovery import DiscoveryAgent, ProductAgent
    from app.agents.factory_opportunity import FactoryOpportunityAgent
    from app.agents.listing import ListingAgent
    from app.agents.listing_review import ListingReviewAgent
    from app.agents.pricing import AdsAgent, PricingAgent
    from app.agents.supplier import SupplierAgent

    expected = {
        DiscoveryAgent: "market_intelligence",
        ProductAgent: "product_intelligence",
        SupplierAgent: "supply_intelligence",
        FactoryOpportunityAgent: "supply_intelligence",
        ListingAgent: "listing",
        ListingReviewAgent: "risk_compliance",
        PricingAgent: "finance_intelligence",
        AdsAgent: "operation_optimization",
        ComplianceAgent: "risk_compliance",
    }
    for cls, key in expected.items():
        assert cls.agent_contract is c.CONTRACTS[key], (
            "%s 应挂 %s，实际 %r" % (cls.__name__, key, cls.agent_contract))
        assert cls.contract() is c.CONTRACTS[key]


def test_base_agent_rejects_undeclared_contract():
    """判别力：未声明契约的 Agent 调用 contract() 必须抛错（不静默返回 None）。

    为什么：静默返回 None 会让「新增 Agent 忘了登记」一路滑到运行时，
    正是红线 1（禁止临时创建 Agent）要防的情形。
    """
    class _Undeclared(BaseAgent):
        name = "undeclared"

    with pytest.raises(NotImplementedError) as exc:
        _Undeclared.contract()
    assert "未声明 agent_contract" in str(exc.value)


def test_support_agent_is_explicitly_unregistered():
    """`SupportAgent` 不在 §7.1 冻结清单内，必须**显式**登记为未纳入架构。

    背景：架构 §6.1 把「客服 Agent」列为禁止的员工角色式建模，而该类承担
    客服意图识别与自动回复。这里断言它是 `None`（显式）而非「忘了写」——
    并锁定该事实，使「悄悄把它当成第 9 个 Agent」无法发生。
    """
    from app.agents.support import SupportAgent

    assert SupportAgent.agent_contract is None
    with pytest.raises(NotImplementedError):
        SupportAgent.contract()
    # 它也不得混进冻结清单
    assert "support" not in c.CONTRACTS


def test_orchestrator_is_not_in_contracts():
    """Orchestrator 是编排者而非领域 Agent（§4），不得出现在领域契约表里。"""
    assert "orchestrator" not in c.CONTRACTS
