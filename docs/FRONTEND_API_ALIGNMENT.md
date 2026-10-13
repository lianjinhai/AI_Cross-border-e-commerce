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
| 8 | 定价/跨境成本 | /pricing(GET、calc、suggest)、/workflows/run(reprice) | `backend/app/routers/pricing.py`、`backend/app/routers/cross_border.py` | ✅ 局部；⚠️ **`backend/app/routers/cross_border.py` 全部端点前端零调用**（duty-rates / logistics-routes / platform-fees / compliance-rules / products/{id}/compliance / landed-cost）；**Pricing 结论（UX-04 只读核查）**：`/pricing/calc` 后端**已支持** `destination_country`（`backend/app/routers/pricing.py` 的 `CalcIn.destination_country`，透传给 `PricingAgent.calc_profit`），前端只需**纯前端接线**（在 `frontend/src/views/Pricing.vue` 调用里透传该字段，可选 `channel_type`/`site`/`qty`），**无需后端改动**；D58 到岸口径另有只读 `POST /cross-border/landed-cost`（同 `services/costing.calc_profit`）可作对齐校验 |
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

## 3. BFF 只读聚合契约（FROZEN，UX-04 前置）

> 两个只读端点：`GET /api/workbench/todo`、`GET /api/workbench/overview`。契约为 UX-04 实施冻结基线（当前 **v1.2**，变更记录见 §3.4），实施者不得改语义；如需变更须经架构师更新本节。

### 3.0 通用约定（两端点共守）

- **只读红线**：仅 SELECT；**不写库、不新增表/迁移、不新增写端点**。
- **复用（不重复 Service）**：聚合实现落新建 backend/app/services/workbench.py，**只组合既有 `services/`、`workflows/` 函数**，禁止在 workbench 模块重写查询 SQL。若某源当前仅有 router 内联查询，实施时**把该查询抽到对应 `services/` 模块**（单一实现），router 与 BFF 共用。
- **鉴权**：按 Workspace Context 逐 key 判定（权威源 `backend/app/services/workspace_context.py` 的 `ROLE_PERMISSIONS`）。未持有某源读权限的调用者，该源**从结果剔除并记 `skipped`**（不报错）。
- **角色投影**：`COMPLIANCE` 角色**剥离价格/库存类动作**（复用 `backend/app/workflows/launch_action_catalog.py` 的 `PRICE_STOCK_ACTIONS` 与 `launch_nba` 既有投影规则，**不新造一套**）；`FACTORY_COLLABORATOR` **不得拿到任何租户侧待办**（`items` 为空、`sources` 全 `skipped`）。
- **错误信封**：与全站一致——失败以 `HTTPException.detail` 对象返回，前端 `frontend/src/api.js:31` 取 `detail.message`；**单源失败不得整体 5xx**。
- **降级语义**：任一源失败 → 端点仍 **200**，`partial=true`，`sources[<源>]='failed'`，对应 section 缺省；前端据此走 **`PARTIAL_DATA`** 态（frontend/src/components/PartialDataBanner.vue），而非整页报错。
- **时间**：`generated_at` 为 ISO 8601 UTC。

### 3.1 GET /api/workbench/todo（跨域待办，只读）

- **路由**：新建 backend/app/routers/workbench.py（`APIRouter(prefix="/workbench")`），在 `backend/app/main.py`（`backend/app/main.py:16-46` 的 import 与 `backend/app/main.py:84-88` 的注册元组）注册，随 `prefix="/api"` → 实际路径 `/api/workbench/todo`。
- **查询参数**：`limit: int = 50`（0<limit≤200，逐源上限）、`include_history: bool = false`（透传 Launch 源）。
- **鉴权（逐源）**：Launch 待办 → `launch:read`；待审批 Action → 复用 `backend/app/services/action_identity.py` 的 `require_action_permission`（`PUBLISH_LISTING` 的权限）；告警 → `ai:read`（`backend/app/services/alerting.py` 既有语义）；Listing 复核队列 → `compliance:check`/`compliance:approve`（与 `frontend/src/permissions.js` 的 APPROVER 语义同源）。
- **响应 schema**：

```
{
  "items": [
    {
      "type": "launch|action|alert|review",     // 待办类别
      "title": string,                           // 展示标题（业务语言 / GUIDED 口径）
      "count": int,                              // 该类待办数量（来自既有源函数，如 list_launches 的 total）
      "severity": "low|mid|high",                // 由既有状态/风险字段映射，不新造口径（= PM 首页设计的 priority）
      "due_at": string|null,                     // ISO 8601 UTC；源无截止语义时为 null（§3.4 裁决追加）
      "route": { "path": string, "return_to": string|null },  // 目标路由；return_to 必须通过 RETURN_WHITELIST（= PM 的 target_url，但改携带白名单校验）
      "ref": string|null                         // 深链接引用（如 /launch/:id、Action#id），可空
    }
  ],
  "counts": { "launch": int, "action": int, "alert": int, "review": int },
  "generated_at": "2026-10-13T00:00:00Z",
  "partial": bool,
  "sources": { "launch": "ok|failed|skipped", "action": "...", "alert": "...", "review": "..." }
}
```

- `route.return_to` 仅当目标属于 `RETURN_WHITELIST`（`frontend/src/utils/navigationReturn.js` 的 `['/launch','/listings','/products','/shops']`）时给出，否则 `null`；前端消费时再经 `isSafeReturnTo()` 二次校验。
- **数据来源（复用，不重复 Service）**：Launch → `backend/app/workflows/launch_list.py` 的 `list_launches`（`mine`/`blocked_only`/`waiting_platform`）；Action 待批 → `services.action_identity.require_action_permission` + `services.store_scope.resolve_store_scope` + `services.ai_actions.action_dict`；告警 → `services.alerting.list_alerts`（status=open）；复核队列 → 现由 `backend/app/routers/listings.py:156` 内联，实施时抽到 `services/`（单一实现）。
- **前端消费**：首页「今天最重要」+ 各域入口角标（替代 `frontend/src/components/PublishActions.vue`、`frontend/src/views/LaunchCenter.vue`、`frontend/src/views/Alerts.vue:128` 各自拼装）。

### 3.2 GET /api/workbench/overview（首页 6 问，只读）

- **路由/方法**：同 workbench 模块。
- **鉴权**：登录用户；BI 相关段沿用 `/bi` 既有读权限（`finance:read`），待办段按 §3.1 逐源判定。
- **响应 schema**：

```
{
  "sections": {
    "metrics":     { gmv, orders, contribution_profit, net_revenue, refund_rate,
                     ad_spend, roi, metric_scope, currency },       // 复用 /bi/dashboard 字段名（不新建口径）
    "in_progress": [ { id, product, store, execution_status,
                       progress:{ completed, total }, next_action, market } ],  // 投影 list_launches(mine=true)
    "top_today":   [ { <todo item> } ],                             // 复用 §3.1 items
    "need_human":  { "count": int },                                 // 审批/复核类待办计数（前端按 items.type 过滤派生）
    "ai_done":     { "count": int, "items": [ { id, title, status, finished_at } ] }, // 投影 /workflows/runs 近 24h success
    "exceptions":  { "items": [ { <alert> } ], "total": int, "counts": {...} }        // 复用 /alerts 响应字段
  },
  "data_quality": { grade, commercial_ready, freshness_hours, real_order_count },     // 复用 /bi/data-quality
  "signals": {                                             // 只读派生信号（derived:true, authoritative:false；见 §3.4）
    "has_sales_shop": bool|null, "sales_shop_count": int|null,
    "has_factory": bool|null, "factory_match_count": int|null,
    "has_1688_credential": bool|null,                      // 仅存在性；绝不含密钥值
    "member_count": int|null, "order_count_30d": int|null
  },
  "next_actions": [ { <todo item> } ],
  "generated_at": "...",
  "partial": bool,
  "sources": { "bi": "ok|failed", "launch": "...", "alert": "...", "review": "...", "workflow": "...", "todo": "..." }
}
```

**6 问 → section 映射（冻结）**：

| 6 问 | section key | 数据源（复用，不新造口径） |
|------|-------------|---------------------------|
| 在做什么 | `in_progress` | `backend/app/workflows/launch_list.py` 的 `list_launches(mine=True)` |
| 进展如何 | `metrics` | `backend/app/services/commercial_analytics.py` 的 `metric_summary`（与 `/bi/dashboard` 同源，`backend/app/routers/bi.py:55`） |
| 今天最重要 | `top_today` | §3.1 `/workbench/todo` |
| 哪些要人工 | `need_human` | §3.1 `approvals` |
| AI 完成了什么 | `ai_done` | `backend/app/routers/workflows.py` 的 `/workflows/runs`（近 24h `status=success`） |
| 哪些异常 | `exceptions` | `backend/app/services/alerting.py` 的 `list_alerts`（复用 `/alerts` 响应字段） |

overview 是**只读聚合层**，内部转调既有服务，**不复制口径**（红线 1）。

### 3.3 归属与验收

- 归 **UX-04 前置（后端 BFF）**：路由 backend/app/routers/workbench.py、聚合 backend/app/services/workbench.py、在 `backend/app/main.py` 注册、同步 `docs/CONTRACT.md` §5 路由层契约。
- 后端测试：`backend/tests/`，至少覆盖「单源失败 → `partial=true` 且 200」「COMPLIANCE 投影剥离价格/库存动作」「FACTORY_COLLABORATOR 空待办」「只读（无写库调用）」。
- 前端消费归 UX-04：frontend/src/composables/workbenchTodo.js。

### 3.4 对齐 PM 首页设计 + 裁决变更（v1.2）

来源：`docs/FRONTEND_USER_JOURNEYS.md §五`（PM 的 6 问 × 角色数据来源表）。

**v1.2 相对 v1.1 的变更（team-lead 裁决）**：
1. `overview` 新增只读派生块 `signals`；**A/B/C/D/F 画像判定移到前端纯函数**（后端不出 persona 标签）。
2. **撤回 `todo.approvals[]`**：审批类待办可由 `items` 按 `type==='action'` 派生，保留会造成**双事实源**（违反「同一能力只有一套」）。
3. `todo.items[].due_at` **保留**（真数据）。

**字段对齐表（v1.1 沿用；`approvals` 行已撤回）**：

| PM 期望命名 | 契约采纳 | 说明 |
|-------------|----------|------|
| `metrics` | ✅ `sections.metrics` | 字段名沿用 `/bi/dashboard` 实际响应（`metric_scope`/`currency` 源自 `metric_summary` 的 `scope`/`currency`） |
| `inProgress[]` | ✅ `sections.in_progress` | `{id,product,store,execution_status,progress,next_action,market}` 确为 `launch_dto.launch_list_item` 既有输出 |
| `alerts` | ✅ 并入 `sections.exceptions` | 复用 `/alerts` 响应 `{items,total,counts}` |
| `quality` | ✅ 顶层 `data_quality` | 复用 `/bi/data-quality`（**无 `realness`**，实为 `real_order_count` + `source_counts`） |
| `aiDone[]` | ✅ `sections.ai_done` | 投影 `/workflows/runs` 近 24h `status=success` |
| `todo.items[].target_url` | ⚠️ 改 `route:{path,return_to}` | `return_to` 须过 `RETURN_WHITELIST`；前端取 `route.path` |
| `todo.items[].priority` | ⚠️ 归一为 `severity` | 语义等价，保留 `severity` 以稳信封 |
| `todo.items[].due_at` | ✅ 保留（可空） | 真数据 |
| `todo.approvals[]` | ❌ **撤回** | 前端按 `items.type` 过滤派生，避免双事实源 |
| `persona` | ⤵️ 改为 `signals` | 见下 |

**`signals` 契约（裁决 1：只读派生，`derived:true, authoritative:false`）**：

| 键 | 类型 | 含义 / 复用来源 |
|----|------|-----------------|
| `has_sales_shop` | bool\|null | 是否存在销售店铺（`Shop.role=='sales'` 且未归档）；复用 `backend/app/services/shop_scope.py` |
| `sales_shop_count` | int\|null | 销售店铺数（同上） |
| `has_factory` | bool\|null | 是否存在源头工厂（`Supplier`）；复用 `backend/app/routers/factory_network.py` 的既有查询（实施时抽到 `services/` 单一实现） |
| `factory_match_count` | int\|null | 工厂机会匹配数（`OpportunitySupplierMatch`）；同上 |
| `has_1688_credential` | bool\|null | 是否存在已授权 1688 货源店铺（`Shop.platform=='1688'`）；**仅存在性，绝不含密钥值**（`backend/app/services/open_1688.py` 的 app_secret 一律不得外泄） |
| `member_count` | int\|null | 当前租户/Workspace 有效成员数；复用 `backend/app/services/membership_service.py` 与 `backend/app/services/workspace_context.py` 的 `_load_active_membership` |
| `order_count_30d` | int\|null | 近 30 天订单数；复用 `backend/app/services/commercial_analytics.py` 的 `metric_summary(...)["orders"]` |

- **只读红线**：`signals` 全部由既有 `services/` 组合得出，只读；**不建表、不新增写路径、不复制 SQL**。
- **失败/无权限语义**：某源无权限或不可得 → 对应键为 `null`，端点 `partial=true`；**不得猜测、不得默认填值**（严格区分「否」与「未知」）。
- **前端归属**：A/B/C/D/F 画像**不在后端产出**；由 frontend/src/composables/workbenchTodo.js（待创建）的纯函数 `resolvePersona(signals)` 判定（可单测），信号不足时回落「通用工作台」。`signal → persona` 规则写入 `docs/FRONTEND_USER_JOURNEYS.md`（PM 域）。
- **权威性声明**：`signals` 仅为**过渡**依据。**权威画像应由用户自述的 `capability_profile`/`business_stage` 承载**——`AGENTS.md` §8（`AGENTS.md:122`）的 Context 契约已声明该字段但**尚未实现**，属首用引导缺口（G1，team-lead 记 UX-D10）。故 `signals` **不得当权威**，不得用于权限或合规判定。

> 契约版本：v1.0（初版）→ v1.1（对齐 PM 命名）→ **v1.2（`signals` 取代 `persona`；撤回 `approvals[]`；保留 `due_at`）**。语义与信封始终不变；最终以 team-lead 裁决为准。

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
| `frontend/src/views/Pricing.vue:88,96` | /pricing/calc、/pricing/suggest | ✅（后端已支持 destination_country，UX-04 待前端透传） |
| `frontend/src/views/Orders.vue:104,120,131,141,150,164` | /orders/*、/shops/{id}/sync_orders | ✅ |
