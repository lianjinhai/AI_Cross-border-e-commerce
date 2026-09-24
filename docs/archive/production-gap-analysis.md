# AI 跨境电商 ERP 生产化差距审计

版本：2026-09-22  
阶段：TASK 0 / 只读审计  
结论基准：实际代码优先于 README 和历史报告

## 1. 审计范围与方法

本次审计覆盖：

- 根目录、后端、前端、Docker、CI、Alembic、测试和文档。
- 44 个 SQLAlchemy 模型、147 个后端 OpenAPI 操作、全部 Adapter、Workflow、Scheduler、Agent、前端路由和 142 个前端 API 调用点。
- 长文档分段读取范围：README 1-181；当前能力报告 1-266；V8.0 需求 1-542；CONTRACT 1-213；项目功能地图标题、运行/边界部分及末尾 180 行；全量商用化方案 1-116；官方验收手册 1-70。

没有运行迁移、容器或会写业务库的验收脚本，没有访问真实平台账号。本文件是审计产物，不代表 DEV-001～DEV-205 已经实施。

最新已完成批次：本地闭环、发布/代发幂等、预测及机会归因、基础角色测试和前端拆包。  
当前批次：生产化 TASK 0。  
下一恢复点：DEV-001 Platform Capability Verification。

## 2. 当前目录结构

```text
AI-电商ERP/
├─ backend/
│  ├─ app/
│  │  ├─ agents/            # 业务 Agent
│  │  ├─ ai/                # LLM Router、轻量知识检索
│  │  ├─ routers/           # FastAPI API
│  │  ├─ services/          # 平台、财务、采集、调度服务
│  │  ├─ workflows/         # Workflow Engine
│  │  ├─ models.py          # 44 个 ORM 模型
│  │  ├─ db.py              # Engine、Session、SQLite 兼容补列
│  │  └─ main.py            # Web 入口及启动生命周期
│  ├─ migrations/versions/ # Alembic 01→06
│  ├─ scripts/             # 迁移、契约沙箱、验收和安全审计脚本
│  └─ tests/               # API、安全、Adapter、商业数据测试
├─ frontend/
│  ├─ src/views/           # 25 个 Vue 文件
│  ├─ src/router.js
│  ├─ src/permissions.js
│  └─ tests/permissions.test.js
├─ docs/
├─ .github/workflows/ci.yml
├─ Dockerfile
└─ docker-compose.yml
```

实际有 25 个 `.vue` 文件，但不是 25 个独立业务页面：路由动态导入 23 个组件，其中包括 Login/Layout，业务子路由为 21 个；`AiAssistant.vue` 是嵌入组件，`RunStatus.vue` 未注册路由。

## 3. 当前后端架构

- 模块化单体：FastAPI Router → Agent/Service → SQLAlchemy Session。
- 多租户和 RBAC 已存在，大多数业务查询显式过滤 `tenant_id`。
- 外部平台差异由 `services/platform_adapters.py` 内聚。
- 平台发布路由目前同步调用 Adapter，但先写 `PlatformPublishAttempt` 保存幂等键和检查点。
- 统一经营指标集中于 `commercial_analytics.py`。
- Workflow 模板、运行和步骤持久化在数据库；Agent 直接读写业务数据库。

适合当前本地演示和单实例运行，不适合直接水平扩容。

## 4. 当前前端架构

- Vue 3 + Vite + Vue Router + Element Plus + ECharts。
- 页面按路由懒加载；Element Plus 和 ECharts 已按需加载并拆包。
- Axios 统一注入认证，并处理 401。
- `permissions.js` 提供角色路由边界；路由可隔离 superadmin、supplier、compliance approver 和普通租户。
- 当前 142 个前端 API 方法/路径均能匹配后端 OpenAPI 操作。

差距：页面写按钮没有全部接入权限能力。Viewer 在 Products、Refunds、Ads、Pricing、Discovery 等页面仍能看到写按钮，最终依赖后端 403；这与“只读角色隐藏关键写操作”的产品描述不一致。

## 5. 当前数据库配置

- 默认数据库为 SQLite：`backend/app/config.py:9-13`。
- Engine 只有 `pool_pre_ping=True`：`backend/app/db.py:7-10`。
- 没有 PostgreSQL 驱动，不能仅设置 `ERP_DB_URL` 就认为 PostgreSQL 可运行。
- 没有 pool size、overflow、timeout、isolation、statement timeout 或 application name 配置。
- 生产环境校验没有禁止 SQLite。
- 应用启动会执行 `Base.metadata.create_all()`；SQLite 还会运行手写补列。

数据模型风险：

- 时间统一使用 naive `datetime.utcnow()`，未建立 timezone-aware 策略。
- Order、PurchaseOrder、Refund、Pricing 等仍有金额 Float；OrderLine、OrderFee、FX、平台结算才使用 Numeric。
- 多数 `tenant_id` 是索引而不是 Tenant 外键。
- `Setting` 使用全局字符串主键，没有 `tenant_id`，设置可能跨租户共享。
- 部分模型 ForeignKey 没有在后续 Alembic migration 中真正补到历史数据库。

## 6. 当前任务执行方式

当前没有统一 Durable Task Queue。

- Scheduler 随 FastAPI 启动，使用进程内 daemon thread。
- 到期任务再派生 daemon thread 执行。
- 进程内 Event/Lock 只能约束单进程，多实例不能防止重复调度。
- 异步模式下 `start_run()` 返回 queued，但 Scheduler 立即用是否 success 判断结果，会把正常入队任务记录为 failed。

## 7. 当前 Workflow 执行方式

已经实现：

- WorkflowRun、WorkflowStep、context、checkpoint/output。
- 条件 UPDATE 抢占、worker_id、lease、heartbeat。
- attempts/max_attempts、断点恢复、成功步骤跳过。
- blocked/partial/failed 等业务语义。

仍然缺失：

- 独立 Worker 和持久队列。
- RETRY_WAIT、DEAD_LETTER、CANCEL_REQUESTED、CANCELLED、UNCERTAIN 的统一任务语义。
- 持久化 next_retry_at、优先级、超时、并发配额、取消检查和死信处理。
- 当前退避是工作线程中最多 1 秒的 sleep + 递归调用，不是生产级持久重试。
- FastAPI 重启会直接终止 daemon thread，依赖下次启动恢复数据库 run。

结论：现有 Workflow 定义、Context 和业务步骤应保留；DEV-103 只替换执行和协调层。

## 8. 当前 Redis 使用情况

Redis 完全未接入：

- requirements 无 redis 客户端。
- config 无 Redis URL。
- compose 无 Redis 服务。
- rate limit、distributed lock、token cache、task coordination 均未使用 Redis。

核心业务事实目前在数据库，符合后续原则，不需要迁入 Redis。

## 9. 当前平台 Adapter 结构

`BaseAdapter` 定义 OAuth、Token、订单、发布、readiness 和能力元数据；具体平台继承实现。统一 `platform_environment/platform_base_url` 已用于部分平台，安全方法重试与限流存在基础实现。

当前状态：

| 平台 | 代码状态 | 审计结论 |
|---|---|---|
| 1688 | partial | 采集、订单、代发幂等存在；超时后的官方查单恢复缺失 |
| Shopee SG | partial | OAuth、刷新、readiness、图片、add_item、订单首屏存在；完整分页、属性提交、readback、shipment/refund/settlement 缺失 |
| TikTok US | protocol_ready_unverified | Global Product 与分页链路存在，需官方环境验证 |
| eBay US | protocol_ready_unverified | Inventory Item/Offer/Publish 存在，需官方环境验证 |
| Walmart | protocol_ready_unverified | OAuth、订单、Feed 和状态查询存在，需动态 Sandbox 验证 |
| Lazada | protocol_ready_unverified | 授权、分页订单和商品接口存在，需确定站点验证 |
| Amazon | planned/disabled | 没有实现，本阶段不开发 |

现有状态是平台级静态字段，不能表达租户、市场、能力、环境、证据和验收人，因此 DEV-001 确有必要。

## 10. 当前测试结构

- 后端：pytest，覆盖 API 主流程、安全、Adapter 协议、分页/超时/Token/部分成功、商业数据与归因；当前基线 51 项。
- 前端：Vitest/jsdom，仅有权限策略测试文件，展开为 14 项逻辑测试。
- CI：后端 SQLite pytest；前端 npm test + build。

不存在：

- PostgreSQL integration test。
- A-H 并发场景测试。
- Webhook 重复/乱序测试；实际上 Webhook 业务入口也不存在。
- Playwright 浏览器 E2E。
- Lint、migration validation、Docker build、依赖/密钥扫描和 E2E artifact。

## 11. 当前日志体系

- Uvicorn 默认访问日志。
- Scheduler 使用 `print` 和 `traceback.print_exc()`。
- AiLog 保存 Agent/LLM 调用、prompt、response、latency 和结果。

不存在统一 JSON logging、上下文绑定、脱敏过滤和 trace correlation。AiLog 会保存 prompt/response，存在客户 PII、商业数据和秘密信息进入审计日志的风险；DEV-201 必须设计字段白名单/脱敏及保留周期。

## 12. 当前监控体系

- `/api/health` 只静态返回 `ok`。
- 没有 readiness/liveness 区分。
- 没有 DB/Redis/Worker 检查。
- 没有 OpenTelemetry、Prometheus 指标或告警事实表。
- 没有业务 metrics 和 P0 告警规则。

## 13. 当前 Docker 部署结构

- Dockerfile 多阶段构建前端，最终单容器运行 Uvicorn 并托管前端。
- 默认 SQLite volume。
- compose 只有 `erp` 与可选 MySQL，不包含 frontend/postgres/redis/worker。
- MySQL profile 没有把 ERP_DB_URL 改为 MySQL，后端依赖也没有数据库驱动，因此不能视为可用生产方案。
- 没有 healthcheck、depends_on、迁移 job、非 root 用户或生产启动门禁。
- Web 容器启动时会建表、seed、启动 scheduler 并恢复任务；多实例会产生争抢和重复执行风险。

## 14. 当前 PostgreSQL 兼容情况

结论：方言表面可配置，但 PostgreSQL Integration 尚未 Ready。

需要专项解决：

- 增加 psycopg 驱动与连接池策略。
- staging/production 禁止 SQLite。
- 建立 PostgreSQL compose、healthcheck、volume 和单实例 migration job。
- 验证 JSON、Boolean、Numeric、timezone、sequence、FK、NULL unique、transaction、isolation、row lock、upsert、deadlock。
- 订单唯一键包含 nullable shop_id；NULL 会允许重复，需要明确部分索引或标准化键。
- 订单同步、发布 attempt、采购、审批和退款存在“先查再写”，并发时仅靠部分唯一索引且未统一捕获冲突。

## 15. 当前 Shopee 实现情况

已实现：

- Shopee v2 签名。
- OAuth 授权码换 Token、刷新 Token。
- SG 站点 readiness：真实店铺信息、物流渠道、类目映射、必填属性查询、图片、价格、库存和重量检查。
- 图片上传和 `product/add_item`。
- 订单列表调用和基础归一化。

未完成/待验证：

- `_HOST` 固定生产域名，没有统一 sandbox/production 开关。
- 订单只取一次 `page_size=20`，未完整遍历游标，也未补拉订单详情。
- readiness 查询了类目必填属性，但 add_item body 没有提交 `attribute_list`。
- 发布后没有平台 readback 和能力验收证据。
- Shipment Update、Refund、Settlement Adapter 能力不存在。
- `can_publish=True` 只能表示代码路径存在，不能表示 PROTOCOL_VERIFIED 或 REAL_STORE_VERIFIED。

## 16. 已存在但文档遗漏的功能

- 前端 CI 已运行 `npm test`，README 的 CI 描述仍只写测试/构建的旧口径。
- Workflow 已有 worker_id、lease、heartbeat、尝试次数和过期恢复，比旧 CONTRACT 描述更完整。
- 发布任务已持久保存 requested_by、request_payload、started/finished、checkpoint 和 uncertain 状态。
- 预测 outcome 与工厂机会营收归因已经存在，旧项目功能地图未更新。
- TikTok、eBay、Walmart、Lazada 的 Adapter 已超出旧功能地图的描述。

## 17. 文档声称存在但代码不存在或不完整的功能

| 文档声称 | 实际代码 |
|---|---|
| “按真实店铺分页拉单” | TikTok/eBay/Walmart/Lazada 有分页基础；Shopee 仅首 20 条 |
| “数据库可平滑切 MySQL/PG” | 缺数据库驱动、PG compose、PG CI 和并发验证 |
| Docker MySQL profile 可用 | ERP 仍固定 SQLite，且无 MySQL driver |
| 25 个前端业务页面 | 25 个 Vue 文件；实际 21 个业务子路由 |
| Viewer 隐藏关键写操作 | 多个页面仍展示写按钮，最终依赖后端 403 |
| URL 采集含 Playwright | Playwright 是可选导入，不在 requirements/Docker 标准安装中 |
| Playwright“过反爬” | 存在隐藏自动化特征代码；与当前禁止绕过平台安全措施的纪律冲突，必须改为失败关闭 |
| 项目功能地图 29 测试/18 页面/9 Agent | 已明显陈旧；当前分别为 51 后端测试、21 业务子路由、扩展 Agent 集合 |
| TikTok 上架未接 | 旧功能地图陈旧；Global Product 代码现已存在 |

## 18. 五类清单

### Already Implemented

- 多租户、RBAC、OAuth state、凭证加密和生产密钥基础门禁。
- 商品、私域工厂、机会、定价、合规、Listing 审批、订单、采购、退款、结算、统一财务和预测归因。
- Adapter 抽象及 TikTok/eBay/Walmart/Lazada 协议代码。
- 发布 attempt 的幂等键、checkpoint 和 uncertain 状态。
- Workflow 的 DB run/step/context、租约、心跳、尝试和恢复。
- Alembic 单线 revision 01→06。
- 基础 CI、51 项后端测试、14 项前端权限逻辑测试。
- 前端路由权限基础和按需分包。

### Partially Implemented

- PostgreSQL：只有 SQLAlchemy URL 抽象，没有驱动、环境和测试。
- Reliable Task：Workflow 有持久状态，但执行仍是线程。
- 任务重试：只有 Workflow step，且不是持久 backoff/DLQ。
- Platform Verification：只有静态粗粒度状态与运行手册，没有数据模型/API/UI。
- Observability：只有 Uvicorn、print 和 AiLog。
- Shopee：OAuth、发布基础和首屏订单存在，完整闭环不足。
- 前端 RBAC：路由完整，页面动作能力控制不完整。
- 财务 reconciliation：已有 API/财务页基础，但未按归因类型区分 DIRECT/ALLOCATED/ESTIMATED/UNATTRIBUTED。

### Missing

- `platform_capability_verification`、能力级状态机、证据摘要/API/UI。
- PostgreSQL/Redis/Worker compose 和相应驱动。
- 独立 durable queue、DLQ、cancel、priority、timeout、quota。
- Webhook 事实表、签名、去重和乱序处理。
- PostgreSQL integration 与 A-H 并发测试。
- 结构化脱敏日志、OpenTelemetry、业务 metrics 和告警。
- Playwright E2E、隔离测试租户/数据库、trace artifact。
- Shopee 完整分页、详情、readback、shipment/refund/settlement。

### Needs Refactor

- 增量拆除应用 lifespan 中的 create_all/seed/scheduler/recovery 生产副作用；保留本地 demo 路径。
- 将 thread dispatch 替换为 enqueue，保留 Workflow 定义、Context 和步骤。
- Scheduler 改为 DB/Redis 协调的单 leader/租约调度。
- 并发“先查再写”改为数据库约束 + upsert/row lock + 冲突恢复。
- 统一 Task 状态并提供旧状态兼容映射。
- Engine 按环境配置连接池和隔离。
- 全量页面写按钮接入统一 capability 权限。
- 采集器移除隐藏自动化特征/绕过挑战行为；验证码、登录墙立即失败关闭。
- 日志统一上下文和脱敏；AiLog 避免保存完整敏感 prompt/response。

### Needs Verification

- 全部 migration 在 PostgreSQL 的 upgrade/downgrade 和 schema diff。
- 现有 SQLite 数据迁移到 PG 的重复、孤儿、金额和时区问题。
- NULL unique、JSON、Boolean、Numeric、FK、sequence 和索引行为。
- 两 Worker 抢占、并发审批、并发采购、重复发布、退款/订单并发。
- Adapter 官方字段版本、签名、分页、Token、限流和 readback。
- Shopee Sandbox/实店与其他平台官方环境。
- Worker crash、Redis outage、连接池耗尽、deadlock 和 stale recovery。

## 19. 潜在破坏性 Migration 风险

编码前必须解决或预检：

1. `20260922_01` 在 migration 内调用当前 `Base.metadata.create_all()`；未来模型变化会改变历史 revision 在新库生成的结构。不能直接修改已部署 revision，需要制定显式基线/PG bootstrap 兼容策略。
2. 应用启动 `create_all` 可能先于 Alembic 建最新表；多实例还会并发 DDL。
3. 02/04/05/06 多处 upgrade 条件创建、downgrade 无条件删除，回滚可能删除原本已经存在的列/表或失败。
4. 新增 unique 前必须扫描历史重复；尤其订单 nullable shop_id、采购幂等、审批、退款。
5. `Setting` 增 tenant_id 会改变全局设置语义，需要 expand/backfill/switch/contract。
6. Float→Numeric 和 naive datetime→timestamptz 需要分阶段转换、对账和时区解释，不能夹带在基础设施迁移。
7. 为历史字段增加非空/FK 前必须检查孤儿行和无 tenant 数据。

本轮不修改任何 migration。

## 20. 实际执行顺序

### Step 1：DEV-001 Platform Capability Verification

依赖最少，先建立事实层：

1. 在现有 Adapter meta 上增量扩展能力枚举和 adapter/api version。
2. 新增 append-only verification model/migration，租户、市场、能力、环境唯一。
3. 证据只保存脱敏摘要和引用，不保存 Token/完整正文。
4. 状态晋级由明确规则控制；200 响应不能自动晋级真实店铺状态。
5. 增加 API、审计和 `/platform-verification` 页面。

### Step 2：DEV-101 PostgreSQL Production Foundation

拆成可验收小步：

1. 驱动、环境门禁、连接池配置。
2. Postgres + Redis compose、volume、healthcheck。
3. 独立且加锁的 migration job；Web 进程不自动迁移/建表。
4. 显式基线策略、全新 PG migration 和旧 SQLite 数据预检。
5. 先建立 A-H 并发失败测试，再补约束、upsert、row lock 和冲突恢复。
6. 暂不同时改全量金额类型和 Setting 主键；另走 expand-contract。

### Step 3：DEV-103 Independent Worker + Reliable Queue

依赖 DEV-101：

1. 复用 WorkflowRun/Step，增加兼容 task envelope；不重写工作流定义。
2. API 只 enqueue，Worker 使用 PG `FOR UPDATE SKIP LOCKED` 抢占。
3. Redis 只做短锁、限流、协调和缓存；DB 保存任务事实。
4. 补 retry_wait、next_run_at、dead_letter、cancel、priority、timeout、quota、worker heartbeat。
5. 迁移 Scheduler 到单 leader/租约执行。

最小可靠方案优先采用 PostgreSQL 事实队列 + 独立 Python Worker；先不引入 Celery 的复杂拓扑。若实现阶段证明需求超出 DB queue，再重新评估。

### Step 4：DEV-201 Structured Logging & Observability

依赖 Worker/task 上下文稳定：

1. request/trace/tenant/user/store/workflow/task/platform 上下文。
2. JSON logging 和统一敏感字段脱敏。
3. OTel 覆盖 HTTP、SQL、Workflow、Worker、Adapter、外部 API 和 AI 调用。
4. Prometheus 业务指标。
5. 数据库事实告警及 DB/Redis/Worker readiness。

### Step 5：DEV-205 Playwright Golden Path

依赖稳定的 PG、Worker 和 trace：

1. E2E 隔离配置、测试租户和六类角色 fixture。
2. 本地契约沙箱，禁止连接真实店铺。
3. 幂等 reset/seed 和稳定可访问名称/test id。
4. 首批覆盖登录、建运营账号、工厂 SKU、Listing 审批、发布任务和失败恢复。
5. 再扩展订单、代发、发货、退款、结算、BI 和 Workflow 恢复。
6. CI 保存 screenshot/video/trace；Mock 结果只能标协议/本地验收。

## 21. 为什么暂不修改现有稳定实现

- 不重写 Workflow Engine：现有定义、Context、步骤、业务状态、lease 和 checkpoint 可直接复用，问题集中在执行层。
- 不重写 Adapter：问题是能力证据、官方验收和局部缺口，不是抽象整体失效。
- 不重写财务指标：统一服务已存在；下一阶段补归因等级和可信度即可。
- 不立即改全量 Float/时区：这是高风险数据迁移，应在 PostgreSQL 基础与对账工具建立后分阶段执行。
- 不立即做 Shopee 真实验收：用户明确要求本轮结束后停止，且外部账号条件尚未确认。

## 22. TASK 0 验收结论

| 验收项 | 结果 |
|---|---|
| 全项目实际代码审计 | DONE |
| 文档/代码差异标记 | DONE |
| 五类清单 | DONE |
| Migration 风险识别 | DONE |
| 五个 DEV 任务真实依赖排序 | DONE |
| 业务代码修改 | 未执行，符合指令 |
| 数据库迁移 | 未执行，符合指令 |
| 外部账号访问 | 未执行，符合指令 |

下一任务：DEV-001。开始前应先确认审计结论；本轮不自动进入实现。
