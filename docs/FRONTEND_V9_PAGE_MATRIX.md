# FRONTEND V9 · 全站页面矩阵（UX-A 产品冻结）

> 系列归属：`FRONTEND_V9_*`（新系列，区别于 V1.0 的 `FRONTEND_*.md` 七份）。
> 依据：实读 `frontend/src/router.js`、`frontend/src/views/`（30 个 .vue）、`frontend/src/components/`（22 个）、`frontend/src/composables/navigation.js`、`frontend/src/permissions.js`；数据来源仅引用 `backend/app/routers/` 实际存在的模块，未确认处标「待确认」。
> 口径：路由注册页 27 条（1 登录 + 1 框架父级 + 25 业务含 1 条参数详情），非路由视图 2 个（AiAssistant / RunStatus），隐藏入口 5 类。旧文档（FRONTEND_PAGE_MATRIX.md）与代码不符处已在文末注明。
> V9 空间划分：**Console**（平台服务商管理后台）/ **Workspace**（跨境经营空间，产品核心）/ **Factory**（工厂协作门户）。

## 表一 · 路由注册页（27/27）

| # | 页面 | 路由 | 空间 | 功能 | 角色 | 数据来源(后端路由) | 关键操作 | 现存问题 | V9 重设计 | 新页面位置 | 验收用例要点 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 登录 | /login | 全空间入口 | 账号登录+角色分流 | 未登录全体 | auth, me | 登录、跳默认落地页 | 写死演示账号提示；登录后硬编码跳 /dashboard 绕过 defaultLanding；无注册/首用引导 | 登录后按 defaultLanding 分流（超管→Console、工厂→Factory、合规→审批台、其余→工作台）；弱化演示提示；新用户首次进入走 onboarding 向导 | Console:/console/login（全空间共用） | ①各角色登录落在各自默认页 ②登录失败提示可读 ③首次登录出现引导入口 |
| 2 | 应用框架 Layout | （父级，非独立页） | Workspace | 侧栏菜单+顶栏+权限态+挂载 AI 助手 | 全体已登录 | me | 切换工作区、退出、退出代客 | 无全局搜索/收藏；只读态横幅弱；工厂/超管直接被重定向到独立页而非独立空间外壳 | V9 以「空间外壳」重构：Console/Workspace/Factory 三套外壳共享设计系统；面包屑+全局搜索+通知中心进顶栏；只读/代客/工作区状态常显 | 全部空间的外壳层 | ①菜单按 Context 权限过滤正确 ②刷新后 Context 恢复不丢权限 ③代客横幅常显可退出 |
| 3 | 经营工作台 Dashboard | /dashboard | Workspace | 6 问经营概览+跨域待办+下一步 | OWNER/OPERATOR/READ_ONLY(+合规白名单) | workbench(todo/overview), bi, launch, alerts, listings, workflows, me | 查看待办、深链跳转、CTA | 已接 UX-04 只读 BFF；但待办来源标签可读性弱、部分深链仍跳列表页而非定位到条目 | V9 定位为「今日经营」：待办卡片按来源域分组、每条可直达明细；新增信号区块用 workbench/overview 的 signals/partial/sources 透出数据完整度 | Workspace:/app | ①待办点击直达对应明细页 ②partial 数据出现完整性提示 ③六类角色/画像首屏差异正确 |
| 4 | 商品发现 | /discovery | Workspace | 趋势扫描+关键词扩展+AI 选品+机会评分 | OWNER/OPERATOR | discovery | 扫描、导入趋势 CSV、选品、评分 | 选品结果不落地商品池（断链）；评分口径不透出 | V9 打通闭环：AI 选品一键「转入商品池」；评分卡展示因子；导入 CSV 向导化 | Workspace:/app/market/discovery | ①选品→商品池落库成功 ②无数据空态有引导 ③CSV 导入有格式校验提示 |
| 5 | 商品池 | /products | Workspace | 商品 CRUD+采集+标准化+详情多 tab+1688 代发 | OWNER/OPERATOR/READ_ONLY | products, product_assets(待确认), product_channels(待确认), purchases, pricing | 新增/编辑、URL 抓取采集、标准化、一件代发下单、详情查看 | 4 个弹窗挤在单页（新增/模拟采集/真实抓取/代发下单）认知重；「模拟平台采集」是演示能力混在真实入口旁；详情抽屉 tab 无锚点 | V9 拆「列表 + 详情页(路由化)」；采集统一一个入口按来源分步；模拟采集移入演示开关，与真实抓取明确区隔；代发下单走标准下单向导 | Workspace:/app/products, /app/products/:id | ①URL 抓取成功后进详情 ②详情路由可直达可分享 ③无 1688 Key 时代发按钮呈未配置态 |
| 6 | Listing 工作台 | /listings | Workspace | 生成/优化/编辑/合规复核/发布/回执 | OWNER/OPERATOR(+合规白名单) | listings, shops, compliance | AI 生成、优化、审核、发布、查看回执 | 6 个弹窗串行（生成/复核/回执/预览/选店铺）流程割裂；发布前后状态跳转不连贯 | V9 重构为「生成 → 编辑预览 → 合规 → 发布 → 回执」单页分步流（复用 LaunchStepPanel 模式），回执用 PublicationReceipts 组件常驻 | Workspace:/app/listings, /app/listings/:id | ①全流程可在单页完成无断点 ②复核驳回回到编辑步 ③发布失败展示可重试回执 |
| 7 | 合规检测 | /compliance | Workspace | 发起检测+报告列表 | OWNER/OPERATOR/COMPLIANCE | compliance | 发起检测、查看报告详情抽屉 | 与合规工作台职责重叠，入口关系不清 | V9 定位为「合规报告中心」：发起检测收敛为入口之一，报告列表+详情为主；审批流归合规工作台 | Workspace:/app/compliance | ①发起检测有进行中反馈 ②报告详情抽屉含评分与问题清单 ③合规员进入本页不越权 |
| 8 | 合规工作台 | /compliance-workbench | Workspace | 审批队列+高风险+规则状态 | COMPLIANCE 专属 | listings, compliance, shops | 审批/驳回 Listing、发起检测 | 审批后就地无「返回原任务」上下文；仅 OWNER 可见设置项混排 | V9 作合规员唯一默认落地页：审批队列左右分栏（队列+详情）、审批后自动聚焦下一条；高风险卡片带一键处理 | Workspace:/app/compliance/approvals | ①合规员登录默认落此页 ②审批后队列自动刷新并聚焦下一条 ③非合规员不可见 |
| 9 | 上线中心 | /launch | Workspace | 上线流程列表+创建（11 列/筛选/分页） | OWNER/OPERATOR | launch, products, shops | 创建流程、筛选、进详情 | 创建弹窗仅 3 字段过于简化，与 11 步流程预期不匹配；筛选条件多但无保存视图 | V9 创建向导化（选商品→选店铺→确认）；列表筛选支持保存常用视图；行内进度条替代纯状态文案 | Workspace:/app/launch | ①向导创建成功进入详情 ②筛选视图可保存复用 ③分页/筛选状态在 URL 可回溯 |
| 10 | 上线流程详情 | /launch/:id | Workspace | 双模式详情+时间线+步骤+动作 | OWNER/OPERATOR | launch, listings | 执行步骤动作、同步、返回列表 | professional_links 仅指向 /listings；GUIDED 模式下一步引导弱；无权限时仅空白 | V9 按 GUIDED/PROFESSIONAL 双形态强化：GUIDED 侧边步骤导航+每步 AI 建议；动作失败给原因与重试；无权限呈 NoPermissionState | Workspace:/app/launch/:id | ①每步动作成功/失败有明确反馈 ②失败可重试 ③无权限用户看到降级态非空白 |
| 11 | 店铺授权 | /shops | Workspace | 货源店/销售店授权卡片+OAuth+类目映射 | OWNER/OPERATOR | shops | 授权、换码、刷新、同步订单、类目映射 | OAuth 回调流程提示分散；授权失败原因不透出；517 行单页过重 | V9 拆「店铺列表 + 授权向导 + 类目映射设置」；授权状态徽标统一；失败原因直接展示 | Workspace:/app/channels/shops | ①OAuth 授权成功列表刷新 ②token 过期态可见并可刷新 ③未授权店铺的同步按钮为禁用态 |
| 12 | 供应商 | /suppliers | Workspace | 4 tab：供应商/机会历史/采购单/应付账龄 | OWNER/OPERATOR | suppliers, purchases, factory_network, settlements | 新增供应商、评分、采购单创建、按预测生成采购、账龄查看 | 4 tab 信息密度差异大；工厂网络入口弱；机会历史与 Discovery 语义重叠 | V9 拆为「供应商库 + 采购单列表页」两个路由页；账龄并入财务域入口；工厂网络作独立分组入口 | Workspace:/app/supply/suppliers, /app/supply/purchases | ①采购单从预测一键生成成功 ②tab 拆分后各自深链可达 ③账龄数据与结算页口径一致 |
| 13 | 工厂供给门户 | /factory-portal | Factory | 本厂产品/产能维护（仅供给目录） | FACTORY_COLLABORATOR 专属 | factory_network(portal) | 新增/更新本厂产品与产能 | 单页薄（101 行）仅 CRUD，无订单/结算/消息等协作视图；工厂账号被 routeRedirect 锁定于此 | V9 扩为完整 Factory Portal：产品产能 + 平台询价/订单（待接入 factory_network 其余端点）+ 结算查看（待接入）；仅见本厂数据 | Factory:/factory/products | ①工厂账号登录仅见本厂数据 ②无权访问任何 /app 页 ③新增产品立即出现在平台侧供给目录 |
| 14 | 动态定价 | /pricing | Workspace | 利润计算+AI 建议价+全店重定价 | OWNER/OPERATOR | pricing, cross_border(待确认), workflows | 计算利润、采纳建议价、触发重定价工作流 | 与商品池/财务的利润口径展示分散；建议价采纳无批量操作 | V9 增加批量采纳/忽略；利润计算卡与 BI/财务口径互链（同一 costing 实现）；重定价触发有运行回执 | Workspace:/app/pricing | ①计算结果与财务页口径一致 ②批量采纳有生效反馈 ③无成本数据商品给出补录引导 |
| 15 | 广告增长 | /ads | Workspace | 广告活动+预算 ROI+审批队列+AI 选词 | OWNER/OPERATOR | ads, actions | 创建活动、优化、审批/执行 AI 动作 | AI 动作审批后的执行结果不回推到列表；与统一告警中心无联动 | V9 审批动作执行后有状态回执并入队列；AI 选词结果可一键应用到活动 | Workspace:/app/ads | ①审批-执行-结果三态在列表可见 ②无店铺授权时呈 NotConfiguredState ③ROI 汇总与活动明细一致 |
| 16 | 订单管理 | /orders | Workspace | 订单列表+状态流转+发货+真店同步+CSV | OWNER/OPERATOR | orders, shops | 导入 CSV、改状态、发货、同步 | 发货后就地更新无下文（缺物流轨迹接入提示）；CSV 导入错误行不透出 | V9 导入给逐行校验报告；发货后展示履约链（待接入物流能力，标注「待接入」）；状态机图示化 | Workspace:/app/orders | ①CSV 错误行列出原因 ②发货后状态即时更新 ③同步中店铺有进行中指示 |
| 17 | 售后管理 | /refunds | Workspace | 退款全状态机 | OWNER/OPERATOR | refunds | 发起退款、改状态、退货收货、确认退款 | 状态机无图示；发起退款与订单页无互链 | V9 状态机可视化时间线；订单详情页可直接发起售后跳入 | Workspace:/app/refunds | ①全状态流转可达 ②从订单发起售后预填订单号 ③非法状态跳转被阻止 |
| 18 | 账期结算 | /settlements | Workspace | 供应商应付账龄+对账单生成/确认/付款 | OWNER/OPERATOR | settlements, suppliers | 生成对账单、确认、登记付款 | 与供应商页账龄 tab、财务页结算数据三处展示口径需统一 | V9 与供应商账龄合并口径后仅此页维护；确认/付款按钮按状态机显隐 | Workspace:/app/settlements | ①生成-确认-付款全流程可走通 ②金额汇总与明细一致 ③已付款对账单不可再编辑 |
| 19 | 智能客服 | /support | Workspace | 会话列表+人工/AI 回复 | OWNER/OPERATOR | support, ai | 查看会话、人工回复、AI 自动回复、关闭 | AI 回复与知识库改写入口分离；会话无标签/优先级 | V9 会话按状态分组+AI 建议回复一键采纳（采纳前可改）；与知识库候选互跳 | Workspace:/app/support | ①AI 建议可编辑后发送 ②关闭会话不可再回复 ③未配置店铺时呈未配置态 |
| 20 | AI 工作流 | /workflows | Workspace | 模板运行+调度+运行历史+恢复 | OWNER/OPERATOR | workflows, schedules, actions | 运行、调度增删、查看运行、恢复失败运行 | 模板参数表单无说明；运行失败恢复入口深 | V9 运行向导带参数说明；失败运行卡片置顶并给恢复动作；调度列表含下次执行时间 | Workspace:/app/ai/workflows | ①带参运行成功 ②失败运行可一键恢复 ③调度触发可验证 |
| 21 | 知识库 | /knowledge | Workspace | 文档管理+AI 候选学习 | OWNER/OPERATOR | knowledge, ai | 增删改文档、搜索、候选回答补写/审批 | 候选审批与客服页分离但语义关联；学习设置藏得深 | V9 候选流并入审批中心式布局；文档搜索置顶；学习设置入 AI 设置域 | Workspace:/app/ai/knowledge | ①候选审批后知识生效可被客服引用 ②删除有确认 ③搜索命中高亮 |
| 22 | BI 经营分析 | /bi | Workspace | 统一指标+趋势+数据质量+AI 报告 | OWNER/OPERATOR/READ_ONLY/COMPLIANCE | bi | 查指标、看趋势、生成 AI 报告 | 指标口径文档缺失；报告生成时长无预期提示 | V9 每指标卡可展开口径说明；报告生成异步化给进度；与 Dashboard 6 问互链 | Workspace:/app/analytics/bi | ①指标口径说明可查 ②报告生成有进度反馈 ③只读用户可完整查看 |
| 23 | 财务工作台 | /finance | Workspace | 汇率+订单行费用+平台结算对账 | OWNER/OPERATOR | finance, cross_border, orders | 录入订单行/费用/结算单、查汇率 | 46 行薄壳依赖 3 个弹窗录入，纯表单堆砌；跨境到岸成本配置（cross_border 路由）前端未接 | V9 录入改行内编辑表格；新增「到岸成本配置」页接入 cross_border（关税/物流路由/平台费率，此前未接标注为新增） | Workspace:/app/analytics/finance, /app/analytics/landed-cost | ①行内编辑保存成功 ②到岸成本配置 CRUD 可用且计算口径与定价一致 ③平台内置口径行只读 |
| 24 | 风险巡检 | /alerts | Workspace | 告警列表+规则配置+扫描 | OWNER/OPERATOR | alerts | 扫描、确认告警、增删规则 | 告警无处置跳转（断链）；规则与 AI 动作审批（actions）无联动 | V9 每条告警给「去处理」深链到对应域；规则配置独立设置区；与 AI 决策依据互链 | Workspace:/app/risk/alerts | ①告警确认后计数更新 ②「去处理」落到正确页面 ③规则增删生效 |
| 25 | AI 决策依据 | /ai-decisions | Workspace | AI 决策链只读审计 | OWNER/OPERATOR | ai | 查看决策详情抽屉 | 只有列表+抽屉，无按对象（商品/订单）过滤；与各 AI 功能页无回链 | V9 支持按决策类型/对象过滤；各 AI 页（定价/广告/客服）决策旁给「查看依据」深链 | Workspace:/app/ai/decisions | ①过滤生效 ②从定价建议可跳到对应决策依据 ③只读不可操作 |
| 26 | 用户与角色 | /users | Workspace | 成员与角色管理 | OWNER 专属 | auth | 新增/编辑成员、分配角色 | 与工作区成员管理概念有重叠（workspace:member:admin）；角色说明缺失 | V9 按角色枚举（OWNER/OPERATOR/READ_ONLY/COMPLIANCE）给权限说明卡；与工作区切换器语义对齐 | Workspace:/app/settings/team | ①仅 OWNER 可见 ②角色修改即时反映菜单可见性 ③不能降级最后一个 OWNER（待确认后端约束） |
| 27 | AI 设置 | /settings | Workspace | AI 参数/经营参数/费率/1688 Key/AI 日志 | OWNER 专属 | ai, me | 读写 AI 设置、查看日志 | 单页混排 5 类配置无分组；Key 状态不显式 | V9 分组为「AI 模型 / 经营参数 / 集成密钥 / 日志」四个设置子页；Key 呈已配置/未配置徽标 | Workspace:/app/settings/ai | ①仅 OWNER 可见可写 ②未配置 Key 的功能页出现 NotConfiguredState ③设置保存有回执 |
| 28 | 平台控制台 | /platform-admin（含 ?tab=audit 隐藏子态） | Console | 总览/租户/审计/维护 4 tab | PLATFORM_ADMIN 专属 | admin, shops, ai | 开通租户、进入租户(代客)、查日志、平台规则检查、清演示数据 | 572 行 4 tab 巨页；?tab=audit 是唯一带 query 的菜单入口，语义隐晦；开通租户凭据弹窗关闭后不可再取 | V9 拆 Console 独立空间 4 页：/console/overview、/console/tenants、/console/audit、/console/maintenance；代客入口显式确认；凭据仅展示一次并提示复制 | Console:/console/* | ①超管登录落地 /console/overview ②进入租户后代客横幅常显可退出 ③非超管访问任一 /console 页被重定向 |
| 29 | AI 助手（全局） | 无路由（全局悬浮 FAB+抽屉） | Workspace | 自然语言助手 | 租户全员（工厂隐藏） | ai | 对话、建议问题 | 回复中 actions 标签不可点击；无会话持久化 | V9 升级为「AI 副驾驶」：actions 可执行（带确认）；支持上下文感知（当前页面）；会话历史持久化（待接入） | Workspace 全局外壳组件 | ①建议动作点击可执行 ②工厂账号不显示 ③对话上下文随页面变化 |
| 30 | 状态标签 RunStatus | 无路由（组件薄封装） | 全空间 | status→文案/颜色原子 | — | 无 | 无 | 已是 StatusTag 薄封装（V1.0 建议已落地），文件留在 views/ 不合理 | V9 并入设计系统原子库，从 views/ 移除该文件 | 设计系统组件库 | ①全部状态枚举覆盖且视觉统一 |

## 表二 · 关键弹窗/抽屉/隐藏界面（非路由界面清单）

| 宿主页 | 界面 | 类型 | V9 处置 |
|---|---|---|---|
| Listings | AI 生成 / 上架合规复核 / 发布回执 / Listing 预览编辑 / 选择上架店铺 | 5 弹窗 | 并入单页分步流（表一 #6），回执常驻面板 |
| Products | 新增商品 / 模拟平台采集 / 真实抓取采集 / 1688 一件代发下单 / 商品详情抽屉 | 4 弹窗+1 抽屉 | 详情路由化；采集双入口合并并区隔演示能力；代发走向导向导 |
| Discovery | 导入趋势数据(CSV) | 弹窗 | 向导化带格式校验 |
| Finance | 新增订单行 / 新增订单费用 / 录入平台结算单 | 3 弹窗 | 改行内编辑（表一 #23） |
| Knowledge | 新增/编辑文档 / 补写标准答案 | 2 弹窗 | 保留，纳入审批中心布局 |
| Orders | 导入订单 CSV | 弹窗 | 向导化+逐行校验报告 |
| Refunds | 发起退款 | 弹窗 | 保留，支持从订单预填 |
| Settlements | 按供应商生成对账单 | 弹窗 | 保留，前置选择器加强 |
| Ads | AI 选词建议 | 弹窗 | 结果一键应用 |
| LaunchCenter | 创建上线流程 | 弹窗 | 向导化（表一 #9） |
| PlatformAdmin | 开通租户 / 初始管理员账号凭据 | 2 弹窗 | 凭据一次性展示+复制提示 |
| FactoryPortal | 新增/更新工厂产品 | 弹窗 | 保留，表单分组 |
| Compliance / AiDecisions / AiAssistant | 报告详情 / 决策详情 / 助手抽屉 | 3 抽屉 | 保留统一抽屉规格（480-560px 档位） |
| 全局（隐藏入口） | 代客进入租户（erp_impersonating 横幅+退出） | 状态 | 代客确认+常显横幅+一键退出 |
| 全局（隐藏入口） | 合规员路径白名单（dashboard/bi/listings/compliance/launch 前缀） | 路由策略 | 保留白名单语义，菜单同源过滤 |
| 全局（隐藏入口） | /platform-admin?tab=audit | query 子态 | 独立为 /console/audit 页 |
| 全局（缺失） | 404 / 错误页 / 未授权页 | 缺失 | V9 新增统一错误页（404/403/500）与无权限态复用 NoPermissionState |
| 全局（缺失） | 首用 onboarding 向导 | 缺失 | V9 新增（登录后按画像分流，见表一 #1） |

## 表三 · 后端路由域 × 前端覆盖核对（防虚构）

| 后端路由模块 | 前端使用 | 备注 |
|---|---|---|
| auth / me | Login, Layout, Users, 全局 Context | 已接 |
| workbench | Dashboard(todo/overview) | UX-04 已接 |
| discovery / products / listings / compliance / launch / shops / suppliers / purchases / factory_network / pricing / ads / orders / refunds / settlements / support / workflows / knowledge / bi / finance / alerts / ai / admin | 表一对应页 | 已接 |
| schedules | Workflows（调度） | 已接（经 /workflows/schedules 路径，待确认是否独立前缀） |
| actions | Ads（AI 动作审批） | 已接（是否通用动作域待确认） |
| cross_border | **未接** | V9 新增「到岸成本配置」页接入（表一 #23） |
| product_assets | Products 详情（/products/{id}/assets，待确认） | 归属待确认 |
| product_channels | **未确认** | 前端未见引用，V9 排期前需架构确认 |

## 附 · 与 V1.0 旧文档（FRONTEND_PAGE_MATRIX.md）不符处（以代码为准）

1. 旧文档「`POST /launch` 后端已有、前端未封装」→ 现 `composables/launchCenter.js` 已封装创建（POST /launch）。
2. 旧文档「Dashboard 自拼聚合」→ 现 Dashboard 已接 `workbench/todo` + `workbench/overview`（UX-04 BFF）。
3. 旧文档「无面包屑」→ 现 `components/Breadcrumb.vue` 已存在并由 router meta.domain 驱动。
4. 旧文档「RunStatus 建议移入 components」→ 现已是 StatusTag 薄封装，但文件仍在 views/。
5. 旧文档菜单 5 组 → 现 `composables/navigation.js` 已按 11 域重构（UX-02 落地），并新增 `/platform-admin?tab=audit` 菜单项。
6. 旧文档口径为「页面本体不重写，仅归类」→ V9 为全站重设计，本矩阵的 V9 列即重设计目标态。

## 遗留待确认项

- `product_channels.py` 的领域与前端归属（无任何前端引用）。
- `product_assets.py` 是否仅服务于商品详情 assets tab。
- `schedules.py` / `actions.py` 的实际路由前缀（按引用路径推断，未逐行核对）。
- 最后一个 OWNER 是否允许被降级（影响 #26 验收）。
- 物流轨迹、AI 会话历史持久化等能力后端是否存在（本文一律标「待接入」，不虚构）。
