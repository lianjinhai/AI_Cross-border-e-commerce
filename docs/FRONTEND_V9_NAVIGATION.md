# FRONTEND V9 · 导航冻结（UX-A 架构冻结）

> 依据：`FRONTEND_V9_PAGE_MATRIX.md` 新页面位置列、`FRONTEND_V9_USER_JOURNEYS.md` 三空间定义、现行 `frontend/src/composables/navigation.js`（11 域语义）与 `permissions.js` routeRedirect 策略。
> 结构延续 UX-02 落地的纯函数组织：菜单定义 + 可见性过滤 = 纯模块（三份：workspace-navigation / console-navigation / factory-navigation），V9 仅改路径为 `/app|/console|/factory/*`，域语义不变。

## 1. Workspace 导航（11 业务域，/app/*）

| 域 key | 域标签 | 二级页面（path · 标签 · 来源矩阵#） |
|---|---|---|
| home | 首页 | `/app` · 经营工作台（#3，今日经营：待办分组+信号区块+onboarding 卡片） |
| market | 市场机会 | `/app/market/discovery` · 商品发现（#4，选品一键转入商品池） |
| product | 商品经营 | `/app/products` · 商品池（#5）；`/app/products/:id` · 商品详情（#5，路由化）；`/app/listings` · Listing 工作台（#6）；`/app/listings/:id` · Listing 详情分步流（#6）；`/app/launch` · 上线中心（#9）；`/app/launch/:id` · 上线流程详情（#10）；`/app/compliance` · 合规报告中心（#7）；`/app/compliance/approvals` · 合规工作台（#8，合规员默认落地） |
| supply | 货源中心 | `/app/supply/suppliers` · 供应商库（#12 拆分）；`/app/supply/purchases` · 采购单（#12 拆分） |
| channel | 销售渠道 | `/app/channels/shops` · 店铺授权（#11，拆列表+授权向导+类目映射） |
| fulfill | 订单履约 | `/app/orders` · 订单管理（#16）；`/app/settlements` · 账期结算（#18） |
| aftersale | 客户售后 | `/app/refunds` · 售后管理（#17）；`/app/support` · 智能客服（#19） |
| optimization | 经营优化 | `/app/pricing` · 动态定价（#14）；`/app/ads` · 广告增长（#15）；`/app/risk/alerts` · 风险巡检（#24） |
| analytics | 数据分析 | `/app/analytics/bi` · BI 经营分析（#22）；`/app/analytics/finance` · 财务工作台（#23）；`/app/analytics/landed-cost` · 到岸成本配置（#23 新增，接 cross-border） |
| aiops | AI 运营 | `/app/ai/workflows` · AI 工作流（#20）；`/app/ai/knowledge` · 知识库（#21）；`/app/ai/decisions` · AI 决策依据（#25） |
| settings | 设置与管理 | `/app/settings/ai` · AI 与集成设置（#27，分组子页）；`/app/settings/team` · 用户与角色（#26） |

设置子页锚点：`/app/settings/ai` 内以锚点分组「AI 模型 / 经营参数 / 集成密钥 / 日志」（单路由 4 组，不做 4 条路由）。
参数详情路由（`/app/products/:id`、`/app/listings/:id`、`/app/launch/:id`）不在侧栏显示，由列表行进入，面包屑回父级。

## 2. Console 导航（/console/*）

| 菜单 | 路径 | 来源 |
|---|---|---|
| 总览 | `/console/overview` | #28 总览 tab |
| 租户管理 | `/console/tenants` | #28 租户 tab（开通+凭据一次性展示+代客入口） |
| 访问审计 | `/console/audit` | #28 `?tab=audit` 独立成页 |
| 维护 | `/console/maintenance` | #28 维护 tab（规则检查/演示数据清理） |

## 3. Factory 导航（/factory/*）

| 菜单 | 路径 | 状态 |
|---|---|---|
| 产品与产能 | `/factory/products` | 已接（factory_network portal） |
| 平台订单 | `/factory/orders` | **待接入**（factory_network 其余端点未核）——不放入口 |
| 结算查看 | `/factory/settlements` | **待接入**——不放入口 |

## 4. 顶栏规范（三外壳共享插槽，各空间按需装配）

| 区位（左→右） | Workspace | Console | Factory |
|---|---|---|---|
| 空间标识 | WorkspaceSwitcher（`me/workspaces` 列表 + `/me/workspaces/{id}/switch`；工厂/受限场景按现行策略降级，不虚构切换） | Console 徽标（无切换） | 工厂名（只读标识） |
| 上下文筛选 | StoreSwitcher（shops 数据源，全局记忆选中店铺，供订单/广告/客服等页作默认筛选） | 当前租户标识（代客时高亮） | — |
| 全局搜索 | 新增：跨域搜索（页面名+商品名+订单号，前端聚合已加载列表与深链；不引入后端新端点） | 租户搜索 | — |
| 待处理任务 | TaskCenter 入口（workbench/todo 前 N 条 + 未读数） | — | — |
| 通知 | NotificationBell（alerts 新告警聚合；点击进 `/app/risk/alerts`） | — | — |
| AI 副驾驶 | AiCopilot FAB+抽屉（Workspace 常显；工厂隐藏；Console 不显示） | — | — |
| 账户 | 用户菜单（角色徽标、退出、退出代客[仅代客时]） | 同左 | 同左 |

状态横幅（外壳常显条，优先级从高到低）：代客中（erp_impersonating，一键退出）> 只读态（READ_ONLY / Context 降级）> partial 数据完整性提示（复用 PartialDataBanner 语义）。

## 5. 权限过滤规则（沿用 permissions.js routeRedirect 现行策略，路径映射到新前缀）

| 角色 | 默认落地 | 可见路径 |
|---|---|---|
| PLATFORM_ADMIN | `/console/overview` | 仅 `/console/*` + `/console/login`；代客中（is_impersonating）临时进入该租户 Workspace 视图，横幅常显可退出 |
| FACTORY_COLLABORATOR | `/factory/products` | 仅 `/factory/*`；访问 `/app/*`、`/console/*` 一律重定向回 `/factory/products` |
| COMPLIANCE | `/app/compliance/approvals` | 白名单（旧 APPROVER_PATHS+前缀映射到新路径）：`/app`、`/app/analytics/bi`、`/app/listings`（含 `/:id` 前缀）、`/app/compliance`（含 `/approvals`）、`/app/launch`（含 `/:id`）；其余重定向到落地页 |
| OWNER | `/app` | 全部 `/app/*`（settings/team 需 canAdmin） |
| OPERATOR / READ_ONLY | `/app` | 全部 `/app/*` 减去 `/app/settings/ai`、`/app/settings/team`、`/app/compliance/approvals`（NON_OWNER_HIDDEN_PATHS 语义）；READ_ONLY 额外全站隐藏写按钮（fail-closed `can()`） |
| 未登录 | — | 仅 `/console/login` |

实现约束：
- `can()/hasPermission()` 继续以后端 workspace-context 为唯一权威源，fail-closed（D24）原样保留；菜单过滤与路由守卫同源（同一导航纯模块产出菜单与白名单，禁止双事实源）。
- 按钮级权限沿用 key 口径（页面操作权限对照表.md），V9 不新增权限 key。
- `/console/audit` 不再使用 query 子态，删除 `?tab=audit` 语义。

## 6. 侧栏行为规范

- **展开/收起**：桌面默认展开（240px），可收起为图标栏（64px），状态存 localStorage（`v9_sidebar_collapsed`）；移动端抽屉式。
- **高亮**：当前路由精确匹配叶子 path；参数详情路由高亮其父列表项（如 `/app/products/:id` 高亮「商品池」）。
- **收藏**：每域页面可标星（localStorage `v9_nav_favorites`），收藏项聚合在侧栏顶部「常用」分组；纯前端能力，不依赖后端。
- **域折叠**：默认展开当前所在域，其余折叠；记忆上次手动展开域。
- **徽标**：合规工作台（待审批数=actions/listings review 队列，取自已接端点）、风险巡检（alerts 未确认数）两类，其余不显示徽标。
