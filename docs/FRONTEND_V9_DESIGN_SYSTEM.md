# FRONTEND V9 · 设计系统（UX-A 架构冻结）

> 基础：现有 `frontend/src/styles/tokens.css`（UX-01 落地，语义令牌与 Element Plus 默认同源）+ `docs/FRONTEND_DESIGN_SYSTEM.md`（V1.0 冻结的 20 类组件清单）。
> V9 原则：**扩展不推翻**——令牌在现有文件上追加，V1.0 已有组件经适配进 V9 组件库；不引入新 UI 组件库（继续 Element Plus 2.9.1 + @element-plus/icons-vue）。

## 1. Design Tokens（V9 扩展版）

在现 tokens.css 基础上追加（现有 5 语义色/间距/字号/圆角/阴影全部保留，取值不变）：

```
/* 追加：状态/功能色梯（主色仍 #409EFF 系） */
--color-primary-light/-dark          交互悬停/按下
--color-primary-bg                   #ecf5ff 主色浅底（评分卡/选中态）
--color-success-bg / warning-bg / danger-bg / info-bg   各语义浅底（#f0f9eb/#fdf6ec/#fef0f0/#f4f4f5）
/* 追加：表面层级 */
--color-surface        #ffffff  卡片
--color-surface-alt    #fafbfc  次级卡片/表头底
--color-bg-elevated    弹层底（=surface+shadow-pop）
--color-border-light   #e4e7ed  次级边框（现网已混用，收敛命名）
--color-text-primary   #303133（=--color-text 别名，过渡期并存）
--color-text-regular   #606266  正文次级（补齐 EP 文本梯度，现网散落）
--color-text-disabled  #c0c4cc
/* 追加：品牌辅助色（空间区分） */
--space-accent-console   #6f42c1  Console 空间强调色
--space-accent-workspace var(--color-primary)
--space-accent-factory   #0e9f6e  Factory 空间强调色
/* 追加：图标尺寸 */
--icon-sm 14px / --icon-md 16px / --icon-lg 20px
/* 追加：抽屉/弹窗档位 */
--drawer-w-sm 480px / --drawer-w-md 560px（抽屉统一两档）
/* 深色模式预留（本版不实现，仅定义变量槽位） */
[data-theme="dark"] { /* --color-bg/--color-surface/--color-text-*/ 三层反色映射，命名不变值变 */ }
```

规则沿用：字面量色值只允许出现在 tokens 文件；EP 变量同源映射（`:root:root` 特异性技巧）保留；深色模式靠语义命名兜底，组件禁读具体色值。

## 2. 20 类公共组件规范

「复用」= V1.0 现有组件适配后进入 V9；「替代」= 列出被吸收的现存实现。

| 组件 | 用途 | 关键 props / 插槽 | 复用或替代 |
|---|---|---|---|
| AppShell | 三空间外壳骨架：侧栏+顶栏+内容区+状态横幅 | props: navigation(导航数据)、space('workspace'\|'console'\|'factory')；slots: topbar-extras、banner | 替代 views/Layout.vue；吸收 SidebarNav |
| PageHeader | 页首：标题+副题+主操作区+面包屑 | props: title、subtitle；slots: actions、filters | 复用 components/PageHeader.vue（加 filters 插槽） |
| WorkspaceSwitcher | 工作区切换下拉 | props: workspaces、activeId；emit: switch（接 `/me/workspaces/{id}/switch`） | 复用 components/WorkspaceSwitcher.vue |
| StoreSwitcher | 全局店铺筛选（顶栏） | props: shops；v-model:selectedId | 新增（数据源 shops） |
| MetricCard | 指标卡：值+趋势+口径说明 | props: label、value、trend、tooltip(口径)、loading；slot: chart | 复用 components/MetricCard.vue（加口径 tooltip，承接 BI 口径说明需求） |
| DataTable | 列表页统一表格封装：列定义+分页+URL 状态同步 | props: columns、loader、pageState(sync to query)；slots: cell 扩展 | 新增（收敛 24 页各自拼的 el-table+分页） |
| AdvancedFilter | 筛选区：字段组+保存视图（localStorage） | props: fields、savedViewsKey | 新增（承接上线中心「保存视图」） |
| StatusBadge | 状态徽标（StatusTag 升名） | props: status、dict('launch'\|'run'\|'risk'\|'order'\|'refund'…) | 复用 components/StatusTag.vue 改名；吸收 views/RunStatus.vue（文件移除） |
| WorkflowStepper | 分步流程骨架（GUIDED 上线/Listing 流/下单向导） | props: steps、current、mode('guided'\|'professional')；slot: step-content | 复用 components/LaunchStepPanel.vue 泛化 |
| TaskCard | 待办卡（工作台/任务中心） | props: todo(workbench/todo 项)、sourceLabel | 新增（承接 UX-04 待办分组语义） |
| RiskCard | 告警卡：风险+「去处理」深链 | props: alert、deepLink | 新增（承接 #24 断链归零） |
| AiActionCard | AI 建议统一卡（三段式） | props: suggestion、evidence[]、risks[]、actions[]；emit: apply | 新增（见 §3） |
| EvidencePanel | 证据面板：决策依据链展示 | props: decisionId、items；跳 `/app/ai/decisions` | 新增（AI 可解释通用件） |
| ApprovalPanel | 审批面板：队列+详情左右分栏 | props: queue、selected；emit: approve/reject | 吸收 ComplianceWorkbench 内联实现 + actions 审批（/actions approve/reject）泛化 |
| EmptyState | 空态 | props: reason(4 态)、hint、action | 复用 components/EmptyState.vue |
| ErrorState | 错误态 | props: message、traceId；emit: retry | 复用 components/ErrorState.vue |
| LoadingState | 加载态骨架 | props: type('table'\|'cards'\|'chart') | 新增（统一 loading 呈现） |
| FormSection | 表单分组（设置子页/向导步） | props: title、description；slot: default | 新增（承接 #27 五类配置分组） |
| ConfirmDialog | 确认弹窗（含危险级） | props: level('normal'\|'danger')、message | 新增（统一 ElMessageBox 封装） |
| AuditTimeline | 审计/时间线（launch 时间线、退款状态机、AI 决策链） | props: events、dict | 吸收 LaunchTimeline 泛化 + Refunds 状态机可视化 |
| SectionState | 页面取数状态机五态包装（loading/empty/error/nopermission/默认内容）【UX-C 第 2 批延伸交付】 | props: state、reason?；slots: default、各态定制 | 包装复用 LoadingState/EmptyState（含 NO_PERMISSION reason）/ErrorState 家族，页面取数处统一套用 |

未被上表吸收的 V1.0 组件去留：StateWrapper/NoPermissionState/NotConfiguredState/WaitingExternalState → 语义并入 EmptyState 的 reason 枚举扩展（`NO_PERMISSION`/`NOT_CONFIGURED`/`WAITING_EXTERNAL`）+ PageHeader 降级插槽，V9 统一为 EmptyState 家族；NextActionButton/PublishActions/LaunchActionDialog/LaunchExperienceToggle/LaunchStatusSummary/PublicationReceipts/ShopCommerceFields/PartialDataBanner → 归入对应 features/ 域组件（launch/listings/shops 专用，不进公共库），保留逻辑平移；Breadcrumb → 并入 AppShell。

## 3. AI 建议样式统一（AiActionCard 三段式）

所有 AI 建议（定价建议价/广告选词/Listing 优化/客服建议回复/工作流下一步）统一为：

1. **建议段**：标题 + 一句话结论 + 置信/评分（如机会评分因子展开）；
2. **证据段**：EvidencePanel 内嵌——依据要点列表，「查看完整决策依据」深链 `/app/ai/decisions`（旅程验收 #3）；
3. **动作段**：主按钮（采纳/应用）+ 次按钮（忽略/编辑后采纳）；采纳需确认的走 ConfirmDialog；执行后回执态展示（成功/失败可重试）。

不可执行的建议（后端无对应端点）只呈现「预告态」，按钮禁用并标「待接入」。

## 4. 状态标签统一映射表

以 `composables/statusDict.js` 为唯一字典源扩展，StatusBadge 消费；各页禁止私配颜色文案：

| 字典 | 覆盖枚举（示例） | 视觉 |
|---|---|---|
| launch | pending/preparing/published/failed… | success/danger/info 梯 |
| run | succeeded/running/failed/recovering | workflow 配色 |
| risk | open/acknowledged/resolved | danger→info 递减 |
| order/refund/purchase/settlement | 各自全状态机 | 状态机档位色（AuditTimeline 同源） |
| shop/auth | authorized/expired/unsynced | 含 token 过期警示态 |
| compliance | pass/warn/high_risk | 成功/警告/危险三档 |
| ai_action | pending_approval/approved/rejected/executed/failed | 审批三态+执行两态 |
