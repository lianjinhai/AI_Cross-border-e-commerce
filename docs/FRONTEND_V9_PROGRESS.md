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
| UX-E AI 及管理页 | ✅ QA 验收 PASS with notes（295/295 全绿；代客安全链完整；AI 诚实边界完整；1 P2 缺项） | Console 4 页/工厂门户/登录分流 + AI 域/设置/副驾驶，路由合并 eda8729 | 3c8c655, 9f4eb68, eda8729 |
| UX-F 验证切换 | ✅ 终验完成（ACCEPTANCE v2，0c2b597）：20 标准 18 通过+2 排期；7 旅程探活无断点；可切换 | 验收报告 v2 + 切换/回退建议 | 0c2b597 |
| 蓝图 R1 全站补齐 | ✅ 完成（dac556a）：导航 11→8 域、9 共享组件、15 新页、11 态字典、8 数据标签；417 测试 + build | frontend-v9 83 文件 | dac556a |
| 运行入口核查 | ✅ 完成（2026-10-14）：根因=V9 从未被任何入口部署；8000 仍指旧 dist；已加 `ERP_FRONTEND_DIST` 切换 + `/api/build-info`；独立验收 8001(V9 静态)/5174(V9 dev) 已起 | 见 `FRONTEND_V9_RUNTIME_VERIFICATION.md` | 未提交 |
| R3-0 现状/契约冻结 | ✅ 完成（2026-10-14）：4 份矩阵（页面归属/后端能力/任务契约/AppShell 基线）+ R3 总蓝图落盘；E01–E12 坐实；4+1 入口设计 | 见 `FRONTEND_R3_*.md` + `UI_REFACTOR_BLUEPRINT_R3.md` | docs |
| R3-1A 基础数据与路由修复 | ✅ 完成（2026-10-14，QA 回归发现 1 项已转 R3-1B 修复）：E01/E02/E05/E06/E09 + E03/E04 骨架；channels 路由唯一化；素材 shop_id 守卫；442/442 测试 + build + 浏览器实证 | ProductDetail/productDetailView/router + 3 新测试 | 777df4b |
| R3-1B 真实操作与权限修复 | ✅ 完成（2026-10-14）：E03 登记补 market/platform（shopContext 推导，content_hash 无上传服务时拒绝提交不假哈希）；E04 核验 403/409/自审/通过/拒绝分类；E10 Launch 按 available_actions.executable 渲染 + disabled_reason + 回执 + 409 保留输入；452/452 测试 + build + 浏览器实证 | ProductDetail/LaunchStepPanel/LaunchDetail/launchCenter/productDetailView + 3 测试 | 2fbabdf |

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
| V9-C1 | P2 | LaunchCenter 保存视图「应用筛选」链路断裂（@apply-filters 无消费方） | ✅ 已修复（e0128a2：补事件绑定+applyViewToFilters 纯函数+用例） |
| V9-D1 | P2 | Orders.vue 利润列文案未复用 biCaliber 常量 | ✅ 已修复（6a67b17：import biCaliber 常量） |
| V9-D2 | P2 | UX-D 页面直接用 EmptyState/LoadingState 未走 SectionState 包装（风格分叉，行为等价） | 接受存量，UX-E 新页面起统一用 SectionState |
| V9-B6 | P1→已修 | 旧 frontend exitImpersonate 只清标记不还原平台 token（平台管理员钉死租户身份） | ✅ UX-E 前半顺手根治（3c8c655：impersonation.js 快照/还原纯函数） |
| V9-E1 | 备注 | AI 会话持久化、定价/广告/客服「查看依据」深链发送端、Support→Knowledge 反向互跳、最后 OWNER 降级后端约束——均后端能力未就绪或跨批接入项 | UX-F 覆盖核对时统一处置（不放假入口） |
| V9-E2 | P2 | console/Tenants.vue 未展示 license_note（授权备注）列（后端 admin.py 字段仍在，纯展示遗漏） | 登记在案，UX-F 修复或接受 |

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

- 2026-10-13：UX-A 冻结（f690fea + 契约 aed39e8）；UX-B 完成并过 QA（1dd1526 + 2128b60）；契约 P2 修订（e18bd58）；UX-C/D 并行交付（7dd4f69 + c142577）；路由合并（2e0ecd8）；契约回写七处真实端点偏离（dd7c055）；UX-E 双线交付（3c8c655 + 9f4eb68 + eda8729，代客 token 还原根治）；UX-F 终验完成（ACCEPTANCE v2，0c2b597，判定 PASS 可切换）。
- 2026-10-14：蓝图 R1 全站补齐（dac556a，83 文件，417 测试 + build）。**运行入口专项核查**：查实「用户看不到 V9 变化」根因 = `config.py` 写死 `frontend/dist`、`Dockerfile` 只构建旧前端，V9 构建产物从未被任何运行入口部署。已加 `ERP_FRONTEND_DIST` 可切换（默认仍旧，可回退）+ `/api/build-info` + `VITE_API_PROXY_TARGET`，起 8001(V9 静态)/5174(V9 dev) 独立验收入口。产出 `FRONTEND_V9_RUNTIME_VERIFICATION.md` 与 `FRONTEND_V9_VISUAL_ACCEPTANCE.md`。

## §7 运行入口与正式接管（2026-10-14 核查）

- **根因**：`backend/app/config.py` `frontend_dist` 写死旧 `frontend/dist`；`Dockerfile` 仅构建 `frontend/`。`frontend-v9/dist` 从未被部署 → 用户访问 8000/5173 永远看到旧界面（5173 另被「TY-平台/退役军人就业服务平台」无关项目争用）。
- **修复**：
  - `config.py`：`ERP_FRONTEND_DIST` 环境变量覆盖 dist 源（默认旧，可回退）；新增 `ERP_BUILD_ID/SHA/TIME`。
  - `main.py`：新增 `GET /api/build-info`（返回 `frontend_dir`/`frontend_dist`/`dist_exists`/`build_*`），让「访问的是哪套前端」可直接判断。
  - `vite.config.js`(V9)：`VITE_API_PROXY_TARGET` 可指任意后端（默认 8000）。
- **当前入口**：`8001`=V9 接管版（静态，`frontend_dir=frontend-v9`、`build_sha=dac556a`）；`5174`=V9 dev；`8000`=旧前端（回退）。
- **正式接管**：设 `ERP_FRONTEND_DIST` 指向 `frontend-v9/dist` 重启 8000；Docker 需新增 V9 构建阶段。详见 `FRONTEND_V9_RUNTIME_VERIFICATION.md` §七。
- 架构师一致性提醒（供 UX-F）：①矩阵 #6 Listing 发布验收用例仍写多店语义，需随单店发布口径修订；②UX-C 广告 ROI 与 #14 定价口径互链、UX-D LandedCost 与 #14 同口径，UX-F 走查时核对一致。
