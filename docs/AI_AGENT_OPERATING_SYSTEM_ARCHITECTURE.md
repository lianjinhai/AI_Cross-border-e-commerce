# AI Agent Operating System 架构冻结 V1.0

> 文档状态：**FROZEN** ｜ 冻结日期：2026-09-23 ｜ 架构负责人：AI 架构总负责人
> 上游依据：`docs/archive/final_architecture_assessment.md`（ADR-F01 ~ ADR-F15）、`docs/phase1_interfaces.md`（Workspace Context 契约）
> 下游约束：**后续所有 AI 能力开发必须遵循本架构**。违反本文件的实现不予合入。
> 本文件不包含编码任务、不创建数据库表、不创建 Agent 代码。执行时机见第 18 节。

---

## 0. 冻结声明与适用范围

### 0.1 本文件冻结什么

| 冻结项 | 说明 |
|---|---|
| AI 系统的分层结构 | 谁在什么位置，谁可以调用谁 |
| 调用拓扑 | 禁止对等调用，强制经 Orchestrator |
| Agent 清单与职责边界 | 第一批 8 个领域能力 Agent，增删需走变更评审 |
| Agent 生命周期状态机 | 状态取值与合法迁移 |
| Action 模型 | Agent 影响业务数据的唯一合法路径 |
| Tool 层契约 | Agent 访问业务能力的唯一入口 |
| Guardrail 规则 | 权限、数据范围、风险、审批四道闸 |
| Workspace 融合方式 | 所有 Agent 必须 Workspace-aware |
| 技术选型结论 | 编排内核的选型与替换边界 |

### 0.2 本文件不冻结什么

- 具体 Prompt 文案（属实现细节，可迭代）；
- 具体模型供应商与版本（属配置，可切换）；
- Agent 内部算法（规则/LLM 混合比例可迭代）；
- 前端呈现形态。

### 0.3 与 Phase 0 冻结决策的关系

本文件**不新增**任何与 Phase 0 ADR 冲突的决策，只做展开。对应关系：

| Phase 0 ADR | 本文件展开章节 |
|---|---|
| ADR-F11 AI 是 Workspace-aware Business Copilot | 第 1、4、17 节 |
| ADR-F08 Capability Profile 属于 Workspace Context | 第 4.2、17.3 节 |
| ADR-F09 Business Stage 使用确定性版本化规则 | 第 17.3 节 |
| ADR-F10 Business Path 是结构化版本化经营计划 | 第 5.4、17.4 节 |
| ADR-F13 Workspace Context 是前端唯一业务上下文 | 第 17.1 节 |
| ADR-F15 生产事实以数据库为准 | 第 8.4、15 节 |
| 6.3 AI Operations 数据模型 | 第 9.3 节 |

---

## 1. AI 在本平台中的定位

### 1.1 定位

本平台的 AI 是：**AI 原生跨境经营操作系统（AI-native Cross-border Business Operating System）**。

它不是：

| 反面模式 | 为什么禁止 |
|---|---|
| 聊天机器人 | 只回答，不经营；无法承接目标 |
| 多个 AI 角色聊天（老板 Agent / 运营 Agent / 采购 Agent） | 角色拟人化导致职责重叠、互相甩锅、无法审计 |
| 万能单体 Agent | 无边界，无法做权限与风险分级 |
| Agent 自由协作网络 | 不可控、不可审计、无法管理权限 |

### 1.2 唯一合法工作流

```
用户提出经营目标
      ↓
系统理解 Workspace 上下文（服务端组装，不信任前端）
      ↓
AI 自动拆解任务（Planner 产出 Task Graph）
      ↓
调用专业能力（Specialist Agents，经 Orchestrator 调度）
      ↓
生成建议（Recommendation / Business Path）
      ↓
经过权限与风险控制（Guardrail 四道闸）
      ↓
必要时执行经营动作（AI Action → Executor → Business API）
```

### 1.3 判定标准

一个 AI 能力是否合格，用这五个问题检验：

1. 它是否在 Workspace 上下文内运行？（无上下文即不合格）
2. 它的输入是否来自服务端组装的事实？（信任前端输入即不合格）
3. 它的输出是否可归类为「建议 / Business Path / AI Action」三者之一？（自由文本即不合格）
4. 它影响业务数据是否经过 Action + Guardrail？（直写数据库即不合格）
5. 它是否可被完整追溯（Agent Trace）？（无痕即不合格）

---

## 2. 总体架构

### 2.1 分层图

```
┌──────────────────────────────────────────────────────────────┐
│  User（用户提出经营目标）                                      │
└───────────────────────────┬──────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  AI Copilot（对话/界面入口，仅负责表达与确认，不含业务判断）      │
└───────────────────────────┬──────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  Agent Orchestration Layer                                    │
│  ┌────────────────┐  ┌──────────┐  ┌────────────────────┐    │
│  │  Orchestrator  │→ │ Planner  │→ │  Agent Runtime     │    │
│  └────────────────┘  └──────────┘  └────────────────────┘    │
│         ↑                                     ↓               │
│  ┌────────────────┐                  ┌────────────────────┐  │
│  │ Guardrail Layer│←────────────────→│ Specialist Agents  │  │
│  └────────────────┘                  └────────────────────┘  │
└───────────────────────────┬──────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  Tool / MCP Layer（唯一业务访问入口，Workspace 绑定 + 审计）     │
└───────────────────────────┬──────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  Business Services（既有 Router / Service / Platform Adapter） │
└───────────────────────────┬──────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  Business Data（PostgreSQL / 未来的 Redis 协调层）              │
└──────────────────────────────────────────────────────────────┘

横切能力：Memory System ｜ Knowledge System ｜ Action System
         ｜ Event System ｜ Observability System
```

### 2.2 十大组件

| # | 组件 | 职责 | 归属章节 |
|---|---|---|---|
| 1 | Orchestrator | 控制中心：接收目标、装载上下文、创建 Task、协调、合并、输出、控权限 | 第 4 节 |
| 2 | Planner | 复杂任务拆解为 Task Graph | 第 5 节 |
| 3 | Specialist Agents | 领域能力执行者（8 个） | 第 6、7 节 |
| 4 | Agent Runtime | 任务状态机、重试、超时、恢复、日志 | 第 8 节 |
| 5 | Memory System | 五层记忆 | 第 11 节 |
| 6 | Knowledge System | 统一知识检索 | 第 12 节 |
| 7 | Tool Layer | 唯一业务访问入口 | 第 10 节 |
| 8 | Guardrail Layer | 权限/范围/风险/审批 | 第 13 节 |
| 9 | Action System | 业务数据变更的唯一合法通道 | 第 9 节 |
| 10 | Observability System | Agent Trace 全链路可追溯 | 第 15 节 |

### 2.3 控制流与数据流的区分

- **控制流**：Orchestrator → Planner → Agent → Tool → Service。单向，可审计。
- **数据流**：Service → Tool → Agent → Orchestrator → 用户。数据只经 Tool 层进出，Agent 不直连数据库。
- **横切**：Guardrail 在控制流的每个动作点介入；Observability 贯穿全部环节。

---

## 3. 架构红线（禁止事项）

以下五条为**不可协商**的冻结红线。任何实现违反其一即为不合格。

### 红线 1：禁止临时创建 Agent

- Agent 必须来自本文件第 7 节的冻结清单；
- 新增 Agent 必须走架构变更评审，并在本文件登记职责、输入、输出；
- 禁止在业务代码里内联定义「一次性 Agent」。

### 红线 2：禁止 Agent 之间自由调用（Peer-to-Peer）

**禁止**：

```
Market Agent ──直接调用──→ Supply Agent ──直接调用──→ Product Agent
```

**必须**：

```
Market Agent ──→ Orchestrator ──→ Supply Agent ──→ Orchestrator ──→ Product Agent
```

原因：

| 问题 | P2P 的后果 | Orchestrator 中心化的结果 |
|---|---|---|
| 可控性 | 调用链爆炸，无法预测 | 拓扑固定，可静态验证 |
| 审计 | 谁调用了谁无法完整还原 | 每次派发都是一条 Trace |
| 权限 | 每个 Agent 需自行鉴权，必然遗漏 | 权限在 Orchestrator 单点判定 |
| 成本 | 递归调用导致 Token 爆炸 | 预算在 Task Graph 层可控 |
| 失败处理 | 错误在 Agent 间扩散 | 失败可定位到具体 Task |

**实现约束**：Agent 之间不得持有彼此的引用，不得 import 其他 Agent 模块。跨 Agent 协作只能通过「向 Orchestrator 返回结构化结果 + 由 Orchestrator 派发下一 Task」实现。

> 现状说明：`backend/app/agents/orchestrator.py` 当前通过 `with DiscoveryAgent(...)` 等直接实例化专业 Agent，属于「中心化调度」的雏形，方向正确；但它是**同步直调**，缺少 Task 层。Phase 2 引入 Agent Runtime 后，这些调用必须改为「Orchestrator 创建 Task → Runtime 执行」。

### 红线 3：禁止 Agent 直接操作数据库

- Agent 不得 import ORM 模型进行写操作；
- Agent 不得持有 `Session` 进行业务表写入；
- 一切业务读写必须经 Tool Layer；
- Agent 自身的运行态记录（Task、Trace、Memory）由 Runtime 统一写入，不由 Agent 自行写。

> 现状说明：`BaseAgent.__init__` 当前直接创建 `SessionLocal()` 并持有 `self.db`，且 `_log()` 直接写 `AiLog`。这是**已知技术债**，在 Phase 2 必须收敛为「Agent 只返回结构化结果，Runtime 负责落库」。迁移策略见第 18.3 节。

### 红线 4：禁止 Agent 绕过权限执行动作

- 任何影响业务数据的动作必须走：Action → Policy → Permission → Risk → Approval → Executor → Business API；
- 禁止 Agent 调用业务写接口（如 `POST /api/products`）绕过 Action 层；
- 禁止 Agent 使用高于请求者权限的身份执行动作。

### 红线 5：禁止用聊天机器人代替 Agent 系统

- 对话界面只是入口，不是系统本体；
- 禁止把「LLM 返回一段文本」当作完成业务任务；
- 业务任务的完成标准是：Task 状态为 `COMPLETED` 且产出结构化结果（或已生成 Action）。

---

## 4. Orchestrator 设计

### 4.1 定位

Orchestrator 是 AI 系统的**唯一控制中心**。它是唯一有权创建 Task、派发 Agent、合并结果、触发 Action 的组件。

### 4.2 职责（九项）

| # | 职责 | 说明 |
|---|---|---|
| 1 | 接收用户目标 | 结构化目标（含目标类型、约束、期望结果） |
| 2 | 读取 Workspace Context | 服务端组装，见 4.3 |
| 3 | 判断任务类型 | 分类到已知任务族；未知则先澄清 |
| 4 | 创建 Task | 落库，状态 `CREATED` |
| 5 | 调用 Planner | 复杂任务产出 Task Graph |
| 6 | 协调 Agent 执行 | 按 Task Graph 顺序/并行派发 |
| 7 | 合并结果 | 多 Agent 结果去重、冲突消解、口径统一 |
| 8 | 生成最终用户输出 | 建议 / Business Path / Action 提案 |
| 9 | 控制权限和风险 | 与 Guardrail 协同，决定是否需审批 |

### 4.3 必须装载的 Workspace Context

Orchestrator 每次运行前必须从服务端 Context 服务获取（对应 `docs/phase1_interfaces.md` 与 ADR-F13）：

| 字段 | 用途 |
|---|---|
| `workspace_id` | 数据隔离与审计主体 |
| `workspace_type` | ORGANIZATION / PERSONAL / FACTORY，决定可用能力 |
| `business_stage` | DISCOVERY / SETUP / TESTING / OPERATING / GROWING / OPTIMIZING，决定推荐策略 |
| `capability_profile` | 当前能做什么（含来源标记），决定可行方案 |
| `permissions` | 允许做什么 |
| `data_scope` | 可见数据范围 |
| `connected_stores` | 已连接销售渠道 |
| `products` | 现有商品池概况 |
| `supply_sources` | 已连接货源 |

**禁止**：使用前端传入的 `role` / `budget` / `capability` / `workspace_id` 作为授权依据（ADR-F11）。

### 4.4 Orchestrator 的边界（不能做什么）

| 不能做 | 原因 |
|---|---|
| 不能替代所有 Agent | 否则退化为万能单体，丧失专业化与可审计性 |
| 不能承担全部业务分析 | 分析必须由领域 Agent 完成，Orchestrator 只做调度与合并 |
| 不能直接写业务数据 | 必须经 Action 层 |
| 不能自行提升权限 | 权限来自 Context，不可自造 |
| 不能跳过 Guardrail | 无例外 |

### 4.5 任务分类与路由

Orchestrator 需要判断任务类型。冻结的任务族：

| 任务族 | 触发示例 | 典型 Agent 组合 |
|---|---|---|
| `OPPORTUNITY_DISCOVERY` | 「帮我找适合东南亚销售的产品」 | Market → Supply → Product → Channel → Finance |
| `LISTING_PRODUCTION` | 「给这个商品做上架内容」 | Product → Listing → Risk |
| `PRICING_OPTIMIZATION` | 「重新定价」 | Finance → Operation |
| `SUPPLY_MATCHING` | 「找供应商」 | Supply → Finance |
| `CHANNEL_STRATEGY` | 「我该做哪个平台」 | Channel → Market → Finance |
| `OPERATION_REVIEW` | 「最近经营怎么样」 | Operation → Finance |
| `RISK_REVIEW` | 「这个商品有风险吗」 | Risk → Product |
| `BUSINESS_PATH_PLANNING` | 「我下一步该做什么」 | Planner 主导 + 全 Agent |

未命中任何任务族时，Orchestrator 必须**先澄清**，不得猜测执行。

### 4.6 结果合并规则

多 Agent 结果合并必须遵守：

1. **口径统一**：财务与经营指标必须调用统一 Metrics / Unit Economics Service，禁止各 Agent 自算（ADR-F11）；
2. **冲突显式化**：Agent 结论冲突时，Orchestrator 必须显式呈现分歧与各自证据，**不得静默择一**；
3. **来源可溯**：每个结论必须携带产出 Agent、证据引用、新鲜度；
4. **降级可见**：任一 Agent 降级（LLM→规则）必须在输出中标注。

---

## 5. Planner 设计

### 5.1 定位

Planner 是 Orchestrator 的下属组件，负责**把复杂目标拆解为可执行、可依赖、可验证的任务图**。

Planner **不执行**任务，只产出计划。

### 5.2 拆解示例

用户目标：「帮我找一个适合东南亚销售的产品。」

Planner 拆解：

| Task | 内容 | 依赖 | 承担 Agent |
|---|---|---|---|
| T1 | 分析用户能力（capability_profile + 已连店铺 + 预算声明） | — | Orchestrator（读 Context，不派 Agent） |
| T2 | 分析市场机会（东南亚需求/趋势/竞争） | T1 | Market Intelligence Agent |
| T3 | 寻找供应（货源匹配、成本、MOQ） | T2 | Supply Intelligence Agent |
| T4 | 计算利润（含汇率、平台费、物流） | T3 | Finance Intelligence Agent |
| T5 | 匹配销售渠道（平台 × Store 适配） | T4 | Channel Strategy Agent |
| T6 | 生成行动建议（Business Path 草案） | T5 | Orchestrator 汇总 |
| T7 | 风险与合规检查 | T5 | Risk & Compliance Agent |

### 5.3 Task Graph 结构

```
Goal
 ↓
Tasks（每个 Task 有 id / 类型 / 承担 Agent / 输入引用 / 期望输出 schema）
 ↓
Dependencies（DAG，禁止环）
 ↓
Agents（每个 Task 绑定一个 Agent，禁止一个 Task 多 Agent）
```

冻结约束：

- Task Graph 必须是 **DAG**（有向无环图），出现环即拒绝执行；
- 每个 Task 必须声明**期望输出的结构 schema**，否则无法验证完成；
- 每个 Task 必须声明**依赖的输入来源**（上游 Task 输出或 Context 字段）；
- 每个 Task 必须声明**预算上限**（LLM 调用次数 / Token 上限），防止成本失控；
- 高风险 Task 必须声明 `requires_approval = true`。

### 5.4 Planner 与 Business Path 的关系

| | Task Graph | Business Path |
|---|---|---|
| 时间尺度 | 单次请求内的执行计划 | 跨周期的经营路线（ADR-F10） |
| 生命周期 | 请求结束即完结 | 版本化、持久化、用户确认 |
| 产出者 | Planner | Orchestrator 汇总 + 用户确认 |
| 存储 | Agent Runtime（Task 表） | `business_paths` / `business_path_steps` |

**规则**：Business Path 可以包含 Task Graph 的**结论**，但 Task Graph 不得直接修改 Business Path。修改 Business Path 必须走用户确认。

### 5.5 Planner 的降级策略

| 场景 | 行为 |
|---|---|
| LLM 不可用 | 使用**确定性规则模板**（按任务族预置拆解模板） |
| 目标模糊 | 不拆解，返回澄清问题清单 |
| 拆解超出能力 | 显式返回「超出当前能力」，禁止编造 Agent |
| 任务图有环 | 拒绝并告警 |

---

## 6. Agent 设计原则

### 6.1 核心原则：Agent 不是员工角色

**禁止**：

- 老板 Agent；
- 运营 Agent；
- 采购 Agent；
- 客服 Agent。

**采用**：**领域能力 Agent（Domain Capability Agent）**。

判定标准：

| 维度 | 员工角色 Agent（禁止） | 领域能力 Agent（采用） |
|---|---|---|
| 命名依据 | 组织职位 | 领域 + 能力 |
| 职责边界 | 按人划分，必然重叠 | 按领域划分，可验证不重叠 |
| 输入 | 模糊的「工作」 | 明确的上游对象 + Context |
| 输出 | 模糊的「建议」 | 结构化对象（有 schema） |
| 可替换性 | 换人等于重做 | 可单独升级算法 |

### 6.2 Agent 的能力约束

每个 Agent 必须声明：

1. `domain`：所属领域（market / supply / product / listing / channel / operation / finance / risk）；
2. `capabilities`：能力清单（动词 + 对象）；
3. `input_schema`：输入结构（引用上游对象类型）；
4. `output_schema`：输出结构（冻结的对象类型）；
5. `required_permissions`：执行所需权限（Guardrail 据此校验）；
6. `required_data_scope`：所需数据范围；
7. `risk_level`：默认风险等级（LOW / MEDIUM / HIGH）；
8. `max_budget`：单次执行的 LLM 预算上限。

### 6.3 Agent 的执行模式（双模）

继承现有 `BaseAgent.ask_json()` 的设计并冻结：

| 模式 | 触发 | 要求 |
|---|---|---|
| `llm` | 模型可用且返回可解析 JSON | 必须通过 schema 校验 |
| `rule` | 模型不可用 / 超时 / 解析失败 / schema 不合法 | **必须存在确定性规则实现**，保证离线可运行 |

冻结要求：**每个 Agent 的每个 action 都必须有 rule 实现**。没有 rule 兜底的 Agent 不允许上线。

### 6.4 Agent 的输出纪律

Agent 输出必须是以下三类之一：

1. **Insight / Recommendation**：结构化建议对象（不改变业务数据）；
2. **Business Path 草案**：供 Orchestrator 汇总；
3. **Action Proposal**：建议执行的动作（进入 Action 流程，不直接执行）。

禁止：Agent 直接返回「已执行」；执行结果只能由 Action System 产生。

---

## 7. 第一批冻结 Agent 清单

以下 8 个 Agent 为 **V1.0 冻结清单**。增删改必须走架构变更评审并更新本节。

### 7.1 清单总览

| # | Agent | domain | 输入 | 输出对象 | 默认风险 | 现状 |
|---|---|---|---|---|---|---|
| 1 | Market Intelligence Agent | market | Market Data + Workspace Capability | `Opportunity Object` | LOW | 部分存在（`DiscoveryAgent`） |
| 2 | Supply Intelligence Agent | supply | Opportunity + Workspace Supply Capability | `Supply Recommendation` | LOW | 部分存在（`SupplierAgent` / `FactoryOpportunityAgent`） |
| 3 | Product Intelligence Agent | product | Product + 经营事实 | `Product Insight` | LOW | 部分存在（`ProductAgent`） |
| 4 | Listing Agent | listing | Product Insight + Channel | `Listing Draft` | MEDIUM | 存在（`ListingAgent`） |
| 5 | Channel Strategy Agent | channel | Opportunity + 已连 Store | `Channel Recommendation` | LOW | 部分存在（`Shop`/`platforms` 能力） |
| 6 | Operation Optimization Agent | operation | 销售/订单/广告/退款/库存/利润 | `Optimization Action` | MEDIUM | 部分存在（`AdsAgent` / 分析服务） |
| 7 | Finance Intelligence Agent | finance | 成本/售价/费率/汇率/结算 | `Financial Insight` | LOW（只分析） | 部分存在（`PricingAgent` / `commercial_analytics`） |
| 8 | Risk & Compliance Agent | risk | 商品/Listing/平台规则 | `Risk Assessment` | LOW | 存在（`ComplianceAgent` / `ListingReviewAgent`） |

> 「部分存在」指当前有可复用能力，但**不满足本架构的 Tool 层与 Action 层约束**，需在 Phase 2 重构接入。

### 7.2 Market Intelligence Agent

- **职责**：市场机会发现。
- **能力**：趋势分析、市场需求、竞争分析、关键词分析、机会评分。
- **输入**：Market Data（趋势库、搜索量、竞争度）；Workspace Capability（能做什么）。
- **输出**：`Opportunity Object`。
- **必填输出字段**：`opportunity_id` / `title` / `category` / `demand_score` / `competition_score` / `profit_potential` / `evidence[]` / `freshness` / `source`。
- **约束**：评分必须给出**可复算的依据**（各分项权重与原始值），禁止只给总分；数据陈旧必须标注 `freshness`。

### 7.3 Supply Intelligence Agent

- **职责**：供应匹配。
- **能力**：工厂分析、1688 分析、Supplier 匹配、成本分析、MOQ 分析。
- **输入**：`Opportunity Object`；Workspace Supply Capability（已连货源、可接受的 Supply Mode）。
- **输出**：`Supply Recommendation`。
- **必填输出字段**：`opportunity_id` / `candidates[]`（含 `supplier_id` / `unit_cost` / `currency` / `moq` / `lead_time` / `evidence[]`）/ `recommended_supply_mode` / `risk_notes`。
- **约束**：多币种必须走可追溯汇率（沿用现有 `SupplierOffer.currency` + FX 失败即失败的设计）；**MOQ 与交期不得估算**，无数据时必须显式标注缺失。

### 7.4 Product Intelligence Agent

- **职责**：商品分析。
- **能力**：商品生命周期、SKU 分析、利润分析、商品组合。
- **输出**：`Product Insight`。
- **必填输出字段**：`product_id` / `lifecycle_stage` / `sku_analysis` / `profit_analysis` / `portfolio_suggestion` / `evidence[]`。
- **约束**：利润必须调用统一 Unit Economics Service，禁止自算（ADR-F11）。

### 7.5 Listing Agent

- **职责**：商品内容生产。
- **能力**：标题、描述、SEO 关键词、多平台适配、合规检查。
- **输出**：`Listing Draft`。
- **必填输出字段**：`product_id` / `platform` / `language` / `title` / `description` / `keywords[]` / `compliance_status` / `draft_id`。
- **约束**：生成后**必须**经 Risk & Compliance Agent 检查；发布动作必须走 Action（`PUBLISH_LISTING`），且风险等级至少 MEDIUM。

### 7.6 Channel Strategy Agent

- **职责**：销售渠道策略。
- **能力**：平台匹配、Store 分析、渠道建议。
- **输出**：`Channel Recommendation`。
- **必填输出字段**：`opportunity_id` / `recommended_channels[]`（含 `platform` / `store_id` / `fit_score` / `reason`）/ `excluded_channels[]`（含排除原因）/ `evidence[]`。
- **约束**：只能推荐**已连接或用户明确声明可接入**的渠道（ADR-F08：Channel Capability 只能由用户声明或真实连接 Store 认定）；**禁止推荐未授权平台**。

### 7.7 Operation Optimization Agent

- **职责**：经营优化。
- **读取**：销售、订单、广告、退款、库存、利润。
- **输出**：`Optimization Action`。
- **必填输出字段**：`finding` / `metric_evidence` / `proposed_actions[]`（每个含 `action_type` / `target` / `expected_impact` / `risk_level`）。
- **约束**：输出的是**Action 提案**，不是已执行的动作；每条提案必须绑定可验证的指标证据。

### 7.8 Finance Intelligence Agent

- **职责**：经营财务分析。
- **能力**：利润、ROI、成本、风险。
- **输出**：`Financial Insight`。
- **必填输出字段**：`period` / `revenue` / `cost_breakdown` / `profit` / `roi` / `risk_flags[]` / `evidence[]`。
- **硬约束**：**只分析，不执行任何财务操作**。禁止生成涉及资金划转、结算执行、退款执行的 Action。这是本 Agent 的**不可协商边界**。

### 7.9 Risk & Compliance Agent

- **职责**：风险控制。
- **检查**：平台规则、商品风险、侵权、高风险动作。
- **输出**：`Risk Assessment`。
- **必填输出字段**：`target_type` / `target_id` / `risk_level` / `violations[]`（含 `rule_source` / `rule_version` / `severity`）/ `required_actions[]`。
- **约束**：
  - 规则来源必须**版本化可追溯**（沿用现有 `platform_rules.py` 的 `version` + `source_url`）；
  - 高风险判定**不得由 LLM 单独决定**，必须有确定性规则命中；
  - Risk Agent 拥有**否决权**：其判定的 HIGH 风险必须阻断后续自动执行。

### 7.10 Agent 之间的关系

**禁止**任何直接调用。合法的协作形态只有一种：

```
Agent A 完成 → 返回结构化结果给 Orchestrator
                    ↓
            Orchestrator 判断是否需要 Agent B
                    ↓
            创建新 Task → Runtime 派发 Agent B
                    ↓
            Agent B 读取 A 的结果（经 Tool 层，作为输入对象）
```

---

## 8. Agent Runtime 设计

### 8.1 定位

Agent Runtime 是**任务执行引擎**，负责把 Task 从创建推进到终态。它不包含业务逻辑。

### 8.2 Agent Task 状态机（冻结）

```
                    ┌──────────┐
                    │ CREATED  │
                    └────┬─────┘
                         ↓
                    ┌──────────┐
                    │ PLANNING │
                    └────┬─────┘
                         ↓
                    ┌──────────┐
              ┌────→│ RUNNING  │←────┐
              │     └────┬─────┘     │
              │          ↓           │
              │   ┌──────────────┐   │
              │   │WAITING_APPROVAL│ │
              │   └──────┬───────┘   │
              │          ↓           │
              │   ┌──────────┐       │
              └───│EXECUTING │───────┘
                  └────┬─────┘
                       ↓
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
   ┌──────────┐  ┌──────────┐  ┌───────────┐
   │COMPLETED │  │  FAILED  │  │ CANCELLED │
   └──────────┘  └──────────┘  └───────────┘
```

| 状态 | 含义 | 合法后继 |
|---|---|---|
| `CREATED` | 任务已创建，未开始 | PLANNING, CANCELLED |
| `PLANNING` | 正在拆解/准备 | RUNNING, FAILED, CANCELLED |
| `RUNNING` | Agent 正在执行 | WAITING_APPROVAL, EXECUTING, COMPLETED, FAILED, CANCELLED |
| `WAITING_APPROVAL` | 等待人工审批 | EXECUTING, FAILED, CANCELLED |
| `EXECUTING` | 正在执行已批准的动作 | COMPLETED, FAILED |
| `COMPLETED` | 终态 | — |
| `FAILED` | 终态 | — |
| `CANCELLED` | 终态 | — |

**禁止**：终态回退到非终态；`WAITING_APPROVAL` 直接跳 `COMPLETED`（必须经 EXECUTING 或 FAILED）。

### 8.3 Runtime 必备能力

| 能力 | 要求 |
|---|---|
| 重试 | 按错误类型区分：可重试（网络/超时）vs 不可重试（schema 不合法/权限拒绝）；重试次数与退避策略在 Task 上声明 |
| 超时 | 每个 Task 必须有超时；超时后进入 FAILED 并释放资源 |
| 恢复 | 进程重启后能识别未完成 Task 并恢复（沿用现有 `recover_incomplete_runs()` 思路，扩展到 Task 粒度） |
| 日志 | 每次状态迁移、每次 Agent 调用、每次 Tool 调用都必须留痕 |
| 租约 | 防止多 Worker 重复执行同一 Task（沿用现有 `_LeaseHeartbeat` 设计） |
| 幂等 | 同一 Task 重复执行不得产生重复副作用（外部调用必须带 idempotency_key） |
| 预算 | 每个 Task 的 LLM 调用次数与 Token 消耗必须可统计、可中断 |

### 8.4 执行持久化原则（ADR-F15 展开）

- **任务状态必须落数据库**，不得只存内存或 Redis；
- Redis 只用于锁、限流、缓存、Token cache、任务协调；
- 外部副作用（平台发布、拉单、代发）必须：
  1. 先写「意图」记录（含 idempotency_key）；
  2. 执行后写「结果」；
  3. 无法确认结果时标记 `UNCERTAIN` 并通过 Read-back 核对；
- 禁止「先调用外部接口，成功后再写库」这种崩溃即丢失的模式。

### 8.5 与现有 Workflow Engine 的关系

现状：`backend/app/workflows/engine.py` 已有 `WorkflowRun` / `WorkflowStep`、租约心跳、`recover_incomplete_runs()`、`resume_run()`。

冻结策略：**不推倒重来，分两层演进**。

| 层 | 归属 | 职责 |
|---|---|---|
| Workflow Layer（现有） | 用户可见的自动化流程（如「自动铺货全流程」） | 编排**确定性业务步骤** |
| Agent Task Layer（新增） | AI 任务执行 | 编排**Agent 的推理与决策** |

关系：Workflow Step 可以**调用** Agent Task（作为一个步骤），但 Agent Task 不得反向修改 Workflow 定义。两者共享同一套租约、恢复、幂等原则。

---

## 9. AI Action 系统设计

### 9.1 核心原则

**Agent 不能直接修改业务数据。**

分析产物不是业务执行动作：D50 的 PricingAgent 仅返回分析，由 Orchestrator
调用产物服务保存既有 PricingRecord，并复核身份、权限和商品归属。
它不创建 AI Action、不修改商品售价、不执行财务操作；此类持久化不得由 Agent 自行落库。
D52 的选品评分遵循同一 Insight 产物边界：Orchestrator/产物服务原子保存既有
ProductScore 与 AiDecision，绑定可信身份和不可变来源，不创建经营 Action；
规则表现读取通过只读 Product Tool 即时聚合，不触发缓存写入。
D54 的上架复核同样由可信调度/产物服务保存既有 ListingReviewDecision，
Agent 只输出分析；保存和重放复核当前身份、归属、内容、规则全文及最新报告。
规则同步迁出 Agent，在独立服务会话执行；人工裁决不复制自动产物来源，
新风险不能借旧批准放行。复核产物不等同发布审批，发布仍经 Action 四道闸。
D55 的合规报告及来源链也由可信服务保存；Listing.risk_level 业务副本经
受限 Action 投影，报告与风险动作原子提交，失败整批回滚；错误与 high 阻断下游。
模型不能低估规则风险或独自认定 high，合规知识新路径不触发向量缓存写。

唯一合法路径：

```
Agent 产出建议
      ↓
AI Action（结构化动作提案）
      ↓
Policy Check（是否符合经营策略）
      ↓
Permission Check（调用者是否有权限）
      ↓
Risk Check（风险等级判定）
      ↓
Approval（按风险等级决定是否需人工审批）
      ↓
Executor（幂等执行器）
      ↓
Business API（既有 Router / Service）
```

### 9.2 示例对照

| 场景 | 禁止的做法 | 必须的做法 |
|---|---|---|
| AI 建议降价 | `db.query(Product).update({"price": x})` | 生成 `CHANGE_PRICE` Action → 走 Guardrail → Executor 调业务接口 |
| AI 建议加广告预算 | 直接改 `AdCampaign.budget` | 生成 `ADJUST_AD_BUDGET` Action（高风险，需审批） |
| AI 生成 Listing | 直接插入 `Listing` 行 | 生成 `CREATE_LISTING_DRAFT` Action（MEDIUM，可自动） |
| AI 建议采购 | 直接创建采购单 | 生成 `CREATE_PURCHASE_ORDER` Action（HIGH，需审批） |

### 9.3 `ai_actions` 数据模型（冻结）

对齐 Phase 0 第 6.3 节，字段冻结如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `workspace_id` | int | 归属 Workspace（必填） |
| `task_id` | int | 来源 Agent Task（可空，事件触发时可空） |
| `agent_type` | str | 产出 Agent |
| `action_type` | str | 动作类型（枚举见 9.4） |
| `target_type` | str | 目标对象类型 |
| `target_id` | int | 目标对象 id |
| `reason` | text | 为什么建议此动作（必填） |
| `evidence` | json | 证据引用（指标、订单、规则版本） |
| `expected_impact` | json | 预期影响（可量化） |
| `risk_level` | str | LOW / MEDIUM / HIGH |
| `required_permission` | str | 执行所需权限 key |
| `execution_mode` | str | OBSERVE / RECOMMEND / APPROVAL_REQUIRED / AUTO_SAFE |
| `approval_required` | bool | 是否需要人工审批 |
| `status` | str | 见 9.5 |
| `requested_by` | int | 发起者 user_id |
| `approved_by` | int | 审批者 user_id |
| `executed_by` | int | 执行者（人或系统） |
| `outcome` | json | 执行结果或失败原因 |
| `idempotency_key` | str | 唯一，防重复执行 |
| `created_at` / `updated_at` / `executed_at` | datetime | |

### 9.4 `action_type` 枚举（V1.0）

| 领域 | action_type | 默认风险 | 默认执行模式 |
|---|---|---|---|
| 商品 | `CHANGE_PRICE` | MEDIUM | APPROVAL_REQUIRED（阈值内可 AUTO_SAFE） |
| 商品 | `UPDATE_PRODUCT_CONTENT` | LOW | AUTO_SAFE |
| 商品 | `ARCHIVE_PRODUCT` | MEDIUM | APPROVAL_REQUIRED |
| Listing | `CREATE_LISTING_DRAFT` | MEDIUM | AUTO_SAFE |
| Listing | `PUBLISH_LISTING` | MEDIUM | APPROVAL_REQUIRED |
| Listing | `UNPUBLISH_LISTING` | HIGH | APPROVAL_REQUIRED |
| 供应 | `CREATE_PURCHASE_ORDER` | HIGH | APPROVAL_REQUIRED |
| 供应 | `CONTACT_SUPPLIER` | LOW | AUTO_SAFE |
| 广告 | `ADJUST_AD_BUDGET` | HIGH | APPROVAL_REQUIRED |
| 广告 | `PAUSE_AD_CAMPAIGN` | MEDIUM | APPROVAL_REQUIRED |
| 订单 | `SHIP_ORDER` | MEDIUM | APPROVAL_REQUIRED |
| 订单 | `SYNC_ORDERS` | LOW | AUTO_SAFE |
| 财务 | `RECORD_EXPENSE` | MEDIUM | APPROVAL_REQUIRED |

**冻结约束**：

1. `AUTO_SAFE` 仅允许出现在 LOW 风险或「已明确授权的阈值内」场景；
2. **禁止新增涉及资金划转的 action_type**；
3. Finance Intelligence Agent **不得产出任何 action**（只分析）；
4. 新增 action_type 必须同时声明：风险等级、所需权限、是否需审批、幂等键生成规则、回滚方式。

### 9.4.1 Action 增量目录（D48，2026-09-30）

| action_type | 风险 / 权限 | 审批 | 幂等 | 回滚 |
|---|---|---|---|---|
| `UPDATE_LISTING_CONTENT` | LOW / `listing:write` | AUTO_SAFE，仅草稿 | Workspace、发起人、类型、目标、服务端执行范围和载荷的 SHA256；执行时复核原始内容 | 按 outcome.before 人工恢复草稿；已发布内容禁止自动覆盖 |
| `CREATE_AD_CAMPAIGN_DRAFT`（D49） | LOW / `finance:write` | AUTO_SAFE，仅本地草稿，日预算 5～500 USD，不启动投放 | Workspace、发起人、Agent、类型、目标、服务端 run/step/输入位置和载荷的 SHA256；数据库唯一约束 | 人工删除新建草稿，保留 Action 审计；禁止自动调用投放平台 |
| `UPDATE_LISTING_COMPLIANCE_RISK`（D55） | LOW / `compliance:check` | AUTO_SAFE，仅可信最新报告风险副本，不改内容/发布 | 服务端原 scope/目标、报告与来源摘要；执行及成功重放核验当前依据，旧 low 不覆盖新 high | 按当前报告重新检测/发起受限投影，不盲目恢复旧 low；报告与 Action 原子失败整批回滚 |
| `REFRESH_BUILTIN_TRENDS`（D56） | LOW / `product:write` | AUTO_SAFE，仅日种子内置估算，不覆盖 csv/api | Workspace、真实发起人、类型、租户目标、服务端范围和载荷 SHA256；重放原 Action、锁内复核快照与固定候选 | outcome.before 供人工核验后恢复，仅内置数据；失败整批回滚，不自动覆盖真实来源 |

既有 `CREATE_LISTING_DRAFT` 的自动权限仅限新建草稿，不包括发布。
既有 `UPDATE_PRODUCT_CONTENT`（D51）固定 LOW / `product:write` / AUTO_SAFE，
本批次仅用于安全标准化类目、重量/材质/颜色和指纹；不改售价、采购或库存。
执行时锁内核对原始内容与重复候选；同范围重放原 Action，失败/拒绝不被恢复绕过。
范围清单保存于 Action evidence 和步骤 output，失败批次不缩掉原商品范围；
outcome.before 用于人工恢复。MySQL/PG 并发语义仍须单独验收。
既有 `PUBLISH_LISTING` 固定 MEDIUM / `listing:write` / APPROVAL_REQUIRED：
发布指纹覆盖 Listing、商品、规则版本、目标店铺；待处理意图复用，唯一键约束
兜底并发提交；拒绝/失败后新请求必须新建 Action，同一工作流范围则保留终态，
不能通过恢复绕过拒绝。发布失败保留目标状态及平台 checkpoint；真实平台撤销
须另走人工业务流程或未来 `UNPUBLISH_LISTING` 审批，不自动反向调用平台。

### 9.5 Action 状态机（冻结）

```
CREATED → PENDING_APPROVAL → APPROVED → EXECUTING → SUCCESS
   │              │              │           │
   │              ↓              ↓           ↓
   │          REJECTED       REJECTED     FAILED
   │
   └→（AUTO_SAFE 场景）→ APPROVED → EXECUTING → SUCCESS / FAILED
```

| 状态 | 含义 |
|---|---|
| `CREATED` | 已生成，未提交 |
| `PENDING_APPROVAL` | 等待人工审批 |
| `APPROVED` | 已批准，待执行 |
| `EXECUTING` | 执行中 |
| `SUCCESS` | 执行成功（终态） |
| `FAILED` | 执行失败（终态，可生成新 Action 重试） |
| `REJECTED` | 被拒绝（终态） |

**禁止**：`REJECTED` 或 `FAILED` 直接重试同一 Action；必须创建新 Action 并保留关联。

### 9.6 Executor 要求

D53 前置安全修复：复核与发布共用内容指纹 V2，纳入规则实际使用的商品标题
和目标平台；历史 V1 依据不自动放行，须重新复核。风险领域写入接管仍未完成。

- 必须**幂等**：同一 `idempotency_key` 重复调用只产生一次副作用；
- 必须**经业务 API/Service**，禁止绕过业务校验；
- 必须**以请求者权限执行**（不是系统超管权限）；
- 必须**写回 outcome**（成功结果或失败原因）；
- 执行失败必须保留现场（目标对象当前状态），便于人工判断。

---

## 10. Tool / MCP Layer 设计

### 10.1 定位

Tool Layer 是 **Agent 访问业务能力的唯一入口**。Agent 禁止直接访问数据库。

### 10.2 强制要求（三个必须）

| 要求 | 说明 |
|---|---|
| **必须绑定 Workspace** | 每个 Tool 调用必须携带 `workspace_id`；Tool 内部强制按该 id 过滤，禁止跨 Workspace 读取 |
| **必须检查 Permission** | 每个 Tool 声明所需 permission key；调用时由 Guardrail 校验，失败即拒绝 |
| **必须记录 Audit** | 每次调用记录：谁调用、哪个 Agent、哪个 Task、读/写了什么、耗时、结果 |

### 10.3 Tool 契约（冻结签名约定）

```
ToolCall {
  workspace_id : int        # 必填，绑定隔离
  agent_type   : str        # 调用方 Agent
  task_id      : int        # 来源 Task（可空）
  trace_id     : str        # 全链路追踪
  permission   : str        # 所需权限 key
  params       : object     # 业务参数
}

ToolResult {
  ok           : bool
  data         : object     # 结构化结果
  evidence     : object     # 证据引用（供 Action 使用）
  freshness    : datetime   # 数据新鲜度
  degraded     : bool       # 是否降级
  error        : object     # 失败原因（ok=false 时必填）
}
```

### 10.4 第一批 Tool 清单（冻结）

| Tool | 方法 | 所需权限 | 读/写 |
|---|---|---|---|
| **Product Tool** | `get_products()` | `product:read` | 读 |
| | `analyze_product()` | `product:read` | 读 |
| | `create_listing_draft()` | `listing:write` | 写（经 Action） |
| **Store Tool** | `get_store_metrics()` | `order:read` | 读 |
| | `list_connected_stores()` | `workspace:read` | 读 |
| | `sync_orders()` | `order:write` | 写（经 Action） |
| **Order Tool** | `get_orders()` | `order:read` | 读 |
| | `analyze_sales()` | `order:read` | 读 |
| **Supply Tool** | `search_suppliers()` | `supply:read` | 读 |
| | `get_supplier_offers()` | `supply:read` | 读 |
| | `create_purchase_order()` | `purchase:write` | 写（经 Action） |
| **Finance Tool** | `calculate_profit()` | `finance:read` | 读 |
| | `get_unit_economics()` | `finance:read` | 读 |
| | `get_fx_rate()` | `finance:read` | 读 |
| **Market Tool** | `get_trends()` | `product:read` | 读 |
| | `score_opportunity()` | `product:read` | 读 |
| **Compliance Tool** | `check_product()` | `compliance:read` | 读 |
| | `check_listing()` | `compliance:read` | 读 |
| | `get_platform_rules()` | `compliance:read` | 读 |
| **Memory Tool** | `recall()` / `remember()` | `ai:read` / `ai:write` | 读/写 |
| **Knowledge Tool** | `search()` | `ai:read` | 读 |

### 10.4.1 第二批 Tool 清单（冻结，2026-09-26 追加）

**补批规则**：**只增不改**。§10.4 的 22 条一字不动，新条目一律追加到本表。
清单完整性由 `backend/tests/test_tool_layer.py::test_manifest_matches_architecture_doc`
解析本页两张表格后与注册表逐条比对（含权限与读/写属性）。

**为什么需要补批**：§10.4 的第一批清单聚焦「机会 → 供应 → 商品 → 渠道」主干，
而现有 Agent 的 57 个读取点还覆盖 `Conversation` / `Listing` / `AdCampaign` /
`OpportunitySupplierMatch` / `SupplierCatalogProduct` / `ForecastSnapshot` /
`ListingReviewDecision` 七类目标（DEBT-36）。缺归属则 §18.3 第 2 步后半无法落地。
**第二批还包含既有 Tool 的方法补批**（Listing / Conversation / Supply / Order / Product / Compliance / Finance 共 10 个方法，为 supplier.py / listing_review.py / factory_opportunity.py / pricing.py 的聚合读取提供归属）；**第三批补批（D45，2026-09-28）追加 11 个只读方法**（计数 / 汇总 / 批量评分 / 类目 / 查重），为 orchestrator.py 与 discovery.py 的读取迁移提供归属，全部复用既有权限 key、零新增权限；**迁移进度见 §18.3.1**（唯一进度记录，本表只声明清单）。

| Tool | 方法 | 所需权限 | 读/写 |
|---|---|---|---|
| **Listing Tool** | `get_listings()` | `listing:read` | 读 |
| **Conversation Tool** | `get_conversations()` | `support:read` | 读 |
| **Supply Tool** | `get_offer_stats()` | `supply:read` | 读 |
| **Order Tool** | `get_daily_sales()` | `order:read` | 读 |
| **Product Tool** | `get_product_ids()` | `product:read` | 读 |
| **Compliance Tool** | `get_review_decisions()` | `compliance:read` | 读 |
| **Supply Tool** | `get_catalog_products()` | `supply:read` | 读 |
| **Supply Tool** | `get_forecast_snapshot()` | `supply:read` | 读 |
| **Finance Tool** | `get_campaigns()` | `finance:read` | 读 |
| **Listing Tool** | `get_published_product_ids()` | `listing:read` | 读 |
| **Product Tool** | `count_products()` | `product:read` | 读 |
| **Product Tool** | `get_categories()` | `product:read` | 读 |
| **Product Tool** | `get_latest_performance()` | `product:read` | 读 |
| **Product Tool** | `get_sold_product_ids()` | `product:read` | 读 |
| **Product Tool** | `find_duplicate()` | `product:read` | 读 |
| **Order Tool** | `get_sales_summary()` | `order:read` | 读 |
| **Finance Tool** | `get_campaign_totals()` | `finance:read` | 读 |
| **Market Tool** | `get_latest_scores()` | `product:read` | 读 |
| **Market Tool** | `pick_trend()` | `product:read` | 读 |
| **Listing Tool** | `count_listings()` | `listing:read` | 读 |
| **Conversation Tool** | `count_conversations()` | `support:read` | 读 |
| **Product Tool** | `calculate_performance()` | `product:read` | 读 |

### 10.5 写操作的特殊约束

**所有写操作 Tool 必须经 Action System**：

```
Agent → Tool.write(...)  ✗ 禁止直接落库
Agent → Action Proposal → Guardrail → Executor → Business Service  ✓
```

Tool 层中的「写方法」实际是**Action 的执行适配器**，不是 Agent 可直接调用的写入接口。

### 10.6 与 MCP 的关系

| 问题 | 冻结答案 |
|---|---|
| 是否采用 MCP 协议 | **是**，作为 Tool 层的对外协议标准 |
| MCP 的作用 | 让外部工具（第三方数据源、平台 API）以统一方式接入 |
| MCP 的边界 | MCP 只提供**能力接入**，不提供**权限绕过**；经 MCP 接入的能力同样受 Guardrail 约束 |
| 自研 Tool 与 MCP Tool | 对 Agent 而言接口一致；差异在适配层 |

---

## 11. Memory 系统设计

### 11.1 五层 Memory（冻结）

禁止只保存聊天记录。必须分为五层，各有明确归属与生命周期：

| # | 层 | 存什么 | 归属 | 生命周期 |
|---|---|---|---|---|
| 1 | **User Memory** | 用户偏好（语言、体验模式、常用平台、沟通风格） | 自然人 | 跨 Workspace，长期 |
| 2 | **Workspace Memory** | 经营事实（已连店铺、主营类目、Supply Mode、定价策略、合规红线） | Workspace | 随 Workspace 存续 |
| 3 | **Task Memory** | 当前任务状态（Task Graph、中间结果、待确认项） | Task | 任务结束即归档 |
| 4 | **Business Memory** | 历史经营经验（做过什么、结果如何、有效/无效的决策） | Workspace | 长期，可累积 |
| 5 | **Agent Runtime Memory** | Agent 运行状态（当前步骤、已调用工具、已消耗预算） | Task/Agent | 任务结束即清理 |

### 11.2 分层理由（为什么不能只存聊天记录）

| 只存聊天记录的后果 | 分层后的结果 |
|---|---|
| 用户偏好与经营事实混杂 | 换 Workspace 时偏好错乱 |
| 任务中间态污染长期记忆 | 历史决策被半成品污染 |
| 无法回答「上次这样做结果如何」 | Business Memory 可支撑经验复用 |
| 无法限制上下文长度 | 每层可独立裁剪、独立过期 |

### 11.3 Memory 写入纪律

| 规则 | 说明 |
|---|---|
| Agent 不得直接写长期 Memory | 长期记忆写入必须经 Runtime 判定（避免污染） |
| 敏感信息不得入 Memory | 凭证、Token、买家 PII 禁止写入 |
| 必须可删除 | 用户要求删除时必须能定位并清除 |
| 必须带来源 | 每条记忆标注来源（用户声明 / 系统观察 / 模型推断） |
| 模型推断不得覆盖用户声明 | 与 ADR-F08 一致 |

### 11.4 Memory 与 Knowledge 的区别

| | Memory | Knowledge |
|---|---|---|
| 内容 | 这个用户/Workspace/任务**发生过什么** | 这个领域**普遍成立什么** |
| 来源 | 本系统内的交互与事实 | 外部规则、教材、行业资料 |
| 时效 | 有明确时间点 | 有版本与生效期 |
| 检索方式 | 按主体（user/workspace/task） | 按语义相似度 + 过滤 |

---

## 12. Knowledge Layer 设计

### 12.1 定位

Agent 的知识不能散落在各 Agent 内部。统一由 Knowledge Layer 提供。

### 12.2 五类知识（冻结）

| # | 类别 | 内容 | 更新方式 |
|---|---|---|---|
| 1 | **平台规则** | 各平台发布规则、违禁词、类目限制、限流 | 版本化，可远程更新（沿用 `platform_rules.py` 的 `version` + `source_url`） |
| 2 | **跨境知识** | 物流、清关、税务、支付、合规常识 | 人工维护 + 审核 |
| 3 | **产品知识** | 类目知识、材质、认证要求 | 人工维护 + 审核 |
| 4 | **企业知识** | 本 Workspace 的内部规范、SOP、供应商协议 | 用户上传，Workspace 隔离 |
| 5 | **用户经验** | 该 Workspace 沉淀的有效做法（从 Business Memory 提炼） | 系统提炼 + 用户确认 |

### 12.3 检索纪律（强制）

1. **Agent 必须通过检索获取知识**，不得硬编码在 Prompt 里；
2. 检索结果必须带**来源与版本**，供 Evidence 引用；
3. 平台规则的检索结果必须带**生效日期**，过期规则必须显式标注；
4. 知识冲突时（如规则更新），**以最新版本为准**并记录冲突；
5. 企业知识与用户经验必须**按 Workspace 隔离**，禁止跨 Workspace 检索。

### 12.4 与现有实现的关系

现状：`backend/app/ai/knowledge.py` 提供 `KnowledgeDoc` + 嵌入检索，`platform_rules.py` 提供规则包。

冻结演进方向：

| 现状 | 目标 |
|---|---|
| KnowledgeDoc 为单一类型 | 拆分为上述五类，带类型标签与来源 |
| 检索无版本约束 | 检索结果必须带版本与生效期 |
| 规则包与知识库分离 | 统一入口，规则作为知识的一种类型 |

---

## 13. Guardrail 设计

### 13.1 四道闸（冻结）

**所有高风险动作必须依次通过**：

```
Permission（有没有权限）
    ↓
Data Scope（能不能看到这个数据）
    ↓
Risk Policy（风险等级是否允许自动执行）
    ↓
Approval（是否需要人工审批）
```

任一道不通过即拒绝，且拒绝原因必须可追溯。

### 13.2 风险分级与处置（冻结）

| 场景 | 风险 | 处置 | 依据 |
|---|---|---|---|
| 自动修改价格 | MEDIUM | **允许**（阈值内自动，超阈值需审批） | 商品价格可逆、影响可测 |
| 自动大额采购 | HIGH | **禁止**自动执行 | 资金不可逆 |
| 自动增加广告预算 | HIGH | **需要审批** | 持续消耗资金 |
| 自动发布高风险商品 | HIGH | **需要审核** | 平台封店风险不可逆 |
| 自动下架 Listing | HIGH | 需要审批 | 影响在售流量 |
| 自动发货 | MEDIUM | 需要审批 | 物流错误成本高 |
| 生成草稿类内容 | LOW | 允许自动 | 不产生外部影响 |
| 只读分析 | LOW | 允许自动 | 无副作用 |

### 13.3 阈值机制

MEDIUM 风险动作允许「阈值内自动」：

- 阈值由 **Workspace 配置**声明（不是 Agent 决定）；
- 阈值必须有**上限**（系统级天花板，Workspace 不可突破）；
- 超出阈值即升级为需审批；
- 阈值变更必须留审计。

### 13.4 Guardrail 的独立性（关键）

Guardrail **不属于** Agent，也不由 Agent 调用。它是 Agent 与业务之间的**独立关卡**：

```
Agent  →  Action  →  [Guardrail 独立判定]  →  Executor
                          ↑
                    不经过 Agent
```

**禁止**：Agent 自己判断「我有权限所以可以执行」；**禁止**：把 Guardrail 逻辑写进 Agent 内部。

### 13.5 与 Workspace Context 的绑定

Guardrail 的权限判定依据**只能**来自服务端组装的 Context：

- `permissions`（来自 Membership 的 Role → Permission 映射）；
- `data_scope`（数据范围）；
- Workspace 配置的阈值。

**禁止**使用前端传入的 role 或权限声明。

---

## 14. Event Driven 设计

### 14.1 定位

Agent 不能只由聊天触发。业务事件必须能触发 Agent。

### 14.2 事件清单（V1.0 冻结）

| 事件 | 触发条件 | 目标 Agent | 默认执行模式 |
|---|---|---|---|
| `OrderCreated` | 新订单落库 | Operation Optimization Agent | OBSERVE（分析，不自动改） |
| `SalesDrop` | 同比/环比跌幅超阈值 | Operation Optimization Agent | RECOMMEND |
| `InventoryLow` | 库存低于安全线 | Supply Intelligence Agent | RECOMMEND |
| `RefundIncrease` | 退款率超阈值 | Risk & Compliance Agent | RECOMMEND |
| `ListingRejected` | 平台审核拒绝 | Risk & Compliance Agent | RECOMMEND |
| `AdSpendSpike` | 广告花费异常上升 | Operation Optimization Agent | RECOMMEND（调整预算仍需审批） |
| `PriceAnomaly` | 价格异常（过低/过高） | Finance Intelligence Agent | OBSERVE |
| `ComplianceRuleUpdated` | 平台规则版本更新 | Risk & Compliance Agent | RECOMMEND（重新扫描在售商品） |

### 14.3 事件处理纪律（冻结）

1. **事件触发同样走 Orchestrator**，不得让事件直接调用 Agent；
2. 事件触发的任务必须有**去重机制**（同一事件不重复触发同一 Task）；
3. 事件触发的任务默认**只读或建议**，不得默认为自动执行；
4. 事件触发的任务必须记录**触发原因**（哪个事件、哪个阈值、什么数据）；
5. 事件风暴保护：同一 Workspace 在时间窗口内的事件必须限流。

### 14.4 与现有 Scheduler 的关系

现状：`backend/app/services/scheduler.py` + `Schedule` 表支持定时任务。

演进：Scheduler 作为**事件源之一**（定时扫描产生事件），事件进入统一 Event 层后由 Orchestrator 处理。禁止 Scheduler 直接调用 Agent。

---

## 15. Observability 设计

### 15.1 Agent Trace（冻结）

必须能完整回答以下七个问题：

| # | 问题 | 记录内容 |
|---|---|---|
| 1 | 哪个 Agent 执行 | `agent_type` + `agent_version` |
| 2 | 为什么执行 | `trigger`（用户目标 / 事件 / Workflow）+ `reason` |
| 3 | 读取什么数据 | Tool 调用清单 + 参数摘要 + 数据来源 |
| 4 | 生成什么结果 | 输出对象 + schema 校验结果 |
| 5 | 调用什么工具 | 每次 Tool 调用的 `trace_id` / 耗时 / 成功失败 |
| 6 | 产生什么 Action | Action 清单 + 风险等级 + 审批路径 |
| 7 | 执行结果 | Action outcome + 业务对象最终状态 |

### 15.2 Trace 结构

```
Trace {
  trace_id          # 全链路唯一
  workspace_id      # 隔离主体
  user_id           # 发起者
  task_id           # 所属 Task
  parent_trace_id   # 上游（用于串联 Orchestrator → Agent → Tool）
  agent_type
  trigger           # USER_GOAL / EVENT / WORKFLOW / MANUAL
  steps[]           # 有序步骤：LLM调用 / Tool调用 / 决策点
  tokens_used
  latency_ms
  outcome           # SUCCESS / FAILED / DEGRADED
  degraded_reason   # 降级原因（LLM→rule 时必填）
}
```

### 15.3 必记内容（与现有 AiLog 的关系）

现状：`AiLog` 记录 `agent` / `action` / `model` / `mode` / `prompt` / `response` / `latency_ms` / `ok`。

冻结演进：

| 现状字段 | 目标 |
|---|---|
| `agent` | 保留，扩展为 `agent_type` + `agent_version` |
| `action` | 保留，作为 step 类型 |
| `mode` | 保留（`llm` / `rule`），作为降级可见性依据 |
| `prompt` / `response` | **必须做 PII 与凭证脱敏**；禁止明文存 Token |
| — | 新增 `trace_id` / `task_id` / `parent_trace_id` / `workspace_id` / `tokens_used` / `trigger` |
| — | 新增 `steps[]`（Tool 调用序列） |

**实现状态（2026-09-27，与 D38 同期）**：`prompt` / `response` 的脱敏已落地——
唯一落点是 `BaseAgent._log`（Agent 审计）与 `tools/audit._brief`（Tool 审计，与
Agent 审计同表，漏一处等于没做），规则见 `backend/app/services/pii_redact.py`，
回归测试 `backend/tests/test_pii_redact.py`。存量 2 行（脱敏前落库）的处置见
规范 §11 **DEBT-37**。

### 15.4 可观测性红线

- 禁止记录 Token、密码、API Key、店铺凭证；
- 禁止记录买家 PII（姓名、电话、地址）；
- 降级（LLM→rule）必须在 Trace 中显式标记，不得静默；
- 每个 Action 必须能从 Trace 反查到决策依据。

### 15.5 Agent 代码的八条强制实现纪律（2026-09-24 补充，源于实测缺陷）

本节不是新架构，而是把红线落到**实现细节**上。以下六条均由真实缺陷倒推得出
（详见 `docs/DECISIONS.md` D12 / D13），违反即视为红线 3/红线 4 的破口：

**纪律 1：按主键取对象必须校验归属，且必须在写库之前。**

`db.get(Model, id)` 是主键直取，**不带任何租户过滤**。凡是「先按租户过滤出 A 表的行，
再用其中的 id 去 `db.get` B 表」的写法，都必须在 `db.get` 之后补
`obj.tenant_id == self.tenant_id` 判定；否则会跨租户泄漏。

实测两例：`pick_candidates` 按 `ProductScore.tenant_id` 过滤评分行，却用 `db.get(Product, pid)`
直取商品 → 泄漏他租户商品标题/类目；`/api/discovery/performance/{id}` 既未校验归属、
又会在**本租户名下写入缓存行**（污染，比只读泄漏更严重）。

归属校验应放在**服务层**而非只在路由：同一函数常被路由与 Agent 两条路径调用，
只在路由校验会漏掉 Agent 路径。会写库的函数必须在写之前拦截。

**纪律 2：告警/事件去重必须同时覆盖「同轮」与「跨轮」。**

去重键 = `(rule_key, subject_type, subject_id)`。两道防线缺一不可：

- 同轮：`SessionLocal` 为 `autoflush=False`，本轮 `db.add` 但未 flush 的记录对
  `db.query` **不可见**，只查库会让同一轮内同一对象的第 2 次触发重复入库；
- 跨轮：库查询 + 时间窗口，防重复告警疲劳。

**纪律 3：自然键对象不得把 `subject_id` 写死为 0。**

主键是整数时 `subject_type` 用纯类型名（`product`/`supplier`/`listing`）；
主键是自然键（字符串）时用 `<类型>:<自然键>`，例如 `platform:shopee`、`currency:CNY`。
若这类对象把 `subject_id` 写死为 0，多个自然键会共用同一去重键而**互相抑制（漏报）**——
这比重复告警更危险，因为它静默。

**纪律 4：凡是暴露给用户的阈值，必须是活参数。**

规则配置（`AlertRule.threshold`）里的每个字段都必须真正参与判定。写死的行为常量
（如把备货周数硬编码为 4）会让用户改配置「看起来生效、实际无效」——这是静默的功能缺陷。

**纪律 5：缓存的有效性判据必须覆盖「数据变化」，不能只看「数据存在」。**

AI 的输入层（表现分、机会分、经营快照）普遍带缓存。判据若写成「缓存里有没有数据」
（如 `units_sold > 0`），则数据从 5 条涨到 25 条时缓存**永不失效**，AI 会长期基于
陈旧经营数据做判断——而且不报错、不告警，属于最隐蔽的一类缺陷。

正确做法：把**聚合结果本身**当指纹（如窗口内 销量/销售额/利润 三项），全等才复用缓存；
并在测试里覆盖「0→有」「有→更多」「有→0」三段（规范 T-6）。

**纪律 6：`limit` 必须发生在排序与过滤之后。**

「先按时间取 limit 条，再在内存里按优先级排序」会让**最高优先级项被截断掉**。
实测：120 条新低风险告警 + 1 条较早的高风险告警，`limit=100` 时高风险完全不可见——
最该处理的静默漏报。排序键必须下推到 SQL（`ORDER BY` 在 `LIMIT` 之前），
并对 `limit` 做上下界夹紧；同理，**计数类指标必须走数据库聚合**，不能数截断后的列表长度。

**纪律 7：身份解析必须「权威源无条件优先」，兜底源只在权威源缺失时生效。**

实测缺陷（Phase 1.8）：路由守卫同时传 legacy `user`（兜底）与 Workspace Context（权威），
解析写成「`user.role` 非空就用 user」→ legacy 压过 Context。后果：平台账号代客进入租户后
（Context = OPERATOR + `is_impersonating=true`）仍被放行到 `/platform-admin`，代客隔离失效。
正确写法是把优先级收敛在**单一函数**（`resolveIdentity()`）内，调用方无需关心：
`context > user.fromContext > user(legacy)`。**兜底源存在的前提必须写进代码注释**，
否则后人会以"冗余"为由删掉它（本项目工厂账号拿不到 Context，删掉兜底即门户不可用）。

**纪律 8：删除类夹具必须校验目标，禁止只靠"约定"。**

实测缺陷：测试夹具按环境变量删除数据库文件，未校验目标是否为主库——误设
`ERP_TEST_DB=erp.db` 会直接删掉业务数据。**任何 unlink/truncate/DROP 路径都要显式
拒绝受保护目标**（本项目 `_guard_test_db_path()` 拒绝 `erp.db` 与历史固定名），
并让拒绝路径本身有测试覆盖。约定（"别这么设"）不是防护。

---

## 16. 技术选型评估

### 16.1 候选方案

| 方案 | 类型 | 核心范式 |
|---|---|---|
| LangGraph | 图编排框架 | 显式状态图 + 检查点 |
| Semantic Kernel | 企业 AI 编排 SDK | Plugin / Planner / Function 调用 |
| CrewAI | 多 Agent 协作框架 | 角色扮演 + 任务委派 |
| AutoGen | 多 Agent 对话框架 | 会话驱动 + 群聊 |
| 自研 Workflow/Orchestration Engine | 自有内核 | 显式状态机 + 租约 + 持久化 |

### 16.2 六维评分（1 = 差，5 = 优）

| 维度 | LangGraph | Semantic Kernel | CrewAI | AutoGen | 自研内核 |
|---|---|---|---|---|---|
| 稳定性 | 4 | 4 | 3 | 3 | **5** |
| 扩展性 | **5** | 4 | 3 | 4 | 3 |
| 生产能力 | 4 | 3 | 2 | 3 | **4** |
| 任务编排 | **5** | 3 | 3 | 4 | 4 |
| 权限控制 | 3 | 3 | **1** | 2 | **5** |
| 可维护性 | 3 | 3 | 2 | 2 | **4** |
| **合计** | **24** | **20** | **14** | **18** | **25** |

### 16.3 逐项说明

**LangGraph**

- 优势：图/状态机表达力强，天然适合 Task Graph；支持检查点与人工介入（human-in-the-loop）；子图可复用。
- 劣势：生态版本迭代快，升级成本需预算；权限、审计、Workspace 绑定仍需自建；引入后与本项目既有 `WorkflowRun`/租约体系存在概念重叠。
- 结论：**可作为 Planner/图执行的候选内核，但不是必须**。

**Semantic Kernel**

- 优势：企业级定位，Plugin 抽象清晰，微软长期维护。
- 劣势：Python SDK 成熟度低于 .NET；Planner 抽象与本项目需要的「Task Graph + 权限单点」不完全对齐；引入后仍需自建 Guardrail 与 Action 层。
- 结论：**概念可借鉴（Plugin/Tool 抽象），不作为内核首选**。

**CrewAI**

- 优势：上手快，多 Agent 协作开箱可用。
- **致命冲突**：其默认范式是**角色扮演 + Agent 之间自由委派**，直接违反本架构：
  - 违反红线 2（禁止 P2P）——CrewAI 的核心机制就是 Agent 互相委派；
  - 违反第 6.1 节（禁止员工角色 Agent）——CrewAI 的建模单位就是「角色（Role）」；
  - 权限控制维度得分 1：无 Workspace 绑定、无权限单点、无 Action 审批模型。
- 结论：**明确排除**。

**AutoGen**

- 优势：会话驱动灵活，研究场景表现好。
- **冲突**：群聊/会话驱动的执行路径**不可静态预测**，无法保证「每次 Agent 调用都经 Orchestrator」，审计困难；v0.2 → v0.4 的重大重写说明其稳定性风险。
- 结论：**明确排除**。

**自研 Workflow/Orchestration Engine**

- 优势：
  - 权限控制与审计是**原生设计**，不是外挂；
  - 已有可复用资产：`workflows/engine.py` 的租约心跳、`recover_incomplete_runs()`、`resume_run()`、幂等键实践；
  - 无第三方版本变更风险；与本项目数据模型（Workspace、Membership、Action）天然一致。
- 劣势：需自建图表达能力、需自建可视化与调试工具、需要工程纪律。
- 结论：**作为主内核**。

### 16.4 最终推荐架构

**推荐：自研编排内核为主 + LangGraph 作为可选图执行后端**

```
┌─────────────────────────────────────────────────────────┐
│  Orchestrator（自研，唯一控制中心）                       │
│  - Workspace Context 装载                                │
│  - Task 创建与状态机                                     │
│  - Guardrail 单点判定                                    │
│  - Trace 全链路                                          │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Planner（自研接口，可插拔实现）                          │
│  - 默认：确定性规则模板（离线可用）                       │
│  - 可选：LLM 拆解                                        │
│  - 可选：LangGraph 图执行后端（Phase 3 评估）             │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Agent Runtime（自研，基于现有 Workflow Engine 演进）      │
│  - 状态机 / 重试 / 超时 / 恢复 / 租约 / 幂等 / 预算        │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Specialist Agents（自研，8 个冻结 Agent）                │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Tool Layer（自研，MCP 兼容协议）                         │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Action System → Guardrail → Executor → Business API     │
└─────────────────────────────────────────────────────────┘
```

**替换边界（重要）**：Planner 与 Agent Runtime 之间定义为**接口**，因此未来若 LangGraph 被证明更适合图执行，可在不改动 Orchestrator、Guardrail、Action、Tool 的前提下替换 Planner 后端。**禁止**把 LangGraph/CrewAI/AutoGen 直接作为 Orchestrator。

**明确排除**：CrewAI、AutoGen（违反红线 2 与第 6.1 节）。

### 16.5 引入第三方框架的三条准入条件

未来若评估引入任何 Agent 框架，必须同时满足：

1. 不改变「Orchestrator 单点控制」拓扑（不得让框架自行决定 Agent 调用关系）；
2. 不绕过 Guardrail 与 Action 层（框架的输出必须降级为 Action 提案）；
3. 可在不改动数据模型的前提下替换（框架不得成为业务事实的存储方，ADR-F15）。

---

## 17. 与 Workspace 体系的融合方案

### 17.1 强制约束：所有 Agent 必须 Workspace-aware

每次 Agent 运行**必须携带**：

| 字段 | 来源 | 用途 |
|---|---|---|
| `workspace_id` | Workspace Context（服务端） | 数据隔离、审计主体 |
| `workspace_type` | Workspace Context | ORGANIZATION / PERSONAL / FACTORY，决定可用能力 |
| `user_id` | Workspace Context | 发起者身份、权限主体 |
| `permissions` | Membership → Role → Permission | 权限判定 |
| `data_scope` | Membership Data Scope | 数据可见范围 |
| `capability_profile` | Workspace Profile（含来源标记） | 可行方案边界 |
| `business_stage` | 确定性规则计算（ADR-F09） | 推荐策略 |

**禁止**：无上下文 Agent（无 `workspace_id` 的 Agent 调用一律拒绝）。

### 17.2 上下文来源的唯一性

```
Workspace Context Service（backend/app/services/workspace_context.py）
        ↓
Orchestrator 装载（服务端组装）
        ↓
随 Task 传递给 Agent 与 Tool
```

**禁止**：

- Agent 自行解析 `User.tenant_id` 或 `User.role`（沿用 `docs/phase1_interfaces.md` 第 9 节禁令）；
- 信任前端传入的 `role` / `workspace_id` / `budget` / `capability`（ADR-F11）；
- 出现第二套授权实现。

### 17.3 Capability Profile 与 Business Stage 的使用纪律

**Capability Profile（ADR-F08）**：

| 规则 | 说明 |
|---|---|
| 能力来源必须标记 | `USER_DECLARED` / `SYSTEM_OBSERVED` / `MODEL_ESTIMATED` |
| Channel Capability | **只能**由用户声明或真实连接 Store 认定 |
| AI 不得凭空认定 | 不得虚构预算、经验、渠道能力 |
| 模型推断不得覆盖用户声明 | `MODEL_ESTIMATED` 只能作为待确认建议 |

对 Agent 的直接影响：

- Market Agent 推荐类目时必须检查 `capability_profile`，推荐**做得到**的机会；
- Channel Agent 只能推荐已连接或用户声明可接入的渠道；
- Supply Agent 必须尊重用户声明的 Supply Mode。

**Business Stage（ADR-F09）**：

| 阶段 | 对 AI 推荐的约束 |
|---|---|
| `DISCOVERY` | 侧重机会发现与可行性，不推荐重投入 |
| `SETUP` | 侧重基础建设（店铺、类目、Listing） |
| `TESTING` | 侧重小批量验证、控制风险 |
| `OPERATING` | 侧重效率优化 |
| `GROWING` | 侧重扩品与渠道扩张 |
| `OPTIMIZING` | 侧重利润与结构优化 |

**禁止**：由 LLM 自由生成阶段；阶段必须由确定性规则从真实业务事实计算（ADR-F09）。

### 17.4 Business Path 的 AI 职责边界

| AI 可以 | AI 不可以 |
|---|---|
| 生成路径草案 | 绕过权限执行高风险动作 |
| 推荐步骤与顺序 | 跳过合规检查 |
| 标注 Reason / Evidence / Freshness / Risk | 跳过单位经济性验证 |
| 建议 Supply Mode 与 Channel | 替代用户确认 |

**规则**：Business Path 的状态推进（如「用户已确认第 3 步」）必须由用户操作产生，AI 不得代填。

### 17.5 与 Factory Collaborator 的融合

Factory Collaborator（ADR-F05）是**独立于 Workspace Member** 的身份，其 Context 为 `source=FACTORY`、`data_scope=FACTORY_SELF`。

对 Agent 的约束：

- 面向 Factory Collaborator 的 Agent 调用只能使用 `supply:read` / `supply:write` 权限；
- **禁止**向其暴露其他 Workspace 的市场数据、订单数据、财务数据；
- 面向 Factory 的 Agent 输出不得包含买方信息。

### 17.6 与 Platform Identity 的融合

Platform Identity（`superadmin`，ADR-F03 相关）**没有业务 Workspace**。

约束：

- Platform Identity **不得**调用业务 Agent（无 `workspace_id` 即被 17.1 拒绝）；
- 平台级 AI 能力（如全局规则更新）走独立的 Platform 路径，不属本架构的业务 Agent 范围；
- 代客访问（impersonation）时以目标 Workspace 身份运行，并标记 `is_impersonating`，审计动作必须区分。

---

## 18. 后续开发路线

### 18.1 前置依赖（当前状态）

| 依赖 | 状态 | 说明 |
|---|---|---|
| Phase 1 Workspace Identity Migration | **已完成（2026-09-23）** | Revision A/B/C/D/E 已在主库执行，alembic head = `20260924_12`；预检器 12/12 PASS；tenant 0 孤儿数据已清零 |
| Workspace Context Service | **已完成** | `workspace_context.py`，含双读与 legacy fallback |
| Workspace Context API | **已完成** | `/api/me/workspaces`、`/api/me/workspace-context`、`/api/me/workspaces/{id}/switch` |
| Capability Profile | **未实现** | 需 Phase 2 |
| Business Stage 规则 | **未实现** | 需 Phase 2 |
| Business Path | **未实现** | 需 Phase 2 |

**结论：本架构文档已冻结；Phase 1 已完成，Agent Runtime 开发的前置条件已满足（可进入 Phase 2/3 规划）。**

### 18.2 分阶段路线

| 阶段 | 名称 | 交付物 | 前置 |
|---|---|---|---|
| **Phase 1** | Workspace Identity Migration | Membership / Role / Context / 双读 / 前端接入 | — |
| **Phase 2** | Workspace 能力画像与经营路径 | `business_capability_profiles` / `business_stages` 规则 / `business_paths` + steps / Context 扩展 | Phase 1 完成 |
| **Phase 3** | Agent 基础设施 | `ai_actions` 表 / `agent_tasks` 表 / Tool Layer / Guardrail / Trace | Phase 2 完成 |
| **Phase 4** | Agent 迁移与接入 | 8 个冻结 Agent 按本架构重构（去直连数据库、去 P2P、接 Tool 层） | Phase 3 完成 |
| **Phase 5** | Event 与自动化 | 事件层 / 8 类事件接入 / Scheduler 改造为事件源 | Phase 4 完成 |
| **Phase 6** | Memory 与 Knowledge | 五层 Memory / 五类 Knowledge / 检索纪律 | Phase 4 完成 |
| **Phase 7** | 体验收口 | Copilot 界面 / Business Path 呈现 / 审批流 UI | Phase 5、6 完成 |

### 18.3 现有 Agent 代码的迁移策略（重要）

现有代码**不推倒重来**，按以下顺序收敛：

| 步 | 动作 | 影响文件（现有） | 风险 |
|---|---|---|---|
| 1 | 为每个 Agent 补齐 `input_schema` / `output_schema` / `required_permissions` / `risk_level` 声明 | `backend/app/agents/*.py` | 低（纯声明） |
| 2 | 引入 Tool Layer，把 Agent 内的直接 ORM 查询改为 Tool 调用 | `backend/app/agents/*.py` | **中**（需逐点核对查询语义） |
| 3 | 引入 Action 层，把 Agent 内的写操作改为 Action 提案 | `listing.py` 的 `publish`、`pricing.py` 的 `reprice_batch` 等 | **高**（涉及业务写入路径） |
| 4 | 引入 Agent Runtime，把 Orchestrator 的同步直调改为 Task 派发 | `orchestrator.py` | **中** |
| 5 | 把 `BaseAgent` 的 `SessionLocal()` 持有改为 Runtime 注入 | `base.py` | **高**（影响全部 Agent） |
| 6 | 补齐 Trace（`trace_id` / `task_id` / `parent_trace_id` / `steps[]`） | `base.py` 的 `_log`、`AiLog` 模型 | 中 |

**顺序要求**：必须按 1→6 顺序，禁止跳步。每步完成后必须保持全部回归测试通过。

### 18.3.1 迁移进度（活记录，每次推进必须同步）

| 步 | 状态 | 证据 / 剩余工作 |
|---|---|---|
| 1 | ✅ **完成**（D35） | 8 条冻结契约落在 `backend/app/agents/contracts.py`；`SupportAgent` 显式未登记（DEBT-34） |
| 2 | ✅ **Agent 侧读取迁移完成**（D37 ~ D46；D52 补只读聚合） | Tool 共 11 个、44 个方法（§10.4.1）。9/9 个 Agent 文件的读取点经 Tool；历史 ORM query/get 棘轮 21→8 的剩余均属第 3 步写路径。D52 将 DiscoveryAgent._rule_scores 的 get_performance 隐性缓存写改为 product.calculate_performance，只读真实订单即时聚合，保留真实来源过滤和新品中性分；Tool 审计及真库全方法覆盖保持。 |
| 3 | 🔶 **进行中**（D47～D56） | 广告预算/草稿、Listing 草稿/优化/发布、商品安全标准化及内置趋势已接 Action；定价、评分、复核报告由可信产物服务保存。D55 合规报告/来源与受限风险 Action 原子提交，错误/high 阻断，原清单防恢复换范围，旧 low 不覆盖新 high；规则同步已迁出复核 Agent。D56 趋势日种子复算、不覆盖真实来源，全部入口可信调度；Schedule 持久化真实身份，历史空绑定显式阻断。发布须独立人工批准与执行，广告仅本地 draft。ORM query/get 棘轮为 3（不代表全部写入数）；供应评分快照/预测/私域报价、客服/知识学习、默认知识向量缓存、告警和基础审计仍待迁移。**第 3 步未完成；第 4～6 步未开始**。 |
| 4 | ⏳ 未开始 | Orchestrator 仍同步直调 |
| 5 | ⏳ 未开始 | `BaseAgent.SessionLocal()` 仍自持会话；完成后才能关闭 DEBT-35 |
| 6 | ⏳ 未开始 | `trace_id` / `task_id` / `parent_trace_id` / `steps[]` 未补 |

最新完成批次（D56，2026-10-01，代码及隔离验收完成）：趋势扫描迁为
`REFRESH_BUILTIN_TRENDS` Action，HTTP/聊天/Workflow/调度统一可信入口；
Schedule 增加真实身份绑定，可回滚迁移计划为 `20261001_19`。历史无身份任务
不得自动绑定管理员，须重新启用；主库未升级。正式结果及剩余风险以最新
子代理索引为准，不将本批完成或隔离验收等同主库部署或第 3 步完成。

> **为什么第 2 步要拆成前后半**：§18.3 的每一步都要求「完成后全部回归测试通过」。
> 在第二批 Tool 清单落地前强行改 Agent，只能把 ORM 查询换成「无对应 Tool 的
> 临时调用」，等于用另一种形式继续绕开边界——那不是推进，是换了个地方欠债。

### 18.4 禁止事项（开发期）

| 禁止 | 原因 |
|---|---|
| 在 Phase 1 完成前开发 Agent Runtime | 依赖未就绪，会产生返工 |
| 新建未登记的 Agent | 违反红线 1 |
| 让 Agent 直接持有 Session 写业务表 | 违反红线 3 |
| 引入 CrewAI / AutoGen | 违反红线 2 与第 6.1 节 |
| 用聊天文本代替结构化输出 | 违反红线 5 |
| 跳过 Guardrail 直接执行 | 违反红线 4 |

---

## 19. 验收标准

本架构在后续阶段的验收依据：

| # | 验收项 | 判定方法 |
|---|---|---|
| 1 | 无 P2P 调用 | 静态检查：Agent 模块之间无相互 import；运行时检查：每次 Agent 调用都有 Orchestrator 派发的 `task_id` |
| 2 | 无直连数据库 | 静态检查：Agent 模块无 ORM 写操作；运行时检查：所有业务读写都有 Tool 调用记录 |
| 3 | 无绕过权限的动作 | 检查：所有业务数据变更都有对应 `ai_actions` 记录且状态合法 |
| 4 | 全部 Workspace-aware | 检查：所有 Agent Task 都有非空 `workspace_id` |
| 5 | 全部可追溯 | 检查：任一 Action 可反查到完整 Trace（含触发原因、读取数据、工具调用） |
| 6 | 离线可用 | 断开 LLM 后所有 Agent 仍能以 `rule` 模式产出结构化结果 |
| 7 | 降级可见 | 所有 `mode=rule` 的调用在 Trace 与用户输出中显式标注 |
| 8 | 无 PII 泄漏 | 审计：Trace / Memory / AiLog 中无 Token、凭证、买家 PII |
| 9 | 高风险动作受控 | 检查：HIGH 风险 Action 无 `AUTO_SAFE` 记录 |
| 10 | 状态机合法 | 检查：Task 与 Action 状态迁移全部符合第 8.2 / 9.5 节 |

---

## 20. 变更控制

| 变更类型 | 需要什么 |
|---|---|
| 新增/删除 Agent | 架构评审 + 更新第 7 节清单 |
| 新增 `action_type` | 声明风险等级 / 权限 / 审批要求 / 幂等规则 / 回滚方式 |
| 修改状态机 | 架构评审（影响面大） |
| 修改 Guardrail 规则 | 安全评审 + 记录阈值依据 |
| 引入第三方框架 | 满足第 16.5 节三条准入条件 |
| 放宽红线 | **不允许**；如确需，必须先修订本文件的红线章节并重新冻结 |

---

## 附录 A：术语表

| 术语 | 含义 |
|---|---|
| Orchestrator | AI 系统唯一控制中心 |
| Planner | 任务拆解器，产出 Task Graph |
| Specialist Agent | 领域能力 Agent（8 个冻结） |
| Agent Runtime | 任务执行引擎（状态机/重试/恢复/租约） |
| Task Graph | 有向无环的任务依赖图 |
| AI Action | 影响业务数据的结构化动作提案 |
| Guardrail | 权限/范围/风险/审批四道闸 |
| Tool Layer | Agent 访问业务能力的唯一入口 |
| Agent Trace | 全链路执行记录 |
| Capability Profile | Workspace 能力画像（含来源标记） |
| Business Stage | 确定性规则计算的经营阶段 |
| Business Path | 结构化、版本化经营计划 |
| Workspace Context | 服务端组装的唯一业务上下文 |

## 附录 B：与现有代码资产的对应关系

| 架构组件 | 现有资产 | 处置 |
|---|---|---|
| Orchestrator | `backend/app/agents/orchestrator.py` | 保留，Phase 4 改造为 Task 派发 |
| Specialist Agents | `backend/app/agents/*.py`（12 个） | 按 8 个冻结 Agent 归并重构 |
| Agent Runtime | `backend/app/workflows/engine.py`（租约/恢复/幂等） | 复用机制，扩展到 Task 粒度 |
| Tool Layer | 无（Agent 直连 ORM） | **新建** |
| Action System | 无 | **新建** |
| Guardrail | `auth.py` 的 `require_*`（路由层） | 保留，AI 侧新增独立 Guardrail |
| Knowledge | `ai/knowledge.py` + `services/platform_rules.py` | 统一为 Knowledge Layer |
| Memory | 无（仅 AiLog） | **新建** |
| Observability | `AiLog` 模型 + `ai.py` 的 `/ai/logs` | 扩展为 Trace 结构 |
| Event | `services/scheduler.py` + `Schedule` 表 | 改造为事件源之一 |
| Workspace Context | `services/workspace_context.py` | 复用，Phase 2 扩展字段 |

---

## 冻结签署

| 项目 | 内容 |
|---|---|
| 文档版本 | V1.0 |
| 冻结日期 | 2026-09-23 |
| 冻结范围 | AI Agent Operating System 全部分层、拓扑、清单、状态机、Action 模型、Tool 契约、Guardrail 规则、技术选型 |
| 生效条件 | 立即生效；后续 AI 开发必须遵循 |
| 修订条件 | 仅可通过第 20 节变更控制流程 |
| 与 Phase 1 的关系 | 本文件为**设计冻结**，不产生编码任务；Agent Runtime 开发须待 Phase 1 Workspace 完成 |
