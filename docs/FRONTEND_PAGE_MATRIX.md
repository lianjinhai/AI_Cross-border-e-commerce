# 前端页面矩阵（UX-00）

> 最后更新：2026-10-13
> 覆盖：`frontend/src/views/` **全部 30 个 .vue**（含 3 个非路由页）。
> 口径：冻结 v1.0 —— 一级 IA 11 域；页面本体不重写，仅重新归类 + 调导航；独立域 `/platform-admin`、`/factory-portal`；框架/原子 `/login`、Layout、AiAssistant、RunStatus。
> 字段取自实读源码，取不到的写「待确认」，不编造。
> 配套：`docs/FRONTEND_UX_AUDIT.md`（缺口 G1–G26）、`docs/FRONTEND_USER_JOURNEYS.md`（A–H/A–G）。

**角色代号**：OWNER 管理员 / OPERATOR 运营 / READ_ONLY 只读 / COMPLIANCE 合规审批 / PLATFORM_ADMIN 超管 / FACTORY_COLLABORATOR 工厂伙伴。
**用户代号**：A 无经验个人 / B 有 1688 货源 / C 自有工厂 / D 已有店铺卖家 / E 专业运营 / F 团队管理员 / G 外部工厂协作者。

---

## 表一 · 页面身份与流转（30/30）

| # | 页面 | 路径 | 服务用户 | 主要职责 | 入口 | 出口 | 核心数据 | 后端 API |
|---|---|---|---|---|---|---|---|---|
| 1 | Login | /login | 未登录全体 | 登录鉴权 | 应用根 / 未认证重定向 | `/dashboard`（硬编码，忽略角色分流，待确认是否本轮修） | token / user / context | `POST /auth/login`；`GET /me/workspace-context` |
| 2 | Layout | 路由父级（非独立路由） | 全体已登录 | 侧边菜单 + 顶栏 + 只读横幅 + 挂载 AI 助手 | 所有业务路由父级 | logout→`/login`；退出代客→`/platform-admin` | Context(role/menus)、代客状态 | `GET /me/workspace-context` |
| 3 | RunStatus | 无路由（应移入 components/ 的 StatusTag） | 全体 | 状态 tag 原子组件 | 被 Dashboard/Compliance/Alerts/Workflows/Suppliers/Listings 引用 | — | status→文案/颜色 | 无 |
| 4 | AiAssistant | 无路由（全局悬浮 FAB） | 全体租户用户（工厂隐藏） | 自然语言助手，调度 Agent | 右下角悬浮球（全局） | 回复文本 + actions tag（当前不可点击） | 对话消息 | `POST /ai/chat` |
| 5 | Dashboard | /dashboard | OWNER/OPERATOR/READ_ONLY（+ COMPLIANCE 白名单） | 概览驾驶舱 | 菜单「概览/驾驶舱」；除合规/工厂/超管外默认落地 | 仅「去运行工作流」→`/workflows` | `/bi/dashboard` | `GET /bi/dashboard` |
| 6 | Discovery | /discovery | E/B | 趋势扫描 + 关键词扩展 + AI 选品 + 机会评分 | 菜单「商品/商品发现」 | 无（结果不落地到商品池） | trends / expanded / picked / scores / performance | `/discovery/trends`(+scan/import/source)、`/expand`、`/pick`、`/scores`、`/performance/{id}` |
| 7 | Products | /products | E/B | 商品池 CRUD + 采集 + 标准化 + 一件代发 + 详情多 tab | 菜单「商品/商品池」 | 无（无去 Listing/上线中心按钮） | products / detail(attrs,offers,listings,pricing,compliance,scores) / performance | `/products`(+collect/collect_url/collect_html/{id}/standardize/{id}/assets)、`/purchases/dropship` |
| 8 | Listings | /listings | E | Listing 生成/优化/编辑/复核/发布/回执 | 菜单「商品/Listing 工作台」 | 发布弹窗、回执弹窗（无去上线中心） | listings / reviewResult / pubShops / readiness / receipts | `/listings`、`/generate`、`/{id}/optimize`、`/{id}/review`(+approve)、`/{id}/publish`、`/listings/review-queue`、`/shops/{id}/listing_readiness/{listingId}` |
| 9 | Compliance | /compliance | COMPLIANCE/E | 发起合规检测 + 报告列表 | 菜单「商品/合规检测」（合规白名单） | 无 | reports / score / issues | `/compliance/reports`、`/compliance/check` |
| 10 | ComplianceWorkbench | /compliance-workbench | COMPLIANCE | 合规员专属：待审批 / 高风险 / 规则状态 / 发起检测 | 菜单首位；合规员默认落地 | 审批后就地（无「返回原任务」） | review-queue / highRisk / rules | `/listings/review-queue`、`/compliance/reports?risk_level`、`/shops/platform_rules`、`/listings/{id}/review/approve`、`/compliance/check` |
| 11 | LaunchCenter | /launch | E/F | 上线流程列表（11 列 / 11 筛选 / 服务端分页） | 菜单「商品/上线中心」 | `/launch/:id` 详情 | `/launch`(page_num) / context / products | `GET /launch`、`/launch/context`、`/products`（**创建端点 `POST /launch` 后端已有，前端未封装**） |
| 12 | LaunchDetail | /launch/:id | E/F | 双模式(GUIDED/PROFESSIONAL) 详情 + 时间线 + 步骤 + 动作 | `/launch` 行点击（带 return_to） | 返回列表；professional_links（目前仅 `/listings`） | detail / steps / events | `/launch/{id}`、`/{id}/steps`、`/{id}/events`、`/{id}/actions/{action}`、`/{id}/sync` |
| 13 | Shops | /shops | F/E/B | 店铺授权：货源店 / 销售店卡片 + OAuth + 类目映射 | 菜单「采购/店铺授权」；多页空态引导 | 无 | shops + platformMeta / category-mappings | `/shops`、`/shops/platforms`、`/shops/category-mappings`、`/{id}/authorize_url`、`/exchange_code`、`/refresh`、`/sync_orders` |
| 14 | Suppliers | /suppliers | B/C/F | 4 tab：供应商 / 机会历史 / 采购单 / 应付账龄 | 菜单「采购/供应商」 | 无 | suppliers / forecast / opportunities / purchases / aging | `/suppliers`(+/{id},/{id}/score,/forecast)、`/factory-network/*`、`/purchases`(+/{id},/from_forecast)、`/settlements/summary` |
| 15 | FactoryPortal | /factory-portal | G（工厂） | 本厂 SKU 维护（仅供给目录） | 独立域菜单；工厂账号默认落地 | 无 | portal/me、portal/products | `/factory-network/portal/me`、`/portal/products` |
| 16 | Pricing | /pricing | E | 真实利润计算 + AI 动态定价 + 全店重定价 | 菜单「采购/动态定价」 | 无 | pricing records / calc | `/pricing`、`/pricing/calc`、`/pricing/suggest`、`/workflows/run` |
| 17 | Ads | /ads | E | 广告活动 + 预算 ROI + 审批队列 + AI 选词 | 菜单「运营/广告增长」 | 无 | campaigns / summary / actions / suggest | `/ads/campaigns`、`/ads/suggest`、`/campaigns/{id}/optimize`、`/actions`(+/{id}/approve\|reject\|execute) |
| 18 | Orders | /orders | E/F | 订单列表 + 状态 + 发货 + 真店同步 + CSV | 菜单「运营/订单管理」 | 无（发货后就地） | orders / syncShops | `/orders`、`/orders/import`、`/orders/export`、`/{id}/status`、`/{id}/ship`、`/shops/{id}/sync_orders` |
| 19 | Refunds | /refunds | E/F | 售后退款全状态机 | 菜单「运营/售后管理」 | 无 | refunds stats / list | `/refunds`、`/{id}/status`、`/{id}/return_receive`、`/{id}/refund` |
| 20 | Settlements | /settlements | F/E | 供应商应付账龄 + 对账单生成/确认/付款 | 菜单「运营/账期结算」 | 无 | summary / settlements | `/settlements`、`/settlements/summary`、`/settlements/generate`、`/settlements/{id}` |
| 21 | Support | /support | E/F | 智能客服：会话 + 人工/AI 回复 | 菜单「运营/智能客服」 | 无 | conversations / messages | `/support/conversations`(+/{id},/{id}/reply,/auto_reply,/close) |
| 22 | Workflows | /workflows | E/F | 工作流模板运行 + 调度 + 运行历史 + 恢复 | 菜单「系统/AI 工作流」；Dashboard 按钮 | 无 | templates / runs / schedules | `/workflows/templates`、`/workflows/run`、`/runs`(+/{id},/{id}/resume)、`/schedules`(+/{id},/{id}/run) |
| 23 | Knowledge | /knowledge | E/F | 知识库文档 + 候选(AI 学习) | 菜单「系统/知识库」 | 无 | docs / candidates / learning | `/knowledge/docs`(+/{id})、`/search`、`/candidates`(+/{id}/answer\|approve\|reject\|revoke)、`/learning/settings` |
| 24 | BI | /bi | F/E | 统一经营口径指标 + 趋势 + 数据质量 + AI 报告 | 菜单「概览/BI 经营分析」（合规白名单） | 无 | metrics / data-quality / profit / report | `/bi/metrics`、`/bi/data-quality`、`/bi/profit`、`/bi/report`（+`/bi/dashboard`） |
| 25 | Finance | /finance | F | 财务事实：汇率 / 订单行费用 / 平台结算对账 | 菜单「运营/财务工作台」 | 无 | fx / order detail / platform-settlements | `/finance/fx`、`/orders/{id}/detail`、`/orders/{id}/lines`、`/orders/{id}/fees`、`/finance/platform-settlements`、`/finance/settlement-reconciliation` |
| 26 | Alerts | /alerts | F/E | 风险巡检告警 + 规则配置 | 菜单「概览/风险巡检」 | 无（无处置跳转） | alerts / counts / rules | `/alerts`、`/alerts/scan`、`/{id}/ack`、`/alerts/rules`(+/{id}) |
| 27 | AiDecisions | /ai-decisions | F/E | AI 决策依据链只读审计 | 菜单「系统/AI 决策依据」 | 无 | /ai/decisions | `GET /ai/decisions` |
| 28 | Users | /users | OWNER/F | 用户与角色 CRUD | 菜单「系统/用户与角色」（仅 OWNER） | 无 | /auth/users | `/auth/users`(+/{id}) |
| 29 | Settings | /settings | OWNER/F | AI 设置 + 经营参数 + 费率 + 1688 Key + AI 日志 | 菜单「系统/AI 设置」（非 OWNER 隐藏） | 无 | /ai/settings / logs | `/ai/settings`(GET/PUT)、`/ai/logs` |
| 30 | PlatformAdmin | /platform-admin | PLATFORM_ADMIN | 平台控制台 4 tab（总览 / 租户 / 日志 / 维护） | 独立域菜单；超管默认落地 | 进入租户→`/dashboard` | admin overview / tenants / logs / rules | `/admin/overview`、`/admin/tenants`(+/{id},/{id}/enter)、`/access_logs`、`/ai_logs`、`/shops/platform_rules`(+/{p}/check_updates)、`/shops/purge_demo_data` |

---

## 表二 · 能力 · 问题 · 处置（30/30）

> 「归类处置」取值：**保留** / **合并** / **重新归类**（后者附目标一级域）。
> 「是否隐藏高级入口」= 是否建议不进一级菜单、仅二级/高级入口。
> 「优先级」= 本轮优化的处理优先级（P0/P1/P2）。

| # | 页面 | 可写操作 | 权限 key | AI 接入位置 | 现存问题 | 与他页重复点 | 归类处置 | 优化点 | 隐藏高级入口 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Login | 登录 | 无 | 无 | 写死演示账号提示（`Login.vue` 的演示账号 `el-alert`）；登录后无条件 `push('/dashboard')`（`Login.vue` 的 `doLogin`）绕过 `defaultLanding` 角色分流；无注册 / 无首用引导 | 无 | 保留（框架/原子） | 按 `defaultLanding` 跳转；弱化演示账号；加首用引导入口 | 否 | P1 |
| 2 | Layout | 退出登录 / 退出代客 | 无（菜单按 `roleKey` 过滤） | 挂载 AiAssistant | 现菜单 5 组 vs 冻结 11 域；「采购」组混入店铺授权/动态定价；无全局搜索/面包屑/收藏 | 无 | 重新归类（11 域重构分组） | 按 11 域改分组 + 加搜索/面包屑 | 否 | **P0** |
| 3 | RunStatus | — | 无 | 无 | 状态字典与 `launchCenter.js` 双事实源（小写 vs 大写） | `composables/launchCenter.js` 状态表 | **合并**（统一一套状态字典） | 移入 `components/` 作 StatusTag | — | P1 |
| 4 | AiAssistant | 发消息 | 无（无鉴权按钮） | 本体（调度全部 Agent） | actions 仅渲染为不可点击 `el-tag`（`AiAssistant.vue` 的 `m.actions` 块）；无历史会话；无「下一步」 | 与 BI 报告 / AiDecisions 建议重叠 | 保留（框架/原子） | action 可跳转；会话历史 | 否 | P1 |
| 5 | Dashboard | 无（仅跳转按钮） | 无 | 仅工作流运行列表 | **不回答 6 问**（见审计 ④）；全角色共用一套指标 | BI 指标重叠 | 保留（一级域「首页」，改造为经营工作台） | 重做「今日经营」：待我处理/进展/异常/下一步 | 否 | **P0** |
| 6 | Discovery | 扫描趋势/导入/扩展/选品/评分 | product:write | 趋势扫描 / 扩展 / 选品 / 评分 | 选品「已选出 X 个」无下一步跳转（`Discovery.vue` 的选品结果 `el-alert`）；评分表无商品标题；趋势靠 CSV 手导 | Products 评分、BI 品类 | 保留（一级域「市场机会」） | 选品→商品池/上线中心深链 | 否 | P1 |
| 7 | Products | 新增/采集/URL/HTML/标准化/代发/导出 | product:write, purchase:write | 机会分（只读） | 详情抽屉缺 Launch 深链/销售渠道/上线进度/AI 建议（`LAUNCH_CENTER_PRODUCT_DESIGN §5` 要求）；代发入口仅商品行内、`product_id` 隐式取自当前行（`Products.vue` 一件代发弹窗 `openDropship`） | Discovery 评分、Suppliers 报价、Listings 列表 | 保留（一级域「商品经营」） | 补「上线进度/销售渠道」tab + 深链 | 否 | P1 |
| 8 | Listings | 生成/优化/编辑/复核/审批/发布/回执 | listing:write, compliance:approve | AI 生成 / 优化 | 发布走审批队列异步，与 LaunchCenter 双入口；列表状态仅 draft/published，无平台三态；发布弹窗单选一店 | LaunchCenter 发布、ComplianceWorkbench 审批 | 保留（一级域「商品经营」） | 与 Launch 划清（Listing=内容编辑，Launch=执行） | 否 | **P0** |
| 9 | Compliance | 开始检测 | compliance:check | 合规 Agent（后台） | 检测对象用数字 ID 输入（`Compliance.vue` 的 `ref_id` `el-input-number`）；与工作台重复 | ComplianceWorkbench | **合并**（→ 工作台收编；本页下沉为二级「合规检测」） | 并入工作台 | 是（合规员保留二级） | P2 |
| 10 | ComplianceWorkbench | 放行/驳回/发起检测 | compliance:approve, compliance:check | 复核结论展示 | 与 Compliance.vue 重复；审批无「返回原任务」且缺商品/目标市场/证据上下文 | Compliance.vue | 保留（一级域「商品经营」下二级） | 补审批上下文 + 回链（return_to） | 否（角色专属） | P1 |
| 11 | LaunchCenter | 无（读为主） | launch:read | 下一动作 / AI 建议列 | **无「创建上线流程」入口**（后端 `POST /launch` 已存在，前端未封装）；责任人筛选是数字 owner_user_id | Listings 发布、Workflows | 保留（一级域「商品经营」） | 补「创建上线流程」向导 | 否 | **P0** |
| 12 | LaunchDetail | 执行动作 / 同步刷新 | launch:manage | AI Action 投影 / NBA | 深链 `return_to` 白名单仅 `/launch*`，`professional_links` 指向 `/listings` ⇒ 回不到原步骤；领域动作 B03–B09 未接通 | 无 | 保留（一级域「商品经营」） | 放开白名单到 `/listings,/products,/shops`；B03–B09 显式未接入+原因 | 否 | P1 |
| 13 | Shops | 店铺 CRUD / 授权 / 同步 / 类目映射 | workspace:write | 无 | 归「采购」域语义错（实为销售渠道）；517 行混两类店铺 + 类目映射 + 平台元数据；`syncOrders` 也出现在货源店卡片（`Shops.vue` 的 `syncOrders` 按钮） | 类目映射与 Products 标准化 / Settings 重叠 | **重新归类**（→「销售渠道」） | 销售渠道主入口；类目映射折叠为高级 | 类目映射可高级 | **P0** |
| 14 | Suppliers | 新增/评分/尽调/门户账号/匹配/转报价/采购单 | supply:write, purchase:write | 供应商评分 / 销量预测 | 「应付账龄」tab 与 Settlements 完全重复（同调 `/settlements/summary`）；匹配机会需数字 product_id | Settlements（账龄）、Products 报价 | **重新归类**（→「货源中心」） | 账龄 tab 移出；匹配用对象选择器 | 账龄高级 | P1 |
| 15 | FactoryPortal | 新增/更新工厂产品 | supply:write | 无 | **只有产品目录**，无协作任务收件箱（旅程 G 断点）；`LAUNCH_CENTER_PRODUCT_DESIGN §6` 的「本厂指派步骤投影」未实现 | 与 Suppliers 工厂数据同源 | 保留（独立域） | 补「协作任务收件箱」 | 否（角色专属） | **P0** |
| 16 | Pricing | 算利润 / AI 定价 / 全店重定价 | finance:write | 定价 Agent | 全店重定价调 `/workflows/run`（`Pricing.vue` 的 `repriceAll`）绕过 Launch/审批，与「Pricing 只分析」冲突；数字 pid 输入；归「采购」错 | Products 定价 tab、Ads 动作 | **重新归类**（→「经营优化」） | 纳入审批；补商品选择器 | 否 | P1 |
| 17 | Ads | 选词建组 / 预算优化 / 批准 / 拒绝 / 执行 | ai:write, finance:write | 广告 Agent | 审批队列走通用 `/actions`，与 PublishActions / Launch actions 三套割裂；数字商品 ID | Workflows、Dashboard run | **重新归类**（→「经营优化」） | 审批收口到统一「待我审批」 | 否 | P2 |
| 18 | Orders | 同步 / 改状态 / 发货 / 导入 / 导出 | order:write | 无 | 无货源匹配/采购/物流追踪/完成（旅程 E 断点）；状态列内联 `el-select` 直接改状态（`Orders.vue` 状态列）易误操作；商品 ID 无标题 | Finance 订单费用、Refunds | 保留（一级域「订单履约」） | 补履约链；状态改确认式 | 否 | P1 |
| 19 | Refunds | 发起/同意/拒绝/退货入库/执行 | refund:write | 无 | 发起退款用订单 ID 数字输入（`Refunds.vue` 的 `form.order_id` `el-input-number`）；无退货物流 | Orders 联动 | **重新归类**（→「客户售后」） | 订单选择器 | 否 | P2 |
| 20 | Settlements | 生成 / 确认 / 标记付款 | settlement:write | 无 | 与 Suppliers 账龄 tab 重复；与 Finance「平台结算对账」是两套账（供应商应付 vs 平台应收）易混 | Suppliers（账龄）、Finance | 保留（一级域「订单履约」）；收编 Suppliers 账龄 | 明确应付/应收分工 | 否 | P2 |
| 21 | Support | 新建 / 回复 / AI 回复 / 关闭 | order:write | 客服 Agent | 新建会话手填平台 + 买家名（无真实来源）；知识候选未联动（在 Knowledge）；借用 order:write 无专属 key | 无 | **重新归类**（→「客户售后」） | 关联订单 / 知识候选；专属权限 key（待确认） | 否 | P2 |
| 22 | Workflows | 运行 / 恢复 / 调度 / 立即执行 | ai:write | 总调度 + Agent 流水线 | 「自动铺货」工作流与 LaunchCenter 是两条并行上线路径（LEGACY_AUTOMATION vs PLATFORM_LAUNCH，见 `PLATFORM_WORKFLOW_PROGRESS §9`）；无上线中心互链 | LaunchCenter、Pricing、Alerts 调度 | **重新归类**（→「AI 运营」，降高级） | 与上线中心互链 + 标注区别 | **是** | P1 |
| 23 | Knowledge | 检索/增删改/补答案/采纳/拒绝/撤销/学习开关 | ai:write | RAG 检索 + 知识自进化 | 归「系统」语义偏；候选与 Support 未联动 | 无 | **重新归类**（→「AI 运营」） | 与客服候选联动 | 否 | P2 |
| 24 | BI | 周期切换 / 生成 AI 报告 | ai:write | AI 经营报告 | 与 Dashboard 指标重叠；A 类用户难懂；缺「指标→问题」下钻 | Dashboard | **重新归类**（→「数据分析」） | Dashboard 简 / BI 详分工 | 否 | P2 |
| 25 | Finance | 汇率 / 订单行 / 费用 / 结算单 | finance:write, workspace:member:admin(fx) | 无 | 订单手输订单 ID；3 tab 写法极密；与 Settlements 易混 | Settlements、BI 口径 | **重新归类**（→「数据分析」） | 拆 tab / 订单选择器 | 可高级 | P2 |
| 26 | Alerts | 立即巡检 / 确认 / 规则启停 | ai:write | 主动巡检九项 | 只告警不执行但缺处置跳转（旅程 H 断点）；阈值只读不可编辑 | Dashboard（无风险区，互补） | **重新归类**（→「经营优化」） | 告警→采购/定价/客服深链 | 否 | P1 |
| 27 | AiDecisions | 筛选查询（只读） | ai:read | AI 决策审计 | 归「系统」；与 Settings / PlatformAdmin 三处 AI 日志分散 | Settings、PlatformAdmin | **重新归类**（→「AI 运营」） | 统一 AI 日志视图 | 是 | P2 |
| 28 | Users | 用户 CRUD | workspace:member:admin | 无 | 角色下拉 value 仍是 legacy 小写（`admin/operator/viewer/compliance_approver`，`Users.vue` 的 `roleMap`/`roleOptions`，仅显示层映射为大写标签）与 Context 权威大写枚举双轨；无数据范围(Store Scope)配置 | 无 | **重新归类**（→「设置与管理」） | 枚举对齐 + 范围配置 | 是 | P1 |
| 29 | Settings | 保存设置 | workspace:member:admin | LLM 配置 | 名为「AI 设置」却含经营参数/费率/1688 Key（范围溢出）；与 PlatformAdmin 规则更新、Finance 汇率双入口 | Finance(fx)、PlatformAdmin(规则) | **重新归类**（→「设置与管理」） | 拆「AI 模型」/「经营参数」 | 是 | P2 |
| 30 | PlatformAdmin | 开通/续期/停用/进入/清空演示/检查规则 | platform:admin | 平台级 AI 日志 | 与租户菜单完全隔离（设计如此）；「清空演示数据」入口在超管（README 称「一键清空」但租户管理员无入口） | AiDecisions/Settings AI 日志 | 保留（独立域） | AI 日志去重 | 否 | P2 |

---

## 附 · 冻结口径映射速查（本矩阵与 v1.0 一致性自检）

| 冻结项 | 矩阵落点 |
|---|---|
| 11 域归属 | 表二「归类处置」列「重新归类（→域）」，与冻结清单逐页一致 |
| 独立域 | #15 FactoryPortal、#30 PlatformAdmin → 「保留（独立域）」 |
| 框架/原子 | #1 Login、#2 Layout、#3 RunStatus、#4 AiAssistant |
| Compliance → 工作台收编 | #9「合并」，#10「保留（二级）」 |
| Suppliers 账龄 → Settlements | #14「账龄 tab 移出」，#20「收编」 |
| AI 日志三处 → 一处 | #21/#24/#27/#29/#30 相关问题列 + G21 |
| 审批三套 → 统一「待我审批」 | #8/#17/#12 问题列 + G8 |
| 状态字典一套 | #3「合并」 + G12 |
| 双模式同源 | #12（同 DTO/状态/权限，仅密度不同） |
| 首页 6 问 | #5 |
| B03–B09 未接入显式 | #12（`disabled_reason`，「未接入」，非 409-only；CONFIRM_ACTIVATION ∈ WAITING_EXTERNAL 不得称「已上线」） |
| 页面 10 态 | `FRONTEND_UX_AUDIT.md` G25/G26 |
