# 前端实施计划（FRONTEND_IMPLEMENTATION_PLAN）

> 最后更新：2026-10-13
> 状态：FROZEN_FOR_IMPLEMENTATION（UX-00 蓝图；冻结口径 v1.0）
> 维护者：架构师
> 上位依据：`docs/FRONTEND_UX_PROGRESS.md` §0 冻结口径 v1.0
> 范围：UX-01..UX-05 文件级可执行计划、公共接口冻结清单、验收命令、回滚点

---

## 0. 阶段总览

| 阶段 | 目标 | 依赖 | 状态 |
|---|---|---|---|
| UX-00 | 全站审计 + 统一蓝图冻结（本批文档） | — | 进行中 |
| UX-01 | 设计系统与框架基座 | UX-00 | 未开始 |
| UX-02 | 信息架构重构（菜单 + 路由归位 + 权限态可见） | UX-01 | 未开始 |
| UX-03 | 商品经营与上线体验统一 | UX-01 | 未开始 |
| UX-04 | 其它业务域页面状态覆盖补齐 | UX-01（组件就绪） | 未开始 |
| UX-05 | 全旅程验收 | UX-02/03/04 | 未开始 |

并行关系：UX-02 ∥ UX-03 可并行（文件集不重叠）；UX-04 与 UX-03 文件隔离。

---

## 1. 需先冻结的公共接口（多 Agent 不得同改）

| 文件 | 为何冻结 | 冻结方式 |
|---|---|---|
| `frontend/src/views/Layout.vue` + `frontend/src/composables/navigation.js` | 菜单/角色可见性唯一源（UX-02 起菜单结构与角色过滤在 `frontend/src/composables/navigation.js`） | 先定 IA + 菜单数据结构（SidebarNav props），再冻结 |
| `frontend/src/router.js` | 路由与守卫唯一源 | 冻结路由表与 meta（只允许新增路由，不改既有语义） |
| `frontend/src/permissions.js` | 分流唯一源（D24） | 冻结；只允许新增导出，不改 routeRedirect/defaultLanding 语义 |
| `frontend/src/api.js` | 全局拦截/错误信封 | 冻结错误信封约定（对象 detail 取 message） |
| `frontend/src/workspace.js` | Context 层（需改响应式） | **先冻结新契约**（响应式 context + 订阅接口）再动 |
| `frontend/src/styles.css` + frontend/src/styles/tokens.css | 设计令牌基座 | 先冻结 token 命名（见设计系统文档 §2） |
| `frontend/src/composables/launchCenter.js` | Launch 数据层契约（T03 冻结） | 冻结纯函数签名，组件只消费 |

冻结后，任何阶段修改这些文件必须单点提交并由集成阶段（UX-05）复核。

---

## 2. UX-01 设计系统与框架基座

- **目标**：建令牌层 + Workspace 响应式与切换入口 + 公共状态组件骨架；修 Discovery 缺陷。
- **新建文件**：frontend/src/styles/tokens.css、frontend/src/components/StatusTag.vue、EmptyState.vue、ErrorState.vue、StateWrapper.vue、WorkspaceSwitcher.vue（均在 `frontend/src/components/` 下）。
- **修改文件**：`frontend/src/styles.css`（引用 token）、`frontend/src/main.js`（引入 tokens）、`frontend/src/workspace.js`（Context 响应式 + 订阅）、`frontend/src/views/Discovery.vue`（补 can import）、`frontend/src/views/Layout.vue`（挂 WorkspaceSwitcher）。
- **单一所有权 Agent**：A（基座）。
- **依赖**：UX-00。
- **验收命令**：`cd frontend && npm test`（不低于 119 passed）、`cd frontend && npm run build`、新增 tokens/workspace/组件的 vitest 用例；浏览器手测切换 Workspace 后菜单刷新。
- **回滚点**：git 提交「frontend: UX-01 令牌与框架基座」。

Workspace 切换 6 项必达（冻结口径 v1.0）：菜单刷新 / 数据失效重取 / 筛选重置 / 待办重取 / AI 会话清空 / 缓存清理。根因证据（UX-01 前）：`frontend/src/workspace.js` 把 Context 存于普通变量（非响应式，`computed` 读它不产生依赖）、`frontend/src/views/Layout.vue` 的 `menus` computed 因此无响应式依赖；UX-01 已改为 `contextRef`（`ref`）+ 订阅接口 `subscribeWorkspaceChange`（详见 `frontend/src/workspace.js`）。

---

## 3. UX-02 信息架构重构

- **目标**：11 域菜单（`docs/FRONTEND_INFORMATION_ARCHITECTURE.md` §2）+ 面包屑/页头 + 权限态可见。
- **新建文件**：frontend/src/components/SidebarNav.vue、Breadcrumb.vue、PageHeader.vue、NoPermissionState.vue。
- **修改文件**：`frontend/src/views/Layout.vue`、`frontend/src/router.js`、`frontend/src/permissions.js`（仅加白名单）、`frontend/src/views/Users.vue`（角色枚举统一为大写，见进度文档 UX-B8）。
- **单一所有权 Agent**：B（IA）。
- **依赖**：UX-01。
- **验收命令**：`cd frontend && npm test`（`frontend/tests/router.test.js`、`frontend/tests/router-guard.test.js`、`frontend/tests/permissions.test.js`、`frontend/tests/permissions-can.test.js` 全绿）；浏览器 E2E 六角色进站落点正确。
- **回滚点**：git 提交「frontend: UX-02 信息架构重构」。

---

## 4. UX-03 商品经营与上线体验统一

- **目标**：Launch 为核心上线工作台；未接通动作显式化；cross-border 前端接通；消费 BFF 待办。
- **新建文件**：frontend/src/composables/workbenchTodo.js、frontend/src/components/NextActionButton.vue、ApprovalActionBar.vue、NotConfiguredState.vue、WaitingExternalState.vue。
- **修改文件**：`frontend/src/views/LaunchCenter.vue`、`frontend/src/views/LaunchDetail.vue`、`frontend/src/components/LaunchStepPanel.vue`、`frontend/src/components/LaunchActionDialog.vue`、`frontend/src/views/Listings.vue`、`frontend/src/views/Pricing.vue`（透传 destination_country）、`frontend/src/components/PublishActions.vue`。
- **后端（可选，需评审）**：新增只读 BFF，落 `backend/app/routers/`（workbench 模块）。
- **单一所有权 Agent**：C。
- **依赖**：UX-01。
- **验收命令**：`cd backend && python -m pytest -q`（≥ 927）、`cd frontend && npm test`、`cd backend && python scripts/launch_e2e.py`。
- **回滚点**：git 提交「frontend: UX-03 商品与上线体验」。

---

## 5. UX-04 其它业务域页面状态覆盖补齐

- **目标**：给缺空态/错误态的页面补 LOADING/EMPTY/ERROR/NO_PERMISSION（10 态模型）。
- **新建文件**：frontend/src/components/MetricCard.vue、DataTableToolbar.vue、ObjectPicker.vue、AiSuggestionCard.vue、RiskAlert.vue、PartialDataBanner.vue。
- **修改文件**（分批，切勿与 C 同文件）：`frontend/src/views/Dashboard.vue`、`frontend/src/views/Workflows.vue`、`frontend/src/views/Ads.vue`、`frontend/src/views/Users.vue`、`frontend/src/views/Alerts.vue`、`frontend/src/views/AiDecisions.vue`、`frontend/src/views/Refunds.vue`、`frontend/src/views/Orders.vue`、`frontend/src/views/Finance.vue`、`frontend/src/views/BI.vue`、`frontend/src/views/Settings.vue`、`frontend/src/views/FactoryPortal.vue`、`frontend/src/views/ComplianceWorkbench.vue`、`frontend/src/views/Support.vue`、`frontend/src/views/Settlements.vue`、`frontend/src/views/Suppliers.vue`、`frontend/src/views/Shops.vue`。
- **单一所有权 Agent**：D（分批）。
- **依赖**：UX-01（状态组件就绪）。
- **验收命令**：逐页 `cd frontend && npm run build` + 新增组件快照/交互测试；`cd frontend && npm test`。
- **回滚点**：按批次 git 提交。

---

## 6. UX-05 全旅程验收与集成

- **目标**：全局联调、E2E、文档同步、BFF 落地验收。
- **新建文件**：docs/FRONTEND_UX_ACCEPTANCE.md（QA 产出）。
- **修改文件**：`docs/FRONTEND_UX_PROGRESS.md`（阶段状态/证据/遗留风险）、`docs/FRONTEND_INFORMATION_ARCHITECTURE.md`（如冻结口径变更）、`docs/DOCUMENT_MAP.md`（新增文档登记）。
- **单一所有权 Agent**：E（集成）。
- **依赖**：UX-02 / UX-03 / UX-04。
- **验收命令（全绿门槛）**：
  - `cd frontend && npm test` 不低于基线（当前 119 passed）；
  - `cd frontend && npm run build` 成功；
  - `cd backend && python -m pytest -q` 不低于 `docs/baseline.json`（以实际 927 为准）；
  - `cd backend && python -m ruff check .` 全绿；
  - `cd backend && python scripts/check_docs_consistency.py --json` 的 total=0；
  - `cd backend && python scripts/e2e_feasibility.py` 与 `cd backend && python scripts/launch_e2e.py` 全 PASS。
- **回滚点**：git 提交「frontend: UX-05 验收与集成」。

---

## 7. 保持不变量（全阶段）

- 双模式（GUIDED / PROFESSIONAL）同一数据/API/权限，禁止两套系统。
- B03–B09 能力显式「未接入」，禁止伪造成功。
- 权限判断一律走 `frontend/src/permissions.js` 的 can()/hasPermission（Context 为权威），禁止读 legacy 角色推导权限（D24）。
- 页面状态遵循 10 态模型：LOADING / EMPTY / NO_PERMISSION / NOT_CONFIGURED / NO_DATA / WAITING_EXTERNAL / PARTIAL_DATA / ERROR / SUCCESS / UNKNOWN。
