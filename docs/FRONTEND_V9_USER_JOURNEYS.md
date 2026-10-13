# FRONTEND V9 · 三空间用户旅程（UX-A 产品冻结）

> 系列归属：`FRONTEND_V9_*`。配套：`FRONTEND_V9_PAGE_MATRIX.md`（页面矩阵）、`FRONTEND_INFORMATION_ARCHITECTURE.md`（V1.0 的 11 域 IA，V9 沿用其业务域语义、重组为三空间）。
> 核心原则：**用户有什么优势就发挥什么优势，缺什么能力 AI 补什么**；不同起点（无货源 / 有工厂 / 有店铺 / 有团队）的业务路径自然衔接，最终都汇入同一条「选品 → 货源 → Listing → 上线 → 订单 → 增长」经营主线。
> 事实边界：只描述已接入 `backend/app/routers/` 的真实能力；后端未有的能力标「待接入」。

## 一、三空间定义

| 空间 | 路由前缀 | 使用者 | 定位 |
|---|---|---|---|
| Platform Console | /console/* | 平台服务商我方运营（PLATFORM_ADMIN） | 租户开通、审计、平台规则维护、代客支持 |
| Commerce Workspace | /app/* | 个人/团队/企业跨境卖家（OWNER/OPERATOR/READ_ONLY/COMPLIANCE） | 产品核心：完整经营闭环 |
| Factory Portal | /factory/* | 外部工厂（FACTORY_COLLABORATOR） | 只看本厂相关数据：产品产能、询价/订单/结算（部分待接入） |

空间隔离由 `permissions.js routeRedirect` 现行策略承载并在 V9 保留：超管锁 Console、工厂锁 Factory、合规员走白名单、其余进 Workspace。

## 二、用户类型 × 旅程总览

| 用户 | 优势（发挥） | 缺口（AI 补） | 起点旅程 | 主空间 |
|---|---|---|---|---|
| U1 零经验新手 | 无（白纸） | 选品、货源、Listing、定价全部 | J1 引导式冷启动 | Workspace |
| U2 有 1688 货源卖家 | 现成货源与价格 | 店铺、Listing、跨境合规 | J2 从货源出发 | Workspace |
| U3 源头工厂主 | 产能与供货能力 | 卖货、店铺运营 | J3 工厂触网（双空间） | Factory → Workspace |
| U4 已有 Shopee/TikTok/eBay 店铺卖家 | 在售店铺与订单 | 选品补货、Listing 优化、内部运营 | J4 从店铺出发 | Workspace |
| U5 跨境团队管理者 | 团队与预算 | 审批、风控、统一口径 | J5 团队治理 | Workspace |
| U6 平台管理员 | 平台侧视角 | — | J6 租户运营 | Console |
| U7 工厂协作者 | 本厂产品资料 | 平台规则理解 | J7 工厂协作 | Factory |

## 三、旅程明细

### J1 零经验新手（无货源、无店铺）

- **起点**：首次登录，无商品、无店铺、无货源。
- **关键路径**：登录 → 工作台 onboarding 引导（新增）→ 商品发现（AI 选品）→ 转入商品池 → 1688 代发下单 → Listing 生成 → 合规检测 → 上线中心创建流程 → 店铺授权 → 发布 → 订单。
- **核心页面流转**：`/app`（onboarding 卡片：3 步引导）→ `/app/market/discovery`（AI 选品+机会评分，一键转入商品池）→ `/app/products/:id`（采集/标准化详情）→ `/app/products`（代发向导）→ `/app/listings`（AI 生成→编辑→复核分步流）→ `/app/compliance`（检测报告）→ `/app/launch`（创建向导→详情 GUIDED 模式）→ `/app/channels/shops`（授权向导）→ `/app/orders`。
- **AI 协助点**：①选品建议与理由（discovery/pick）；②Listing 文案与关键词（listings/generate、optimize）；③建议定价（pricing/suggest）；④合规问题修复建议（compliance 报告）；⑤上线每步的下一步建议（launch GUIDED）；⑥全局 AI 副驾驶随时问答（ai/chat）。
- **AI 补位逻辑**：用户无任何经验 → AI 承担「选什么、卖什么价、怎么写、怎么上」的全部判断，用户只做确认。
- **验收标准**：①零操作经验者按 onboarding 从选品走到首单上线全程无需外部帮助；②每步 AI 建议有可读理由；③任一步失败可重试且有原因；④未配置 1688 Key/未授权店铺时对应步骤呈未配置态而非报错。

### J2 已有 1688 货源卖家

- **起点**：已有供应商/代发关系，无或少量店铺。
- **关键路径**：登录 → 供应商录入（含 1688 链接）→ 商品采集/标准化 → 店铺授权 → Listing 生成 → 合规 → 上线 → 订单/代发履约。
- **核心页面流转**：`/app`（待办引导）→ `/app/supply/suppliers`（新增供应商+评分）→ `/app/products`（URL 抓取采集）→ `/app/channels/shops`（授权销售店）→ `/app/listings` → `/app/compliance` → `/app/launch` → `/app/orders`（代发下单 pawning 经 purchases/dropship）→ `/app/pricing`（以真实进货价算利润）。
- **AI 协助点**：①采集抓取自动标准化商品资料；②按成本自动建议售价与利润测算；③Listing 一键生成；④店铺/合规自动预检（listings/review-queue 预审）。
- **AI 补位逻辑**：用户强项是货源与成本 → AI 补「把它变成能上架的商品与 Listing」的整段能力；定价建议基于其真实进货价（发挥优势而非替代）。
- **验收标准**：①录入供应商后商品采集链路顺畅；②利润计算与财务页口径一致；③从供应商到上架全链路步骤可回溯（launch 时间线）。

### J3 源头工厂主（有工厂，想直接卖）

- **起点**：以 FACTORY_COLLABORATOR 邀请进 Factory Portal，或以卖家身份注册后关联自有工厂。
- **关键路径**（工厂视角）：工厂登录 → Factory Portal 维护产品/产能 → 平台侧产生询价/订单（待接入）。
- **关键路径**（自销视角）：邀请/切换进 Commerce Workspace → 把本厂产品转入商品池 → 店铺授权 → Listing/上线/订单同 J2。
- **核心页面流转**：`/factory/products`（产品与产能 CRUD）→（平台邀请或身份切换）→ `/app` → `/app/products` → `/app/channels/shops` → `/app/launch` → `/app/orders`。
- **AI 协助点**：①工厂侧：产品资料从极简输入生成标准供给目录（基于 product_assets 能力，待确认）；②平台侧：按产能自动匹配平台选品需求（factory_network 机会，待接入）；③自销：同 J2 全套。
- **AI 补位逻辑**：工厂主优势是货与产能 → AI 补「卖货」：选品匹配、店铺运营、Listing。两条路径（供货平台 vs 自营销售）由身份/邀请自然分流，不强制二选一。
- **验收标准**：①工厂账号仅能访问 /factory/* 且只见本厂数据；②工厂新增产品即时出现在平台侧供给目录（suppliers/factory_network 联动）；③同一账号被授予租户成员身份后可切换 Workspace（switch 受限场景按现行 me 策略降级，不虚构切换能力）。

### J4 已有 Shopee/TikTok/eBay 店铺卖家

- **起点**：已有在售店铺与历史订单。
- **关键路径**：登录 → 授权店铺 → 同步订单 → 逆向补商品/供应商 → 缺口商品走 AI 选品补货 → Listing 优化 → 经营增长。
- **核心页面流转**：`/app/channels/shops`（OAuth 授权向导）→ `/app/orders`（真店同步 sync_orders）→ `/app/products`（补录/采集商品）→ `/app/pricing`（重定价）→ `/app/listings`（优化在售 Listing）→ `/app/ads`（广告增长+AI 选词）→ `/app/analytics/bi`（经营分析）。
- **AI 协助点**：①订单同步后自动补全商品/费用事实（finance、orders）；②在售 Listing 一键优化（listings/optimize）；③广告 AI 选词与优化（ads/suggest、campaigns/{id}/optimize）；④风险巡检（alerts）与 AI 决策可解释（ai-decisions）。
- **AI 补位逻辑**：用户强项是店铺与流量 → AI 补「供应链与内部运营」：把已有订单逆向变成采购/库存事实，把增长交给广告与定价优化。
- **验收标准**：①三类平台店铺授权与订单同步真实走通（以已接入 shops 端点为准）；②同步订单出现在订单页并带店铺标识；③广告审批动作有执行回执；④同步失败原因可见。

### J5 跨境团队管理者（有团队）

- **起点**：OWNER，已有成员分工与经营数据。
- **关键路径**：登录 → 分配角色 → 团队按分工工作 → 管理者看审批/风控/统一口径。
- **核心页面流转**：`/app/settings/team`（成员与角色）→ 团队成员各自进入 `/app` 相关域 → 管理者日常落 `/app`（工作台待办）→ `/app/compliance/approvals`（合规员）或审批队列 → `/app/risk/alerts`（风控巡检）→ `/app/analytics/bi`、`/app/analytics/finance`（统一口径与利润）→ `/app/ai/decisions`（AI 决策审计）→ `/app/settlements`（付款）。
- **AI 协助点**：①工作台待办按成员/域分发（workbench/todo）；②告警自动巡检+处置深链；③BI AI 报告（bi/report）；④AI 动作统一审批（actions，经广告等工作流入口）。
- **AI 补位逻辑**：管理者优势是组织与资源 → AI 补「全局可见性与风险拦截」：不用逐页翻，待办/告警/审批主动找人。
- **验收标准**：①READ_ONLY 成员全程无写入口；②COMPLIANCE 仅白名单路径可达；③告警确认与处置闭环可追踪；④OWNER 可查每个 AI 决策的依据链。

### J6 平台管理员（平台服务商运营）

- **起点**：超管登录。
- **关键路径**：登录 → Console 总览 → 开通租户 → 发初始凭据 → （需要时）代客进入租户排查 → 回退出。
- **核心页面流转**：`/console/overview` → `/console/tenants`（开通、凭据一次性展示）→ 代客进入 → 外壳切为该租户 Workspace 视图（erp_impersonating）→ 顶栏代客横幅一键退出 → `/console/audit`（访问审计）→ `/console/maintenance`（平台规则检查、演示数据清理）。
- **AI 协助点**：AI 日志（ai_logs）与访问审计辅助定位租户问题（只读审计，不代客做经营决策）。
- **验收标准**：①超管登录仅落 Console；②非超管访问 /console/* 被重定向；③代客全程横幅常显且退出即恢复；④租户开通凭据仅展示一次且提示复制。

### J7 工厂协作者（外部工厂员工）

- **起点**：受平台邀请，只服务本厂。
- **关键路径**：登录 → 默认落 Factory Portal → 维护本厂产品/产能 → 响应平台需求（待接入）。
- **核心页面流转**：`/factory/products`（唯一核心页）→ 未来扩展 /factory/orders、/factory/settlements（均「待接入」，不虚构入口）。
- **AI 协助点**：极简输入生成标准产品资料（待确认）；平台规则/合规要求通俗解读（依托 knowledge，待接入工厂侧）。
- **验收标准**：①只能看到本厂数据（后端 factory_network portal 隔离为准）；②访问任何 /app/*、/console/* 被拒绝；③产品更新对平台侧供应商页可见。

## 四、跨起点衔接（业务主线汇流）

```
U1 无货源 ──AI 选品──┐
U2 有1688 ──供应商──┤
U4 有店铺 ──同步订单→逆向补商品──┤==> 商品池 /app/products
U3 工厂主 ──供给目录→转入商品池──┘        │
                                   Listing 生成/合规/上线
                                   /app/listings → /app/launch
                                          │
                                   订单履约 /app/orders
                                          │
                    增长优化 /app/pricing + /app/ads + /app/analytics/bi
```

- 衔接点 1：Discovery 选品 → Products（「转入商品池」按钮，V9 新增闭环）。
- 衔接点 2：Factory 供给目录 → Suppliers/商品池（factory_network 现有能力）。
- 衔接点 3：Orders 同步 → 缺货商品 → Pricing/Ads（增长回路）。
- 衔接点 4：所有失败/异常 → Alerts + AI 决策依据（风控与可解释回路）。

## 五、旅程通用验收（三空间）

1. 空间隔离：每个角色的默认落地页、可见路由、菜单与 `me/workspace-context` 权限目录完全一致；刷新后不丢。
2. 全程无虚构：任何「待接入」能力不出现可点击入口（只能以预告态/文档态出现）。
3. AI 可解释：每个 AI 建议可跳转 `/app/ai/decisions` 查看依据。
4. 断链归零：V1.0 审计的 G 类断链（选品不落池、告警无处置、审批无回跳等）在 V9 逐条消除，验收以 `FRONTEND_V9_PAGE_MATRIX.md` 各行验收要点为准。
5. 旧业务逻辑零推翻：Product/Supplier/Factory/1688/Shop/Listing/Publishing/Order/Purchase/Finance/Compliance/Workflow/Agent/Workspace 的后端契约与业务规则不变，V9 仅重排前端组织方式。
