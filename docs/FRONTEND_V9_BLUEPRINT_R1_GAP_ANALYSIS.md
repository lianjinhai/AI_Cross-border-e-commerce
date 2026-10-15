# FRONTEND V9 · 蓝图 R1 增量设计规约（Gap Analysis）

> 对照基线：《AI原生跨境电商经营平台 V9.0 全站前端产品与交互详细蓝图（评审稿）》V9.0-UX-Blueprint-R1（2026-10-13）
> 现状基线：`frontend-v9/`（UX-A~F 六阶段完成，35 个 Vue 页面、11 域导航、295 测试全通过）
> 本文性质：增量设计规约，供架构师拆解文件级任务。**不修改任何代码文件。**
> 结论速览：导航 11 域 → 8 域重组（改 3 个 navigation.js + 守卫白名单）；**12 个新增页面**（含 ONB×3、WK-02、MK-03、CH-01/03、OR-03、OP-04、BI-02、AI-04）；**7 个既有页面改造**；10 个共享组件中 4 个全新、6 个既有扩展；11 态统一渲染 + 数据真实性标签为**横切规约**，建议以组件+字典落地而非逐页硬编码。

---

## 1. 域对比总表

| 蓝图 R1 域（新） | 蓝图要求 | 现状（frontend-v9） | 差距 | 建议动作 | 优先级 |
|---|---|---|---|---|---|
| ① 工作台 | WK-01 经营首页 + WK-02 全局任务中心 | `home` 域 1 项：`/app` → WorkspaceHome.vue（含待办分组+onboarding 卡） | 无独立任务中心页；TaskCenter 在 WorkspaceShell 中仍标"待装配" | 新建 WK-02 `/app/tasks`；首页按 §5.1 结构核对改造 | P0 |
| ② 发现与商品 | ONB-01~03、MK-01/02、MK-03 候选池、PR-01~03、LS-01/02、LC-01/02、AS-01、CO-01/02 | `market`(1 项)+`product`(5 项)：Discovery / Products / ProductDetail / Listings / LaunchCenter / LaunchDetail / compliance×2（StubPage） | 无候选池页；ONB 三屏未独立（仅首页一张卡）；compliance 两页仍 StubPage；PR-01 未达"专业表格"规格（批量/筛选保存/导入模板）；AS-01 素材中心无独立页（assets 在详情页内） | 新建 ONB×3 + MK-03；改造 PR-01/02；接实 compliance Stub；素材独立页 | P0 |
| ③ 货源与采购 | SU-01~04、PO-01/02、供应风险（专业） | `supply` 域 2 项：Suppliers / Purchases | 无 1688 货源发现（SUP-01）页；无货源匹配（SU-04）页；风险巡检在 optimization 域，语义应归本域专业入口 | 新建货源发现/匹配页；risk/alerts 语义并入或双挂；供应商详情增强（报价/风险） | P1 |
| ④ 渠道与店铺 | CH-01 渠道推荐、CH-02 店铺管理、CH-03 店铺健康 | `channel` 域 1 项：Shops（店铺授权） | 无渠道推荐/能力墙页；无店铺详情/健康页 | 新建 CH-01、CH-03；Ch-02 = 现有 Shops 增强 | P1 |
| ⑤ 订单与服务 | OR-01/02/03、CS-01/02、物流与履约异常 | `fulfill`(2)+`aftersale`(2)：Orders / Settlements / Refunds / Support | 无 OR-03 发货/代发/备货任务页；物流轨迹**待接入**（API 映射已标注）；订单详情需按四区结构核对 | 新建 OR-03（备货/代发分离展示）；物流异常页标"待接入" | P1 |
| ⑥ 经营优化 | OP-01 定价、OP-02 诊断、OP-03 广告、OP-04 策略实验 | `optimization` 3 项：Pricing / Ads / RiskAlerts | 无策略实验页（OP-04）；Ads 需按"真实能力受限显示"核对（蓝图 §5.13） | 新建 OP-04；Ads 加真实性标签与受限态 | P2 |
| ⑦ 财务与分析 | FN-01~03、BI-01/02 | `analytics` 3 项：Bi / Finance / LandedCost | 无 BI-02 预测与数据质量页；FN-02 对账需差异/未归因增强；真实利润需成本追溯整合 LandedCost | 新建 BI-02；Finance 增强对账差异与真实性标签 | P1 |
| ⑧ AI与自动化 | AI-01 Copilot、AI-02 行动中心、AI-03 工作流、AI-04 Agent 运行 | `aiops` 3 项：Workflows / Knowledge / AiDecisions；Copilot 在 features/aicopilot | 无独立 AI 行动中心（AI-02）；无 Agent 运行记录/额度（AI-04） | 新建 AI-02、AI-04；Copilot 保持现状（§5.15 分层核对） | P1 |
| 设置（底部/账户菜单） | SET-01 空间信息、SET-02 成员权限、SET-03 凭据、SET-04 套餐 | `settings` 2 项（requiresOwner）：AiSettings / TeamSettings | 缺 SET-01/03/04；SET-02 ≈ 现有 TeamSettings | 新建 SET-01/03/04；导航下沉至账户菜单（不与业务主导航同权重） | P2 |
| Factory Portal | FP-01~05（首页/SKU/报价产能/备货贴标/履约历史） | `factory` 域仅 1 页：FactoryProducts（产品与产能） | 现有 1 页可拆为 FP-02/03；FP-01/04/05 缺，其中备货/贴标任务投影**待接入**（API 映射标注 /factory/orders、/factory/settlements 未核） | FP-02/03 由现有页拆分；FP-01 新建；FP-04/05 建"待接入"骨架（只读任务队列+明示） | P2 |
| Platform Console | PC-01~06（总览/Workspace 与套餐/Adapter 认证/数据源规则/AI 资源/任务与审计） | `console` 域 4 页：Overview / Tenants / Audit / Maintenance | 缺 PC-03 Adapter 认证中心、PC-04 数据源与规则、PC-05 AI 资源；现有 4 页对应 PC-01/02/06/维护 | 新建 PC-03/04/05；Audit 并入"系统任务与审计"或保持 | P2 |
| 横切：11 态统一 | 蓝图 §6.4 全部列表/详情页 11 状态文案与主行动 | 现有 LoadingState/EmptyState/ErrorState/SectionState/PartialBanner/StatusBadge 仅覆盖 5~6 态（加载中/空/错误/部分数据） | 缺 NOT_CONFIGURED / NO_PERMISSION / WAITING_EXTERNAL / WAITING_USER / BLOCKED / UNCERTAIN 独立表达 | 扩展 SectionState 为 11 态状态机 + shared/pageStates.js 文案字典 | P0 |
| 横切：数据真实性 | 蓝图 §6.5 八类标签（官方已核验…数据未知） | 无对应组件；biCaliber.js 有口径概念但未做来源标签 | 全缺 | 新建 DataQualityBanner + MoneyValue（含币种/汇率/估算状态） | P0 |

---

## 2. 各域详细差距清单

> 组件路径均相对 `frontend-v9/src/`。"StubPage"指仍挂 `StubPage.vue` 的路由条目。

### 2.1 域① 工作台（现 `home`）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| WK-01 首页 | `pages/home/WorkspaceHome.vue` 已实现：待办分组、①在做什么、②进展、③今天最重要、④人工、⑤AI 完成、onboarding 卡、PartialBanner | 未按 §5.1 结构：缺"当前经营阶段（有依据才显示）"；核心 CTA 未按"状态规则推导"（无店铺→连接渠道 / 有店无品→选品 / 待 Launch→继续上线 / 稳定→处理异常）；"平台等待 / 风险异常 / AI 建议待审"四计数条未做 | 改造：按 §5.1 版式重构信息分区，CTA 用规则推导；数字卡必须带口径/可信度/更新时间（复用 §2 数据标签组件） |
| WK-02 全局任务中心 | 无页面；`shells/WorkspaceShell.vue` 第 16 行注释"待装配：TaskCenter"；`components/TaskCard.vue` 已就绪（待办深链、J2 断链归零） | 无 `/app/tasks` 路由与页面 | 新建 `pages/home/TaskCenter.vue`：跨域待办（launch/action/order/approval 四类，源 = workbench/todo），支持筛选（我的/平台等待/风险/AI 建议），行内深链带 return_to |
| AUTH-02 Workspace 选择/切换 | `components/WorkspaceSwitcher.vue` 已实现（/me/workspaces、switchWorkspace、subscribeWorkspaceChange） | 缺"新建空间"入口与切换后清除 Store 选择/缓存的明示（蓝图 §2.4 硬约束） | 扩展 WorkspaceSwitcher：切换时清 localStorage v9_selected_shop + 旧 Context；加"创建空间"跳 ONB-01 |
| ONB-01~03 | 无独立页；现状仅 WorkspaceHome 内一张 onboarding 卡（persona A/B/C 三条路径，derived 非准入依据） | 缺三屏独立页（起点选择/资产连接/经营计划检查单）；跳过不断路未实现 | 新建 `pages/onboarding/` 三屏（§5.2 规格）；跳过保留"继续准备"入口；Business Path 未接通时用明示"引导清单"，不称 AI 自动规划 |

### 2.2 域② 发现与商品（现 `market` + `product`）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| MK-01 机会雷达 | `pages/market/Discovery.vue`（discovery 端点：扫描/选品/评分） | 缺"热度/需求证据/竞争/预估售价区间/风险/数据来源与更新时间"列的完整机会卡；列表/机会卡切换 | 改造 Discovery：列表列补齐来源与更新时间；加真实性标签 |
| MK-02 机会详情/验证 | 无独立详情页（Discovery 行内展开？） | 缺"结论区 + 左市场事实/中类目与供应/右适配资源与下一动作"三栏；核心按钮 `保存到候选池 → 寻找货源 → 创建商品方案` 链未建 | 新建 `pages/market/OpportunityDetail.vue`（hidden 参数路由 `/app/market/opportunity/:id`）；数据源=discovery 读端点，无独立详情端点则页内聚合+标记 API_GAP |
| MK-03 商品候选池 | **无** | 机会→备选商品 的过渡态无处落（蓝图 §4 MK-03 Product Candidate） | 新建 `pages/market/Candidates.vue`（`/app/market/candidates`）：候选清单（来源机会 ID/证据版本可回看）、主操作"创建商品方案"（POST products）；无货源也能保存机会 |
| PR-01 商品库 | `pages/product/Products.vue`（products、product_channels 只读、pricing） | 未达 §5.4 专业表格规格：缺固定筛选（来源/类目/风险/有关联货源/在售实例）、默认列规范（缩略图+SKU/成本状态/渠道数/上线摘要）、批量成本试算/批量 Launch/导出、CSV 导入模板+映射+校验预览 | 改造 Products：固定筛选区+默认列+批量动作浮栏；导入模板若接口缺口则标"接口缺口"不建假按钮 |
| PR-02 商品详情 | `pages/product/ProductDetail.vue`（+assets） | 未按 §5.5 八 Tab（概览/货源/销售渠道/上线进度/经营表现/合规素材/AI建议/历史）；"主档 vs 某店铺外部状态"两事实区分未明示 | 改造 ProductDetail：Tab 结构对齐；渠道 Tab 显示 Listing 版本/流程状态/外部事实/下一动作四列 |
| PR-03 编辑/导入 | 产品编辑在 Products/ProductDetail 内嵌表单 | 独立字段规范+校验页未拆 | 低优：抽屉/弹层形式即可，不单独建路由（P2） |
| LS-01 Listing 工作台 | `pages/product/Listings.vue`（listings 端点：生成/优化/复核/发布/回执） | 需按"专业入口"定位核对批量/保存筛选 | 保持不变（P2 核对） |
| LS-02 版本对比 | **无** | 改动比对页缺 | 若后端无版本 API 则**不建**，在 Listings 行内标记能力缺口（待核） |
| LC-01 上线中心 | `pages/product/LaunchCenter.vue`（launchCenter.js 封装） | 未按 §5.6：缺固定快捷过滤七态、行内"继续处理/查看状态"按 WAITING_EXTERNAL 区分、创建 Launch 四步抽屉 | 改造 LaunchCenter：快捷过滤条+行内主按钮语义+四步创建抽屉 |
| LC-02 上线详情 | `pages/product/LaunchDetail.vue` + features/launch 六组件（Timeline/StepPanel/ActionDialog/StatusSummary/ExperienceToggle/WaitingExternalState） | 已有 Guided/Professional 双模；需核对：依赖图时间线（平行任务按组）、B03–B09 未实现步骤不放出假成功按钮、深链保留 launch_run_id/step_code/return_to | 改造 LaunchDetail 对照 §5.7 交互契约逐条验收（测试断言） |
| AS-01 素材/授权 | 无独立页；product_assets 在 ProductDetail 内（CRUD+verify） | 缺按 Product 关联的素材列表（权利状态/授权来源/适用范围/版本哈希/失效风险） | 新建 `pages/product/Assets.vue`（`/app/products/assets` 或挂在商品详情 Tab 提升为独立页，架构师定夺）；UNKNOWN/RESTRICTED 默认不可自动发布 <!-- docs-ok --> |
| CO-01/02 合规 | 两路由仍挂 StubPage（compliance、compliance/approvals） | 合规工作台五类队列（待审/缺证据/待补/已验证/过期）未实现 | 接实：按 API 映射（listings review-queue、compliance、shops）实现两页；材料详情 CO-02 可先并入工作台 Tab（P2 拆分） |

### 2.3 域③ 货源与采购（现 `supply`）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| SU-01 货源发现（1688/手动） | **无**（1688 是货源不是销售渠道，现状无任何入口） | 三个来源 Tab（1688/私域工厂/手动供应商）+ 筛选（SKU/币种/MOQ/交期/库存时效/授权/市场可行性） | 新建 `pages/supply/Sourcing.vue`（`/app/supply/sourcing`）；1688 端点未核 → 先落 UI 骨架+"待接入"标记，不建假数据 |
| SU-02/03 供应商列表/详情 | `pages/supply/Suppliers.vue`（suppliers、factory_network；CRUD/评分） | 详情缺"资质/目录/历史报价/采购记录/质量交付风险"；主操作 `保存供货报价/发起对接/为商品匹配` | 改造 Suppliers：详情页增强（可参数路由 hidden） |
| SU-04 货源匹配 | **无** | 左商品要求/中候选对比/右总成本与缺项；缺币种汇率日、缺物流费禁当真利润 | 新建 `pages/supply/Matching.vue`（`/app/supply/matching?productId=`）；成本假设走 pricing/costing 读端点 |
| PO-01/02 采购单 | `pages/supply/Purchases.vue`（purchases、suppliers；创建/按预测生成） | 详情四区（审批/发单/收货）核对 | 保持不变+行内详情抽屉（P2） |
| 供应风险（专业入口） | 风险巡检在 `/app/risk/alerts`（optimization 域） | 蓝图 §2.1 列"供应风险（专业入口）" | **最终归 optimize 域**（与 §4 映射表一致：risk/alerts 保留在"经营优化"域，货源域不再重复挂）；path 不变 |

### 2.4 域④ 渠道与店铺（现 `channel`）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| CH-01 渠道推荐与接入状态 | **无** | "平台能力墙"：每平台卡=目标市场/真实能力（授权/发布/订单/售后/广告）/验证等级（真实已认证/协议未验证/计划中/受限）/接入前提/开始连接；**不是 Logo 墙** | 新建 `pages/channel/Channels.vue`（`/app/channels`）；数据源=Adapter Registry/Platform Capabilities 端点未核 → 验证等级字段缺则整卡标"协议未验收"，Temu 类受限渠道明示 |
| CH-02 店铺管理/授权 | `pages/channel/Shops.vue`（shops：OAuth/刷新/同步订单/类目映射） | 列表缺"最近成功同步/待续期/支持动作/同步告警"列 | 改造 Shops：列补齐 |
| CH-03 店铺详情/健康 | **无** | 顶部三态（授权有效/商品能力已验证/订单能力已验证）+ 四 Tab（商品/订单/同步任务/证书配置） | 新建 `pages/channel/ShopDetail.vue`（hidden `/app/channels/shops/:id`） |

### 2.5 域⑤ 订单与服务（现 `fulfill` + `aftersale`）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| OR-01 订单工作台 | `pages/fulfillment/Orders.vue`（orders、shops；CSV 导入/状态流转/发货/真店同步） | 缺固定快捷队列（待处理/待采购/待发货/异常/退款中/已完成）+默认列（买家脱敏/付款履约售后三态/异常） | 改造 Orders：快捷队列条+列规范 |
| OR-02 订单详情 | 无参数路由 | 四区：订单头时间线/左订单行费用收货/中履约路径（代发/自库/工厂直发/平台备货）/右总额成本退款利润可信度 | 新建 hidden 路由 `orders/:id`（详情抽屉或独立页，架构师定夺） |
| OR-03 发货/代发/备货任务 | **无**（备货与代发必须独立展示，不能用同一"创建采购单"代替） | 履约员按模式执行页；备货显示批准量/备妥量/外部参考号/仓库证据；采购显示供货商/价格/收货 | 新建 `pages/fulfillment/Fulfillment.vue`（`/app/fulfillment`）；平台备货端点未核 → 备货区块标"待接入/人工在平台处理"，采购区块走现有 purchases 端点 |
| 物流与履约异常 | 无；API 映射明确"物流轨迹（orders 发货后履约链）**待接入**" | 蓝图 §2.1 列出此项 | **不建可点击入口**；订单详情页内"物流"位占位显示"物流轨迹待接入"（见 §7 清单） |
| CS-01/02 客服/售后 | `pages/aftersale/Support.vue`、`Refunds.vue`（support、refunds 端点） | 客服三栏工作台核对；退款须区分"内部审批完成"与"外部平台退款确认"；发送平台消息仅在真实连通消息 API 时允许 | 改造 Refunds：双状态区展示；Support：无消息 API → 明确"人工去平台处理"标识 |
| FN-02 结算与对账 | `pages/fulfillment/Settlements.vue`（settlements、suppliers；生成对账/确认/登记付款） | 归属从"订单履约"移到"财务与分析"域（导航重组）；差异/未归因展示 | 保持 path 不变，域归属改 `finance` |

### 2.6 域⑥ 经营优化（现 `optimization`）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| OP-01 定价工作台 | `pages/optimization/Pricing.vue`（pricing、workflows；利润计算/采纳建议价/重定价） | 按商品×Store 表（采购报价/供应商币种/汇率日/平台费/物流/税/广告假设/贡献利润/可信度/最低安全价）核对；核价面板"申报 vs 平台 vs 底价 vs 贡献"动作仅在合法 Action 时出现 | 改造 Pricing：字段与可信度标签；缺汇率禁当真利润（§5.13） |
| OP-02 商品/店铺诊断 | 部分由 RiskAlerts 承担 | 诊断队列（销量下降/利润变差/退款升高…）每条须带数据/阈值/时间窗/证据/措施/历史 | 改造 RiskAlerts 为"商品与店铺诊断"（label 对齐，可保持 path） |
| OP-03 广告与增长 | `pages/optimization/Ads.vue`（ads、actions；活动 CRUD/优化/AI 选词，审批走 actions） | 未接入投放 API 时只能展示导入分析/策略草案并标"人工建议"，不得出现"已投放" | 改造 Ads：真实性标签 + 受限态（对照 UX-20 验收） |
| OP-04 策略实验 | **无** | 建议→实验→结果的追踪（蓝图 §2.1"优化建议与策略实验"） | 新建 `pages/optimization/Experiments.vue`；后端无实验端点 → 建骨架+"待接入"标记（只读展示 AI 决策依据中的建议，不建假 A/B） <!-- docs-ok --> |

### 2.7 域⑦ 财务与分析（现 `analytics`）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| FN-01 经营总览 | `pages/analytics/Bi.vue`（bi 端点） | §5.14 版式核对：GMV/净收入/贡献利润/结算到账/退款率五指标**不得混用"收入"标签**；币种+日期口径；估算分摊明示 | 改造 Bi：指标卡带口径与数据标签；图表点 Store/商品 带筛选跳明细 |
| FN-03 真实利润 | 成本在 LandedCost + Finance 分散 | 利润明细需成本追溯（采购/物流/平台费/广告拆解）与可信度 | 改造 Finance：利润拆解区；LandedCost 保持为配置页 |
| BI-02 预测与数据质量 | **无** | 预测页（训练样本/连续性/真实数据比例/窗口/模型版本/WAPE）+ 数据质量（未到账/对账差异/缺成本/缺汇率/来源混合→跳明细修复） | 新建 `pages/analytics/Forecast.vue`（`/app/analytics/forecast`）；无预测端点 → 预测区"待接入"，数据质量区基于现有 finance/orders 缺项统计可先行 |
| 到岸成本配置 | `pages/analytics/LandedCost.vue`（cross-border 四组 CRUD+试算） | 保持不变 | 保持不变 |

### 2.8 域⑧ AI 与自动化（现 `aiops`）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| AI-01 Copilot | `features/aicopilot/AiCopilot.vue`（ai 端点；会话持久化**待接入**） | 按 §5.15 分层核对：打开即带上下文（空间/页面/对象/可帮任务）；回答区分事实/估算/判断；切空间不得延续旧对象 | 保持现状+契约核对；会话不持久化须明示"本次会话结束后不保留" |
| AI-02 AI 行动中心 | 无独立页（AiDecisions 是只读决策依据；actions 审批散在 ads 等页） | 建议/审批/执行/结果全生命周期列表（对象/原因/证据摘要/风险/口径/状态/来源/审批人/结果/下一操作） | 新建 `pages/aiops/AiActions.vue`（`/app/ai/actions`）：actions 端点已存在（approve/reject/execute），可直接落地 P0 |
| AI-03 工作流 | `pages/aiops/Workflows.vue`（workflows、/schedules；模板/调度/恢复） | 专业工作流 Run/Template/FlowKind/阶段耗时/重试/事件日志核对；Launch 与 LEGACY_AUTOMATION 语义区分 | 改造 Workflows：列补齐 |
| AI-04 Agent 运行与额度 | **无** | 轨迹/成本/失败/配额（管理员视角） | 新建 `pages/aiops/AgentRuns.vue`（`/app/ai/agent-runs`，requiresOwner）；Agent Observability 端点未核 → "待接入"骨架，只读 <!-- docs-ok --> |
| AI 知识库 | `pages/aiops/Knowledge.vue`（knowledge、ai） | 保持不变（权限允许者可见） | 保持不变 |

### 2.9 设置（现 `settings`，仅 OWNER）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| SET-01 空间信息/经营偏好 | 无 | Workspace 名称/PERSONAL-ORGANIZATION/目标/地区偏好；升级不触发数据迁移 | 新建 `pages/settings/WorkspaceInfo.vue`（`/app/settings/workspace`，requiresOwner）；me/workspace 端点，未核字段标缺口 |
| SET-02 成员与权限 | `pages/settings/TeamSettings.vue`（auth；成员增改/角色分配） | 缺 Data Scope/最近访问/邀请状态/最后 OWNER 保护；外部工厂协作者不得列进普通成员 | 改造 TeamSettings：列补齐；工厂协作者独立分组 |
| SET-03 凭据管理 | **无** | 店铺 OAuth + AI 凭据仅显尾部/状态，不回显明文；平台级/Workspace 级作用域区分 | 新建 `pages/settings/Credentials.vue`（`/app/settings/credentials`）；shops OAuth 端点可复用，AI 凭据走 settings/ai 现有能力 → 聚合展示 |
| SET-04 套餐与使用量 | **无**（Subscription 待核） | 费用/配额/能力/升级 | 新建 `pages/settings/Plan.vue`（requiresOwner）；无 Subscription 端点 → 整页"待接入"占位，**不建假数据** <!-- docs-ok --> |

### 2.10 Factory Portal（现 `factory` 1 页）与 Platform Console（现 `console` 4 页）

| 蓝图项 | 现状 | 差距 | 动作 |
|---|---|---|---|
| FP-01 工厂门户首页 | 无（登录即进 products） | 本厂待办（报价 N 条/备货 N 个/贴标 N 次）+ 我方 SKU 侧栏 | 新建 `pages/factory/FactoryHome.vue`（`/factory` 重定向到此）；待办数据=factory_network portal 端点未核 → 骨架+"任务同步中/暂无" |
| FP-02 商品/SKU | `pages/factory/FactoryProducts.vue`（portal 产品/产能 CRUD） | 拆分：商品目录 | 改造为 FP-02（path 改为 `/factory/catalog` 或保持，架构师定夺；旧 /factory/products 302 查表需同步） |
| FP-03 报价/库存/产能 | 现 FP-02 内含产能 | 报价/MOQ/币种/库存时效独立 | 拆出新页 `pages/factory/Capability.vue` |
| FP-04 备货/贴标任务 | 无；factory task projection **待接入** | 任务详情（要求数量/交期/参考图/材料）+ 确认受理/提交证明/无法完成 | 新建 `pages/factory/StockingTasks.vue` 只读队列+"待接入"标记；有任务端点后接写操作 |
| FP-05 履约与历史 | 无；/factory/orders、/factory/settlements **待接入** | 本厂订单任务与历史 | 新建 `pages/factory/FulfillmentHistory.vue` 占位"待接入"；禁止复用卖家 Launch DTO |
| PC-01 平台总览 | `pages/console/Overview.vue`（admin、shops、ai、auth） | 平台级运行指标（活跃空间/连接健康/后台失败/AI 消耗/需复核能力），不默认显示跨租户明细 | 改造 Overview：指标口径核对 |
| PC-02 Workspace 与服务 | `pages/console/Tenants.vue` | 租户+套餐管理；代客进入须原因/时间/操作者/审计 | 改造 Tenants：代客操作挂审计字段 |
| PC-03 Adapter 认证中心 | 无 | 能力拆到授权/发布/在售核验/订单/退款子能力，每项协议实现+真实联调状态+证据时间 | 新建 `pages/console/Adapters.vue`；Registry 端点未核 → 验证等级缺显"尚未验证" |
| PC-04 数据源与规则 | 无 | 来源/适用范围/版本/有效期/最近拉取/错误/回滚 | 新建 `pages/console/Rules.vue`；Maintenance 页现有"规则检查"能力可并入 |
| PC-05 AI 资源与成本 | 无 | 模型路由/Token/成本/限流/配额，仅真实数据可用时显示 | 新建 `pages/console/AiResources.vue`；ai 端点有配额读？未核 → 缺显"未接入" |
| PC-06 系统任务与审计 | `pages/console/Audit.vue` + `Maintenance.vue` | 任务看板（排队/运行/等待外部/未知结果/重试死信/失败）；缺独立 Worker 功能时明示"平台能力未就绪" | Audit 保持；Maintenance 增加任务看板区（数据缺 → "未就绪"态） |

---

## 3. 新增页面规格（12 页 + 拆分项）

> 每页七要素：入口 / 面包屑 / 数据来源 / 主操作 / 关联深链 / 11 态说明 / 证据审计 / 角色限制。
> 通用约定：全部页面遵守 §6 横切规约（11 态 + 数据标签 + 深链上下文），下表只写页面特有差异；`return_to` 白名单限站内路径；参数路由均 `hidden`。

### 3.1 WK-02 全局任务中心 `pages/home/TaskCenter.vue` → `/app/tasks`
- **入口**：主导航"工作台"下第 2 项；顶栏"待办"计数深链；首页"今天最重要"整卡链接
- **面包屑**：工作台 > 我的任务；顶栏显示 Workspace 名 + 数据截止时间
- **数据来源**：`/workbench/todo`（四类：launch/action/alert/review，V1.2 signals 契约）；无聚合端点缺口
- **主操作**：行内"去处理"深链到对应业务页（TaskCard 已实现）；页级无写操作
- **关联深链**：每条待办带 source 域 + object_id；从业务页回来须 `return_to=/app/tasks` 保持筛选
- **11 态**：LOADING 骨架；EMPTY_NEW="你还没有待办"→跳首页主 CTA；EMPTY_FILTER=重置；NO_PERMISSION=该角色无权（COMPLIANCE 只见自己的审批队列，服务端过滤）；ERROR=重试；待办计数 badge 取同源
- **证据审计**：页面底部"上次更新 X 分钟前"；单条待办展示来源与创建时间
- **角色**：所有授权用户；各类型待办由服务端按权限裁剪

### 3.2 ONB-01/02/03 `pages/onboarding/` → `/onboarding`（新空间后默认落点；三屏单路由 step 或三段路由由架构师定，建议 `/onboarding?step=1..3`）
- **入口**：新建 Workspace 后自动进入；已跳过者从首页"继续准备"恢复
- **面包屑**：设置 > 经营起步（或不带面包屑的向导形态）
- **数据来源**：ONB-01 纯前端（五选项）；ONB-02 资产连接=shops/suppliers/factory_network 各自接入态；ONB-03 Business Path **未接通** → 用"引导清单"静态规则呈现，页面标注"引导清单（非 AI 自动规划）"
- **主操作**：ONB-01 选择起点（可跳过）；ONB-02 每屏最多三项任务（跳各模块接入页）；ONB-03 生成路径 → "进入我的任务"（跳 WK-02）
- **11 态**：ONB-02 每个接入卡按目标模块真实状态渲染（未连接=NOT_CONFIGURED→接入；同步中=WAITING_EXTERNAL；部分数据=PARTIAL_DATA）；无假进度
- **角色**：新空间创建者/OWNER；成本金额无证据不显示

### 3.3 MK-02 机会详情 `pages/market/OpportunityDetail.vue` → `/app/market/opportunity/:id`（hidden）
- **入口**：MK-01 行点击；深链
- **数据来源**：discovery 读端点（若需聚合 Opportunity/Costing 则页内组合，缺端点标 API_GAP）
- **主操作**：`保存到候选池`（幂等）→ 跳 MK-03；`寻找货源`→ SU-01；`创建商品方案`→ POST products 后跳 PR-02
- **11 态**：证据不足/数据陈旧 → BLOCKED 文案"证据不足，不得视为爆款"；EMPTY_NEW 不适用；等待外部数据源=WAITING_EXTERNAL
- **角色**：卖家/运营；合规角色不可见（白名单过滤，filter.js 同步）

### 3.4 MK-03 商品候选池 `pages/market/Candidates.vue` → `/app/market/candidates`
- **入口**：主导航"发现与商品"；MK-02 保存后自动出现
- **数据来源**：Product Candidate 读端点**未核** → 若缺：以 products 列表 + 筛选"来源=机会/候选"降级实现并标 API_GAP（架构师核 backend 后二选一）
- **主操作**：`创建商品`（POST products）→ 跳 PR-02；行内"来源机会"回看机会 ID 与证据版本
- **11 态**：EMPTY_NEW="还没有候选商品"→跳市场发现；NO_PERMISSION 正常
- **角色**：卖家/运营

### 3.5 CH-01 渠道中心 `pages/channel/Channels.vue` → `/app/channels`
- **入口**：主导航"渠道与店铺"第 1 项；ONB-02 渠道任务
- **数据来源**：Platform Capabilities/Adapter Registry 端点**未核** → 未核前：平台卡静态目录 + 能力字段一律标"协议未验收"，仅 shops 端点能证实的授权状态可显示
- **主操作**：`开始连接`→ CH-02 授权流；受限渠道（Temu）主操作=`查看接入前提与材料`（只读，不出现"连接"按钮）
- **11 态**：NOT_CONFIGURED="未连接该渠道"→材料清单；WAITING_EXTERNAL="OAuth 等待平台回调"
- **角色**：卖家/运营；无销售域权限者只读

### 3.6 CH-03 店铺详情/健康 `pages/channel/ShopDetail.vue` → `/app/channels/shops/:id`（hidden）
- **入口**：Shops 列表行点击；首页店铺告警深链
- **数据来源**：shops（授权/最近同步/告警）；订单/商品能力验证端点**未核** → 三态中未核项显示"未验证"而非 ✅
- **主操作**：`重新授权`（AsyncActionDialog 二次确认+不可逆影响说明）；Tab 内按能力跳转
- **11 态**：授权失效=BLOCKED+"去恢复授权"；同步失败=PARTIAL_DATA+缺项入口；WAITING_EXTERNAL=刷新状态（禁盲重试）
- **角色**：该 Store 在 Data Scope 内才可见（服务端 403 → NO_PERMISSION 页）

### 3.7 OR-03 发货/代发/备货 `pages/fulfillment/Fulfillment.vue` → `/app/fulfillment`
- **入口**：主导航"订单与服务"；订单详情履约路径区深链
- **数据来源**：采购=purchases（已有）；平台备货端点**未核** → 备货区"待接入"占位+人工在平台处理引导；代发=purchases/dropship 链路（API 映射已有）
- **主操作**：按订单当前履约模式显示单一主按钮（`委托代发` / `登记发运` / `创建采购`）；备货批准量/备妥量只读
- **11 态**：WAITING_EXTERNAL=平台备货等待中；UNCERTAIN=发运结果待核查（禁重发）；BLOCKED=缺采购前置
- **角色**：履约员/采购员；金额列受 Data Scope 保护

### 3.8 OP-04 策略实验 `pages/optimization/Experiments.vue` → `/app/optimization/experiments` <!-- docs-ok -->
- **入口**：主导航"经营优化"（专业入口可默认收起）
- **数据来源**：后端实验端点**不存在** → P2 骨架页：只读展示 AiDecisions 中"建议类"记录 + 明示"策略实验能力待接入，以下为历史建议记录"
- **主操作**：无（不建假 A/B 按钮）；`查看决策依据`→ AI 决策页
- **11 态**：NOT_CONFIGURED 主态；接入后切真实数据
- **角色**：运营/专业用户

### 3.9 BI-02 预测与数据质量 `pages/analytics/Forecast.vue` → `/app/analytics/forecast`
- **入口**：主导航"财务与分析"
- **数据来源**：预测端点**未核** → 预测区待接入占位；数据质量区可先行（基于 finance/orders 缺项：未到账/对账差异/缺成本/缺汇率/来源混合，各自统计与跳明细）
- **主操作**：数据质量行 `修复/跳明细`（结算/财务页带筛选深链）
- **11 态**：PARTIAL_DATA 主态；预测未达商用门槛显示"仅参考"，禁自动采购
- **角色**：财务/负责人

### 3.10 AI-02 AI 行动中心 `pages/aiops/AiActions.vue` → `/app/ai/actions`
- **入口**：主导航"AI 与自动化"；顶栏待办审批数；AI 建议深链
- **数据来源**：`actions` 端点（已接，approve/reject/execute）
- **主操作**：列表行 `审批`（AsyncActionDialog：对象/Store/金额币种/前置条件/审批人）；执行后结果不确定=UNCERTAIN"核查中"，409 刷新不丢输入
- **11 态**：EMPTY_FILTER/EMPTY_NEW（"AI 还没有提出建议"）；旧审批失效=BLOCKED 明示
- **角色**：运营/审批人；COMPLIANCE 仅见自己队列

### 3.11 AI-04 Agent 运行与额度 `pages/aiops/AgentRuns.vue` → `/app/ai/agent-runs`（requiresOwner） <!-- docs-ok -->
- **入口**：主导航"AI 与自动化"（管理员项）
- **数据来源**：Agent Observability 端点**未核** → 整页"待接入"骨架：只读队列+明示"运行记录与配额数据未接入"，**不编造 Token 成本**
- **主操作**：无（接入后：查看轨迹/重试失败）
- **11 态**：NOT_CONFIGURED 主态；接入后 UNCERTAIN=未知结果队列
- **角色**：OWNER/管理员

### 3.12 管理侧与工厂侧新增页（紧凑规格）

| 页面 | 路径 | 数据来源 | 主操作 | 11 态/角色要点 |
|---|---|---|---|---|
| SET-01 空间信息 | `/app/settings/workspace` | me/workspace 端点（字段未核） | 保存偏好（写操作走现有端点，缺口标出） | requiresOwner；升级不触发 Product/Order 迁移（页面文案明示） |
| SET-03 凭据管理 | `/app/settings/credentials` | shops OAuth + settings/ai 现有凭据聚合 | 连接/续期/吊销（AsyncActionDialog） | 仅显状态与尾部掩码，禁明文回显；requiresOwner |
| SET-04 套餐 | `/app/settings/plan` | Subscription 未核 | 无写操作 | 整页"待接入"占位；requiresOwner |
| FP-01 工厂首页 | `/factory`（重定向目标） | factory_network portal | "去处理"深链到任务 | 待办未核→"暂无任务"空态；只收工厂身份绑定 DTO，不渲染卖家财务字段 |
| FP-04 备货/贴标 | `/factory/stocking` | task projection 待接入 | 只读队列+"待接入"；接入后 确认受理/提交证明/无法完成 | 工厂授权某贴标步骤≠批准整条 Launch（文案约束） |
| FP-05 履约历史 | `/factory/fulfillment` | /factory/orders、/factory/settlements 待接入 | 无 | 占位页；禁复用卖家 Launch 详情 JSON |
| PC-03 Adapter 认证 | `/console/adapters` | Registry 未核 | 无（只读证据） | 每项能力缺=显"尚未验证"；证据时间必显 |
| PC-04 数据源与规则 | `/console/rules` | admin 规则端点（Maintenance 现有能力并入） | 规则启用/停用（现有写端点） | 版本/有效期/最近拉取缺项明示 |
| PC-05 AI 资源 | `/console/ai-resources` | ai 配额读端点未核 | 无 | 缺数据=不渲染图表，显"未接入" |

FP-02/03 为现有 `FactoryProducts.vue` 的拆分（catalog / capability 两页），非全新页面，规格并入 §2.10 执行。

---

## 4. 导航重组映射表（旧 11 域 → 新 8 域）

> 仅改 `workspace-navigation.js` 的域 label/分组与 `meta.domain` 标签；**path 全部保持不变**（302 查表、深链、测试 295 条均不受影响），domain 中文标签同步改（面包屑同源）。Settings 从主导航下沉：保留路由与 requiresOwner 守卫，主导航底部账户菜单挂 3 项（空间信息/成员权限/凭据），套餐挂账户菜单"升级套餐"。

| 旧域 key（11） | 旧 label | 新域（8） | 新 label | 新域内 items（path 不变，★=新增） |
|---|---|---|---|---|
| `home` | 首页 | `workbench` | 工作台 | `/app` 经营首页；★`/app/tasks` 我的待办 |
| `market` | 市场机会 | `discovery` | 发现与商品 | `/app/market/discovery` 市场机会；★`/app/market/candidates` 商品候选池；`/app/products` 商品库；`/app/listings` Listing 工作台；`/app/launch` 上线中心 |
| —（新增合规/素材归属） | | `discovery` | 发现与商品 | `/app/compliance` 合规报告；`/app/compliance/approvals` 合规工作台；`/app/products/assets`★ 素材中心 |
| `product` | 商品经营 | 拆散 | （并入上） | 原 5 项 → 发现与商品 4 项 + 合规/素材 3 项（原 compliance 从"商品经营"挪出，与商品主链路区分） |
| `supply` | 货源中心 | `supply` | 货源与采购 | ★`/app/supply/sourcing` 货源发现；`/app/supply/suppliers`；★`/app/supply/matching` 货源匹配；`/app/supply/purchases`；（专业入口）`/app/risk/alerts` 供应风险 |
| `optimization`(risk/alerts 项) | 经营优化·风险巡检 | `supply` | 货源与采购 | risk/alerts 移入本域专业入口（path 不变） |
| `channel` | 销售渠道 | `channel` | 渠道与店铺 | ★`/app/channels` 渠道推荐；`/app/channels/shops` 店铺管理 |
| `fulfill`(orders/settlements) | 订单履约 | `orders` | 订单与服务 | `/app/orders` 订单工作台；★`/app/fulfillment` 发货/代发/备货；`/app/refunds` 售后退款；`/app/support` 客户消息 |
| `aftersale` | 客户售后 | `orders` | 订单与服务 | 原 2 项并入上 |
| `optimization`(pricing/ads) | 经营优化 | `optimize` | 经营优化 | `/app/pricing` 定价与利润试算；`/app/ads` 广告与转化；★`/app/optimization/experiments` 策略实验；（诊断=RiskAlerts 改名归入本域或双挂，架构师定：建议 risk/alerts 保留在 supply 域，optimize 域加"商品与店铺诊断"指向同 path 不同 item 需去重 → **最终：risk/alerts 归 optimize 域，supply 域不加诊断项**，修正 §2.3） |
| `analytics`(bi/finance/landed-cost) | 数据分析 | `finance` | 财务与分析 | `/app/analytics/bi` 经营总览与 BI；`/app/settlements` 结算与对账（挪入）；`/app/analytics/finance` 真实利润；`/app/analytics/landed-cost`；★`/app/analytics/forecast` 预测与数据质量 |
| `aiops`(3 项) | AI 运营 | `ai` | AI 与自动化 | ★`/app/ai/actions` AI 行动中心；`/app/ai/workflows` 工作流；★`/app/ai/agent-runs` Agent 运行（OWNER）；`/app/ai/knowledge` 知识库；`/app/ai/decisions`（专业入口可收起） |
| `settings` | 设置与管理 | 下沉 | 账户菜单 | 主导航不占 8 域名额；账户菜单=空间信息★/成员权限/凭据★/套餐★；`/app/settings/ai`、`/app/settings/team` 路由保留 |

**新手抑制规则**（蓝图 §2.1）：GUIDED 模式仅展开与用户画像相关的域（画像 A 显示 工作台/发现与商品/渠道与店铺；B 加 货源与采购/订单与服务；C 加 订单与服务/AI），"常用/全部功能"切换；PROFESSIONAL 全量展开。落地方式：`buildDomains` 增加 `persona` 参数，导航渲染层过滤，**路由守卫白名单不变**（权限服务端双重限制，抑制仅是视觉层）。

**filter.js / types.js 同步项**：NAV_BADGES 增加 `tasks`（待办计数=workbench/todo 长度）；COMPLIANCE 白名单按新域 items 重新枚举（path 集合不变，只是分组变了）。

---

## 5. 共享组件规格（10 个，含现状定位）

> 现状定位：`components/` 21 个中 **WorkspaceSwitcher / StoreSwitcher（≈StoreScopeSelector）/ EvidencePanel（≈EvidenceViewer）已存在**；其余 6 个全新。落地目录统一 `components/`（与现有一致），契约如下。

### 5.1 现有组件扩展（3）

| 组件 | 现状 | 按蓝图 §8.2 需补 |
|---|---|---|
| `WorkspaceSwitcher.vue` | props: workspaces/activeId；emits: switch | ① 切换时同步清 localStorage `v9_selected_shop` 与列表筛选缓存（当前是否已做需核）；② 切换期间顶栏显"切换中，旧数据已失效"（getWorkspaceEpoch 丢弃过期快照已有，补视觉态）；③ 增加"新建空间"项 → ONB-01 |
| `StoreSwitcher.vue`（≈StoreScopeSelector） | props: shops/modelValue | ① 命名/文档对齐"StoreScope"语义：仅销售店铺，**禁止把 source 类型店铺当销售过滤**；② 未接店铺引导项（跳 CH-01）；③ "全部/特定"两态持久化键沿用 `v9_selected_shop` |
| `EvidencePanel.vue`（≈EvidenceViewer） | 已存在 | 补 props：`source`、`verified`（官方已核验布尔）、`scope`（适用范围）、`version`、`expiresAt`、`refObject`；未核验默认中性样式（非绿色） |

### 5.2 全新组件（6）+ 扩展 1（SectionState 11 态化）

```js
// BusinessStatus.vue —— 状态徽章增强（替代裸 StatusBadge 场景）
props: { standard: String /* 标准态码 */, raw: String /* 原始状态，PRO 模式显示 */,
         evidenceLevel: String /* 数据标签码，见 §6.5 */, updatedAt: String, note: String }
// 规则：外部等待=中性色（禁红色误报）；PRO 模式才显 raw；点击展开 note
// 配套：shared/pageStates.js 导出 11 态字典 {code, title, actionText, tone}，
//       所有列表/详情页经 SectionState state prop 消费，文案不允许页面自写

// NextActionPanel.vue
props: { availableActions: Array /* {code,label,kind:'primary|secondary',reason?,confirm?} */,
         object: Object /* 对象身份 {type,id,store} */ }
emits: { select(action), confirm(action) }
// 规则：恰一个 primary；无权限=不渲染并显只读解释；业务不可执行=reason+补救入口；
//       技术未接通=灰化+"暂不支持"；confirm=true 走 AsyncActionDialog

// AsyncActionDialog.vue
props: { action, context, idempotencyKey, revision /* CAS */ }
emits: { submit, done(result), uncertain }
// 状态机：提交中 → 成功/失败/409(状态已变→刷新)/超时(UNCERTAIN:"结果待核查")；
//         超时后只允许"重新查询状态"，禁盲重试副作用

// MoneyValue.vue
props: { value, currency, analysisCurrency, fxDate, estimated: Boolean, unit:'unit|total' }
// 必显：币种 + 汇率基准日（fxDate 缺=显"汇率未知"）+ 估算/已结算标签；缺值不渲染 0

// EntityLink.vue
props: { objectType, objectId, storeId?, workflowRunId?, stepCode?, returnTo }
// 生成站内白名单深链；无权限对象点击 → /403 安全错误页（不渲染敏感数据）

// DataQualityBanner.vue
props: { tag /* 八类标签码，见 §6.5 */, detail?, links? /* 跳缺项明细 */ }
// 合同测试/演示环境须常显（部署层注入，非页面各自判断）

// SectionState.vue（既有，扩展）
// 现有 state: 'loading'|'empty'|'error'|'partial' → 扩为 11 态码透传 +
// props: { state, code /* 11 态码 */, emptyHint, actionText, onAction }
// 每列表/详情区块统一走此组件，杜绝逐页自写空态文案
```

---

## 6. 优先级建议

### P0（必须，首批交付）
1. **导航 11→8 域重组**（§4）：3 个 navigation.js + meta.domain 标签 + filter.js 白名单 + 新手抑制；path 不变，302 与 295 测试可回退验证
2. **11 态统一渲染**：pageStates.js 字典 + SectionState 扩展 + BusinessStatus；先落工作台/列表 5 个高频页试点再铺开
3. **数据真实性标签 + MoneyValue + DataQualityBanner**：所有金额/指标卡先接（首页/BI/定价/财务四处），八类标签字典进 shared/
4. **WK-02 任务中心**（数据已齐，纯前端聚合页，价值最高）
5. **AI-02 行动中心**（actions 端点已接，补齐审批闭环可见性）
6. **MK-03 候选池 + ONB-01~03**（新空间首次体验，Business Path 未接通按"引导清单"降规格）
7. **compliance 两页 StubPage 接实**（现有路由空壳，验收矩阵 UX-07 依赖）

### P1（重要，二批）
8. CH-01/CH-03、PR-01/PR-02 规格升级（专业表格/八 Tab）、LC-01/02 契约核对整改、OR-03、BI-02、FN-02 对账差异、SET-01/03、FP-01/02/03 拆分、PC-01/02 改造
9. 深链上下文（return_to + workflow_run_id/step_code）在 launch→compliance→返回 全链路打通（验收 UX-10）

### P2（可延后，三批）
10. OP-04 策略实验（骨架待接入）、AI-04（骨架）、SET-04（骨架）、FP-04/05（待接入占位）、PC-03/04/05、AS-01 素材独立页、LS-02 版本对比（视后端能力决定建或不建）

### 执行约束
- 每批完成跑全量 295 测试 + 导航无 404 回归（原业务入口不丢失）；
- 新页先挂 11 态 + 数据标签组件，禁止页面内自写空态文案；
- "待接入"页一律只读骨架 + 明示文案，**禁止假按钮、假数据、假成功态**（蓝图 §12.2 逐条对照）。

---

## 7. 待接入标记清单（后端未支持 → 标"待接入"，不建假按钮）

| # | 功能 | 所在位置 | 依据 | 标记方式 |
|---|---|---|---|---|
| 1 | 物流轨迹（发货后履约链） | OR-02/03、订单详情 | API 映射"待接入"节 | 物流区块占位"物流轨迹待接入"，仅显已知的发运登记态 |
| 2 | AI 会话历史持久化 | AI-01 Copilot | 同上 | 抽屉顶部明示"会话不保存" |
| 3 | /factory/orders、/factory/settlements | FP-05 | factory_network 端点未核 | 履约历史页整页占位"待接入" |
| 4 | 工厂侧 AI 产品资料生成 | FP-02 | product_assets 工厂侧复用待确认 | 不出现"AI 生成"按钮 |
| 5 | 工厂任务投影（备货/贴标） | FP-04 | 蓝图 §4 明示"待接入" | 只读队列+"待接入"；写操作暂缺 |
| 6 | 平台备货申请 | OR-03 | §7 契约"区分本地状态与平台状态" | 备货区"平台备货待接入，请人工在平台处理" |
| 7 | 1688 货源 API | SU-01 | 端点未核 | 1688 Tab 显"未接入，手动添加供应商可用" |
| 8 | Platform Adapter Registry 读端点 | CH-01、PC-03 | 未核 | 验证等级一律"协议未验收/尚未验证" |
| 9 | Subscription/套餐 | SET-04 | 蓝图 §4"待核" | 整页占位 |
| 10 | 预测模型端点 | BI-02 | 未核 | 预测区"待接入"，数据质量区先行 |
| 11 | Business Path / 经营路径 | ONB-03 | 蓝图 §5.2 明示未接通 | 用静态"引导清单"替代，页面标注非 AI 规划 |
| 12 | Agent Observability | AI-04 | 未核 | 整页占位"运行记录未接入" |
| 13 | Product Candidate 读端点 | MK-03 | 未核 | 降级=products+来源筛选，标 API_GAP |
| 14 | 策略实验端点 | OP-04 | 不存在 | 只读历史建议+"待接入" |
| 15 | Listing 版本 API | LS-02 | 未核 | 不建页；Listings 行内标"版本对比未支持" |
| 16 | 广告投放真实 API | OP-03 | UX-20 验收项 | 无投放控制 UI；仅导入分析/策略草案+"人工建议"标签 |
