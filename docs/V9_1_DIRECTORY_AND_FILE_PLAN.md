# V9.1 前后端目录与文件落位清单

> 最后更新：2026-10-18。状态：开发落位方案；现有路径已静态核对，拟新增文件尚未创建。
> 用途：V9.1 开发前确定每项职责写入哪个文件，避免重复实现和目录失控。
> 上位规范：`AGENTS.md`、`docs/CODE_AND_DIRECTORY_STANDARD.md`。本文件只补充 V9 目录及本次功能落位，不替代架构、接口或进度事实源。

## 1. 使用规则

1. 优先修改下列现有文件，不按原型编号新建 page01、page02，不另开 frontend-v10、backend-v2 或第二套 ERP。
2. 本文为职责地图，不意味着所有列出的文件每批都要修改。每批先列准确的新增/修改文件、职责、依赖、测试和回滚点，再编码。
3. 拟新增文件仅在现有职责确实无法承接时创建；不能先搭空目录、空服务和占位 API。创建后将本清单中的状态改为实际存在。
4. 新增顶层目录或 services 模块，按 D-6 同步上位规范 §2；同步文档地图、API 契约和相应测试。结构调整记录 ADR，不能借重构无关搬迁。
5. 本次审查时存在未提交开发内容；存在不代表已提交或已验证。执行前重新查 Git，不覆盖其他工作。

## 2. 顶层职责与当前目录

以下为相关目录的职责视图，省略无关文件和缓存，不是完整递归文件清单。

```text
AI-电商ERP/
├── AGENTS.md                       协作与安全入口
├── backend/
│   ├── app/                        部署运行代码
│   │   ├── main.py                 应用入口、路由装配、静态托管
│   │   ├── config.py               配置，不硬编码密钥或测试环境
│   │   ├── db.py                   数据库连接基础设施
│   │   ├── auth.py                 认证/鉴权公共入口
│   │   ├── models.py               现有 ORM 实体定义；Workspace 表族例外见 §4
│   │   ├── routers/                HTTP 参数、鉴权、响应及下层调用
│   │   ├── services/               领域规则、事实写入、只读聚合
│   │   │   └── adapters/           平台适配实现
│   │   ├── workflows/             流程引擎、Launch DAG/状态/动作/恢复/DTO
│   │   ├── agents/                既有领域 Agent 与编排；不直接访问数据库
│   │   ├── tools/                 Agent 数据访问与工具审计通道
│   │   └── ai/                    模型/RAG 基础设施
│   ├── migrations/versions/       新增 Alembic 迁移，已执行文件不改
│   ├── tests/                     后端单元/接口/权限/迁移测试
│   ├── scripts/                   运维、验证、备份脚本
│   └── erp.db                     本地业务库，非源码，不提交
├── frontend-v9/                   本次唯一前端开发对象
│   ├── src/
│   │   ├── main.js / App.vue       启动与根组件
│   │   ├── app/router/            路由、守卫、旧链接兼容
│   │   ├── app/errors/            403/404/500 页面
│   │   ├── app/pages/             已有 StubPage；不把新业务页放此处
│   │   ├── shells/                共用外壳、顶栏、侧栏、三空间装配
│   │   ├── pages/                 路由页面，按业务域分目录
│   │   ├── features/              单一业务域的组件/状态逻辑
│   │   ├── components/            跨域可复用的显示/交互组件
│   │   ├── composables/           Vue 响应式取数与交互编排
│   │   ├── shared/                展示转换、纯规则及既有上下文工具
│   │   │   ├── api/               HTTP 客户端及错误基础设施
│   │   │   └── navigation/        导航树与角色过滤
│   │   ├── api/domains/           按业务域封装真实请求
│   │   ├── api/dto.js             既有 DTO 适配；不可改成另一份业务模型
│   │   ├── permissions/           前端能力判断，不替代服务端鉴权
│   │   ├── styles/tokens.css       颜色/间距/字体等令牌唯一落点
│   │   └── styles.css             全局基础样式，避免堆页面专用 CSS
│   └── tests/                     Vitest 契约、展示、状态和交互测试
├── frontend/                      旧版回退，默认不双写新能力
├── docs/
│   ├── DOCUMENT_MAP.md            文档总索引
│   ├── CONTRACT.md                API 契约
│   ├── DECISIONS.md               ADR 权威源
│   ├── FRONTEND_V9_PROGRESS.md    既有 V9 进度事实源
│   ├── evidence/                  已有验收材料目录，生成物策略见 §7
│   └── archive/                   一次性报告与提示词快照
└── .gitignore / .dockerignore     生成物先声明再产生
```

不新增平行的 frontend-v9/src/services HTTP 层；现有 HTTP 请求统一通过 shared/api/client.js，再由 api/domains 封装。不在后端新建 repository/domain/schema 多层框架作为本次改造的前置条件。

## 3. 前端文件落位：原型到实际入口

下表路径均相对仓库根；每个路由页面是组装入口，不应把全部表单、请求和状态机塞进一个 Vue。

| 功能/原型 | 现有页面 | 现有请求/状态复用 |
|---|---|---|
| 外壳 | `frontend-v9/src/shells/AppShellCore.vue`、`frontend-v9/src/shells/ShellSidebar.vue`、`frontend-v9/src/shells/WorkspaceShell.vue` | `frontend-v9/src/shared/navigation/workspace-navigation.js`、`frontend-v9/src/composables/workspaceShell.js` |
| 01 我的生意 | `frontend-v9/src/pages/home/WorkspaceHome.vue` | `frontend-v9/src/api/domains/workbench.js`、`frontend-v9/src/shared/workspaceHomeView.js` |
| 02 起步 | `frontend-v9/src/pages/onboarding/Onboarding.vue` | `frontend-v9/src/shared/onboardingProfile.js`、`frontend-v9/src/shared/onboardingStart.js`；画像持久化请求落位见 §6 |
| 03 商品方向 | `frontend-v9/src/pages/market/Discovery.vue`；候选 `frontend-v9/src/pages/market/Candidates.vue` | `frontend-v9/src/api/domains/discovery.js`、`frontend-v9/src/composables/discoveryTransfer.js` |
| 04/06 SKU 研究与商品详情 | `frontend-v9/src/pages/product/ProductDetail.vue`；列表 `frontend-v9/src/pages/product/Products.vue` | `frontend-v9/src/api/domains/products.js`、`frontend-v9/src/shared/productDetailView.js` |
| 05 比选 | `frontend-v9/src/pages/supply/Matching.vue` | `frontend-v9/src/api/domains/suppliers.js`、`frontend-v9/src/shared/matchingView.js` |
| 07 上线 | `frontend-v9/src/pages/product/LaunchDetail.vue` | `frontend-v9/src/api/domains/launch.js`、`frontend-v9/src/features/launch/LaunchStepPanel.vue`、`frontend-v9/src/composables/launchViews.js` |
| 08 AI 行动 | `frontend-v9/src/pages/aiops/AiActions.vue` | `frontend-v9/src/api/domains/actions.js`、`frontend-v9/src/components/ApprovalPanel.vue` |
| 09 费用与利润 | `frontend-v9/src/pages/optimization/Pricing.vue`；维护 `frontend-v9/src/pages/analytics/Finance.vue` | `frontend-v9/src/api/domains/pricing.js`、`frontend-v9/src/api/domains/finance.js`、`frontend-v9/src/components/MoneyValue.vue` |
| 10 订单履约 | `frontend-v9/src/pages/fulfillment/Orders.vue`、`frontend-v9/src/pages/fulfillment/Fulfillment.vue` | `frontend-v9/src/api/domains/orders.js`、`frontend-v9/src/api/domains/purchases.js`、`frontend-v9/src/shared/orderView.js` |

路由装配继续使用 `frontend-v9/src/app/router/index.js` 与既有 routes-uxd.js、routes-uxe-a.js、routes-uxe-b.js，不为一次改造再创建 v91-router 平行事实源。既有文件名包含历史批次不构成必须改名的理由。

### 前端边界

- pages：页面结构、路由参数、组合调用；不直接散落 axios/fetch，不内置财务核算公式。
- features：特定业务面板，例如商品准备阶段、费用完整性；只有真正跨域复用才升级到 components。
- composables：loading、取消/过期响应、选择、取数和操作编排；不复制后端权限或定价规则。
- shared：当前含 workspace 等有状态工具，是存量约定；新纯展示函数不得 import 页面，不能因为“共用”就把所有业务往这里放。
- api/domains：字段与请求协议，不操作 DOM、不弹页面级 toast，不把异常改写成假空数组。
- shared/api/client.js：统一认证、传输基础能力，领域业务错误仍交由相应视图处理。
- 组件警戒 300 行/硬上限 400 行；超过时按职责拆分，不能靠压缩代码规避。

## 4. 后端职责和准确复用文件

| 职责 | HTTP 边界 | 领域实现及规则位置 |
|---|---|---|
| 工作台聚合 | `backend/app/routers/workbench.py` | `backend/app/services/workbench.py`；只读聚合，不接管其他域写入 |
| 身份与范围 | `backend/app/routers/me.py` | `backend/app/services/workspace_context.py`、`backend/app/services/shop_scope.py`、`backend/app/services/store_scope.py` |
| 配置/成员 | 按既有对应路由复用 | `backend/app/services/settings_service.py`、`backend/app/services/membership_service.py`；不是把画像写入身份解析函数 |
| 商品与渠道 | `backend/app/routers/products.py`、`backend/app/routers/product_channels.py` | `backend/app/services/product_outputs.py`、`backend/app/services/product_performance.py`；渠道流程 DTO 复用 workflows |
| 市场研究 | `backend/app/routers/discovery.py` | `backend/app/services/discovery_outputs.py`、`backend/app/services/trend_source.py` |
| 供应商/报价 | `backend/app/routers/suppliers.py` | `backend/app/services/supply_outputs.py`；独立报价选择职责如必要按 §6 新增 |
| 订单/采购 | `backend/app/routers/orders.py`、`backend/app/routers/purchases.py` | 复用既有库存/供给能力；跨域只读聚合如必要按 §6 新增，不在 workbench 中写订单 |
| 费用/利润 | `backend/app/routers/pricing.py`、`backend/app/routers/finance.py` | `backend/app/services/costing.py`、`backend/app/services/commercial_analytics.py`、`backend/app/services/pricing_outputs.py` |
| 上线流程 | `backend/app/routers/launch.py` | `backend/app/workflows/launch_actions.py`、`backend/app/workflows/launch_state.py`、`backend/app/workflows/launch_dto.py`、`backend/app/workflows/launch_access.py`；其他 launch_* 文件按真实调用使用 |
| 素材与证据 | `backend/app/routers/product_assets.py` | `backend/app/services/product_assets.py`、`backend/app/services/asset_rights.py`、`backend/app/services/asset_schema.py` |
| AI Action | `backend/app/routers/actions.py` | `backend/app/services/action_system.py`、`backend/app/services/action_records.py`、`backend/app/services/action_policy.py`；队列执行查既有 action_queue 等实现 |
| 外部平台 | 原有业务路由，不增加绕过领域的快捷执行入口 | `backend/app/services/platform_adapters.py` 为兼容入口；具体平台实现在 adapters 包 |

普通业务可以 routers → services → 数据层；AI 请求按 routers → Orchestrator/agents → tools → services 执行，不能把所有普通 CRUD 强行套 Agent。services 不导入 routers，tools 不导入 agents，Agent 不直接读写数据库或调用其他 Agent。Launch 的 workflows 分层保留，不迁出到另一套 launch_service 重复实现。

`models.py` 是现有 ORM 入口，但 **Workspace Phase 1 表族是明确例外**：上位规范 D-7 要求由 Alembic 落地，通过运行时探测与原生 SQL 读取；不得为画像方便直接注册该族到 Base.metadata，导致 create_all 绕过迁移。画像存储应先判断复用现有设置/表族还是需要新迁移，决定后记录 ADR。

Pydantic 请求模型现有多在各领域 router，复用现状；跨模块类型若确需抽取，先确定所属领域和唯一来源，不同时创建 schemas.py 与 schemas/，不从 services 反向 import router 中的类型。Python 模块警戒 300/上限 500 行、函数警戒 50/上限 80 行；models.py 仅纯定义例外。

## 5. 测试文件落位

| 功能 | 已有后端测试入口 | 已有前端测试入口 |
|---|---|---|
| 工作台 | `backend/tests/test_workbench.py` | `frontend-v9/tests/workspace-home-view.test.js`、`frontend-v9/tests/workbench.test.js` |
| 画像与范围 | `backend/tests/test_workspace_context_api.py`、`backend/tests/test_setting_scope.py` | `frontend-v9/tests/onboarding-profile.test.js`、`frontend-v9/tests/onboarding-start.test.js` |
| 商品/供给 | `backend/tests/test_supply_outputs.py`、`backend/tests/test_discovery_outputs.py` | `frontend-v9/tests/products-query.test.js`、`frontend-v9/tests/product-detail-view.test.js`、`frontend-v9/tests/shared/matching.test.js` |
| 上线/素材 | `backend/tests/test_launch_api.py`、`backend/tests/test_launch_actions.py`、`backend/tests/test_product_assets.py` | `frontend-v9/tests/launch-views.test.js`、`frontend-v9/tests/launch-center.test.js` |
| AI Action | `backend/tests/test_action_system.py` | `frontend-v9/tests/uxe-api-domains.test.js`；审批交互新测试见 §6 |
| 成本/财务 | `backend/tests/test_pricing_outputs.py`、`backend/tests/test_commercial_data_integrity.py` | `frontend-v9/tests/uxd-api-domains.test.js`；完整性新测试见 §6 |
| 订单 | `backend/tests/test_orders.py`、`backend/tests/test_store_scope.py` | `frontend-v9/tests/order-view.test.js` |
| 导航/权限 | `backend/tests/test_security.py`、`backend/tests/test_role_permissions.py` | `frontend-v9/tests/permissions.test.js`、`frontend-v9/tests/v91-shell-sidebar.test.js` |

测试入口并不证明覆盖充分；新增行为补在所属域，不能把所有用例写进 test_api.py 或新建一个巨型 test_v91_all.py。共享 pytest fixtures 放 `backend/tests/conftest.py`，不从另一测试模块跨文件 import fixture。隔离服务验证复用 `backend/scripts/e2e_feasibility.py`，不要把启动/数据库初始化逻辑放进 app 页面路由。

## 6. 必要新增文件的预定位置（提案，尚未创建）

以下是明确的候选路径，**不是创建指令或现存事实**。开工时先查是否已有等价模块，若有则复用并修订本表。不要把下列名字直接当可 import 的路径。

| 候选文件（提案） | 创建条件与唯一职责 | 配套测试（同为提案） |
|---|---|---|
| backend/app/services/onboarding_profile.py | 现有配置服务不能直接承接时，封装画像校验、作用域和持久化；HTTP 优先扩展既有 me.py | backend/tests/test_onboarding_profile.py |
| frontend-v9/src/api/domains/onboarding.js | 后端画像契约确认后封装专门读写；身份 Context 仍用既有 me/workspace，不复制 | frontend-v9/tests/onboarding-api.test.js |
| backend/app/services/product_journey.py | 现有商品/渠道读模型不足时聚合阶段、缺口及合法下一步；不持有第二份流程状态 | backend/tests/test_product_journey.py |
| backend/app/services/supply_selection.py | 确有独立报价选择业务时校验归属、有效性并持久化，不重算成本 | backend/tests/test_supply_selection.py |
| backend/app/services/order_workbench.py | 订单全量计数与订单/采购/履约关联只读聚合；订单写入仍在所属领域 | backend/tests/test_order_workbench.py |
| frontend-v9/src/features/product/ProductJourneyPanel.vue | 商品详情准备阶段过大需拆出时；消费真实 DTO，不请求多个后端自造阶段 | frontend-v9/tests/product-journey-panel.test.js |
| frontend-v9/src/features/optimization/CostCompletenessPanel.vue | 费用完整性业务面板需拆分时；消费 costing 结果，不复制公式 | frontend-v9/tests/cost-completeness-panel.test.js |
| frontend-v9/src/features/aiops/ActionDetailPanel.vue | AI 建议主从页需拆分时；复用 ApprovalPanel 和 Action API | frontend-v9/tests/action-detail-panel.test.js |

迁移文件放 backend/migrations/versions，具体文件名与 revision 必须根据届时 Alembic head 确定，不能提前编造编号。新增请求/响应字段明确在 `docs/CONTRACT.md` 中记录，不因原型叫“经营阶段”就直接创建同名数据库列。

## 7. 文档、原型、生成物与本地数据

- 目录职责维护本文件；通用规则维护 `docs/CODE_AND_DIRECTORY_STANDARD.md`；接口维护 `docs/CONTRACT.md`；决策维护 `docs/DECISIONS.md`；进度维护 `docs/FRONTEND_V9_PROGRESS.md`。不再建立平行进度总表。
- 原型 ZIP 长期来源为用户提供的 Downloads 文件；可安全解压到仓库外临时目录，不把 PNG 塞进 src 当整页实现。若确需版本化设计源，先明确保留策略，不擅自把大包提交仓库。
- 一次性验收报告放 docs/archive 并登记 archive/README；持续维护文档登记 DOCUMENT_MAP。可复现脚本在 backend/scripts，测试在对应 tests。
- 截图、浏览器轨迹、日志、临时构建、测试数据库优先放仓库外任务专属目录。若用已有 docs/evidence 下的批次目录，先确认对应生成物被 Git 与 Docker 忽略；手写证据索引是否入库单独决定，不用忽略整个 docs 来掩盖文档。
- 当前观察到 backend/qa、frontend-v9/dist_tmp_qa2 等既有目录，其存在不是新规范。后续不得以此为模板扩散；未核实归属、用途和进程状态前不能清理或搬动。
- 当前 `.dockerignore` 可见前端专用规则主要指向旧 frontend，不可假定 V9 的 node_modules/dist/临时输出自动被覆盖；产生新输出或改构建前核对两份 ignore 的实际匹配结果。
- app 内禁止数据库、日志和临时脚本；主库、冷备、.env、依赖和构建产物禁止提交。需要部署配置改动时单独验证 Docker/TLS，不因目录梳理就改生产入口。

## 8. 每批必须先填写的文件清单

| 路径 | 状态 | 职责/具体改动 | 上下游依赖 | 对应测试/验证 | 回滚边界 |
|---|---|---|---|---|---|
| 必须填准确相对路径 | 已有修改/新增提案/仅核对 | 一个主要职责 | API、服务、状态或组件 | 实际测试路径及行为 | 本批自有差异，保留其他 WIP |

不允许“修改前端相关文件”“新增几个接口”这种模糊计划。先提交可读清单，不代表每次都需要用户审批；范围已授权时按清单继续。发现新依赖先更新清单，再增文件。每批结束用实际 diff 对照清单，解释任何新增/遗漏，并更新本文件的现有/提案状态。

目录验收：无重复入口/事实源，无反向依赖，无绕过 Action 的写入，无孤儿路由/API，无不明生成物入库；源码规模满足上位规范。路径存在性检查只证明落位，不代表功能测试通过。
