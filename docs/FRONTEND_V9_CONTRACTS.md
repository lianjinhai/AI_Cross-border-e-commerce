# FRONTEND V9 · 冻结契约（UX-B 编码直接输入）

> 系列归属：`FRONTEND_V9_*`。上位：`FRONTEND_V9_MASTER_DESIGN.md` §6（迁移策略）、`FRONTEND_V9_IMPLEMENTATION_PLAN.md` §7（先冻结再并行）。本文即那 4 份契约的落盘细化。
> 约束：只引用 `backend/app/routers/` 实存端点；不改 `frontend/`、`backend/` 代码。工程师按本文实现，不做设计判断。
> `frontend-v9/` 为未来文件，路径引用以 `<!-- docs-ok -->` / `// docs-ok` 豁免文档门禁。

---

## 一、Design Tokens 令牌名冻结

**结论（起份方式）：`frontend-v9/src/styles/tokens.css` 全新起份——以现有 `frontend/src/styles/tokens.css` 全文拷贝为底、按本节追加扩展。旧文件保持原样不动（旧前端零影响）；两文件允许并存（不同目录），不共享路径。**

### 1.1 沿用（值与命名逐字不变）

`--color-primary:#409EFF` `--color-success:#67C23A` `--color-warning:#E6A23C` `--color-danger:#F56C6C` `--color-info:#909399` `--color-bg:#f5f7fa` `--color-text:#303133` `--color-text-secondary:#909399` `--color-border:#dcdfe6` `--color-sidebar:#1f2d3d`；`--space-1..6`(4/8/12/16/24/32px)；`--font-size-xs/sm/md/lg/xl/display`(12/13/14/16/18/26px)；`--font-weight-regular/medium/bold`(400/500/700)；`--radius-sm/md/round`(4/8/999px)；`--shadow-card/pop/focus`。

### 1.2 新增

```
/* 文本/表面梯度（补齐现网散落值） */
--color-text-regular:#606266;  --color-text-disabled:#c0c4cc;
--color-surface:#ffffff;  --color-surface-alt:#fafbfc;  --color-border-light:#e4e7ed;
/* 语义浅底 */
--color-primary-bg:#ecf5ff;  --color-success-bg:#f0f9eb;  --color-warning-bg:#fdf6ec;
--color-danger-bg:#fef0f0;  --color-info-bg:#f4f4f5;
/* 空间强调色 */
--space-accent-workspace:var(--color-primary);  --space-accent-console:#6f42c1;  --space-accent-factory:#0e9f6e;
/* 图标尺寸 */
--icon-sm:14px;  --icon-md:16px;  --icon-lg:20px;
/* 抽屉档位（统一两档） */
--drawer-w-sm:480px;  --drawer-w-md:560px;
```

### 1.3 深色模式预留（本版不实现，只定命名规则）

- 派生规则：深色值写于 `[data-theme="dark"]` 选择器内，**只覆盖、不新增名字**——组件只允许引用 §1.1/§1.2 的语义名，深浅切换=同名换值；`--color-sidebar`、`--space-accent-*` 一并覆盖。
- 禁止组件出现 `data-theme` 判断或第二套类名；主题开关实现属 UX-F 之后，本文不做。

### 1.4 Element Plus 映射约定

沿用现方案逐字平移：`:root:root`（特异性 0,2,0）内 `--el-color-primary:var(--color-primary)` 等 5+1 映射；EP 派生梯度（light-3/5/7/8/9）仍由 EP 构建期生成，tokens 文件不处理。字面量色值只允许出现在 tokens 文件（含本节新增块）。

---

## 二、AppShell 契约 + 导航数据结构

**结论（单双组件）：三薄壳 + 共享内核。`shells/AppShellCore.vue` 承载布局骨架（侧栏+顶栏槽+内容区+状态横幅+面包屑），`WorkspaceShell.vue / ConsoleShell.vue / FactoryShell.vue` 为薄壳，仅注入各自的导航源、空间强调色与顶栏装配；不做一个巨型带分支的单组件。** <!-- docs-ok: UX-B 新建文件，路径在 UX-B 创建后可解析 -->

### 2.1 AppShellCore 接口

```js
// shells/AppShellCore.vue  <!-- docs-ok: UX-B 阶段新建后可解析 -->
props: {
  space:        String,   // 'workspace' | 'console' | 'factory'，决定强调色与横幅策略
  navigation:   Array,    // §2.2 结构的域数组（已按角色过滤）
  impersonating:Boolean,  // 代客中：常显横幅+一键退出
  readOnly:     Boolean,  // 只读态横幅（READ_ONLY 或 Context 降级）
}
slots: { default /* 页面内容 */, 'topbar-extras' /* 顶栏空间差异化装配 */, banner /* 追加横幅 */ }
emits: { 'exit-impersonate' /* 退出代客 */, 'toggle-sidebar' /* 收起/展开 */ }
```

**P2-1 补注（权威口径）**：UX-B 实现采用内核内置 `<router-view>` 承载路由页面内容（AppShellCore.vue），这是路由组合场景的**权威形态**，页面开发一律经路由挂载；`default` 插槽约定保留给非路由嵌套场景（测试桩、静态演示），两者不并存使用。

三薄壳职责（各 ≤60 行）：WorkspaceShell 装配 WorkspaceSwitcher+StoreSwitcher+全局搜索+TaskCenter+通知+AI 副驾驶 FAB；ConsoleShell 仅租户标识+搜索；FactoryShell 仅工厂名（无副驾驶）。工厂账号隐藏副驾驶、Console 不显示副驾驶（旅程验收 J6/J7）。

### 2.2 导航数据结构（三空间同构，域数组）

```js
// shared/navigation/types.js（纯数据约定，非运行时代码）
// 域：{ key:string, label:string, icon:string, children:NavChild[] }
// NavChild：{ path:string, label:string, icon:string, hidden?:boolean, badge?:'approvals'|'alerts' }
// icon 一律 @element-plus/icons-vue 组件名（现网约定）；hidden=参数详情等不入侧栏的子路由；badge 取已接端点计数
// 三份菜单源：workspace-navigation.js（11 域）/ console-navigation.js（4 项）/ factory-navigation.js（1 项+2 待接入注释占位）
//   <!-- docs-ok: UX-B 阶段新建后可解析 -->（上面三文件路径）
```

### 2.3 角色过滤函数签名（平移 navigation.js 语义 + 新前缀）

```js
// shared/navigation/filter.js  <!-- docs-ok: UX-B 阶段新建后可解析 -->
buildDomains({ roleKey, canManageMembers, isImpersonating })  // → Array<Domain>
// roleKey ∈ 6 枚举；PLATFORM_ADMIN(非代客)→console 树；FACTORY_COLLABORATOR→factory 树；
// COMPLIANCE→白名单过滤（/app、/app/analytics/bi、/app/listings*、/app/compliance*、/app/launch*）；
// 非 OWNER 隐藏 /app/settings/*、/app/compliance/approvals；OWNER 全量（team 需 canManageMembers）
whitelistForRole(roleKey)  // → Set<string>，与 buildDomains 同源产出，供路由守卫复用（禁止双事实源）
```

### 2.4 切换器接口与 workspace.js 对接

```js
// components/WorkspaceSwitcher.vue
props: { workspaces:Array /* /me/workspaces 的 items */, activeId:String }
emits: { switch(workspaceId) }  // 壳内调用 shared/workspace.js 的 switchWorkspace(id)，成功后由 subscribeWorkspaceChange 通知刷新
// components/StoreSwitcher.vue
props: { shops:Array /* shops 列表 */, modelValue:String /* shopId */ }
emits: { 'update:modelValue' }  // 选中值存 localStorage v9_selected_shop，供订单/广告/客服页作默认筛选
```

对接约定：一律用现有 `shared/workspace.js` 平移件——`getContext()`（响应式引用，读取即建立依赖）、`getWorkspaceEpoch()`（丢弃过期快照）、`subscribeWorkspaceChange(fn)`（切区后刷新菜单与页面数据）；禁止新写 Context 获取逻辑或第二份 axios 实例。

---

## 三、路由契约

### 3.1 meta 字段约定

```js
meta: {
  space: 'app'|'console'|'factory',  // 空间归属，守卫与 AppShell 选壳依据
  domain: '商品经营',                 // 一级域中文标签（与导航树 domain.label 同源），面包屑渲染
  title: '商品池',                    // 页标题（document.title + 面包屑叶）
  hidden: true,                      // 仅参数详情路由标注：不入侧栏
  requiresOwner: true,               // 仅 /app/settings/* 标注：非 OWNER 守卫拦截
}
```

### 3.2 旧路径 → 新路径 302 映射表（30 条，全量有对应，无孤儿）

| 旧路径 | 新路径 | 备注 |
|---|---|---|
| /login | /console/login | 全空间共用 |
| /（Layout redirect /dashboard） | /app | 外壳根 |
| /dashboard | /app | 经营工作台（矩阵#3） |
| /discovery | /app/market/discovery | #4 |
| /products | /app/products | #5 |
| （无） | /app/products/:id | 新增详情路由 |
| /listings | /app/listings | #6 |
| （无） | /app/listings/:id | 新增详情路由 |
| /compliance | /app/compliance | #7 定位改为报告中心 |
| /compliance-workbench | /app/compliance/approvals | #8 合规员默认落地 |
| /launch | /app/launch | #9 |
| /launch/:id | /app/launch/:id | #10 id 透传 |
| /shops | /app/channels/shops | #11 |
| /suppliers | /app/supply/suppliers | #12 拆分 |
| （无） | /app/supply/purchases | 新增页（旧 4 tab 之一独立） |
| /factory-portal | /factory/products | #13 |
| /pricing | /app/pricing | #14 |
| /ads | /app/ads | #15 |
| /orders | /app/orders | #16 |
| /refunds | /app/refunds | #17 |
| /settlements | /app/settlements | #18 |
| /support | /app/support | #19 |
| /workflows | /app/ai/workflows | #20 |
| /knowledge | /app/ai/knowledge | #21 |
| /bi | /app/analytics/bi | #22 |
| /finance | /app/analytics/finance | #23；到岸成本新页 /app/analytics/landed-cost 无旧对应 |
| /alerts | /app/risk/alerts | #24 |
| /ai-decisions | /app/ai/decisions | #25 |
| /users | /app/settings/team | #26 |
| /settings | /app/settings/ai | #27 |
| /platform-admin | /console/overview | #28 拆 4 页：/console/tenants、/console/maintenance 随迁 |
| /platform-admin?tab=audit | /console/audit | query 子态独立成页，query 语义废弃 |

**结论（无对应新页处置）：本表 30 条全部有明确新对应，无「无对应」孤儿；实现为 router 内 `redirect` 数组（或守卫前置查表），带 `:id` 的透传参数；查表未命中的旧路径统一落 404 页（不做静默 /app 兜底，便于暴露映射遗漏）。**

### 3.3 守卫行为约定（平移 permissions.js 语义，路径查 §3.2 表）

1. 有 token 先 `ensureWorkspaceContext()`（刷新不丢权限，现行约定）；
2. `routeRedirect()` 判定顺序不变：未登录→/console/login；PLATFORM_ADMIN(非代客)→仅 /console/*；FACTORY_COLLABORATOR→仅 /factory/*；COMPLIANCE→白名单外重定向落地页；`requiresOwner` 且非 OWNER→/app；代客中放行该租户 Workspace 视图；
3. **P2-4 澄清（权威规则唯一化）**：运行时权限分流**一律按第 2 条重定向**——COMPLIANCE 白名单外→`/app/compliance/approvals`、`requiresOwner` 非 OWNER→`/app`，此为唯一权威口径；`/403` 页仅作防御性挂接点保留（直接导航 /403、或未来显式拒绝场景），守卫**不会**把用户送到 /403，原「已登录但白名单拒绝→/403」条款**废弃**；
4. 404：未匹配路由→`/404`（NotFound）；500：全局错误边界→ServerError；
4. 登录成功按 `defaultLanding()` 分流（超管→/console/overview、工厂→/factory/products、合规→/app/compliance/approvals、其余→/app）。

---

## 四、api/domains 模块签名

### 4.1 模块清单（api/ 下，对齐 API_MAPPING 30 页）

auth.js、me.js、workbench.js、discovery.js、products.js（含 product_assets/product_channels）、listings.js、compliance.js、launch.js、shops.js、suppliers.js、purchases.js、factoryNetwork.js、pricing.js、ads.js、orders.js、refunds.js、settlements.js、support.js、workflows.js、schedules.js、knowledge.js、bi.js、finance.js、crossBorder.js、alerts.js、ai.js、admin.js、actions.js、users.js
`<!-- docs-ok: UX-B 阶段新建后可解析 -->`（上列各文件）。其余域（discovery/refunds/settlements/support/knowledge/pricing/finance/crossBorder/alerts/ai/admin/factoryNetwork/schedules）职责=各自域端点的 1:1 薄封装+DTO 转换，签名模式同 §4.2，不赘述。

### 4.2 高频域完整签名（UX-C/D）

```js
// 统一形态：fetchXxx(参数) → Promise<DTO>；actionXxx(参数) → Promise<结果DTO>；转换在 api/dto.js 纯函数
// <!-- docs-ok: UX-B 阶段新建后可解析 -->（本节各文件）

// auth.js（后端 auth）：login({username,password})→{token,user}；listUsers()/createUser(d)/updateUser(id,d)→成员 DTO
// me.js（me）：fetchContext()（经 shared/workspace.js，不在本模块重复）；fetchWorkspaces()→{items[]};switchWorkspace(id)→bool

// workbench.js（只读 BFF，字段透传后端 build_todo/build_overview，禁改名）：
fetchTodo({limit=50, includeHistory=false}) → {items:[{type:'launch'|'action'|'alert'|'review', ...}], counts, partial, sources}
fetchOverview({limit=50})                  → {sections, signals, partial, sources}  // signals 任一键不可得即 null
// partial 降级：partial=true 时 TaskCard/MetricCard 必须渲染完整性提示（契约 §4.3）

// products.js（products + product_assets + product_channels，前缀均 /products）：
fetchProducts({page,keyword,source}) → {items[],total};  fetchProduct(id) → 商品 DTO（含 assets、channels 只读）
createProduct(d)/updateProduct(id,d) → 商品 DTO;  scrapeByUrl({url}) → 标准化结果;  standardize(id)
createDropshipOrder(id,{...}) → 采购单 DTO（走 purchases 链路）;  fetchAssets(id)/addAsset(id,d)/verifyAsset(id,assetId)
fetchChannels(id) → 渠道只读列表

// shops.js（shops）：fetchShops() → {items[]（含授权态/token 过期态）};authorize(shopType)/exchangeCode(d)/refresh(id)
syncOrders(id) → 同步结果;  saveCategoryMapping(id,d)

// launch.js（launch，沿用 composables/launchCenter.js 封装逻辑平移）：
fetchLaunches({page,filters,view}) → {items[],total};  createLaunch({product_id,shop_id,...}) → 流程 DTO
fetchLaunch(id) → {steps[],timeline[],mode:'GUIDED'|'PROFESSIONAL',...};  runStepAction(id,stepId,action) → 步骤回执
syncLaunch(id) → 同步回执

// listings.js（listings）：fetchListings({page,status}) → {items[],total}
// 【P2-2 回写】后端无 GET /listings/{id}（listings.py 实存仅：列表、/{id}/publication-attempts、review-queue、/{id}/reviews），
//  原 fetchListing(id) 拆分为：
fetchListingReceipts(id) → 发布回执数组（GET /listings/{id}/publication-attempts，PublicationReceipts 数据源）
fetchListingReviews(id)  → 复核记录列表（GET /listings/{id}/reviews，审批分栏数据源）
// 详情页数据由列表项 + 上述两接口拼装，不再假设单条详情端点
generate(d)/optimize(id,d) → 生成/优化结果（含 AI 建议三段式数据）;  submitReview(id)/approveReview(id,verdict)
publish(id,{shopIds}) → 发布回执 DTO

// orders.js（orders）：fetchOrders({page,status,shopId}) → {items[],total};importCsv(file) → {ok[],errors:[{row,reason}]}
updateStatus(id,status)（非法流转由后端拒绝，前端 StateBar 预校验）;ship(id,d) → 履约回执（物流轨迹待接入不渲染）
syncShopOrders(shopId) → 同步回执

// purchases.js（purchases）：fetchPurchases({page,status,supplierId}) → {items[],total}
createPurchase(d) → 采购单 DTO;generateFromForecast(supplierId) → 生成结果（一键从预测生成）

// bi.js（bi）：fetchMetrics() → 指标数组（每项含口径说明字段）;fetchTrends(query) → 序列数据
generateReport(query) → {taskId?,report}（异步进度按回执轮询，无 taskId 则同步返回）

// actions.js（独立前缀 /actions，ApprovalPanel 统一消费）：
fetchActions({status,type,page}) → {items[],total};approve(id)/reject(id,{reason}) → 审批回执
execute(id) → 执行回执（含成功/失败态，失败可重试）
```

### 4.3 统一请求封装约定（api/client.js + errors.js）

- client.js 逐字平移现 `api.js`：Bearer 注入、401→清 token/erp_impersonating/Context 并跳 /console/login、`detail` envelope 规整（对象取 message）只弹一次全局 toast；
- errors.js：`normalizeError(err) → {message, traceId?, blockers?}`，页面级错误交 ErrorState，不再重复 toast；
- 403：不弹 toast，返回规整错误由页面呈 NoPermissionState 语义（EmptyState reason='NO_PERMISSION'）；
- partial 透传：workbench 两端点的 `partial`/`sources` 字段**必须**透传到视图层（TaskCard/信号区块），禁止吞掉；FACTORY 空、COMPLIANCE 脱敏由后端保证，前端不特判；
- DTO 转换全部为 dto.js 纯函数（snake_case→视图模型），可 vitest 直测；页面禁止直接 import axios。
