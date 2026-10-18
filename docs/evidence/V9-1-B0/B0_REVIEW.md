# 链鲸 V9.1 原型落地 · B0 实施前只读复核

> 日期：2026-10-18｜基线 commit：`c6d7c98`（工作区含他团队未提交 WIP，见 §1）
> 范围：**只读复核**。本轮未修改任何业务代码、未启动服务、未登录外部账号。
> 依据：素材包 10 张 PNG（程序化取样尺寸与色值，非目测）、`README_前端落地说明.md`、当前 V9 源码、后端路由与模型、权限矩阵。
> 完成门槛（提示词 §四 B0）：十图均有映射 · 已存在/可派生/缺接口分清 · 当前前端版本可识别。

---

## 0. 结论摘要

1. **十张原型全部能在现有仓库找到落点，不需要新建第二套 ERP、第二套订单或第二套利润事实。** 5 个主入口在 `workspace-navigation.js` 已收敛完成（R3-2A），原型要求的 IA 与当前代码**同构**；差距在「一级项只显示 5 个」的渲染方式，不在信息架构。
2. **6 处正确性缺陷经源码复核仍然存在**（类目筛选参数错配、订单金额硬编码 `$`、店铺范围被显式丢弃、导航名与页面目标不一致、定价页手输商品 ID、AI 行动审批权限键与后端不一致）。它们属于「先修正确性再谈外观」，必须在 B1 处理，否则视觉改造会把错误一起美化。
3. **两个能力缺口会阻断"看起来完成"的验收**：① Workspace 经营画像（预算/目标市场/风险偏好/资源起点）**既无表也无端点**，原型 02 要求的"按真实画像恢复状态"当前无法真做；② 订单列表接口不返回店铺名/商品名、也不支持 `shop_id` 过滤，原型 10 的"按店铺/商品串联"缺后端支撑。
4. **运行版本可识别，但本轮无服务在跑**：`/api/build-info` 端点已存在，默认配置仍指向旧 `frontend/dist`。任何视觉验收前必须先 curl 该端点记录真实前端身份（详见 §2）。

---

## 1. 复核边界与不可触碰清单

基线：`c6d7c98`。工作区存在**他团队未提交 WIP**，本轮一律只读，不 staging、不 checkout、不格式化：

| 类型 | 文件 | 归属判断 |
|---|---|---|
| 已修改 | `backend/app/routers/actions.py`、`backend/app/routers/listings.py`、`backend/app/services/review_outputs.py` | 工作台/WIP 他团队 |
| 已修改 | `backend/app/config.py`、`backend/app/main.py` | 部署接管修复（`ERP_FRONTEND_DIST` + `/api/build-info`），属既有交付 |
| 新增未跟踪 | `backend/app/routers/workbench.py`、`backend/app/services/workbench.py`、`backend/app/services/action_queue.py`、`backend/tests/test_workbench.py`、`backend/qa/` | 工作台 WIP 他团队 |
| 已修改 | `frontend/src/views/Dashboard.vue` + `frontend/src/components/*`、`frontend/src/composables/workbenchTodo.js`、`frontend/tests/workbench.test.js` | 旧前端 WIP 他团队（回退基线，不动） |
| 已修改 | `frontend-v9/vite.config.js` | 代理目标可配置（`VITE_API_PROXY_TARGET`），用于隔离验收，非业务逻辑 |
| 已修改 | `docs/CONTRACT.md`、`docs/archive/README.md` | 他团队文档同步 |

**结论**：B1 起若需触碰上述目录，先与该变更方确认；V9.1 改造的文件清单（§7）已避开这些路径。

附带核对：素材包解压到 `C:/temp/linkwhale-v91/`，逐条校验无路径越界、无脚本文件，仅 1 份 README + 10 张 PNG。

---

## 2. 当前前端版本识别（B0 门槛项）

三层证据，逐层可执行：

| 层 | 判定方式 | 当前结论 |
|---|---|---|
| 配置层 | `backend/app/config.py` 的 `frontend_dist` 默认值 | 默认 `<root>/frontend/dist`（**旧前端**）。未设 `ERP_FRONTEND_DIST` 时 8000 一定不是 V9 |
| 运行时层 | `GET /api/build-info` 返回 `frontend_dir` / `frontend_dist` / `dist_exists` / `build_sha` | 端点已在（`backend/app/main.py`）。**这是唯一可信的"我看到的到底是哪套前端"判据** |
| 本轮实测 | `curl -m 3 http://127.0.0.1:8000/api/build-info` | **连接被拒绝：本轮无任何服务在跑**，无法给出运行期截图证据 |

已归档的历史实测（`docs/FRONTEND_V9_RUNTIME_VERIFICATION.md`）：8000 曾返回旧 `index-D3-EbOxi.js`，8001（`ERP_FRONTEND_DIST=frontend-v9/dist`）返回 V9 的 `index-gEmKFVQd.js`。**但该 hash 对应旧构建，B6 必须重新取样，不能引用旧 hash 当本轮证据。**

**B1 开工第一步（强制）**：起隔离实例 → `curl /api/build-info` → 把 `build_sha` 与 `git rev-parse HEAD` 一起写进当批交付记录。不做这一步，后续所有截图都不具备可比性。

---

## 3. 十图映射总表

权限一律以 `backend/app/services/workspace_context.py` 的 `ROLE_PERMISSIONS` 为权威；前端 `can(key)` 只查询、不重定义。

| # | 原型 | 路由 | 现有组件 | 主要数据来源 | 主动作 / 权限 | 差距等级 |
|---|---|---|---|---|---|---|
| 01 | 我的生意 | `/app` | `pages/home/WorkspaceHome.vue` | `api/domains/workbench.js`、`launch`、`bi` | 任务卡跳转（只读）；无写权限 | **中**：单列任务区 vs 原型 2:1 双列；预算/市场/风险无来源 |
| 02 | 新手起步 | `/onboarding` | `pages/onboarding/Onboarding.vue` | `api/domains/shops.js` | 方向选择（纯前端）→ 跳 J0 | **高**：三资源起点卡缺；画像无持久化 |
| 03 | AI找商品方向 | `/app/market/discovery` | `pages/market/Discovery.vue` | `api/domains/discovery.js` | 导入趋势 / AI 扫描 / 转入商品池 → `product:write` | **高**：市场/预算/类目三筛选不存在；无数据更新时间 |
| 04 | 工厂SKU出海 | `/app/products/:id`（供给研究子视图）；外部厂方走 `/factory/products` | `pages/product/ProductDetail.vue`、`pages/factory/FactoryProducts.vue` | `products`、`suppliers`、`factoryNetwork` | 只读研究；厂方维护走 `supply:write` | **高**：无"SKU × 目标市场"对象，市场证据无来源 |
| 05 | 货源比选 | `/app/supply/matching` | `pages/supply/Matching.vue` | `suppliers.js` 的 `fetchOffers` | 询价（无 API）→ 人工路径 | **中**：三栏 6/10/8 内嵌表格，原型为全宽比较表 |
| 06 | 商品经营中心 | `/app/products/:id` | `pages/product/ProductDetail.vue` | `products`、`launch`、`listings` | 创建/继续上线 → `launch:create` | **中**：缺"概览/货源/销售准备/表现"分页签；阶段不可解释 |
| 07 | Launch上线工作台 | `/app/launch/:id`（列表 `/app/launch`） | `pages/product/LaunchDetail.vue`、`LaunchCenter.vue` | `api/domains/launch.js` | `available_actions` 真实动作；审批 → `compliance:approve` | **中**：单列纵向 vs 原型三栏；步骤分组需可追溯 |
| 08 | AI行动中心 | `/app/ai/actions` | `pages/aiops/AiActions.vue` | `api/domains/actions.js` | 批准/执行 → **`order:write`（错）** | **中**：抽屉详情 vs 原型左右主从；权限键错配 |
| 09 | 利润风险决策 | `/app/pricing`（联动 `analytics/landed-cost`、`analytics/finance`） | `pages/optimization/Pricing.vue` | `api/domains/pricing.js` → `POST /api/pricing/calc` | 试算/采纳 → `finance:write` | **高**：主流程要手输商品 ID；费用完整性未前置判断 |
| 10 | 订单履约协同 | `/app/orders`（联动 `fulfillment`、`supply/purchases`、`settlements`） | `pages/fulfillment/Orders.vue` | `api/domains/orders.js` | 状态/发货/导入 → `order:write` | **高**：无店铺/商品列；`shopId` 被丢弃；币种硬编码 |

> 图 04 的归属按提示词 §一.1 处理：**是"商家自己有工厂/商品资源"的经营研究场景**，不是给外部 `FACTORY_COLLABORATOR` 开商家工作台。商家侧落 `/app/products/:id` 子视图；厂方维护仍在受限 `/factory/*`，两处分别验权限。

---

## 4. 字段三分类（已存在 / 可派生 / 缺后端）

### 4.1 已存在（可直接绑定，缺的只是呈现）

| 字段/对象 | 事实源 |
|---|---|
| 商品基础：`sku` `title` `category` `brand` `hs_code` `attrs` `images` `source_platform` `source_url` `status` | `backend/app/models.py` 的 `Product` |
| 机会评分：`demand` `competition` `profit` `risk` `total` `reasons` `model` | `ProductScore`（发现页三张表已在用） |
| 订单：`shop_id` `product_id` `listing_id` `qty` `amount` `cost` `profit` **`currency`** `status` `tracking_no` `source` `country` `buyer_name` | `Order`。**`currency` 已存在，是 UI 硬编码 `$` 的前置条件已具备** |
| 供应商报价：`supplier_name` `price` `moq` `ship_days` | `fetchOffers` 返回 |
| 上线流程：步骤、状态、`available_actions`、版本、回执 | launch 域 DTO（`LaunchDetail.vue` 已在消费） |
| 成本试算：8+ 项成本分解、`cost_total_cny`、汇率缺失时 fail-closed | `backend/app/services/costing.py` 的 `calc_profit`，`POST /api/pricing/calc` |
| 来源标签 8 码 + `tagInfo()` / `moneyLabel()` / `envTag()` | `frontend-v9/src/shared/dataLabels.js` |
| 任务聚合与计数 | workbench 域（**他团队 WIP**，只读消费，不改） |

### 4.2 可派生（现有字段算得出，需写纯函数 + 测试，不新增表）

| 派生项 | 依据 | 落点 |
|---|---|---|
| 经营阶段 `STARTING/SUPPLY/LAUNCHING/OPERATING/UNKNOWN` | `workspaceHomeView.js` 的 `businessStage()` 已按 `signals` + `in_progress` 推导 | **已实现**，原型 01/02 可直接复用；仍需把"为什么是这个阶段"文案外露 |
| 商品准备阶段/阻断 | 商品 × 其 `launch` 状态 × 素材完整性 | 新增纯函数（`shared/productStageView.js`） |
| 订单店铺名 | 前端已有 `fetchShops()` 列表 → `shop_id` 映射 | B1 前端映射即可；后端 join 为更优解 |
| 订单商品名 | `product_id` → 需二次查询或后端 join | 推荐后端补 `shop_name` / `product_title`（见 §5-G1） |
| 费用完整性（缺哪项） | `calc_profit` 的分解项 + 汇率是否存在 | 新增 `shared/costCompletenessView.js` |
| 数据新鲜度（"更新日期"） | 趋势快照若有 `created_at` 则取最大值为"数据时间" | 需先核对 discovery DTO 是否暴露；**未确认前不得显示某日期** |
| 订单摘要（待发货/待处理） | 无聚合端点 → **只能显示"当前页范围"并标注** | 原型 10 要求"不能拿分页条数冒充全量"，按此实现 |

### 4.3 缺后端支持（必须显示缺口，禁止编造）

| 缺口 | 影响原型 | 本轮处理 |
|---|---|---|
| **G-A Workspace 经营画像**（预算、目标市场、风险偏好、资源起点）无表、无端点 | 02 三资源起点卡"按真实画像恢复"、01 经营条件卡 | 只能做"本次会话内选择"，显式标注未持久化；不把 localStorage 冒充服务端画像 |
| **G-B SKU × 目标市场研究**无对象、无端点 | 04 右侧"目标市场条件与证据" | 显示"待核实/未取得依据"，禁止硬编码新加坡/马来西亚/美国 |
| **G-C 询价发送**无 API | 05"发送询价" | 只提供生成/复制询价内容；复制成功≠已发送 |
| **G-D 订单全量聚合**无端点 | 10 顶部摘要 | 显示当前页范围或"缺口"，不用分页条数冒充全量 |
| **G-E 平台回款结算**：`settlements` 是**供应商应付对账**，不是平台 GMV/回款 | 10"结算不是 GMV" | 页面必须写明口径，禁止把供应商应付读成平台回款 |
| **G-F 素材上传/权利凭证**仅有部分（`services/product_assets.py`），无通用上传服务 | 07 素材权利 | 沿用现有登记凭据，禁止伪造 hash 或自动判定授权 |

---

## 5. 正确性缺陷复核（相对 `c6d7c98` 仍然存在）

| ID | 现状（符号引用，非行号） | 证据 | 等级 |
|---|---|---|---|
| **UI-01 类目筛选不生效** | `pages/product/Products.vue` 把 `q.category` 作为 `source` 传给 `fetchProducts`；`api/domains/products.js` 只透传 `source`；后端 `list_products` 读的是 `category` | 三处参数名不一致，筛选必然空转 | **P0** |
| **UI-02 币种硬编码** | `pages/fulfillment/Orders.vue` 金额与预估利润均写死 `$`；`Order.currency` 已存在 | 后端默认 `USD`，但 CNY 订单同样显示 `$` | **P0** |
| **UI-02b 定价页同源问题** | `pages/optimization/Pricing.vue` 表头写死"当前价$ / 建议价$ / 单件利润$" | 与 UI-02 同一类错误，易被漏掉 | **P0** |
| **UI-03 店铺范围被丢弃** | `api/domains/orders.js` 的 `fetchOrders` 含 `void shopId`；后端 `list_orders` 无 `shop_id` 参数 | "已按店铺过滤"是假象 | **P0** |
| **UI-04 导航名与页面目标不一致** | 导航叶子"真实利润"→ `meta.title` 为「真实利润」→ 但 `Finance.vue` 标题是「财务工作台」且默认 tab 停在汇率维护 | 用户点"真实利润"看到汇率表 | **P1** |
| **UI-05 定价主流程要手输 ID** | `Pricing.vue` 用 `el-input-number` 手输 `pid` 才能试算 | 破坏 J0 商品上下文链，违反"中途不需复制 ID" | **P1** |
| **UI-06 AI 审批权限键错配** | `AiActions.vue` 用 `can('order:write')` 门禁批准/执行；后端 `services/ai_actions.py` 的 `decide_budget_action` 走 `_require_finance`（`finance:write`）；而"审批"语义的权威键是 `compliance:approve`（仅 OWNER/COMPLIANCE 持有） | OWNER/OPERATOR 因两者同在 `_WRITE_PERMISSIONS` 而未暴露；**COMPLIANCE 作为指定审批人反而看不到任何按钮** | **P1** |
| **UI-07 侧栏色值写死** | `ShellSidebar.vue` 内联 `background-color="#1f2d3d" text-color="#bfcbd9" active-text-color="#409EFF"` | 违反"组件只引用语义令牌"，且导致改主题必须改组件 | **P2**（B1 一并处理） |

**UI-06 需要一次决策**（B4 前必须定）：要么把 UI 门禁改为"按 action 类型映射权限"并让后端对 `ADJUST_AD_BUDGET` 接受 `compliance:approve`，要么把该面板的措辞从"审批"改为"财务确认"。**在决策前不要动权限代码。**

---

## 6. 视觉基线：取样值与采用值

程序化取样（10 张图 1434×533，跨页一致）：

| 用途 | 取样值 | 出现范围 |
|---|---|---|
| 侧栏底色 | `#0C2654` | 十张全部（每张约 10 万像素） |
| 工作区底色 | `#F5F8FC` | 十张全部 |
| 卡片白 | `#FFFFFF` | 十张全部 |
| 浅蓝选中/任务卡 | `#EAF2FB` | 01/02/08 等 |
| 边框/分隔 | `#DCE5EF` | 十张全部 |
| 次级蓝（链接/图标） | `#245A9C` | 多张 |
| 主按钮蓝 | `#236BBD` | 02/10 等 |
| 暖黄缺口/风险底 | `#FFF4DE` | 03/04/05/06/07/09 |
| 品牌金色点 | `#DDB85E` | 侧栏左上角 |
| 主标题深色 | `#0C2654`；次级 `#172D4B`；辅助 `#3B5076` | 正文区 |

**与现行令牌的差异（必须在 B1 记录采用值及原因）**：

- 主色 `#409EFF`（现行）→ `#236BBD`（原型）。这是**可见的品牌变化**，不是微调；改 `--color-primary` 会连带影响所有 Element Plus 主按钮与链接。需一并核对对比度与禁用态。
- 侧栏 `#1f2d3d`（现行）→ `#0C2654`（原型）。
- 布局：侧栏 `220px`（收起 64px）→ **建议 208px**；顶栏 `56px` → **建议 58px**。理由：208 与原型取样一致（1434−208=1226 内容区），且比 220 多出 12px 横向空间给比较表；58 与 56 差 2px，对齐原型成本极低。**采用值一次定死，禁止两套布局基线混用。**
- 内容横向留白：原型约 28px，现行用 `--space-*` 阶梯，**不要为此新增魔法数字**，在令牌层定义 `--layout-content-gutter`。

> 原型是**展示画幅**，不是页面高度。禁用整页图片/canvas/全局缩放/固定高度裁切。

**五入口渲染差异（关键）**：`workspace-navigation.js` 的一级结构已是 5 项（mybiz/goods/orders/revenue/tools），但 `ShellSidebar.vue` 对非 `collapsible` 的 4 个入口**把子项平铺成 `el-menu-item`**（2+4+5+5 = **16 个叶子**），只有 tools 是 `el-sub-menu`。原型是"只显示 5 个主项"。这是**渲染方式**改造，不是信息架构重做：path 一律不变（R3-2A 铁律），二级入口改由页内局部导航/抽屉承接。

---

## 7. 最小改动文件清单（按批，避开 WIP）

### B1 正确性 + 统一外壳
| 文件 | 改动 |
|---|---|
| `frontend-v9/src/api/domains/products.js` | `fetchProducts` 增加 `category` 参数并与 `source` 分开透传 |
| `frontend-v9/src/pages/product/Products.vue` | 传 `category`；保留 `source` 语义给"来源"筛选 |
| `frontend-v9/src/api/domains/orders.js` | 去掉 `void shopId`，`shop_id` 透传；参数名与后端对齐 |
| `backend/app/routers/orders.py` | `list_orders` 增 `shop_id` 过滤；返回 `shop_name`/`product_title`（join，不新增表） |
| `frontend-v9/src/pages/fulfillment/Orders.vue` | 币种绑定 + 店铺列 + 真实范围提示 |
| `frontend-v9/src/pages/optimization/Pricing.vue` | 表头币种去硬编码（与 UI-02 同批） |
| `frontend-v9/src/pages/analytics/Finance.vue` | 标题/默认 tab 与导航名对齐（UI-04） |
| `frontend-v9/src/shared/navigation/workspace-navigation.js` | 仅调标签文案（如"财务台账"），**path 不动** |
| `frontend-v9/src/styles/tokens.css` | 新增 V9.1 令牌（nav/brand/evidence/gutter），旧令牌保留一版做回退对照 |
| `frontend-v9/src/shells/ShellSidebar.vue` | 去内联色值 → 令牌；一级只渲染 5 项，二级进抽屉/页内导航 |
| `frontend-v9/src/shells/AppShellCore.vue` | 208/58 采用值 + 响应式断点复核 |
| `frontend-v9/tests/*`（新增/扩充） | 类目筛选、币种、`shopId` 透传、五入口渲染、令牌引用的真实断言 |

### B2 起步与研究（01/02/03）
`pages/home/WorkspaceHome.vue`、`shared/workspaceHomeView.js`（外露阶段理由）、`pages/onboarding/Onboarding.vue`（三资源起点卡 + 会话内画像并显式标注）、`pages/market/Discovery.vue`（筛选语义 + 证据卡 + 高级表格折叠）、必要时新增 `shared/onboardingProfile.js`（纯函数，含"未持久化"标记）。

### B3 商品与供给（04/05/06 + 商品列表推导）
`pages/product/ProductDetail.vue`、`shared/productDetailView.js`、`pages/supply/Matching.vue`、`pages/product/Products.vue`、新增 `shared/productStageView.js`。

### B4 上线与 AI（07/08）
`pages/product/LaunchDetail.vue`、`LaunchCenter.vue`、`pages/aiops/AiActions.vue`（主从布局 + 权限键按 §5 决策修正）。

### B5 费用与订单（09/10）
`pages/optimization/Pricing.vue`（去手输 ID、完整性前置）、`pages/analytics/LandedCost.vue`、`pages/fulfillment/Orders.vue`、`Fulfillment.vue`、新增 `shared/costCompletenessView.js`。

### B6 验收与文档
`docs/evidence/V9-1-B6/`（逐图真实截图 + 六角色 + 四视口）、`docs/FRONTEND_V9_PROGRESS.md`、`docs/FRONTEND_V9_DESIGN_SYSTEM.md`（令牌新增项）、`docs/DECISIONS.md`（主色变更、208/58、五入口渲染方式）。

**不在本清单内即不改。** 尤其不动 `backend/app/routers/actions.py`、`listings.py`、`services/review_outputs.py`、`workbench*`、旧 `frontend/`。

---

## 8. 接口缺口（按"是否本轮可闭环"分组）

| ID | 缺口 | 建议 | 本轮能否闭环 |
|---|---|---|---|
| G1 | `GET /api/orders` 无 `shop_id` 过滤、无 `shop_name`/`product_title` | 后端小改（join 两表，不动模型/迁移） | **能**（B1） |
| G2 | 类目筛选参数错配 | 前端改参数名即可，无后端改动 | **能**（B1） |
| G3 | 订单全量聚合（待发货/待处理计数）无端点 | 先显示"当前页范围"；端点另立需求 | 不能（显示缺口） |
| G4 | Workspace 画像（预算/市场/风险/资源起点）无表无端点 | 需新表 + 端点 + 权限测试，属独立需求 | 不能（会话内 + 标注） |
| G5 | SKU × 目标市场证据 | 需外部数据源，先"待核实" | 不能 |
| G6 | 询价发送 | 无 API；人工路径 + 复制 | 不能 |
| G7 | 平台回款结算 | `settlements` 是供应商应付，口径需在页面说明 | 不能（标注口径） |
| G8 | 素材上传/权利凭证 | 沿用现有登记凭据 | 部分 |

---

## 9. 回滚点

| 层 | 回滚手段 |
|---|---|
| 代码 | 按批提交，单批单 commit；B1–B5 每批可独立 revert，互不牵连 |
| 前端入口 | 去掉 `ERP_FRONTEND_DIST` 重启 → 立即回到旧 `frontend/dist`；**本改造不切生产入口** |
| 令牌 | 新令牌以新增变量方式加入，旧令牌保留一版；回滚只需还原 `tokens.css` |
| 数据库 | **本轮不改模型、不加迁移**（G1 仅查询层 join）；如需加字段必须单独立项 |
| 文档 | 每批只改当批文档；`docs/evidence/V9-1-B*/` 为纯新增，删除即回滚 |

---

## 10. 分批验证计划

| 批 | 验证方式（不接受"构建通过"当验收） |
|---|---|
| B1 | ① 类目筛选：造两品类商品，选 A 类后表格只剩 A（真实请求参数断言 + 页面断言）；② 币种：造 CNY 与 USD 订单，符号随 `currency` 变化；③ 店铺范围：两店铺订单，切店铺后列表与计数随请求变化；④ 五入口：截 1440/1366/768/390 四视口，一级仅 5 项且无高度溢出；⑤ 旧深链 30 条 302 不退化为 404 |
| B2 | 三类起点（无资源/有商品或工厂/有店铺）各自首屏主动作不同且可达；刷新后画像行为**可解释**（会话内丢失必须明说，不得显示成已保存）；无市场证据时不出现"已验证商机" |
| B3 | 商品→比选→返回不丢上下文；多店铺 Launch/Listing 状态互不串用；报价来源可点开，缺失显示"待核实"；复制询价后提示为"已复制"而非"已发送" |
| B4 | 后端步骤 ID 与状态不被压平；403/409/超时/等待外部四态各自正确；仅选中建议不触发审批（网络层断言无写请求） |
| B5 | 缺物流费/税费时**不出现**净利润数字；不手输 ID 可从商品上下文进入；摘要范围标注真实；采购单与销售订单不混；结算口径写明 |
| B6 | 逐图真实截图对照 + 六角色 + 四视口 + 零数据/部分失败/多币种/多店铺；`/api/build-info` 与 commit 一并落证据 |

每批必跑：`frontend-v9` 单测 + build；后端有改动跑 pytest（**必须用系统 Python 3.11**）+ ruff；文档门禁 `check_docs_consistency.py` 回 `total=0`。

---

## 11. 待决决策（B1/B4 前需要拍板）

1. **主色是否从 `#409EFF` 改为 `#236BBD`**：影响所有 EP 主色组件与链接，属可见品牌变更。建议改，但需一次写成 `DECISIONS.md` 条目。
2. **侧栏 208 / 顶栏 58** 是否确认（与现行 220/56 并存会形成双基线，必须二选一）。
3. **UI-06 语义**：AI 行动面板叫"审批"（→ `compliance:approve`）还是"财务确认"（→ `finance:write`）。
4. **Workspace 画像**（G4）是否立项：不立项则原型 02 永久停在"会话内选择"，交付说明必须写明。

---

## 12. 本轮未做（明确声明）

- 未修改任何业务代码、未新增/修改迁移、未启动服务、未登录外部平台。
- 未做任何运行期截图；§2 的版本结论来自配置默认值 + 已归档历史实测，**不是本轮实测**。
- 未验证移动端真实交互、未验证六角色实际登录行为、未验证外部平台提交/核价/成交。
- 十张图仅做程序化取样（尺寸/主色板），未做逐元素布局测量；B1 落地前若需精确间距，按需再取样。
