# FRONTEND V9 · API 映射（UX-A 架构冻结）

> 依据：PM 矩阵「数据来源」栏 + 逐文件核实 `backend/app/routers/`（本次已核实 product_assets / product_channels / schedules / actions / cross_border 的真实前缀与端点）。所有端点均为 backend 实存模块，未接能力标「待接入」。

## 0. 本次核实结论（原「待确认」项落定）

| 项 | 核实结果 |
|---|---|
| product_assets.py | 前缀 **/products**：GET/POST `/products/{id}/assets`、POST `/products/{id}/assets/{asset_id}/verify` → 归属商品详情资产 tab，V9 商品详情页接入 |
| product_channels.py | 前缀 **/products**：仅 GET `/products/{id}/channels`（只读）→ 实存但现网未接；V9 作为商品详情「渠道」信息可选接入，标注只读 |
| schedules.py | 独立前缀 **/schedules**（CRUD + POST `/{id}/run`）→ 现网 Workflows.vue 已直调 `/schedules`，PM 矩阵「经 /workflows/schedules」记载有误，以 /schedules 为准 |
| actions.py | 独立前缀 **/actions**：GET 列表、POST `/{id}/approve|reject|execute` → 通用 AI 动作域，V9 ApprovalPanel 统一消费（广告等入口共用） |
| cross_border.py | 前缀 **/cross-border**：duty-rates / logistics-routes / platform-fees / compliance-rules 各 CRUD + `/products/{id}/compliance` + POST `/landed-cost` → 「到岸成本配置」页接入确认可行 |
| 最后一个 OWNER 降级 | backend auth.py/me.py **未见显式守卫** → 维持「待确认」，前端确认弹窗不承诺后端拦截 |

## 1. 页面 → 端点映射表

方法默认 GET 读取；「操作」列为写端点（均以 `/api` 为 baseURL）。workbench 契约（/workbench/todo、/workbench/overview，signals/partial/sources、COMPLIANCE 脱敏、FACTORY 空、partial 降级）沿用 V1.0 契约 v1.2。

| 页面（新路径） | 主数据源 | 操作端点 |
|---|---|---|
| 登录 /console/login | auth（login）、me | auth 登录 |
| 经营工作台 /app | workbench/todo、workbench/overview；跳转目标域各自读取 | — |
| 商品发现 /app/market/discovery | discovery | discovery 扫描/选品/评分；转入商品池=POST products |
| 商品池 /app/products | products、product_channels（只读）、pricing | products CRUD、采集（抓取/标准化）、代发下单（purchases/dropship 链路） |
| 商品详情 /app/products/:id | products、product_assets（/products/{id}/assets）、product_channels | assets CRUD+verify；products 更新 |
| Listing 工作台 /app/listings（+:id） | listings、shops、compliance | listings 生成/优化/复核/发布/回执（PublicationReceipts 数据源） |
| 合规报告中心 /app/compliance | compliance | 发起检测 |
| 合规工作台 /app/compliance/approvals | listings(review-queue)、compliance、shops | listings 审批/驳回、compliance 发起检测 |
| 上线中心 /app/launch | launch、products、shops | POST /launch（经 launchCenter.js 现封装） |
| 上线详情 /app/launch/:id | launch、listings | launch 步骤动作、同步 |
| 店铺授权 /app/channels/shops | shops | OAuth 授权/换码/刷新/同步订单/类目映射 |
| 供应商库 /app/supply/suppliers | suppliers、factory_network | suppliers CRUD/评分 |
| 采购单 /app/supply/purchases | purchases、suppliers | 采购创建、按预测生成 |
| 工厂门户 /factory/products | factory_network(portal) | portal 产品/产能 CRUD |
| 动态定价 /app/pricing | pricing、workflows | 利润计算、采纳建议价、重定价工作流触发 |
| 广告增长 /app/ads | ads、actions、shops | 活动 CRUD/优化、AI 选词；审批走 /actions/{id}/approve\|reject\|execute |
| 订单管理 /app/orders | orders、shops | CSV 导入、状态流转、发货、真店同步 |
| 售后管理 /app/refunds | refunds | 发起退款、状态流转、退货收货、确认退款 |
| 账期结算 /app/settlements | settlements、suppliers | 生成对账单、确认、登记付款 |
| 智能客服 /app/support | support、ai、knowledge | 人工回复、AI 自动回复、关闭 |
| AI 工作流 /app/ai/workflows | workflows、**/schedules**、actions | 模板运行、调度 CRUD+run、失败恢复 |
| 知识库 /app/ai/knowledge | knowledge、ai | 文档 CRUD/搜索、候选补写/审批 |
| BI 经营分析 /app/analytics/bi | bi | AI 报告生成 |
| 财务工作台 /app/analytics/finance | finance、orders、cross-border | 订单行/费用/结算单录入、汇率查询 |
| 到岸成本配置 /app/analytics/landed-cost | **cross-border**（duty-rates / logistics-routes / platform-fees / compliance-rules CRUD；/landed-cost 试算） | 四组 CRUD；口径与 pricing 共用 costing 实现 |
| 风险巡检 /app/risk/alerts | alerts、ai | 扫描、确认告警、规则 CRUD |
| AI 决策依据 /app/ai/decisions | ai | —（只读） |
| 用户与角色 /app/settings/team | auth | 成员增改、角色分配 |
| AI 与集成设置 /app/settings/ai | ai、me | AI/经营参数读写、Key 配置、日志查看 |
| Console 四页 /console/* | admin、shops、ai、auth | 开通租户、代客进入/退出、日志、规则检查、清演示数据 |
| AI 副驾驶（全局） | ai | 对话（actions 可执行需确认；会话持久化**待接入**） |

待接入（后端未证实，不放可点击入口）：物流轨迹（orders 发货后履约链）、AI 会话历史持久化、/factory/orders、/factory/settlements、工厂侧 AI 产品资料生成（product_assets 工厂侧复用待确认）。

## 2. 前端 API 层组织

```
frontend-v9/src/api/
├── client.js        axios 实例平移自 api.js（401 拦截+detail envelope 规整原样保留）
├── dto.js           DTO 映射纯函数：后端 snake_case → 视图模型；每域一组 transformXxx（纯函数可测）
├── errors.js        错误规整：detail 对象/字符串统一为 {message, traceId, blockers?}；供 ErrorState 消费
└── domains/         按域一文件（products.js / launch.js / workbench.js …），导出 fetchXxx/actionXxx
```

- 页面禁止直接 import axios：一律经 domains/ 模块；转换逻辑在 dto.js 纯函数中，与展示分离（可 vitest 直测）。
- 错误处理：client.js 只做 401/全局 toast 一次；页面级错误经 errors.js 规整后交 ErrorState，不重复弹 toast。

## 3. BFF 只读约束（沿用 V1.0 契约，禁止第二套重复 Service）

- 仅 `/workbench/todo`、`/workbench/overview` 两个只读聚合端点；V9 新页面**不得新增后端聚合端点**，缺数据用现有域端点前端拼装。
- COMPLIANCE 角色脱敏、FACTORY 返回空、字段级 `partial` 降级语义原样保留；前端 TaskCard/MetricCard 必须实现 partial 提示（数据完整性提示）。
- workbench 契约变更须走契约文档流程（CONTRACT.md），不允许前端私自假设字段。
