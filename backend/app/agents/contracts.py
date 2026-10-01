"""Agent 契约声明（Agent OS §6.2 / §18.3 第 1 步）。

**本模块只放声明，不含任何业务逻辑、不做任何 I/O。**

为什么需要
    `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` §6.2 要求每个 Agent 必须声明
    8 项能力约束（`domain` / `capabilities` / `input_schema` / `output_schema` /
    `required_permissions` / `required_data_scope` / `risk_level` / `max_budget`），
    但此前**一项都没有**——Agent 的能力边界只存在于文档里，代码无从校验，
    也无法在 Guardrail / Runtime 落地时被机器读取。

    §18.3 把「补齐声明」列为**第 1 步**（纯声明、低风险），且要求
    **必须按 1→6 顺序、禁止跳步**。本模块即该步的交付。

为什么把词汇表集中在这里，而不是散在 12 个 Agent 文件里
    权限 key、数据范围、风险等级是**跨 Agent 共用的词汇表**。若每个 Agent 各写一份
    字符串字面量，改名时必然漏改（T-53：同一份信息维护在两个地方必然漂移）。
    因此：**词汇表集中定义在本模块**，Agent 只做引用。

与权限体系的关系
    `required_permissions` 的取值**必须**来自 `docs/phase1_interfaces.md` 第 4 节的
    权限目录（权威实现是 `services/workspace_context.py` 的 `ROLE_PERMISSIONS`）。
    本模块用 `_ALL_KNOWN_PERMISSIONS` 做**构建期自检**：声明里出现目录外的权限 key
    会直接抛错——防止「声明了一个没人能拥有的权限」这种静默失效。

与 Action 层的关系
    `risk_level` 是 Agent 的**默认**风险等级，用于 §9.2「Action 提案」的初值。
    具体 Action 的最终风险等级由 `action_type` 决定（§9.4 枚举），二者可能不同
    （例：Listing Agent 默认 MEDIUM，但它产出的 `CREATE_LISTING_DRAFT` 是 AUTO_SAFE）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- 词汇表：领域

DOMAIN_MARKET = "market"
DOMAIN_SUPPLY = "supply"
DOMAIN_PRODUCT = "product"
DOMAIN_LISTING = "listing"
DOMAIN_CHANNEL = "channel"
DOMAIN_OPERATION = "operation"
DOMAIN_FINANCE = "finance"
DOMAIN_RISK = "risk"

DOMAINS = frozenset({
    DOMAIN_MARKET, DOMAIN_SUPPLY, DOMAIN_PRODUCT, DOMAIN_LISTING,
    DOMAIN_CHANNEL, DOMAIN_OPERATION, DOMAIN_FINANCE, DOMAIN_RISK,
})

# ---------------------------------------------------------------- 词汇表：风险

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"

RISK_LEVELS = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH})

# ---------------------------------------------------------------- 词汇表：数据范围
# 取值来自 docs/phase1_interfaces.md 第 5 节（冻结枚举）。

SCOPE_WORKSPACE_ALL = "WORKSPACE_ALL"
SCOPE_SHOP_SCOPED = "SHOP_SCOPED"
SCOPE_SELF_ONLY = "SELF_ONLY"

DATA_SCOPES = frozenset({SCOPE_WORKSPACE_ALL, SCOPE_SHOP_SCOPED, SCOPE_SELF_ONLY})

# ---------------------------------------------------------------- 词汇表：权限
# 权威来源：docs/phase1_interfaces.md 第 4 节权限目录 + workspace_context.ROLE_PERMISSIONS。
# `compliance:check` 不在该节表格里，但它是 ROLE_PERMISSIONS 中的真实 key
# （见 services/workspace_context.py 的 _PERM_COMPLIANCE_CHECK 及其注释）。

PERM_WORKSPACE_READ = "workspace:read"
PERM_WORKSPACE_WRITE = "workspace:write"
PERM_PRODUCT_READ = "product:read"
PERM_PRODUCT_WRITE = "product:write"
PERM_SUPPLY_READ = "supply:read"
PERM_SUPPLY_WRITE = "supply:write"
PERM_LISTING_READ = "listing:read"
PERM_LISTING_WRITE = "listing:write"
PERM_ORDER_READ = "order:read"
PERM_ORDER_WRITE = "order:write"
PERM_FINANCE_READ = "finance:read"
PERM_FINANCE_WRITE = "finance:write"
PERM_PURCHASE_READ = "purchase:read"
PERM_PURCHASE_WRITE = "purchase:write"
PERM_SETTLEMENT_READ = "settlement:read"
PERM_SETTLEMENT_WRITE = "settlement:write"
PERM_REFUND_READ = "refund:read"
PERM_REFUND_WRITE = "refund:write"
PERM_COMPLIANCE_READ = "compliance:read"
PERM_COMPLIANCE_CHECK = "compliance:check"
PERM_COMPLIANCE_APPROVE = "compliance:approve"
PERM_AI_READ = "ai:read"
PERM_AI_WRITE = "ai:write"
PERM_WORKSPACE_MEMBER_ADMIN = "workspace:member:admin"
PERM_PLATFORM_ADMIN = "platform:admin"

# 权限目录外的 key 一律拒绝（构建期自检用）。
_ALL_KNOWN_PERMISSIONS = frozenset({
    PERM_WORKSPACE_READ, PERM_WORKSPACE_WRITE,
    PERM_PRODUCT_READ, PERM_PRODUCT_WRITE,
    PERM_SUPPLY_READ, PERM_SUPPLY_WRITE,
    PERM_LISTING_READ, PERM_LISTING_WRITE,
    PERM_ORDER_READ, PERM_ORDER_WRITE,
    PERM_FINANCE_READ, PERM_FINANCE_WRITE,
    PERM_PURCHASE_READ, PERM_PURCHASE_WRITE,
    PERM_SETTLEMENT_READ, PERM_SETTLEMENT_WRITE,
    PERM_REFUND_READ, PERM_REFUND_WRITE,
    PERM_COMPLIANCE_READ, PERM_COMPLIANCE_CHECK, PERM_COMPLIANCE_APPROVE,
    PERM_AI_READ, PERM_AI_WRITE,
    PERM_WORKSPACE_MEMBER_ADMIN, PERM_PLATFORM_ADMIN,
})

# ---------------------------------------------------------------- 声明结构


@dataclass(frozen=True)
class AgentContract:
    """单个 Agent 的能力契约（Agent OS §6.2 的八项声明）。

    不可变（frozen）：契约是**冻结事实**，运行时不得改写——否则 Guardrail 读到的
    与架构文档记载的会不一致，且无从审计。
    """

    agent_name: str
    domain: str
    capabilities: tuple[str, ...]
    input_schema: str
    output_schema: str
    required_permissions: frozenset[str]
    required_data_scope: str
    risk_level: str
    max_budget: float
    # §7.2~§7.9 的「必填输出字段」——由架构文档逐条提取，供校验器比对。
    # 为什么放进契约：否则「文档写了必填、实现忘了输出」只能靠人工核对。
    required_output_fields: tuple[str, ...] = ()
    spec_section: str = ""
    known_gaps: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.domain not in DOMAINS:
            raise ValueError("domain 不在冻结枚举内：%r" % (self.domain,))
        if self.risk_level not in RISK_LEVELS:
            raise ValueError("risk_level 不在冻结枚举内：%r" % (self.risk_level,))
        if self.required_data_scope not in DATA_SCOPES:
            raise ValueError(
                "required_data_scope 不在冻结枚举内：%r" % (self.required_data_scope,))
        unknown = self.required_permissions - _ALL_KNOWN_PERMISSIONS
        if unknown:
            raise ValueError(
                "required_permissions 含权限目录外的 key：%s（权威目录见 "
                "docs/phase1_interfaces.md 第 4 节）" % sorted(unknown))
        if self.max_budget < 0:
            raise ValueError("max_budget 不得为负：%r" % (self.max_budget,))
        if not self.capabilities:
            raise ValueError(
                "capabilities 不得为空——§6.2 要求「动词 + 对象」的能力清单")
        if not self.required_output_fields:
            raise ValueError(
                "required_output_fields 不得为空——§7.2~§7.9 为每个 Agent 冻结了必填输出字段")

# ---------------------------------------------------------------- 冻结清单（V1.0，§7）
#
# 本清单**必须**与架构文档第 7 节一致。增删改必须走架构变更评审（§20）。
# 每条契约的字段依据如下：
#   - domain / capabilities / input_schema / output_schema：§7.2~§7.9 正文；
#   - risk_level：§7.1 总览表「默认风险」列；
#   - required_permissions：取该 Agent 经 Tool 层访问所需的最小权限集
#     （§11 Tool 表 + docs/phase1_interfaces.md 第 4 节权限目录）；
#   - required_data_scope：§17 与 phase1_interfaces 第 5 节；领域 Agent 一律
#     WORKSPACE_ALL（数据范围收窄属 Phase 3 的 SHOP_SCOPED 预留）；
#   - max_budget：§6.2 第 8 项。**当前 LLM 层无成本计量能力**（实测
#     `ai/llm.py` 无 cost/token/price 任何字段），故本值目前是**声明上限**，
#     待 Phase 3 Runtime 落地后由 Guardrail 真正执行；见 known_gaps。

MARKET_INTELLIGENCE = AgentContract(
    agent_name="market_intelligence",
    domain=DOMAIN_MARKET,
    capabilities=(
        "分析市场趋势", "发现市场需求", "分析竞争格局",
        "扩展关键词", "评分机会",
    ),
    input_schema="MarketData + WorkspaceCapability",
    output_schema="Opportunity Object",
    required_output_fields=("opportunity_id", "title", "category", "demand_score", "competition_score",
                       "profit_potential", "evidence[]", "freshness", "source"),
    required_permissions=frozenset({PERM_PRODUCT_READ, PERM_AI_READ}),
    required_data_scope=SCOPE_WORKSPACE_ALL,
    risk_level=RISK_LOW,
    max_budget=0.05,
    spec_section="§7.2",
    known_gaps=(
        "当前实现为 DiscoveryAgent（含 scan_trends / expand_keywords / score_product），"
        "直接读写 ORM（MarketTrend / ProductScore），尚未经 Tool 层——§18.3 第 2 步",
        "评分依据的可复算性（§7.2 约束）尚未由 schema 强制",
    ),
)

SUPPLY_INTELLIGENCE = AgentContract(
    agent_name="supply_intelligence",
    domain=DOMAIN_SUPPLY,
    capabilities=(
        "匹配供应商", "分析工厂供货能力", "分析 1688 货源",
        "分析成本", "分析 MOQ",
    ),
    input_schema="Opportunity Object + WorkspaceSupplyCapability",
    output_schema="Supply Recommendation",
    required_output_fields=("opportunity_id", "candidates[]", "recommended_supply_mode", "risk_notes"),
    required_permissions=frozenset({PERM_SUPPLY_READ, PERM_PRODUCT_READ, PERM_AI_READ}),
    required_data_scope=SCOPE_WORKSPACE_ALL,
    risk_level=RISK_LOW,
    max_budget=0.05,
    spec_section="§7.3",
    known_gaps=(
        "当前由 SupplierAgent 与 FactoryOpportunityAgent 两个类分担，尚未归并为单一 Agent",
        "MOQ / 交期「不得估算、无数据须显式标注缺失」（§7.3 约束）尚未由 schema 强制",
    ),
)

PRODUCT_INTELLIGENCE = AgentContract(
    agent_name="product_intelligence",
    domain=DOMAIN_PRODUCT,
    capabilities=(
        "分析商品生命周期", "分析 SKU", "分析利润", "建议商品组合",
    ),
    input_schema="Product + 经营事实",
    output_schema="Product Insight",
    required_output_fields=("product_id", "lifecycle_stage", "sku_analysis", "profit_analysis",
                       "portfolio_suggestion", "evidence[]"),
    required_permissions=frozenset({PERM_PRODUCT_READ, PERM_ORDER_READ, PERM_AI_READ}),
    required_data_scope=SCOPE_WORKSPACE_ALL,
    risk_level=RISK_LOW,
    max_budget=0.05,
    spec_section="§7.4",
    known_gaps=(
        "当前实现为 DiscoveryAgent 内的 ProductAgent（standardize / map_category），"
        "尚未独立成类",
        "利润必须调用统一 Unit Economics Service、禁止自算（§7.4 约束，ADR-F11）"
        "——统一实现在 services/costing.py，但尚未强制所有路径走它",
    ),
)

LISTING = AgentContract(
    agent_name="listing",
    domain=DOMAIN_LISTING,
    capabilities=(
        "生成标题", "生成描述", "生成 SEO 关键词", "适配多平台", "检查合规",
    ),
    input_schema="Product Insight + Channel Recommendation",
    output_schema="Listing Draft",
    required_output_fields=("product_id", "platform", "language", "title", "description",
                       "keywords[]", "compliance_status", "draft_id"),
    required_permissions=frozenset(
        {PERM_LISTING_READ, PERM_LISTING_WRITE, PERM_PRODUCT_READ, PERM_AI_READ}),
    required_data_scope=SCOPE_WORKSPACE_ALL,
    risk_level=RISK_MEDIUM,
    max_budget=0.10,
    spec_section="§7.5",
    known_gaps=(
        "generate/optimize/publish 已只产出 Action 提案，由 Orchestrator 同步调度（D48）；"
        "Task 派发、Runtime 会话注入及完整 Trace 仍待 §18.3 第 4～6 步",
    ),
)

CHANNEL_STRATEGY = AgentContract(
    agent_name="channel_strategy",
    domain=DOMAIN_CHANNEL,
    capabilities=(
        "匹配销售平台", "分析 Store 表现", "建议渠道组合",
    ),
    input_schema="Opportunity Object + 已连接 Store",
    output_schema="Channel Recommendation",
    required_output_fields=("opportunity_id", "recommended_channels[]", "excluded_channels[]", "evidence[]"),
    required_permissions=frozenset({PERM_LISTING_READ, PERM_ORDER_READ, PERM_AI_READ}),
    required_data_scope=SCOPE_WORKSPACE_ALL,
    risk_level=RISK_LOW,
    max_budget=0.05,
    spec_section="§7.6",
    known_gaps=(
        "**尚无独立实现**：当前只有 services/platforms.py 与 shops 能力可复用",
        "「只能推荐已连接或用户明确声明可接入的渠道」（ADR-F08）需在实现时强制",
    ),
)

OPERATION_OPTIMIZATION = AgentContract(
    agent_name="operation_optimization",
    domain=DOMAIN_OPERATION,
    capabilities=(
        "分析销售", "分析订单", "分析广告", "分析退款", "分析库存", "分析利润",
        "生成优化建议",
    ),
    input_schema="销售/订单/广告/退款/库存/利润",
    output_schema="Optimization Action",
    required_output_fields=("finding", "metric_evidence", "proposed_actions[]"),
    required_permissions=frozenset(
        {PERM_ORDER_READ, PERM_FINANCE_READ, PERM_REFUND_READ,
         PERM_LISTING_READ, PERM_AI_READ}),
    required_data_scope=SCOPE_WORKSPACE_ALL,
    risk_level=RISK_MEDIUM,
    max_budget=0.10,
    spec_section="§7.7",
    known_gaps=(
        "当前由 AdsAgent 与 services/alerting.py 分担，尚未归并为单一 Agent",
        "AdsAgent.optimize_budget() 已改为只产出预算建议，ADJUST_AD_BUDGET 经"
        "Action 审批执行（D47）；其余优化能力仍待收敛为 Action 提案",
    ),
)

FINANCE_INTELLIGENCE = AgentContract(
    agent_name="finance_intelligence",
    domain=DOMAIN_FINANCE,
    capabilities=(
        "分析利润", "分析 ROI", "分析成本结构", "识别财务风险",
    ),
    input_schema="成本/售价/费率/汇率/结算",
    output_schema="Financial Insight",
    required_output_fields=("period", "revenue", "cost_breakdown", "profit", "roi",
                       "risk_flags[]", "evidence[]"),
    required_permissions=frozenset(
        {PERM_FINANCE_READ, PERM_SETTLEMENT_READ, PERM_ORDER_READ, PERM_AI_READ}),
    required_data_scope=SCOPE_WORKSPACE_ALL,
    risk_level=RISK_LOW,
    max_budget=0.05,
    spec_section="§7.8",
    known_gaps=(
        "当前由 PricingAgent 与 services/commercial_analytics.py 分担，尚未归并",
        "PricingAgent 已被 Action 服务端白名单拒绝，D50 分析产物由调度层保存；"
        "统一 Financial Insight 必填字段尚未覆盖全部存量分析输出",
    ),
)

RISK_COMPLIANCE = AgentContract(
    agent_name="risk_compliance",
    domain=DOMAIN_RISK,
    capabilities=(
        "检查平台规则", "检查商品风险", "检查侵权", "识别高风险动作",
    ),
    input_schema="Product / Listing + 平台规则包",
    output_schema="Risk Assessment",
    required_output_fields=("target_type", "target_id", "risk_level", "violations[]", "required_actions[]"),
    required_permissions=frozenset(
        {PERM_COMPLIANCE_READ, PERM_COMPLIANCE_CHECK, PERM_PRODUCT_READ,
         PERM_LISTING_READ, PERM_AI_READ}),
    required_data_scope=SCOPE_WORKSPACE_ALL,
    risk_level=RISK_LOW,
    max_budget=0.05,
    spec_section="§7.9",
    known_gaps=(
        "当前由 ComplianceAgent 与 ListingReviewAgent 分担，尚未归并为单一 Agent",
        "ComplianceAgent 已强制确定性规则风险底线及 HIGH 规则依据；"
        "完整 Risk Assessment 输出与跨领域风险判定仍待归并",
        "Risk Agent 的**否决权**（HIGH 必须阻断后续自动执行）属 Action 层职责，"
        "合规报告与发布门禁已阻断 HIGH；其他领域的统一否决仍待接管",
    ),
)

# ---------------------------------------------------------------- 索引

#: Agent 名 -> 契约。运行时（Guardrail / Runtime / Tool 层）应从这里读取，
#: 不得各自维护第二份（T-53）。
CONTRACTS: dict[str, AgentContract] = {
    c.agent_name: c for c in (
        MARKET_INTELLIGENCE,
        SUPPLY_INTELLIGENCE,
        PRODUCT_INTELLIGENCE,
        LISTING,
        CHANNEL_STRATEGY,
        OPERATION_OPTIMIZATION,
        FINANCE_INTELLIGENCE,
        RISK_COMPLIANCE,
    )
}

#: 架构 §7.1 冻结清单要求的 Agent 数量。任何增删都必须走 §20 变更评审。
FROZEN_AGENT_COUNT = 8


def get_contract(agent_name: str) -> AgentContract | None:
    """按名取契约；未登记返回 None（调用方决定是拒绝还是降级）。"""
    return CONTRACTS.get(agent_name)


def assert_frozen_count() -> None:
    """自检：契约表必须恰好覆盖 §7.1 的 8 个冻结 Agent。

    为什么需要：红线 1 禁止「临时创建 Agent」。若有人新增契约却忘了更新
    架构文档第 7 节，或误删一条，本函数让它在**导入期**就暴露，
    而不是等运行时才发现某个 Agent「悄悄不在清单里」。
    """
    if len(CONTRACTS) != FROZEN_AGENT_COUNT:
        raise AssertionError(
            "Agent 契约表必须恰好 %d 条（§7.1 冻结清单），实际 %d 条：%s"
            % (FROZEN_AGENT_COUNT, len(CONTRACTS), sorted(CONTRACTS)))


assert_frozen_count()
