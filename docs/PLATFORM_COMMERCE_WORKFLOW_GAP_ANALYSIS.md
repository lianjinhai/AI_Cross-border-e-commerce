# Platform Commerce Workflow 与 Launch Center 差距审计

> 状态：AUDITED / 待下一阶段设计指令；本文建议未实施、未冻结。
> 最后更新：2026-10-10（Asia/Shanghai）。
> 代码基点：`d14232e`；审计开始时 Git 工作区干净。
> 范围：本地代码、模型、迁移、权限、前端和测试源码审计。未修改业务代码，未启动服务，未访问主库或外部账号，未执行迁移或外部发布。

## 0. 结论与证据边界

当前系统有商品、Listing、发布审批、平台发布意图、目的国合规证据、成本利润计算、采购与库存基础。缺少的是把它们串成 **Workspace × Product × Store × 固定版本 Profile** 的持久化经营流程。

**现有 Workflow 可扩展，但不能原样承担 Platform Workflow。** 推荐保留并扩展 `WorkflowTemplate / WorkflowRun / WorkflowStep`，将平台生命周期作为独立的流程种类，由确定性状态迁移服务处理；已有顺序 Agent 批任务继续按原语义运行。不要复制一套三表和第二套 ERP，也不要仅往 `context` 塞几个字段就宣称完成。

**发布成功与在售事实目前没有彻底分离。** Walmart Adapter 已明确 Feed 提交不等于上线，前端也有提示，但公共发布服务仍将 Listing 置为 `published`。Launch 必须分别保存提交结果和可销售证据。

本报告回答用户要求的十二项问题（§1—§12）。来源分为：

- **已核对实现**：下文引用的本地路径和符号；说明代码行为，不代表线上联调通过。
- **业务样本**：用户消息中的复杂平台阶段、核价、备货、标签和材料流程。用户补充的是项目路径，未提供独立平台原始材料，因此不声称已审阅截图、官方手册或真实订单。
- **建议**：目标字段、表和规则均为后续设计输入，未创建、未迁移。
- **未核实**：主库当前 Alembic revision、存量数据量、账号授权、实际平台接口与法规最新要求。本轮没有进行法律或平台规则有效性认定。

### 必须优先处理的差距

| 优先级 | 发现 | 本地证据 | 影响 |
|---|---|---|---|
| P0（新 Launch 上线前） | 缺少 Product × Store 生命周期锚点 | `backend/app/models.py` 的 Listing、WorkflowRun | 同品跨店不能可靠保存独立进度 |
| P0 | Listing 全局已发布判断与 Action 查重不充分区分店铺 | `backend/app/services/action_publish.py` 的 publish_listing；`backend/app/services/action_system.py` 的 _existing_intent | 前者可能直接重放已有 external_id，后者会拒绝不同店铺的新意图；底层按店铺的发布记录不能消除上层限制 |
| P0 | Feed 提交状态被上层折成 published | `backend/app/services/adapters/walmart.py` 的 publish_listing；公共发布服务 | 不能用 published 或 HTTP 成功判定 ACTIVE |
| P0 | 市场与合规检查未可靠绑定目标店铺 | `backend/app/services/publish_gate.py` 的 resolve_destination、evaluate | 商品属性或适配器默认市场可能替代真实目标市场；未知目的地或检查异常返回 warn，不能作为新 Launch 的通过依据 |
| P0 | 图片只有 URL，没有授权状态和使用范围 | `backend/app/models.py` 的 Product.images；`backend/app/services/action_publish.py` 的 publish_facts | 无法阻断 UNKNOWN/RESTRICTED 素材进入正式发布 |
| P0 | 缺少核价决策与可信成本快照 | `backend/app/services/costing.py` 的 calc_profit；`backend/app/services/action_policy.py` | 不能安全实现自动接受平台核价 |
| P1 | 工厂步骤可见性、店铺范围权限、人工待办、事件日志未闭环 | `backend/app/auth.py`、Workspace Context、Workflow 表 | 不能靠前端隐藏字段满足数据隔离和审计 |

P0 是新能力的上线前置级别，不表示本轮已修复或已复现线上事故。

## 1. 当前系统已经能承载哪些阶段？

| 业务阶段 | 当前承载 | 缺口与复用边界 |
|---|---|---|
| PRODUCT_INFORMATION | Product 的 SKU、标题、类目、品牌、HS、attrs、images；商品标准化 Action | 可直接作为资料源；缺少按 Store/Profile 的资料完成度与锁定快照 |
| PLATFORM_ATTRIBUTES | CategoryMapping、PlatformRulePack、Adapter 必填校验；部分平台 listing_readiness | 可复用预检；缺少独立平台属性任务和按市场/模式的完整 schema |
| PRODUCT_CREATED / PLATFORM_SUBMISSION | Listing 草稿、PUBLISH_LISTING Action、PlatformPublishAttempt | 复用提交审批与幂等意图；需区分商品 ID、offer ID、feed ID、提交 ID |
| PLATFORM_REVIEW | Walmart submission_status 有查询入口 | 没有通用审核等待、回调、轮询推进、状态映射；ListingReviewDecision 是内部复核，不能冒充平台审核 |
| PRICE_REVIEW | PricingRecord、统一 costing 服务 | 只有内部计算结果，无平台核价轮次、回传证据、币种绑定 |
| PRICE_DECISION | 通用 AiAction 审批与执行器 | 没有 ACCEPT/COUNTER/REJECT/ABANDON 的业务记录、Policy 和 Executor |
| FIRST_ORDER | Order、PurchaseOrder 已存在 | “平台首单”究竟是销售订单、备货申请还是履约任务尚未确定；样本节点可表达人工任务，不能伪造销售订单 |
| STOCK_PREPARATION | SupplierOffer、PurchaseOrder、Warehouse、InventorySnapshot | 没有请求量/批准量/备妥量和平台备货引用；采购收货与平台备货不能等同 |
| MARKET_COMPLIANCE | DestinationComplianceRule、ProductComplianceEvidence、ComplianceReport、发布门禁 | 已有 Product × Country 基础；缺少通用 Artifact 类型、审核状态、版本、有效起始时间、平台适用范围 |
| LABEL_PREPARATION | images 与合规 evidence_ref 可保存引用 | 无标签包、条码来源、标签版本及真实认证数据绑定 |
| PHYSICAL_EVIDENCE | 通用 JSON 输出可放描述 | 无一等人工节点、实拍证据归属、提交/拒绝/补交循环 |
| READY_FOR_SALE / ACTIVE | Listing.status、external_id、published_at | 无完整前置条件汇总和平台在售核验；Product.active 也只是内部商品状态 |
| MONITORING | ProductPerformance、商业分析、AlertEvent、Schedule | 可复用经营分析与提醒；尚未与具体 Launch 的在售/失效事件建立可靠关联 |

库存现状尤其需要分清：供应报价在 `SupplierOffer.in_stock` 等字段；可售数量部分保存在 `Product.attrs.onhand`；海外仓快照是 `InventorySnapshot`；采购承诺是 `PurchaseOrder`。`backend/app/routers/purchases.py` 的 receive_po 直接增加 attrs.onhand，部分收货余量按取消处理，不能直接拿它充当平台分批备货。

## 2. 哪些现有模型可以直接复用？

模型定义权威源为 `backend/app/models.py`。下表“复用”不等于字段已经满足全部 Launch 需求。

| 现有模型/服务 | 建议用途 | 不应承担的职责 |
|---|---|---|
| Product | 唯一商品主档 | 不塞入每个店铺的整套流程状态 |
| Supplier、SupplierOffer、SupplierCatalogProduct、SupplierPortalMember | 货源、报价、工厂绑定 | 不创建 TemuSupplier/TemuStock |
| Shop | Store 的已有实现；销售/货源角色、授权、归档 | 不另建同义 Store 表；缺的 market/store_type/business_mode 走增量扩展 |
| Listing | 平台内容草稿和现有发布业务对象 | 不把一个全局 external_id 当成所有店铺的外部商品 |
| PlatformPublishAttempt | 按 tenant/listing/shop 唯一的发布意图、checkpoint、外部回执 | 不充当长期经营实例、全部外部动作或事件总线 |
| WorkflowTemplate / WorkflowRun / WorkflowStep | 定义、实例、步骤的存储与恢复基础 | 不能用旧状态直接假装覆盖长周期生命周期 |
| PlatformRulePack / CategoryMapping | 平台规则、类目映射 | 平台生命周期版本必须与规则包版本分开固定 |
| ComplianceReport / ListingReviewDecision | 内部风险分析和内部内容审核证据 | 不替代真实认证文件或平台核价/审核 |
| ProductComplianceEvidence / DestinationComplianceRule | 市场合规注册基础 | 不把 evidence_ref 非空等同权威认证已验证 |
| PricingRecord / ExchangeRate / PlatformFeeSchedule / DutyRate / LogisticsRoute | 内部经济性与来源快照基础 | 不覆盖平台价格决策历史 |
| PurchaseOrder / Warehouse / InventorySnapshot | 采购与仓库事实 | 不把平台批准备货量写成销售库存 |
| AiAction / AiDecision / AiLog | 建议、审批、执行与 AI 轨迹 | 非 AI 的平台事件、人工确认仍需通用流程审计 |
| Order / OrderLine / ProductPerformance / AlertEvent | 上线后经营监控 | 不因样本走到 FIRST_ORDER 就伪造交易或利润 |

“Publishing Task”在当前代码中不是独立同名 ORM 模型。可复用的是 `AiAction(PUBLISH_LISTING)`、`PlatformPublishAttempt` 和 WorkflowStep 的组合，不应再建一个重复的发布任务系统。

## 3. 哪些阶段或横向能力无法表达？

### 3.1 定义与状态

当前模板 steps 主要是 `{agent, action, params}`，无强类型、版本冻结、依赖、参与者、证据条件、超时策略。Run 仅记录 template_key、context、运行状态、租约；没有 product/store/listing 外键、市场和 lifecycle_status。Step 有顺序和输出，但没有稳定 step_code、人工责任人、外部状态和证据版本。

目标至少需要用户提出的十一种通用 Step Type；MANUAL_TASK 建议作为执行方式，和 COMPLIANCE/LABEL 等业务类型正交。例如 LABEL + MANUAL_TASK + FACTORY 表达贴标，LABEL + SYSTEM 表达标签包生成。无需加入平台专属枚举。

生命周期状态不能粗暴映射：旧 `success` 是执行完成，不是 ACTIVE；旧 `blocked` 会标记 finished_at 并跳过后续步骤，不能当作所有 WAITING_PLATFORM/WAITING_USER 的别名。`WAITING_APPROVAL` 长于现有 Run.status 的 String(16)，不能直接追加枚举而忽略迁移。

### 3.2 核价与单位经济性

`backend/app/services/costing.py` 已计算采购、物流、平台费、广告、退款、支付费、关税、进口 VAT、清关、退税和仓储要素，应作为唯一计算基础。

但是 `calc_profit` 的输出币种固定 USD，没有显式 platform/store 参数；成本平台从商品属性或默认值读取。采购价、广告、物流、费用和 USD 汇率存在默认/估算路径，采购报价币种换算有严格缺汇率检查，但不能因此认定全部经济性输入可信。`cost_elements` 接受 platform，不代表上层 calc_profit 已贯通这一参数。

因此还需：显式 Store/Market/Currency 参数、有效报价与汇率时点、估算来源/缺失项、统一贡献利润口径、最低安全价求解与计算快照。平台售价相关税费可能随售价变化，不能简单用当前利润倒推安全价。批量物流与仓储金额需统一到单件口径后再用于核价。

`PricingRecord` 是分析记录，不包含申报价、平台核价、轮次、决定及决定理由。建议新增 PriceReview 业务记录并引用 PricingRecord/成本快照。低于底价或可信输入不足时禁用 AUTO_SAFE 的 ACCEPT；重新核价使旧审批失效。人工是否可特批及限制需在下一阶段明确。

当前 `action_system.submit_action` 显式拒绝 pricing Agent 提交业务 Action。不能直接加个按钮绕过这条边界；核价分析继续由现有 Pricing 能力承担，执行策略需要经过 Agent OS 变更设计。

### 3.3 Artifact、Label 与素材权利

ProductComplianceEvidence 只有商品、国家、requirement、evidence_ref、valid_until 等字段；唯一键不允许同一证据要求并存多版本，现有 upsert 会更新当前记录。它不是完整 Artifact Registry。

建议覆盖 MANUFACTURER_INFO、RESPONSIBLE_PERSON、PRODUCT_CERTIFICATE、PRODUCT_PHOTO、LABEL、BARCODE、DECLARATION、OTHER，明确“已上传、待核验、有效、过期、拒绝”区别。Registry 应输出适用范围和所缺资料，而不只是一个商品级布尔值。

产品图片没有 OWNED/SUPPLIER_AUTHORIZED/LICENSED/UNKNOWN/RESTRICTED 状态、授权证明、版本及平台使用范围。采集 URL/HTML 得到的图片不能回填为 OWNED。衍生图应继承来源约束，换背景、去 Logo 或重绘不改变授权事实。

Label Package 需引用不可变输入版本和受核验的认证信息；认证标志不是由模型自由生成的文案。条码也须有来源、类型、校验和适用范围。标签生成成功、打印完成、贴标实拍被接受是不同节点。

### 3.4 同步、事件和人工任务

BaseAdapter 有授权、订单同步、发布、预检和 submission_status 契约，但没有统一 PriceReview/Stock/Artifact/Activation 同步协议。Shop 列表返回的 capabilities 来自适配器类，不是按账号、市场、业务模式确认的 Store 能力。

未发现通用生命周期 Webhook 接收、版本化 raw_status 映射或可可靠投递的事件 outbox。现有 AlertEvent 是巡检告警，不能当成具备事务提交、消费确认和重放能力的事件总线。

人工节点必须持久化说明、指派对象、证据、确认人、完成条件与驳回历史；不能由“用户点完成”直接绕过合规和核价门禁。未知外部状态保留 raw_status 并阻断自动推进；轮询超时不能假设完成。

## 4. 哪些前端页面可以复用？

本轮是源码交互审计，未启动浏览器进行视觉或可用性验收。

| 页面/组件 | 已有内容 | Launch 接入方式 |
|---|---|---|
| `frontend/src/views/Products.vue` | 商品列表、详情抽屉、属性、评分、报价/Listing/合规等详情及经营表现读取 | 保留抽屉与主档操作，整理为概览、货源、销售渠道、上线进度、经营表现、合规、AI 建议、历史；增加目标 Store 入口 |
| `frontend/src/views/Listings.vue` | 文案生成编辑、内部复核、发布选择、能力提示、部分平台预检、Feed 查询 | 保留专业工作台，Launch 步骤引用现有编辑/复核/发布能力；回跳绑定实例和店铺 |
| `frontend/src/components/PublishActions.vue` | 发布 Action 审批执行队列 | 复用审批交互；增加实例上下文和明确提交/在售结果，避免两套审批 |
| `frontend/src/views/Workflows.vue` | 模板卡片、计划任务、运行历史、步骤抽屉、恢复 | 复用 Stepper 交互思路与状态展示组件，保留自动化页面；现有 agent.action 标题不适合新手上线流程 |
| `frontend/src/views/Shops.vue` | 店铺授权、平台能力与类目映射 | 复用渠道选择，补市场/模式资料与能力真实性显示 |
| `frontend/src/views/Compliance.vue`、`frontend/src/views/ComplianceWorkbench.vue` | 检测报告、风险与复核队列 | 复用分析和审核；Artifact 上传/版本核验不是现成页面功能 |
| `frontend/src/views/Pricing.vue` | 成本试算和定价结果 | 复用成本展示；补平台价格、底价、可信度、决定及对应 Action |
| `frontend/src/views/Suppliers.vue` | 供应商、机会、采购单及收货 | 复用采购选择与追踪，不把采购单 Tab 改名后当成平台备货 |
| `frontend/src/views/FactoryPortal.vue` | 工厂供给入口 | 在门户增加受限的备货/贴标任务投影，禁止展示完整卖家流程和财务 |
| `frontend/src/views/AiDecisions.vue`、Alerts、经营分析页 | AI 依据和经营提醒 | 从步骤上下文联到现有证据、风险和经营表现 |

当前 `frontend/src/router.js` 无 Launch、Asset Center、Label Center 独立路由；不能描述成已有页面。已有仓储后端模型，也不等于已有完整 Inventory 专业前端。

Launch 新增一个列表/详情体系。列表显示商品、平台/店铺/市场、当前阶段、required 步骤完成数、阻断、确定性下一动作、责任人、AI 建议。详情左侧时间线、右侧当前任务；Guided/Professional 使用同一后端 DTO 和动作集合，仅改变信息密度。

目前未发现 Experience Mode 实现。新增偏好不应改变权限或使 Guided 隐藏必要风险。并行分支下不能只依赖 current_step 标量，应有可执行步骤集合；required 可适用步骤作为进度分母，等待和失败不计完成，跳过必须有 Profile 依据。

## 5. 哪些菜单应该重新归类？

`frontend/src/views/Layout.vue` 已有“商品”分组：商品发现、商品池、Listing、合规工作台、合规检测。建议在该组增加“上线中心”，保留专业入口，避免再建生命周期、标签、证据、核价等多个一级菜单。

当前“采购”分组同时放店铺授权、供应商、动态定价，混合了渠道与采购职责。建议：供应商/采购继续属于采购；店铺授权作为销售渠道配置入口（先保留旧路由，菜单可移到现有运营分组）；定价作为商品/经营专业工具，由 PRICE_DECISION 深链进入。

“AI 工作流”保持自动化与调度含义，不能与 Launch 混成一个状态列表。合规员继续只看到其许可的审核任务；工厂伙伴仍以门户任务为主要入口。菜单可见性不能替代 API 的数据范围检查。

## 6. 是否真正需要新增数据库表？

**需要少量新增领域持久化，但不需要照搬候选九表，更不需要平台专用表。** 以下是审计推荐，精确 DDL 留下一阶段。

| 候选领域 | 推荐决策 | 理由与约束 |
|---|---|---|
| platform_workflow_definition | 优先扩展 WorkflowTemplate | 新增流程种类、选择维度、版本、状态与受校验 steps schema；发布后的版本不可覆盖 |
| platform_workflow_instance | 优先扩展 WorkflowRun | 增量绑定 workspace/product/listing/shop、definition/version、市场和生命周期状态；旧执行状态保留；外键和查询索引不能只藏在 JSON |
| platform_workflow_step_instance | 优先扩展 WorkflowStep | 加 step_code、业务类型、执行方式、actor、等待/完成条件、证据、外部引用、指派等；不用再复制一张步骤表 |
| platform_status_mapping | 首期作为不可变 Profile 版本配置 | 受版本控制的映射已能满足两个本地 Profile；需要运营在线维护/独立审核时再建表，不能无版本热改 |
| compliance_artifact | 优先扩展 ProductComplianceEvidence | 保留现有证据来源；增加 artifact_type/status/version/valid_from/source 等，旧查询通过兼容层读取当前有效版；若设计证明两种语义不能安全合并，再论证独立 Registry，避免双真相 |
| product_asset | 建议新增 | 没有可承担授权、来源、版本、市场和使用范围的现有模型；Product.images 保留为兼容投影 |
| product_label | 首期复用 product_asset 的 LABEL_PACKAGE 类型和结构化 manifest | 标签包是可版本化的生成资产；打印批次和复杂监管追溯出现后再论证专表 |
| price_review | 建议新增 | 多轮平台核价/决定是业务事实，PricingRecord 和 AiAction 都不能替代该事实源 |
| stock_preparation | 建议新增 | 平台备货审批/执行事实独立于采购、供应库存和销售库存；关联既有 PO、Warehouse、Supplier |
| workflow_event / outbox | 建议新增通用追加式事件日志，兼作首期 outbox | WorkflowStep.output 会覆盖，AiAction 不覆盖所有人工/平台事件；需要不可变前后态、事件序号、幂等键与可靠投递状态 |

以上最小持久化方向是 **扩展既有三张 Workflow 表和证据/店铺表，新增 Asset、PriceReview、StockPreparation、WorkflowEvent 四类表**。这是审计建议的领域数量，不是已评审的最终表数；不以“少建表”为由丢弃版本、外键、审计或并发约束。

一个 Product × Store 首期只保留一个长期经营实例；重复启动返回该实例。后续重启活动若需要多次实例，先明确 campaign/attempt 语义再改唯一性，不能默认无限新建。可使用一个店铺绑定的 Listing 草稿对应一个 Launch，跨店生成独立草稿，继续复用原 Listing 模型；是否给 Listing 加可空 shop_id 或只由 Run 绑定，须在架构设计时统一，不能继续从平台名猜店铺。

## 7. 当前 Workflow Engine 能否承担 Platform Workflow？

证据：`backend/app/workflows/engine.py` 的 start_run、run_workflow、_claim_run、_LeaseHeartbeat、resume_run、recover_incomplete_runs；`backend/app/routers/workflows.py`。

### 可以复用的基础

模板生成 Run/Step；步骤参数快照；按 seq 执行；数据库租约和续租；异常重试；跳过已成功步骤；上下文持久化；启动恢复；人工恢复；可信 Action 发起者与 Orchestrator 接入。冻结架构 §8.5 明确允许现有 Workflow Layer 演进。

### 不能原样复用的语义

run_workflow 把可调度动作限制为 `_KNOWN` 中的 Agent/action；流程以循环执行到完成或阻断为主。business_status=blocked 时设置 finished_at，并将后续步骤标成 skipped；resume_run 会重置 failed/blocked/skipped。这样不能区分“合法跳过”和“被阻断尚未开始”，也不能表达独立人工任务、异步回调和分支依赖。

模板仅用 key 读取，未固定定义 ID/版本；虽然 Step.params 已快照，完整的进入/完成/映射规则没有版本快照。旧恢复器会领取 queued/running Run，新生命周期若混用这些状态可能被错误派发给 Agent。

### 推荐扩展方式与备选

推荐为 Template/Run 增加 flow_kind，将平台生命周期分发到同一 Workflow 子系统内的确定性 transition 服务。旧恢复/列表/调度需按 kind 隔离。短任务复用租约原则和安全执行接口；等待平台/人工时释放 worker，不持有数天线程或睡眠循环。Step handler 从注册表查找 Service、Adapter、人工任务或 Orchestrator，不能把所有业务塞进 Adapter。

合法迁移必须复核依赖、当前修订号、权限、证据和幂等键。NBA 由状态机给出 available_actions，AI 只能解释和排序，不能添加动作。执行时重新计算权限和前置条件，防止旧页面或旧审批穿透。

备选方案是在旧三表旁增加一张领域绑定扩展表；仅当字段空值/唯一性或旧报表兼容成本高于扩展成本时采用。不推荐完全另建三表、另建引擎；也不推荐把一切放入 Run.context。

### 复用比例的可核查口径

以基础机制清单衡量：模板→实例、步骤持久化、租约、重试、启动恢复、断点恢复、上下文传递、Orchestrator 接入均已有资产，但其中派发/恢复需适配新 kind。以本轮业务验收衡量，版本化 Profile、Product×Store 实例、外部等待、人工任务、核价、平台备货、Asset/Label、NBA、生命周期同步/事件都需新增或明显扩展。

因此不能诚实地给出“代码复用 80%”之类数字。本报告确认既有 Workflow 三个核心实体全部有复用价值，完整平台生命周期验收尚无现成闭环；工时或行数复用率应在下一阶段任务拆解后估算。

## 8. 最小改造方案是什么？

建议形成一条完整、可验证的纵向路径，不把最低版本简化成只有 Stepper 的页面：

1. 用户选择商品与销售店铺，服务端解析 Workspace、Membership、Store 和市场/模式，拒绝 source 店铺、归档店铺和越权目标。
2. Profile resolver 按 platform、market、store_type、account_type、business_mode、category 选择唯一已发布版本；不匹配/有歧义时要求补资料，不能猜默认复杂流程。
3. 创建或复用 Product × Store 实例，固定 definition/version 与条件/映射快照，绑定店铺专属草稿。
4. 确定性状态机计算每一步的完成条件、阻断原因、available_actions 和 next_best_action；AI 推荐不是状态来源。
5. 提交走既有 PUBLISH_LISTING 审批和发布意图，补强店铺维度幂等。外部回执先归类为 submitted/reviewing/active，未知状态保持等待。
6. 人工任务允许录入平台核价、备货和材料证据，标注 MANUAL/EXTERNAL、来源与核验状态；无 API 不删步骤，也不假装同步成功。
7. 核价走统一成本服务；Artifact、素材权利、标签包与实拍全部满足 Profile 的完成条件后，才能验证 READY/ACTIVE。
8. 状态、前后态审计和待投递事件在同一事务提交；外部副作用保留意图、幂等键、结果不确定和 read-back 补偿，避免把网络重试当成 exactly-once。
9. 同一个 Launch 页面展示两个本地测试 Profile，产品详情的渠道 Tab 返回对应实例；上线后链接现有经营监控。

API 建议沿用当前 `/api` 前缀（`backend/app/main.py` 和 `frontend/src/api.js`），提供 launch 列表/详情/创建/steps/actions/sync，以及 products 的 channels/assets/compliance-artifacts 聚合能力。用户的 `/api/v1` 是建议路径；不应只给 Launch 单独引入 v1 而未说明全站版本策略。已有合规和发布接口保留，Launch 层协调调用相同 Service。

同步优先实现一个统一 ingestion 服务：人工刷新、Polling、Webhook 都送入它，携带可信 workspace/shop、外部对象类型与 ID、原始状态、平台事件 ID/版本、来源时间。必须拒绝错店回调、重放、旧版本覆盖新状态；Webhook 还需验签、防重放，未获支持的平台不得暴露“已连接”状态。

Temu 在 `backend/app/services/adapters/planned.py` 中为 restricted，继承未开放业务能力的基类。复杂测试 Profile 命名应强调“用户样本 / Contract Test / UNVERIFIED”，不修改该能力状态。其他 can_publish=True 平台也可能标为 protocol_ready_unverified，不能以布尔值代替真实验证。

## 9. 对现有 Workspace 冻结架构是否有影响？

核心 User → Workspace → Capability → Supply → Product → Store → Listing → Order → Finance 链路无需改变。Launch 增加经营流程关系，不引入新身份或第二套权限系统。

但实现不是“零影响”：

- `WorkspaceContext` 当前有 workspace_kind、membership_id、permissions、data_scope、legacy_tenant_id 等；`capability_profile`、`business_stage`、Experience Mode 并未随现有 Context 完整实现。按冻结契约增加字段需要评审和测试，不能擅改严格响应字段集。
- 身份解析已经有 MEMBERSHIP/LEGACY 双读，文件头仍称 legacy-only，是注释滞后。Launch 必须调用 resolve_workspace_context，而非信任前端 workspace_id 或直接以 User.tenant_id 代替工作空间。
- workspace_profiles.id 与 tenant_id 必须通过真实映射核对，不能假设数值永远相等。现有模型大多仍以 tenant_id 隔离。
- 迁移已定义 membership_data_scopes，但当前 Context 的 membership 路径返回 WORKSPACE_ALL，未看到细粒度 Store scope 的消费实现；不能宣称“已有 Store Scope”。需在统一权限层补充，执行和同步时复核。
- 当前权限 key 使用冒号，例如 listing:write。用户提出的 launch.read 等是业务权限目录，建议统一映射为现有命名风格 launch:read、launch:create、launch:manage、launch:price_review、launch:stock_prepare、launch:compliance_manage、launch:label_manage、launch:submit，并同步数据库权限行、代码常量、API 和前端；不能同时维护两套等义 key。
- Factory 账号仅允许供应门户和少数身份查询，权限为 supply:read/write，且非 Workspace Member。最小兼容方案是在门户下提供属于其 Supplier 的步骤投影，不开放全量 Launch DTO；请求必须沿绑定校验、脱敏财务/买方信息。若要求 Factory 直接访问 launch 路由或获 launch 权限，属于冻结身份/Agent 契约扩展，须先评审。

`docs/WORKSPACE_MIGRATION_PROGRESS.md` 的 R-04/R-05 是历史记录，本轮未读主库，不把历史行数作为现在的事实。

## 10. 对 Agent Operating System 冻结架构是否有影响？

总体兼容：Workflow 是真实状态源；Agent 经 Orchestrator 使用只读 Tool 分析；执行性建议转成 AiAction，经 Permission/Data Scope/Risk/Approval 后由 Executor 调用业务 Service，再由 Workflow 合法迁移。

需要增量登记 Action 类型、目标类型、Policy、Handler、事件目录和输入输出契约；不能直接让 Agent 写 WorkflowRun/Step。尤其价格分析当前被显式限制为 Insight，放开其业务 Action 不是普通枚举添加。

不增加“Temu Agent”或“上线老板 Agent”。平台差异属于 Profile/Adapter，通用领域能力仍遵守冻结的八个领域 Agent。模型产出只包含建议及证据，不得生成有效认证事实、自动确认人工贴标或伪造平台核价。

`AiAction` 已具备 workspace、权限、审批人、执行人、evidence、outcome 和幂等键，可复用。其现有 Handler 只覆盖部分动作；“冻结文档列过”不代表核价、标签、备货 Action 已实现。事件由可靠投递机制进入 Orchestrator，不直接调用 Agent；默认分析/建议模式。

建议审批证据至少固定 workflow_instance、step、store、profile_version、review_revision、成本/Artifact/Asset 版本。审批后这些数据变化应拒绝旧 Action，重新生成建议。执行失败不把步骤标成完成，外部不确定状态先核对再允许重试。

## 11. 是否存在数据迁移风险？

存在。本轮仅审计迁移源码，没有运行预检或数据库探测。

| 风险 | 建议控制 |
|---|---|
| 历史 Listing 没有 shop_id，local/demo 发布也可有 external_id | 优先按 PlatformPublishAttempt 的准确店铺关系追溯；无充分证据不猜店铺，不回填 ACTIVE；保留待认领历史 |
| 旧 published 与真正 ACTIVE 不等义 | 保留旧字段兼容；新 lifecycle_status 由明确证据推进；历史状态不得批量“升级成上线” |
| 旧 WorkflowRun 被恢复器/列表混读 | flow_kind 默认 LEGACY_AUTOMATION；新运行器、旧恢复器、Schedule、API 列表全加类型边界测试 |
| Template.key 查询与新版本并存 | 旧模板路径不改语义；新 Profile 固定 ID+version，发布后不可覆盖，退役仅影响新实例选择 |
| 旧证据唯一键与版本冲突 | 先扩展兼容读层再调整唯一键；明确历史证据未核验状态；有效时间、国家/区域映射不能盲目复制 |
| Product.images 没有授权 | 回填 UNKNOWN，保留原 URL 与来源；上线门禁新增后应提前展示待补授权任务，不将旧图默认为合法 |
| Workspace 身份表非全部登记为 ORM | 明确外键/迁移依赖，引用 workspace_profiles 的方式须同时通过独立测试库与 Alembic 测试，不能绕开维护窗口 |
| 权限目录数据库行与代码常量双来源 | 迁移补权限映射；测试 MEMBERSHIP 与 LEGACY 两条路径、失效 Membership 和身份变更 |
| SQLite 增列、唯一键、外键与 JSON 更新 | 副本演练 upgrade/downgrade、幂等回填和 FK/integrity 校验；JSON 采用新对象更新，避免 ORM 未检测变化 |
| 新数据回滚会丢领域事实 | 先停新入口/worker、保留审计和数据导出再回滚；已有外部副作用不靠 downgrade 撤销 |
| 服务启动含 create_all 和轻量迁移 | `backend/app/db.py` 的 init_db 有写行为；不得为审计而启动服务或绕过 Alembic 正式升级 |

后续迁移按扩展 → 兼容读取 → 小范围启用 → 验证 → 必要收缩推进；新增 revision，不修改已执行迁移。主库维护前按 `docs/backup_restore_runbook.md` 冷备并运行 `backend/scripts/migration_preflight.py`；P0 清零才执行。

## 12. 推荐的最终实施计划是什么？

| 阶段 | 交付 | 进入下一阶段条件 |
|---|---|---|
| A：当前审计 | 本报告 + 文档地图 | 用户下一阶段指令；本轮在这里停止 |
| B：领域/产品/状态设计 | 确定三表扩展、Store/Listing 绑定、Profile schema、状态迁移、角色与页面设计 | 冻结语义和兼容策略评审完成；不把建议当实现 |
| C：迁移设计与副本演练 | 新增表/列/索引、权限迁移、幂等回填、downgrade 与旧数据映射 | 主库不动，副本演练和租户隔离通过 |
| D：后端 Framework | Profile resolver、transition、NBA、人工步骤、事件审计、统一同步入口 | 重试/重放/并发/跨店/跨租户/旧流程回归通过 |
| E：业务服务接入 | 核价、备货、Artifact、Asset Rights、Label Package；复用现有发布和 Guardrail | 低价、缺资料、授权未知、无有效标志来源均不能自动放行 |
| F：Launch 前端 | 同一页面双模式、商品渠道与进度 Tab、专业页深链、Factory 受限任务 | 服务器控制动作；用户可知当前阶段、缺项、下一步及责任人 |
| G：两个本地 Profile + Contract/E2E | 复杂样本和简单样本，独立临时库/可控平台测试桩 | 两条完整生命周期成功及负向门禁成立；明确测试来源 |
| H：真实平台接入 | 仅对有授权及已确认接口的平台做联调 | 官方能力/账号权限/环境验证，真实回读确认；Temu 未验证继续受限 |

下一阶段应逐步产出的文档（**提案，未创建**）：

- `docs/PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md`：领域、复用与依赖边界。<!-- docs-ok: 提案，未创建，等待下一阶段 -->
- `docs/LAUNCH_CENTER_PRODUCT_DESIGN.md`：信息结构、角色、模式与专业页串联。<!-- docs-ok: 提案，未创建，等待下一阶段 -->
- `docs/PLATFORM_WORKFLOW_STATE_MODEL.md`：合法迁移、条件、版本、NBA、事件。<!-- docs-ok: 提案，未创建，等待下一阶段 -->
- `docs/PLATFORM_WORKFLOW_MIGRATION_PLAN.md`：迁移、回填、演练及回滚。<!-- docs-ok: 提案，未创建，等待下一阶段 -->
- `docs/PLATFORM_WORKFLOW_E2E_MATRIX.md`：测试输入、断言与证据。<!-- docs-ok: 提案，未创建，等待下一阶段 -->
- `docs/PLATFORM_WORKFLOW_PROGRESS.md`：分阶段完成记录和遗留问题。<!-- docs-ok: 提案，未创建，等待下一阶段 -->

### 两个 Profile 的验证边界

复杂样本：PRODUCT_INFORMATION → PLATFORM_ATTRIBUTES → PRODUCT_CREATED → PRICE_REVIEW → PRICE_DECISION → FIRST_ORDER → STOCK_PREPARATION → MARKET_COMPLIANCE → LABEL_PREPARATION → PHYSICAL_EVIDENCE → READY_FOR_SALE → ACTIVE；按需要挂接 MONITORING。FIRST_ORDER 先作为有来源说明的样本任务，不假定等于真实订单。

简单样本：商品资料 → 合规 → 发布提交 → 在售核验/ACTIVE。即使简单流程也不能让提交响应自动替代在售事实。

本地测试桩只用于 Contract/E2E，必须与真实 Adapter、真实账号和实际运营数据分开标识。人工录入的外部确认可以推进人工模式流程，但证据来源仍是 MANUAL，不能显示为 API VERIFIED。

| 场景 | 未来验收断言 |
|---|---|
| A 新手 | Guided 显示完成数、当前阶段、下一步；等待平台时明确无需操作 |
| B 专业 | 同一实例 Professional 展示价格、利润、证据、外部 ID、版本、同步时间；动作权限不变 |
| C 双 Store | 同一商品两个实例独立推进；一个已发布不阻断/污染另一个；同店重复创建幂等 |
| D 低核价 | 比较正确币种和成本快照；低于底价禁止 AUTO_SAFE 接受；成本缺失同样不自动接受 |
| E 缺合规资料 | 缺必需 Artifact、过期、未知市场或校验异常时 BLOCKED，原因可见 |
| F 标签不全 | 标签输入缺失/认证未经核验/实拍未通过时不能 ACTIVE；不能 AI 补造认证 |
| G 外部变化 | 验签/归属正确事件或授权刷新推进；重复、乱序、错店、未知状态不误推进 |
| H 升级版本 | v4 发布不改 v3 实例的步骤、映射和完成语义；新实例才选择 v4 |
| 额外权限门禁 | 跨 Workspace、READ_ONLY、COMPLIANCE 越权、Factory 非本厂步骤、superadmin 无代客身份均拒绝 |
| 额外可靠性门禁 | 重启恢复、审批后撤权/资料变更、外部提交成功本地失败、事件投递失败均可追溯并安全恢复 |
| 额外素材门禁 | UNKNOWN/RESTRICTED 及授权范围不覆盖当前平台/市场的资产不能正式发布 |

已有测试可作为回归基础：`backend/tests/test_api.py` 的 test_workflow_auto_listing，`backend/tests/test_action_system.py`，`backend/tests/test_platform_adapters.py`，`backend/tests/test_publish_gate.py`，`backend/tests/test_cross_border.py`，`backend/tests/test_warehouses_inventory.py`，`backend/tests/test_security.py`。这些测试不等于 A—H 已通过。正式实施时执行相关测试、全量基线检查（见 `docs/baseline.json`）和 `backend/scripts/e2e_feasibility.py`；涉及容器构建链路才追加对应容器/TLS 验证。

## 13. 审计覆盖与本轮交付记录

### 代码与长文档覆盖

- Workflow：完整主执行链与 resume/recovery 分段核对；模型 WorkflowTemplate/Run/Step、路由和前端模板/步骤/恢复交互。
- Publishing/Listing：action_publish 全链、action_system 的目标/意图/幂等策略、action_policy；Listing 和 PlatformPublishAttempt 定义、发布与复核 API 入口、前端发布/预检/Feed 查询。
- Product/Store：主档、Shop 模型、商品详情聚合、店铺列表能力、shop_scope；商品抽屉、菜单和路由。
- Compliance/Pricing/Inventory：证据与规则模型、check_evidence/requirements_for、门禁全链、costing 全文、采购收货和库存服务关键路径；相关前端 API 接点。
- Adapter：BaseAdapter、contract、registry、planned；逐平台能力声明及 Walmart 提交/查询、其他发布返回点。未进行逐平台所有 HTTP 分支的完整协议审计。
- Identity/Agent：WorkspaceContext 字段、权限常量、MEMBERSHIP 双读、Factory/平台路径白名单、Action 身份复核、Orchestrator 入口；Agent OS 架构 §8.5、§9.1、§13、§14、§17 重点核对，其他章节通过目录定位。
- 规范：AGENTS 全文；CODE_AND_DIRECTORY_STANDARD 的文档维护段重点核对；DOCUMENT_MAP 全文；Workspace 进度尾部作为历史上下文。
- 迁移：迁移文件清单、Workspace identity expand 结构与 downgrade、db.init_db 的启动写行为；未逐个执行迁移或核对主库应用状态。

宽范围检索曾发生输出截断；影响核心判断的 Workflow 恢复、模型、成本、合规、权限、菜单及发布状态返回点已通过缩小范围重读。覆盖按上述模块与符号界定，不声称逐行审完所有前后端源码或所有架构章节。

### 验证和停止点

本轮仅新增本报告、更新 `docs/DOCUMENT_MAP.md` 的登记。已运行 `backend/scripts/check_docs_consistency.py --json`，所有检查项为空、total=0、退出码为 0；`git diff --check` 通过；`git add --dry-run` 确認仅包含上述两份 Markdown 文档。初次文档检查发现未来六份设计文档被当成失效路径，已按现有校验器约定逐行标注“提案，未创建”，未创建占位文档或放宽检查器。未运行后端/前端功能测试、E2E、迁移和真实 API，因此没有新的“可部署/真实接入/生命周期验收通过”结论。

下一步是阶段 B 的架构、产品与状态设计，等待用户指令；不自动进入编码或创建其余六份设计文档。
