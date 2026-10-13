# FRONTEND V9 · 总设计（UX-A 架构冻结）

> 系列归属：`FRONTEND_V9_*`。依据：`FRONTEND_V9_PAGE_MATRIX.md`（产品冻结）、`FRONTEND_V9_USER_JOURNEYS.md`、实读 `frontend/src/`（router.js / permissions.js / workspace.js / api.js / composables/navigation.js / styles/tokens.css）与 `backend/app/routers/`。
> 本阶段（UX-A）只做研究与文档，不改任何代码。

## 1. 三空间外壳架构

三空间 = 三套 AppShell 实例 + 一套共享设计系统（tokens / 公共组件 / 状态原子）：

| 空间 | 前缀 | 外壳组件 | 使用者 | 菜单源 |
|---|---|---|---|---|
| Console | `/console/*` | ConsoleShell（紧凑工具型） | PLATFORM_ADMIN | console-navigation.js |
| Workspace | `/app/*` | WorkspaceShell（完整侧栏+顶栏） | OWNER/OPERATOR/READ_ONLY/COMPLIANCE | workspace-navigation.js（11 域） |
| Factory | `/factory/*` | FactoryShell（极简单栏） | FACTORY_COLLABORATOR | factory-navigation.js |

共享设计系统：`styles/tokens.css` 扩展 + 20 类公共组件（见 DESIGN_SYSTEM 文档）。三外壳只差「导航源 + 顶栏插槽 + 权限目录」，布局骨架、面包屑、全局状态横幅（只读/代客/未配置）复用同一实现。
登录页 `/console/login` 全空间共用（PM 矩阵 #1），登录后按 `defaultLanding` 分流：超管→`/console/overview`、工厂→`/factory/products`、合规→`/app/compliance/approvals`、其余→`/app`。
非路由视图处置：AiAssistant 升级为 Workspace 全局副驾驶（actions 可执行、上下文感知）；RunStatus 并入设计系统原子库，从 views/ 移除。

## 2. 页面组织总览

30 界面按 PM 矩阵落位三空间：Workspace 24 路由页（11 域，详见 NAVIGATION 文档）、Console 4 页、Factory 1 页 + 2 待接入页（不放入口）；登录 1 页。18 项弹窗按矩阵表二处置：向导化（CSV 导入/创建上线/代发下单）、行内化（财务录入）、路由化（商品详情）、常驻面板化（发布回执）。

## 3. 与现有 frontend/ 的关系

- **业务逻辑零推翻**：14 个后端域契约与 `workspace.js`（Context 响应式缓存/订阅/epoch）、`permissions.js`（fail-closed `can()`、Context 优先、legacy 仅路由兜底）策略原样保留，封装后平移。
- **可直接平移复用**（纯函数模块，拷入 `frontend-v9/src/shared/` 后仅改 import 路径）：`workspace.js`、`permissions.js`、`composables/statusDict.js`、`composables/navigation.js`（按三空间拆分重组）、`composables/launchCenter.js`、`composables/publicationReceipts.js`、`composables/publishActionQueue.js`。
- **重写**：所有 30 个 views（V9 重设计目标态）、Layout→三 AppShell、navigation.js 菜单结构（11 域语义不变、路径改为 `/app/*`）。
- **V1.0 已落地组件**：StatusTag/EmptyState/ErrorState/StateWrapper/MetricCard 等 22 个中约 12 个经适配并入 V9 组件库（映射见 DESIGN_SYSTEM 文档）。

## 4. 基座落位决策（关键结论）

**决策：同仓新目录 `frontend-v9/`，UX-F 验收通过后一次性删除 `frontend/`，仓库回到单前端。不采用 Git 分支改造。**

| 权衡项 | 同仓新目录 frontend-v9/ | Git 分支改造 frontend/ |
|---|---|---|
| 切换前旧系统可运行 | ✅ main 上 frontend/ 持续可构建、可继续接收 hotfix 与 UX-04 等在途迭代 | ❌ 长期分支与 main 漂移，hotfix 需双向 cherry-pick |
| 双前端维护成本 | ⚠️ 过渡期（约 5 个阶段）存在两套工程；**以「切换即删旧目录」为硬承诺收敛** | ⚠️ 合并前一直是「隐形双前端」，且对照验收困难 |
| Vite/依赖复用 | ✅ package.json/vite.config 逐字复制锁定同版本（EP 2.9.1 / Vite 5.4 / ECharts 6.1 / Vitest 2.1），tokens 与纯函数模块直接拷贝 | ✅ 同 |
| CI 影响 | ✅ 单流水线按路径过滤：`frontend/**` 与 `frontend-v9/**` 各一套 build+test job，互不阻塞，PR 可双跑对照 | ❌ 需维护双分支 CI 规则；跨分支 PR 对照不可行 |
| 风险 | 过渡期依赖升级须双目录同步（约定：过渡期锁版本不升级） | 分支存活期越长漂移越不可控 |

结论理由：当前团队仍在旧前端上交付（UX-04 在途），分支改造会冻结 main 迭代或制造漂移；同仓新目录以「目录级隔离 + 切换即删」达成同等单前端终态，且 CI/对照/回退（切回=旧目录仍在 git 历史，甚至切换初期保留 1 个版本周期）都更简单。

## 5. 前端分层

```
frontend-v9/src/
├── app/            应用装配：main.js、router/（三空间路由表+守卫）、全局横幅/错误页
├── shells/         AppShell×3（WorkspaceShell/ConsoleShell/FactoryShell，共享骨架子组件）
├── pages/          路由页（按 11 域分目录：market/product/supply/channel/fulfillment/aftersale/optimization/analytics/aiops/settings/console/factory）
├── features/       业务逻辑层（非 UI）：按域组织 store/转换器/流程编排（如 launch flow、publish queue），业务逻辑与展示分离的唯一归属地
├── components/     20 类公共组件（DESIGN_SYSTEM 冻结清单）
├── shared/         平移复用的纯函数模块（workspace/permissions/statusDict/navigation 数据 + api 客户端）
├── composables/    UI 态 composable（usePageQuery/useDrawerState 等展示性状态）
├── api/            按域封装的 API 模块（DTO 映射+错误规整，见 API_MAPPING 文档）
├── permissions/    permissions.js 平移 + 路由 meta 权限声明
├── styles/         tokens.css（V9 扩展版）+ 全局样式
└── tests/          vitest（纯函数优先，沿用现行约定）
```

分离原则：**pages 只做「取数→渲染→派发动作」**；数据转换、状态机推导、权限组合、流程编排一律在 features/ 或 shared/ 的纯函数中，保证无 @vue/test-utils 环境下可测。

## 6. 迁移与切换策略总纲

1. **契约先行**：UX-B 先冻结三样公共契约——tokens、AppShell props/插槽、路由 meta（domain/title/space/permission）与导航数据结构；之后 UX-C/D/E 三批次按契约并行。
2. **平移不重写**：shared/ 纯函数模块在 UX-B 一次性拷入并通过原测试（tests/ 同步拷贝），保证权限/Context 行为零漂移。
3. **按域纵向切片**：每阶段交付「完整可走的域」（页面+features+api 封装+测试），不做跨阶段半页。
4. **双跑对照**：过渡期 CI 双构建；UX-F 用覆盖矩阵逐页核对 V9 与旧页数据一致性（同一后端）。
5. **切换**：UX-F 验收后，vite 代理/部署入口指到 frontend-v9 构建产物；旧 frontend/ 保留 1 个版本周期作回退窗口，之后删除。
6. **回退**：部署层切回旧产物即回退（后端 API 不变，无数据迁移）；路由/权限契约未动后端，回退零后端动作。

## 7. 风险清单

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 双目录过渡期依赖漂移 | 过渡期锁版本；升级仅在 UX-F 后做 |
| R2 | `/app/*` 新路径与旧 `/dashboard` 等深链/收藏失效 | 旧路径 302 映射表（router alias 或服务端重定向，UX-B 交付） |
| R3 | 平移 permissions/workspace 时引入回归 | 原测试文件同步拷贝并要求全绿（UX-B 验收项） |
| R4 | 后端能力不存在导致页面虚构（物流轨迹/会话持久化/工厂订单结算） | 全部标「待接入」不放入口（PM 矩阵口径） |
| R5 | 30 页并行开发风格漂移 | 20 类公共组件 + 页面骨架模板在 UX-B 冻结，评审按契约核对 |
| R6 | Vite 双构建产物路径/代理差异 | UX-B 统一 vite.config（同 proxy、同 base），CI 双跑验证 |
| R7 | 最后一个 OWNER 降级约束后端未确认 | 设置页按「待确认」处理：前端确认弹窗文案不承诺后端拦截（API_MAPPING 已核实后端无显式守卫） |
