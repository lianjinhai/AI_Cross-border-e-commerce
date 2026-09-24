# AI 跨境电商经营平台最终架构评估

> 架构冻结版本：V3.0  
> 评估日期：2026-09-22  
> 状态：Phase 0 架构冻结完成，尚未进入 Phase 1 编码  
> 事实依据：当前后端、前端、数据库模型、迁移、测试与部署配置。代码与历史文档冲突时，以代码为准。

## 0. 执行结论

当前系统不需要重建业务底座。现有 `Tenant` 已经承担商品、供应商、店铺、Listing、订单、财务、Agent 和 Workflow 的数据边界，可以冻结为：

`Tenant = Workspace Boundary`

最终产品架构冻结为：

```text
Platform
└── User（自然人身份）
    └── WorkspaceMembership
        └── Workspace / Tenant Boundary
            ├── WorkspaceProfile
            ├── CapabilityProfile
            ├── BusinessStage
            ├── BusinessPath / Steps
            ├── Supply Domain
            ├── Product Domain
            ├── Sales Domain / Store
            ├── Order / Fulfillment / After-sales
            ├── Finance / Settlement / Profit
            ├── AI Operations / AI Action
            └── Workflow / Audit
```

这一架构能够在不搬迁现有经营数据的前提下支持：

- 一名自然人拥有多个 Personal 或 Organization Workspace；
- Personal 平滑升级为 Organization，历史数据和 Tenant ID 不变；
- Organization 使用 Membership、Role、Permission 和 Data Scope；
- 外部工厂协作者只访问其 Factory 资源，不成为完整 Workspace Member；
- 新手使用 Guided Experience，成熟经营者使用 Professional Experience；
- AI 基于 Workspace 的真实能力、经营阶段和经营事实提供结构化行动建议。

当前不能直接进入前端 Workspace Switcher 开发。必须先解决身份迁移、Workspace 配置隔离和 Supply/Sales 订单域隔离。

---

## 1. 最终冻结决策

下列决策从本报告生效，后续开发不得自行改变；如确需变化，必须形成架构决策记录、数据迁移影响分析和回滚方案。

### ADR-F01：Tenant 保留为 Workspace 数据边界

- 保留 `tenants` 表、主键和现有业务表的 `tenant_id`；
- 产品、Service 和新 API 使用 Workspace 术语；
- 不批量重命名表和外键；
- `workspace_id` 在新领域代码中等价于现有 Tenant ID。

### ADR-F02：User 只代表自然人身份

- User 不代表公司、经营空间、角色或权限；
- `User.tenant_id`、`User.role` 只作为兼容期字段；
- 最终授权不得直接依据这两个字段；
- Platform Super Admin 是平台身份，不使用虚构 Workspace 0。

### ADR-F03：所有 Workspace 授权通过 Membership

最终授权链固定为：

`User → WorkspaceMembership → Role → Permission → Data Scope`

- Membership 表达用户属于哪个 Workspace；
- Role 表达该 Workspace 中的职责；
- Permission 表达允许的动作；
- Data Scope 表达可操作的 Store、Factory 或其他资源范围；
- 前端导航不构成授权，后端始终强校验。

### ADR-F04：Personal 与 Organization 共用业务底座

- Workspace Type 只有 `PERSONAL`、`ORGANIZATION`；
- Personal 默认一个 OWNER，不展示复杂 RBAC；
- Organization 支持成员、Role Template、Custom Role、Permission 和 Data Scope；
- Personal 升级 Organization 只更新 Workspace 类型并增加成员，不迁移 Product、Store、Order、Listing 或财务数据。

### ADR-F05：Factory Collaborator 独立于 Workspace Member

- Workspace 自有工厂属于 Workspace 的 Supply Source；
- 外部合作工厂通过 Factory Collaborator 关系访问；
- Factory Collaborator 只可访问绑定 Factory 的 SKU、报价、库存、产能、需求、订单和履约；
- 不得访问整个 Workspace 的财务、其他供应商、全部 Store 或成员信息。

### ADR-F06：Supply 与 Sales 是两个独立领域

Supply Source 固定为：

- `PRIVATE_FACTORY`；
- `1688`；
- `MANUAL_SUPPLIER`。

Sales Channel 是商品销售平台；Store 是实际经营边界。

- 1688 永远是 Supply，不是 Sales Channel；
- source Shop 不得进入销售订单同步；
- 采购/分销订单不得写入销售 Order；
- GMV、销售利润、广告和结算只使用 Sales Domain 的事实数据。

### ADR-F07：Store 是销售经营边界

关系固定为：

`Workspace → Store → Platform`

- Order、Advertisement、Settlement 优先直接关联 Store；
- Listing 继续作为 Workspace/Platform 的内容母稿；
- Store 上的实际发布由发布实例记录承载，当前可复用 `PlatformPublishAttempt.shop_id`；
- 不为每个 Store 复制一份 Listing 母稿；
- 历史 `shop_id=NULL` 数据保留为 `UNASSIGNED`，不得伪造归属。

### ADR-F08：Capability Profile 属于 Workspace Context

- Capability Profile 描述当前 Workspace 能做什么；
- 能力来源必须标记为 `USER_DECLARED`、`SYSTEM_OBSERVED` 或 `MODEL_ESTIMATED`；
- Channel Capability 只能由用户声明或真实连接 Store 认定；
- AI 不得凭空认定预算、经验或能力；
- MODEL_ESTIMATED 不得覆盖用户声明，只能作为待确认建议。

### ADR-F09：Business Stage 使用确定性、版本化规则

固定状态：

- `DISCOVERY`；
- `SETUP`；
- `TESTING`；
- `OPERATING`；
- `GROWING`；
- `OPTIMIZING`。

阶段由真实业务事实计算，不根据注册时间，也不由 LLM 自由生成。规则必须版本化并保留计算依据。

### ADR-F10：Business Path 是结构化、版本化经营计划

Business Path 必须包含：

- 当前阶段；
- 优势与缺口；
- 有序步骤；
- 推荐 Supply Mode 和 Channel；
- Reason、Evidence、Freshness、Risk；
- 状态和用户确认记录。

AI 可以生成路径草案，但不能绕过权限、合规、单位经济性和人工审批直接执行高风险动作。

### ADR-F11：AI 是 Workspace-aware Business Copilot

- AI 输入必须来自服务端组装的 Workspace Context；
- AI 输出统一为建议、Business Path 或 AI Action；
- AI Action 至少包含 target、reason、evidence、expected impact、risk、required permission、execution mode、status 和 outcome；
- AI 不直接信任前端传入的 role、budget、capability 或 workspace ID；
- 财务和经营指标必须调用统一 Metrics / Unit Economics Service。

### ADR-F12：Experience Mode 不是 Role

- 模式固定为 `GUIDED`、`PROFESSIONAL`；
- WorkspaceProfile 保存默认模式；
- Membership 可保存个人偏好覆盖；
- 最终有效模式为“成员偏好，否则 Workspace 默认”；
- 两种体验使用相同数据库、API 和业务页面。

### ADR-F13：Workspace Context 是前端唯一业务上下文

前端不得继续把 localStorage 中的 `user.role` 当作最终权限来源。

统一读取：

`GET /api/me/workspace-context`

响应由服务端生成，至少包含 User、Workspace、Membership、Role、Permissions、Data Scopes、Capability、Stage、Experience Mode、Subscription、Supply Sources、Stores、Business Path、Pending Tasks、Navigation 和 Default Route。

localStorage 只可保存短期会话凭证和非敏感 UI 偏好，不保存可被信任的授权事实。

### ADR-F14：Subscription 与 Workspace Type 分离

- PERSONAL / ORGANIZATION 是经营空间类型；
- FREE / BASIC / PRO / ENTERPRISE 是订阅概念；
- 当前 `Tenant.plan` 在兼容期保留，但不得被用作 Workspace Type；
- 本阶段不实现复杂计费。

### ADR-F15：生产事实以数据库为准

- PostgreSQL 是 Integration、Staging、Production 的业务事实库；
- Redis 只用于锁、限流、缓存、Token cache 和任务协调；
- 订单、Listing、采购、退款、结算和 Workflow 状态不能只存在 Redis；
- Workflow 定义与业务步骤保留，执行方式最终迁到独立 Worker；
- 外部副作用使用数据库持久化幂等、UNCERTAIN 和 Read-back 恢复。

---

## 2. 当前架构

### 2.1 应用结构

当前是 FastAPI + SQLAlchemy 单体后端和 Vue 3 + Element Plus + ECharts 前端。

- 后端 Router 统一挂在 `/api`；
- ORM 模型主要集中在 `backend/app/models.py`；
- 业务能力由 Router、Agent、Service、Platform Adapter 和 Workflow Engine 组成；
- 前端为单一 Layout 下的懒加载业务页面；
- 当前部署镜像同时提供 API 和前端静态资源。

### 2.2 身份与租户

当前：

- `Tenant` 包含 name、plan、status 和许可信息；
- `User.tenant_id` 为非空 FK；
- `User.role` 是单一硬编码角色；
- JWT 携带 `uid`、`tid`、`role`、`imp`、`ver`；
- 普通用户没有 Membership 或 Workspace switch；
- superadmin 可使用 tenant override 代管 Tenant；
- superadmin 种子使用 `tenant_id=0`。

因此当前模型实际是“一名 User 固定属于一个 Tenant”，还不是冻结目标中的自然人多 Workspace 模型。

### 2.3 权限

当前后端通过：

- `require_write`；
- `require_admin`；
- `require_compliance_approver`；
- Router 中的 `user.tenant_id` 过滤；
- Factory Portal 的 tenant + supplier 过滤。

前端通过 `permissions.js` 中的固定角色数组和路径白名单控制入口。

当前没有通用 Membership、Role、Permission、Custom Role、Store Scope 或 Data Scope 数据模型。

### 2.4 Factory 与 Supplier

现有能力较完整：

- Supplier 支持 factory/trader/platform 等类型；
- Supplier Catalog 支持工厂自维护 SKU；
- Supplier Evidence、Offer、Score 和 Opportunity Match 已存在；
- SupplierPortalMember 将工厂账号绑定到一个 Supplier；
- Factory Portal 路由按 tenant + supplier 双重过滤。

缺口：SupplierPortalMember 的 `user_id` 全局唯一，无法支持同一自然人协作多个 Factory；Portal 仍依赖全局 supplier role。

### 2.5 Supply Domain

当前三类供给已经有实现基础：

- 私域工厂：Supplier + SupplierCatalogProduct；
- 1688：`Shop.role=source` + Adapter + 代发；
- 手工供应商：Supplier。

但缺少统一 Supply Source 读模型，且 source Shop 仍能调用销售订单同步。

### 2.6 Sales Channel 与 Store

`Shop` 当前同时承载 source/sales 两种角色。

- PlatformPublishAttempt 已关联 shop_id；
- Order 和 PlatformSettlementRecord 有 nullable shop_id；
- Listing 只有 platform，没有 shop_id；
- AdCampaign 没有 shop_id。

因此 Store 已是部分销售边界，但广告和部分结算归属仍不完整。

### 2.7 Product、Opportunity 与 Listing

- Product 带 tenant_id、来源平台和来源 URL；
- MarketTrend 表达关键词趋势；
- ProductScore 提供 demand、competition、profit、risk、total 和 reasons；
- Factory Opportunity Match 支持供给匹配；
- Listing、合规检查、独立复核、发布尝试和幂等基础已存在。

当前没有 Workspace User Fit；Market、Supply 和 Product source 的部分字段语义仍混杂。

### 2.8 Order、履约与 Finance

系统已有销售订单、订单行、费用、采购、1688 代发、退款、结算、平台结算、汇率和商业指标服务。

需要注意：source Shop 进入通用订单同步时可能把采购/分销数据写入销售 Order，破坏 GMV 和利润可信度。

### 2.9 AI Agent

当前已有 Discovery、Product、Supplier、Factory Opportunity、Pricing、Ads、Listing、Compliance、Listing Review、Support 和 Orchestrator Agent。

Agent 普遍以 tenant_id 隔离，部分输出已有 evidence 和 risk。主要不足：

- 没有统一 Workspace Context；
- Orchestrator 仍是关键词路由式聊天入口；
- 没有统一 AI Action 持久化模型；
- 部分经营汇总直接查询旧 Order 字段，没有全部走统一指标服务；
- 无 Capability、Stage、Path 和 Data Scope 上下文。

### 2.10 Workflow

现有 Workflow 已具备定义、运行、步骤、Context、checkpoint、lease、heartbeat 和恢复基础，应保留。

当前执行仍由 FastAPI 进程内 daemon thread 启动；这不满足独立 Worker 和进程故障恢复的生产要求。

### 2.11 前端

当前前端：

- 只有 Login，没有 Register 或 Onboarding；
- 登录后固定进入 `/dashboard`；
- localStorage 保存 token、user 和 impersonation 状态；
- Layout 硬编码大量菜单；
- Dashboard 是统一专业驾驶舱；
- AI Assistant 只发送 message；
- Factory Portal 已形成独立受限界面；
- Shops 页面已经把货源店和销售店分栏展示。

当前不存在 Workspace Switcher、Capability Profile、Business Path、Guided/Professional Mode 或 workspace-context 状态层。

### 2.12 数据库与部署

当前默认仍是 SQLite：

- 应用启动调用 `create_all` 并执行 SQLite 轻量补列；
- Docker Compose 默认使用 SQLite volume；
- 可选 profile 是 MySQL，不是冻结目标 PostgreSQL；
- Alembic 已存在，但基线迁移使用动态 metadata；
- Compose 没有 PostgreSQL、Redis、独立 Worker 和独立 Frontend 服务。

### 2.13 测试

已有后端 API、安全、商业数据和平台 Adapter 测试；前端有 Vitest 角色路由测试。

尚缺：

- Workspace Membership 和切换测试；
- PostgreSQL migration/integration 测试；
- Playwright A-G 真实浏览器流程；
- Store Scope、Factory Collaborator 和跨 Workspace 缓存隔离测试；
- 独立 Worker 故障恢复测试。

---

## 3. 与最终架构的差距

| 领域 | 当前状态 | 冻结目标 | 差距级别 |
|---|---|---|---|
| User | tenant_id + role 绑定 User | 纯自然人身份 | P0 |
| Workspace | Tenant 仅企业租户语义 | PERSONAL/ORGANIZATION 经营空间 | P0 |
| Membership | 不存在 | 多 Workspace 关系与授权入口 | P0 |
| Permission | 固定角色守卫 | Role→Permission→Data Scope | P0 |
| Workspace Context | 不存在 | 服务端统一上下文 | P0 |
| Setting | 全局 key | Platform-global / Workspace-scoped 分层 | P0 |
| Supply/Sales | source/sales 部分区分 | 两个严格隔离领域 | P0 |
| Super Admin | tenant_id=0 | 平台身份、无虚构 Workspace | P1 |
| User 删除 | 物理删除 User | 移除 Membership/停用身份 | P1 |
| Capability Profile | 不存在 | 有来源的 Workspace 能力画像 | P1 |
| Business Stage | 不存在 | 真实状态规则计算 | P1 |
| Business Path | 不存在 | 版本化结构路径 | P1 |
| Store 边界 | 订单/发布/结算部分覆盖 | 销售事实优先归 Store | P1 |
| Factory Collaborator | 单 Factory 绑定 | 多关系但严格资源范围 | P1 |
| AI Copilot | tenant-aware 聊天编排 | workspace-aware AI Action | P1 |
| Experience | 单一专业页面 | Guided / Professional | P1 |
| Dashboard | 固定 KPI | 按 Context 自适应 | P2 |
| Opportunity | 单一商业评分 | Commercial Value + User Fit | P2 |
| Workflow Runtime | 进程内线程 | Durable Queue + Worker | 生产 P0 |
| 数据库 | SQLite 默认/MySQL profile | PostgreSQL 生产基线 | 生产 P0 |
| E2E | 无 Playwright | A-G + 权限/隔离验证 | 生产 P0 |

---

## 4. 可直接复用部分

### 4.1 数据与领域

- Tenant 主键和所有既有 tenant_id；
- Product、MarketTrend、ProductScore；
- Supplier、Supplier Catalog、Evidence、Offer、Score；
- Shop 及其 source/sales 标记；
- Listing 内容母稿、Compliance、Review、Publish Attempt；
- Order、OrderLine、OrderFee、Purchase、Refund、Settlement、FX；
- Workflow Template/Run/Step、checkpoint、lease、heartbeat；
- AI Log、TenantAccessLog；
- 商业指标、预测和机会归因服务。

### 4.2 安全与业务规则

- 现有 tenant 过滤模式；
- `require_*` 守卫的业务语义，作为兼容适配层；
- Factory Portal 的 tenant + supplier 双重校验；
- superadmin 代管审计概念；
- Listing 提交人与审批人分离、合规和发布门禁。

### 4.3 前端

- 现有 Product、Factory、Supplier、Shops、Listing、Order、Finance、Workflow 页面；
- Dashboard 的专业指标和图表；
- Factory Portal 独立体验；
- Shops 的货源/销售分栏；
- 现有业务 URL 和路由懒加载。

### 4.4 明确不重写

- 不重写 Workflow 定义和业务步骤；
- 不重写平台 Adapter 体系；
- 不重写统一财务指标服务；
- 不创建 PersonalProduct/OrganizationProduct 等重复页面；
- 不将 Tenant 全库改名为 Workspace；
- 不把 Listing 强制改成一店一稿。

---

## 5. 必须修改部分

### P0：Phase 1 前置

1. 新增 WorkspaceMembership，并把最终授权入口迁到 Membership；
2. `User.tenant_id` 改为兼容字段，允许平台身份不绑定 Workspace；
3. 处理 superadmin `tenant_id=0`；
4. 将用户删除改成 Membership 移除或身份停用优先；
5. 将 Setting 分成 platform-global 和 workspace-scoped；
6. 禁止 source Shop 调用销售订单同步；
7. 建立服务端 active Workspace 校验和 Context；
8. 增加跨 Workspace、角色、Store Scope 和 Factory Scope 的强制测试。

### P1：产品核心

1. WorkspaceProfile 与 Workspace Type；
2. Role、Permission、Data Scope 兼容模型；
3. Capability Profile 及来源；
4. Business Stage 规则引擎；
5. Business Path 与步骤；
6. Workspace API 和 Switch；
7. Workspace Context；
8. Onboarding、Switcher、Experience Mode；
9. AI Action 与 Workspace-aware Copilot；
10. Advertisement 和 Settlement 的 Store 归属完善。

### P2：体验与经营优化

1. 自适应 Dashboard；
2. 一级导航治理；
3. Commercial Value + User Fit；
4. Factory Collaborator 的需求、订单和履约入口；
5. 细化 Organization Custom Role 和资源范围管理。

---

## 6. 最终数据模型

以下是冻结后的目标模型。实施允许分阶段，但不得改变关系方向。

### 6.1 Workspace 核心

#### tenants（保留）

新增：

- `workspace_type`: PERSONAL / ORGANIZATION；

保留：id、name、status、plan、许可和现有业务关系。

#### workspace_profiles

- tenant_id/workspace_id；
- business_stage；
- default_experience_mode；
- onboarding_status；
- target_markets；
- default_currency；
- timezone；
- stage_rule_version；
- stage_evidence；
- created_at / updated_at。

#### workspace_memberships

- user_id；
- tenant_id/workspace_id；
- role_id 或兼容 role_code；
- status；
- experience_mode_preference；
- membership_version；
- invited_by / joined_at；
- created_at / updated_at；
- 唯一约束 `(user_id, tenant_id)`。

#### workspace_roles

- tenant_id nullable：NULL 表示系统模板；
- code / name；
- role_type：TEMPLATE / CUSTOM；
- permissions；
- status；
- created_at / updated_at。

#### membership_data_scopes

- membership_id；
- resource_type：WORKSPACE / STORE / FACTORY 等；
- resource_id nullable；
- access_level；
- created_at。

首版可以保留权限 JSONB，但高频授权条件和 resource scope 必须结构化并可索引。

### 6.2 Capability 与 Path

#### business_capability_profiles

- workspace_id；
- supply_capabilities；
- channel_capabilities；
- operation_capabilities；
- goals；
- budget_range；
- available_time；
- team_size；
- target_markets；
- preferred_channels；
- version / updated_at。

每个能力项必须包含 value、source、observed_at/declared_at 和 confidence rule reference；预算不得进入通用列表响应。

#### business_paths

- workspace_id；
- version；
- stage；
- strengths；
- gaps；
- recommended_supply_mode；
- recommended_channel；
- risks；
- status：DRAFT / CONFIRMED / ACTIVE / COMPLETED / SUPERSEDED；
- created_by / confirmed_by；
- created_at / confirmed_at。

#### business_path_steps

- path_id；
- sequence；
- step_type；
- status；
- target_entity_type / target_entity_id；
- reason；
- evidence；
- required_permission；
- completed_at。

### 6.3 AI Operations

#### ai_actions

- workspace_id；
- target_type / target_id；
- action_type；
- reason；
- evidence；
- expected_impact；
- risk_level；
- required_permission；
- execution_mode：OBSERVE / RECOMMEND / APPROVAL_REQUIRED / AUTO_SAFE；
- status；
- requested_by / approved_by / executed_by；
- outcome；
- idempotency_key；
- created_at / updated_at。

### 6.4 配置

现有 Setting 不再作为所有租户共享的唯一 key 空间。冻结为两类：

- PlatformSetting：平台级非租户配置和平台应用元数据；
- WorkspaceSetting/Secret Reference：经营空间费率、模型偏好、Workspace Token 引用等。

敏感明文凭证不得进入普通 JSON 或日志。

---

## 7. Workspace Context 契约

### 7.1 API

```text
GET  /api/me/workspaces
POST /api/workspaces
GET  /api/workspaces/{id}
PATCH /api/workspaces/{id}
POST /api/workspaces/{id}/switch
GET  /api/me/workspace-context
GET  /api/workspaces/{id}/profile
PUT  /api/workspaces/{id}/profile
GET  /api/workspaces/{id}/business-path
POST /api/workspaces/{id}/business-path/generate
```

为避免破坏现有 `/api` 路由，本阶段不强制整体迁移到 `/api/v1`；未来版本化使用兼容别名和弃用周期。

### 7.2 Context 响应

```json
{
  "user": {},
  "workspace": {},
  "membership": {},
  "role": {},
  "permissions": [],
  "data_scopes": [],
  "capability_profile": {},
  "business_stage": "SETUP",
  "experience_mode": "GUIDED",
  "subscription": {},
  "connected_supply_sources": [],
  "connected_stores": [],
  "business_path": {},
  "pending_tasks": [],
  "navigation": [],
  "default_route": "/dashboard",
  "context_version": 1
}
```

### 7.3 切换规则

- 客户端提交目标 Workspace ID；
- 服务端验证 active Membership；
- 服务端生成新的 active workspace context/token；
- Token 兼容保留 `tid`，新增 membership ID/version；
- 切换后前端取消旧请求、清除 Workspace 缓存并重新读取 Context；
- 代管状态与普通 Workspace 切换使用不同 claim、不同 UI 标识和不同审计动作；
- 客户端传入的 role、permission 和 navigation 一律不可信。

---

## 8. Migration 方案

采用 Expand → Backfill → Dual Read → Switch → Contract，禁止一次性替换。

### M0：迁移前审计

只读检查：

- User 与 Tenant 的有效关系；
- superadmin 0 值；
- 跨 tenant 外键/业务引用；
- SupplierPortalMember 孤儿和重复；
- Shop.role 与 1688 历史记录；
- Order/Settlement 的空 shop_id；
- Setting key 的平台级/Workspace 级归属；
- 物理删除 User 的历史引用风险。

失败时只报告，不自动猜测或修复归属。

### M1：Expand

- Tenant additive 增加 workspace_type；
- 新增 WorkspaceProfile、WorkspaceMembership、Role/Data Scope 基础表；
- User.tenant_id 改 nullable，但暂不删除；
- 新增显式 Alembic revision 和 downgrade；
- 现有 Tenant 默认回填 ORGANIZATION；
- 新注册用户才创建 PERSONAL。

### M2：Backfill

- 非 supplier 普通用户回填 Membership；
- admin 映射为 OWNER/兼容 ADMIN，operator 映射 OPERATOR，viewer 映射 READ_ONLY；
- compliance_approver 映射对应权限模板；
- supplier 继续走 Factory Collaborator，不自动获得完整 Membership；
- superadmin `tenant_id=0` 迁为 NULL 平台身份；
- 记录回填批次、异常和数量。

### M3：Dual Read / Dual Write

- 登录和授权优先读取 Membership；
- 无 Membership 的旧账号回退 User.tenant_id/role；
- 成员变更同时维护兼容字段，但只把 Membership 作为新事实来源；
- `/auth/users` 保持兼容，内部逐步改成成员管理；
- 禁止新业务直接读取 `User.role` 作最终授权。

### M4：Workspace Context 与切换

- 上线 `/me/workspaces`、switch 和 workspace-context；
- 前端 Context 状态层先上线，旧 role policy 作为受控 fallback；
- Switcher 通过 feature flag 灰度；
- 验证两个 Workspace 并发请求、缓存和 token 失效。

### M5：配置和领域隔离

- 将 Setting 拆为 platform-global/workspace-scoped；
- 对既有 key 做人工确认或明确映射；
- source Shop 禁止销售订单同步；
- 1688 采购事实迁到 Purchase Domain；
- 不把历史 source Order 静默当作销售订单，需标记并对账。

### M6：Contract

只有满足以下条件后才允许停止旧字段写入：

- 所有有效用户都有正确 Membership 或平台身份；
- API、Worker、Agent 和前端不再依赖 User.role/tenant_id；
- Workspace 切换和权限 E2E 全部通过；
- 至少经过一个稳定发布周期；
- 已验证 downgrade/forward-fix 路径。

旧列可以长期保留为 deprecated，不以“数据库整洁”为理由强制删除。

### 回滚原则

- 新表/列均为 additive；
- 迁移批次可追踪；
- 旧认证路径在双读期可恢复；
- workspace_type 回滚不删除业务数据或 Membership；
- 配置迁移在旧路径关闭前保留受控双读；
- 不在同一迁移中补齐全库 FK、强制 shop_id 非空或批量改字段语义。

---

## 9. 实施顺序

严格按以下 Phase 执行，不跨阶段抢做体验层。

### Phase 0：架构冻结

状态：DONE。

- 本报告作为冻结基线；
- 后续变更必须回答兼容、Migration、历史数据、权限和测试影响。

### Phase 1：身份体系

1. 迁移前数据审计和测试；
2. Workspace Type、Profile、Membership；
3. Role/Permission/Data Scope 兼容底座；
4. superadmin 平台身份；
5. Setting 隔离与 source/sales P0 修复；
6. Workspace API、Switch、Context；
7. 双读和回滚验证。

进入条件：显式 migration 经 SQLite 兼容验证和 PostgreSQL migration 验证。

### Phase 2：经营画像

1. Capability Profile；
2. Business Stage 规则；
3. Business Path 与 Steps；
4. 数据来源和 Evidence；
5. 新手、有工厂、已有 Store、有供应链四类路径测试。

### Phase 3：体验体系

1. Register/Onboarding；
2. Workspace Switcher；
3. Guided/Professional；
4. 自适应 Dashboard；
5. 服务端 Navigation；
6. 保留现有业务页面和 URL。

### Phase 4：业务隔离

1. Supply Source 聚合；
2. Sales Channel/Store 读模型；
3. 广告、结算 Store 归属；
4. 历史 unassigned 数据治理；
5. Factory Collaborator 多关系与严格 Scope。

P0 的 source/sales 订单阻断修复在 Phase 1 完成；Phase 4 负责完整领域治理。

### Phase 5：AI 经营

1. Workspace Context 注入；
2. AI Action；
3. Guardrail 与审批；
4. Commercial Value + User Fit；
5. 统一 Metrics/Unit Economics；
6. Action Outcome 回写。

### Phase 6：全面测试与生产门禁

1. A-G Playwright；
2. PostgreSQL integration；
3. Migration upgrade/downgrade；
4. Membership/Permission/Data Scope；
5. Worker 故障恢复；
6. 切换并发和缓存隔离；
7. Personal → Organization 历史数据保持；
8. Supply/Sales 财务口径隔离。

---

## 10. 风险登记

| 风险 | 等级 | 当前证据 | 控制措施 |
|---|---|---|---|
| Workspace 凭证串用 | P0 | Setting 是全局主键 | 配置作用域拆分、密钥引用、跨空间测试 |
| 1688 污染 GMV | P0 | source Shop 可调用销售同步 | 路由和 Service 双重角色校验 |
| 非法 Workspace 切换 | P0 | 无 Membership，前端仅 localStorage | 服务端 Membership 校验和新 Context |
| 权限回归 | P0 | role 硬编码在前后端 | 双读、权限矩阵、拒绝优先 |
| PostgreSQL 迁移失败 | P0 | superadmin tenant_id=0、动态基线 | 显式 revision、数据预检、PG 集成测试 |
| 进程故障丢任务 | P0 | Workflow 使用 daemon thread | 独立 Worker、持久队列、租约恢复 |
| 历史 User 物理删除 | P1 | `/auth/users/{id}` 调用 db.delete | 改 Membership remove/disable |
| Store 归属不完整 | P1 | AdCampaign 无 shop_id，部分事实可空 | nullable 增量字段、回填和 UNASSIGNED |
| Factory 越权 | P1 | 现有 Portal 安全但依赖 supplier role | 保留资源校验，迁到 collaborator scope |
| Capability 被 AI 猜测 | P1 | 当前无来源模型 | 来源枚举、确认流程、模型值不可覆盖 |
| 指标口径分叉 | P1 | Orchestrator 直接聚合 Order | 统一 Metrics Service |
| 前端缓存串空间 | P1 | localStorage 单用户快照 | Context store、请求取消、cache namespace |
| 大迁移锁表/孤儿 | P1 | 多数 tenant_id 无复合约束 | 小步迁移、先报告后约束 |
| 双系统维护 | P1 | 容易复制 Personal/Organization 页面 | 一套 API/页面，Context 控制密度和入口 |

---

## 11. 测试与验收冻结

### 11.1 身份与隔离

- 一个 User 拥有两个 Workspace，角色和数据范围不同；
- 两个 Workspace 的 Product、Store、Order、Finance 相互隔离；
- Workspace switch 后旧请求和缓存不能回写当前空间；
- 跨 Workspace ID 返回 403/404，不泄漏资源存在；
- superadmin 代管与普通 switch 不混用；
- User 停用使所有会话失效，移除一个 Membership 不删除自然人。

### 11.2 产品场景 A-G

- A：新个人用户建立 Personal Workspace、画像和新手路径；
- B：有工厂用户优先从 Factory SKU 找海外机会；
- C：已有 Shopee Store 用户优先导入、诊断和优化；
- D：第二 Workspace 数据隔离；
- E：Personal 升级 Organization，历史 ID 与数据保持；
- F：Organization Custom Role + Store Scope；
- G：Factory Collaborator 只能进入本厂 Portal。

### 11.3 经营可信

- source Shop 无法触发销售订单同步；
- 1688 采购订单不进入 GMV；
- Order、Advertisement、Settlement 的 Store 归属可解释；
- AI 推荐显示 Evidence、Freshness 和 Risk；
- Capability 的来源可追溯；
- Business Stage 规则相同输入产生相同结果。

### 11.4 Migration

- 旧 SQLite 数据可升级；
- PostgreSQL 空库可完整升级；
- 历史库升级前数据检查可重复运行；
- 回填幂等；
- downgrade 或 forward-fix 路径明确；
- 双读期旧 API 与新 Context 行为一致。

---

## 12. 开发变更门禁

每个后续任务在修改前必须回答：

1. 是否符合 ADR-F01 至 ADR-F15？
2. 是否改变 Workspace 数据归属？
3. 是否影响现有历史数据和 API？
4. 是否保持 Personal/Organization 共用底座？
5. 是否需要显式 Migration 和 downgrade？
6. 是否改变权限、Data Scope 或 Store Scope？
7. 是否需要更新 workspace-context？
8. 是否有单元、集成、权限和 E2E 测试？
9. 是否能在不删除旧字段的情况下增量上线？
10. 回滚时会丢失什么？

任一问题没有明确答案，不进入编码。

---

## 13. Phase 1 开始前的具体任务包

### P1-01 迁移前只读审计器

输出 User/Tenant、Membership 回填候选、superadmin 0、跨 tenant 引用、Setting 归属、Shop.role、source Order 和 Store 空归属报告。

### P1-02 身份与 Membership 测试先行

先增加多 Workspace、不同角色、非法切换、成员移除、平台身份和 Factory Collaborator 回归测试。

### P1-03 显式数据库 Migration

只增加 workspace_type、WorkspaceProfile、WorkspaceMembership 和必要索引；不在同一 revision 引入全部 Capability/Path/UI 模型。

### P1-04 认证双读

Membership 优先、旧 User 字段 fallback；保持现有登录和旧 API 可用。

### P1-05 P0 领域修复

完成 Setting 作用域与 source/sales 订单隔离，避免新 Context 建立在错误数据之上。

### P1-06 Workspace API 与 Context

Context 先服务后端权限和测试，再接前端 Switcher。

---

## 14. 本轮结果

- 业务代码修改：无；
- 数据库修改：无；
- API 修改：无；
- UI 修改：无；
- 新增文档：`docs/final_architecture_assessment.md`；
- 架构状态：Phase 0 DONE；
- 下一步：按 P1-01 → P1-06 顺序进入 Phase 1；
- 当前不应实施：Onboarding、Switcher、自适应 Dashboard、AI User Fit；这些能力必须等待 Membership 与 Workspace Context 基座稳定。

本架构冻结的是核心关系、数据边界和执行顺序，不冻结合理的字段细节、索引优化或 UI 表现；任何细节调整都不得违反 ADR-F01 至 ADR-F15。
