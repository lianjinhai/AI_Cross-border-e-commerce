# FRONTEND V9 · 实施计划（UX-A 架构冻结）

> 对应阶段：UX-B（基座）→ UX-C（核心页）→ UX-D（经营闭环页）→ UX-E（AI/管理页）→ UX-F（验证切换）。基座 = 主设计 §4 决策：同仓新目录 `frontend-v9/`，切换后删除 `frontend/`。

## 1. UX-B 新前端工程基座

**文件清单**（均 frontend-v9/ 下）：

```
package.json / vite.config.js / index.html        （逐字复制自 frontend/，锁定依赖版本）
src/main.js / src/App.vue
src/styles/tokens.css（V9 扩展版）+ styles.css
src/app/router/index.js                           三空间路由表 + 守卫（routeRedirect 平移，路径映射 /app|/console|/factory）+ 旧路径 302 映射表
src/app/errors/NotFound.vue / Forbidden.vue / ServerError.vue
src/permissions/permissions.js、src/shared/workspace.js、src/shared/api/client.js   （纯模块平移+原测试同步拷贝）
src/shared/navigation/workspace-navigation.js / console-navigation.js / factory-navigation.js
src/shells/WorkspaceShell.vue / ConsoleShell.vue / FactoryShell.vue + ShellTopbar.vue / ShellSidebar.vue / ShellBanner.vue
src/components/ 第 1 批公共组件（≤10 个）：PageHeader、StatusBadge、EmptyState、ErrorState、LoadingState、MetricCard、FormSection、ConfirmDialog、DataTable、AppShell 骨架子件
src/shared/statusDict.js、src/api/dto.js、src/api/errors.js
tests/（平移 14 个测试文件 + 新增 shell/router-guard 测试）
```

**验收标准**：①平移模块原测试全绿（workspace/permissions/router-guard/navigation）；②三外壳可渲染且按角色路由分流正确（超管→/console、工厂→/factory、合规→approvals）；③tokens 无字面量色值外泄（lint 约定）；④CI 双目录构建通过；⑤旧深链 302 到新路径。

## 2. UX-C 核心页（依赖 UX-B）

文件：`pages/market/Discovery.vue`、`pages/product/Products.vue` + ProductDetail.vue、`pages/product/Listings.vue` + ListingFlow.vue、`pages/product/LaunchCenter.vue` + LaunchDetail.vue、`pages/channel/Shops.vue` + ShopAuthWizard.vue、`pages/home/WorkspaceHome.vue`（工作台，含 TaskCard/信号区块/onboarding 卡）、`features/`（launch flow、publish queue、discovery 转池）、第 2 批组件（TaskCard、AiActionCard、EvidencePanel、WorkflowStepper、AdvancedFilter、StoreSwitcher）。 <!-- docs-ok: UX-B/C 新建文件，路径在对应阶段创建后可解析 -->
**依赖**：UX-B 的外壳/路由/tokens/第 1 批组件 + workbench 契约 v1.2。
**验收要点**：①J1/J2 旅程关键断链归零（选品落池、待办直达、采集区隔演示）；②Listing 单页分步流全流程无断点；③创建上线向导化+筛选保存视图；④OAuth 授权状态徽标统一、失败原因可见；⑤partial 数据完整性提示。

## 3. UX-D 经营闭环页（依赖 UX-B，与 UX-C 并行）

文件：`pages/supply/Suppliers.vue` + Purchases.vue、`pages/fulfillment/Orders.vue`（CSV 逐行校验报告）+ Settlements.vue、`pages/aftersale/Refunds.vue`（状态机 AuditTimeline）+ Support.vue、`pages/optimization/Pricing.vue`（批量采纳）+ Ads.vue（/actions 审批回执）+ RiskAlerts.vue、`pages/analytics/Bi.vue`（口径展开）+ Finance.vue（行内编辑）+ LandedCost.vue（接 /cross-border 四组 CRUD + /landed-cost）、第 3 批组件（RiskCard、ApprovalPanel、AuditTimeline、WorkspaceSwitcher 收尾）。 <!-- docs-ok: UX-D 新建文件，路径在 UX-D 创建后可解析 -->
**验收要点**：①CSV 错误行报告；②发货/退款/结算状态机可视化且非法跳转被阻止；③到岸成本 CRUD 可用且与定价口径一致；④广告审批-执行-结果三态可见；⑤告警「去处理」深链正确。

## 4. UX-E AI 及管理页（依赖 UX-D 中 actions/approval 语义，可与 UX-D 尾部并行）

文件：`pages/aiops/Workflows.vue`（/schedules）+ Knowledge.vue + AiDecisions.vue（按类型/对象过滤）、`pages/settings/AiSettings.vue`（4 分组）+ TeamSettings.vue、`pages/console/Overview|Tenants|Audit|Maintenance.vue`（4 页拆分+代客确认+凭据一次性展示）、`pages/factory/FactoryProducts.vue`、`features/aicopilot/`（副驾驶 actions 可执行+上下文感知；会话持久化待接入不放入口）、全局 404/403/500 挂接。 <!-- docs-ok: UX-E 新建文件，路径在 UX-E 创建后可解析 -->
**验收要点**：①合规员/超管/工厂登录各落默认页（J6/J7 全程）；②代客横幅常显可退出；③租户凭据仅展示一次；④AI 副驾驶建议动作可执行带确认、工厂不可见；⑤未配置 Key 功能页呈 NotConfiguredState。

## 5. UX-F 验证切换（依赖 UX-C/D/E 全部）

- **覆盖矩阵核对**：以 PM 矩阵 30 行×验收用例要点逐行勾验（30/30 路由页+非路由视图），18 项弹窗按表二处置核对；产出核对记录文档。
- **E2E 与回归**：7 类旅程（J1-J7）各一条端到端走查；vitest 全量回归；旧 302 映射抽测。
- **性能基线**：首屏 LCP/路由切换耗时/包体积对比旧 frontend/ 构建产物，劣化超 10% 需说明（代码分割按域 lazy 已在路由表约定）。
- **切换步骤**：①部署入口切至 frontend-v9 构建产物（nginx/vite 代理不变，baseURL /api 不变）；②观察 1 个版本周期；③删除 frontend/ 目录与对应 CI job（单前端终态）。
- **回退步骤**：部署入口切回旧产物即回退；后端零动作（无契约变更）；回退窗口期内旧目录保留。

## 6. 测试策略（沿用现行约定）

- vitest + jsdom，**无 @vue/test-utils**：组件逻辑（过滤/转换/状态推导/DTO）一律抽纯函数放 shared/ 或 features/，测试只测纯函数与模块契约（如现 navigation.test.js、workbench.test.js 模式）。
- 平移模块测试零改动通过为验收线；新增页面每页至少 1 个纯函数测试（列定义/筛选逻辑/状态映射）。
- 契约测试：workbench BFF 契约字段（signals/partial/sources、脱敏、空）以现有 workbench.test.js 为基线继续守护。

## 7. 冻结与并行约定（Agent 间只传接口契约）

**先冻结再并行**（UX-B 内完成、此后不再改动）：
1. `styles/tokens.css` V9 扩展版（令牌名=契约，改令牌名须全员评审）；
2. AppShell props/插槽 + 三导航数据结构 `{key,label,icon,children:[{path,label,icon,badge?}]}`；
3. 路由 meta 契约 `{space, domain, title, permission?}` + 旧路径 302 表；
4. api/domains 模块签名（函数名+DTO 形状）与 errors.js 规整结果。

**并行批次**：UX-C / UX-D 依赖 UX-B 后即刻并行（两者无共享页面）；UX-E 前半（Console/Factory/Settings）可提前与 UX-C 并行，后半（AI 域）等 UX-D 的 ApprovalPanel/AiActionCard 落地。跨批次只通过上述 4 份冻结契约 + 组件 props 文档（DESIGN_SYSTEM §2）传递接口，禁止直接读对方页面代码。

**关键路径**：UX-B → UX-C（最长链：WorkspaceHome/Listing 分步流）→ UX-F；UX-D 与 UX-C 并行不占关键路径；UX-E 关键件（副驾驶/ApprovalPanel）须在 UX-F 前完成。

## 8. 硬约束复核

- 不引入新 UI 组件库 ✅（Element Plus 2.9.1 延续）；不做全仓 TS 迁移 ✅（沿用 JS + JSDoc 注释约定）；业务逻辑不推翻 ✅（shared/ 平移 + features/ 仅前端重组）；后端能力未证实的全部标「待接入」✅（API_MAPPING §1 末行清单）。
