# 代码与目录规范 V1.0

> 适用范围：`AI-电商ERP` 全仓库（`backend/` `frontend/` `docs/`）
> 生效日期：2026-09-23
> 配套文档：`docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md`（Agent 层冻结架构）、`docs/CONTRACT.md`（接口契约）、`docs/DECISIONS.md`（决策记录）

## 0. 执行原则（先读这一节）

本规范对**新增与修改**的代码强制生效；对**存量**代码采取「登记债务、渐进整改」。

| 原则 | 说明 |
|---|---|
| **增量强制** | 新增文件、新增函数、被修改的函数体，必须符合本规范 |
| **存量渐进** | 存量不合规代码不得以「顺手重构」名义被大范围改写；整改须走独立任务并登记 |
| **债务可追溯** | 存量偏差统一登记在 §11 债务台账，不允许存在「隐形债务」 |
| **门禁优先** | 能用工具自动检查的规则一律进工具链（§9），不依赖人工记忆 |
| **例外须记录** | 任何偏离规范的实现，必须在 `docs/DECISIONS.md` 追加一条决策记录 |

**为什么不是「一刀切」**：实测现状是 23 个 router **100% 直连 ORM**、`services/platform_adapters.py` 单文件 **1146 行**。若要求立即全面整改，规范将在生效当天即被违反，反而失去权威性。因此采用「新代码严格、老代码登记」路线。

---

## 1. 最高优先级：纳入版本控制（P0）

**现状（2026-09-24 更新）**：本目录**已纳入 Git**（`git init -b main`，首次提交 `6215d49`，208 文件 / 0.87 MB）。此前长期处于无版本控制状态，问题如下（保留作为历史记录）：

- `.gitignore` 与 `.dockerignore` 当时**完全未生效**；
- `.github/workflows/ci.yml` 的 push/PR 触发**永远不会执行**；
- 任何一次误删、误改都无法回溯——当时唯一的回滚手段是手工冷备（见 `docs/backup_restore_runbook.md`）。

**规范**：

1. 仓库根目录必须存在 `.git`，且 `main` 分支受保护。✅ 已满足
2. 任何超过 1 小时的开发任务开始前，工作区必须处于「已提交或已 stash」状态。
3. 禁止提交：`*.db`、`node_modules/`、`dist/`、`__pycache__/`、`.pytest_cache/`、`.env`、`.zcode/`、`nul`。
4. 提交信息格式：`<域>: <动作> <对象>`，例如 `workspace: 修复 superadmin 越权写入`。
5. 冷备目录（`backend/backups/`、`_erp_backups/`、`_wip_backup/`）、根目录 `_*.py` 一次性脚本、`.orig` / `.bak` 变异残留，**一律禁止入库**（已在 `.gitignore` 显式声明）。
6. 行尾由 `.gitattributes` 统一锁定为 LF；`*.sh` / `Dockerfile` 强制 LF，`*.db` 等声明为 `binary`。

> **执行提示**：`git init` 属破坏性不可逆操作范畴的「新起点」，须由项目负责人确认后执行；执行后首次提交前必须先确认 `.gitignore` 覆盖完整（§7）。本次已按此执行：提交前用 `git add --dry-run` 逐项核对，确认 `.db` / `node_modules` / `dist` / 日志 / `.env` / 冷备目录 / 临时脚本均为 0 命中后才提交。

---

## 2. 目标目录结构

```
AI-电商ERP/
├── .github/workflows/ci.yml        # CI：测试 + 构建
├── backend/
│   ├── app/                        # 【运行时】只放会被部署的代码
│   │   ├── agents/                 # 领域能力 Agent（冻结架构 §7）
│   │   ├── ai/                     # LLM / RAG 基础设施
│   │   ├── routers/                # HTTP 边界层
│   │   ├── services/               # 业务能力层
│   │   │   ├── adapters/                # 平台适配器包（DEBT-05 拆包；见 D28）
│   │   │   │   ├── contract.py          # 契约层：常量/环境开关/重试/异常/归一化数据结构
│   │   │   │   ├── catmap.py            # 类目映射查询与提示
│   │   │   │   ├── base.py              # BaseAdapter（发布三道关、平台限流）
│   │   │   │   ├── registry.py          # ADAPTERS 注册表 + get_adapter + platform_meta
│   │   │   │   └── <platform>.py        # 各平台适配器（ali1688/shopee/tiktok/ebay/walmart/lazada/planned）
│   │   │   ├── platform_adapters.py     # **兼容门面**：重新导出 + 可打补丁点代理（唯一对外入口）
│   │   │   ├── costing.py               # 成本/利润唯一实现（Agent 共享，不依赖 agents/）
│   │   │   ├── settings_service.py      # 配置三级回退（P1-10 隔离）
│   │   │   ├── shop_scope.py            # 店铺可见性守卫（归档店铺一律视为不存在）
│   │   │   ├── tenant_data_purge.py     # 演示数据清理（按外键拓扑序）
│   │   │   └── workspace_context.py     # 身份 Context 唯一入口
│   │   ├── tools/                  # Agent 唯一数据通道（Agent OS §10；见 D37）
│   │   │   ├── contract.py              # 冻结契约：ToolSpec/ToolContext/ToolResult/ToolCall/错误码
│   │   │   ├── base.py                  # BaseTool + call() 六步管线 + 共用口径（as_int/clamp_limit/ts）
│   │   │   ├── audit.py                 # §10.2「必须记录 Audit」唯一落点（独立短会话）
│   │   │   ├── registry.py              # TOOLS 索引 + import 期清单自检
│   │   │   └── <domain>.py              # 9 个领域 Tool：product/store/order/supply/finance/
│   │   │                                #   market/compliance/memory/knowledge（§10.4 冻结清单）
│   │   ├── workflows/              # 工作流引擎
│   │   ├── models.py               # 数据模型（单一入口）
│   │   ├── pagination.py           # 分页参数统一约束（PageNum/PageSize，上限 200）
│   │   ├── auth.py  config.py  db.py  main.py  seed.py
│   │   └── serialize.py  secure_types.py
│   ├── migrations/versions/        # Alembic 迁移（只增不改）
│   ├── scripts/                    # 【运维】迁移/备份/审计/验证脚本，不参与运行时
│   │   ├── migration_preflight.py       # 迁移前 12 项预检
│   │   ├── backup_restore_drill.py      # 冷备与恢复演练
│   │   ├── live_acceptance.py           # 真服务业务闭环验收（7 步）
│   │   ├── e2e_feasibility.py           # 端到端可行性（真启动 + 隔离性校验）
│   │   ├── docker_feasibility.py        # Docker 镜像可行性（真构建 + 真运行 + 真登录）
│   │   ├── tls_feasibility.py           # HTTPS 链路可行性（真 Caddy + 真应用，8 项）
│   │   └── security_data_audit.py       # 权限矩阵与数据一致性审计
│   ├── tests/                      # 测试
│   │   ├── conftest.py             # 共享夹具（库隔离 + client + auth_headers + 状态自愈），
│   │   │                           #   禁止任何测试模块跨文件 import 夹具（§8 T-2）
│   │   └── test_*.py               # 按被测对象/业务域命名；深度对抗测试按域分文件
│   ├── alembic.ini  pytest.ini  pyproject.toml
│   ├── requirements.txt            # 运行时依赖声明（兼容区间，给人看）
│   ├── requirements.lock.txt       # 运行时精确锁定（Docker 用，构建可复现）
│   ├── requirements-dev.txt        # 开发依赖声明
│   └── requirements-dev.lock.txt   # 开发/CI 精确锁定（含 ruff / pytest）
├── docs/
│   ├── adr/                        # 架构决策记录镜像/索引层（不产生第二份真相）
│   │   ├── README.md               #   索引 + 状态定义 + 新增流程；权威源为 DECISIONS.md
│   │   └── NNNN-*.md               #   高价值决策自包含摘要（现 7 篇：0003/0007/0018/
│   │                               #   0022/0023/0024/0026），必须回指 DECISIONS.md 的 D 编号
│   ├── archive/                    # 一次性报告归档（14 篇，索引见 archive/README.md）
│   └── *.md                        # 活文档（需持续维护）
├── frontend/
│   ├── src/{views,components,composables}/   # components/composables 为 Phase 2 目标
│   ├── tests/
│   └── dist/  node_modules/        # 生成物，禁止提交
├── Dockerfile                      # 两阶段构建；runtime 阶段已命名（可 --target 单独验证）
├── docker-compose.yml              # 生产模式固定 + 密钥必填（无默认值）
├── docker-entrypoint.sh            # 容器入口：先 alembic upgrade head 再启服务
└── .gitignore  .dockerignore  .env.example  README.md  AGENTS.md  CONTRIBUTING.md
```

### 2.1 硬性规则

| 编号 | 规则 |
|---|---|
| D-1 | `app/` 内禁止出现数据库文件、日志、临时脚本 |
| D-2 | 运维脚本一律放 `backend/scripts/`，禁止放 `app/` |
| D-3 | 业务库唯一为 `backend/erp.db`；**禁止**在 `backend/` 根目录新增**业务** `.db`。测试库例外：默认名 `test_erp_<pid>.db`（PID 隔离）或由 `ERP_TEST_DB` 指定，且必须被 `.gitignore` 覆盖（§7.1）。运维脚本产出的库放 `backend/backups/` |
| D-8 | 新增 `.db` 类产物（含 WAL 旁文件 `-wal`/`-shm`/`-journal`）前，必须同步 `.gitignore` **与** `.dockerignore`。注意 `*.db` **不匹配** `*.db-wal`，旁文件必须单独列 |
| D-4 | 一次性报告放 `docs/archive/`（索引见 `docs/archive/README.md`）；只有需要持续维护的文档留在 `docs/` 根 |
| D-5 | 禁止提交生成物；`.gitignore` 必须先于文件产生而覆盖（§7） |
| D-6 | 新增顶层目录或 `app/services/` 新增模块必须同步更新本文件 §2 |
| D-7 | `app/services/workspace_context.py` **刻意不定义** `workspace_memberships` 等 Phase 1 表的 ORM 模型：注册进 `Base.metadata` 会让 `create_all` 绕过迁移门禁。该表族只经 Alembic 落地，读取用运行时探测 + 原生 SQL。新增该族表时必须遵守此约束 |

---

## 3. 分层与依赖方向

### 3.1 目标分层（与 Agent OS 架构对齐）

```
routers/      HTTP 边界：参数校验、鉴权、序列化、调用下层
    ↓
agents/       领域能力：Orchestrator / Planner / 8 个 Specialist Agent
    ↓
tools/        Agent 唯一数据通道（Phase 2 起强制）
    ↓
services/     业务能力：平台适配、规则引擎、分析、采集
    ↓
models.py     数据定义
```

### 3.2 依赖规则

| 编号 | 规则 | 违反后果 |
|---|---|---|
| L-1 | `services/` **禁止** import `routers/` | 立即阻断（当前 0 处，保持） |
| L-2 | `agents/` **禁止** import `routers/` | 立即阻断（当前 0 处，保持） |
| L-3 | `agents/` **禁止** import 其他 `agents/`（红线 2，禁止 P2P） | 立即阻断 |
| L-4 | `routers/` 可以 import `services/` `agents/` `models.py` | 允许（存量已如此） |
| L-5 | **新增** Agent 数据访问必须经 `tools/`（Phase 2 起）；存量 `BaseAgent.db` 已登记为债务 | 登记 |
| L-6 | 禁止函数体内延迟 import 来掩盖循环依赖；确需延迟导入必须写明原因注释 | 新增代码阻断 |
| L-7 | `tools/` **禁止** import `agents/`（依赖方向 `routers -> agents -> tools -> services -> models`） | 立即阻断 |

> **L-3 补充**：Agent 之间的协作只能由 Orchestrator 编排。任何「A Agent 直接调用 B Agent」的写法都违反架构红线 2。

> **L-7 补充**：Tool 层反向 import Agent 会成环，并让 Tool 层无法脱离 Agent
> 独立测试——而「能独立测试」正是它作为唯一数据通道的前提。权限目录同理：
> `tools/contract.py` 从 `services/workspace_context.ROLE_PERMISSIONS` 求并集，
> **不**从 `agents/contracts.py` 取（T-53：同一份信息不得维护在两个地方）。

### 3.3 存量偏差（登记，不立即整改）

- `routers/` 23/23 直连 `models.py`：允许，但**新增 router 若含业务逻辑，逻辑必须下沉到 `services/`**。
- 函数体内延迟 import：**routers/ 45 处 / 11 文件**（2026-09-24 AST 实测，台账原写「32 处 / 8 个 router」已过期）。
  分布：`shops.py`(11)、`knowledge.py`(8)、`listings.py`(6)、`purchases.py`(4)、`ai.py`(3)、`discovery.py`(3)、
  `factory_network.py`(3)、`orders.py`(3)、`bi.py`(2)、`suppliers.py`(1)、`support.py`(1)。
  全 `app/` 共 **109 处 / 35 文件**（含 `workflows/engine.py` 11、`agents/orchestrator.py` 5、`seed.py` 5 等）。
  **只减不增**；新增必须写明原因注释（L-6）。
- `services/scheduler.py` 反向 import `workflows.engine` 与 `agents.discovery`：登记为债务，Phase 2 通过事件总线解耦。
- `agents/supplier.py` 反向 import `services.commercial_analytics`：登记为债务。

---

## 4. 命名规范

| 对象 | 规则 | 示例 |
|---|---|---|
| 模块 / 文件 | 小写 + 下划线 | `platform_rules.py` |
| 类 | 大驼峰 | `BaseAdapter`、`WorkspaceContext` |
| 函数 / 变量 | 小写 + 下划线 | `resolve_workspace_context()` |
| 常量 | 全大写下划线 | `DEFAULT_RULE_PACKS` |
| 私有成员 | 单下划线前缀 | `_read_setting()` |
| 测试文件 | `test_<被测对象>.py` | `test_workspace_context.py` |
| 测试函数 | `test_<行为>_<预期>` | `test_role_permission_matrix` |
| 迁移文件 | `<日期>_<序号>_<描述>.py` | `20260923_09_users_nullable_workspace.py` |

### 4.1 业务域命名冲突（须修正）

| 冲突 | 现状 | 规定 |
|---|---|---|
| `settlement` | `routers/finance.py` 指**平台结算**；`routers/settlements.py` 指**供应商应付结算** | 前者统一改称 `platform-settlement`；新增接口禁止再用裸 `settlement` |
| `forecast` | 散落于 `bi.py`、`suppliers.py`、`purchases.py` 三处 | 新增预测能力统一挂 `/bi/` 域下 |
| `match` | `suppliers.py`（货源匹配）与 `factory_network.py`（工厂机会匹配） | 新增匹配能力须在路径中带域前缀 |

---

## 5. 文件规模与拆分阈值

| 类型 | 警戒线 | 硬上限 | 超出时 |
|---|---|---|---|
| Python 模块 | 300 行 | 500 行 | 按职责拆分为包（目录 + `__init__.py`） |
| Python 函数 | 50 行 | 80 行 | 提取私有函数 |
| Vue 单文件组件 | 300 行 | 400 行 | 抽 `components/` 子组件与 `composables/` |
| 测试文件 | 400 行 | 600 行 | 按被测对象拆分 |

**当前超标（2026-09-24 实测，存量债务见 §11）**：

| 文件 | 行数 | 阈值 | 说明 |
|---|---|---|---|
| ~~`app/services/platform_adapters.py`~~ | ~~1158~~ | ~~500~~ | ✅ **已完成**：已拆为 `services/adapters/` 包（12 模块，最大 309 行），DEBT-05 关闭 |
| `tests/test_api.py` | **1041** | 600 | DEBT-11：按业务域拆分（2026-09-24 复测：原记 857，已涨 184） |
| `scripts/backup_restore_drill.py` | 805 | 500 | 运维脚本，允许放宽（三段式 CLI，逻辑内聚） |
| `app/models.py` | **848** | 500 | **例外**：见下方说明 |
| `scripts/migration_preflight.py` | 672 | 500 | 运维脚本，12 项检查各自独立，拆分收益低 |
| `app/seed.py` | **420** | 300（警戒） | 演示数据构造，Phase 2 可拆 `seed/` 包 |
| `tests/test_deep_domains.py` | **458** | 400（警戒） | 四域对抗测试，按域分文件即可（原记 352，已涨 106） |
| `app/services/workspace_context.py` | **343** | 300（警戒） | 身份 Context 唯一入口，保持单文件便于审计 |
| `app/services/alerting.py` | 341 | 300（警戒） | **新登记**（此前漏登） |
| `app/auth.py` | 331 | 300（警戒） | **新登记** |
| `app/routers/shops.py` | 328 | 300（警戒） | **新登记** |
| `app/services/knowledge_learning.py` | 326 | 300（警戒） | **新登记** |
| `app/agents/discovery.py` | 326 | 300（警戒） | **新登记** |
| `app/routers/purchases.py` | **319** | 300（警戒） | 采购 + 代发同域 |
| `tests/test_ai_native_p2.py` | 392 | 400（警戒） | **新登记** |
| `frontend/src/views/PlatformAdmin.vue` | **528** | 400 | DEBT-12（原记 518） |
| `frontend/src/views/Shops.vue` | 473 | 400 | DEBT-12 |
| `frontend/src/views/Suppliers.vue` | 380 | 300（警戒） | DEBT-12 |
| `frontend/src/views/Listings.vue` | 358 | 300（警戒） | DEBT-12 |
| `frontend/src/views/Products.vue` | 338 | 300（警戒） | DEBT-12 |

> **`models.py` 例外**：数据模型集中定义便于 Alembic 与 ORM 关系维护，允许超过 500 行，但**必须保持纯定义**，禁止混入业务逻辑。

---

## 6. 数据库与迁移规范

| 编号 | 规则 |
|---|---|
| M-1 | 所有结构变更**必须**通过 Alembic 迁移；禁止手工改表 |
| M-2 | 迁移文件**只增不改**；已执行的迁移禁止编辑（含改注释） |
| M-3 | 每个迁移必须实现可用的 `downgrade()`；无法回滚的必须写明原因 |
| M-4 | 数据回填类迁移必须**幂等**（重复执行结果一致）并带硬性断言 |
| M-5 | 迁移执行前必须生成冷备并跑 `scripts/migration_preflight.py`；P0 未清零不得执行 |
| M-6 | 禁止在迁移中 import `app.models`；使用原生 SQL 或 `sa.table()` 轻量定义 |
| M-7 | 新增含 `tenant_id` 的表必须同时声明 `tenant_id → tenants.id` 外键 |
| M-8 | 新增 Agent / AI 能力**禁止**直接建表；须走 Agent OS 架构 §9 的 Action 模型 |
| M-9 | **WAL 模式下"文件哈希未变"不能证明"数据未变"**：判断主库是否被写必须同时比对**行数**（或先 `wal_checkpoint(TRUNCATE)`）；恢复主库时**必须连同 `-wal` / `-shm` 一起删除**，否则残留 WAL 会被回放到新库 |

> **M-7 说明**：`models.py` 当前定义 45 张表（含 `tenant_id` 的 42 张），其中仅 `users`、`tenant_settings` 声明了 `tenant_id → tenants.id` 外键，**40 张缺失**。这导致 `PRAGMA foreign_key_check` 返回 0 违规**不能**作为租户隔离的合规证明（历史 tenant 0 孤儿数据 37 行即因此漏检）。
>
> **表数口径**：主库 52 张表 = `models.py` 45 张 + Alembic 独有的 6 张（`workspace_profiles` / `workspace_memberships` / `workspace_roles` / `permissions` / `role_permissions` / `membership_data_scopes`，见 D-7）+ `alembic_version`。

> **M-9 说明（D17 实测踩坑）**：做"隔离性检测"的回退法验证时，故意让服务连回主库，
> 跑完后主库文件 **SHA256 完全没变**，但**总行数从 3,169 变成 3,230**——因为新数据
> 先写进了 `erp.db-wal`。若只比对哈希就会**误判为"隔离有效"**，把一个真实发生的
> 数据污染当成通过。
>
> 两个必须记住的推论：
> 1. **检测**：任何"主库是否被写"的校验，都要同时看行数（`e2e_feasibility.py` 已如此实现）；
> 2. **恢复**：从冷备恢复时必须 `erp.db` + `erp.db-wal` + `erp.db-shm` 一起删，
>    否则残留 WAL 回放会把被污染的数据"复活"进来（与 `conftest.py` 删测试库时的
>    教训同源，见该文件 `_remove_db_files` 的注释）。

---

## 7. 生成物与临时产物管理

### 7.1 必须被忽略（`.gitignore` + `.dockerignore` 双写）

```
__pycache__/            *.pyc              .pytest_cache/
backend/erp.db          backend/*.db       backend/test_erp*.db
backend/*.db-wal        backend/*.db-shm   backend/*.db-journal
backend/*.db.bak-*      !backend/*.db.example
frontend/node_modules/  frontend/dist/     frontend/.zcode/
*.log                   .env               nul
```

> **为什么 WAL 旁文件必须单独列**：`backend/*.db` **不匹配** `erp.db-wal` 这类名字。
> 漏写会把 4MB+ 的 WAL 文件误纳入版本控制（`.dockerignore` 早已覆盖，`.gitignore` 曾漏）。

### 7.2 规则

| 编号 | 规则 |
|---|---|
| G-1 | 新增任何生成物前，**先**把忽略规则写进 `.gitignore` 与 `.dockerignore` |
| G-2 | 禁止在仓库内用 `> nul`（Windows 保留设备名会生成垃圾文件）；重定向丢弃输出用 `> $null` |
| G-3 | 调试脚本用完即删；需保留的必须移入 `backend/scripts/` 并写明用途 |
| G-4 | `*.db` 一律不进版本控制；示例数据通过 `app/seed.py` 重建 |

---

## 8. 测试规范

| 编号 | 规则 |
|---|---|
| T-1 | 新增业务能力必须带测试；Bug 修复必须先写能复现的失败测试 |
| T-2 | 测试**不得**依赖执行顺序；共享夹具用 pytest fixture |
| T-3 | 涉及权限/租户隔离的改动，必须同步更新 `tests/test_security.py` 的权限矩阵 |
| T-4 | 测试断言必须与被测语义一致；**禁止**为让测试通过而放宽断言 |
| T-5 | 涉及数据库结构的改动，必须同步更新 `tests/test_migration_preflight.py` |
| T-6 | 缓存/聚合逻辑的测试**必须覆盖「数据变化」**（0→有、有→更多、有→0），只测「0→有」不算覆盖 |
| T-7 | 涉及 `limit`/`offset` 的接口，测试数据量**必须超过 limit**，并断言排序优先级项仍在结果中 |
| T-8 | **禁止恒真断言**：`>= 0`、`x == 同一对象`、空集合上的 `all(...)`、`try/except: pass` 吞失败、`pytest.skip` 兜底前置。断言必须能因被测代码出错而失败 |
| T-9 | **禁止硬编码序号定位**（`steps[7]`、`items[0]` 假定顺序）。改按语义键定位（`next(s for s in steps if s["action"] == ...)`）或用契约字段（`seq`）比较 |
| T-10 | **测试夹具不得删除业务数据**：任何"删库/清表"路径必须显式校验目标不是业务库（见 `conftest.py::_guard_test_db_path`） |
| T-11 | 新增回归测试必须用「**临时回退修复 → 确认测试失败 → 恢复**」证明其有效；无法证明时须在 docstring 标注为"契约守护"而非"缺陷回归" |
| T-12 | **验收脚本自身必须可靠**：脚本选用的前置数据必须显式探测（不得假定 `items[0]` 可用）；数据前提缺失时报 `SKIP` 并说明原因，**不得伪装成 `FAIL`**；断言必须针对"本次操作产生的对象"，不得针对"全局汇总值" |
| T-13 | **可行性验证必须真启动服务**：进程内 `TestClient` 全绿 ≠ 可部署。涉及"项目可实际运行"的结论，必须真启动 uvicorn + 真实 HTTP 调用 + 静态前端可访问，且**在数据库副本上执行**（不碰主库） |
| T-14 | **回退法变异只能改「被测逻辑」，不得同时修改「守护断言」**：两者一起改等于自己拆掉报警器，会得出"守护无效"的假结论。必须保留断言、只让被测行为坏掉 |
| T-15 | **需要全量数据时必须分页遍历**（`tests/conftest.py::fetch_all`、`scripts/security_data_audit.py::get_all`），禁止用大 `page_size` 一把梭；遍历函数必须断言「取回条数 == total」 |
| T-16 | **审计/校验脚本禁止抽样**：抽样得出的「无问题」结论不成立。实测主库订单 518 条而脚本只取 500 条，最后 18 条从未被审计却仍打印「已全覆盖」 |
| T-17 | 测试**禁止**在业务库创建 `schedules` 记录；确需验证调度逻辑必须用测试库并断言清理。**排查主库异常时必须检查 `schedules.enabled`**——残留任务会持续运行，不会被「不查询」规避（见 D20） |
| T-18 | **新增验证脚本后必须逐项用回退法验证每个检查点的判别力**：「整体通过」不代表每个检查点都有效。实测 `docker_feasibility.py` 首版的「依赖版本比对」就检不出「Dockerfile 没引用锁定清单」（兼容区间恰好解析出相同版本），补结构检查后才有效（见 D21） |
| T-19 | **修复安全缺陷时必须验证「开关打开」的路径**：只在默认（关闭）态验证等于没验证。实测 DEBT-23 上一版把 `starlette.middleware.proxy_headers`（starlette 1.x 已移除）当可用模块，开关关闭时全绿、打开即崩——**负向交付**，只有真部署才触发（见 D22） |
| T-20 | **部署类配置必须真跑端到端并断言链路效果**，不能只验「容器起来了」。TLS 要断言应用侧**真的看到了 https**——Caddy 无条件转发，即使应用没开信任开关也返回 200（见 D22 第 5 项） |
| T-21 | **安全开关必须配「来源限定」**：只给「信任/不信任」布尔开关，实际会退化成信任所有来源。实测 `FORWARDED_ALLOW_IPS=*` 下直连即可把客户端 IP 伪造成任意值（见 D22 第三节） |
| T-22 | **放行路径白名单必须用精确匹配，不用前缀匹配**——前缀会把同前缀下的写语义端点一并放行。改白名单后必须用回退法验证边界仍被拒（见 D23 第一节） |
| T-23 | **同一实体在不同层（Service / Router）的查询条件必须一致**。实测 `SupplierPortalMember.status` 校验 Router 有、Service 无，形成 fail-open；当同类路径已有同等校验时，缺它的分支即疏漏而非设计（见 D23 第二节） |
| T-24 | **非 ORM 身份对象必须提供自己的序列化方法**，通用 `to_dict` 不得承担身份语义。新增身份形态时只改 `identity_snapshot`，不得在各端点分别做鸭子类型判断（见 D25） |
| T-25 | **「靠巧合正确」必须显式化**。当漏传某标记恰好不改变结果时，必须补「结构性断言」（拦截调用捕获实参），而非依赖端点行为——否则一次无关重构就会让它静默错乱（见 D25） |
| T-26 | **同一概念的标记名必须与冻结契约一致**。`is_impersonated` / `is_impersonating` 这类只差后缀的并存命名，是排查事故的经典陷阱（见 D25） |
| T-27 | **双读改造必须同时实现写入侧**。只做读取侧会让新数据掉到 legacy 分支，且**改权限不生效**（降权静默失败）——这类缺陷在存量数据上完全不可见（见 D26） |
| T-28 | **写侧与读侧必须共用同一张映射表**（如 `normalize_legacy_role`）。两份手工维护的映射必然漂移（见 D26） |
| T-29 | **渐进启用的探测门禁只用于「由迁移创建的表」**。对 `create_all` 一定建表的 ORM 表使用探测门禁，会让清理逻辑静默 no-op、反而制造外键失败（见 D26） |
| T-30 | **设计变更推翻守护测试前提时，必须改写守护点而非放宽断言**。D24 删除前端兜底表后，「两张表一致」的守护失效——正确做法是改为「不存在第二份表」（见 D24/D26） |
| T-31 | **安全边界（写权限）与体验兜底（路由/展示）必须分开决策**。把两者绑在一起会导致「要么全删、要么全留」的伪二选一（见 D24） |
| T-32 | **前端权限兜底表一律视为缺陷**。权限事实源只能是后端 Context；前端手工维护第二份表必然漂移，且可被客户端伪造（见 D24） |
| T-33 | **「平台级/全局」语义的表禁止用魔法 ID 作哨兵值**（如 `tenant_id=0`）。必须用 NULL + 列 nullable，与 `users` 的 superadmin 处理保持同一模式。哨兵值会让孤儿检测失去判别力（见 D27） |
| T-34 | **SQLite 加外键只能重建表，且外键必须具名**。匿名外键既无法创建（`Constraint must have a name`），反射出的 `name` 也是 `None`，`downgrade()` 无法安全删除（见 D27） |
| T-35 | **表重建类迁移必须做前后快照比对并硬性断言**（列 / 索引 / 既有外键 / 行数）。SQLite 重建会静默重建索引与既有外键，不做比对就无法发现丢失（见 D27） |
| T-36 | **测试库与生产库建库路径不同时，结构断言可能对迁移缺陷免疫**。测试库走 `create_all`（按模型建表）时，迁移清单的遗漏会被完全掩盖——必须额外加「清单 vs 清单」的直接比对，并用回退法验证判别力（见 D27） |
| T-37 | **拆包/搬移代码后必须验证 monkeypatch 点仍指向真实调用点**。补丁落在「门面」而调用点在「子模块」时会**静默失效**（测试全绿但实际没测到目标代码）；验证方式：断言 `facade.X is 调用点模块.X` + 判别力测试证明补丁改变了行为（见 D28） |
| T-38 | **按块搬移源码必须显式带上装饰器**。AST 的 `node.lineno` 不含 `decorator_list` 行，漏掉后 `@dataclass` / `@property` / `@staticmethod` 全部丢失，且只在运行时才暴露（见 D28） |
| T-39 | **模块搬进子包后相对导入层级必须重算**。`from ..X` 在 `a/b/c.py` 与 `a/b/pkg/c.py` 中指向不同模块（见 D28） |
| T-40 | **拆包不得改变对外导入路径**：保留兼容门面，把「路径不变」变成硬约束，避免测试补丁点与应用导入同时漂移（见 D28） |
| T-41 | **架构红线必须由静态扫描守护，不能靠评审**。L-3（禁止 Agent 间 P2P）的违规在功能上是「能跑通」的——照算出利润、测试照绿，只有读源码才能发现。实测 `FactoryOpportunityAgent -> PricingAgent` 就是这样漏掉的。守护测试须用 **AST** 而非正则，且必须覆盖**函数体内的延迟 import**（违规的常见形态） |
| T-42 | **静态扫描器必须区分相对导入层级**。`from .x`（level=1，包内同级）与 `from ..x`（level=2，跨层）语义完全不同；不区分会把 `.models` / `.db` 误报成 P2P，门禁沦为噪音后真正违规被淹没（实测第一版即如此）。扫描器同样需要**判别力样本**验证，否则「0 处违规」可能只是检测器失灵 |
| T-43 | **已登记债务的豁免清单要反向断言「债务仍存在」**。只写「豁免」时，债务修好后豁免项会悄悄变成死代码，台账与实际长期脱节（规范 Doc-5）。`test_known_service_to_agent_debt_is_still_present` 即为此设——修好即变红，强制同步台账 |
| T-44 | **测试夹具的表名必须与生产一致**。规则/清单类代码常按生产表名写死（如 `MARKER_RULES` 里的 users/products/...），玩具表名（`parents`/`children`）会让被测脚本一行都识别不到——测试「跑通却什么都没验证」，是最隐蔽的**恒真断言**。实测 `test_cleanup_probe_data.py` 首版 5 项红即由此而来 |
| T-45 | **守卫型工具（校验器/检查器）的测试重点是「判别力」而非「跑通」**。恒真通过的校验器比没有校验器更危险——它让人误以为被校验对象是自洽的。每个检查项都必须有「构造违规 → 断言被抓到」的用例，外加「合规输入不得误报」的反向用例 |
| T-46 | **同一份文档不得被扫描两遍**。集合拼接（`live_docs + glob(...)`）在两者重叠时会让同一问题重复上报（实测重复率 100%）。用解析后的绝对路径去重——重复告警会让使用者对整个门禁失去信任 |
| T-47 | **Windows 上用 PowerShell 写文档时，反引号是转义符**。markdown 的行内代码标记 `` `x` `` 在 PowerShell 双引号字符串里会被解析：`` `r `` → 回车、`` `n `` → 换行、`` `e `` → ESC(0x1B)、`` ``` `` 三连会被压成 `` ` ``。实测后果：4 个文档共 **18 处代码围栏塌缩**、3 个标识符被吃掉首字符（`roleKey`→`oleKey`、`routeRedirect`→`outeRedirect`、`erp_user.role`→`rp_user.role`）、1 处路径被撕成 3 行，且**从首次提交起潜伏 20 轮未被发现**——因为损坏后的文本「读起来仍然通顺」。写文档一律用 `[System.IO.File]::WriteAllText` 或单引号 here-string，禁止用双引号字符串拼 markdown |
| T-48 | **`write_text` 在 Windows 上会把 `\\n` 写成 CRLF**。Python 的 `Path.write_text()` / `open(..., "w")` 默认 `newline=None`，在 Windows 上把 `\\n` 翻译成 `\\r\\n`。本仓库 `.gitattributes` 锁 `eol=lf`，写文档/代码后必须显式 `newline="\\n"`（或 `write_bytes` 后自行归一），否则每次编辑都会污染整个文件的行尾 |
| T-49 | **内容损坏必须由机器检查，人工评审对它无效**。T-47/T-48 造成的损坏在功能上零影响（测试照绿、服务照跑），但会污染文档阅读与检索。已固化为 `check_docs_consistency.py` 的 **D. 文本卫生**（控制字符 / BOM / CR 行尾 / 残缺围栏 / 未闭合行内代码）与 **E. 换行注入**（字面量被写成真换行） |
| T-50 | **同一问题只报一次**。CR 行尾同时满足「行尾检查」与「控制字符检查」，第一版两处都报 → 同一文件重复 3 条告警（与 T-46 同类）。判定职责必须唯一：行尾归行尾检查，控制字符检查显式排除 CR |
| T-51 | **代码重构后，文档里的 `file.py:123` 行号必然失效**。DEBT-05 把 `platform_adapters.py` 从 1303 行拆成 12 模块后，`项目介绍与功能地图.md` 仍有 **11 处**引用旧行号（如引用 `platform_adapters.py` 的 71-539 行，而门面只剩 131 行）——**检查 B（路径引用有效）全绿**，因为文件确实还在。行号引用必须单独检查（`check_docs_consistency.py` 的 F 项），且拆包/删函数后应优先把引用改成**符号名**（`adapters/base.py` 的 `BaseAdapter`）而非行号 |
| T-52 | **索引层声称「已逐条核对」必须由机器持续核对**。`docs/adr/README.md` 明确写「锚点已逐条核对、覆盖全部 D 编号」，实测 **D22~D26 锚点各偏移 2 行、D27~D31 完全未收录**（表停在 D26 却写「总计 28 条」）。人工核对在**每次追加决策后**都会失效——锚点必须在 CI 校验（`check_docs_consistency.py` 的 G 项） |
| T-53 | **同一份信息不得维护在两个地方**。`docs/archive/README.md` 曾维护「活文档清单」，实测列 11 个而实际 18 个（漏 7 个，含 4 份零引用文档）——保留第二份清单 = 保留漂移源。改为**单一来源** `docs/DOCUMENT_MAP.md` + 在旧位置留废止说明并指向新源 |
| T-54 | **已关闭的任务/子代理不得留下「进行中」标记**。实测 `docs/子代理实施索引-20260923.md` 里 **Godel**（P1-04）在第 33 行标「进行中」，而同一文件第 46 行已写「已完成，总结已入索引，已清理」——**同一份文档内自相矛盾**；**Parfit**（DEBT-07 `CONTRIBUTING.md`）标「🔄 进行中」，而 `CONTRIBUTING.md` 早已存在（16050 字节）、规范 §11 的 DEBT-07 已标「已完成」。这类**僵尸状态**会让人误以为「还有活没干完 / 有进程还占着资源」，**直接误导调度决策**。已固化为 `check_docs_consistency.py` 的 **I 项**：同一 ID 不得同时标「进行中」与「已完成」，且「进行中」不得挂在规范 §11 已关闭的债务上 |
| T-55 | **门禁的豁免/白名单必须配反向断言，证明「被豁免的东西不是被守护的对象」**。本轮给 L-3 门禁的 `_ALLOWED_INTERNAL` 加入 `contracts`（Agent 契约声明模块：零 Agent 类、零 I/O），否则 `from .contracts import CONTRACTS` 会被误报成 Agent 间 P2P 调用。但**只加白名单 = 开一个静默后门**：若哪天有人把真 Agent 塞进豁免清单，「扫描 0 处违规」就退化成恒真断言——正是 L-3 曾漏掉 `factory_opportunity -> pricing` 的同一种失败模式。故新增 `test_allowed_internal_modules_contain_no_agent_classes`，用 AST 断言被豁免模块里**没有任何 `BaseAgent` 子类**。同一模式已用于 DEBT-09（`test_known_service_to_agent_debt_is_still_present` 反向断言债务仍存在）。**判定口径**：每条豁免都必须能回答「凭什么它不是被守护的对象」，且该理由由**测试**承担，不靠注释 |
| T-56 | **行尾/BOM 门禁必须覆盖源码，不能只覆盖文档**。D 项只扫 `docs/**/*.md`，于是**本轮实测踩到**：新写的 `backend/app/agents/contracts.py` 落了 **400 处 CRLF**，校验器**全绿通过**，`git commit` 只给一条 `warning: CRLF will be replaced by LF`（长输出里极易忽略）。后果两层：① 工作区长期留 CRLF，并产生「`git status` 显示已修改、`git diff` 却为空」的**假状态**（stat 缓存失效），直接误导「是否已提交」的判断；② 同类写入路径对任何脚本都成立——本仓库已有真实损害先例：`docker-entrypoint.sh` 变 CRLF 后容器报 `bad interpreter: /bin/sh^M`。已固化为 `check_docs_consistency.py` 的 **K 项**（非 Markdown 的 BOM/CRLF，按 NUL 字节跳过二进制、排除 `node_modules` 等目录，后缀豁免从 `.gitattributes` 解析以免留第二份清单）。**判定口径**：凡「格式契约」类检查，覆盖面必须与契约声明的范围一致（`.gitattributes` 管全仓，检查就不能只管网页文档） |

> **T-4 说明**：本轮修复中，`test_security.py` 曾把「superadmin 可访问租户业务 API」固化为正确行为，`test_api.py` 曾把「租户停用」误断言为「租户到期」。两者都是断言与语义脱节，属于**测试在保护错误行为**，比缺测试更危险。

> **T-6 / T-7 说明（D13 教训，两条都是「测试全绿但功能不可用」）**：
> - **T-6**：`product_performances` 缓存的失效判据只比「有无订单」，实测 5 单变 25 单仍返回旧值；
>   而用例只测了 `0 单 → 10 单` 的翻转，恰好绕过缺陷。**缓存有效性必须看数据是否变化，不是数据是否存在。**
> - **T-7**：`list_alerts` 先按时间 `limit 100` 再在内存按级别排序，实测 120 条新低风险 + 1 条较早高风险时
>   高风险完全不可见；用例数据量小于 limit，恰好绕过。**任何 limit 都必须发生在排序/过滤之后。**

> **T-8 ~ T-11 说明（D15 教训，来自并行工具（zcode）与审计的共同发现）**：
> - **T-8**：实测到 4 类恒真断言——`deleted["orders"] >= 0`（计数恒真）、
>   `read_only == wc._READ_PERMISSIONS`（同一对象自比较）、
>   `assert len(items) >= 0`、以及 `if not alerts: pytest.skip(...)`（单跑必跳过）。
>   这类"假测试"给出虚假安全感，比缺测试更危险。
> - **T-9**：`test_api.py` 用 `steps[7]` 断言"被拦步骤"，而模板里第 7 步是
>   `review_batch`（下标 6）——顺序调整后测试失败但**指向错误的排查方向**。
> - **T-10**：`conftest.py` 的 `ERP_TEST_DB` 无防呆，误设 `erp.db` 会让会话夹具
>   直接删掉业务主库（实测已加校验并验证拒绝启动）。**删除类夹具必须校验目标**。
> - **T-11**：写了回归测试不等于测试有效。本轮 2 条修复用回退法证明有效，
>   另 1 条实测**无法复现差异**，已如实降级标注——避免"二次假绿"。
>   **D16 补充（更强的教训）**：本轮新增的"选品门槛"断言**首版判别力不足**——把
>   `pick_candidates(min_total=60)` 变异为 `0` 后断言**依然通过**，因为演示租户里种子商品
>   分数普遍 ≥60，占满了 `limit` 窗口，低分商品本来就挤不进来。改为**隔离租户**场景
>   （新建租户 + 3 个低分商品，租户内无其它候选）后变异立刻被抓到。
>   **结论：断言必须在"被测行为坏掉时必然失败"的场景下设计，回退法是唯一可靠证据。**

> **T-14 ~ T-16 说明（D19 教训：静默截断会让"隔离比对"假绿）**：
> 13 个列表端点的 `page_size` 原本**无上界**。实测测试库 `orders` 恰好 500 条，
> 与测试里硬编码的 `page_size=500` **完全相等**——当时没截断纯属侥幸，
> seed 一增订单数，跨租户隔离比对与利润恒等式核对就会静默漏数据。
> 主库更能说明问题：`security_data_audit.py` 写死取 500 条并注释"应全覆盖"，
> 而主库实际 518 条，**最后 18 条从未被审计过**。
>
> 处置：新增 `app/pagination.py`（`MAX_PAGE_SIZE=200`，越界 **422 快速失败**），
> 13 个端点统一改用 `PageNum`/`PageSize`，并提供分页遍历工具。
> 加上限后**立刻有 3 个测试失败**（它们本来就依赖"无上限"）——这正是修复的价值：
> 把"将来会静默出错"变成"现在立刻报错"。
>
> **T-14 是本轮最有价值的教训**：做回退法验证时，第一版把 `fetch_all` 的
> 「只取第一页」变异**和**它的总数一致性断言**一起改掉了，结果测试通过，
> 差点得出"守护无效"的错误结论。第二次**只变异遍历逻辑、保留断言**，
> 立刻被抓到。**变异测试的前提是报警器必须还在。**

> **T-12 / T-13 说明（D17 教训：验收脚本自己失灵，把"功能正常"误报为"功能坏了"）**：
> 2026-09-24 首次对**真实运行的服务**跑 `scripts/live_acceptance.py`，7 步里 2 步 FAIL。
> 逐条定位后确认**业务功能完全正常，是脚本自己有三处缺陷**：
> 1. 采购闭环取 `GET /products` 的**第一个**商品建单——该商品恰好没有 `supplier_offers`
>    记录，于是 404「无可用货源报价」。**是脚本选错商品，不是采购坏了**。
> 2. 订单闭环传 `platform="shopee"`，而 `/orders/sync` 是**演示订单入口**，只接受
>    `demo:<平台>`（传真实平台名返回 409）。脚本用错了接口语义。
> 3. 采购断言要求「该供应商应付**总额归零**」——但供应商 1 存在种子数据里的历史
>    未结清结算单（`ST#3 pending / 158.4`），于是**每次跑都必然失败**。应断言
>    「**本次生成的结算单**已 paid」。
>
> **教训**：`TestClient` 全绿让人以为"已经验证过了"，但**没有任何一条测试真正启动过
> 服务、加载过前端构建产物、走过一次真实 HTTP**。验收脚本一旦自己不可靠，产生的
> 是**假失败**（浪费排查时间）或**假通过**（掩盖真缺陷），两者都比没有脚本更危险。
> 修正后 7 步全 PASS（`exit=0`），并保留 `SKIP` 语义用于"数据前提缺失"。

**当前基线以 `docs/baseline.json` 为单一事实源**（由 `backend/scripts/refresh_test_baseline.py`
采集，**禁止手工编辑**）：后端 `pytest -q` 与**反序文件列表**跑均应达到其 `backend.tests`；
前端 `npm test` 应达到其 `frontend.tests`。其余门禁：`ruff check` → All checks passed；
`migration_preflight.py` → 12 项全 PASS；**真启动服务端到端验收** →
`scripts/live_acceptance.py` 7 步全 PASS / exit=0。**任何提交不得低于此基线。**

> **为什么不再写具体数字（2026-09-24 改）**：基线数字此前手工维护在 6 个文档里，
> 实测**同时过期且互不一致**（并存 199 / 257 / 264 / 179 / 165 五个值，真实值 291）。
> 现由 `scripts/check_docs_consistency.py` 在 CI 中强制校验，活文档里出现与事实源
> 不符的 `N passed` 会直接判失败。

> **反序跑是强制自检项（D16 新增）**：顺序依赖是"单跑绿、全量红"的唯一根因，而普通全量跑
> 未必能暴露它（取决于文件名字典序）。提交涉及测试夹具/种子数据的改动前，必须额外跑一次
> **反序文件列表**：`python -m pytest (ls tests/test_*.py | sort -r) -q`。

> **测试可重复性硬要求（D11 教训）**：
> - 测试必须能**重复跑**（同一测试库连跑两次全绿）与**并发跑**（多进程各自独立库）。
>   曾因 `_seed()` 对全局唯一的 `settings` 表不幂等 + 测试库固定名 + WAL 旁文件残留，
>   并发/重复运行时爆发 100+ 个 `UNIQUE constraint failed: settings.key`。
> - 新增任何「无租户维度的全局表」时，种子写入必须走幂等的「缺什么补什么」路径。
> - 测试库默认名带进程号（`test_erp_<pid>.db`）；需要固定名时用 `ERP_TEST_DB` 显式指定。

> **T-2 已发生的两次真实违反（务必避免重犯）**：
> 1. 共享夹具曾定义在 `test_api.py` 内、被其他文件跨模块 import，隐含「文件名排序决定成败」的
>    顺序依赖；某个排序更靠前的模块先建连接即触发 `WinError 32` 整批报错。已下沉 `tests/conftest.py` 根治。
> 2. 改 admin 口令的用例递增 `token_version` 使会话级共享 token 失效，导致后续文件集体 401。
>    已通过「`auth_headers` 函数级作用域 + token 失效自动重登」与「用例级快照还原」双重防护。
> 教训：**任何会改变全局状态的测试，必须在用例级还原，或让共享夹具自愈。**

---

## 9. 工具链与代码风格

### 9.1 已配置

- `backend/pyproject.toml`：ruff 规则集（`E` `F` `W` `I` `UP` `B`；行宽 100；`E501` 关闭以兼容存量）
- `backend/requirements-dev.txt`：开发依赖声明（人读）
- `backend/requirements-dev.lock.txt`：开发依赖**精确锁定**（CI 与本地实际安装用）
- `backend/requirements.lock.txt`：运行时依赖**精确锁定**（Docker 镜像用）

### 9.2 使用方式

```bash
cd backend
# 推荐：用锁定清单，保证与他人/CI/镜像完全一致
pip install -r requirements-dev.lock.txt
python -m ruff check .          # 只检查，不改动
python -m ruff check --fix .    # 自动修复可安全修复项
python -m ruff format .         # 格式化
```

> **依赖锁定规则（D-9）**：`requirements*.txt` 是「声明」，`requirements*.lock.txt` 是「锁定」。
> - 新增/升级依赖 → 改**声明**文件，然后重新生成锁文件，**重跑全量测试**，测试通过才提交；
> - 禁止只改锁文件不跑测试；禁止手工编辑锁文件（会被下次生成覆盖）；
> - 锁文件含中文注释时，**首行 `# -*- coding: utf-8 -*-` 不可删**：旧版 pip（实测 23.2.1）在中文
>   Windows 上按 GBK 解码，缺声明会直接 `UnicodeDecodeError` 崩溃，表现为「安装依赖失败」；
> - `pytest` / `ruff` **只属于开发依赖**，禁止放回运行时声明（会把测试框架装进生产镜像）。

### 9.3 风格约定

| 编号 | 规则 |
|---|---|
| S-1 | 缩进 4 空格（Python）/ 2 空格（JS/Vue）；文件末尾保留单个换行 |
| S-2 | 导入分组：标准库 → 第三方 → 本地，组间空行；禁止 `import *` |
| S-3 | 文件统一 UTF-8（无 BOM）；中文注释与中文错误信息一律保留 |
| S-4 | 公共函数必须有 docstring，说明「做什么」而非「怎么做」 |
| S-5 | 禁止裸 `except:`；捕获异常必须记录或转换为明确错误 |
| S-6 | 面向用户的错误信息用中文，日志与内部异常可用英文 |

### 9.4 CI 门禁（已落地）

| 阶段 | 门禁 | 状态 |
|---|---|---|
| 当前 | 后端 `ruff check` + `pytest -q`；前端 `npm test` + `npm run build` | 已启用 |
| 下一步 | 逐步收紧规则集（先移除 `B008` 例外，再启用 `E501`） | 待存量格式化 |
| 长期 | 追加 `mypy` 关键模块类型检查 | 规划中 |

**当前基线**：测试用例数以 `docs/baseline.json` 为单一事实源；`ruff check` → All checks passed；`migration_preflight.py` → 12 项全 PASS（`P0_fail=0`）；`docker_feasibility.py` → 12 项全 PASS；`tls_feasibility.py` → 8 项全 PASS。

> **规则集说明**：首轮启用时出现 509 条告警，其中 `B008`（FastAPI `Depends()` 必须写在默认参数）等属框架惯用法误报，已按「只报功能性缺陷」原则显式豁免。豁免项均在 `pyproject.toml` 中标注原因与「只减不增」约束，不允许无理由扩大豁免。

---

## 10. 文档规范

| 编号 | 规则 |
|---|---|
| Doc-1 | **决策的唯一权威源是 `docs/DECISIONS.md`**（按 D 编号追加）。`docs/adr/` 是**镜像/索引层**，不产生第二份真相：只收录「改变架构边界或安全模型」的高价值决策，文件名为 `docs/adr/NNNN-<短横线英文名>.md`（四位补零，按原 D 编号顺序），每篇必须自包含（`Context`/`Decision`/`Consequences`/`Alternatives considered`/`References`）并在 `References` **回指 D 编号**。索引与状态定义见 `docs/adr/README.md` |
| Doc-2 | 一次性报告完成后移入 `docs/archive/`，文件名保留日期 |
| Doc-3 | 活文档必须维护「最后更新」与「状态」字段 |
| Doc-4 | 接口变更必须同步 `docs/CONTRACT.md`；Agent 相关变更必须同步 Agent OS 架构文档 |
| Doc-5 | 禁止文档与代码脱节：文档中引用的路径、字段名、状态值必须可被检索验证。**由 `scripts/check_docs_consistency.py` 在 CI 强制**（基线数字一致 / 路径引用有效 / 台账状态自洽） |
| Doc-6 | **测试用例数只有一个来源**：`docs/baseline.json`（由 `scripts/refresh_test_baseline.py` 采集，禁止手工编辑）。活文档**不得写具体数字**，只写「见 `docs/baseline.json`」——数字会随施工变化，手工抄写到 N 个文档必然漂移。历史性记录（决策记录里的「当次实测」）必须加 `<!-- docs-ok: 原因 -->` 行内标记豁免 |
| Doc-7 | **文档里的引用必须是「可解析路径」而非「裸文件名」**，且**提案中的未来文件**要显式标注（如「提案，未创建」）——否则校验器无法区分「写错路径」与「规划中的文件」 |
| Doc-8 | **文档内容不得含控制字符、BOM，行尾必须 LF，代码围栏必须完整**。这些是「文件本身的损坏」，与内容是否属于历史记录无关，因此检查覆盖面是**全部**文档（不适用 `HISTORICAL_DOCS` 豁免）。由 `check_docs_consistency.py` 的 D/E 两项强制。**非 Markdown 的源码/配置同样受此约束**（由 K 项强制，见 T-56） |
| Doc-9 | **文档引用代码位置时优先用符号名而非行号**。行号会随重构失效，符号名（类/函数名）稳定。必须写行号时，须在改动该文件后同步更新——由 `check_docs_consistency.py` 的 F 项强制（行号不得超出文件实际行数；同名文件歧义时保守跳过，避免误报） |
| Doc-10 | **索引/镜像类文档（ADR 索引、文档地图）的「一致性声称」必须可被校验**。凡写「覆盖全部 X」「已逐条核对」的文档，须有对应检查项；`docs/adr/README.md` 的 D 编号索引锚点由 G 项强制（行号一致 + 无漏收录） |
| Doc-11 | **活文档必须有总索引且被机器强制同步**：`docs/` 根下每个活文档须在 `docs/DOCUMENT_MAP.md` 登记，`docs/archive/` 每个文件须在 `docs/archive/README.md` 登记——由 `check_docs_consistency.py` 的 H 项强制。未登记的文档会成为「没人知道它存在、也不知道哪份已过期」的孤儿（实测 4 份零引用） |

---

## 11. 存量债务台账

> 登记即可，不要求立即整改。每次整改后更新状态。

| 编号 | 债务 | 严重度 | 涉及文件 | 整改时机 |
|---|---|---|---|---|
| DEBT-01 | ~~仓库未纳入版本控制~~ | ~~**P0**~~ | 仓库根 | ✅ **已完成（2026-09-24）**：`git init -b main` + 首次提交 `6215d49`（208 文件 / 0.87 MB / `fsck` 干净）。提交前补齐 `.gitignore` 冷备目录、`_*.py`、`.orig/.bak` 缺口，并新增 `.gitattributes` 锁定行尾 |
| DEBT-02 | ~~`tenant_id=0` 孤儿业务数据 37 行 / 12 张表~~ | ~~P0~~ | `backend/erp.db` | ✅ **已完成**：已清零（含根因修复：superadmin 越权写入 + 审计脚本护栏） |
| DEBT-03 | ~~45 张含 `tenant_id` 的表缺外键约束~~ | ~~**P1**~~ | `migrations/` | ✅ **已完成（2026-09-24）**：迁移 `20260924_16` 补齐 45 张表外键，主库 48/48 张含 `tenant_id` 的表全部受约束（执行前实测缺口是 **45 张**，文档原写「40 张」已过期）。施工中挖出关键阻塞：`platform_rule_packs` 用 `tenant_id=0` 作**平台级哨兵值**（`platform_rules.py:235`），直接加外键会让 `check_updates()` 写入路径崩——按 `users` 先例改为 **nullable + 写 NULL**（见 `docs/DECISIONS.md` D27）。**并发现一个测试盲区**：测试库走 `create_all` 会掩盖迁移清单遗漏（删掉 `products` 后其余用例全绿），已补「清单 vs 清单」直接比对 + 回退法验证 |
| DEBT-04 | ~~无 lint/format 配置与门禁~~ | ~~P1~~ | 全仓 | ✅ **已完成**：已配 `backend/pyproject.toml` + `requirements-dev.txt`，`ruff check` 全绿并接入 CI |
| DEBT-05 | ~~`platform_adapters.py` 1303 行单文件承载 13 个适配器~~ | ~~**P1**~~ | `app/services/platform_adapters.py` | ✅ **已完成（2026-09-24）**：拆为 `services/adapters/` 包（contract / catmap / base / registry + 7 个平台模块，共 12 文件，最大 309 行）；`platform_adapters.py` 缩为 **131 行兼容门面**，对外导入路径与全部 monkeypatch 点保持不变。**拆包中挖出并修掉 3 个真实缺陷**：① 测试 monkeypatch 只落在门面、适配器调用点收不到 → 补丁**静默失效**（实测打到真实 api.sandbox.ebay.com 抛 401）；② `@dataclass` 装饰器在按块搬移时丢失；③ 包内相对导入层级少一层。已加 10 项守护测试 + 回退法验证（见 D28） |
| DEBT-06 | ~~`backend/` 根目录混放 3 个 `.db`，其中 2 个无引用~~ | ~~P1~~ | `backend/*.db` | ✅ 已完成：`test_dbg.db`、`project_goal_acceptance.db` 已冷备后清理，仅留 `erp.db` |
| DEBT-07 | ~~缺 `AGENTS.md` / `CONTRIBUTING.md` / ADR 目录~~ | ~~P1~~ | 仓库根、`docs/` | ✅ **已完成（2026-09-24）三件套齐全**：① `AGENTS.md`（面向 AI 助手，协作红线）；② 仓库根 `CONTRIBUTING.md`（面向人：环境搭建 / 开发循环 / 测试基线 / 迁移流程 / 提交与评审 / Windows 陷阱，与 `AGENTS.md` 互补不重复）；③ `docs/adr/README.md`（权威源 `DECISIONS.md` 的镜像/索引层，含 D1~D26 全量索引表 + 状态定义 + 新增流程）并拆出 7 篇自包含 ADR（`0003`/`0007`/`0018`/`0022`/`0023`/`0024`/`0026`，判定标准=改变架构边界或安全模型） |
| DEBT-08 | `agents/base.py` 自建 `SessionLocal`，绕过依赖注入 | **P2** | `app/agents/base.py:10,19` | Phase 2 Tool Layer 落地时一并解决 |
| DEBT-09 | `services/scheduler.py` 自建 `SessionLocal` + 反向依赖 | **P2** | `app/services/scheduler.py:12,42,57,83,88` | Phase 2 事件总线 |
| DEBT-10 | 函数体内延迟 import：**routers/ 45 处 / 11 文件**；全 `app/` 109 处 / 35 文件（2026-09-24 AST 实测） | P2 | 11 个 router + workflows/engine.py 等 | 只减不增。**台账原写「32 处 / 8 个 router」已过期**（少 13 处）；§4 的「8 个 router」同步修正为 11 |
| DEBT-11 | `test_api.py` 857 行 / 29 用例单文件 | **P2** | `tests/test_api.py` | 按业务域拆分 |
| DEBT-12 | 前端 5 个视图 >300 行 | **P2** | `views/PlatformAdmin.vue` 等 | Phase 1.7 前端接入时评估 |
| DEBT-13 | ~~`docs/` 活文档与一次性报告混放~~ | ~~P2~~ | `docs/` | ✅ 已完成：13 个一次性报告已归档到 `docs/archive/`，附索引 README |
| DEBT-14 | `workspace_profiles.owner_user_id` 7 行全为 NULL | **P2** | 数据 | Phase 1 收尾 |
| DEBT-15 | `membership_data_scopes` 0 行，Guardrail 第二道闸无数据支撑 | **P2** | 数据 | Phase 2 |
| DEBT-16 | ~~`shops` 13 行 role 全为 `sales`（1688 应为 `source`）~~ | ~~P2~~ | 数据 | ✅ 已完成：11 行已修正为 `source`，与平台默认一致 |
| DEBT-17 | `routers/purchases.py` 中 `DropshipIn` 重复定义 | P2 | `app/routers/purchases.py` | 已完成：已删除重复定义 |
| DEBT-18 | `platform_adapters.py` 发布前校验未按声明字段校验 price/stock/images | P1 | `app/services/platform_adapters.py` | 已完成：已按声明逐项校验 |
| DEBT-19 | ~~删店铺直接物理删除，撞 5 张表外键 → 500~~ | ~~P0~~ | `app/routers/shops.py` | ✅ 已完成：改为归档式软删除（`shops.archived_at`，Revision E），凭证即时失效 |
| DEBT-20 | ~~`purge_demo_data` 未按外键拓扑序删除 → 必然 500~~ | ~~P0~~ | `app/routers/shops.py` | ✅ 已完成：抽出 `services/tenant_data_purge.py`，子表在前、父表在后 |
| DEBT-21 | 店铺可见性守卫散落在各路由，靠人肉记得排除归档行 | **P2** | `app/services/shop_scope.py` | 已提供统一入口 `active_shop()`；`routers/orders.py` 已改用，其余 3 处为内联判断，Phase 2 统一 |
| DEBT-22 | ~~`requirements.txt` 全为 `>=`，构建不可复现~~ | ~~**P1**~~ | `backend/requirements*.txt` | ✅ **已完成（2026-09-24）**：新增 `requirements.lock.txt`（运行时 31 包）+ `requirements-dev.lock.txt`（开发 38 包），Docker 与 CI 改用锁定清单；`requirements.txt` 补齐兼容上限。实测：全新 venv 仅装运行锁可**真启动服务**（`/api/health` 200、静态前端 945 字节），开发锁下 `pytest` 231 passed <!-- docs-ok: 2026-09-24 当次实测史实 --> |
| DEBT-23 | ~~无 HTTPS / 反向代理配置~~ | ~~**P0**~~ | 部署层 | ✅ **已完成（2026-09-24）**：Caddy 反向代理（自动 ACME）+ TLS 覆盖层 `docker-compose.tls.yml`；应用侧 `ERP_TRUST_PROXY_HEADERS` + `ERP_TRUSTED_PROXY_HOSTS` 两道闸；基础 compose 绑定收紧为 `127.0.0.1:8000` 并显式声明「TLS 在外部」。新增 `scripts/tls_feasibility.py`（**真 HTTPS 端到端** 8 项全 PASS）+ `tests/test_tls_proxy_config.py`（13 项）。**上一版改动藏 3 个真实缺陷已修**（starlette 模块已移除导致开关一开就崩、`=0` 被误判为已声明、基础 compose 漏声明打断既有部署）——详见 `docs/DECISIONS.md` D22 |
| DEBT-24 | ~~`ERP_ADMIN_PASSWORD` 门禁形同虚设：`auth.admin_bootstrap_password()` 从未被调用，生产环境仍可用 `admin123` 登录~~ | ~~**P0**~~ | `app/seed.py`、`app/main.py` | ✅ **已完成**：新增 `seed._ensure_admin_password()` 并在 lifespan 调用（见 `docs/DECISIONS.md` D10.1），回归测试 3 项 |
| DEBT-25 | 测试共享夹具跨文件 import，存在收集顺序依赖 | **P2** | `tests/` | ✅ **已完成**：夹具下沉 `tests/conftest.py`，`auth_headers` 自愈 + 用例级状态还原（见 D10.2） |
| DEBT-26 | ~~`_seed()` 对全局唯一的 `settings` 表不幂等~~；~~测试库单实例（固定名 + WAL 旁文件残留）~~ | ~~**P1**~~ | `app/seed.py`、`tests/conftest.py`、`.gitignore` | ✅ **已完成**：抽出 `DEFAULT_SETTINGS` + `_ensure_default_settings()`（缺什么补什么）；测试库 PID 隔离 + `ERP_TEST_DB` 覆盖 + WAL 旁文件统一清理；`.gitignore` 补齐旁文件与 PID 库名（见 `docs/DECISIONS.md` D11） |
| DEBT-27 | ~~`page_size` 无上限；调用方用大 `page_size` 做集合比对会被静默截断~~ | ~~**P1**~~ | `app/pagination.py`、13 个 router、`tests/conftest.py`、`scripts/security_data_audit.py` | ✅ **已完成（2026-09-24）**：新增 `app/pagination.py`（`MAX_PAGE_SIZE=200`，越界 422）；13 个列表端点统一改用 `PageNum`/`PageSize`；新增 `fetch_all` 夹具与 `get_all` 辅助函数做**分页遍历取全量**；`test_pagination_edge` 收紧为「超上限必须 422」。回退法验证：去掉上限 → 被抓；`fetch_all` 只取首页 → 被抓 |
| DEBT-28 | ~~`FactoryOpportunityAgent` 直接调用 `PricingAgent`（Agent 间 P2P），绕过 Orchestrator，且**未登记为债务**~~ | ~~**P0**~~ | `app/agents/factory_opportunity.py:30,114-115` | ✅ **已完成（2026-09-24）**：违反 Agent OS §3 / 规范 L-3（协作只能由 Orchestrator 编排）。修法：把成本/利润计算下沉到 `app/services/costing.py`，`PricingAgent` 与 `FactoryOpportunityAgent` 各自调用同一实现——既消除 P2P，又让成本口径**唯一**（两处各写一遍迟早漂移，门禁用的利润率会与定价页展示的不是同一个数）。**根因是「靠评审把关」失效**：该违规藏在方法体内的延迟 import，只扫顶层 import 的写法看不见它；现由 `tests/test_agent_layer_boundaries.py` 用 AST 扫描（覆盖函数体内 import）固化为门禁，并附判别力样本 |
| DEBT-29 | `services/scheduler.py` 反向依赖 `agents/`（越层） | **P2** | `app/services/scheduler.py:88` | 已登记豁免（规范原文即有）；Phase 2 事件总线落地时解决。守护测试 `test_known_service_to_agent_debt_is_still_present` 反向断言其存在——债务修好后测试会红，提醒同步台账（防豁免清单变死代码） |
| DEBT-30 | `services/` 缺「Agent 共享领域计算」层，导致 Agent 各自复制成本口径 | **P2** | `app/services/costing.py` | 本次仅抽出成本/利润；其余共享计算（销量预测口径、平台费率）Phase 2 评估 |
| DEBT-31 | **静默吞异常 17 处**（`except Exception` 块内无 log/raise/rollback；全 `app/` 共 26 处 `except Exception`，裸 `except:` 0 处） | **P1** | `agents/compliance.py:130`、`agents/discovery.py:122/210/365`、`agents/listing.py:238`、`agents/orchestrator.py:164`、`agents/pricing.py:132`、`agents/supplier.py:227`、`ai/knowledge.py:33/116`、`auth.py:284`、`db.py:68`、`routers/bi.py:182`、`routers/purchases.py:112`、`services/scraper.py:240`、`services/workspace_context.py:325/364` | 违反 S-5「捕获必须记录或转换」。2026-09-24 AST 实测（机械粗筛 20 处，人工排除 3 处「实际有记录」：`agents/base.py:46` 调 `self._log`、`agents/orchestrator.py:22` 写 `AiLog`、`workflows/engine.py:186` 写 `step.error`）。**判定口径**：语义上是否记录/抛出（非字面量匹配）。仅 3 处有意图注释（scraper、workspace_context ×2） |
| DEBT-32 | **超阈值函数 11 个**（>80 行硬上限；全 `app/` 共 562 个函数，>50 行警戒线 24 个） | **P2** | `seed.py:200 _seed`(265)、`services/alerting.py:125 scan`(196)、`agents/factory_opportunity.py:25`(126)、`agents/supplier.py:94 forecast`(122)、`routers/orders.py:106 import_csv`(117)、`db.py:78 _migrate_sqlite`(112)、`routers/purchases.py:168 dropship_order`(97)、`agents/discovery.py:196 pick_candidates`(90)、`workflows/engine.py:151 run_workflow`(84)、`agents/listing_review.py:15 review`(82)、`routers/listings.py:187 publish`(81) | 按域拆函数。**口径**：`end_lineno - lineno + 1`，不含装饰器行，**含嵌套函数**（不含嵌套则 >80 为 10 个、>50 为 22 个——两种口径翻转点见 D29 索引） |
| DEBT-33 | 迁移 `import app.models`（违 M-6）2 处 + 空壳 `downgrade()` 1 处，**均未登记豁免** | **P2** | `migrations/versions/20260922_01_commercial_finance_baseline.py:16,20`、`20260922_02_factory_supply_network.py:32` | 补登记豁免说明。空壳 `downgrade()` 已写明原因（M-3 允许例外但须说明）；其余 15 个迁移的 `downgrade()` 均有真实 `op.*`/`sa.text` 调用（已逐个核实） |
| DEBT-34 | **`SupportAgent` 未纳入 Agent OS 冻结清单**：架构 §6.1 明确把「客服 Agent」列为**禁止的员工角色式建模**，而代码里该类承担客服意图识别 + 自动回复（身份冲突） | **P2** | `backend/app/agents/support.py`、`backend/app/agents/contracts.py` | 已显式登记 `agent_contract = None`，`contract()` 会抛 `NotImplementedError`，契约测试反向断言其仍为 `None`。处置方向**需负责人裁决**：或按领域能力重建模（客服意图识别归入 Operation Optimization / Risk & Compliance），或保留并补架构例外说明。**不得**给它挂一个凑数的契约 |
| DEBT-35 | **兼容期 `legacy_context` 路径无法校验权限**：§10.2「必须检查 Permission」在 legacy 路径下不生效（Tool 层拿不到权限集合） | **P1** | `backend/app/tools/contract.py`、`backend/app/tools/base.py` | 过渡处置：放行但标记 `ToolResult.degraded=True`，审计行 `mode=tool` 记录缺口（§15.4 降级不得静默）。**关闭条件**：§18.3 第 5 步（Runtime 注入权威上下文）落地后，`legacy_context` 调用点清零。在此之前不得把 degraded 当已校验 |
| DEBT-36 | **§10.4 第一批 Tool 清单覆盖不了现有 Agent 的全部读取点**：`Conversation`、`Listing`（通用读取）、`AdCampaign`、`OpportunitySupplierMatch`、`SupplierCatalogProduct`、`ForecastSnapshot`、`ListingReviewDecision` 七类目标没有 Tool 归属 | **已关闭（D46）** | `backend/app/tools/registry.py`、`docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` §10.4 / §10.4.1 | 第二、三批清单累计补齐至 43 个方法。2026-09-30 D46：`discovery.py` 最后 15 处读取已迁到 Product / Market Tool，Agent 侧 9/9 文件读取迁移完成；`_ORM_CALL_BASELINE` 由起点 57 降至 **8**，剩余 8 处 `query/get` 均用于写路径，归 §18.3 第 3 步。决策记录见 D38 ~ D46。 |
| DEBT-37 | **主库 `ai_logs` 存量 2 行含买家消息原文**（脱敏修复前落库，来源 `support.auto_reply` 的 prompt） | **P2** | `backend/erp.db` 的 `ai_logs` id=944 / 946 | 代码侧已封堵（`backend/app/services/pii_redact.py`，2026-09-27，写入前脱敏 + 回归测试）。**存量处置待负责人确认**：保留 / 原地脱敏 / 删除；执行前必须冷备（`scripts/backup_restore_drill.py backup`）。未经确认不得改动主库数据 |

---

## 12. 提交前检查清单

新增或修改代码后，逐项确认：

- [ ] 无新增 `.db` / 日志 / 临时文件进入仓库
- [ ] 新增文件符合 §2 目录结构，未越层放置
- [ ] 依赖方向符合 §3（尤其 L-1 / L-2 / L-3）
- [ ] 文件与函数规模未超 §5 阈值
- [ ] 结构变更走 Alembic 迁移且 `downgrade()` 可用（§6）
- [ ] 新增能力带测试；权限改动已更新 `test_security.py`（§8）
- [ ] `ruff check` 全绿；`pytest -q` 与反序跑均 ≥ `docs/baseline.json` 的后端基线；`npm test` ≥ 其前端基线
- [ ] 测试可重复（同一库连跑两次全绿）且可并发（多进程各自独立库）
- [ ] 涉及结构变更时 `scripts/migration_preflight.py` 12 项全 PASS（P0 未清零不得执行）
- [ ] 涉及"可运行/可部署"的结论时，已真启动服务跑过 `scripts/live_acceptance.py` 且全 PASS（T-13）
- [ ] 改动构建链路（`Dockerfile` / 依赖文件 / `.gitattributes` / 入口脚本）后，已跑 `scripts/docker_feasibility.py` 且 12 项全 PASS（DP-1 / DP-2）
- [ ] 改动 TLS / 反向代理 / compose 端口映射后，已跑 `scripts/tls_feasibility.py` 且 8 项全 PASS（DP-7）
- [ ] 偏离规范的实现已在 `docs/DECISIONS.md` 记录
- [ ] 相关文档已同步（`CONTRACT.md` / Agent OS 架构 / 本文件）
- [ ] 文档一致性校验通过：`cd backend && python scripts/check_docs_consistency.py` 全 PASS（Doc-5/Doc-6）
- [ ] 用例数变化时已刷新事实源：`python scripts/refresh_test_baseline.py`（禁止手工改 `docs/baseline.json`）

---

## 附：本规范的维护

- 修改本文件须在 `docs/DECISIONS.md` 追加记录，并说明触发原因。
- 每次 Phase 收尾时复核 §11 台账，更新状态与新增债务。
- 本文件与 `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` 冲突时，Agent 层规则以后者为准。
