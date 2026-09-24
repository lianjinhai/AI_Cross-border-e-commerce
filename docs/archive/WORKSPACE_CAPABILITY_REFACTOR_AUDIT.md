# User / Workspace / Capability 重构审计

> DEV-010｜审计日期：2026-09-22  
> 结论依据：当前代码、数据库结构、路由、前端页面与现有测试。文档描述与代码冲突时，以代码为准。  
> 本轮范围：只读审计与最小改造方案；未修改业务代码、数据库、API 或前端行为。

## 0. 执行结论

当前 `Tenant` 已经承担绝大多数经营数据的隔离边界，可以在产品层直接抽象为 `Workspace`，不应把全库 `tenant_id`、Tenant 表名或现有业务 API 大规模改名。

真正需要补齐的不是另一套“个人版系统”，而是四层增量能力：

1. 将自然人 `User` 与经营空间关系从单一 `User.tenant_id` 拆成可多选的 `WorkspaceMembership`；
2. 在既有 Tenant 边界上增加 Workspace 类型、经营画像、经营阶段和结构化 Business Path；
3. 由后端统一输出 active workspace 的权限、数据范围、导航和默认落点；
4. 前端继续复用现有商品、工厂、店铺、订单和财务页面，只增加上下文、引导体验与信息架构外壳。

本轮发现两个会影响后续多 Workspace 正确性的 P0 缺陷：

- `Setting` 使用全局 key，缺少 tenant/workspace 作用域，AI、1688 等配置存在跨经营空间串用风险；
- `source` 类型的 1688 店铺可进入通用销售订单同步，采购/分销单可能落入销售 `Order`，进而污染 GMV 和利润口径。

DEV-011 编码前应先形成显式、可回滚的增量迁移，并将上述两项作为前置治理，而不是直接开发 Workspace Switcher。

## 1. 审计方法与边界

### 1.1 已核对范围

- 后端：`User`、`Tenant`、认证、角色守卫、超管代管、Supplier/Factory、1688、Product、Listing、Shop、Order、Finance、Agent、Workflow、设置与迁移；
- 前端：Login、Router、权限、Layout/Menu、Dashboard、Shops、Products、Discovery、Factory Portal、Users、AI Assistant；
- 测试：后端安全/跨租户测试、前端角色路由测试；
- 现有数据库：表结构和当前用户/租户关系的只读检查。

### 1.2 审计限制

- 项目目录当前不是 Git 工作区，无法用提交历史确认字段演进；
- 本轮没有执行数据库写入、迁移或业务测试；
- 没有外部平台账号参与，本报告不包含真实店铺能力验收结论。

## 2. 左脑门禁：目标、约束、风险、最小方案

### 2.1 业务目标

建立一套同时服务个人、团队、企业和外部工厂协作者的统一业务底座，实现：

`User → Workspace → Capability Profile → Business Path → Market → Supply → Product → Store → Order → Profit → Next Action`

### 2.2 必须保持的约束

- Tenant ID 继续作为现有经营数据边界；
- 不搬迁现有 Product、Supplier、Shop、Listing、Order、Finance、Workflow 数据；
- 不复制 Personal/Organization 两套业务页面或 API；
- 保持现有 URL 和主要用户操作路径兼容；
- Factory Collaborator 继续是工厂关系，不自动成为完整 Workspace Member；
- 角色与菜单可以增量升级，但后端授权始终是最终边界。

### 2.3 最高风险

| 风险 | 级别 | 影响 | 处理原则 |
|---|---|---|---|
| active workspace 只在浏览器 localStorage 切换 | P0 | 可跨空间读取或写入数据 | 必须由后端校验 Membership 后签发/刷新上下文 |
| 全局 Setting 无 workspace 作用域 | P0 | 1688、LLM、费率或凭证串用 | 拆 Platform-global 与 Workspace-scoped 配置 |
| source 店铺同步进销售订单 | P0 | 采购单污染 GMV、利润和预测 | source/sales 路由强隔离 |
| `User.tenant_id` 与单一 `role` | P1 | 无法一人多 Workspace、分空间角色 | 新增 Membership，双读兼容迁移 |
| superadmin 使用 `tenant_id=0` | P1 | PostgreSQL 外键不兼容 | 改为 nullable/global identity，先迁数据 |
| 直接重命名 Tenant 或全库 FK | P1 | 高锁表、历史数据和 API 回归风险 | 禁止；产品层使用 Workspace 术语 |
| 前端菜单隐藏代替授权 | P1 | 直达 URL 或 API 越权 | 服务端 permissions/data scopes 强校验 |

### 2.4 最小可行方案

保留 `Tenant` 表和全部 `tenant_id`，定义：

`Tenant ≈ Workspace Boundary`

增量增加：

- Tenant 上的 `workspace_type`；
- `workspace_profile`；
- `workspace_membership`；
- `business_capability_profile`；
- `business_path` 与 `business_path_step`；
- 服务端 `workspace-context`；
- 前端 Workspace Switcher、Onboarding、Business Path 和 Guided/Professional 外壳。

Personal 升级 Organization 只改变 Workspace 类型、资料和成员关系，Tenant ID 不变，因此商品、店铺、订单、Listing、AI 记录和财务历史无需搬迁。

## 3. 当前 User 模型

实际代码：`backend/app/models.py:42-52`。

当前 `User` 表包含：

- 非空 `tenant_id`；
- 全局唯一 `username`；
- `password_hash`、`display_name`；
- 单一字符串 `role`；
- `status` 和 `token_version`。

判断：

- `username` 已适合作为自然人身份的全局登录标识；
- `tenant_id` 和 `role` 把自然人身份、默认经营空间和空间内授权混在一张表；
- 当前一个 User 只能属于一个 Tenant；
- 当前不存在自助注册或自然人先于 Workspace 存在的流程。

特别风险：`backend/app/seed.py` 以 `tenant_id=0` 创建 superadmin，但模型声明了 Tenant 外键。SQLite 当前未严格暴露该问题，切换 PostgreSQL 时会冲突。

## 4. 当前 Tenant 模型

实际代码：`backend/app/models.py:20-28`。

当前 `Tenant` 包含：

- `name`；
- `plan`；
- `status`；
- 许可到期和备注；
- 创建时间。

绝大多数业务表都有 `tenant_id`，包括 Product、Supplier、工厂目录、Listing、发布尝试、Shop、Purchase、Refund、Settlement、Order、Workflow、Knowledge 和 AI Log。

判断：Tenant 已经是稳定的数据隔离与经营边界，但产品文案仍把它视为“客户公司租户”。底层可保留，产品/API 服务层应逐步使用 Workspace 术语。

## 5. Tenant 是否可以抽象为 Workspace

结论：可以，而且这是风险最低的方案。

可复用依据：

- 核心业务表已经通过 `tenant_id` 归属同一经营边界；
- Shop 属于 Tenant，订单和发布尝试可进一步关联 Shop；
- JWT 已携带 `tid`，能够承载 active workspace 上下文；
- 现有路由普遍使用 `user.tenant_id` 做查询过滤；
- 跨租户安全测试已经建立了可保留的回归基础。

不应做：

- 不应新建一套与 Tenant 平行且复制全部业务外键的 Workspace；
- 不应批量把所有 `tenant_id` 改成 `workspace_id`；
- 不应为 Personal 和 Organization 复制两套表、路由或页面。

## 6. 当前 User 与 Tenant 关系

当前关系是：

`Tenant 1 → N User`，但 `User N → 1 Tenant`。

租户由 superadmin 创建，同时创建一个 admin 用户。普通用户只能由租户管理员在 `/auth/users` 中创建。没有：

- 自助注册；
- Membership；
- Workspace Owner；
- Workspace 邀请；
- active workspace 切换；
- Personal → Organization 转换。

## 7. 当前一个 User 是否可加入多个 Tenant

不可以。

原因：

- `User.tenant_id` 是单值非空列；
- JWT 中 `tid` 默认直接来自 User；
- 普通用户切换时没有 Membership 校验；
- `role` 也存于 User，无法表达同一人在不同 Workspace 的不同角色。

superadmin 的“进入租户”是平台代管/冒充流程，不是普通用户多 Workspace 能力，不能直接用作产品 Switcher。

## 8. 当前 Role

当前角色为硬编码字符串：

- `superadmin`；
- `admin`；
- `compliance_approver`；
- `operator`；
- `viewer`；
- `supplier`。

后端守卫位于 `backend/app/auth.py:124-140`；租户用户 CRUD 只接受固定角色集合。前端 `frontend/src/permissions.js` 另有一套固定路由矩阵。

判断：现有角色语义和守卫函数可作为兼容层保留，但角色归属应逐步迁到 Membership。首版不需要几十个硬编码岗位。

建议模板映射：

| 旧角色 | Workspace 模板/关系 | 兼容策略 |
|---|---|---|
| admin | OWNER 或 ADMIN 兼容模板 | 回填 Membership；旧字段暂保留 |
| operator | OPERATOR | 回填 Membership |
| viewer | READ_ONLY | 回填 Membership |
| compliance_approver | 自定义权限或兼容模板 | 保持审批权限语义 |
| supplier | Factory Collaborator | 不回填普通 Workspace Member |
| superadmin | Platform identity | 不属于普通 Workspace |

## 9. 当前 Permission

当前没有 Permission 表、Custom Role 或通用 Data Scope。

实际授权方式：

- 后端 `require_write`、`require_admin`、`require_compliance_approver`；
- 各路由按 `user.tenant_id` 过滤；
- 前端按角色隐藏路由和菜单；
- Supplier Portal 另有 tenant + supplier 双重资源过滤。

可保留现有守卫语义，但下一阶段应由 Membership 解析 effective role、permissions 和 data scopes。前端 navigation 只负责体验，不得成为授权来源。

## 10. 当前 Factory 用户模型

`SupplierPortalMember` 已将 User 与具体 Supplier/Factory 绑定，认证层还限制 `supplier` 只能访问 `/factory-network/portal/*` 与 `/auth/me`，门户 CRUD 同时校验 tenant 和 supplier。

结论：这已经符合 Factory Collaborator 不是完整 Workspace Member 的方向，应复用而不是重写。

缺口：

- `user_id` 全局唯一，一个自然人无法绑定多个工厂或 Workspace；
- Portal 目前主要支持本厂资料/SKU，尚未覆盖需求、订单和履约；
- 当前隔离入口依赖全局 `supplier` role，未来应由协作者关系与数据范围驱动。

## 11. 当前 Supply 资源归属

已有三类基础实体：

- PRIVATE_FACTORY：`Supplier.supplier_type=factory` + Supplier Catalog；
- MANUAL_SUPPLIER：现有 Supplier/trader 等记录；
- 1688：`Shop.role=source` + 1688 Adapter/代发链路。

现状不是缺少业务能力，而是缺少统一 `Supply Source` 领域视图。建议先用 DTO/service 聚合现有实体，不创建另一套平行货源表。

阻断缺陷：通用 `/shops/{id}/sync_orders` 未禁止 source 店铺；1688 Adapter 返回的采购/分销单可能写入销售 `Order`。在 Workspace 个性化推荐依赖 GMV 前必须隔离。

## 12. 当前 Store / Sales Channel 归属

`Shop` 同时承载 source 和 sales 两种角色。销售侧可在产品层称为 Store，底层表名继续保留。

Store 边界覆盖情况：

| 业务对象 | 当前 Store 关联 | 判断 |
|---|---|---|
| PlatformPublishAttempt | 有 `shop_id` | 可视为 Listing 向具体 Store 的发布实例 |
| Order | 有 nullable `shop_id` | 保留 nullable 兼容历史导入 |
| PlatformSettlementRecord | 有 nullable `shop_id` | 可按 Store 对账，但历史存在未分配记录 |
| Listing | 无 `shop_id` | 可继续作为平台内容母稿，不必强塞 Store |
| AdCampaign | 无 `shop_id` | 后续需增量增加 Store 范围 |
| Refund | 经 Order 间接关联 | 可复用 |

最小治理：不重写 Listing；发布实例以 PlatformPublishAttempt 作为 Store 边界；广告与结算逐步补 nullable Store 归属并回填，不强制历史数据非空。

## 13. 当前 Dashboard

`frontend/src/views/Dashboard.vue` 是统一的成熟经营驾驶舱，展示 GMV、订单、利润、ROI、Listing、会话及图表。

缺口：没有 Workspace Type、Business Stage、Capability、下一步、启动进度或 Factory/已有 Store 特化。

应保留现有 KPI 和图表作为 Professional/Operating 区块；自适应首页只增加外层编排，不重写财务指标或复制 Dashboard。

## 14. 当前 Onboarding

当前不存在 Register、Onboarding、Capability Profile 或 Business Path 路由/API/页面。

登录后：

- 前端保存 token 和 user 到 localStorage；
- 固定跳转 `/dashboard`；
- 没有创建 Personal Workspace、自助加入/创建第二 Workspace 或恢复未完成引导。

新 Onboarding 必须可分步保存和恢复，用户声明值要标注 `USER_DECLARED`；Store、Supplier 和订单等事实可作为 `SYSTEM_OBSERVED`；模型推断必须单独标记 `MODEL_ESTIMATED`，不得覆盖用户声明。

## 15. 当前菜单与信息架构

当前 Layout 按概览/商品/采购/运营/系统硬编码 18 个以上入口，只做角色过滤。`店铺授权`被放在采购分组，Supply 与 Sales Channel 概念混杂。

缺口：

- 无 Workspace Switcher；
- 无 Experience Mode；
- 无服务端 navigation；
- 无业务阶段驱动的默认落点；
- Personal 用户同样会面对复杂管理入口。

应保留全部旧 URL，以导航映射方式逐步归类为：首页、机会、商品、货源、渠道、订单、经营、AI 助手、更多。

## 16. 当前 AI 入口

AI Assistant 是全局浮层，向 `/ai/chat` 只发送 message，提供固定快捷问题。后端 Agent 能获取 tenant_id，但没有完整的 Workspace、Business Stage、Capability Profile、Supply Sources、Connected Stores、Business Path、Pending Tasks 或 Data Scope 上下文。

风险：当前 Orchestrator 的部分经营汇总仍直接查询旧 Order 字段，未完全统一到 Metrics / Unit Economics Service；Workspace Copilot 接入时不能扩大这一口径分叉。

目标不是通用聊天，而是由后端在 active workspace 下组装只读 Context，再让 AI 生成带 Evidence、Reason、Data Source、Freshness、Risk 的建议或可审计 AI Action。

## 17. Market / Supply / Channel 概念审计

### 17.1 Market

现有 `MarketTrend`、Discovery Agent、ProductScore 能表达趋势和商业评分，但所谓 Opportunity 主要由 Product + ProductScore 承担，尚无独立 Market Opportunity 聚合。

### 17.2 Supply

Supplier、私域工厂目录、1688 source Shop 和代发链路已经存在。缺口是统一读模型与清晰入口，不是重新建表。

### 17.3 Channel

Sales Channel 由 `Shop.role=sales` 和平台 Adapter 承担，真实经营边界是 Store。应把 source Shop 从销售渠道语义中隔离。

### 17.4 当前混杂点

- `Product.source_platform` 同时出现平台/域名等不同语义；
- `MarketTrend.platform` 可以包含 1688；
- Discovery 查询会把 1688/wholesale 当市场提示；
- Shop 一张表混合 source 与 sales；
- 1688 source 可进入销售订单同步。

因此首版应先建立领域术语、枚举映射和 DTO，保留历史值并提供 `UNKNOWN`/兼容映射，不能直接把旧字段强改为严格枚举。

## 18. Opportunity 与 User Fit

现有 ProductScore 包含需求、竞争、利润、风险和 total，可继续作为 Commercial Value 的数据基础。

当前没有：

- Workspace/User Fit；
- Supply Fit、Channel Fit、Experience Fit、Budget Fit、Operation Fit；
- 标准 Evidence、Freshness、Risk 结构；
- 来源区分。

最小方案：保持 ProductScore.total 兼容，新建或扩展独立的 Workspace Opportunity Fit 结果，使用可解释规则和版本化权重，至少返回两个维度：

- `commercial_value_score`；
- `user_fit_score`。

用户声明能力与系统观察能力不得混写，预算等敏感信息不进入不必要的列表展示。

## 19. 可以直接复用的能力

- Tenant ID 与现有业务 `tenant_id` 数据边界；
- 全局唯一 username 作为自然人登录标识；
- JWT `tid` 作为 active workspace 上下文的载体；
- 现有后端角色守卫语义和跨租户测试；
- superadmin 代管流程与 TenantAccessLog，但必须与用户 Switcher 区分；
- SupplierPortalMember 和 Factory Portal 的本厂隔离；
- Product、Supplier、Factory Catalog、1688、Shop、Listing、Order、Finance、Workflow 等核心业务实体/API/页面；
- Shops 页已有的 source/sales 分栏；
- Dashboard 的专业经营指标组件；
- 前端原有业务 URL 和懒加载结构；
- ProductScore 作为 Commercial Value 基础；
- 现有统一商业指标服务和业务闭环。

## 20. 需要扩展的能力

- Tenant 增加 `workspace_type`，另建 WorkspaceProfile；
- WorkspaceMembership 承载每空间 role/status/data scope；
- active workspace 的选择、校验、切换和审计；
- Capability Profile、Business Stage、Business Path；
- `workspace-context` API；
- Workspace-scoped Setting；
- Supply Source 聚合服务和 Market/Supply/Channel 术语治理；
- source/sales 订单同步隔离；
- Workspace Opportunity Fit 与 Evidence；
- 前端响应式 Context、Switcher、Onboarding、Business Path、Adaptive Dashboard；
- Organization 的成员、Role Template、Custom Role 和 Store Scope；
- AI Copilot 的 workspace-aware 上下文与结构化 AI Action。

## 21. 需要迁移的能力

### 21.1 身份迁移

- `User.tenant_id` 阶段性改为 nullable/legacy default workspace；
- superadmin `tenant_id=0` 迁成 NULL 或平台身份；
- 非 supplier 用户回填一条 WorkspaceMembership；
- `User.role` 暂保，认证先 Membership 优先、旧字段 fallback；
- supplier 不自动回填 WorkspaceMember；
- 用户删除从物理删除转为 Membership 移除/停用优先。

### 21.2 经营空间迁移

- 现有 Tenant 全部先回填 `ORGANIZATION`，避免擅自把历史公司判为个人；
- 新注册个人创建 PERSONAL Workspace + OWNER Membership；
- Personal 转 Organization 只更新类型和组织资料，不改 Tenant ID。

### 21.3 配置迁移

- 将 Workspace 密钥、Token、AI/费率经营配置从全局 Setting 迁到 workspace scope；
- 平台级 app metadata 仍可保留 global scope；
- 迁移前先识别现有 key 的真实归属，不能盲目复制到所有 Workspace。

### 21.4 Factory Collaborator 迁移

- 先审计重复/孤儿；
- 将 `user_id unique` 调整为 `(tenant_id, supplier_id, user_id)` 唯一；
- 保留 portal 路径和 tenant+supplier 资源检查。

## 22. 根本不应该动的内容

- Tenant 表名、Tenant 主键和全库既有 `tenant_id`；
- Product、Order、Listing、Supplier、Shop 等稳定业务表的核心语义；
- 现有业务页面内部主要 API 流程和 URL；
- Factory Portal 的本厂资源门禁；
- superadmin 代管与其审计语义；
- Listing 母稿模型，不因 Store 边界强行改造成一店一稿；
- 现有 Workflow Engine、平台 Adapter 和财务指标服务；
- Personal/Organization 共用的业务模块。

## 23. 文档与代码差异

| 目标/文档描述 | 实际代码 | 结论 |
|---|---|---|
| 多租户/RBAC 已存在 | tenant 过滤和固定角色存在 | 真实但粒度较粗，不等于 Workspace Membership/RBAC |
| 用户可按角色协作 | 同一 User 只有一个 tenant 和 role | 不支持跨 Workspace 多角色 |
| 工厂账号可维护 SKU | SupplierPortalMember + Portal 已实现 | 可直接复用，但仅单工厂绑定 |
| 店铺区分货源和销售 | Shop.role 已区分 | 前端信息架构仍混杂，后端同步缺角色隔离 |
| AI Agent 能经营协同 | Agent 已 tenant-aware | 尚不具备 Capability/Stage/Path/Permission 完整上下文 |
| Dashboard/BI 已存在 | 专业经营指标已存在 | 不是新手/阶段自适应首页 |
| Onboarding/Workspace 概念 | 代码中不存在 | 需要新增，不得声称已实现 |
| Subscription | 只有 Tenant.plan | 套餐与 Workspace 类型必须分离 |

## 24. 历史数据与迁移风险

1. `User.tenant_id` 非空、superadmin 0 值和 PostgreSQL 外键冲突；
2. `User.role` 仍被大量守卫和前端逻辑读取，不能一次删除；
3. `/auth/users/{id}` 当前物理删除 User，历史外键和多 Membership 场景不安全；
4. 多数业务 `tenant_id` 只有普通索引，数据隔离主要依靠应用过滤；
5. 跨实体引用缺少 `(tenant_id, id)` 复合约束，迁移前需做一致性审计；
6. 全局 Setting 需要先确认平台级与空间级归属；
7. `Product.source_platform` 历史值不规范，不能直接 enum 化；
8. 旧 Shop.role 需要核对，1688 数据不能默认当 sales；
9. Order/Settlement 的 nullable `shop_id` 必须保留以兼容历史导入；
10. SupplierPortalMember 唯一约束变更前要查重复和孤儿；
11. 现有 Alembic 基线使用动态 metadata，新结构必须创建显式 revision；
12. 浏览器缓存和切换前并发请求可能造成跨 Workspace 残留，需要 request epoch/cache invalidation。

## 25. 建议领域模型

```text
Platform
└── User（自然人身份）
    ├── WorkspaceMembership ── Workspace/Tenant（经营边界）
    │                         ├── WorkspaceProfile
    │                         ├── BusinessCapabilityProfile
    │                         ├── BusinessPath ── BusinessPathStep
    │                         ├── Supply Sources
    │                         ├── Stores
    │                         └── 既有全部业务数据
    └── FactoryCollaborator ── Supplier/Factory（外部协作边界）
```

`workspace_type` 与订阅必须分离：

- Workspace Type：PERSONAL / ORGANIZATION；
- Experience Mode：GUIDED / PROFESSIONAL；
- Subscription：FREE / BASIC / PRO / ENTERPRISE（本轮仅保持可扩展，不实现复杂计费）；
- Role：Membership 在当前 Workspace 的授权；
- Factory Collaborator：独立于普通 Workspace Membership 的资源关系。

## 26. 最小改造方案与依赖顺序

### Phase 0：测试与数据盘点

1. 固化现有跨租户、角色、工厂 Portal 与核心闭环回归；
2. 增加历史数据检查脚本：User/Tenant、跨 tenant 引用、Setting、Shop.role、无 Store 订单；
3. 为新增能力定义 feature flag/兼容回退。

验收：不改业务行为，能够在迁移前报告所有阻断数据。

### Phase 1：身份与 Workspace 基座

1. 显式 migration：Tenant additive `workspace_type`；
2. 新增 WorkspaceProfile、WorkspaceMembership；
3. User.tenant_id 阶段性 nullable，处理 superadmin 0；
4. 回填非 supplier Membership；
5. 建立 Membership service 和兼容认证解析。

验收：旧登录和 API 不变；同一 User 可在两个 Workspace 有不同 Membership；无跨空间泄漏。

### Phase 2：阻断性隔离治理

1. Setting 拆分 global/workspace scope；
2. 禁止 source Shop 进入销售订单同步；
3. 1688 采购同步归 Purchase 领域；
4. 保持历史数据可读并标记 unassigned/unknown。

验收：切换 Workspace 不串配置；1688 source 数据不进入销售 GMV。

### Phase 3：Workspace API 与 Context

1. `/me/workspaces`、Workspace CRUD/升级、switch；
2. switch 必须校验 active Membership 后签发新上下文；
3. `/me/workspace-context` 聚合 profile、stage、capability、permission、data scope、subscription、supply、stores、path、tasks、navigation 和 default route；
4. superadmin impersonation 与 Workspace switch 使用不同状态和审计动作。

验收：服务端是上下文和导航规则的唯一权威来源。

### Phase 4：Capability、Stage 与 Business Path

1. Capability Profile 支持 USER_DECLARED/SYSTEM_OBSERVED/MODEL_ESTIMATED 来源；
2. Business Stage 使用真实状态规则，而非注册时间；
3. Business Path 结构化、版本化、步骤化；
4. 场景模板覆盖新手、有工厂、已有 Store、有供应链四类；
5. AI 生成后必须由用户确认，不能直接执行高风险动作。

验收：有工厂用户不默认走 1688；已有 Store 用户优先导入与诊断。

### Phase 5：前端外壳

1. 响应式 workspace-context/session；
2. Workspace Switcher；切换后清理请求/缓存并重取 context；
3. 新 Onboarding 和 Business Path；
4. 单一 Dashboard 内 Guided/Professional 两种编排；
5. 服务端 navigation + 旧角色策略 fallback；
6. 一级导航重组但保留原 URL 和页面。

验收：Personal 不受复杂 RBAC 干扰；Organization 保留成员协作；业务页面不复制。

### Phase 6：Organization 权限与 Factory 协作

1. Role Template、Custom Role、Permission、Store Scope；
2. 旧角色映射和 auth/users API 兼容；
3. Factory Collaborator 多关系和 Portal 能力增量扩展；
4. 用户删除改为移除 Membership/停用优先。

验收：成员只能访问授权 Store；外部工厂无法读取销售财务和其他供应商。

### Phase 7：AI Copilot 与 User Fit

1. AI 只通过 active workspace context 获取真实状态；
2. 统一 AI Action 和 Guardrail；
3. Commercial Value 复用 ProductScore；
4. User Fit 使用可解释规则、证据、数据新鲜度和风险；
5. AI 经营指标全部调用统一 Metrics/Unit Economics Service。

验收：AI 不猜测用户能力/预算；建议可追溯；高风险动作继续审批。

### Phase 8：E2E 与收口

覆盖用户要求的 A-G 场景，并额外验证：

- 两个 Workspace 并发请求与切换后的缓存失效；
- 跨 Workspace 资源返回 403/404 且不泄漏存在性；
- Personal → Organization 后所有历史实体 ID 不变；
- superadmin 代管退出与 Workspace switch 不互相污染；
- source Shop 无法触发销售订单同步；
- Factory Collaborator 无销售财务访问权。

## 27. 回滚策略

- 所有新表、新列和 API 先 additive；
- 旧 `User.tenant_id`、`User.role`、旧登录和旧路由在兼容期保留；
- 新 Context/UI 通过 feature flag 或失败回退旧 Dashboard；
- migration 使用显式 downgrade，避免数据搬迁式重命名；
- Personal → Organization 只改类型，可回滚类型但不删除成员或经营数据；
- Setting 迁移在旧读路径关闭前保持双读和明确优先级；
- 不在同一个 revision 中补齐全库 FK 或强制历史 `shop_id` 非空。

## 28. DEV-010 分类清单

### Already Implemented

- Tenant 经营边界与大部分业务 tenant 隔离；
- 单 Workspace 下的固定角色守卫；
- superadmin 代管和审计；
- Factory Portal 的本厂隔离与 SKU 维护；
- Supply、Product、Store、Listing、Order、Finance、Workflow 主业务底座；
- Shop source/sales 基础区分；
- 专业 Dashboard 和 AI 浮层入口；
- 跨租户和前端角色路由基础测试。

### Partially Implemented

- Tenant 可承担 Workspace，但没有产品层 Workspace API/Profile/Type；
- Store 是销售边界，但广告、历史订单和部分结算粒度不完整；
- Supply 三类实体存在，但没有统一 Supply Source 领域视图；
- AI 能读取 tenant 数据，但不具备完整 workspace context；
- Factory Collaborator 已隔离，但仅支持单绑定和有限 Portal；
- Opportunity 有商业评分，但没有 User Fit 与标准 Evidence。

### Missing

- Personal Workspace、自助注册和第二 Workspace；
- WorkspaceMembership 与 Workspace 级角色/权限；
- Capability Profile、Business Stage、Business Path；
- workspace-context API；
- Workspace Switcher、Onboarding、Guided/Professional；
- 自适应首页和服务端导航；
- Custom Role、Store Scope；
- Workspace-aware Copilot 与 AI Action；
- User Fit 双维评分；
- A-G 浏览器 E2E。

### Needs Refactor

- User.tenant_id/role 的身份与授权耦合；
- 全局 Setting；
- source/sales 的订单同步边界；
- 前端 localStorage 单角色快照与硬编码菜单；
- 物理删除 User；
- FactoryPortalMember 全局单绑定；
- Market/Supply/Channel 字段语义混杂；
- AI 内部指标旁路统一服务。

### Needs Verification

- 历史 tenant 一致性与孤儿引用；
- 旧 Shop.role 的正确性；
- Setting 各 key 的真实归属；
- 无 Store 历史订单/结算处理；
- PostgreSQL 下 nullable/FK/唯一约束迁移；
- Membership 双读期间的权限一致性；
- Workspace 切换并发与缓存隔离；
- Personal 升级 Organization 的完整数据保持。

## 29. DEV-010 验收结果

| 验收项 | 状态 | 说明 |
|---|---|---|
| 完整扫描目标领域 | DONE | 已核对身份、RBAC、Factory、Supply、Store、业务数据、前端与测试 |
| 判断 Tenant 是否可复用 | DONE | 可复用为 Workspace Boundary |
| 识别直接复用/扩展/迁移/不应动 | DONE | 已形成四类清单 |
| 识别历史数据风险 | DONE | 已列 P0/P1 与迁移前检查 |
| 给出最小实施顺序 | DONE | Phase 0-8，先基座与隔离、后体验与 AI |
| 修改业务代码 | NOT STARTED | 符合本轮先审计要求 |

## 30. 下一任务

下一任务应为 DEV-011“Workspace 领域抽象”，但只执行低风险基座部分：

1. 先补迁移前只读数据检查和身份/隔离测试；
2. 输出显式表结构与 API 兼容契约；
3. 评审 migration 的 upgrade/downgrade 和 superadmin 处理；
4. 再落地 Tenant additive 字段、WorkspaceProfile、WorkspaceMembership；
5. 暂不开发完整 Onboarding、Dashboard 重排或 User Fit。

在 DEV-011 通过迁移验证和回归前，不进入大规模前端改造。
