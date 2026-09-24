# 技术选型与决策记录（ADR）

## D1 开源同类项目调研：为什么自研而不是二开

调研结论（2026-09）：

| 候选项目 | 类型 | 评估结论 |
|---|---|---|
| Odoo / ERPNext | 通用 ERP | 体量数十万行；Odoo 企业版闭源、社区版 LGPL，ERPNext 为 GPLv3 强传染；均无 AI 原生多智能体能力。二开成本极高且方向不匹配。 |
| 启航跨境电商ERP（qihangerp，Gitee/GitHub） | 跨境 ERP | 最接近的国产开源（SpringCloud 微服务，已接 Shopify/SHEIN 订单），但本质仍是传统铺货/订单 ERP，无选品评分、合规检测、Agent 体系；Java 技术栈与 LLM 生态衔接弱。可借鉴其平台接入分层思想。 |
| Vibe Seller（zpoint/vibe-seller） | 卖家自动化 | CDP 浏览器自动化 + 任意 LLM，偏 RPA 执行层，无平台级数据模型与 BI，不适合作为系统底座。 |
| clawEC Agents | 跨境 AI Agent 集合 | 理念最接近（选品/运营/客服 Agent 化），但为脚本集合，缺 ERP 数据底座与前端。 |
| Dify / CrewAI / AutoGen | 通用 Agent 编排 | 借鉴其工作流引擎（步骤状态机、上下文传递、模型路由）设计，但不是电商业务系统。 |

**决策**：自研为主，「借鉴设计、复用成熟库」。理由：
1. 规划书的核心差异化（多智能体 + 业务闭环 + AI 原生）在现有项目中均不存在，二开任何项目都要推倒其核心层；
2. 许可证风险（GPL 传染）对后续商业化不利；
3. Python 生态（FastAPI/SQLAlchemy）与 LLM 生态天然衔接，团队可维护性最好。

## D2 技术栈

- **后端** Python 3.11 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + PyJWT。SQLite 开箱即用，`ERP_DB_URL` 可平滑切 MySQL/PG。
- **前端** Vue3 + Vite + Element Plus + ECharts + axios。中文 ERP 交互习惯，组件全量引入降低构建复杂度。
- **口令散列** 用标准库 pbkdf2_hmac，避免 bcrypt 在 Windows 的编译问题。
- **单体模块化** 而非微服务：MVP 阶段 1 进程 14 个路由模块 + 独立 agents 层，未来按模块拆分服务即可（规划书 26 章预留）。

## D3 LLM 双模架构（本系统最重要的决策）

每个 Agent 方法统一走 `ask_json(prompt, fallback)`：
- 配置了 API Key → 调 Model Router（OpenAI 兼容协议，默认智谱 GLM）要求 JSON 输出，容错解析；
- 未配置 / 调用失败 / 输出不合法 → 无缝降级到确定性规则引擎。

收益：演示环境零配置可跑通全部流程；生产接大模型后同一套代码自动升级为 AI 生成/分析；LLM 故障不阻塞业务。代价：规则引擎需要与 LLM 输出同构维护（契约文档已固化字段）。

## D4 合规门禁语义

单一品牌词命中即扣 50 分 → 风险等级 high → ListingAgent.publish 直接拒绝。这是刻意保守的业务语义：侵权下架/封店的代价远高于误拦。调整阈值改 `agents/compliance.py` 的扣分表即可。

## D5 工作流数据流

模板步骤 `{agent, action, params}` → 运行时按序执行，步骤输出全量存 `WorkflowStep.output`，其中 `context_patch` 合并进 `run.context` 传给后续步骤（如 pick_candidates 产出 product_ids，standardize_batch 消费）。注意 SQLAlchemy JSON 列的就地变更不可变检测问题——引擎统一赋新对象（`run.context = dict(ctx)`）。
# D16：跨境平台角色与接入顺序（2026-09-21）

- 1688 固定为货源端，只承担采集、供应商、报价和采购，不作为销售市场。
- 销售市场按 TikTok Shop 美国站 → Shopee 新加坡站 → Amazon 美国站推进。
- 平台适配以具体站点的官方 API 为边界，不使用无法落地的“通用平台字段”冒充真实能力。
- 未完成官方契约、权限和测试验证的平台能力必须在能力清单中保持禁用。

# D17：销售渠道扩展分层（2026-09-21）

- Shopee 新加坡站已部分接通；TikTok Global Product、eBay Inventory/Offer、Walmart OAuth/订单/异步 Feed、Lazada OAuth/订单/商品协议已实现，统一标记为 `protocol_ready_unverified`，等待官方沙箱或实店验收。
- 默认平台环境为 `sandbox`；仅显式设置 `ERP_<PLATFORM>_ENV=production` 才允许切换生产端点，也可用 `ERP_<PLATFORM>_BASE_URL` 指向本地契约沙箱。
- 下一优先级：完成上述四个平台的官方沙箱验收，再推进 AliExpress。
- 准入受限：Temu 跨境店、SHEIN，需先完成平台招商或应用审核。
- 补充渠道：Shopify Markets 属于独立站而非 marketplace；Mercado Libre 用于拉美市场。
- 所有规划平台均进入统一能力矩阵，但订单同步、发布、刷新等按钮默认关闭，禁止用占位实现冒充真实接入。

## D6 代码与目录规范：存量渐进、增量强制（2026-09-23）

**背景**：实测发现维护性风险集中爆发——仓库**未纳入 Git**、无任何 lint/format 门禁、23/23 router 直连 ORM、`platform_adapters.py` 单文件 1146 行、`backend/` 根目录混放 3 个 `.db`（2 个无引用）。

**决策**：制定 `docs/CODE_AND_DIRECTORY_STANDARD.md`，采取「存量渐进、增量强制」路线，而非一次性全量整改。

**理由**：
1. 若要求立即全面整改，规范在生效当天即被违反，反而丧失权威性；
2. 存量不合规是「已运行且测试通过」的代码，大范围改写风险高于收益；
3. 先把**可自动化的门禁**立起来（ruff + CI），能持续阻止新增债务，这比一次性清理更有价值。

**执行**：
- 新增 `backend/pyproject.toml`（ruff 规则集）与 `requirements-dev.txt`；
- 首轮启用时 509 条告警，其中 `B008`（FastAPI `Depends()`）等 421 条属框架惯用法误报，按「只报功能性缺陷」原则显式豁免；
- 修复真实缺陷 3 类：`DropshipIn` 重复定义、发布前校验未按声明字段校验、未使用变量与导入共 67 处；
- 结果：`ruff check` 全绿，接入 CI 门禁。

**代价**：`E501`（行宽）暂未启用，存量格式不统一的问题保留在台账（DEBT-04 后续收紧）。

**关联**：`docs/CODE_AND_DIRECTORY_STANDARD.md` §0、§9.4、§11。

## D7 店铺删除语义：归档式软删除（2026-09-23）

**背景**：开启 SQLite 外键强制（`PRAGMA foreign_keys=ON`，见 `app/db.py`）后，
`DELETE /api/shops/{id}` 立刻暴露为 500。实测有 5 张表引用 `shops.id`：
`oauth_states`（非空）、`platform_publish_attempts`（非空）、`orders`、
`purchase_orders`、`platform_settlement_records`。原先的物理删除从未真正安全，
只是 SQLite 默认不强制外键掩盖了它。

**决策**：删除店铺 = **归档**（`shops.archived_at` 置位 + 凭证清空 + 状态置 expired），
不物理删除行。

**理由**：
1. 物理删除会抹掉订单/采购单/结算单的店铺归属，破坏财务对账与审计留痕；
2. 级联删除同样不可接受——用户点「删除店铺」不应连带销毁历史订单；
3. 归档后店铺从列表与所有可写入口隐藏，用户可见行为与"删除"一致。

**执行**：
- 新增 `shops.archived_at`（Revision E，可空，`NULL` = 正常可用）；
- `delete_shop` 归档 + 清空 `app_secret`/`access_token`/`refresh_token`（凭证即时失效）；
- 新增 `services/shop_scope.py::active_shop()` 作为统一可见性守卫；
- 列表、`_owned`、订单导入、代发、上架发布、平台守门均排除归档店铺；
- 回归测试：`tests/test_shop_archive_and_purge.py`（3 项）。

**代价**：店铺行永久保留（含 `shop_name` 等非敏感字段）。若未来需要彻底清除，
应先经合规确认，再单独执行带级联策略的清理任务。

**关联**：`docs/CODE_AND_DIRECTORY_STANDARD.md` DEBT-19、DEBT-21。

## D8 生产部署基线：显式门禁、容器跑迁移、健康检查（2026-09-23）

**背景**：部署可行性审计发现 4 个 P0：compose 未设 `ERP_ENV=production`（生产门禁
全部短路，默认 JWT 密钥与 `admin123` 会直接上线）、无 TLS、SQLite 无 WAL（写锁争用）、
容器不跑迁移（schema 由 `create_all` 生成，版本漂移）。

**决策**：
1. compose 显式 `ERP_ENV=production`，且 `ERP_JWT_SECRET` / `ERP_ADMIN_PASSWORD` /
   `ERP_CREDENTIAL_KEY` / `ERP_CORS_ORIGINS` 四项**不给默认值**，未配置则 compose 直接
   报错退出——宁可起不来，也不带着开发默认值静默上线；
2. 容器入口 `docker-entrypoint.sh` 先 `alembic upgrade head` 再启服务，迁移失败阻断启动；
3. 镜像加 `HEALTHCHECK`（调 `/api/health`）与 `logging` 轮转；`npm install` → `npm ci`；
   运行阶段切非 root 用户 `erp`。

**TLS 未纳入本次范围**：HTTPS/反向代理属部署层，需结合真实域名与证书签发方式确定，
单独出方案。**当前状态：生产不可直接对外暴露，须置于 TLS 终止代理之后。**

**关联**：`docs/CODE_AND_DIRECTORY_STANDARD.md` DEBT-23。

## D9 迁移例外：修改已执行的 Revision C（2026-09-23）

**背景**：`20260923_09_users_nullable_workspace.py` 原含硬断言「NULL `tenant_id`
用户恰好 1 个」。但 superadmin 仅在设置 `ERP_SUPERADMIN_PASSWORD` 时才创建
（`seed.py::_ensure_superadmin`），因此**全新空库执行 `alembic upgrade head` 必然失败**
（0 个 NULL 用户 ≠ 1），容器化部署路径被彻底堵死。

**决策**：**破例修改已执行的迁移文件**（违反规范 M-2「迁移只增不改」），把断言改为兼容
两种场景：`total_users == 0` 直接返回；否则 `null_users == superadmins`（允许 0 个）。

**理由**：该迁移从未在"无 superadmin 的全新库"上成功执行过，即该路径本就不可用；
修改只放宽断言、不改数据语义，且已在全新空库与主库两条路径上实测通过
（空库 `0 → 20260923_10` EXIT=0；主库按序 upgrade 成功）。

**约束**：此为**一次性例外**。除「修复使迁移完全无法执行」的缺陷外，已执行迁移一律只增不改。

## D10 生产口令必须真正生效 + 测试夹具下沉 conftest（2026-09-23）

### D10.1 `ERP_ADMIN_PASSWORD` 从「门禁摆设」改为真正生效

**背景**：`auth.admin_bootstrap_password()` 定义了却**从未被调用**，而 `seed.py` 固定写入
`hash_password("admin123")`。后果是：生产环境 `validate_production_settings()` 要求配置强
`ERP_ADMIN_PASSWORD`（否则拒绝启动），但该口令从未用于创建或更新 admin 账号——门禁
「看起来合规」，实际仍可用 `admin123` 登录。这是一个**真实可利用的安全缺陷**，由容器内
全链路验证发现（Docker 实测中尝试用 `admin123` 登录生产容器被拒后才暴露）。

**决策**：新增 `seed._ensure_admin_password(db)`，在 `main.py` lifespan 中于
`_ensure_superadmin` 之后调用：

1. 未配置 `ERP_ADMIN_PASSWORD`，或配置值仍为 `admin123` 且**非生产**环境 → 跳过（不破坏演示）；
2. 生产环境**即使配置为 `admin123` 也不跳过**（生产门禁已在更早阶段拒绝该值，此处再兜一层）；
3. 仅作用于演示租户的 `admin` 账号，不触碰其他账号与租户；
4. 口令已对齐时直接返回，避免每次启动重算散列并使旧 token 无谓失效。

改口令同时递增 `token_version`（撤销既有 token），与 `routers/auth.py` 的改密逻辑一致。

**回归测试**：`tests/test_admin_bootstrap_password.py`（3 项：配置生效且默认值被拒 /
未配置时保留演示默认 / 改口令使旧 token 失效）。

### D10.2 测试共享夹具下沉 `tests/conftest.py`

**背景**：会话级夹具（`_fresh_db` / `client` / `auth_headers`）原先定义在 `test_api.py` 内，
其他 7 个测试文件靠 `from .test_api import ...` 复用。该写法隐含「`test_api.py` 必须最先被
收集」的顺序假设：一旦有文件名排序更靠前的模块（如 `test_admin_*.py`）先 import `app.db`
建立连接，会话级 `_fresh_db` 就无法删除测试库文件（Windows `PermissionError: WinError 32`），
整批用例报错。这直接违反规范 §8 T-2「测试不得依赖执行顺序」。

**决策**：
1. 三个共享夹具移入 `tests/conftest.py`——pytest 保证 conftest 先于所有测试模块加载，
   环境变量与库文件清理一定发生在任何 `app.*` import 之前，顺序依赖被**结构性**消除；
2. `auth_headers` 改为**函数级**作用域 + 会话级 token 缓存：每次先探测 token 有效性，
   失效即重新登录。原因是个别用例会改 admin 口令并递增 `token_version`，若把 token 固定在
   会话级，后续用例会拿到已撤销凭证，形成新的「谁先跑谁通过」顺序依赖；
3. 改口令的用例自带 `_isolate_admin_account` 自动夹具，快照并还原 admin 的口令散列与
   `token_version`，即使断言失败也不把污染留给同会话内其它文件。

**验证**：全量 `142 passed`；显式乱序运行（`test_workspace_context_api.py` +
`test_admin_bootstrap_password.py` + `test_api.py`）同样全绿；单文件独立运行通过。

**关联**：`docs/CODE_AND_DIRECTORY_STANDARD.md` DEBT-24、§8 T-2。

## D11 测试可重复性：幂等种子 + 测试库隔离（2026-09-24）

**背景**：并发/重复跑测试时出现大规模 `sqlite3.IntegrityError: UNIQUE constraint
failed: settings.key`（一次实测 115~142 个用例在 setup 阶段报错）。根因有**两个独立缺陷**，
都不在测试代码本身，而在被测代码与测试基础设施：

1. **`_seed()` 对全局唯一的 `settings` 表不幂等**。`settings.key` 无租户维度、全局唯一，
   但 `_seed()` 无条件 `db.add(Setting(...))`。当「演示数据被清理、租户仍在」时再次调用
   `_seed()`（测试夹具重建种子即属此场景），必然撞唯一约束。**这是真实缺陷**：任何
   「清空业务数据后重建演示数据」的路径都会失败，不只是测试。
2. **测试库是单实例资源**。默认 `test_erp.db` 为固定名，两个 pytest 进程并发时互相踩踏；
   且 WAL 模式下若只删主库文件、不删 `-wal`/`-shm` 旁文件，残留 WAL 会在下次建库时被
   回放到新库，把上一轮数据"复活"进来，同样触发唯一约束冲突。

**决策**：

1. 抽出 `seed.DEFAULT_SETTINGS` 常量与 `_ensure_default_settings(db)`（**缺什么补什么**，
   不覆盖用户已改的配置值），`_seed()` 改为调用它；重复调用安全，且保留原有默认值语义。
2. 测试库路径支持 `ERP_TEST_DB` 环境变量覆盖；默认名带进程号（`test_erp_<pid>.db`），
   并发进程天然隔离。清理函数 `_remove_db_files()` 统一删除 `-wal`/`-shm`/`-journal`/主库。
3. `test_commercial_data_integrity.py` 的库路径解析与 conftest 对齐（否则并行时它会指向
   默认库，成为新的踩踏点）。
4. `.gitignore` 补齐 SQLite 旁文件规则（`backend/*.db-wal` 等）与 PID 库名通配
   （`backend/test_erp*.db`）。此前 `.dockerignore` 有、`.gitignore` 漏，会把 4MB+ 的 WAL
   文件误纳入版本控制。

**验证**：
- 全量 `165 passed`（142 原有 + 23 深度对抗测试），`ruff check` 全绿；
- **连续两次**跑同一测试库均全绿（验证幂等，此前第二次必失败）；
- **并发**两个 pytest 进程（各自独立库）同时运行，各自 `142 passed`；
- `migration_preflight.py` 12 项全 PASS；主库 `integrity ok` / FK 违规 0 / 52 表 / `20260923_11`。

**关联**：`docs/CODE_AND_DIRECTORY_STANDARD.md` DEBT-26、§7.1、§8 T-2。

## D12 并行工具引入代码的缺陷根治：租户隔离 + 告警去重 + 阈值生效（2026-09-24）

**背景**：并行工具（zcode）本轮主要承担**测试编写**，同时新增了 AI 原生能力代码
（M1 选品飞轮 `product_performances`、M3 主动巡检 `alerting.py` / `routers/alerts.py`、
M6 决策解释 `ai_decisions`，迁移 `20260924_12`）。按分工，**它引入的缺陷由主代理根治**。
以下 5 项均为**实测复现的真实缺陷**，不是风格问题：

| # | 缺陷 | 严重度 | 复现方式 | 根因 |
|---|---|---|---|---|
| 1 | `pick_candidates` 跨租户泄漏商品 | **P1** | 给 `tenant_id=999` 的商品写一条 `tenant_id=1` 的 `ProductScore`，`POST /api/discovery/pick` 返回该他租户商品标题/类目 | 评分行按租户过滤，但 `db.get(Product, pid)` 按主键直取、未校验归属 |
| 2 | `/api/discovery/performance/{id}` 跨租户越权 + 污染 | **P1** | 请求他租户商品 id → `200` 且在本租户名下写入 `product_performances` 缓存行 | 路由与服务层均未校验商品归属；该接口会**写库**，污染比只读泄漏更严重 |
| 3 | 同轮巡检内去重完全失效 | **P1** | 同一供应商 2 条延迟报价 → 产生 2 条相同告警 | `SessionLocal` 是 `autoflush=False`，本轮 `db.add` 的告警对 `db.query` 不可见 |
| 4 | 告警去重键撞车导致**漏报** | **P1** | `fx_volatility` / `policy_changed` 的 `subject_id` 写死为 `0`，多个币种/平台共用同一去重键，修好 #3 后会互相抑制 | 自然键（币种/平台）未参与去重键 |
| 5 | `stockout_risk` 的 `threshold.weeks` 是死参数 | P2 | 把 `weeks` 从 1 改到 4，建议补货量不变（恒为 `demand*4`） | 补货量硬编码 4 周，与配置阈值脱节 |

**决策**：

1. **归属校验下沉到服务层**（`product_performance.py` 新增 `_assert_owned` + `ProductNotFound`），
   路由翻译为 404。理由：`get_performance` 有路由与 Agent 两条调用路径，只在路由校验会漏掉
   Agent 路径；且该函数会写库，必须在写之前拦截。同时 `window_days` 夹紧到 `[1, 365]`。
2. **`pick_candidates` 增加 `p.tenant_id != self.tenant_id` 判定**，与同文件
   `score_product` / `standardize` 的既有写法对齐。
3. **`_emit` 去重改为双防线**：本轮内存集合 `seen`（解决 autoflush 不可见）+ 库查询
   （跨轮次/跨进程窗口）。`seen` 在 `scan()` 内单例传入，命中库去重时也登记 token。
4. **自然键并入 `subject_type`**：约定「主键是整数用纯类型名；主键是自然键用
   `<类型>:<自然键>`」，即 `platform:shopee`、`currency:CNY`。
5. **`stockout_risk` 拆成两个活参数**：`weeks`（触发线，默认 1，保持原语义）+
   `cover_weeks`（备货目标，默认 4，保持原行为）。默认行为不变，改配置即生效。

**验证**（全部为实测，非推断）：
- 缺陷 1：修复前 `leak=True` → 修复后 `False`，且本租户仍能挑出 3 个候选；
- 缺陷 2：修复前 `200` + 缓存行 `(tenant_id=1, product_id=25)` → 修复后 `404` + 缓存行 0；
  `window_days` 传 `0/-5/100000` 分别夹紧为 `30/1/365`；
- 缺陷 3：同供应商 2 条报价 `created=1 skipped=1 入库=1`（修复前入库 2）；
- 缺陷 4：2 币种波动同时告警（修复前第 2 个被抑制）；3 平台政策更新首轮 3 条、次轮 0 条；
- 缺陷 5：`weeks=1/2/5` 与 `cover_weeks=2` 的补货量分别按配置变化；
- 回归：全量 `179 passed`、`ruff check` 全绿；另抽查 `stockout_risk`（多订单 1 条）、
  `listing_stale`（3 条老 Listing 3 条告警）、`price_below_floor`（多报价 1 条）、
  次轮 scan 幂等（`created=0 skipped=5`）均符合预期。

**遗留**：并行工具仍负责测试编写；新增的 `alert_events` / `alert_rules` / `ai_decisions` /
`product_performances` **尚未接入 `tenant_data_purge` 之外的清理语义评估**（`product_performances`
已补入清理计划，其余为只增审计表，按设计保留）。前端尚未接入 alerts 页面。

**关联**：`docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` §9/§10（Action 与 Tool 的权限约束）、
`docs/CONTRACT.md` §7、`docs/CODE_AND_DIRECTORY_STANDARD.md` §8 T-2。

## D13 并行工具代码的第二轮缺陷根治：缓存指纹 + 告警可见性 + 巡检可调度（2026-09-24）

**背景**：D12 之后继续按「它写测试、我根治缺陷」的分工审查新增的 AI 原生能力代码，
又发现 3 项实测可复现的真实缺陷。共同特征是**测试全绿但功能实际不可用**——
现有用例的数据量/场景恰好绕过了缺陷触发条件（详见 D14 的测试假绿审计）。

| # | 缺陷 | 严重度 | 复现方式 | 根因 |
|---|---|---|---|---|
| 1 | 表现分缓存**永不随订单增长失效** | **P1** | 5 单时算一次（`units=5 score=61.9`），再加 20 单（共 25 单）再算，仍返回 `units=5 score=61.9` | 缓存有效性只比「有无订单」（`cached.units_sold > 0`），订单数从 5 变 25 不改变「有」这个事实 |
| 2 | 高风险告警被 limit **挤出结果（漏报）** | **P1** | 库内 120 条新低风险 + 1 条较早高风险 → `GET /alerts?limit=100` 返回 100 条低风险，**high = 0** | 「先按时间取 limit 条，再在 Python 里按级别排序」，截断发生在排序之前 |
| 3 | 主动巡检**无法在界面调度** | P2 | 「AI 工作流」页新建调度，任务类型下拉只有「工作流 / 趋势扫描」；类型列对非 workflow 一律显示「趋势扫描」 | 后端 `run_task` 与 `POST /schedules` 均支持 `alert_scan`，但前端下拉缺选项、标签判断写死；种子数据也未预置巡检任务 |

**决策**：

1. **缓存指纹改为「窗口内聚合值」**：新增 `_window_aggregate()` 返回
   `(订单数, 销量, 销售额, 利润)`，既作打分输入又作缓存指纹；三者全等才复用缓存。
   新增订单、退款（`status` 变化后移出窗口）、改价改量都会改变指纹。
   一次查询同时服务「判缓存」与「重算」，比原来的两次查询更快。
2. **级别排序下推到 SQL**：用 `case()` 把 `high/mid/low` 映射为排序序号，
   `ORDER BY 序号, created_at DESC, id DESC` 后再 `limit`；同时把 `limit` 夹紧到
   `[1, 500]`（防止 `limit=0` 或超大值）。
3. **计数改为数据库聚合**：新增 `alerting.alert_counts()`，按 `level` group by +
   单独统计 `open`。原实现是数列表长度，告警超过 `limit` 时会少算
   （KPI 卡片显示「低风险 100」而库里其实有 300 条）。
4. **补齐巡检的调度入口**：前端类型下拉加「主动巡检」选项、类型列改用
   `kindLabel(row)` 三态判断；种子数据预置「每 6 小时经营风险巡检」
   （`enabled=False`，沿用演示环境保守策略，租户在界面一键启用）。

**验证**（全部为实测，非推断）：
- 缺陷 1：修复前 `units 5→5`（BUG）→ 修复后 `units 5→25`；回归用例
  `test_performance_cache_invalidates_on_order_change` 固化该场景；
- 缺陷 2：修复前 `high=0 low=100`（BUG）→ 修复后 `high=1 low=99` 且高风险排在首位；
  回归用例 `test_high_risk_visible_beyond_limit` 固化「级别整体有序」契约；
- 缺陷 3：`kindLabel` 三态 + 下拉三项，前端 `35 passed`；
- 回归：后端 `181 passed`（179 + 2 新增）、前端 `35 passed`、`ruff check` 全绿。

**教训（写入规范）**：**缓存的有效性判据必须覆盖「数据变化」而非「数据存在」**；
**任何 limit 都必须发生在排序/过滤之后**。这两条已补入
`docs/CODE_AND_DIRECTORY_STANDARD.md` §8 与
`docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` §15.5。

**关联**：D12、`docs/AI原生能力升级方案.md` §M1/§M3。

## D14 并行工具代码的第三轮根治 + 测试假绿审计（2026-09-24）

**背景**：D13 之后派两个**只读审计子代理**并行排查：一个查 Phase 1.8 的 legacy 入口清单，
一个查 `backend/tests/` 的「假绿」风险（即实现有缺陷但测试全绿）。两者共报出
**5 项真实缺陷**，全部实测复现并修复；另有 1 项被判定为「既有契约」不改。

### 一、修复的真实缺陷

| # | 缺陷 | 严重度 | 复现方式 | 根因 |
|---|---|---|---|---|
| 1 | `POST /api/suppliers/offers` **跨租户写入** | **P1（安全）** | A 租户把报价挂到 B 租户商品 → `200` 且写入成功（实测写入 1 行） | `db.get(Product, id)` 只查存在性、未比对 `tenant_id`，与同文件 `_owned` 写法不一致 |
| 2 | 部分退款后表现分**永不更新** | **P1** | 10 单各 qty=2，退 1 件（订单状态不变）→ `refund_rate` 仍为 `0.0`，应为 `0.1` | 缓存指纹只含 销量/销售额/利润，而部分退款**不改订单状态**，三项全不变 |
| 3 | 库存变化后售罄率**永不更新** | P2 | 收货入库改 `attrs.onhand` → `sell_through` 陈旧 | 同上，`onhand` 未进指纹 |
| 4 | 代客态 Context **被误判为平台身份** | P1 | superadmin 经 `/admin/tenants/{id}/enter` 进入租户后查 Context → `source=PLATFORM`、`workspace_id=None` | `me.py` 未把代客标记透传给 `resolve_workspace_context`（`is_impersonating` 恒为默认 `False`） |
| 5 | 前端**刷新即丢 Context**（Phase 1.8 致命前置） | **P0** | F5 刷新后 Context 归 null → `hasPermission()` 全返回 `null` → 所有权限判断落回 legacy 分支 | `loadWorkspaceContext()` 只在登录成功时调用，无启动引导 |

**决策**：

1. **缓存判据改为「重算结果 vs 缓存」全字段比对**（`_derive()` 纯函数 + `all(...)` 比对）。
   理由：输入维度会随规则演进增加，已因此踩过两次（① 只比「有无订单」；② 只比订单侧三项）。
   比结果集最稳，新增维度无需再改缓存逻辑；聚合查询走 `tenant_id+product_id` 索引，代价可接受。
2. **报价校验与 `_owned` 对齐**：`product.tenant_id != user.tenant_id` → 404（不泄露存在性）。
3. **代客标记显式化**：`_ImpersonatedUser` 加类属性 `is_impersonated = True`，`me.py` 用
   `getattr(user, "is_impersonated", False)` 透传（**注**：该字段名于第十七轮统一为 `is_impersonating` 以对齐 `docs/phase1_interfaces.md` §6 冻结契约，见 D25）。此前只能靠 `role == "operator"` 推断，
   而代客态与真 operator 的 role 字符串完全相同，无法区分。
4. **启动引导抽成 `ensureWorkspaceContext()`** 并在路由守卫每次导航时调用（已缓存则直接返回）。
   抽成独立函数而非写在守卫里：守卫是路由库内部机制，测试只能靠真实导航触发（会连带加载
   `.vue` 组件，慢且脆）；抽出来后可直接断言行为契约。

### 二、测试假绿修复（审计发现「恒真断言」与守卫缺口）

| 用例 | 原问题 | 修法 |
|---|---|---|
| `test_scoring_uses_performance` | `"表现分" in reasons or "暂无真实销售数据" in reasons` —— reasons 按构造必含其一，**恒真** | 造 12 笔真实订单，断言 reasons 出现「售出 12 件」且总分变化 |
| `test_explore_quota` | `assert "explore_floor" in body` —— 实现无条件返回该键（可为 None），**恒真** | 断言 `limit=3` 时恰好 1 个 `explore_pick`、门槛为数值、理由含「探索配额」 |
| `test_decision_filter_by_agent` | `all(...)` 在**空列表**上恒真 | 先 `assert items` 再断言 |
| `test_alert_ack_not_delete` | `if not alerts: pytest.skip(...)` —— 接口回归成永远返回空会**静默跳过** | 改为 `assert alerts` 前置断言 |
| `test_rule_toggle_and_threshold` | 只回读 PUT 响应，**从不验证阈值是否真的改变行为** | 新增 `test_threshold_is_a_live_parameter`：weeks=5 触发、weeks=1 不触发 |
| 跨租户矩阵 | 只覆盖 products/orders/knowledge/auth/ai；新接口（表现分、报价、告警 ack、规则改）**零覆盖** | `test_security.py` 扩到这 4 类，含「不得写入他租户缓存行」 |
| 幂等回放 | `idempotent_replay` 分支**零覆盖** | 新增 `test_publish_is_idempotent_on_retry`：第二次必须重放且平台尝试记录数不增 |
| `/alerts` 的 `total` | 等于 `len(items)`（已被 limit 截断），与契约「总数」不符 | 新增 `alert_total()` 走数据库聚合；响应加 `returned` 字段区分 |

**关键验证方法（值得复用）**：新增的每条回归测试都用「**临时回退修复 → 确认测试失败 → 恢复**
的方式证明它真能抓住缺陷。本轮验证了 3 条（代客标记、死参数、缓存指纹），全部确认有效——
避免「写了回归测试但其实也是恒真」的二次假绿。

**判定为既有契约、不改**：工厂门户账号访问 `/api/me/*` 返回 403 是**有意设计**
（`test_workspace_context_api.py` 已固化该契约），Phase 1.8 需为其单独规划入口，
不能简单放开白名单。

**验证**：后端 `186 passed`（181 + 5 新增）、前端 `39 passed`（35 + 4 新增）、
`ruff check` 全绿；主库 `20260924_12` / 56 表 / `integrity ok` / FK 违规 0（本轮全程未写主库）。

**遗留（已登记，未处理）**：
1. 40+ 个写接口的跨租户归属校验**实现正确但无测试守护**（审计 #6），建议后续补参数化矩阵；
2. `page_size` 无上限、`page_num<=0` 静默返回第一页（审计 #9），属接口健壮性债务；
3. `test_order_profit_identity` 的校验集合被 `page_size=500` 静默截断（审计 #10）；
4. M6 决策记录目前只有 `discovery` 一处调用，其余 Agent 未接入（审计附带发现）。

**关联**：D12、D13、`docs/CODE_AND_DIRECTORY_STANDARD.md` §8 T-6/T-7、
`docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` §15.5 纪律 5/6。

---

## D15：Phase 1.8 前端身份切 Context —— 优先级规则与「legacy 必须保留」的依据

**日期**：2026-09-24　**范围**：`frontend/src/{permissions,router,api}.js`、
`views/{Layout,Users,PlatformAdmin}.vue`、`backend/app/routers/me.py`

### 一、核心决策：Context 无条件优先，legacy 仅兜底

新增 `resolveIdentity({user, impersonating, context})` 作为**唯一身份解析入口**：

```
context 存在 → 用 context（权威）
否则 user.fromContext → 用 user
否则 user（legacy 小写角色）→ 映射到大写枚举
```

**为什么不能写成「`user.role` 非空就用 user」**：路由守卫会**同时**传 `user`
（兜底）与 `context`（权威）。旧写法会让 legacy 压过 Context——实测：平台账号
代客进入租户后（Context=OPERATOR + `is_impersonating=true`），因 legacy 仍是
`superadmin` 而被放行到 `/platform-admin`，代客隔离形同虚设。

### 二、为什么 legacy 兜底**不能删**（R-07 只做收口、不做删除）

1. ~~**工厂账号拿不到 Context**~~ → **已由 D23（G-3）解决**：`/api/me/workspaces`
   与 `/api/me/workspace-context` 已对工厂账号放行（只读），`/switch` 仍拒。
   本节以下论述保留为**决策历史**，当时的判断与修复均以此为据；
   现行状态请看 D23。
2. **Context 请求失败**（网络抖动 / 后端 5xx）时用户至少还能用。

**收口做法**：legacy 读取集中在 `permissions.js` 的三个常量
（`currentUser()` / `role()` / `LEGACY_ROLE_MAP`），文件头显式声明为**唯一允许处**。
`isSupplier()` / `isSuperadmin()` 也改走 `roleKey()`，不再直接读 localStorage。

**删除前置条件**（D23 更新）：原前置「先为工厂账号开通 Context 通道」
**已完成**。现剩余前置是「Context 请求失败时的降级策略」——兜底需从
「身份来源之一」降级为「异常降级路径」，建议与 Phase 2 Tool Layer 一并处理。

### 三、代客会话的一致性要求

代客涉及 4 个状态：`erp_token` / `erp_user`（纯展示）/ `erp_impersonating` /
Context 缓存。三条路径必须清理一致：

| 路径 | token | user | impersonating | Context |
|---|---|---|---|---|
| 进入代客（`PlatformAdmin.enter`） | 换新 | 保留（展示） | 写入快照 | **清空**（避免平台身份带进租户） |
| 退出代客（`Layout.leave-impersonation`） | 还原 | 还原 | 移除 | **清空**（否则回到平台控制台仍带租户身份） |
| 登出 / 401（`Layout.logout` / `api.js`） | 移除 | 移除 | **移除** | 清空 |

**401 曾漏清 `erp_impersonating`**：代客期间 token 过期 → 重新登录平台账号后
标记仍在 → 守卫把平台管理员当租户身份 → `/platform-admin` 被弹回 `/dashboard`，
**管理员被锁在自己的控制台外**。已修并纳入契约。

### 四、展示数据与权限数据分离（G-2 的裁决）

冻结契约 `docs/phase1_interfaces.md` §7 的 PII 红线规定 Context API **不输出**
`username`/`display_name`（`to_public_dict()` 刻意不含，契约测试用
`set(body) == CONTEXT_FIELDS` 严格固化）。因此：

- **权限/角色**：一律 `roleKey()` / `canAdmin()`（Context 优先）。
- **姓名展示**：保留 `localStorage.erp_user.display_name` 作**纯显示缓存**。
- **代客态展示名**：用 Context 的 `workspace_name` 渲染「平台代管 · {租户名}」，
  不再伪造 `erp_user`（否则运营者在租户工作台看到平台方真名，既困惑又泄露平台身份）。

### 五、本轮修复的真实缺陷（含 zcode 并行工作引入者）

| # | 缺陷 | 严重度 | 来源 | 修法 |
|---|---|---|---|---|
| 1 | **`app/db.py` 用过期 `cols` 变量 → 启动即崩** | **P0** | zcode | `shop_id` 判断前重新 `PRAGMA table_info(orders)`（`cols` 已被 `market_trends` 覆盖，导致每次启动重复 ALTER → `duplicate column name`） |
| 2 | 守卫漏传 `user` → legacy 兜底失效 | **P0** | 本轮改造引入 | 守卫恢复传 `currentUser()`；`resolveIdentity()` 保证 Context 胜出 |
| 3 | legacy 压过 Context（代客隔离失效） | P1 | 本轮改造引入 | `resolveIdentity()` 改为 Context 无条件优先 |
| 4 | `/login` 分支漏传 `context` | P1 | 本轮改造引入 | `defaultLanding(user, impersonating, context)` |
| 5 | 401 漏清 `erp_impersonating` | P1 | 既有 | `api.js` 补移除 |
| 6 | `test_api.py` 步骤下标 off-by-one（`steps[7]` 实为 `review_batch`） | P1 | zcode | 改按 `agent+action` 语义定位 + `seq` 比较 |
| 7 | `test_api.py` 断言不存在的字段 `publish_pending_listing_ids` | P1 | zcode | 改断言真实契约 `context.review_blocked`（含非空 reasons） |
| 8 | `test_shop_archive_and_purge` 恒真断言 `deleted["orders"] >= 0` | P1 | zcode | 改 `> 0`（清理前已确认有数据） |
| 9 | `test_workspace_context` 自比较 `read_only == _READ_PERMISSIONS` | P2 | zcode | 改具体键集合 + 断言无 `:write` |
| 10 | `conftest.py` 的 `ERP_TEST_DB` 无防呆（**误设可删主库**） | **P0** | 审计发现 | 新增 `_guard_test_db_path()`，拒绝 `erp.db`/`test_erp.db` |
| 11 | 代客态展示平台管理员真名 | P2 | 本轮改造暴露 | `Layout.vue` 用 `workspace_name` 渲染「平台代管 · X」 |

**验证方法**：缺陷 2 与缺陷 3 均用「**临时回退修复 → 确认新测试失败 → 恢复**」
证明回归测试有效（缺陷 3 的对照测试确认能抓；缺陷 5 的三端点一致性测试经实测
**当前无可观测差异**，已在用例 docstring 中如实标注为「契约守护」而非「缺陷回归」）。

### 六、审计发现但**判定为既有契约、本轮不改**

1. ~~**工厂账号 `/api/me/*` 403**（G-3）~~：**已由 D23 解决**（放行只读端点）。
2. **`FACTORY_COLLABORATOR` 在 `role_permissions` 表无行**：迁移 `20260923_08`
   的 `ROLES` 常量**有意只 seed 4 个 workspace 角色**（工厂走独立 FACTORY 分支、
   不落 Membership），读取时经 `_permissions_from_db() → None` 回退代码常量。
   已把该「有意缺席」写进 `test_every_role_permissions_table_matches_code_constants`
   的断言，与「意外漏行」区分开。
3. **代客态可写**：`auth.py` 注释曾写「只读操作符」，但代码给的是 `operator`
   （含写权限），且设计文档明确「代客以目标租户身份执行业务」。**以代码与设计
   文档为准**，修正注释；安全边界靠「审计 + token 作用域 + `is_impersonating` 标记」。

### 七、遗留（已登记，未处理）

1. 测试库缺 `workspace_memberships` 表（`create_all` 不含该表，因刻意不注册 ORM），
   导致 Context 的 **MEMBERSHIP 生产路径在 app 层无覆盖**（仅 service 层
   `test_workspace_dual_read.py` 用 tmp_path 手工建库覆盖）。建议 conftest 增加
   「迁移等价建表」步骤。
2. `Layout.vue` 的 computed 依赖非响应式 Context 缓存（当前被守卫 `await` 掩盖），
   代客进出用整页跳转规避；建议后续把 Context 改为 `shallowRef` 暴露。
3. `test_ai_native_p0.py` 的 `pytest.skip("无告警可确认")` 依赖前序用例造数据
   （单跑必 skip），建议用例内自造前置。
4. `test_security.py` 的 `page_size=500` 集合比对会被静默截断（同审计 #10）。

**关联**：D12、D13、D14、`docs/WORKSPACE_MIGRATION_PROGRESS.md` R-07、
`docs/phase1_interfaces.md` §7/§8、`docs/CODE_AND_DIRECTORY_STANDARD.md` §8 T-2/T-3。

---

## D16：测试可信度收口 —— 「断言存在」不等于「行为被守住」

**日期**：2026-09-24　**范围**：`backend/tests/**`、`backend/tests/conftest.py`、
`backend/migrations/versions/20260924_15_*.py`、`backend/erp.db`

### 一、核心问题：本轮的失败全部来自测试本身，而非产品功能

本轮起点是"212 passed"，但其中 3 条**时好时坏**（单跑通过、全量失败）。逐条追查后发现
全部是测试侧缺陷，且分四类：

| 类别 | 形态 | 危害 |
|---|---|---|
| **顺序依赖** | 断言依赖种子存量，而另一文件会 `purge_demo_data` 清空全租户数据 | 单跑绿、全量红；`7 failed` 实测复现 |
| **定时炸弹** | 硬编码日期落在滑动窗口内（30 天 / 28 天 / 365 天） | 到某一天**整批永久失败**，与代码无关 |
| **恒真断言** | `>= 0`、`in ("rule","llm")`、`0 <= x <= 100` | 实现彻底坏掉也照样绿 |
| **自证式断言** | 期望值由被测函数自己推导 | 被测函数返回错值时用例仍通过 |

**教训**：绿灯本身不构成质量证据。一条断言只有在"把被测行为改坏时会失败"时才算数。

### 二、处置原则：一切守护用回退法证明

新增/加固的每条断言都必须做**变异验证**（规范 §8 T-11）：

1. `Copy-Item <file> <file>.bak`
2. 用补丁制造变异（把被守护的行为改坏）
3. 跑测试，**必须失败**
4. 还原，确认 `rg` 找不到变异标记且 `.bak` 已消失

**本轮最重要的发现**：`test_discovery_flow` 里新加的"选品门槛"断言**首版判别力不足**——
把 `pick_candidates(min_total=60)` 变异为 `0` 后，断言**依然通过**。原因是演示租户里
种子商品分数普遍 ≥ 60，占满了 `limit` 窗口，低分商品本来就挤不进来。

改为**隔离租户**场景（新建租户 + 3 个 20 分商品，租户内无其它候选）后，变异立刻被抓到。
这条经历写进规范：**"写了断言"不等于"守住了行为"，回退法是唯一可靠证据**。

### 三、测试库必须与生产库同构（根因修复）

`conftest.py` 原先用 `create_all()` 建表 + 只补跑 2 条迁移，导致：

- **`workspace_memberships` 表根本不存在**（`models.py` 刻意不注册身份模型，避免
  `create_all` 绕过维护窗口门禁）→ `membership_table_available()` 恒 False →
  **MEMBERSHIP 生产路径在 API 层零覆盖**，3 处断言把 `LEGACY_FALLBACK` 固化成"预期行为"；
- **21 处列级漂移**（如 `shops.app_secret` 生产 `VARCHAR(256)`、测试 `VARCHAR(1024)`）→
  "测试能写、生产会拒"。

**修法**：新增 `_upgrade_to_head()`，在**独立子进程**里执行 `alembic upgrade head`。
子进程隔离是必需的：`alembic.ini` 的 `[logger_root]` 会给 root logger 装 `StreamHandler`，
而 pytest 的 `caplog` 依赖自己注入的 handler——root logger 一旦被动过，日志类断言会
**全部静默失败**（实测 `caplog.records` 变空）。

### 四、迁移正确性：表优先于常量（zcode 引入缺陷的根因）

zcode 给 `ROLE_PERMISSIONS` 加了 `compliance:check`，但漏了两件事，构成**生产静默失效**：

1. **没写 `permissions` 目录表** → `role_permissions.permission_key` 有外键指向
   `permissions.key`，迁移在 FK 强制下直接 `IntegrityError` 失败（实测复现）；
2. 即便补上目录行，`_permissions_from_db` 是**表优先**——只改常量在线上不生效。

**决策**：权限变更**必须走迁移**，且迁移里**先插 `permissions` 再插 `role_permissions`**
（downgrade 反向）。`tests/test_workspace_dual_read.py` 已固化"表 ↔ 常量一致"契约。

### 五、迁移编号冲突的裁决原则

zcode 与主代理在 10:12 / 10:14 各自创建了 `20260924_15_*.py`，导致 **Alembic 多 head、
迁移链断裂**。

**裁决：先到者保留编号，后到者修正其缺陷。** 理由：并行协作下重编号会让已落盘的
备份/演练记录（按编号索引）失配；而修正缺陷的成本远低于重编号带来的追溯成本。

### 六、账本漂移的处置（P0，按 runbook 执行）

主库账本 `20260924_13` 落后于代码 head `20260924_15`。处置链路：

冷备（`_erp_backups/erp-20260924-103216.db`，sha256 `4dc1078b...`，57 表 / 3149 行，
`changed_during_backup=false`）→ **副本演练**（`_erp_backups/drill15/` 上跑通迁移，
预检 12 项全 PASS）→ 主库 `upgrade head` → 复验。

**结果**：57 表 / 3153 行 / `integrity ok` / FK 违规 0 / 预检 **12 项全 PASS（`P0_fail=0`）**；
**数据零损失**——除权限表按设计 +1/+3 行，其余 55 张表行数完全不变。

**注意**：`init_db()` 只做 `create_all` + 补列，**不会**跑 alembic 迁移。新增迁移后
必须手动执行，否则账本会再次漂移（这正是本轮漂移的成因）。

### 七、回归基线

| 项 | 结果 |
|---|---|
| `pytest -q` | **231 passed** |
| `pytest -q`（**反序文件列表**） | **231 passed**（顺序依赖消除的直接证据） |
| `pytest test_shop_archive_and_purge.py test_api.py`（原 7 failed） | **34 passed** |
| `npm test` | **67 passed** |
| `ruff check .` | All checks passed |
| `migration_preflight.py` | 12 项全 PASS，`exit=0` |

### 八、第十轮：弱断言全面收口与 schema 漂移复核

#### 8.1 恒真/弱断言逐条修正（全部经回退法验证）

| 位置 | 原断言的问题 | 修正后的断言 | 回退法验证 |
|---|---|---|---|
| `test_api.py:160` 合规检测 | `risk_level in ("low","mid","high")` 三值全覆盖，恒真 | 按 `_scan` 契约复算 score/risk，并断言干净商品 `issues == []` 且 `risk_level == "low"` | 变异扣分 `-20` → **抓到** |
| `test_api.py:480` 数据质量 | `grade in ("low","medium","high")` 恒真 | 按 `quality_report` 判定式复算 grade，断言 `commercial_ready` 与 grade 一致 | 变异 `real_count >= 20 → 0` → **抓到** |
| `test_api.py:911` 代客审计 | `total >= 1 or len(items) >= 1` 两侧同值，冗余 | 断言 `total == len(items)`，且本次 enter 恰好新增 1 条该租户记录、最新一条 `tenant_id/action` 正确 | 变异 `total +1`、`tenant_id +999` → **均抓到** |
| `test_platform_adapters.py:262` | `in ("planned","restricted")` 无法发现两平台状态互换 | 改为逐平台精确期望值字典 | 变异 shopify `planned→restricted` → **抓到** |
| `test_shop_archive_and_purge.py:53` | `in (200,404)` 使归档幂等与路由不存在不可区分 | 钉死 `== 404` 且 `detail == "店铺不存在"` | 变异重复删除返回 200 → **抓到** |
| `test_security.py:184` | `in (302,307)` 无法区分正确跳转与任意跳转 | 钉死 `== 307` 且 `location == "/shops?auth=failed"` | 变异跳转目标 → **抓到** |
| `test_deep_domains.py:313/315` | `in (200,400)` 掩盖"该给默认值却报错"的回归 | 钉死 200，并按 `calc_profit` 契约复算利润公式（成本除汇率、扣佣金）与 margin | 变异漏扣佣金 → **抓到** |
| `test_api.py:753` | `in (200,400)` 连"明错误"与"静默成功"都区分不了 | 钉死 400，且 detail 同时含 `1688` 与 `货源店铺` | 变异 1688 `role` 改 `sales` → **抓到** |

#### 8.2 越权矩阵覆盖缺口补齐

`test_security.py` 的权限矩阵此前**完全未覆盖 M4 的 6 个端点**。已补入
`/api/knowledge/candidates`（读）、`/learning/settings`（读/写）、candidates 的
answer/approve/reject/revoke（写），并加"放行角色必须真正抵达业务逻辑"的
404 断言。回退法：把 `set_learning` 的 `require_write` 换成 `get_current_user`
→ **立刻抓到 viewer 越权写配置**（此前零覆盖）。

#### 8.3 schema 漂移：实测复核（**修正 D16 原文的截断说法**）

本轮用两条独立建库路径实测：

| 对比 | 结果 |
|---|---|
| 测试库 `create_all + alembic head` vs 纯 `alembic head`（空库） | **列级差异 0、表差异 0** |
| 生产库 vs 测试库 | **列级差异 21 处** |

**结论修正**：21 处差异是「生产库落后于当前模型」的历史欠账，**不是**测试库缺陷
（测试库两条路径一致，说明 `create_all` 与迁移链已收敛）。差异构成：

- **18 处可空性**：生产库可空、模型/测试库 `NOT NULL`。实测主库这些列 **NULL 行数全为 0**，
  可安全收紧。
- **3 处列宽**：`shops.app_secret`（生产 256 / 模型 1024）、`access_token`、
  `refresh_token`（生产 1024 / 模型 2048）。**实测主库这三列数据全为空**（11 行 shops，最大长度 0）。

**D16 原文「明文超 ~120 会被截断」的说法不成立**，实测 SQLite 行为：

```
声明 VARCHAR(8)，写入 5000 字符 -> 实际存储 = 5000 | 截断: False
NOT NULL 插入 NULL: 被拒绝 -> NOT NULL constraint failed
```

即 SQLite **不强制 VARCHAR 长度**（无截断），但**强制 NOT NULL**。因此真实风险
排序与原文相反：可空性差异（18 处）比列宽差异（3 处）更接近真实风险，但
**当前生产数据均满足收紧条件**，两者都尚未造成后果。收敛动作放在 Phase 2
切 MySQL/PG 时执行（换库会真正强制长度与 NOT NULL）。

#### 8.4 本轮新增守护

- `test_role_permission_matrix` 新增 M4 六端点 + 业务逻辑抵达断言（回退法已验证）。
- 弱断言清零：`rg` 复查 `in (200, 400)` / `in (200, 404)` / `in (302, 307)` /
  `>= 1 or len` 在测试中**仅剩 0 处**同类模式。

#### 8.5 主库残留测试数据：隔离性实测（**新发现的既有事实，非本轮引入**）

**现象**：主库 `erp.db` 中存在测试命名的数据——`users` 里 `probe-user-tmp` /
`iso_b` / `factory_portal_test` / `compliance_test` / `probe_x`（共 5 个），
`products` 里「权限探针」「门禁验证商品 无图」「测试缺货商品 采购流程」等（共 7 条），
以及对应的 `listings` / `compliance_reports` / `product_scores` 派生行。

**是否本轮造成**：**否**。全部记录 `created_at ≤ 2026-09-24 02:39:28`，而本轮所有
操作发生在 12:00 之后，且主库 `-wal` 最后写入时间为 11:54:40（本轮未写主库）。

**决定性隔离性实测**（本轮执行）：

| 步骤 | 主库 SHA256（前 32 位） | 总行数 |
|---|---|---|
| 全量 `pytest -q` 前 | `1d6a3dc058bdd8ec5b00344d62b03239` | 3,169 |
| 全量 `pytest -q` 后（231 passed） | `1d6a3dc058bdd8ec5b00344d62b03239` | 3,169 |

**结论**：当前测试套件**完全不写主库**（连 WAL 都不变），隔离机制有效。
主库残留数据来自更早的排查过程（当时可能未设 `ERP_DB_URL` 或手工连过主库）。

**处置建议（未执行，需人工确认）**：这些行属"脏演示数据"，删除会影响
`compliance_reports` / `product_scores` / `listings` 的外键链。因涉及主库写操作，
按 `AGENTS.md` §2 须先冷备 + 走 runbook，**留给项目负责人裁决**。

**为什么记录**：它是「主库行数 3,153 → 3,169」这一差异的完整解释。若不记录，
下次核对 `WORKSPACE_MIGRATION_PROGRESS.md` 的行数清单时会误判为"迁移丢了/多了数据"。

### 九、遗留（已登记，未处理）

1. **21 处列级漂移**（见 8.3 实测）：生产库落后于模型，当前无实际后果，
   Phase 2 换 MySQL/PG 时收敛。**主库凭证列当前全为空，无截断风险**。
2. **无清理写入**：`test_api.py`、`test_security.py:72`、`test_setting_scope.py:26/119`
   创建租户后从不删除，跨文件累积全局租户行。**已实测确认无任何断言依赖租户
   数量**（`rg` 全库无 `Tenant.count` 类断言），故不构成顺序依赖，仅影响整洁度。
3. **迁移 `20260924_14` 的 nullable 与 tenant 外键**：迁移脚本未声明 `nullable=False`
   （模型是非 Optional），也未按规范 §7.6 声明 `tenant_id → tenants.id` 外键。
   当前库因表是 `create_all` 建的而"恰好正确"，Phase 2 换库时会暴露。
4. **`page_size` 无上限**（审计 #10）：`test_security.py` 集合比对可能被静默截断。
5. **G-3 工厂账号 Context 通道**：Phase 1.8 删除 legacy 兜底的唯一前置，待产品决策。

**关联**：D14、D15、`docs/WORKSPACE_MIGRATION_PROGRESS.md`、
`docs/子代理实施索引-20260923.md` 第九轮、`docs/CODE_AND_DIRECTORY_STANDARD.md` §8 T-8/T-11。

---

## D17：可行性验证必须真启动服务 —— 验收脚本自己失灵把"功能正常"误报为"功能坏了"（2026-09-24）

### 一、问题：231 个测试全绿，但没有一条验证过"服务能跑起来"

截至本轮，后端 231 个测试**全部使用进程内 `TestClient`**（`fastapi.testclient`），
没有任何一条：

- 真正启动过 uvicorn 进程；
- 加载过前端构建产物（`frontend/dist`）并验证静态托管可用；
- 走过一次真实 TCP/HTTP 请求。

于是"项目可实际运行"这个结论一直**只有间接证据**。本轮补做真实启动验证，
并立刻暴露了问题。

### 二、真启动验证的执行方式（关键：不碰主库）

| 步骤 | 做法 | 目的 |
|---|---|---|
| 1 | `python scripts/backup_restore_drill.py backup --db erp.db` | 按 `AGENTS.md` §2 先冷备 |
| 2 | 把冷备复制为 `_smoke/smoke.db` | 验收在**副本**上跑 |
| 3 | `ERP_DB_URL=.../smoke.db` 启动 uvicorn（端口 8123/8124） | 真实进程 + 真实 HTTP |
| 4 | 跑 `scripts/live_acceptance.py http://127.0.0.1:8124` | 4 条业务闭环 |
| 5 | 结束后比对主库 SHA256 与行数 | 证明隔离有效 |

**主库隔离证据**（全程实测）：

| 时点 | 主库 SHA256（前 32 位） | 总行数 |
|---|---|---|
| 验收前 | `1d6a3dc058bdd8ec5b00344d62b03239` | 3,169 |
| 验收后 | `1d6a3dc058bdd8ec5b00344d62b03239` | 3,169 |

### 三、发现：7 步里 2 步 FAIL，但**业务功能全部正常**——是脚本自己有三处缺陷

| # | 现象 | 根因 | 性质 |
|---|---|---|---|
| 1 | 采购闭环 FAIL（`无可用货源报价`） | 脚本取 `GET /products` 的**第一个**商品建单，该商品恰好无 `supplier_offers` 记录 | **脚本选错商品** |
| 2 | 订单闭环 FAIL（`unable to parse string as an integer`，order_id=None） | 脚本传 `platform="shopee"`，而 `/orders/sync` 是**演示订单入口**，只接受 `demo:<平台>`（真实平台名返回 409） | **脚本用错接口语义** |
| 3 | 修完 1、2 后采购仍 FAIL | 断言要求「该供应商应付**总额归零**」，但供应商 1 有种子数据里的历史未结清结算单（`ST#3 pending / 158.4`） | **断言对象错误**（应断言"本次生成的结算单已 paid"） |

**逐条反证**（证明功能本身正常）：

- 直接按数据库里"有在库报价"的 `product_id=1` 走完整链：
  `POST /purchases` 200 → `receive` 200（`onhand 53→56`）→ `settlements/generate` 200
  → `confirmed` → `paid` 200 → 该结算单未结清额归零。**采购闭环完全正常**。
- 把 `platform` 换成 `demo:shopee`：`/orders/sync` 200 返回 3 单 →
  `ship` 200（拿到 `tracking_no`）→ 退款建单/审批/退货入库/退款 全 200，
  订单状态联动为 `refunded`。**售后闭环完全正常**。

### 四、修正（`backend/scripts/live_acceptance.py`）

1. 新增 `_product_with_stock_offer()`：显式探测"有在库报价"的商品，
   探测不到时报 **`SKIP`** 并说明"数据前提缺失，不是功能缺陷"——**不再伪装成 FAIL**。
2. `platform` 改为 `demo:shopee`，并在注释写明该入口的语义边界。
3. 采购断言改为校验**本次生成的结算单**状态，而非全局汇总值。
4. 汇总输出新增 `SKIP` 计数与原因列表。

**修正后**：`共 7 步：PASS 7 / FAIL 0 / SKIP 0`，`exit=0`。

### 五、决策与规范固化

新增两条强制规则（`docs/CODE_AND_DIRECTORY_STANDARD.md` §8）：

| 编号 | 规则 |
|---|---|
| T-12 | **验收脚本自身必须可靠**：前置数据必须显式探测（不得假定 `items[0]` 可用）；数据前提缺失报 `SKIP` 而非 `FAIL`；断言必须针对"本次操作产生的对象"，不得针对"全局汇总值" |
| T-13 | **可行性验证必须真启动服务**：进程内 `TestClient` 全绿 ≠ 可部署；涉及"可实际运行"的结论必须真启动 uvicorn + 真实 HTTP + 静态前端可访问，且**在数据库副本上执行** |

### 六、为什么这条记录重要

`TestClient` 全绿会让人误以为"已经验证过了"，从而**长期不做真启动验证**。
而验收脚本一旦自己不可靠，产生的是：

- **假失败** → 浪费排查时间，甚至诱发"把正常功能改坏"的错误修复；
- **假通过** → 掩盖真缺陷，比没有脚本更危险。

**结论：验证手段本身也需要被验证。** 这与 D16（"断言存在"不等于"行为被守住"）
是同一条原则在更高层面的体现——从"断言"上升到"验证工具链"。

### 七、隔离性检测的有效性验证（回退法，**过程中真的写坏了主库并已完整恢复**）

按 T-11 的要求，对 `e2e_feasibility.py` 的**隔离性检测能力**本身做了回退法验证：
把 `env` 里的 `ERP_DB_URL` 覆盖删掉，让服务连回默认主库。

**预期**：脚本第 7 步应报 `exit=2`（隔离失效）。**实测**：确实报 `exit=2`
——但代价是**主库真的被写了 61 行**（这正是它要检测的场景）。

| 时点 | 主库总行数 | 说明 |
|---|---:|---|
| 变异前 | 3,169 | 干净基线 |
| 变异跑完后 | 3,230 | +61 行（变异测试产生的演示数据） |

**为什么 sha256 相同而行数不同**：SQLite WAL 模式下新数据先写 `erp.db-wal`，
主库文件本身未变。**这是一条重要教训：WAL 模式下"文件哈希未变"不能证明"数据未变"，
必须同时比对行数或强制 checkpoint。** 本脚本已同时比对 SHA256 与行数（`_row_count`）。

**恢复过程（按 runbook）**：
1. 先冷备当前含残留的状态（`erp-20260924-131822.db` / 3,230 行）以备追溯；
2. 停掉所有 python 进程（释放 SQLite 文件句柄）；
3. 删除 `erp.db` + `-wal` + `-shm`（**必须删 WAL，否则残留数据会被回放**）；
4. 从干净的 `erp-20260924-131713.db`（3,169 行 / integrity ok）复制回来。

**恢复验证**：

| 指标 | 恢复后实测 | 期望 |
|---|---|---|
| 总行数 | 3,169 | 3,169 |
| 表数量 | 57 | 57 |
| `integrity_check` | ok | ok |
| `foreign_key_check` 违规 | 0 | 0 |
| `alembic_version` | `20260924_15` | `20260924_15` |
| 关键表 | users 9 / orders 521 / products 53 / listings 39 | 与变异前一致 |
| `migration_preflight.py` | 12 项全 PASS（`P0_fail=0`） | 全 PASS |
| `pytest -q` | 231 passed | 231 passed |

**结论**：隔离性检测**确实有效**（能抓到主库被写），且 runbook 恢复流程**可用**
（从发现到恢复完整、零数据损失）。但本次也说明：**验证隔离性的回退法本身有风险**
（会真的写坏主库），必须在有可靠冷备的前提下做，且事后必须完整验证恢复。

**已留档**：`backend/backups/erp-20260924-131822.db`（含变异残留，可追溯）与
`erp-20260924-131713.db`（干净基线）。两者均保留，不删除。

---

## D18：仓库纳入 Git —— 唯一 P0 债务清零（2026-09-24）

### 一、背景

自项目启动以来仓库**无 `.git`**（见规范 §1、DEBT-01、R-01）。后果：

- `.gitignore` / `.dockerignore` / `.github/workflows/ci.yml` **全部未生效**；
- 唯一回滚手段是手工冷备，**代码本身无任何版本历史**；
- 并行工具（zcode）与主代理反复发生「文件同改、迁移编号撞车」，无冲突检测能力。

`git init` 按规范 §1 须由项目负责人确认。本次获得明确授权（用户「按你推荐的来」）后执行。

### 二、执行前的安全体检（先查后做，全部实测）

| 检查项 | 方法 | 结果 |
|---|---|---|
| 危险文件是否会被入库 | `git add --dry-run .` 逐项核对 | 208 文件中 `.db` / `-wal` / `node_modules` / `dist` / `.log` / 临时脚本**均 0 命中** |
| 密钥泄漏 | 正则扫描 `AKIA*` / `sk-*` / PEM 私钥 / `secret=` 赋值 | **0 命中**；`.env.example` 全为占位符 |
| 忽略规则是否覆盖冷备 | `git check-ignore -v` 逐项实测 | 补齐后 10 项关键路径全部命中 |
| 行尾一致性 | 扫描 197 个文本文件 | 181 LF / 2 CRLF / **14 混合**；`core.autocrlf=true` |

### 三、发现并修复的三个真实隐患（**若不体检就会踩**）

1. **`.gitignore` 缺口：冷备目录完全未覆盖。**
   `backend/backups/`（10 个 2.3 MB 冷备库）、`_erp_backups/`、`_wip_backup/` 都不在忽略列表。
   原因：`backend/*.db` **不匹配子目录**。若直接提交，会一次性灌入约 25 MB 数据库文件。
   → 已显式声明三个目录。

2. **`.gitignore` 缺口：临时脚本与变异残留。**
   根目录 `_h.py` / `_w.py` / `_chk*.py`（一次性探测脚本）与 `test_api.py.orig`
   （回退法残留备份）会被入库。→ 已加 `/_*.py`、`*.orig`、`*.bak`、`*.rej`。

3. **`docker-entrypoint.sh` 会被写成 CRLF，容器启动即失败。**
   本机 `core.autocrlf=true`，而该文件仓库内为 LF。检出到 Linux 时变成 CRLF，
   容器报 `bad interpreter: /bin/sh^M`——**这是「本地一切正常、部署就崩」的典型缺陷**。
   → 新增 `.gitattributes`：`* text=auto eol=lf`，`*.sh` / `Dockerfile` 强制 LF，
   `*.db` 等声明 `binary`，`package-lock.json` 折叠 diff。

### 四、执行结果

| 指标 | 值 |
|---|---|
| 命令 | `git init -b main` |
| 首次提交 | `6215d49` — `chore: 首次纳入版本控制（R-01）` |
| 纳入文件 | **208 个**（`backend/` + `frontend/` + `docs/` + 部署与协作配置） |
| `.git` 体积 | **0.87 MB**（223 objects） |
| `git fsck` | 干净（exit 0） |
| 提交后工作区 | 干净（0 未跟踪 / 0 修改） |
| 忽略规则实测 | 11 项关键路径中 10 项命中；唯一「未忽略」为 `.env.example`（**应当入库**，是模板） |

### 五、规范固化

| 编号 | 规则 |
|---|---|
| V-1 | 冷备目录（`backend/backups/`、`_erp_backups/`、`_wip_backup/`）、根目录 `_*.py`、`.orig`/`.bak`/`.rej` **一律禁止入库**；`.gitignore` 与 `.dockerignore` 必须**双写** |
| V-2 | 新增任何「子目录下的产物」时，必须实测 `git check-ignore -v <路径>`——通配符**不跨目录**，`backend/*.db` 挡不住 `backend/backups/x.db` |
| V-3 | 行尾由 `.gitattributes` 锁定 LF；shell 脚本与 `Dockerfile` 一旦变成 CRLF，容器会 `bad interpreter` |
| V-4 | 首次提交（或大范围 `git add`）前，必须先 `git add --dry-run` 核对清单，确认危险文件 0 命中后才提交 |

### 六、后续

- 日常开发改为「小步提交」，提交信息遵循 `<域>: <动作> <对象>`；
- `main` 分支保护与远端仓库（GitHub/GitLab）**尚未配置**——属部署层事项，需负责人决定托管位置后执行；
- CI（`.github/workflows/ci.yml`）现已被 Git 识别，但**仍需推送到远端才会真正触发**。

---

## D19：分页参数必须有上限 —— 静默截断会让「隔离比对」假绿（2026-09-24）

### 一、问题（审计 #10 / DEBT-27）

13 个列表端点的 `page_size: int = 20` **没有上界**，带来两个后果：

1. **可被拉全表**：`page_size=10**9` 会把整表读进内存再序列化，是廉价 DoS 面；
2. **静默截断更危险**：调用方用大 `page_size` 做「集合比对」时，
   若实际数据比页大小多一条，返回的第一页**看起来完全正常**，漏掉的记录不会被发现。

### 二、实测证据：测试库恰好卡在临界点

修复前实测（临时探测用例，跑完即删）：

| 端点 | `total` | `page_size=500` 取回 | 是否截断 |
|---|---:|---:|---|
| `/api/orders` | **500** | 500 | 否——**恰好相等** |
| `/api/products` | 24 | 24 | 否 |
| `/api/knowledge/docs` | 8 | 8 | 否 |

**`total` 与硬编码的 500 完全相等**，意味着当时只是「侥幸没截断」：
seed 一旦增加订单数，`test_security.py` 的跨租户订单比对与
`test_deep_domains.py` 的利润恒等式核对就会**静默漏掉多出来的订单**（假绿）。

**主库更能说明问题**：`security_data_audit.py` 里写死 `page_size=500` 并注释
「演示库订单 500 条，分页取 500 应全覆盖」——而主库实际已有 **518 条**，
即**最后 18 条从未被审计过**，脚本却仍会打印「已全覆盖」。这是自欺式通过。

### 三、处置

1. **新增 `app/pagination.py`**：`MAX_PAGE_SIZE = 200`，
   `PageNum = Query(1, ge=1)`、`PageSize = Query(20, ge=1, le=MAX_PAGE_SIZE)`。
2. **13 个列表端点**统一改用这两个依赖（`admin/auth/compliance/discovery/knowledge/
   listings/orders/pricing/products/purchases/refunds/settlements/support`）。
3. **上限取 200**：覆盖全部前端用法（最大 200，`views/Refunds.vue`），
   并与既有 `limit` 类参数上限（`ai.py`/`listings.py`/`admin.py`）保持一致。
4. **快速失败而非静默截断**：越界返回 **422**，强制调用方改成分页遍历。
5. **提供遍历工具**：`tests/conftest.py` 新增 `fetch_all` 夹具，
   `scripts/security_data_audit.py` 新增 `get_all`——按 `total` 逐页取完再合并，
   并断言「取回条数 == total」，数据增长或并发写入都不会静默漏。

### 四、修复后被测试立刻抓出的 3 处依赖「无上限」

加上限后全量跑，**3 个测试当场失败**（`KeyError: 'items'`，即拿到 422）：

| 测试 | 原写法 | 改法 |
|---|---|---|
| `test_security.py::test_cross_tenant_isolation` | `page_size=500` 比对订单集合 | 改 `fetch_all`（分页遍历） |
| `test_security.py::test_data_consistency_after_flows` | `page_size=500` 取订单字典 | 改 `fetch_all` |
| `test_deep_domains.py::test_order_profit_identity` | `page_size=500` 逐条核对利润 | 改 `fetch_all` |

这正是上限约束的价值：**把「将来会静默出错」变成「现在立刻报错」。**

### 五、回退法验证（证明守护有效）

| 变异 | 期望 | 实测 |
|---|---|---|
| 去掉 `PageSize` 的 `le=MAX_PAGE_SIZE` | 测试失败 | ✅ `test_pagination_edge` 失败（`assert 200 == 422`） |
| `fetch_all` 只取第一页（**保留**总数断言） | 测试失败 | ✅ 隔离测试与利润核对均失败 |
| `fetch_all` 只取第一页（**同时删掉**总数断言） | — | ❌ **没被抓到** |

**第三行是本轮最重要的教训**：变异时若把「被测逻辑」和「守护断言」一起改掉，
等于自己拆掉了报警器，回退法会给出「守护无效」的假结论。
**正确做法：只变异被测逻辑，保留断言**——第二次重做后立刻被抓到。

### 六、规范固化

| 编号 | 规则 |
|---|---|
| P-1 | 列表端点的 `page_size` 必须有上限（`app/pagination.py` 的 `MAX_PAGE_SIZE`），越界返回 422 |
| P-2 | 需要全量数据时**必须分页遍历**（`fetch_all` / `get_all`），禁止用大 `page_size` 一把梭 |
| P-3 | 遍历函数必须断言「取回条数 == total」，防止并发写入或分页缺陷导致的静默漏数据 |
| P-4 | 审计/校验脚本**禁止抽样**：抽样得出的「无问题」结论不成立（主库 518 条却只审 500 条即为例证） |
| T-14 | 回退法变异**只能改被测逻辑**，不得同时修改守护断言——否则报警器被自己拆掉，结论无效 |

### 七、回归基线（2026-09-24 实测）

| 项 | 结果 |
|---|---|
| 后端 `pytest -q` | **231 passed** |
| `ruff check .` | All checks passed |
| `e2e_feasibility.py` | **7 步全 PASS / exit=0**，主库隔离性成立（3169 行未变） |
| 前端 `page_size` 用法 | 全部 ≤ 200，无需改动 |


---

## D20：主库残留计划任务必须停用 —— 测试残留会变成「持续运行的后台任务」（2026-09-24）

### 一、发现经过

核对主库时发现 `erp.db-wal` 反复被写、总行数却不变（始终 3,169），
逐字段比对后定位到根因：**`schedules` 表的 `run_count` / `last_run_at` 在递增**。

进一步排查：主库有 **11 个测试残留的计划任务处于 `enabled=1`**
（10 个 `probe` + 1 个 `验收-趋势扫描`），`interval_minutes=60`，
**每小时真实执行一次**，已各累计 50 次以上。

### 二、为什么这比「静态脏数据」严重

| | 静态脏数据 | 残留的启用任务 |
|---|---|---|
| 影响 | 只污染查询结果 | **持续消耗资源、持续写库** |
| 何时发作 | 被读到才发作 | **每次服务启动就开始跑** |
| 能否被忽略 | 可以（不查即无感） | 不可以（后台线程自主触发） |

机制：`app/main.py` 的 `lifespan` 调用 `start_scheduler()`，
后台线程每 30 秒扫描 `enabled=1` 的任务，到点即执行（`services/scheduler.py`）。
**测试残留任务只要被创建过且没停用，就会永久进入生产调度队列。**

本轮实测影响面有限（`trend_scan` 是幂等 upsert，只更新 12 条 `market_trends` 的
数值与时间戳，不新增行），但这属**运气**：若残留的是 `workflow` 类任务，
会真实触发下单/定价等业务动作。

### 三、处置（可逆，不删行）

```sql
UPDATE schedules SET enabled = 0
WHERE name LIKE '%probe%' OR name LIKE '%验收%';
```

处置前冷备 `backend/backups/erp-20260924-150445.db`。
**保留行而不删除**：`run_count` / `last_run_at` 是排查线索，删掉会丢失取证信息。

| 指标 | 处置前 | 处置后 |
|---|---:|---:|
| `enabled=1` 的任务 | 12 | **1**（仅合法的「每日市场趋势扫描」） |
| 总行数 | 3,169 | 3,169（**零删除**） |
| `integrity_check` / FK 违规 | ok / 0 | ok / 0 |
| 预检 | 12 项全 PASS | 12 项全 PASS |
| `e2e_feasibility` | 7 步全 PASS | 7 步全 PASS |

### 四、规范固化

| 编号 | 规则 |
|---|---|
| S-7 | 测试**禁止**在业务库创建 `schedules` 记录；确需验证调度逻辑时，必须用测试库并断言清理 |
| S-8 | 排查主库异常时，**必须检查 `schedules.enabled`**：残留任务会持续运行，不会被「不查询」规避 |
| S-9 | 处置主库数据优先选择**可逆操作**（置 `enabled=0`）而非删除行；删除会丢失取证线索 |

### 五、遗留

主库仍有 2 个 probe 用户与 13 个 probe 商品（静态脏数据，未处置）：
删除会牵动 `compliance_reports` / `product_scores` / `listings` / `orders` 外键链，
需先出清理方案（含拓扑序删除）再执行。**已登记，待裁决。**


---

## D21：Docker 生产镜像端到端实测 —— 从「构建通过」到「真的能跑」（2026-09-24）

### 一、为什么必须做这一步

D8 定下了生产部署基线（compose 门禁、容器跑迁移、HEALTHCHECK、非 root 用户），
但此后**从未实测过完整镜像**。而本轮改动（依赖锁定、`.gitattributes` 行尾策略）
恰好都落在构建链路上：

- `Dockerfile` 从 `requirements.txt` 改为 `requirements.lock.txt`；
- `.gitattributes` 新锁定 `*.sh` 为 LF。

两者任一失效，都会造成「本地测试全绿、镜像起不来」。因此必须真构建 + 真运行。

### 二、实测过程与结果

| 步骤 | 命令/方式 | 结果 |
|---|---|---|
| 前端构建 | `npm run build` | ✅ 27.57s 成功 |
| 镜像构建 | `docker build --target runtime -t ai-erp-verify:latest .` | ✅ exit=0 |
| 依赖版本核对 | 容器内 `pip list` | ✅ fastapi 0.141.1 / uvicorn 0.53.0 / starlette 1.7.0 / alembic 1.20.0 —— **与锁定清单逐项一致** |
| 生产镜像纯净性 | 容器内查 `pytest` / `ruff` | ✅ **均不存在**（验证「pytest 移出运行时依赖」生效） |
| 入口脚本行尾 | `od -c /usr/local/bin/docker-entrypoint.sh` | ✅ 首行 `# ! / b i n / s h \n` —— **LF，非 CRLF**（`.gitattributes` 生效） |
| 容器启动 | `docker run` + 生产模式三项必填密钥 | ✅ 启动成功，entrypoint 自动跑完迁移（日志见下） |
| 健康检查 | `GET /api/health` | ✅ 200 `{"ok":true,"app":"AI-Commerce ERP"}` |
| 静态前端 | `GET /` | ✅ 200，945 字节 |
| **真实登录** | `POST /api/auth/login`（用 `ERP_ADMIN_PASSWORD` 设的口令） | ✅ 200，user=admin |
| **业务接口** | `GET /api/products?page_size=5`（带 token） | ✅ 200，total=24，取回 5 |

容器内迁移日志（entrypoint 自动执行）：

```
[Revision 14] knowledge_candidates 已存在，跳过
[Revision 15] permissions 新增 compliance:check
[Revision 15] 已插入权限映射: ['OWNER->compliance:check', ...]
[entrypoint] 启动应用：python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

数据卷 `/data` 正常生成 `erp.db` + `-shm` + `-wal`（WAL 模式生效），属主为 `erp`（非 root）。

### 三、过程中的一个「假失败」

首轮用 `-p 18080:8000` 映射端口，容器内 `GET /api/health` 明明 200，
宿主机访问却 **404**。排查发现 **18080 被本机另一个项目的 node 服务占用**
（`D:
odejs
ode.exe`，PID 3864）——与本项目无关。

换随机空闲端口后全部通过。**教训**：本机并行跑着多个项目，
做端口相关验证时必须**动态取空闲端口**，不能写死常见端口；
否则会把「端口冲突」误判为「应用起不来」。

### 四、规范固化

| 编号 | 规则 |
|---|---|
| DP-1 | 改动构建链路（`Dockerfile` / 依赖文件 / `.gitattributes` / 入口脚本）后，**必须真构建镜像并真运行容器**，不能只跑单元测试 |
| DP-2 | 容器验证必须覆盖：依赖版本与锁定清单一致、生产镜像不含测试工具、入口脚本为 LF、健康检查 200、**真实登录 + 一个业务接口调用** |
| DP-3 | 端口相关验证必须**动态取空闲端口**（`socket.bind(("127.0.0.1", 0))`），不得写死——本机并行项目会占用常见端口，导致误判 |

### 五、边界（未做的事，避免误读为「已可上线」）

- **TLS 已于 D22 落地**（DEBT-23 完成）：本节的「容器可运行」结论仍不等于
  「可对外暴露」——TLS 配置由 `docker-compose.tls.yml` + `Caddyfile` 提供，
  需按 `scripts/tls_feasibility.py` 验证后使用（见 D22）；
- 本次验证在**本机 Docker Desktop** 完成，未在真实云主机/编排环境验证；
- 镜像验证后已清理（`docker rmi`），未留残留镜像或容器。

### 六、固化：`scripts/docker_feasibility.py`（11 项检查，一条命令复验）

上述验证已固化为脚本，避免下次改构建链路又要临时拼命令：

```bash
cd backend && python scripts/docker_feasibility.py            # 完整：构建 + 运行
cd backend && python scripts/docker_feasibility.py --skip-build  # 复用镜像
```

检查项：前端产物 / Dockerfile 引用锁定清单 / 镜像构建 / 依赖版本逐项一致 /
不含 pytest·ruff / 入口脚本 LF / 容器启动 / 健康检查 / 静态前端 /
真实登录 / 业务接口调用。

### 七、回退法验证（含一条"检查项不足"的教训）

| 变异 | 期望 | 实测 |
|---|---|---|
| 镜像内额外 `pip install pytest` | 失败 | ✅ `[FAIL] 不含 pytest/ruff` |
| 锁文件把 `fastapi` 钉到 0.115.0 | 失败 | ✅ 构建阶段即失败（exit=3），也算检出 |
| **Dockerfile 改回用 `requirements.txt`**（无锁定） | 失败 | ❌ **第一版没被抓到** |

**第三行是重要教训**：`requirements.txt` 的兼容上限（`fastapi>=0.115,<1.0`）
恰好解析出了与锁定清单**相同的版本**，于是"版本比对"通过——
**脚本只能验「装了什么」，验不出「装的是不是锁定清单」**。
这属于「检查项覆盖不足」，不是脚本 bug：锁定清单的价值在于**确定性**，
而"这次恰好解析一致"不代表下次也一致。

补了一项**结构检查**（`Dockerfile` 必须引用 `requirements.lock.txt`）后重跑同一变异，
立刻被检出。**两项互补**：一个验「装的是锁定清单」，一个验「装的版本对得上」。

> 与 D19 的 T-14 是同一条原则的两个侧面：
> T-14 说"变异时别把报警器一起拆掉"；
> 这里说"报警器本身可能测不到你想测的东西，必须用变异验证它的覆盖范围"。

### 八、补充规范

| 编号 | 规则 |
|---|---|
| DP-4 | 验证"是否使用了锁定清单"必须做**结构检查**（如 grep Dockerfile），不能只比对安装结果——兼容区间可能恰好解析出相同版本 |
| DP-5 | 新增任何验证脚本后，必须用**回退法逐项验证每个检查点的判别力**；"整体通过"不代表每个检查点都有效 |
## D22：TLS 落地 —— 并把「修复」里藏的 3 个缺陷挖出来（2026-09-24）

**背景**：DEBT-23（无 HTTPS / 反向代理）是唯一未清的 **P0**。上一轮已加了配置开关、
Caddyfile 与 TLS compose 覆盖层，但**一行都没验证过**。本轮先跑验证，结果：
改动本身带来 **3 个真实缺陷**，其中 1 个是 P0 级「比不改更糟」。

### 一、上一版改动的三个真实缺陷

| # | 缺陷 | 后果 | 证据 |
|---|---|---|---|
| 1 | `main.py` 直接 `from starlette.middleware.proxy_headers import ...` | **开关一打开就崩**（import 阶段 `ModuleNotFoundError`） | 该模块在 starlette 1.x **已被移除**；实测本机 1.3.1、镜像内 1.7.0 均 `ModuleNotFoundError`。关着时一切正常，**只有真部署才触发** |
| 2 | `ERP_TLS_TERMINATED_ELSEWHERE` 用「非空即真」判断 | 写 `=0`（本意关闭）被当成「已声明 TLS」→ 门禁放行 | `bool(os.getenv(...))` 对 `"0"` 为真 |
| 3 | 门禁要求声明 TLS 位置，但基础 `docker-compose.yml` 没声明 | **README 的「Docker 一键部署」实际不可用** | `docker_feasibility.py` 实测 FAIL 2 项（容器启动即被门禁拒绝） |

第 1 条的性质值得单独说明：它不是「功能没做完」，而是**负向交付**——
缺陷只在开关打开时出现，而开关默认关闭，因此**本地测试全绿、CI 全绿**，
直到有人在生产上启用它。这正是 T-13（「可运行/可部署」结论必须真跑）存在的理由。

### 二、修复方案

1. **转发头实现换成 uvicorn 的**（`uvicorn.middleware.proxy_headers`）：
   它在依赖树内、版本受锁文件约束，且是 uvicorn 自身处理 `--proxy-headers`
   的同一份代码。抽到 `app/proxy_headers.py` 集中管理，**并写明为什么不能用
   starlette 的**——否则后来者很容易「顺手改回去」。
2. **门禁严格比对 `== "1"`**（抽出 `_env_flag()`），`0/false/no/空` 一律视为未声明。
3. **两个 compose 形态各自显式声明**：
   - 基础层：`ERP_TLS_TERMINATED_ELSEWHERE=1`（TLS 由宿主机代理终止），
     同时把端口绑定从 `8000:8000` 收紧为 **`127.0.0.1:8000:8000`**——
     否则「TLS 在别处」这条声明就是橡皮图章：谁都能用 http 直连，
     而应用还以为前面有 TLS。
   - TLS 层：`ERP_TRUST_PROXY_HEADERS=1` + `ERP_TRUSTED_PROXY_HOSTS=<代理网段>`，
     并用 `!reset` **清空**继承来的「TLS 在别处」声明（两层同时声明是语义矛盾）。

### 三、新增的第二道闸：可信代理来源

`ERP_TRUST_PROXY_HEADERS=1` 单独**不足以**安全。实测证据：

```
FORWARDED_ALLOW_IPS=* 时，直连应用发送 X-Forwarded-For: 203.0.113.77
→ uvicorn 日志记录 `203.0.113.77:0 - "GET /api/health"`（客户端 IP 被完全伪造）
```

因此新增 `ERP_TRUSTED_PROXY_HOSTS`（默认 `127.0.0.1`），只有来自可信地址的
转发头才被采信。Docker 下代理源地址是容器网段，故 TLS 覆盖层**固定了专用网段**
（`172.31.240.0/24`，可用 `ERP_PROXY_NETWORK_PREFIX` 覆盖）——
不固定时 Docker 从地址池动态分配，应用侧无法预先写死可信来源，
只能退化成「信任所有来源」，等于没有防护。

### 四、Caddyfile 的一处实测纠错

初版写了三行 `header_up X-Forwarded-For/-Proto/-Host`，注释声称「传递真实客户端信息」。
实测（真 Caddy 容器 + 回显上游，逐个变体对比）：

- Caddy **默认就会**把这三个头设为正确值；
- 且会**忽略**客户端伪造的 `X-Forwarded-For`（实测发 `1.2.3.4`，上游收到真实地址）；
- `caddy validate` 对这三行逐条告警 `Unnecessary header_up ...`。

> **中途我下过一个错结论**：先看到某个变体的输出里没有 `x-forwarded-proto`，
> 就判断「`{remote_host}` 求值为空 → Caddy 删除了该头」。重测（逐行归因）后
> 发现是自己读错了输出——头一直都在。**已删除那段错误注释。**
> 教训：读工具输出也要用「逐项归因」的方式，不能凭一次整体观感下结论。

三行已删除（冗余行本身无害，但会掩盖「Caddy 已内置该保护」这一事实，
让后来者误以为不写就没有转发头）。`X-Real-IP` 保留——Caddy **不**默认设置它。

### 五、新增验证：真 HTTPS 端到端（`scripts/tls_feasibility.py`）

`docker_feasibility.py` 验的是**无 TLS 基线**（直连 8000）。TLS 链路
**只有真跑一遍才算验证过**。新脚本 8 项检查，实测全 PASS：

| # | 检查项 | 实测结果 |
|---|---|---|
| 1 | Caddyfile 语法有效 | Valid configuration |
| 2 | 镜像就绪 | ai-erp-tls-verify:latest |
| 3 | 应用容器内健康检查 | 200 |
| 4 | **应用未暴露到宿主机**（`ports: !reset` 语义） | 未映射任何端口 |
| 5 | 代理证书签发 | 已签发（tls internal 自签 CA） |
| 6 | **真 HTTPS 请求** | HTTP/2 200 + `{"ok":true}` |
| 7 | **应用真的采信转发头** | 日志中的真实客户端 `172.31.241.2`（非代理地址） |
| 8 | 宿主机 8000 不可直连 | 已拒绝 |

设计要点：

- **保真**：临时 Caddyfile 与生产**逐字一致**，只加一行 `tls internal`
  （离线自签所需），域名/邮箱仍走环境变量——验证的是生产同一份模板；
- **第 7 项是关键**：只证明「HTTPS 能通」**不够**。Caddy 无条件转发，
  即使应用**没开**信任开关也能返回 200，那样应用仍以为自己在 http 之后，
  生成的回调地址与审计日志全是错的。故必须直接观察应用侧的解析结果。
- **第 4/8 项**把「外部无法绕过 TLS」变成可执行证据，而不是只看配置文件。

### 六、回退法验证（逐项确认判别力，DP-5）

| 变异 | 期望 | 实测 |
|---|---|---|
| `ERP_TLS_TERMINATED_ELSEWHERE=0`（非空即真） | 被抓 | ✅ 3 项 FAIL |
| `proxy_headers.py` 改回 starlette import | 被抓 | ✅ 2 项 FAIL（ModuleNotFoundError） |
| 应用侧 `ERP_TRUST_PROXY_HEADERS=0` | 被抓 | ✅ 门禁先拦（判别链有效） |
| 应用侧改声明 `ERP_TLS_TERMINATED_ELSEWHERE=1` | 被抓 | ✅ **仅第 7 项 FAIL**（HTTPS 通但转发头未采信——精确命中） |
| 应用容器额外映射 8000 到宿主机 | 被抓 | ✅ 第 4 项 FAIL |
| 脚本漏传 `ACME_EMAIL` 给 `caddy run` | 被抓 | ✅ 第 5 项 FAIL（`wrong argument count ... after 'email'`） |

第四行最能说明问题：**其他 7 项全 PASS，只有第 7 项抓住**——
如果当初只写「HTTPS 能通」这一条断言，这个缺陷会完整漏过去。

### 七、脚本自身踩的两个坑（已修）

1. `--skip-build` 未检查镜像是否存在 → `docker run` 去 registry 拉同名镜像，
   把「本地无镜像」误报成「registry 连不上」（报错指错方向）；
2. 断言 `"200 OK" in out` 在 **HTTP/2** 下误判——HTTP/2 状态行是 `HTTP/2 200`，
   没有 `OK` 字样。真成功了却报 FAIL。改为分别校验状态行与响应体。

### 八、补充规范

| 编号 | 规则 |
|---|---|
| DP-6 | 「修复安全缺陷」的改动必须验证**开关打开时**的路径——只在默认（关闭）态验证，等于没验证 |
| DP-7 | 部署类配置（TLS / 代理 / 网段）必须**真跑端到端**并断言**链路效果**（如应用侧真的看到了 https），不能只验「容器起来了」 |
| DP-8 | 安全开关必须配「来源限定」（如可信 IP 段）；只给「信任/不信任」布尔开关，实际会退化成信任所有来源 |

**关联**：`docs/CODE_AND_DIRECTORY_STANDARD.md` DEBT-23；
新增文件 `app/proxy_headers.py`、`scripts/tls_feasibility.py`、`tests/test_tls_proxy_config.py`。

## D23：G-3 工厂账号 Context 通道 —— Phase 1.8「删除旧入口」的唯一前置（2026-09-24）

**背景**：Phase 1.8 的「删除 legacy 入口」此前**暂缓**，理由写在 D15 第二节：
工厂账号拿不到 Context，删掉 legacy 兜底会让工厂门户直接不可用。
本轮打通该通道，并顺带挖出一个**真实的 fail-open 缺陷**。

### 一、G-3 打通：放行只读端点，不放行写语义端点

`app/auth.py` 原先把工厂账号挡在 `/api/me/*` 之外（403）。现在改为
**精确白名单**（`_FACTORY_SCOPE_PATHS`）：

| 路径 | 放行 | 理由 |
|---|---|---|
| `/api/factory-network/portal/*` | ✅ | 门户资料（原有） |
| `/api/auth/me` | ✅ | 原有 |
| `/api/me/workspaces` | ✅ **新增** | 只读：让工厂身份可被前端解析 |
| `/api/me/workspace-context` | ✅ **新增** | 只读：Context 权威源 |
| `/api/me/workspaces/{id}/switch` | ❌ **刻意拒绝** | **写语义**（审计 + 未来持久化）；工厂的活动 Workspace 由 `SupplierPortalMember` 唯一确定，**不存在可切换的第二个 Workspace**，放行只会扩大攻击面 |

**为什么用精确白名单而不是前缀匹配**：`path.startswith("/api/me/")` 会把
`/switch` 一并放行。这不是假想风险——回退法实测（把白名单改成前缀匹配）
立刻被 `test_factory_portal_account_reaches_read_only_context` 抓住。

### 二、顺带挖出的真实缺陷：门户绑定不校验 status（fail-open）

`build_factory_context()` 查询 `SupplierPortalMember` 时**只按 user_id 过滤、
未校验 `status`**，而路由层 `_portal_scope` 一直带 `status == "active"`。

两条路径判定不一致 → **绑定停用后门户 API 拒绝（403），但 Context 仍宣称
`supply:read/supply:write`**。

**影响面**（这是它值得当缺陷而非小瑕疵的原因）：

1. `/api/me/workspace-context` 现已对工厂开放，Context 是前端**权威**权限来源
   （`permissions.js` 的 legacy 仅兜底）→ 表现为「界面按钮可点、实际请求 403」，
   用户可见的不一致；
2. `require_permission()` 的**后端鉴权**也以 Context 为权威判定路径
   （`auth.py:221-229`），不只是显示问题；
3. **MEMBERSHIP 路径一直带 `status='ACTIVE'`**（`_MEMBERSHIP_QUERY`），
   工厂路径是**唯一**漏检的分支——属实现疏漏，非有意设计。

**修法**：补 `status == "active"`，停用绑定的处理与「未绑定」一致
（`permissions=∅`、`workspace_id=None`），仍可访问门户自身资料。

### 三、验证

**端到端真实链路**（真启动 uvicorn + 真登录 + 真调 API，副本库）：

```
[OK] 服务已启动
开通门户账号: 200 g3_verify_portal
工厂登录: 200
GET /api/me/workspaces         -> 200 {"items":[{"id":1,"name":"义乌市华晨日用品厂",
                                     "kind":"FACTORY","role":"FACTORY_COLLABORATOR",
                                     "source":"FACTORY","is_active":true}],"total":1}
GET /api/me/workspace-context  -> 200 {"role":"FACTORY_COLLABORATOR",
                                     "permissions":["supply:read","supply:write"],
                                     "data_scope":"FACTORY_SELF","source":"FACTORY"}
POST /switch（应 403）         -> 403 工厂门户账号仅可维护本厂资料
GET /api/suppliers（应 403）   -> 403
==== G-3 端到端: 全部通过 ====
```

**回退法逐项验证判别力**：

| 变异 | 期望 | 实测 |
|---|---|---|
| 白名单改成 `startswith("/api/me/")` | 被抓 | ✅ `/switch` 403 断言失败 |
| 去掉 `build_factory_context` 的 status 条件 | 被抓 | ✅ `test_inactive_portal_binding_grants_no_permissions` 失败 |

**回归**：`pytest` 246 passed（原 244 + 新增 2）；前端 68 passed（+1）；
`ruff` 全绿；`npm run build` 成功。

### 四、对 Phase 1.8 的影响

`permissions.js` 文件头原写「工厂账号拿不到 Context」——**该前提已不成立**，
本轮同步更新注释（否则后来者会依据过时前提做判断）。

**注意：legacy 兜底仍不能删**，但理由已变：
- ~~工厂账号拿不到 Context~~ → **已解决**；
- **Context 请求可能失败**（网络抖动、后端 5xx、F5 刷新瞬间）→ 仍需兜底，
  否则这些场景下所有按钮会消失。

即「删除旧入口」的**阻塞项已清除**，剩余工作是把兜底从「身份来源之一」
降级为「异常降级路径」——这需要单独评估（建议在 Phase 2 与 Agent Tool Layer
一起做，因为两者都涉及权限判定入口的统一）。

### 五、补充规范

| 编号 | 规则 |
|---|---|
| T-22 | **放行路径白名单必须用精确匹配，不用前缀匹配**——前缀会把同前缀下的写语义端点一并放行。改白名单后必须用回退法验证边界仍被拒 |
| T-23 | **同一实体在不同层（Service / Router）的查询条件必须一致**。实测 `SupplierPortalMember` 的 `status` 校验在 Router 有、Service 无，形成 fail-open；且 MEMBERSHIP 路径有同等校验时，缺它的分支就是疏漏而非设计 |

**关联**：D15（Phase 1.8 优先级与 legacy 保留依据）、`docs/phase1_interfaces.md` §6/§7、
`docs/WORKSPACE_MIGRATION_PROGRESS.md` Phase 1.8 表；
修改文件 `app/auth.py`、`app/services/workspace_context.py`、
`tests/test_workspace_context_api.py`、`tests/test_workspace_context.py`、
`frontend/src/permissions.js`、`frontend/src/router.js`、`frontend/tests/permissions*.test.js`。

## D24：前端 legacy 兜底降级为「只读」而非删除 —— 写权限 fail-closed（2026-09-24）

**背景**：Phase 1.8「删除旧逻辑入口」的最后一个阻塞项。`permissions.js` 保留
legacy `localStorage.erp_user` 兜底，此前它**会授予写权限**（`LEGACY_CAPABILITIES`
手工维护的角色→权限表）。

**为什么不能直接删**：Context 请求可能失败（网络抖动、后端 5xx、F5 刷新瞬间）。
直接删会让所有按钮消失；而「Context 不可用 → 跳登录页」会引入**无限重定向环**
（守卫的 `authenticated` 只判 token 存在，后端 5xx 时 token 仍有效 → 跳 `/login`
→ `defaultLanding` 弹回 `/dashboard` → 循环）。

### 一、采纳方案：写权限 fail-closed，路由兜底保留

| 维度 | 处理 | 理由 |
|---|---|---|
| **写权限**（`canWrite`/`canAdmin`/`canApprove`/`can`） | ❌ **fail-closed**：Context 不可用时一律 `false`，`LEGACY_CAPABILITIES` 整体删除 | 写权限是安全边界，不能靠客户端兜底表授予 |
| **路由/菜单/展示**（`roleKey`/`routeRedirect`/`defaultLanding`） | ✅ **保留 legacy 兜底** | 否则 Context 故障时平台管理员与工厂账号会被弹到无权页面 |

**为什么这个切分是对的**：已核实 `can()` 在 8 个视图的用法**全部是写操作**
（`*:write` + `compliance:approve`），**无任何读权限依赖它** → fail-closed
不会导致「页面读不出来」，只会让写按钮消失，正好等于「只读降级」。

### 二、残留风险（显式记录，勿当已解决）

伪造 `localStorage.erp_user.role` **仍能影响路由与菜单**（可进 `/platform-admin`
界面渲染，接口返回 403）。这是 A′ 的固有残留——路由兜底必须保留。

**属 UI 层问题，非数据越权**：后端独立鉴权已实测兜住——viewer 写商品 403、
viewer 读 `/api/admin/users` 404、viewer 进 `/api/admin/overview` 403、
viewer 代客进入 403。

**若后续要彻底去 legacy**：必须先为「Context 故障时的路由策略」单独设计
（例如显式「身份加载失败」页），不能直接删 `routeRedirect` 兜底。

### 三、验证

| 验证 | 结果 |
|---|---|
| 回退法判别力（DP-5） | ✅ 临时恢复兜底表 → **13 个断言变红**（证明新断言有判别力） |
| 前端回归 | ✅ 72 passed（原 68，净增 4）；`npm run build` 成功 |
| 后端守护测试同步 | ✅ 改写为守护**新契约**（禁止重新引入兜底表；写权限 key 扫描范围扩到整个 `src/`）——**不是放宽断言** |
| 死代码清理 | ✅ `identitySnapshot()` / `isSuperadmin()` / `workspaceSource()`（清理前 `rg` 确认零调用点） |

### 四、补充规范

| 编号 | 规则 |
|---|---|
| T-31 | **安全边界（写权限）与体验兜底（路由/展示）必须分开决策**。把两者绑在一起会导致「要么全删、要么全留」的伪二选一 |
| T-32 | **前端权限兜底表一律视为缺陷**。权限事实源只能是后端 Context；前端手工维护第二份表必然漂移，且可被客户端伪造 |

**关联**：D15/D23（Phase 1.8）、D25（代客身份序列化）、D26（Membership 写入侧）；
修改文件 `frontend/src/permissions.js`、`frontend/src/workspace.js`、
`frontend/tests/permissions*.test.js`、`frontend/tests/workspace.test.js`、
`backend/tests/test_role_permissions.py`。
## D25：代客态 `/api/auth/me` 500 —— 鸭子类型身份对象被当 ORM 行序列化（2026-09-24）

**背景**：真启动服务走代客链路（root 登录 → 进入租户 → 调 `/api/auth/me`）时
直接 500。`GET /api/auth/me` 是前端与多个测试的**高频基础端点**，
它崩了意味着「代客进入租户后工作台首屏必挂」。

### 一、根因

`get_current_user` 在代客态返回 `_ImpersonatedUser`——一个**鸭子类型替身**
（`app/auth.py`），它没有 `__table__`；而 `/api/auth/me` 直接把它喂给
`serialize.to_dict()`，后者遍历 `obj.__table__.columns`：

```
File "backend/app/serialize.py", line 9, in to_dict
    for col in obj.__table__.columns:
AttributeError: '_ImpersonatedUser' object has no attribute '__table__'
```

**为什么长期没被发现**：普通登录态拿到的是真 ORM 行，路径完全正常；
代客态此前**零测试覆盖**（`rg "auth/me" backend/tests/` 命中的全是普通用户态），
而前端当时也不调该端点。这是一条「只有真启动服务 + 真代客才会走到」的路径。

### 二、修法：收敛到唯一序列化入口，而不是逐点打补丁

新增 `identity_snapshot(user)`（`app/auth.py`）作为**唯一**身份序列化入口：
`_ImpersonatedUser` 提供 `to_public_dict()`，其余身份走 `to_dict()`。

**为什么不让 `serialize.to_dict` 去兼容鸭子类型**：那样每个「非 ORM 身份对象」
都要在通用序列化器里加分支，`to_dict` 会逐渐承担身份语义；而身份快照的字段
是**安全契约**（不能泄露 `password_hash`、不能泄露平台角色），必须在身份层定义。

**安全语义（勿改）**：`to_public_dict()` 把 `role` 与 `tenant_id` 钉成**目标租户**
的值（`operator` + 目标租户 id）。若返回平台账号的 `superadmin`，前端 legacy
兜底会把代客会话当平台本尊放行到 `/platform-admin`，代客隔离失效（D19）。

### 三、顺带修的隐式耦合：代客标记的唯一判定点

`require_permission` 内部调 `resolve_workspace_context(db, user)` **未透传代客标记**，
代客态会被解析成 `PLATFORM_ADMIN` + `workspace_id=None` + `permissions={'platform:admin'}`。

**当前不出事靠的是巧合**：代客替身的 `role` 恰好是 `operator`，漏传标记时会落到
LEGACY 分支、算出同样的 OPERATOR 权限。实测把透传删掉后
`POST /api/compliance/check` 仍返回 404，**端点断言抓不到差异**。

因此新增 `is_impersonating_user(user)` 作为唯一判定点，并**把字段名统一为
`is_impersonating`**（原为 `is_impersonated`，与冻结契约 `phase1_interfaces.md`
第 6 节的 Context 字段只差一个后缀——同一会话里两个近似标记极易看错）。
`me.py` 三个端点同时收敛到 `_current_context()`，新增端点不会再漏透传。

### 四、验证

| 验证 | 结果 |
|---|---|
| 缺陷复现（修复前） | ✅ 500 + `AttributeError`（探针实测） |
| 全端点差分扫描（代客 token vs operator token，167/167 覆盖） | ✅ 修复前**恰好只有** `/api/auth/me` 报代客专属 500；修复后 **0 个** |
| 泄露扫描 | ✅ 代客态响应无 `password_hash`、无 `superadmin` 字样；`role=operator`、`tenant_id` 钉成目标租户 |
| 真服务复验（uvicorn + 真代客 token） | ✅ 代客 `/api/auth/me` 200；代客读商品 200；代客访问 `/api/admin/*` 403；平台本尊仍 `superadmin` 且无代客标记 |
| 回退法判别力（DP-5） | ✅ 变异 1（序列化退化）→ 3 用例红；变异 2（角色不钉租户）→ 3 用例红；变异 3（漏传标记）→ 捕获到 `{'flag': False}` |
| 回归 | ✅ 后端 250 passed；主库 sha256 前后一致 |

**注意**：`test_require_permission_sees_impersonated_context` 的判别力**不能**靠端点
状态码实现（端点返回值对漏传标记无差异，实测确认）。唯一有判别力的写法是
拦截 `require_permission` 的解析调用并捕获实参——补丁必须在**创建依赖之前**打
（该函数在自身函数体内 import 解析函数，名字在调用 `require_permission(...)` 时
绑定为 `_dep` 的闭包变量）。

### 五、补充规范

| 编号 | 规则 |
|---|---|
| T-24 | **非 ORM 身份对象必须提供自己的序列化方法**，通用 `to_dict` 不得承担身份语义。新增身份形态时只改 `identity_snapshot`，不得在各端点分别做鸭子类型判断 |
| T-25 | **「靠巧合正确」必须显式化**。当漏传某标记恰好不改变结果时，必须补「结构性断言」（拦截调用捕获实参），而非依赖端点行为——否则将来一次无关重构就会让它静默错乱 |
| T-26 | **同一概念的标记名必须与冻结契约一致**。`is_impersonated` / `is_impersonating` 这类只差后缀的并存命名，是排查事故的经典陷阱 |

**关联**：`docs/phase1_interfaces.md` §6、D19（代客隔离）、D23（G-3）；
新增文件 `tests/test_identity_snapshot.py`；
修改文件 `app/auth.py`、`app/routers/auth.py`、`app/routers/me.py`。

## D26：Membership 只有读取侧、没有写入侧 —— 一次挖出三个同源缺陷（2026-09-24）

**背景**：Phase 1.1~1.7 实现了 `resolve_workspace_context` 的**双读**（MEMBERSHIP
优先、LEGACY 兜底），迁移 `20260923_08` 也回填了存量数据。但**写入侧从未实现**：
全仓没有任何代码路径为新建租户/新建用户补身份行（`rg "INSERT INTO workspace"` 为空）。

### 一、三个同源缺陷（均为真库实测）

| # | 缺陷 | 实测证据 | 严重度 |
|---|---|---|---|
| 1 | `POST /api/admin/tenants` 不建 `workspace_profiles` | 新租户 admin 的 Context `source=LEGACY_FALLBACK`（演示租户是 `MEMBERSHIP`） | **中**：Phase 1.8 删旧入口后新租户会**失去身份来源** |
| 2 | `POST /api/auth/users` 不建 `workspace_memberships` | 新用户 `source=LEGACY_FALLBACK`、membership 行数 0 | 中：同上 |
| 3 | `PUT /api/auth/users/{id}` 改角色只写 `users.role` | operator 降为 viewer 后 Context **仍返回 OPERATOR**（MEMBERSHIP 是权威路径，旧 `role_key` 继续生效） | **高**：**降权被静默忽略**，属安全缺陷 |
| 4 | `DELETE /api/auth/users/{id}` 未清身份行 | `IntegrityError: FOREIGN KEY constraint failed`（`PRAGMA foreign_keys=ON`） | 中：删账号直接 500 |

缺陷 1/2 是「新数据拿不到身份」，3 是「旧数据改不动权限」，4 是「删不掉」——
**根因完全相同**：身份表没有写入口。

### 二、修法：新增唯一写入口，与读取侧共用同一张映射表

新增 `app/services/membership_service.py`，四个函数对应四个场景：

- `ensure_workspace_profile()`：幂等建 profile（**不覆盖已有名称**——租户改名
  不应静默改写 Workspace 名称，改名属 Phase 2 的 Workspace 管理界面）；
- `sync_membership()`：幂等 upsert，覆盖「新建」与「改角色」两种场景；
- `remove_user_memberships()` / `remove_user_portal_bindings()`：删账号前清理。

**为什么必须共用 `normalize_legacy_role`**：写侧若自己维护一份 legacy→role_key
映射，就会出现「写进去的角色读不出来」（例如 `compliance_approver` 一边映射
COMPLIANCE、另一边漏掉）。写侧与读侧必须同一张表。

**渐进启用**：`workspace_profiles` / `workspace_memberships` 由 Alembic 创建，
`models.py` 刻意不注册（否则 `create_all` 会绕过 Phase 1 的维护窗口门禁）。
因此写侧表未落地时**全部 no-op**，行为与 Phase 1.1 完全一致。

**一个反例（刻意不用探测门禁）**：`remove_user_portal_bindings` 操作的是
`supplier_portal_members`——它是 ORM 模型，`create_all` 一定会建表。若也用
`membership_table_available` 门禁，该函数会在迁移前静默 no-op，反而**漏掉清理、
删账号时撞外键**。

### 三、前端：写权限只读降级（D24 的 A′ 方案）

`permissions.js` 的 legacy 兜底此前会**授予写权限**（`LEGACY_CAPABILITIES`），
意味着前端伪造 `localStorage.erp_user.role` 即可让写按钮出现。现改为：

- **写权限 fail-closed**：`canWrite` / `canAdmin` / `canApprove` / `can` 在
  Context 不可用时**一律返回 false**，`LEGACY_CAPABILITIES` 整体删除；
- **路由/菜单保留 legacy 兜底**：否则 Context 故障时平台管理员与工厂账号会被
  弹到无权页面，体验更差（且需先解决重定向环问题）；
- 清理死代码 `identitySnapshot()` / `isSuperadmin()` / `workspaceSource()`。

**为什么不是「Context 不可用 → 跳登录页」**：守卫的 `authenticated` 只判 token
存在，后端 5xx 时 token 仍有效 → 跳 `/login` → `defaultLanding` 弹回 `/dashboard`
→ **无限重定向环**。必须同时改守卫契约 + 清 token + 加提示，代价远超收益。

**残留风险（显式记录）**：伪造 `erp_user.role` 仍能影响**路由与菜单**（可进
`/platform-admin` 界面渲染，接口返回 403）。这是 A′ 的固有残留——路由兜底必须
保留。属 **UI 层问题，非数据越权**：后端独立鉴权已实测兜住（viewer 写商品 403、
`/admin/users` 404、`/admin/overview` 403、代客进入 403）。

### 四、验证

| 验证 | 结果 |
|---|---|
| 缺陷复现（修复前） | ✅ 四项全部复现（含降权失效、删除 500） |
| 回退法判别力（DP-5） | ✅ 移除后端写侧调用 → `test_membership_write.py` **5 用例全红**；前端临时恢复兜底表 → 13 个断言变红 |
| 真服务复验（uvicorn，副本库） | ✅ 新租户 `MEMBERSHIP/OWNER`；新用户 `MEMBERSHIP/OPERATOR`；降权后 `READ_ONLY`；删用户 200；代客 `/auth/me` 200；**主库 sha256 前后一致** |
| 回归 | ✅ 后端 257 passed；前端 72 passed；`ruff` 全绿；`npm run build` 成功；`migration_preflight` 12 项全 PASS |
| 守护测试同步 | ✅ 两个前端权限契约测试改written为守护**新契约**（禁止重新引入兜底表；写权限 key 扫描范围扩到整个 `src/`）——**不是放宽断言** |

### 五、补充规范

| 编号 | 规则 |
|---|---|
| T-27 | **双读改造必须同时实现写入侧**。只做读取侧会让新数据掉到 legacy 分支，且**改权限不生效**（降权静默失败），这类缺陷在存量数据上完全不可见 |
| T-28 | **写侧与读侧必须共用同一张映射表**（如 `normalize_legacy_role`）。两份手工维护的映射必然漂移 |
| T-29 | **渐进启用的探测门禁只用于「由迁移创建的表」**。对 `create_all` 一定建表的 ORM 表使用探测门禁，会让清理逻辑静默 no-op、反而制造外键失败 |
| T-30 | **设计变更推翻守护测试前提时，必须改写守护点而非放宽断言**。D24 删除前端兜底表后，「两张表一致」的守护失效——正确做法是改为「不存在第二份表」 |

**关联**：D15/D23（Phase 1.8）、D24（前端 A′）、`docs/phase1_interfaces.md` §6/§7；
新增文件 `app/services/membership_service.py`、`tests/test_membership_write.py`；
修改文件 `app/routers/admin.py`、`app/routers/auth.py`、`tests/test_role_permissions.py`、
`frontend/src/permissions.js`、`frontend/src/workspace.js`、`frontend/tests/permissions*.test.js`。

---

## D27：tenant_id 外键收敛 —— 平台级表用 NULL 而不是 0 哨兵值（2026-09-24）

**背景**：`app/db.py` 在**应用连接级**强制 `PRAGMA foreign_keys=ON`，但 45 张含
`tenant_id` 的业务表**从未声明** `tenants.id` 外键（DEBT-03）。后果有两个：

1. 应用层写错租户时数据库**不拒绝**——DEBT-02 的 37 行 `tenant_id=0` 孤儿数据
   就是这么产生的（`app/seed.py:153` 有同源注释）；
2. `PRAGMA foreign_key_check` 返回 0 只说明「**已声明**的外键没违规」，
   **不能**证明租户引用完整——这是合规假象，比明面上的缺陷更危险。

**施工前实测**（主库只读体检，2026-09-24）：48 张表含 `tenant_id`，其中
3 张已有外键（`tenant_settings` / `users` / `workspace_profiles`），缺口 **45 张**；
45 张表数据干净（孤儿 0 / NULL 0 / FK 违规 0）。

### 一、关键阻塞：`platform_rule_packs` 用 `tenant_id=0` 作平台级哨兵值

`app/services/platform_rules.py:235` 写入 `PlatformRulePack(tenant_id=0, ...)`。
探针实测：**该写入当前成功**（正因缺外键），一旦补上外键，写入路径立即崩。

判定它是**平台级共享表**的依据（不是猜的）：

- 读取路径 `get_active_rules()` 只按 `platform` 过滤，**刻意不带租户维度**
  （`platform_rules.py:116-118`）；
- `alerting.py:219-220` 也只看 `updated_at`，同样无租户过滤；
- 规则包内容来自各平台**公开**卖家规则文档，对所有租户一致。

即：`tenant_id=0` 在这里是「不归属任何租户」的**哨兵值**，与
`users.tenant_id=0`（superadmin 平台身份）是**同一类缺陷**——Revision C
（`20260923_09`）已把后者迁为 NULL 并把列改 nullable。

### 二、决策：沿用 users 先例，改 NULL，**不做豁免**

| 候选方案 | 取舍 |
|---|---|
| A. 改 nullable + 写入侧改 None | ✅ **采纳**。语义正确，与 users 先例一致 |
| B. 给该表豁免（不加外键） | ❌ 否决。会让「45 张表全有外键」退化成「44 张 + 1 个例外」，例外会在**后续每一次 schema 审计中被反复误报**，长期成本更高 |
| C. 混合（租户表加 FK + 平台级表豁免） | ❌ 同 B 的问题 |

**为什么不做「给 tenants 插入 id=0 的哨兵租户」**：那会让 0 变成合法租户 ID，
使「孤儿数据检测」失去判别力（`migration_preflight.check_tenant_zero` 直接失效），
且 `orders.tenant_id=0` 这类真实错误将永远无法被发现。

### 三、实现要点（迁移 `20260924_16`）

1. **SQLite 不支持 `ALTER TABLE ADD CONSTRAINT`**，加外键只能重建表
   （`batch_alter_table(recreate="always")`）。重建会连带重建索引与**既有外键**，
   因此迁移对每张表做「前后快照比对」并在漂移时**中止**：列定义、索引、
   既有外键集合、行数——任一漂移即 `RuntimeError`。
2. **外键必须具名**（`fk_<table>_tenant_id_tenants`）：实测匿名外键
   （`batch.create_foreign_key(None, ...)`）会直接抛
   `ValueError: Constraint must have a name`；且 SQLite 下匿名外键反射出的
   `name` 为 `None`，`downgrade()` 无法安全删除。
3. **幂等**：加外键前先探测 `PRAGMA foreign_key_list`，已有则跳过
   （测试库路径是 `create_all` + 全量迁移链，必须能重复执行）。
4. **`downgrade()` 可用**：按反射名 `drop_constraint`；平台级表改回 NOT NULL 前
   若仍有 NULL 行则**主动报错**（防止静默丢失「平台级」语义）。
5. **模型层同步**：45 处 `mapped_column(index=True)` 改为带具名
   `ForeignKey("tenants.id", ...)`——否则 `create_all` 建的新库与迁移后的库
   结构漂移，测试库（走 create_all）会与生产库不一致。
6. **平台级表改 nullable 必须在加外键之前**，否则外键会先拒绝 NULL 写入。

### 四、实测验证

| 验证 | 结果 |
|---|---|
| 副本库执行 | ✅ 45 张表补完；列定义零漂移、索引零漂移、既有外键**全部保住**、行数 3169 不变、integrity ok、FK 违规 0 |
| 唯一「差异」 | ✅ 仅 `platform_rule_packs.tenant_id` 由 `NOT NULL` 变 nullable——**正是设计意图** |
| 幂等性 | ✅ 重复 `upgrade head` 两次：exit=0、状态不变 |
| `downgrade()` | ✅ 回退到 `_15` 后外键从 48 降到 3（=原始状态）；再 upgrade 恢复 48 |
| **判别力（对照组）** | ✅ 未加外键的原始库：`products.tenant_id=999/0`、`rulepack.tenant_id=0` **三个都写入成功**（缺陷真实存在）；加外键后**全部被拒**（5/5 符合预期） |
| 主库执行 | ✅ exit=0，48/48 张含 `tenant_id` 的表全部有外键 |
| 主库复验 | ✅ `migration_preflight` **12 项全 PASS**（执行前唯一 FAIL 是 alembic 账本 `_15` vs `_16`，属迁移前预期）；`e2e_feasibility` **7 步全 PASS**（含真实服务 + 业务闭环，主库 sha256 前后一致） |
| 回归 | ✅ 后端 **264 passed**（257 基线 + 7 新增）；`ruff` 全绿 |
| 冷备 | ✅ 执行前 `backup_restore_drill.py backup` 7 项检查全 PASS |

### 五、挖出的测试盲区（本次最有价值的发现）

新增 `tests/test_tenant_id_foreign_keys.py` 后做**回退法验证**，发现一个**真实盲区**：

> 从迁移清单里删掉 `products` 后，其余 5 个用例**全部照常通过**。

**成因**：测试库建库路径是 `create_all`（按**模型**建表）+ 全量迁移链。
模型层已声明外键，`create_all` 就把外键建好了——于是「库里有外键」这类断言
**完全掩盖**了迁移清单的遗漏。换言之：**只测「最终结构」无法验证「迁移本身」**。

**修法**：新增 `test_migration_table_list_matches_model_metadata`，**不查库**，
直接比对迁移模块的 `TENANT_FK_TABLES` 与模型元数据。再次回退法验证：
删掉 `products` → 该用例**立即变红**。

**方法论沉淀**：结构类断言存在「多路径建库」时必须识别**哪条路径会被测到**。
本项目测试库与生产库的建库路径不同（`create_all` vs 纯迁移），
任何「只测结果不测过程」的断言都可能对迁移缺陷免疫。

### 六、补充规范

| 编号 | 规则 |
|---|---|
| T-33 | **「平台级/全局」语义的表禁止用魔法 ID 作哨兵值**（如 `tenant_id=0`）。必须用 NULL + 列 nullable，并保持与 `users` 的 superadmin 处理同一模式。哨兵值会让孤儿检测失去判别力 |
| T-34 | **SQLite 加外键只能重建表，且外键必须具名**。匿名外键既无法创建（`Constraint must have a name`）也无法在 `downgrade()` 中安全删除 |
| T-35 | **表重建类迁移必须做前后快照比对并硬性断言**（列/索引/既有外键/行数）。SQLite 重建会静默重建索引与既有外键，不做比对就无法发现丢失 |
| T-36 | **测试库与生产库建库路径不同时，结构断言可能对迁移缺陷免疫**。必须额外加「清单 vs 清单」的直接比对，并用回退法验证判别力 |

**关联**：DEBT-02（`tenant_id=0` 孤儿数据，根因已修但未封死）、
D18/`20260923_09`（users nullable 先例）、`docs/CODE_AND_DIRECTORY_STANDARD.md` §7；
新增 `migrations/versions/20260924_16_tenant_id_foreign_keys.py`、
`tests/test_tenant_id_foreign_keys.py`；
修改 `app/models.py`（45 处）、`app/services/platform_rules.py`。
