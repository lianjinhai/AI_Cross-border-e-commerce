# 前端 R3 页面所有权矩阵（FRONTEND_R3_PAGE_OWNERSHIP_MATRIX）

> 日期：2026-10-14 ｜ 状态：R3-0 冻结 ｜ 基线 HEAD：`dac556a`（V9 蓝图 R1 全站前端补齐）
> 工作区含未提交增量（workbench WIP 他人代码），本矩阵基于**当前实际代码**，不重置、不覆盖、不混入提交。
> R3 目标：将 8 域 40+ 菜单项收敛为 **4+1 入口** + 专业工具柜 + 独立门户，任务驱动而非菜单驱动。

---

## 1. R3 导航原则

| 原则 | 说明 |
|---|---|
| 默认 5 入口 | 我的生意 / 我的商品 / 我的订单 / 我的收益 / 全部工具；替代 8 域 26 个侧栏项 |
| 专业工具柜 | 低频功能收敛到「全部工具」抽屉或独立门户（工厂/平台） |
| 任务驱动 | 用户看到"做什么"而非"去哪找"；J0 零基础纵向旅程优先 |
| 角色可见性 | 各角色只看到自身权限内的入口；工厂/平台不混入商家侧栏 |
| 旧路径保留 | 30 条 legacy-redirects 不变，深链/旧书签仍可达 |

---

## 2. R3 五入口 → 实际路由映射

### 入口 1：我的生意（/app）

| 子项 | 路由 | 页面组件 | 来源 | 状态 |
|---|---|---|---|---|
| 经营首页（工作台） | `/app` | `WorkspaceHome.vue` | UX-B 真实 | 需 R3 重构（E07 信息过载） |
| 我的待办 | `/app/tasks` | `TaskCenter.vue` | 蓝图 R1 真实 | 需 R3 重构（统一任务列表，E08） |
| 新手引导 | `/onboarding` | `Onboarding.vue` | 蓝图 R1 真实 | 保留，J0 入口 |

### 入口 2：我的商品

| 子项 | 路由 | 页面组件 | 来源 | 状态 |
|---|---|---|---|---|
| 商品库 | `/app/products` | `Products.vue` | UX-B 真实 | R3 重构主列表（列可配置） |
| 商品详情 | `/app/products/:id` | `ProductDetail.vue` | UX-B 真实 | R3 重构主详情（E01/E02/E03 修复） |
| 上线中心（列表） | `/app/launch` | `LaunchCenter.vue` | UX-B 真实 | R3 重构（J1 主旅程） |
| 上线详情 | `/app/launch/:id` | `LaunchDetail.vue` | UX-B 真实 | R3 重构（E10 动作权限） |
| Listing 工作台 | `/app/listings` | `Listings.vue` | UX-B 真实 | R3 并入商品详情 Tab |
| Listing 详情 | `/app/listings/:id` | `StubPage.vue` | **stub** | R3 实现 |
| 素材中心 | `/app/products/assets` | `StubPage.vue` | **stub** | R3 实现（E03/E04/E05） |
| 合规报告 | `/app/compliance` | `Compliance.vue` | 蓝图 R1 真实 | R3 保留（合规角色入口） |
| 合规工作台 | `/app/compliance/approvals` | `Approvals.vue` | 蓝图 R1 真实 | R3 保留（审核员默认落地） |
| 市场机会 | `/app/market/discovery` | `Discovery.vue` | UX-B 真实 | R3 移入专业工具 |
| 商品候选池 | `/app/market/candidates` | `Candidates.vue` | 蓝图 R1 真实 | R3 移入专业工具 |
| 机会详情 | `/app/market/opportunity/:id` | `OpportunityDetail.vue` | 蓝图 R1 真实 | R3 移入专业工具（hidden） |
| 渠道推荐 | `/app/channels` | `Channels.vue`（UX-D） | UX-D 真实 | R3 移入专业工具 |
| 店铺管理 | `/app/channels/shops` | `Shops.vue` | UX-B 真实 | R3 移入专业工具 |
| 店铺详情 | `/app/channels/shops/:id` | `ShopDetail.vue` | UX-D 真实 | R3 保留（hidden） |

### 入口 3：我的订单

| 子项 | 路由 | 页面组件 | 来源 | 状态 |
|---|---|---|---|---|
| 订单工作台 | `/app/orders` | `Orders.vue` | UX-D 真实 | R3 保留（J4） |
| 发货/代发/备货 | `/app/fulfillment` | `Fulfillment.vue` | 蓝图 R1 真实 | R3 保留 |
| 售后退款 | `/app/refunds` | `Refunds.vue` | UX-D 真实 | R3 保留 |
| 客户消息 | `/app/support` | `Support.vue` | UX-D 真实 | R3 保留 |
| 结算与对账 | `/app/settlements` | `Settlements.vue` | UX-D 真实 | R3 保留（财务角色） |

### 入口 4：我的收益

| 子项 | 路由 | 页面组件 | 来源 | 状态 |
|---|---|---|---|---|
| 经营总览与 BI | `/app/analytics/bi` | `Bi.vue` | UX-D 真实 | R3 重构主首页 |
| 真实利润 | `/app/analytics/finance` | `Finance.vue` | UX-D 真实 | R3 保留 |
| 到岸成本 | `/app/analytics/landed-cost` | `LandedCost.vue` | UX-D 真实 | R3 保留 |
| 预测与数据质量 | `/app/analytics/forecast` | `Forecast.vue` | 蓝图 R1 真实 | R3 保留 |
| 定价与利润试算 | `/app/pricing` | `Pricing.vue` | UX-D 真实 | R3 保留 |

### 入口 5：全部工具（专业工具柜）

低频/专业功能，R3 收敛至此，减少日常侧栏负荷：

| 子项 | 路由 | 页面组件 | 来源 |
|---|---|---|---|
| 货源发现 | `/app/supply/sourcing` | `Sourcing.vue` | 蓝图 R1 真实 |
| 供应商库 | `/app/supply/suppliers` | `Suppliers.vue` | UX-D 真实 |
| 货源匹配 | `/app/supply/matching` | `Matching.vue` | 蓝图 R1 真实 |
| 采购单 | `/app/supply/purchases` | `Purchases.vue` | UX-D 真实 |
| 广告与转化 | `/app/ads` | `Ads.vue` | UX-D 真实 |
| 商品与店铺诊断 | `/app/risk/alerts` | `RiskAlerts.vue` | UX-D 真实 |
| 策略实验 | `/app/optimization/experiments` | `StubPage.vue` | **stub** |
| AI 行动中心 | `/app/ai/actions` | `AiActions.vue` | 蓝图 R1 真实 |
| AI 工作流 | `/app/ai/workflows` | `Workflows.vue` | UX-E-B 真实 |
| Agent 运行 | `/app/ai/agent-runs` | `StubPage.vue` | **stub** |
| AI 知识库 | `/app/ai/knowledge` | `Knowledge.vue` | UX-E-B 真实 |
| AI 决策依据 | `/app/ai/decisions` | `AiDecisions.vue` | UX-E-B 真实 |
| 设置：空间信息 | `/app/settings/workspace` | `WorkspaceInfo.vue` | 蓝图 R1 真实 |
| 设置：AI 与集成 | `/app/settings/ai` | `AiSettings.vue` | UX-E-B 真实 |
| 设置：用户与角色 | `/app/settings/team` | `TeamSettings.vue` | UX-E-B 真实 |
| 设置：凭据管理 | `/app/settings/credentials` | `Credentials.vue` | 蓝图 R1 真实 |
| 设置：套餐管理 | `/app/settings/plan` | `StubPage.vue` | **stub** |

---

## 3. 独立门户（不混入商家侧栏）

### 平台控制台（/console）

| 路由 | 页面组件 | 来源 |
|---|---|---|
| `/console/overview` | `Overview.vue` | UX-E-A 真实 |
| `/console/tenants` | `Tenants.vue` | UX-E-A 真实 |
| `/console/audit` | `Audit.vue` | UX-E-A 真实 |
| `/console/maintenance` | `Maintenance.vue` | UX-E-A 真实 |
| `/console/adapters` | `Adapters.vue` | 蓝图 R1 P2 真实 |
| `/console/rules` | `Rules.vue` | 蓝图 R1 P2 真实 |
| `/console/ai-resources` | `AiResources.vue` | 蓝图 R1 P2 真实 |
| `/console/login` | `Login.vue` | UX-E-A 真实 |

### 工厂门户（/factory）

| 路由 | 页面组件 | 来源 |
|---|---|---|
| `/factory`（FactoryHome） | `FactoryHome.vue` | 蓝图 R1 真实 |
| `/factory/products` | `FactoryProducts.vue` | UX-E-A 真实 |
| `/factory/stocking` | `StockingTasks.vue` | 蓝图 R1 真实 |
| `/factory/fulfillment` | `FulfillmentHistory.vue` | 蓝图 R1 真实 |
| `/factory/capability` | `Capability.vue` | 蓝图 R1 真实 |

---

## 4. Stub 页面清单（R3 须实现或明确标注缺口）

| 路由 | 组件 | R3 处置 |
|---|---|---|
| `/app/products/assets` | `StubPage.vue` | R3-1 实现素材中心（E03/E04/E05 修复） |
| `/app/listings/:id` | `StubPage.vue` | R3-1 实现 Listing 详情 |
| `/app/channels` | index.js 中 `stub` 但 UX-D `Channels.vue` 实际存在 | **冲突：index.js 挂 stub，UX-D 有真实组件**，R3-0 坐实实际加载的是哪个 |
| `/app/optimization/experiments` | `StubPage.vue` | R3-2 实现策略实验或移出导航 |
| `/app/ai/agent-runs` | `StubPage.vue` | R3-4 实现 Agent 运行或标注能力缺口 |
| `/app/settings/plan` | `StubPage.vue` | 移出导航（需 Owner 且无业务意义） |

> **E09 路由冲突证据**：`index.js` 第 68 行 `channels` 挂载 `stub`；`routes-uxd.js` 第 119-121 行同样 path `channels` 挂载 `Channels.vue`。Vue Router 同 path 时后注册的条目生效（UXD_ROUTES 在 appChildren 展开后追加），但行为依赖展开顺序，**必须运行时验证实际命中组件**。

---

## 5. 角色可见性矩阵（R3 导航过滤规则）

| 角色 | 我的生意 | 我的商品 | 我的订单 | 我的收益 | 全部工具 | 平台控制台 | 工厂门户 |
|---|---|---|---|---|---|---|---|
| OWNER | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| OPERATOR | ✅ | ✅（可写） | ✅ | 只读 | 部分 | ❌ | ❌ |
| READ_ONLY | ✅（只读） | ✅（只读） | ✅（只读） | ✅（只读） | 只读 | ❌ | ❌ |
| COMPLIANCE | ❌ | 合规入口 | ❌ | ❌ | 合规工具 | ❌ | ❌ |
| FACTORY_COLLABORATOR | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| PLATFORM_ADMIN | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |

> 导航过滤统一走 `filter.js`（`buildDomains` / `whitelistForRole`），禁止各树自带过滤逻辑。

---

## 6. R2 E01–E12 当前状态追踪（R3-0 核实结果）

> **R3-1A 修复入账（2026-10-15）**：E01/E02/E03/E04/E05/E06/E09 已由 R3-1A 落地
> （ProductDetail 渠道/素材 DTO + 店铺上下文 + 分区错误态；index.js 唯一挂载 channels；
> 新增 tests/product-detail-view / products-api-contract / route-resolve-channels，
> 442 用例全绿 + 5174 浏览器实测截图见 docs/evidence/R3-1A/）。
> 登记纠正：E03/E04 原描述仅指素材表单/核验请求体，R3-1A 已一并修复（AssetIn/ReviewIn 逐字对齐）；
> E10（LaunchDetail 按动作权限）属 R3-1B，未在本批。

| ID | 问题 | 当前证据 | R3 处置 |
|---|---|---|---|
| E01 | ProductDetail 读渠道 `items`，后端返回 `channels` | `ProductDetail.vue` 第 42-48 行读 `channels` 数组但字段为 `channel/external_id/status/synced_at`；后端 `launch_dto.py` 返回 `channels` 含 `shop/active_launch/history` | R3-1 修复 DTO 适配 |
| E02 | `fetchAssets` 不传 `shop_id` | `products.js` `fetchAssets(id)` 无 `shopId` 参数；`product_assets.py` 要求必填 | R3-1 修复 |
| E03 | 新增素材表单字段不完整 | `ProductDetail.vue` 新增素材 dialog 仅 `type/url`；`AssetRegistration` 要求 `asset_key/expected_version/asset_type/uri/content_hash/rights_status/source/market/platform/shop_id` | R3-1 修复 |
| E04 | `verifyAsset` 无请求体 | `products.js` `verifyAsset(id, assetId)` POST 无 body；`ReviewIn` 要求 `shop_id/expected_version/decision/evidence_ref/reason` | R3-1 修复 |
| E05 | 素材表格读 `type/url/verified`，后端字段不同 | `ProductDetail.vue` 表格列 `type/url/verified`；后端模型用 `asset_type/uri/verification_status` | R3-1 建立 ViewModel |
| E06 | 渠道/上线 catch 后置空 | `ProductDetail.vue` `loadChannels/loadLaunches` catch 清空数组 | R3-1 分区错误处理 |
| E07 | WorkspaceHome 信息过载 | 6 个卡片连续呈现（E07 证据：`WorkspaceHome.vue` 第 14-101 行） | R3-2 重构工作台 |
| E08 | 8 域 26 项导航 | `workspace-navigation.js` 8 域 26 子项 | R3-2 收敛为 4+1 入口 |
| E09 | channels 路由重复 | `index.js` 挂 stub；`routes-uxd.js` 挂 `Channels.vue` | R3-1 坐实唯一路由 |
| E10 | LaunchDetail 通用 `canWrite` | `LaunchDetail.vue` 使用通用 `canWrite()` 而非按动作权限 | R3-1 修复 |
| E11 | 视觉验收未截图 | `FRONTEND_V9_VISUAL_ACCEPTANCE.md` 标"待截图" | R3-5 真实浏览器验收 |
| E12 | Docker 构建链未收口 | `Dockerfile` 已有 `frontend-v9-build` 阶段但 `ERP_FRONTEND_DIST` 默认旧 | R3-5 收口 |

---

## 7. 页面所有权归属

| 页面 | 所有权 | 说明 |
|---|---|---|
| 路由表（`index.js` / `routes-uxd.js` / `routes-uxe-a.js` / `routes-uxe-b.js`） | 前端负责人 | R3 重构由总调度统一合并，禁止各包直接改 `index.js` |
| 导航树（`workspace-navigation.js`） | 前端负责人 | R3 从 8 域改为 4+1 入口，filter.js 同步更新 |
| 各页面组件 | 对应业务域工程师 | 按 R3 任务契约分派 |
| API 域（`api/domains/*.js`） | 前端负责人 | R3-1 修复断点时统一改 |
| 后端路由（`backend/app/routers/*.py`） | 后端负责人 | R3 修复只读 DTO 适配，不改业务逻辑 |
| workbench（未提交 WIP） | 他人 | **禁止混入 R3 提交** |
