# 前端设计系统（FRONTEND_DESIGN_SYSTEM）

> 最后更新：2026-10-13
> 状态：FROZEN_FOR_IMPLEMENTATION（UX-00 蓝图；冻结口径 v1.0）
> 维护者：架构师
> 上位依据：`docs/FRONTEND_UX_PROGRESS.md` §0.4 / §0.5
> 范围：设计令牌规范 + 20 类公共组件冻结清单 + 两条可用性原则的组件级方案

---

## 1. 现状（as-is）

### 1.1 无令牌层
- `frontend/src/styles.css` 全文 9 行（body / .page / .mb16 / .mr8 / .kpi-card / .chart-box）**UX-01 前无 :root、无 CSS 变量**；UX-01 已新增 `frontend/src/styles/tokens.css`，并令 `styles.css` 改为引用 `var(--color-*)`。
- 间距/字号/圆角写在各组件内联 style 或 scoped CSS，值不统一（12 / 13 / 16 px 混用）。

### 1.2 硬编码色值遍布
全仓 grep：**24 个 views 含硬编码 hex**。频次 Top：Dashboard 8、Support 7、Refunds 6、PlatformAdmin 5、Alerts 5、Shops/Listings/Workflows/Pricing/Products 各 3-4。

### 1.3 实际调色盘（= Element Plus 默认）
| 语义 | 值 | 典型出处 |
|---|---|---|
| 侧栏底 | #1f2d3d | `frontend/src/views/Layout.vue:3`（=`--color-sidebar`） |
| 主色 primary | #409EFF | `frontend/src/styles/tokens.css:24`（`--color-primary`，= Element Plus 默认） |
| success | #67C23A | `frontend/src/components/LaunchTimeline.vue:64`（`.node.done`） |
| warning | #E6A23C | `frontend/src/views/LaunchCenter.vue:280`（`.affected`） |
| danger | #F56C6C | `frontend/src/components/LaunchTimeline.vue:67`（`.node.failed`） |
| info/次要 | #909399 | `frontend/src/components/LaunchTimeline.vue:57`（`.seq`） |
| 正文 | #303133 | `frontend/src/views/Layout.vue:145`（`.user-chip`） |
| 背景 | #f5f7fa | `frontend/src/styles/tokens.css:29`（`--color-bg`；`styles.css:1` 已改为引用该变量） |
| 边框 | #dcdfe6 / #e4e7ed | `frontend/src/components/LaunchTimeline.vue:60,73` |

---

## 2. 目标令牌规范（TO-BE）

新增 tokens 文件：frontend/src/styles/tokens.css（`frontend/src/styles/` 目录下，由 `frontend/src/main.js` 在 `frontend/src/styles.css` 之前引入）。命名规范：

| 前缀 | 用途 | 必列令牌 |
|---|---|---|
| --color-* | 语义色 | --color-primary(#409EFF)、--color-success(#67C23A)、--color-warning(#E6A23C)、--color-danger(#F56C6C)、--color-info(#909399)、--color-bg(#f5f7fa)、--color-text(#303133)、--color-text-secondary(#909399)、--color-border(#dcdfe6)、--color-sidebar(#1f2d3d) |
| --space-* | 间距 | --space-1(4px)、--space-2(8px)、--space-3(12px)、--space-4(16px)、--space-5(24px)、--space-6(32px) |
| --font-* | 字号/字重 | --font-size-xs(12px)、--font-size-sm(13px)、--font-size-md(14px)、--font-size-lg(16px)、--font-size-xl(18px)、--font-size-display(26px)、--font-weight-regular(400)、--font-weight-medium(500)、--font-weight-bold(700) |
| --radius-* | 圆角 | --radius-sm(4px)、--radius-md(8px)、--radius-round(999px) |
| --shadow-* | 阴影 | --shadow-card、--shadow-pop、--shadow-focus |

规则：**Element Plus 变量同源映射**（`--el-color-primary: var(--color-primary)` 等）；两者只允许在 tokens 文件里出现字面量色值，业务组件一律引用 `var(--color-*)`。

---

## 3. 公共组件 20 类（冻结清单）

命名统一为 PascalCase，落位 frontend/src/components/ 下的同名 .vue 文件（`frontend/src/components/`）。「替代」列为现存散落实现（`文件:行号`）。

| 组件 | 关键 props | 替代的散落实现 | 归属阶段 |
|---|---|---|---|
| StatusTag | status:string; table?:'launch'\|'run'\|'risk'; size? | `frontend/src/views/RunStatus.vue`（原状态字典；UX-01 后其为 `frontend/src/components/StatusTag.vue` 的薄封装） | UX-01 |
| EmptyState | reason:'NO_DATA'\|'NO_PERMISSION'\|'NOT_CONFIGURED'\|'NO_MATCH'\|'REQUEST_FAILED'; hint?; action? | 仅 `frontend/src/views/LaunchCenter.vue`（`el-empty` 空态）有；其余页无 | UX-01 |
| ErrorState | message:string; traceId?; onRetry:()=>void | 无（仅 toast `frontend/src/api.js:31`） | UX-01 |
| NoPermissionState | required:string; scope? | 无（按钮消失无说明） | UX-02 |
| NotConfiguredState | capability:string; reason:string | 「未接入」占位取 `frontend/src/composables/launchCenter.js` 的 `NOT_CONNECTED` / `notConnected()` | UX-03 |
| WaitingExternalState | owner:string; since?; hint? | Launch 内联（`frontend/src/components/LaunchStatusSummary.vue:33-41`） | UX-03 |
| PartialDataBanner | missing:string[]; note? | 无（RunStatus 仅文案） | UX-04 |
| PageHeader | title; breadcrumb; actions slot | `frontend/src/views/Layout.vue:10` 仅 title | UX-02 |
| Breadcrumb | items:{label,to?}[] | 无 | UX-02 |
| WorkspaceSwitcher | value; onChange(id) | 无（`frontend/src/workspace.js` 的 `switchWorkspace()`/`loadWorkspaces()` 有封装无 UI） | UX-01 |
| SidebarNav | domains:{key,label,children}[]; activePath | `frontend/src/views/Layout.vue:5`（`<SidebarNav>`）+ `frontend/src/composables/navigation.js` | UX-02 |
| AiSuggestionCard | title; suggestion; source:'rule'\|'llm'; apply? | Discovery/Ads/Pricing 各自内联 | UX-04 |
| NextActionButton | action; executable; reason?; onRun | `frontend/src/components/LaunchStepPanel.vue:47-53` | UX-03 |
| ApprovalActionBar | items; onApprove; onReject; onExecute | `frontend/src/components/PublishActions.vue` + Ads + ComplianceWorkbench | UX-03 |
| RiskAlert | level:'low'\|'mid'\|'high'; issues:{text}[] | `frontend/src/views/Listings.vue` / Compliance 内联 | UX-04 |
| MetricCard | label; value; trend?; loading? | `frontend/src/styles.css:5-7`（.kpi-card）+ Dashboard 内联 | UX-04 |
| DataTableToolbar | filters slot; onRefresh; onExport | 各页 el-card filters（如 `frontend/src/views/LaunchCenter.vue:3-26`） | UX-04 |
| ObjectPicker | modelValue; fetchOptions:()=>Promise<{id,label}[]> | Products/Listings/LaunchCenter 各处 el-select | UX-04 |
| JourneyGuideCard | step; steps; hint | 无（引导缺失） | UX-05 |
| StateWrapper | state:'loading'\|'empty'\|'error'\|'nopermission'\|'ready'; slots | 各页手写 v-loading/el-empty（见 IA 文档 §2.3 状态矩阵） | UX-01 |

---

## 4. 两条可用性原则的组件级方案

### 4.1 「状态不能只靠颜色区分」
- **达标现状**：Launch 时间线 `frontend/src/components/LaunchTimeline.vue:60-68` 用 border-left 色**同时**配 el-tag 文字（`frontend/src/components/LaunchTimeline.vue:12-14`）。
- **不达标现状（纯颜色）**：`frontend/src/views/LaunchCenter.vue:81`（`.affected`）、`frontend/src/components/LaunchStepPanel.vue:103-104`（`.missing`/`.muted`）。
- **方案**：所有状态一律由 `StatusTag` 渲染（图标 + 文字 + 颜色三要素）；`RiskAlert` 强制「文字等级 + 图标」，禁止仅用色块。令牌层不引入仅靠色相的语义。
- **验收**：任一状态在去色（灰度）截图下仍可辨（E2E 灰度断言）。

### 4.2 「危险操作统一 danger + 二次确认」
- **达标现状**：`frontend/src/components/LaunchActionDialog.vue:4-8`（高风险 warning + 二次确认）、`frontend/src/components/PublishActions.vue:23`（拒绝按钮 type=danger）。
- **不达标现状**：删商品、清空演示数据、取消流程等靠 `ElMessageBox.confirm` 临时兜底，样式/措辞不统一。
- **方案**：新建 `RiskAlert` + `ApprovalActionBar` + `NextActionButton` 三件套；危险动作统一 `type="danger"` + `RiskAlert`（列出影响范围）+ 二次确认（高风险勾选、run 级动作需 note+confirm，遵循 `frontend/src/composables/launchCenter.js` 的 `actionPayload()` 契约，规则见同文件 `CONFIRM_PAYLOAD_ACTIONS`）。
- **验收**：全部危险操作入口具备 danger 样式与二次确认（E2E 断言）。

---

## 5. 迁移与回滚

- 迁移顺序：先落 tokens（不改视觉）→ 再逐页把硬编码色替换为 `var(--color-*)`（灰度回归）→ 再抽组件。
- 回滚点：每阶段 git 提交；tokens 为纯新增文件，回滚即删除引用。
- 守卫：`frontend/tests/` 前端测试不得下降（当前 119 passed）；新增 tokens 与组件需配套测试。
