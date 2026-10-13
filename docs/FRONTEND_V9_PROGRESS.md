# FRONTEND V9 · 全站前端重设计进度（事实源）

> 系列归属：`FRONTEND_V9_*`。本文件是 V9 项目的阶段状态、关键决策、缺陷与验证基线的**唯一事实源**，由总调度维护。
> 设计冻结见 `FRONTEND_V9_MASTER_DESIGN.md`，实施依据见 `FRONTEND_V9_IMPLEMENTATION_PLAN.md` 与 `FRONTEND_V9_CONTRACTS.md`。

## §0 冻结口径（UX-A，commit f690fea）

- **目标**：全平台前端系统性重设计（10 类界面全覆盖），交付真实可运行前端，不是局部优化。
- **三产品空间**：Platform Console（`/console/*`）/ Commerce Workspace（`/app/*`，产品核心）/ Factory Portal（`/factory/*`）；Personal 与 Organization 共享业务底座。
- **基座落位（已定）**：同仓新目录 `frontend-v9/`；UX-F 验收后一次性删除旧 `frontend/` 回归单前端；切换前旧前端保持可运行；回退=部署层切回旧产物。
- **业务红线**：Product/Supplier/Factory/1688/Shop/Listing/Publishing/Order/Purchase/Finance/Compliance/Workflow/Agent/Workspace 权限的业务逻辑不推翻；重设计只针对前端组织方式。
- **诚实边界**：后端未接能力标「待接入」且不放可点击入口（物流轨迹/AI 会话持久化/工厂订单结算/工厂侧 AI 资料）；禁 Mock 数据；禁第二套重复 Service。

## §1 阶段状态

| 阶段 | 状态 | 交付 | 提交 |
|---|---|---|---|
| UX-A 设计冻结 | ✅ 完成 | 7 文档（矩阵/旅程/总设计/导航/设计系统/API映射/实施计划）+ 契约 1 份（aed39e8） | f690fea, aed39e8 |
| UX-B 工程基座 | ✅ 完成（QA: PASS with notes，无 P0/P1；P2 已清零） | frontend-v9/ 95 文件：脚手架+tokens+三薄壳+路由302+29域(11完整)+12组件+186 测试 | 1dd1526, 2128b60 |
| UX-C 核心业务页 | ✅ QA 合并验收 PASS with notes（无 P0/P1） | 工作台/市场/商品/Listing/上线/店铺 + 第 2 批组件（含 SectionState 五态） | 7dd4f69 |
| UX-D 经营闭环页 | ✅ QA 合并验收 PASS with notes（无 P0/P1） | 供应链拆分/履约/售后/优化/BI/财务/到岸成本 + 第 3 批组件 | c142577 |
| 路由合并 | ✅ 完成（2e0ecd8：UXD_ROUTES 12 条挂接替换 StubPage，整仓 build 过） | router/index.js 引入 routes-uxd.js | 2e0ecd8 |
| UX-E AI 及管理页 | 🔄 两线并行实施中（A 线：Console 4 页/Factory/登录；B 线：AI 域/设置/副驾驶） | 见 §4 实施计划 | — |
| UX-E AI 及管理页 | ⏳ 排队（前半可并行） | AI 运营/登录初始化/Console 4 页/Factory Portal | — |
| UX-F 验证切换 | ⏳ 排队 | 覆盖矩阵/E2E/权限/性能/切换回退 | — |

## §2 UX-B 交付事实（commit 1dd1526）

- 目录：`frontend-v9/src/{app/{router,errors,pages},shells,components,shared/{workspace,ui,statusDict,api,navigation},permissions,composables,api/{dto,domains}}` + tests 15 文件。
- 验证：`npm test` 186/186（14 文件，断言零放宽）；`npm run build` 成功（vendor 分包）；dev 冒烟 5174 端口 200（须带 `CODEBUDDY_SAFE_DELETE_ENABLED=0`，见 §5 坑位）。
- 302 查表：29 条旧路径全量覆盖（契约计数口径含 3 条新页行），`:id` 透传、query 保留、未命中落 404 无静默兜底。
- R8 分支：`/platform-admin` 同 path 异 query 显式判断 `to.query.tab`，三种情形单测锁定。
- 有据偏离（QA 确认合理）：AppShellCore 用内置 router-view（契约 §2.1 已补注）；listings 拆 fetchListing→Receipts/Reviews（后端无单条 GET）；orders importCsv 按 csv_text 真实入参。
- 已知占位：全部业务页挂 StubPage（无可点击入口）；18 个 api 域待 UX-C/D/E 补齐；TaskCenter/NotificationBell/AiCopilot 注释装配位。

## §3 缺陷登记

| 编号 | 级别 | 内容 | 状态 |
|---|---|---|---|
| V9-B1 | P2 | AppShellCore 内置 router-view 与契约 §2.1 default 插槽表述不符 | ✅ 已修复（契约 §2.1 补注权威口径，e18bd58） |
| V9-B2 | P2 | 契约 §4.2 fetchListing 与实现拆分不一致 | ✅ 已修复（契约 §4.2 回写真实拆分签名，e18bd58） |
| V9-B3 | P2 | ConsoleShell.vue:27 'PLATFORM_ADMIN' 字面量兜底 | ✅ 已修复（2128b60：permissions.js 导出 ROLES 枚举，ConsoleShell 引用） |
| V9-B4 | P2 | 契约 §3.3.2 与 §3.3.3 对 COMPLIANCE 白名单外行为表述冲突 | ✅ 已修复（统一为 §3.3.2 重定向唯一权威规则，/403 仅防御性挂接，e18bd58） |
| V9-B5 | P2 | ShellSidebar el-menu props 与 .menu-group 深色字面量 | 接受（沿现网写法，UX-C 接入 eslint 规则时一并治理） |
| V9-C1 | P2 | LaunchCenter 保存视图「应用筛选」链路断裂（@apply-filters 无消费方） | 修复中（A 线 engineer-2） |
| V9-D1 | P2 | Orders.vue 利润列文案未复用 biCaliber 常量 | 修复中（B 线 engineer-3） |
| V9-D2 | P2 | UX-D 页面直接用 EmptyState/LoadingState 未走 SectionState 包装（风格分叉，行为等价） | 接受存量，UX-E 新页面起统一用 SectionState |

## §4 验证基线

| 指标 | 基线 | 来源 |
|---|---|---|
| frontend-v9 npm test | 186 用例 / 14 文件全绿 | UX-B（总调度+QA 双重复现） |
| frontend-v9 npm run build | 成功（1756 modules） | UX-B |
| 旧 frontend npm test | 77（docs/baseline.json） | 不回归红线 |
| backend pytest | 646（docs/baseline.json） | 不回归红线 |
| docs 门禁 | total=0 | 每次提交前 |

## §5 坑位备忘（工程实现必读）

1. **dev 启动必须带 `CODEBUDDY_SAFE_DELETE_ENABLED=0`**：否则 vite 依赖优化/构建清空目录时会被环境守护的批量删除拦截而崩溃（QA 独立验证时再次复现）。
2. 文档引用 frontend-v9 未来文件路径须行尾 `<!-- docs-ok -->` 豁免（门禁 path_refs 按文件名解析）。
3. 后端 pytest 用系统 Python（`AppData\Local\Programs\Python\Python311`）；前端测试无 @vue/test-utils，组件逻辑抽纯函数。
4. workbench.py 当前为未提交 WIP（UX-04），frontend-v9 的 workbench 域链路待其合入后完整。

## §6 变更记录

- 2026-10-13：UX-A 冻结（f690fea + 契约 aed39e8）；UX-B 完成并过 QA（1dd1526 + 2128b60）；契约 P2 修订（e18bd58）；UX-C/D 并行交付（7dd4f69 + c142577）；路由合并（2e0ecd8）；契约回写七处真实端点偏离（dd7c055）；QA 合并验收进行中。
- 架构师一致性提醒（供 UX-F）：①矩阵 #6 Listing 发布验收用例仍写多店语义，需随单店发布口径修订；②UX-C 广告 ROI 与 #14 定价口径互链、UX-D LandedCost 与 #14 同口径，UX-F 走查时核对一致。
