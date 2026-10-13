# 全平台前端信息架构与用户体验统一优化 — 进度追踪

> 最后更新：2026-10-13
> 维护者：主理人（软件团队交付总监）
> 上位依据：全平台前端 IA 与 UX 统一优化总调度指令 V1.0

本文件是本次前端体验统一优化的**唯一进度事实源**，持续维护，不归档。
每批次实施完成后必须在此更新「阶段状态」「关键决策」「验证证据」「遗留风险」。

---

## 0. 冻结口径 v1.0（全站统一，未经决策不得改动）

### 0.1 一级信息架构（11 域，页面本体不重写，仅重新归类 + 调整导航）

| # | 一级域 | 归入页面 | 说明 |
|---|---|---|---|
| 1 | 首页 | `/dashboard` | 由固定 Dashboard 改造为「经营工作台」，回答 6 问 |
| 2 | 市场机会 | `/discovery` | 趋势 / 扩展 / 选品 / 机会评分 |
| 3 | 商品经营 | `/products`、`/listings`、`/launch`、`/compliance`(下沉二级「合规检测」) | Launch Center 为核心上线工作台 |
| 4 | 货源中心 | `/suppliers` | 供应商 / 机会匹配 / 采购单 |
| 5 | 销售渠道 | `/shops` | 销售店铺 + 类目映射；目标市场聚合在此 |
| 6 | 订单履约 | `/orders`、`/settlements` | 供应商应付口径 |
| 7 | 客户售后 | `/refunds`、`/support` | |
| 8 | 经营优化 | `/pricing`、`/ads`、`/alerts` | |
| 9 | 数据分析 | `/bi`、`/finance` | |
| 10 | AI 运营 | `/knowledge`、`/ai-decisions`、`/workflows`(高级入口) | |
| 11 | 设置与管理 | `/settings`、`/users` | |

**独立域**（不并入 11 域，角色专属菜单）：`/platform-admin`（PLATFORM_ADMIN）、`/factory-portal`（FACTORY_COLLABORATOR）。

**框架 / 原子**（不入导航）：`/login`、`Layout.vue`、`AiAssistant.vue`（全局悬浮球）、`RunStatus.vue`（应迁移为 `components/StatusTag.vue`）。

**合并去重清单**：

| 重复项 | 现状 | 处置 |
|---|---|---|
| 合规检测 | `Compliance.vue` 与 `ComplianceWorkbench.vue` 双页 | 工作台收编，Compliance 降为合规员二级入口 |
| 供应商账龄 | `Suppliers.vue` 账龄 tab 与 `Settlements.vue` 同调 `/settlements/summary` | 账龄收口到 Settlements |
| AI 日志 | `Settings.vue` / `AiDecisions.vue` / `PlatformAdmin.vue` 三处 | 合并为一处统一 AI 日志视图 |
| 审批动作 | `PublishActions` / Ads `/actions` / Launch actions 三套 | 统一「待我审批」 |
| 状态字典 | `views/RunStatus.vue`(小写) 与 `composables/launchCenter.js`(大写) 双事实源 | 统一为一套 |

### 0.2 双体验模式（GUIDED / PROFESSIONAL）

同一数据、同一 API、同一权限、同一业务规则，仅**展示密度与引导程度**不同；切换偏好按用户持久化。**禁止做成两套系统**。

### 0.3 首页 6 问

在做什么 / 进展如何 / 今天最重要 / 哪些要人工 / AI 完成了什么 / 哪些异常 → 另加「下一步动作」。

### 0.4 设计令牌

新增 `frontend/src/styles/tokens.css`，`:root` 变量命名规范：`--color-*`、`--space-*`、`--font-*`、`--radius-*`、`--shadow-*`。
映射 Element Plus 默认：primary `#409EFF` / success `#67C23A` / warning `#E6A23C` / danger `#F56C6C` / info `#909399`；背景 `#f5f7fa`；正文 `#303133` / 次要 `#909399` / 边框 `#dcdfe6`。

### 0.5 公共组件 20 类（冻结清单）

`StatusTag`、`EmptyState`、`ErrorState`、`NoPermissionState`、`NotConfiguredState`、`WaitingExternalState`、`PartialDataBanner`、`PageHeader`、`Breadcrumb`、`WorkspaceSwitcher`、`SidebarNav`、`AiSuggestionCard`、`NextActionButton`、`ApprovalActionBar`、`RiskAlert`、`MetricCard`、`DataTableToolbar`、`ObjectPicker`、`JourneyGuideCard`、`StateWrapper`。

### 0.6 Workspace 切换（必改项）

Context 改为响应式 + 订阅；新增 `WorkspaceSwitcher`（复用已有封装 `/me/workspaces`、`/me/workspaces/{id}/switch`，前端已有调用能力但**无 UI 入口**）。切换后必须：菜单刷新 / 数据失效重取 / 筛选重置 / 待办重取 / AI 会话清空 / 缓存清理。**6 项现状 5 项未处理、1 项部分**。

### 0.7 契约红线

复用现有 API，**禁止重复 Service**；BFF **仅只读聚合**。新增只读聚合：`GET /workbench/todo`（跨域待办）、`GET /workbench/overview`（首页 6 问）。不新增写端点。

### 0.8 未接通业务能力（B03–B09）

显式展示「未接入 + 原因」，**禁止伪造成功**、**禁止只有 409 的按钮**。`CONFIRM_ACTIVATION` 属 `WAITING_EXTERNAL`，不得宣称「已上线」。

### 0.9 页面状态 10 态

`LOADING` / `EMPTY` / `NO_PERMISSION` / `NOT_CONFIGURED` / `NO_DATA` / `WAITING_EXTERNAL` / `PARTIAL_DATA` / `ERROR` / `SUCCESS` / `UNKNOWN`。

---

## 1. 阶段状态

| 阶段 | 目标 | 状态 | 证据 |
|---|---|---|---|
| UX-00 | 全站审计 + 统一蓝图冻结 | ✅ 完成 | 8 份蓝图文档落盘（PM 3 + 架构师 4 + 主理人 1）；`DOCUMENT_MAP.md` 已登记 9 份 `FRONTEND_*.md` |
| UX-01 | 设计系统与框架基座 | ✅ 完成 | commit `3097c86`；`npm test` 119→128；build ✓；QA 独立验证 A/B/C/D 全 PASS |
| UX-02 | 信息架构重构（菜单 + 路由归位 + 权限态可见） | ✅ 完成 | commit `7ca69cb`；`npm test` 128→142；build ✓；QA 独立验证 E/F 全 PASS，补测 `7bb02ef` |
| UX-03 | 商品经营与上线体验统一 | 🔄 进行中 | 已派发（纯前端：Launch 创建入口 / 未接通动作显式化 / 深链返回闭环） |
| UX-04 | 首页经营工作台 + 其它业务域页面状态覆盖补齐 | 未开始 | — |
| UX-05 | 全旅程验收 | 未开始 | — |

---

## 2. 文档索引（本次新增，共 9 份）

| 文档 | 用途 | 负责 |
|---|---|---|
| `FRONTEND_UX_AUDIT.md` | 全站体验与能力缺口审计 | 产品经理 |
| `FRONTEND_INFORMATION_ARCHITECTURE.md` | as-is→to-be 信息架构与权限分流 | 架构师 |
| `FRONTEND_PAGE_MATRIX.md` | 全站 30 页页面矩阵 | 产品经理 |
| `FRONTEND_DESIGN_SYSTEM.md` | 设计令牌 + 20 类公共组件规范 | 架构师 |
| `FRONTEND_USER_JOURNEYS.md` | A–H 旅程 + A–G 用户画像与断点 | 产品经理 |
| `FRONTEND_API_ALIGNMENT.md` | 11 域端点对照 + BFF 只读聚合方案 | 架构师 |
| `FRONTEND_IMPLEMENTATION_PLAN.md` | UX-01..UX-05 文件级实施计划 | 架构师 |
| `FRONTEND_UX_PROGRESS.md` | 本文件，进度事实源 | 主理人 |
| `FRONTEND_UX_ACCEPTANCE.md` | 全旅程验收报告 | QA（UX-05 产出） |

---

## 3. 关键决策记录（本次）

| 编号 | 决策 | 理由 |
|---|---|---|
| UX-D1 | 采用 11 域一级 IA，页面本体不重写 | 避免全站重写；只调导航与归类，风险最小 |
| UX-D2 | `/platform-admin`、`/factory-portal` 保持独立角色域 | 与租户菜单完全隔离是既有设计，强行并入会破坏权限模型 |
| UX-D3 | `RunStatus.vue` 迁移为 `components/StatusTag.vue` 并统一状态字典 | 消除双事实源，是状态一致性的前置条件 |
| UX-D4 | Workspace Context 改响应式（先冻结新契约再动） | 当前为非响应式模块变量，是「切换不刷新」的根因 |
| UX-D5 | 首页与待办走只读 BFF 聚合，不新增写端点 | 遵守「复用现有 API、禁止重复 Service」红线 |
| UX-D6 | `Discovery.vue` 缺失 `can` import 作为 UX-01 首批修复项 | 静态可判的渲染期缺陷，现有测试无组件级覆盖 |
| UX-D7 | 令牌本批**只收敛为与 Element Plus 默认逐字相同的取值**（视觉零变化），不顺手改配色 | 避免令牌化与视觉改版混在一起，冲突时无法归因 |
| UX-D8 | 「返回上一步」内置在 `components/PageHeader.vue`（读 `route.query.return_to` 并做白名单校验），而非逐个改造专业页 | 一处实现即覆盖 Products/Listings/Shops 等所有深链落地页，符合「不逐页重做导航」原则 |
| UX-D9 | 后端只读 BFF（`/workbench/todo`、`/workbench/overview`）与 Pricing 跨境的 `destination_country` 透传**后移到 UX-04**，与首页经营工作台同批 | 二者都服务于首页/待办聚合，同批落地可一次验收；UX-03 保持纯前端、零后端改动，风险最低 |

---

## 4. 已确认缺陷（待修）

| 编号 | 缺陷 | 证据 | 状态 |
|---|---|---|---|
| UX-B1 | `Discovery.vue` 模板调用 `can('product:write')` 但未 import，且 `main.js` 无 `globalProperties.can` → 渲染期抛错 | `views/Discovery.vue:10-11`；`main.js` 无 `globalProperties` | ✅ 已修（`3097c86`，`:151` 补 import；QA C6 PASS） |
| UX-B2 | Workspace 无切换入口，`switchWorkspace()`/`loadWorkspaces()` 无 UI 调用点 | `workspace.js:118/133`；`Layout.vue:27-31,168-185` | ✅ 已修（`3097c86`，新增 `WorkspaceSwitcher` 挂入 `Layout.vue:23`） |
| UX-B3 | Context 为非响应式模块变量，切换后菜单/数据不刷新 | `workspace.js:22`；`Layout.vue:85-90,143-158` | ✅ 已修（`3097c86`，改为 `ref` + `subscribeWorkspaceChange`；QA B4/B5 PASS） |
| UX-B4 | 仅 10/30 页有空态、仅 2 页有内联错误态；错误全靠瞬时 toast 无重试 | 架构师 §2.3 状态覆盖审计 | ⏳ UX-04 |
| UX-B5 | 无设计令牌，24 个 views 硬编码色值 | `styles.css` 9 行无 `:root` | ✅ 已修（`3097c86`，新增 `styles/tokens.css`；QA A1–A3 PASS） |
| UX-B6 | `/launch` 无「创建上线流程」入口，后端 `POST /launch` 已存在 | `routers/launch.py:83`；`composables/launchCenter.js` 无封装 | 🔄 UX-03 处理中 |
| UX-B7 | Launch 深链白名单仅 `/launch*`（`RETURN_WHITELIST = ['/launch']`），指向 `/listings` 后回不到原步骤 | `composables/launchCenter.js:18` | 🔄 UX-03 处理中（扩为 `/launch,/listings,/products,/shops`） |
| UX-B8 | `Users.vue` 角色下拉仍为 legacy 小写枚举，与 Context 大写双轨 | `Users.vue:82-87` | ✅ 已修（`7ca69cb`，展示大写 ↔ 提交 legacy 原值映射；后端仅接受 legacy，无需后端改动） |

---

## 5. 验证基线（每次批次必须复核）

| 项 | 命令 | 当前基线 |
|---|---|---|
| 前端单测 | `cd frontend && npm test` | 142 passed（UX-00 时 119 → UX-01 128 → UX-02 142；QA 补测 +4） |
| 前端构建 | `cd frontend && npm run build` | ✓ 通过（UX-01 11.74s / UX-02 10.36s） |
| 后端单测 | `cd backend && python -m pytest -q` | 927 passed（`docs/baseline.json` 记 646，已过时，以实际为准） |
| 代码检查 | `cd backend && python -m ruff check .` | 全绿 |
| 文档一致性 | `cd backend && python scripts/check_docs_consistency.py --json` | total=1（唯一项：`FRONTEND_UX_ACCEPTANCE.md` 尚未产出，UX-05 消除） |
| E2E 可行性 | `cd backend && python scripts/e2e_feasibility.py` | 7/7 PASS |
| Launch 闭环 | `cd backend && python scripts/launch_e2e.py` | 14/14 PASS |

> 说明：本文件不在门禁的 `LIVE_DOCS` 名单内，故其「N passed」写法不参与 A 项基线数字校验。

---

## 6. 变更日志

| 日期 | 阶段 | 变更 |
|---|---|---|
| 2026-10-13 | UX-00 | 完成全站审计（PM 页面矩阵/A–H 旅程/首页诊断；架构师 as-is IA/框架/设计系统/契约）；冻结口径 v1.0；建立本进度文档 |
| 2026-10-13 | UX-00 | 8 份蓝图文档落盘并登记 `DOCUMENT_MAP.md`（PM：UX_AUDIT/PAGE_MATRIX/USER_JOURNEYS；架构师：INFORMATION_ARCHITECTURE/DESIGN_SYSTEM/API_ALIGNMENT/IMPLEMENTATION_PLAN；主理人：UX_PROGRESS） |
| 2026-10-13 | UX-01 | commit `3097c86`：新增 `styles/tokens.css`、`StatusTag/EmptyState/ErrorState/StateWrapper/WorkspaceSwitcher`、`composables/statusDict.js`；`workspace.js` 改 `ref` 响应式 + `subscribeWorkspaceChange`/`getWorkspaceEpoch`；`RunStatus.vue` 收编；修 `Discovery.vue` 缺失 `can` import。`npm test` 119→128，build ✓ |
| 2026-10-13 | UX-01/02 | QA 独立验证（基于 `git show` 提交内容 + 指定测试子集）：A–F 13 项全 PASS，测试 96/96（+补测 4 → 100），源码/测试缺陷 0。补测提交 `7bb02ef` |
| 2026-10-13 | UX-02 | commit `7ca69cb`：新增 `composables/navigation.js`（11 域 + 六角色过滤）与 `SidebarNav/Breadcrumb/PageHeader/NoPermissionState`；`Layout.vue` 菜单改 11 域、header 改 PageHeader+Breadcrumb；`router.js` 纯新增 `meta.domain`；`Users.vue` 角色枚举对齐（展示大写 ↔ 提交 legacy）。`npm test` 128→142，build ✓ |
| 2026-10-13 | UX-03 | 派发实施（纯前端）：Launch「创建上线流程」入口、未接通动作显式化、深链返回闭环（白名单扩为 `/launch,/listings,/products,/shops` + `PageHeader` 返回按钮） |
