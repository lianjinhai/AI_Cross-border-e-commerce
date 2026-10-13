# 前端 UX 审计报告（UX-00）

> 最后更新：2026-10-13
> 状态：审计完成（只读研究，未修改任何业务代码）。本文是「全站信息架构与 UX 统一优化」蓝图的原始素材之一。
> 配套文档：`docs/FRONTEND_PAGE_MATRIX.md`（30 页矩阵）、`docs/FRONTEND_USER_JOURNEYS.md`（A–H 旅程 + A–G 画像）。
> 冻结口径 v1.0：一级 IA 11 域、双模式同源、首页 6 问、B03–B09 显式未接入、页面 10 态。三份文档与此完全一致。

---

## ① 审计范围与方法

**范围**

| 项 | 内容 |
|---|---|
| 前端页面 | `frontend/src/views/` 全部 **30 个 .vue**（逐个打开，非抽样） |
| 前端其它 | `src/router.js`、`views/Layout.vue`、`composables/navigation.js`（菜单定义与角色过滤，UX-02 抽出自 `Layout.vue`）、`src/permissions.js`、`src/workspace.js`、`src/api.js`、`composables/launchCenter.js`、`components/` |
| 后端对照 | `backend/app/routers/launch.py`、`backend/app/services/workspace_context.py`（权限矩阵） |
| 文档 | README.md、AGENTS.md、docs/LAUNCH_CENTER_PRODUCT_DESIGN.md、docs/PLATFORM_WORKFLOW_PROGRESS.md、docs/需求分析与详细设计说明书V8.0.md、docs/页面操作权限对照表.md、docs/角色界面差异化设计方案.md、docs/项目介绍与功能地图.md（章节级） |
| 缺失文档（如实标注，未假装已读） | FRONTEND_UX_AUDIT / FRONTEND_INFORMATION_ARCHITECTURE / FRONTEND_PAGE_MATRIX / FRONTEND_DESIGN_SYSTEM / FRONTEND_USER_JOURNEYS / FRONTEND_API_ALIGNMENT / FRONTEND_IMPLEMENTATION_PLAN / FRONTEND_UX_PROGRESS / FRONTEND_UX_ACCEPTANCE —— 审计启动时**全部不存在** |

**方法**：①逐个打开 30 个页面源码，提取「入口/出口/核心数据/可执行操作/权限 key/后端 API/问题」；②对照 `permissions.js` 与 `workspace_context.py` 校验权限 key 是否与实际一致；③以「用户旅程要求 vs 代码事实」逐条比对，标注断点；④结论一律附证据来源（`文件` + 符号名，例如 `函数/常量/组件`；行号仅在稳定处使用），取不到的写「待确认」。

**纪律**：只读不改；不把未实现能力写成已实现；不确定处标「待确认」。

---

## ② 现状口径校正

以下三处口径与历史文档/描述不一致，**以代码为准**：

| # | 项 | 文档/既有描述 | 代码事实 | 证据 |
|---|---|---|---|---|
| 1 | 一级菜单分组 | 用户建议 **11 个一级业务域** | 现网为 **5 组**：概览 / 商品 / 采购 / 运营 / 系统 | `frontend/src/composables/navigation.js`（`BUSINESS_DOMAINS`；UX-02 由 `Layout.vue` 抽出） |
| 2 | 页面数量 | `docs/项目介绍与功能地图.md` 自称「24 页」；`README.md` 自称「28 个视图组件」 | `router.js` 实际 **27 条路由**；`views/` 共 **30 个 .vue**（其中 3 个非路由页：`Layout.vue` 框架、`AiAssistant.vue` 全局悬浮球、`RunStatus.vue` 状态原子） | `frontend/src/router.js`（`routes` 常量，27 条路由）；`frontend/src/views/` |
| 3 | 权限 key 对照表 | `docs/页面操作权限对照表.md`（2026-10-01）声称为全量 | **已过时**：后端已新增 `launch:read / launch:create / launch:manage / launch:price_review / launch:stock_prepare / launch:compliance_manage / launch:label_manage / launch:submit`，该表未收录 | `backend/app/services/workspace_context.py:82-84` |

**附加口径事实（供后续阶段引用）**

- **现网菜单分组归属**（`frontend/src/composables/navigation.js` 的 `BUSINESS_DOMAINS`）：概览=`/dashboard,/bi,/alerts`；商品=`/discovery,/products,/listings,/launch,/compliance-workbench,/compliance`；采购=`/shops,/suppliers,/pricing`；运营=`/ads,/orders,/refunds,/settlements,/finance,/support`；系统=`/workflows,/knowledge,/ai-decisions,/settings,(/users仅OWNER)`。
- **角色菜单过滤**：`PLATFORM_ADMIN`→平台菜单；`FACTORY_COLLABORATOR`→工厂菜单；`COMPLIANCE`→白名单 6 页（`/compliance-workbench,/dashboard,/bi,/listings,/compliance,/launch`）；非 OWNER 隐藏 `/settings,/users,/compliance-workbench`（`frontend/src/composables/navigation.js` 的 `COMPLIANCE_ALLOWED_PATHS` / `NON_OWNER_HIDDEN_PATHS` / `buildDomains`）。
- **后端创建端点已存在但前端无入口**：`POST /launch`（`backend/app/routers/launch.py:83-84`（`create()`），服务 `create_launch`）已实现，但前端数据层 `composables/launchCenter.js` 只封装了 `context/list/detail/steps/events/executeAction/sync`，**没有创建封装、页面也无入口** —— 缺口在前端。
- **双模式（GUIDED/PROFESSIONAL）现状**：`LaunchDetail.vue` 两模式读**同一份 DTO**、状态一致、切换不重新鉴权（`LaunchDetail.vue` 的 `mode`/`effectiveMode`、`components/LaunchExperienceToggle.vue`），符合冻结方向；但仅上线中心详情页实现，其余页面无模式概念。

---

## ③ 30 页能力缺口清单（G1–G24）

> 严重度：P0=阻断主旅程/必须本轮解决；P1=显著影响体验；P2=优化项。
> 处置：新建 / 改造 / 合并 / 仅补入口。

| # | 缺口 | 影响旅程 | 影响页面 | 严重度 | 建议处置 |
|---|---|---|---|---|---|
| G1 | 无注册页、无「经营目标/能力画像/经营路径」页面（Context 有 `capability_profile`/`business_stage` 字段但无 UI） | A | Login、首页 | **P0** | 新建（首用引导向导） |
| G2 | `/launch` 无「创建上线流程」入口（后端 `POST /launch` 已存在，前端未封装） | A/B/C/D | LaunchCenter | **P0** | 仅补入口（前端） |
| G3 | Launch 领域动作 B03–B09 未接通（仅 COMPLETE_DATA/SUBMIT_PLATFORM/CONFIRM_ACTIVATION/CANCEL/ABANDON 可用，其余 409/未接入；须显式「未接入+原因」，禁止伪造成功） | A/D/F/H | LaunchDetail | **P0** | 后端补（已设计未实现，见 `docs/PLATFORM_WORKFLOW_PROGRESS.md §14`） |
| G4 | 真实「在售核验」未实现，Listings 发布止于 SUBMITTED/待核验（`CONFIRM_ACTIVATION` 属 WAITING_EXTERNAL，不得称「已上线」） | A/C/H | Listings、Launch | **P0** | 后端改造（已设计未实现） |
| G5 | 工厂协作任务收件箱缺失（`/factory-portal` 只有本厂供给目录，无「收到备货/报价任务→提交材料→完成」视图） | G | FactoryPortal | **P0** | 新建/改造 |
| G6 | 首页（Dashboard）不回答 6 问题（详见 ④） | A/B/C/F | Dashboard | **P0** | 改造 |
| G7 | 订单→货源匹配→采购→物流→完成 履约链断裂 | E | Orders | P1 | 改造（补入口+物流） |
| G8 | 审批/动作队列三套（PublishActions / Ads `/actions` / Launch actions）不统一 | C/F/H | Listings、Ads、LaunchDetail | P1 | 合并（统一「待我审批」） |
| G9 | 商品池详情缺 Launch 深链 / 销售渠道 / 上线进度 / AI 建议 tab（`docs/LAUNCH_CENTER_PRODUCT_DESIGN.md §5` 已要求） | B/C/D | Products | P1 | 改造 |
| G10 | 合规审批无「返回原任务」+ 工作台缺商品/目标市场/证据上下文 | F | ComplianceWorkbench | P1 | 改造 |
| G11 | `Compliance.vue` 与 `ComplianceWorkbench.vue` 功能重复 | F | Compliance、ComplianceWorkbench | P1 | **合并**（Compliance → 工作台收编） |
| G12 | 状态字典双事实源：`RunStatus.vue`（小写）vs `composables/launchCenter.js`（大写 EXECUTION_STATUS/PLATFORM_STATUS） | 全站 | RunStatus、Launch* | P1 | **合并**（统一一套状态字典） |
| G13 | 无「从店铺同步商品」入口（仅订单同步 `/shops/{id}/sync_orders`） | C | Shops、Products | P1 | 新建/改造 |
| G14 | Launch 深链 `return_to` 白名单仅 `/launch*`，而 `professional_links` 指向 `/listings` 并携带 `return_to` ⇒ 回不到原步骤（AC-14.7 未闭环） | B/C | LaunchDetail | P1 | 改造（放开白名单到 `/listings,/products,/shops`） |
| G15 | 多页用「数字 ID」输入关联对象（Products 代发 / Refunds / Finance / Suppliers 匹配 / Launch 责任人） | C/E/F | Products、Refunds、Finance、Suppliers、LaunchCenter | P1 | 改造（对象选择器） |
| G16 | 无批量操作（表格无多选列、无批量上线/批量动作） | D | Products、LaunchCenter | P1 | 改造 |
| G17 | Alerts 告警无处置跳转（「只告警不执行」但缺下一步） | H | Alerts | P1 | 改造 |
| G18 | Users 角色下拉仍是 legacy 小写枚举（`admin/operator/viewer/compliance_approver`），与 Context 大写枚举双轨 | 全站权限一致性 | Users | P1 | 改造 |
| G19 | Suppliers「应付账龄」tab 与 `Settlements.vue` 重复（同调 `/settlements/summary`） | F | Suppliers、Settlements | P2 | **合并**（账龄 → Settlements） |
| G20 | 无独立「目标市场」视图（散在 `/shops` 店铺 commerce 字段） | B/C | Shops | P2 | 新建（或在 Shops 内聚合） |
| G21 | 三处 AI 日志分散（Settings `/ai/logs`、AiDecisions `/ai/decisions`、PlatformAdmin `/admin/ai_logs`） | H | Settings、AiDecisions、PlatformAdmin | P2 | **合并**（统一一处） |
| G22 | 无全局搜索 / 面包屑 / 收藏 | 全站 IA | Layout | P2 | 新建 |
| G23 | 登录页写死演示账号提示 + 登录后无条件 `push('/dashboard')` 绕过 `defaultLanding` 角色分流 | 全站 | Login | P2 | 改造 |
| G24 | 无 SaaS 自服务开通（租户靠平台超管开通） | A | PlatformAdmin | P2 | 新建（远期） |

**补：与冻结 10 态相关的缺口（贯穿全站）**

| # | 缺口 | 说明 |
|---|---|---|
| G25 | 页面状态覆盖不全 | 多数页面仅处理 LOADING/EMPTY/SUCCESS；NO_PERMISSION 仅靠 `can()` 隐藏按钮（无整页无权态）、NOT_CONFIGURED/WAITING_EXTERNAL/PARTIAL_DATA/UNKNOWN 仅 Launch 系列部分覆盖（`launchCenter.js` 空态分因、`LaunchStatusSummary` 等待平台中性色） |
| G26 | B03–B09 禁用按钮只给 409 | 设计要求「显式未接入+原因」，`LaunchStepPanel.vue` 已展示 `disabled_reason`，但需全站一致口径核对（见 G3） |

---

## ④ 首页现状诊断（`frontend/src/views/Dashboard.vue`，125 行）

**实际展示**

| 区块 | 内容 | 数据源 |
|---|---|---|
| KPI 卡 ×6 | GMV / 订单数 / 真实利润 / 广告 ROI / 在售 Listing / 待处理会话 | `GET /bi/dashboard`（`Dashboard.vue` 的 `onMounted` 内） |
| 趋势图 | 近 30 天 GMV + 订单数（折线） | 同上 |
| 饼图 | 类目销售分布 | 同上 |
| 表格 | 热销 Top5 商品 | 同上 |
| 表格 + 按钮 | 最近 AI 工作流运行 + 「去运行工作流」→`/workflows` | 同上（`Dashboard.vue` 的「去运行工作流」按钮） |

**对照首页必须回答的 6 问**

| 6 问 | 现状 | 判定 |
|---|---|---|
| 在做什么 | 无进行中上线/任务的聚合 | ❌ 缺 |
| 进展如何 | 仅工作流运行状态，无 Launch 进度 | ⚠ 部分 |
| 今天最重要 | 无 | ❌ 缺 |
| 哪些要人工 | 无待办聚合（待审批 Listing / 待处理退款 / 待核价 / 待人工告警） | ❌ 缺 |
| AI 完成了什么 | 仅工作流 run 列表 | ⚠ 极弱 |
| 哪些异常 | 告警/风险未上首页（KPI 仅「待处理会话」） | ❌ 缺 |
| （下一步） | 仅一个通用「去运行工作流」按钮，非按用户定制 | ❌ 缺 |

**A/B/C/F/G 五类用户应有内容 vs 现状差距**

| 用户 | 首页应有 | 现状 | 差距 |
|---|---|---|---|
| A 无跨境经验个人 | 「开始经营三步走」（选品→连店→上线）引导卡 + 学习资源 + 下一步按钮 | 直接展示专业 KPI（ROI/贡献利润），门槛过高，无引导 | **大** |
| B 有 1688 货源/采购经验 | 「货源机会 / 待采集 / 待标准化 / 待匹配报价」 | 无任何货源相关内容 | **大** |
| C 自有/合作工厂 | 「工厂数据完整度 / 机会匹配结果 / 待尽调」 | 无 | **大** |
| F 多人团队/企业管理员 | 「成员与权限 / 授权到期 / 审计 / 待人工审批」 | 无（能力散在 Users/PlatformAdmin/合规工作台） | **中** |
| G 外部工厂协作者 | 不应见 Dashboard（应见工厂门户） | 守卫已强制跳 `/factory-portal`（`permissions.js` 的 `routeRedirect`→`FACTORY_COLLABORATOR` 分支） —— **符合**；但工厂门户自身首页缺「任务」（见 G5） | 符合（门户另补） |

**附加事实**：Dashboard 是「除合规/工厂/超管外所有角色的统一落地页」（`permissions.js` 的 `defaultLanding` 中 OWNER/OPERATOR/READ_ONLY 均落 `/dashboard`），却用同一套指标，未做角色差异化（仅菜单过滤）——与 `docs/角色界面差异化设计方案.md §1.2` 自评一致。

---

## ⑤ 最关键的 3 个发现

1. **全站 30 页是「工具清单式」而非「任务/旅程式」信息架构**：首页只回答 6 问中的 1 个（`Dashboard.vue` 仅 BI 指标），A/B/C/D 四类用户的旅程起点（经营目标/能力画像/新手引导）与终点（创建上线/「下一步」）全部缺失 —— 不是页面不够，是缺「把页面串起来的路」（对应 G1、G2、G6）。

2. **核心业务闭环断在两处硬缺口**：`/launch` 无「创建上线流程」入口（**后端 `POST /launch` 已存在，前端未封装**，缺口纯在前端）；Launch 领域动作 B03–B09 未接通（代码事实：仅 5 个动作可用，其余 409/未接入）+ 真实在售核验未实现，Listings 发布止于「待核验」——「找货源→连店铺→选商品→开始上线」这条主旅程在 UI 上走不通（对应 G2、G3、G4）。

3. **大量 IA 错位与重复，需「重新归类+合并+收口」而非重写**：店铺授权/动态定价/供应商被归到「采购」组语义错；账龄在 Suppliers 与 Settlements 双份、合规检测双页、审批动作三套、状态字典两套、AI 日志三处 —— 同一能力被拆散在多个入口，是本次「信息架构与 UX 统一优化」最高性价比的改造面（对应 G8、G11、G12、G19、G21 及 §2 的 11 域重归类）。
