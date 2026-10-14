# 前端 R3 后端能力映射（FRONTEND_R3_BACKEND_CAPABILITY_MAP）

> 日期：2026-10-14 ｜ 状态：R3-0 冻结 ｜ 基线 HEAD：`dac556a`
> 能力分级：A=源码已见端点；B=前端已接仍需联调；C=未核实或后端缺口。A/B 均不代表真实外部平台接通。

---

## 1. 我的生意（/app 入口）

### 1.1 经营首页 `/app`（WorkspaceHome.vue）

| 数据块 | 读 API | 请求参数 | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 概览 partial/error | `GET /workbench/overview` | `limit` | 当前空间 | VERIFIED（BFF 聚合） | A |
| 进行中上线 | overview.sections.in_progress | — | 当前空间 | VERIFIED | B |
| 指标（近 30 天） | overview.sections.metrics | — | 财务读 | ESTIMATED（销售/广告分列） | B |
| 跨域待办 | overview.sections（launch/action/alert/review） | — | 当前空间 | VERIFIED | B |
| 人工介入 | overview.sections.need_human | — | 审批权 | VERIFIED | B |
| AI 完成 | overview.sections.ai_done | — | 当前空间 | VERIFIED（近 24h） | B |
| 异常 | overview.sections.exceptions | — | 当前空间 | VERIFIED | B |

**异常处理**：`partial=true` 时 `PartialBanner` 明示缺源；`error` 时 `ErrorState` 重试；各 SectionState 11 态独立。

### 1.2 我的待办 `/app/tasks`（TaskCenter.vue）

| 数据块 | 读 API | 请求参数 | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 待办聚合 | `GET /workbench/todo` | `limit`, `includeHistory` | 当前空间 | VERIFIED | A |

**写操作**：无（只读聚合；任务处理跳转对象页）。

---

## 2. 我的商品（路由映射）

### 2.1 商品库 `/app/products`（Products.vue）

| 数据块 | 读/写 API | 请求参数 | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 商品列表 | `GET /products` | `page/keyword/source` | 当前空间 | VERIFIED | A |
| 新建 | `POST /products` | 全量 body | 可写 | VERIFIED | A |
| 更新 | `PUT /products/{id}` | 部分字段 | 可写 | VERIFIED | A |
| URL 采集 | `POST /products/collect_url` | `url` | 可写 | OBSERVED（外部抓取） | B |
| HTML 采集 | `POST /products/collect_html` | `url/html` | 可写 | OBSERVED | B |
| 演示采集 | `POST /products/collect` | `sourcePlatform/keyword/count` | 可写 | DEMO | C |
| 导出 | `GET /products/export` | — | 读 | VERIFIED | A |
| 标准化 | `POST /products/{id}/standardize` | — | 可写 | VERIFIED | A |

### 2.2 商品详情 `/app/products/:id`（ProductDetail.vue）

| 数据块 | 读/写 API | 请求参数 | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 商品主体 | `GET /products/{id}` | — | 读 | VERIFIED | A |
| 重新标准化 | `POST /products/{id}/standardize` | — | 可写（canWrite） | VERIFIED | A |
| 渠道（只读） | `GET /products/{id}/channels` | — | 读 | **E01：后端返回 channels，前端读 items，需坐实** | B |
| 素材列表 | `GET /products/{id}/assets` | **E02：缺 shop_id** | 读 | OBSERVED | B |
| 新增素材 | `POST /products/{id}/assets` | **E03：字段不完整** | 可写 | VERIFIED（需完整登记） | B |
| 素材核验 | `POST /products/{id}/assets/{assetId}/verify` | **E04：无 body** | 核验权（独立） | VERIFIED | B |

### 2.3 上线中心 `/app/launch`（LaunchCenter.vue）

| 数据块 | 读/写 API | 请求参数 | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 上线列表 | `GET /launch` | `page/filters/view` | 当前空间 | VERIFIED | A |
| 创建 | `POST /launch` | 商品+店铺 | 可写 | VERIFIED | A |
| 详情 | `GET /launch/{id}` | — | 读 | VERIFIED | A |
| 步骤动作 | `POST /launch/{id}/actions/{action}` | `payload` | **E10：按动作权限** | VERIFIED | B |
| 同步 | `POST /launch/{id}/sync` | `expectedRevision` | 可写 | VERIFIED（乐观锁） | A |

### 2.4 Listing 工作台 `/app/listings`（Listings.vue）

| 数据块 | 读/写 API | 请求参数 | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 列表 | `GET /listings` | `page/status/platform/productId` | 读 | VERIFIED | A |
| 详情 | `GET /listings/{id}` | — | 读 | VERIFIED | A |
| 发布回执 | `GET /listings/{id}/publication-attempts` | — | 读 | VERIFIED（区分 SUBMITTED/在售） | A |
| 生成 | `POST /listings/generate` | — | 可写 | ESTIMATED | B |
| 提交审核 | `POST /listings/{id}/review` | — | 可写 | VERIFIED | A |
| 批准 | `POST /listings/{id}/review/approve` | `note` | 审批权 | VERIFIED | A |
| 发布 | `POST /listings/{id}/publish` | `shop_id` | 可写 | VERIFIED | A |
| 删除 | `DELETE /listings/{id}` | — | Owner | VERIFIED | A |

### 2.5 店铺管理 `/app/channels/shops`（Shops.vue）

| 数据块 | 读/写 API | 请求参数 | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 店铺列表 | `GET /shops` | params | 读 | VERIFIED | A |
| 创建 | `POST /shops` | — | 可写 | VERIFIED | A |
| 授权 | `GET /shops/{id}/authorize_url` | — | 可写 | OBSERVED（外部 OAuth） | B |
| 刷新 | `POST /shops/{id}/refresh` | — | 可写 | OBSERVED | B |
| 同步订单 | `POST /shops/{id}/sync_orders` | — | 可写 | OBSERVED | B |
| 上架就绪 | `GET /shops/{shopId}/listing_readiness/{listingId}` | — | 读 | VERIFIED | A |

---

## 3. 我的订单（路由映射）

| 页面 | 读 API | 写 API | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 订单工作台 `/app/orders` | `GET /orders`（page/status/shopId/platform/keyword） | `PUT /orders/{id}/status`、`POST /orders/{id}/ship`、`POST /orders/import`、`POST /orders/sync` | 读/可写 | VERIFIED / 同步 OBSERVED | A/B |
| 发货备货 `/app/fulfillment` | fulfillment 相关 | 见 API 域 | 可写 | VERIFIED | A |
| 售后退款 `/app/refunds` | `GET /refunds`、`GET /refunds/{id}` | `POST /refunds`、`PUT /refunds/{id}/status`、`POST /refunds/{id}/return_receive`、`POST /refunds/{id}/refund` | 读/可写 | VERIFIED | A |
| 客户消息 `/app/support` | `GET /support/conversations` | `POST /support/conversations/{id}/reply`、`auto_reply`、`close` | 读/可写 | VERIFIED | A |
| 结算对账 `/app/settlements` | `GET /settlements`、`/settlements/summary` | `POST /settlements/generate`、`PUT /settlements/{id}` | 读/可写 | VERIFIED | A |

---

## 4. 我的收益（路由映射）

| 页面 | 读 API | 写 API | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| BI 总览 `/app/analytics/bi` | `GET /bi/metrics`、`/bi/data-quality`、`/bi/profit`、`/bi/dashboard`、`/bi/report` | — | 财务读 | ESTIMATED（周期/币种需标注） | B |
| 真实利润 `/app/analytics/finance` | finance 域 | — | 财务读 | VERIFIED | A |
| 到岸成本 `/app/analytics/landed-cost` | landed-cost 域 | — | 财务读 | VERIFIED | A |
| 预测 `/app/analytics/forecast` | `GET /suppliers/forecast` | — | ESTIMATED | C |
| 定价试算 `/app/pricing` | `GET /pricing`、`POST /pricing/calc`、`POST /pricing/suggest` | calc 只分析 | VERIFIED（估算标注） | A/B |

> 收益域金额一律带币种，百分比带分母和周期；估算标 ESTIMATED，缺失用「—/尚未获得」，不得当零。

---

## 5. 全部工具（专业工具柜）

| 工具 | 读 API | 写 API | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 货源发现 `/app/supply/sourcing` | sourcing 域 | — | 读 | VERIFIED | A |
| 供应商库 `/app/supply/suppliers` | `GET /suppliers`、`/suppliers/{id}`、`/suppliers/offers`、`/suppliers/match`、`/suppliers/forecast` | `POST /suppliers`、`POST /suppliers/{id}/score` | 读/可写 | VERIFIED | A |
| 货源匹配 `/app/supply/matching` | `POST /suppliers/match` | — | 读 | VERIFIED | A |
| 采购单 `/app/supply/purchases` | `GET /purchases` | `POST /purchases`、`POST /purchases/dropship` | 可写 | VERIFIED | A |
| 广告 `/app/ads` | `GET /ads/campaigns`、`POST /ads/suggest` | `POST /ads/campaigns`、`/ads/campaigns/{id}/optimize` | 可写 | VERIFIED | A |
| 诊断 `/app/risk/alerts` | `GET /alerts`、`/alerts/rules` | `PUT /alerts/{id}/ack`、`PUT /alerts/rules/{id}`、`POST /alerts/scan` | 可写 | VERIFIED | A |
| 策略实验 `/app/optimization/experiments` | — | — | — | **stub，后端缺口** | C |
| AI 行动中心 `/app/ai/actions` | `GET /actions`（status/type/page） | `POST /actions/{id}/approve`、`/actions/{id}/reject`、`/actions/{id}/execute` | 审批/可写 | VERIFIED | A |
| AI 工作流 `/app/ai/workflows` | workflows 域 | — | 读 | VERIFIED | A |
| Agent 运行 `/app/ai/agent-runs` | — | — | Owner | **stub，后端缺口** | C |
| 知识库 `/app/ai/knowledge` | `GET /ai/decisions`、`/ai/logs` | `POST /ai/chat` | 读 | VERIFIED | A |
| 决策依据 `/app/ai/decisions` | `GET /ai/decisions` | — | 读 | VERIFIED | A |
| 空间信息 `/app/settings/workspace` | settings 域 | — | Owner | VERIFIED | A |
| AI 设置 `/app/settings/ai` | `GET /ai/settings` | `PUT /ai/settings` | Owner | VERIFIED | A |
| 用户角色 `/app/settings/team` | users 域 | — | Owner | VERIFIED | A |
| 凭据管理 `/app/settings/credentials` | credentials 域 | — | Owner | VERIFIED | A |
| 套餐管理 `/app/settings/plan` | — | — | Owner | **stub，移出导航** | C |

---

## 6. 工厂门户（独立）

| 页面 | 读 API | 写 API | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 工厂首页 `/factory` | factory_network 域（投影） | — | FACTORY_COLLABORATOR | VERIFIED（仅自身相关） | A |
| 产品与产能 `/factory/products` | factory 投影 | — | 工厂 | VERIFIED | A |
| 备货贴标 `/factory/stocking` | 备货任务 | 上传实物/备货证据 | 工厂 | VERIFIED | A |
| 工厂履约 `/factory/fulfillment` | 履约历史 | — | 工厂 | VERIFIED | A |
| 报价能力 `/factory/capability` | 供货能力 | — | 工厂 | VERIFIED | A |

> 工厂门户**不得**暴露销售利润、全店铺数据或通用 Launch 管理；无任务 API 时明示缺口，不借商家接口扩大范围。

---

## 7. 平台控制台（独立）

| 页面 | 读 API | 写 API | 权限 | 可信度 | 状态 |
|---|---|---|---|---|---|
| 平台总览 `/console/overview` | admin 域 | — | PLATFORM_ADMIN | VERIFIED | A |
| 租户管理 `/console/tenants` | `GET /admin/tenants` | 租户 CRUD | PLATFORM_ADMIN | VERIFIED | A |
| 访问审计 `/console/audit` | audit 域 | — | PLATFORM_ADMIN | VERIFIED（代客身份持续可见） | A |
| 维护 `/console/maintenance` | maintenance | — | PLATFORM_ADMIN | VERIFIED | A |
| Adapter 认证 `/console/adapters` | adapters | — | PLATFORM_ADMIN | VERIFIED | A |
| 数据源规则 `/console/rules` | rules | — | PLATFORM_ADMIN | VERIFIED | A |
| AI 资源 `/console/ai-resources` | ai-resources | — | PLATFORM_ADMIN | VERIFIED | A |

---

## 8. 数据可信度四轴分离（R3 渲染规则）

| 轴 | 取值 | 渲染 |
|---|---|---|
| 页面加载状态 | LOADING / ERROR / READY | SectionState 11 态 |
| 业务流程状态 | draft / in_progress / blocked / done | BusinessStatus（不单靠颜色） |
| 外部平台状态 | SUBMITTED / ACTIVE / VERIFIED | 提交≠在售，明示 |
| 数据可信度 | VERIFIED / OBSERVED / ESTIMATED / MISSING / DEMO | 8 类数据标签 |

- 错误不得当空、未知不得当零、提交不得当在售、建议不得当执行、未授权不得当已接入。
- 金额带币种，百分比带分母周期，估算标 ESTIMATED，缺失标「—/尚未获得」。

