# 前端 API 契约对齐（FRONTEND_API_ALIGNMENT）

> 最后更新：2026-10-13
> 状态：FROZEN_FOR_IMPLEMENTATION（UX-00 蓝图；冻结口径 v1.0）
> 维护者：架构师
> 上位依据：`docs/CONTRACT.md`、`docs/FRONTEND_UX_PROGRESS.md` §0.7
> 范围：11 业务域「前端实际调用 vs 后端实际提供」对照、未接通动作边界、BFF 只读聚合方案

---

## 0. 红线（不得违反）

1. **复用现有 API**：前端只调用后端已存在端点，**禁止重复 Service**。
2. **BFF 仅只读聚合**：新增 `/workbench/*` 只做读聚合，**不新增写端点、不写库**。
3. **未接通能力显式**：B03–B09 动作显式展示「未接入 + 原因」，**禁止伪造成功**、**禁止只有 409 的按钮**。

---

## 1. 11 业务域端点对照

标注：✅ 已对齐 / ⚠️ 后端有前端未用 / ❌ 前端调但后端无 / 🧩 需新增只读聚合(BFF)。「前端调用」来自 `frontend/src` 内请求路径；「后端提供」来自 `backend/app/routers/`。

| # | 业务域 | 前端实际调用（节选） | 后端实际提供 | 结论 |
|---|---|---|---|---|
| 1 | 身份/工作区/平台 | /auth/login、/auth/users(CRUD)、/me/workspace-context、/me/workspaces、/admin/{overview,tenants,access_logs,ai_logs}、/admin/tenants/{id}/enter | `backend/app/routers/auth.py`、`backend/app/routers/me.py`、`backend/app/routers/admin.py` | ✅；⚠️ `/auth/me` 前端未用（改用 Context）；⚠️ `/me/workspaces/{id}/switch` 后端有（`backend/app/routers/me.py:87`）但**前端无 UI 入口** |
| 2 | 商品发现/商品池 | /products(GET/POST/PUT/DELETE/detail/export/collect/collect_url/collect_html/{id}/standardize)、/discovery(trends、trends/scan、trends/import、trends/source、expand、pick、scores、performance/{id}) | `backend/app/routers/products.py`、`backend/app/routers/discovery.py` | ✅；⚠️ 后端有前端未用：/products/{id}/channels（`backend/app/routers/product_channels.py:20`）、/products/{id}/assets 与其 verify（`backend/app/routers/product_assets.py:43-65`）、/discovery/score/{id}(POST)（`backend/app/routers/discovery.py:45`） |
| 3 | 供应商/采购 | /suppliers(GET/POST/PUT/{id}/score/{id}/forecast)、/purchases(dropship、from_forecast、POST、GET、PUT、receive、DELETE) | `backend/app/routers/suppliers.py`、`backend/app/routers/purchases.py` | ✅；⚠️ /suppliers/match（`backend/app/routers/suppliers.py:80`）、/suppliers/offers（`backend/app/routers/suppliers.py:111,134`）未用 |
| 4 | 工厂协同 | /factory-network/portal/{me,products}、/opportunities/match、/opportunities、/matches/{id}/promote、/suppliers/{id}/{verification,portal-account} | `backend/app/routers/factory_network.py` | ✅；⚠️ /factory-network/opportunity-attribution（`backend/app/routers/factory_network.py:279`）未用 |
| 5 | Listing/发布审批 | /listings(GET、generate、PUT、optimize、review、review-queue、review/approve、publish、DELETE、publication-attempts)、/actions(GET、approve、reject、execute)、/shops/{id}/listing_readiness/{lid} | `backend/app/routers/listings.py`、`backend/app/routers/actions.py`、`backend/app/routers/shops.py` | ✅ |
| 6 | 合规 | /compliance/reports、/compliance/check、/listings/review-queue、/listings/{id}/review(/approve)、/shops/platform_rules | `backend/app/routers/compliance.py`、`backend/app/routers/listings.py` | ✅；⚠️ /compliance/reports/{id}（`backend/app/routers/compliance.py:49`）未用 |
| 7 | 上线中心 Launch | /launch/context、/launch(list)、/launch/{id}、/{id}/steps、/{id}/events、/{id}/actions/{action}、/{id}/sync | `backend/app/routers/launch.py`（八端点：74/83/102/123/133/143/160/178） | ✅ 全对齐 |
| 8 | 定价/跨境成本 | /pricing(GET、calc、suggest)、/workflows/run(reprice) | `backend/app/routers/pricing.py`、`backend/app/routers/cross_border.py` | ✅ 局部；⚠️ **`backend/app/routers/cross_border.py` 全部端点前端零调用**（duty-rates / logistics-routes / platform-fees / compliance-rules / products/{id}/compliance / landed-cost）；前端 /pricing/calc 未传 destination_country → 与 D58 到岸成本能力不对齐 |
| 9 | 订单/售后/结算 | /orders(GET、import、export、status、ship)、/shops/{id}/sync_orders、/refunds(GET、POST、status、return_receive、refund)、/settlements(GET、generate、summary、PUT) | `backend/app/routers/orders.py`、`backend/app/routers/refunds.py`、`backend/app/routers/settlements.py` | ✅ |
| 10 | 财务 | /finance/fx(GET/POST)、/finance/orders/{id}/{detail,lines,fees}、/finance/settlement-reconciliation、/finance/platform-settlements | `backend/app/routers/finance.py` | ✅ |
| 11 | 增长与 AI | /ads(campaigns GET/POST/optimize/suggest)、/bi(dashboard、metrics、data-quality、profit、report)、/alerts(GET、rules、scan、ack)、/support(conversations…)、/workflows(templates、runs、run、resume)、/schedules(CRUD/run)、/knowledge(docs、search、candidates、learning)、/ai(chat、settings、logs、decisions) | `backend/app/routers/ads.py`、`backend/app/routers/bi.py`、`backend/app/routers/alerts.py`、`backend/app/routers/support.py`、`backend/app/routers/workflows.py`、`backend/app/routers/schedules.py`、`backend/app/routers/knowledge.py`、`backend/app/routers/ai.py` | ✅；⚠️ /bi/forecast-monitoring、/bi/forecast-outcomes（`backend/app/routers/bi.py:30,35`）未用 |

**❗前端在调但后端无**：本轮对照**未发现**（现有前端调用均可落到后端某 router）。若后续发现，必须在此登记为 ❌ 并阻断合并。

---

## 2. 未接通动作的真实边界（7 组）

权威源：`backend/app/workflows/launch_action_catalog.py:103-144` 的 BUSINESS_ACTION_META；`connected=False` 者执行即 **409 ACTION_NOT_ALLOWED**（`backend/app/workflows/launch_actions.py:84-86`；未注册动作见 `backend/app/workflows/launch_action_catalog.py:147-152`）。前端已展示禁用动作并附原因：`frontend/src/components/LaunchStepPanel.vue:47-53`（不可执行者置灰 + disabled_reason，数据来自 `backend/app/workflows/launch_nba.py:144-145`）。

| 组 | 动作 | 后端状态 | 证据 |
|---|---|---|---|
| 核价 | REPORT_PRICE | 未接通（永远 409） | `backend/app/workflows/launch_action_catalog.py:122-123`、DISABLED_PRICE:33 |
| 价格决策 | ACCEPT_PRICE / COUNTER_PRICE | 未接通 | `backend/app/workflows/launch_action_catalog.py:124-127` |
| 平台备货 | REQUEST_STOCK / CONFIRM_STOCK | 未接通 | `backend/app/workflows/launch_action_catalog.py:128-131`、DISABLED_STOCK:34 |
| 合规 Artifact | UPLOAD_ARTIFACT / VERIFY_ARTIFACT | 未接通 | `backend/app/workflows/launch_action_catalog.py:132-135`、DISABLED_COMPLIANCE:35 |
| 标签 | GENERATE_LABEL / REGENERATE_LABEL | 未接通 | `backend/app/workflows/launch_action_catalog.py:136-139`、DISABLED_LABEL:36 |
| 实拍材料 | UPLOAD_PHYSICAL_EVIDENCE / VERIFY_EVIDENCE | 未接通 | `backend/app/workflows/launch_action_catalog.py:140-143`、DISABLED_EVIDENCE:37 |
| 外部状态确认 | CONFIRM_ACTIVATION | **已接通**，external_confirmer=True（依赖外部核验，属 WAITING_EXTERNAL） | `backend/app/workflows/launch_action_catalog.py:112-114`；需 launch:submit + compliance:approve |

已接通（P0）：COMPLETE_DATA、SUBMIT_PLATFORM、CONFIRM_ACTIVATION、RETRY、CANCEL、ABANDON_PRODUCT（`backend/app/workflows/launch_action_catalog.py:105-120`）。

**前端处置原则**：禁用动作以 NotConfiguredState / WaitingExternalState 呈现（见 `docs/FRONTEND_DESIGN_SYSTEM.md` §3），禁止伪造为可用。

---

## 3. BFF 只读聚合方案

### 3.1 GET /workbench/todo（跨域待办，只读）
- 聚合来源（复用现有端点，不重复 Service）：Launch「需我处理」`/launch?mine=true`（`backend/app/routers/launch.py:102`）、发布审批 `/actions?action_type=PUBLISH_LISTING&status=PENDING_APPROVAL`（`backend/app/routers/actions.py:49`）、告警 `/alerts?status=open`（`backend/app/routers/alerts.py:21`）、复核队列 `/listings/review-queue`（`backend/app/routers/listings.py:156`）。
- 返回：`{ items:[{domain,title,count,next_action,ref}], counts:{...} }`；只读，不写库。
- 前端消费：首页「今天最重要」+ 各域入口角标（替代 `frontend/src/components/PublishActions.vue`、`frontend/src/views/LaunchCenter.vue`、`frontend/src/views/Alerts.vue:128` 各自拼装）。

### 3.2 GET /workbench/overview（首页 6 问，只读）
- 聚合来源：`/bi/dashboard`（`backend/app/routers/bi.py:55`）+ `/workbench/todo` + Launch 汇总（`/launch`）。
- 返回：回答 6 问（在做什么 / 进展如何 / 今天最重要 / 哪些要人工 / AI 完成了什么 / 哪些异常）+ 下一步动作。
- 与 `/bi/dashboard` 的关系：overview 是**只读聚合层**，内部转调既有服务，不复制口径（遵守红线 1）。

### 3.3 归属与验收
- 后端 BFF 归 UX-05 前置任务，路由归 `backend/app/routers/`（新增 workbench 模块）；需带后端测试（`backend/tests/`）。
- 前端消费归 UX-03 / UX-04。

---

## 4. 前端调用点索引（便于回归）

| 调用点（前端） | 端点 | 对齐 |
|---|---|---|
| `frontend/src/workspace.js`（`loadWorkspaceContext()`） | GET /me/workspace-context | ✅ |
| `frontend/src/workspace.js`（`switchWorkspace()`） | POST /me/workspaces/{id}/switch | ✅（无 UI） |
| `frontend/src/workspace.js`（`loadWorkspaces()`） | GET /me/workspaces | ✅（无 UI） |
| `frontend/src/composables/launchCenter.js`（数据层 `loadContext`/`listLaunches`/`loadDetail`/`loadSteps`/`loadEvents`/`executeAction`/`syncLaunch`） | /launch/* 八端点 | ✅ |
| `frontend/src/composables/publishActionQueue.js:11,21,32` | /actions | ✅ |
| `frontend/src/composables/publicationReceipts.js:7` | /shops/{id}/submissions/{ext} | ✅ |
| `frontend/src/views/Discovery.vue`（多处） | /discovery/* | ✅ |
| `frontend/src/views/Pricing.vue:88,96` | /pricing/calc、/pricing/suggest | ✅（未传 destination_country） |
| `frontend/src/views/Orders.vue:104,120,131,141,150,164` | /orders/*、/shops/{id}/sync_orders | ✅ |
