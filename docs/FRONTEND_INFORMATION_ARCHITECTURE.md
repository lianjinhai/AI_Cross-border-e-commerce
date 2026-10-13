# 前端信息架构（FRONTEND_INFORMATION_ARCHITECTURE）

> 最后更新：2026-10-13
> 状态：FROZEN_FOR_IMPLEMENTATION（UX-00 蓝图；冻结口径 v1.0）
> 维护者：架构师
> 上位依据：`docs/FRONTEND_UX_PROGRESS.md` §0 冻结口径 v1.0
> 范围：全站 as-is → to-be 信息架构、路由/菜单映射、权限分流规则、导航层级问题

---

## 1. as-is 现状信息架构

### 1.1 现一级菜单（5 组）→ 目标 11 域映射

现菜单定义见 `frontend/src/composables/navigation.js` 的 `BUSINESS_DOMAINS`（11 域）与 `PLATFORM_DOMAINS`/`FACTORY_DOMAINS`（UX-02 起从 `frontend/src/views/Layout.vue` 抽出），三套菜单按角色互斥由 `buildDomains()`（同文件）实现。下表「旧分组」列为 UX-02 前的 5 组菜单，已随重构移除。

| 旧分组（UX-02 前 Layout.vue） | 现条目 | 旧行号 | 目标 11 域归属 |
|---|---|---|---|
| 概览 | /dashboard、/bi、/alerts | 108-112 | 1 首页、9 数据分析、8 经营优化 |
| 商品 | /discovery、/products、/listings、/launch、/compliance-workbench、/compliance | 113-120 | 2 市场机会、3 商品经营 |
| 采购 | /shops、/suppliers、/pricing | 121-125 | 5 销售渠道、4 货源中心、8 经营优化 |
| 运营 | /ads、/orders、/refunds、/settlements、/finance、/support | 126-133 | 8 经营优化、6 订单履约、7 客户售后、9 数据分析 |
| 系统 | /workflows、/knowledge、/ai-decisions、/settings、/users | 134-140 | 10 AI 运营、11 设置与管理 |

结论：现 5 组按「类目/服务」堆放，与目标 11 域（按经营活动）不是一一对应，需重新归类（页面本体不重写，仅调导航与归类）。

### 1.2 路由全量（来源 `frontend/src/router.js:11-46` 的 `routes`）

`router.js` 共定义 27 条路由（含 `/login` 与 `/launch/:id` 深链接）。逐条 meta.title 与目标归属：

| 路径 | meta.title | 目标一级域 | 现菜单入口 |
|---|---|---|---|
| /login | —（`router.js:12`） | 框架/原子（不入导航） | 无 |
| /dashboard | 驾驶舱 | 1 首页 | ✅概览 |
| /discovery | 商品发现 | 2 市场机会 | ✅商品 |
| /products | 商品池 | 3 商品经营 | ✅商品 |
| /listings | Listing 工作台 | 3 商品经营 | ✅商品 |
| /compliance | 合规检测 | 3 商品经营（下沉二级） | ✅商品 |
| /compliance-workbench | 合规工作台 | 3 商品经营（合规员二级入口） | ✅商品 |
| /launch | 上线中心 | 3 商品经营（核心上线工作台） | ✅商品 |
| /launch/:id | 上线流程详情 | 3 商品经营（深链接） | 🔗深链接 |
| /shops | 店铺授权 | 5 销售渠道 | ✅采购 |
| /suppliers | 供应商 | 4 货源中心 | ✅采购 |
| /factory-portal | 工厂供给门户 | 独立域（FACTORY_COLLABORATOR） | ✅工厂门户 |
| /pricing | 动态定价 | 8 经营优化 | ✅采购 |
| /ads | 广告增长 | 8 经营优化 | ✅运营 |
| /orders | 订单管理 | 6 订单履约 | ✅运营 |
| /refunds | 售后管理 | 7 客户售后 | ✅运营 |
| /settlements | 账期结算 | 6 订单履约 | ✅运营 |
| /support | 智能客服 | 7 客户售后 | ✅运营 |
| /workflows | AI 工作流 | 10 AI 运营（高级入口） | ✅系统 |
| /knowledge | 知识库 | 10 AI 运营 | ✅系统 |
| /bi | BI 经营分析 | 9 数据分析 | ✅概览 |
| /finance | 财务工作台 | 9 数据分析 | ✅运营 |
| /alerts | 风险巡检 | 8 经营优化 | ✅概览 |
| /ai-decisions | AI 决策依据 | 10 AI 运营 | ✅系统 |
| /users | 用户与角色 | 11 设置与管理 | ✅系统（仅 OWNER） |
| /settings | AI 设置 | 11 设置与管理 | ✅系统（仅 OWNER） |
| /platform-admin | 平台管理 | 独立域（PLATFORM_ADMIN） | ✅平台控制台 |

### 1.3 三套菜单互斥逻辑（`frontend/src/composables/navigation.js` 的 `buildDomains()`）

| 身份 | 返回菜单 | 规则 | 行号 |
|---|---|---|---|
| PLATFORM_ADMIN（非代客） | `PLATFORM_DOMAINS` | 与业务菜单完全隔离，各分区由 /platform-admin 页内 el-tabs 承载 | `frontend/src/composables/navigation.js:117-127`、183 |
| FACTORY_COLLABORATOR | `FACTORY_DOMAINS` | 仅「工厂门户 /factory-portal」 | `frontend/src/composables/navigation.js:130-139`、184 |
| COMPLIANCE | `BUSINESS_DOMAINS` 白名单过滤 | 允许集 `{/compliance-workbench,/dashboard,/bi,/listings,/compliance,/launch}` | `frontend/src/composables/navigation.js:187-189`（`COMPLIANCE_ALLOWED_PATHS` 142-144） |
| 非 OWNER（OPERATOR/READ_ONLY） | `BUSINESS_DOMAINS` 隐藏项 | 隐藏 `{/settings,/users,/compliance-workbench}` | `frontend/src/composables/navigation.js:191-195`（`NON_OWNER_HIDDEN_PATHS` 147-149） |
| OWNER | `BUSINESS_DOMAINS` 全量 | — | `frontend/src/composables/navigation.js:197-202` |

菜单可见性以 `roleKey()` 判定（定义于 `frontend/src/permissions.js`，Context 优先、legacy 兜底；`frontend/src/views/Layout.vue` 导入后传入 `buildDomains()`），与 `frontend/src/permissions.js` 路由分流同源。

---

## 2. to-be 目标信息架构（冻结口径 v1.0）

### 2.1 一级 11 域

| # | 一级域 | 归入页面 | 说明 |
|---|---|---|---|
| 1 | 首页 | /dashboard | 由固定 Dashboard 改造为「经营工作台」，回答 6 问 |
| 2 | 市场机会 | /discovery | 趋势 / 扩展 / 选品 / 机会评分 |
| 3 | 商品经营 | /products、/listings、/launch、/compliance（二级） | Launch Center 为核心上线工作台 |
| 4 | 货源中心 | /suppliers | 供应商 / 机会匹配 / 采购单 |
| 5 | 销售渠道 | /shops | 销售店铺 + 类目映射；目标市场聚合在此 |
| 6 | 订单履约 | /orders、/settlements | 供应商应付口径 |
| 7 | 客户售后 | /refunds、/support | — |
| 8 | 经营优化 | /pricing、/ads、/alerts | — |
| 9 | 数据分析 | /bi、/finance | — |
| 10 | AI 运营 | /knowledge、/ai-decisions、/workflows（高级入口） | — |
| 11 | 设置与管理 | /settings、/users | — |

**独立域**（不并入 11 域，角色专属菜单）：/platform-admin（PLATFORM_ADMIN）、/factory-portal（FACTORY_COLLABORATOR）。

**框架/原子**（不入导航）：/login、`frontend/src/views/Layout.vue`、`frontend/src/views/AiAssistant.vue`（全局悬浮球）、`frontend/src/views/RunStatus.vue`（应迁移为 components 下的 StatusTag）。

### 2.2 合并去重清单

| 重复项 | 现状 | 处置 |
|---|---|---|
| 合规检测 | Compliance 与 ComplianceWorkbench 双页 | 工作台收编，Compliance 降为合规员二级入口 |
| 供应商账龄 | Suppliers 账龄 tab 与 Settlements 同调 /settlements/summary | 账龄收口到 Settlements |
| AI 日志 | Settings / AiDecisions / PlatformAdmin 三处 | 合并为一处统一 AI 日志视图 |
| 审批动作 | PublishActions / Ads 的 /actions / Launch actions 三套 | 统一「待我审批」 |
| 状态字典 | `frontend/src/views/RunStatus.vue`（小写）与 `frontend/src/composables/launchCenter.js`（大写）双事实源 | 统一为一套（StatusTag） |

---

## 3. 权限分流规则全量（`frontend/src/permissions.js`）

守卫链：`frontend/src/router.js:61-76` 的 `beforeEach` → 有 token 时 `ensureWorkspaceContext()`（`frontend/src/workspace.js:124-128`）→ `routeRedirect({path, authenticated, user, context, impersonating})`。身份解析 `resolveIdentity`（`frontend/src/permissions.js:155-159`）：**Context 无条件优先，legacy 仅兜底**。

| 规则/常量 | 值 | 行号 |
|---|---|---|
| APPROVER_PATHS | {/compliance-workbench,/dashboard,/bi,/listings,/compliance} | 107 |
| APPROVER_PREFIX_PATHS | ['/launch']（精确 /launch 或 startsWith('/launch/')) | 110-113 |
| ADMIN_PATHS | {/users,/settings} | 114 |
| canWrite() | hasPermission('order:write') ?? false | 63 |
| canAdmin() | hasPermission('workspace:member:admin') ?? false | 64 |
| canApprove() | hasPermission('compliance:approve') ?? false | 65 |
| can(cap) | Context 有→结果；无→false（fail-closed，D24） | 82-86 |
| LEGACY_ROLE_MAP | admin/owner→OWNER、operator→OPERATOR、viewer→READ_ONLY、compliance_approver→COMPLIANCE、superadmin→PLATFORM_ADMIN、supplier→FACTORY_COLLABORATOR | 44-52 |
| routeRedirect 决策序 | /login：已登录→defaultLanding；未登录→/login；PLATFORM_ADMIN&&!代客→强制 /platform-admin；path===/platform-admin→/dashboard；FACTORY_COLLABORATOR→强制 /factory-portal；path===/factory-portal→/dashboard；COMPLIANCE 且非 approver 路径→/compliance-workbench；ADMIN_PATHS 且 role!==OWNER→/dashboard；否则放行(null) | 172-189 |
| defaultLanding | PLATFORM_ADMIN→/platform-admin；FACTORY_COLLABORATOR→/factory-portal；COMPLIANCE→/compliance-workbench；其余→/dashboard | 191-197 |

后端权威权限源：`backend/app/services/workspace_context.py:86-102` 的 ROLE_PERMISSIONS（OWNER/OPERATOR/READ_ONLY/COMPLIANCE/PLATFORM_ADMIN/FACTORY_COLLABORATOR，含 launch:read 与 launch:create/manage/price_review/stock_prepare/compliance_manage/label_manage/submit 与 compliance:check/approve）。

---

## 4. 导航层级问题清单（as-is）

> 下列问题为 UX-00 冻结时的 as-is（5 组菜单）；UX-02 已按 §2 归位。证据指向旧 `frontend/src/views/Layout.vue` 菜单定义（已移除），保留作历史对照。

| 编号 | 问题 | 证据 | 目标域影响 |
|---|---|---|---|
| N1 | 分组按「类目/服务」而非经营活动：采购组混入 店铺授权(渠道)+供应商(供给)+动态定价(定价)；运营组塞入 财务工作台+账期结算 | `frontend/src/views/Layout.vue`（UX-02 前「采购/运营」组） | 拆到 4/5/8/9 域 |
| N2 | 合规职责散落 3 处：/compliance、/compliance-workbench（商品组）、/alerts 风险巡检（概览组） | `frontend/src/views/Layout.vue`（UX-02 前合规入口散落于概览/商品组） | 3 商品经营 + 8 经营优化 |
| N3 | 系统组把 AI 能力（工作流/知识库/AI 决策依据/AI 设置）与组织管理（用户与角色）混合 | `frontend/src/views/Layout.vue`（UX-02 前「系统」组） | 10 AI 运营 + 11 设置与管理 |
| N4 | /ai-decisions（只读审计面）归系统而非治理/审计，与平台侧访问审计割裂 | `frontend/src/views/Layout.vue`（UX-02 前 /ai-decisions 归「系统」组） | 10 AI 运营 |
| N5 | /launch 与商品组并列，跨商品/合规/发布多域，未与 Listing 工作台形成发布流水线心智 | `frontend/src/views/Layout.vue`（UX-02 前 /launch 与商品组并列） | 3 商品经营 |
| N6 | 重复入口：/compliance 与 /compliance-workbench 并列，职责边界对用户不可见 | `frontend/src/views/Layout.vue`（UX-02 前 /compliance 与 /compliance-workbench 并列） | 3 商品经营 |

---

## 5. 标题 / 面包屑 / 高亮规则

- **as-is**（UX-00）：头部仅显示 `$route.meta.title`（`frontend/src/views/Layout.vue:10` 的 `<PageHeader :title>`），UX-02 前**全站无面包屑组件**（UX-02 已新增 `frontend/src/components/Breadcrumb.vue` 与 `frontend/src/components/PageHeader.vue`）；菜单高亮 `activeMenu`（`frontend/src/views/Layout.vue:115-119`）：/platform-admin 的 query `tab=audit` 单独高亮，`/launch/*` 归一到 /launch。
- **to-be**：新增公共组件 `Breadcrumb` 与 `PageHeader`（见 `docs/FRONTEND_DESIGN_SYSTEM.md`）。面包屑由「一级域 → 页面 → 详情」三段构成（如 商品经营 / 上线中心 / 流程详情）；`activeMenu` 的归一规则保留不变。
- **回归保护**：`frontend/tests/router.test.js` 与 `frontend/tests/router-guard.test.js` 覆盖现有分流语义，重构后必须保持通过（只允许新增断言，不得放宽）。
