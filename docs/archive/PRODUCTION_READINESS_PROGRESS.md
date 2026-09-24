# Production Readiness

更新日期：2026-09-22

状态枚举：`TODO` / `IN_PROGRESS` / `BLOCKED` / `BLOCKED_EXTERNAL` / `DONE` / `VERIFIED`

## TASK 0 Production Gap Analysis

状态：`DONE`

- [x] 读取实际代码、配置、迁移、测试和核心文档。
- [x] 生成 `docs/production-gap-analysis.md`。
- [x] 标记文档漂移、潜在破坏性迁移和实施依赖。
- [x] 本阶段未修改业务代码、数据库或真实平台。

## M0 Platform Verification

状态：`TODO`

### DEV-001 Platform Capability Verification

状态：`TODO`

验收条件：

- 能力级状态模型、租户/市场/环境隔离和唯一约束。
- 脱敏证据引用、审计字段和受控状态晋级。
- API 与 `/platform-verification` 前端页面。
- REAL_STORE_VERIFIED 不可由单次 HTTP 200 自动产生。

## M1 Production Infrastructure

状态：`TODO`

### DEV-101 PostgreSQL Productionization

状态：`TODO`

- PostgreSQL 驱动、连接池、环境门禁、compose、healthcheck、volume。
- 受控 migration job 和 PG schema/migration 验证。
- A-H PostgreSQL concurrency integration tests。

### DEV-103 Independent Worker + Reliable Queue

状态：`TODO`

- 保留 Workflow 定义/Context/步骤。
- FastAPI 不再启动任务执行 daemon thread。
- 独立 Worker、持久队列、lease/heartbeat/retry/DLQ/cancel/priority/timeout/quota/recovery。
- Redis 只承担协调类职责，业务事实保留数据库。

## M2 Testing & Observability

状态：`TODO`

### DEV-201 Structured Logging & Observability

状态：`TODO`

- JSON 日志、上下文、脱敏。
- OpenTelemetry 基础链路。
- 业务 metrics、readiness/liveness 和生产告警基础。

### DEV-205 Playwright Golden Path

状态：`TODO`

- 隔离环境、角色 fixture、确定性 reset/seed。
- Playwright 登录、工厂 SKU、审批、发布任务和恢复黄金路径。
- CI 浏览器执行及 trace/screenshot/video artifact。

## M3 Shopee Production Verification

状态：`BLOCKED_EXTERNAL`

原因：真实/官方测试账号尚未完成验收准备。本轮不进入 Shopee 真实账号阶段。

本地前置缺口：完整分页、详情、attribute_list 发布、readback、shipment/refund/settlement 和证据持久化。

## M4 Data & Finance Trust

状态：`TODO`

- 真实店铺 Orders/Items/Fees/Refunds/Ads/Settlement/FX 数据尚未导入验收。
- Reconciliation 已有基础 API/UI，但归因类型和可信度仍需增强。

## M5 Forecast Certification

状态：`TODO`

- 已有时间切分基线、WAPE/Bias 和 Outcome。
- 缺少 `INSUFFICIENT_DATA/BASELINE_ONLY/VALIDATED/AUTOMATION_ELIGIBLE/SUSPENDED` 认证状态及真实数据正式认证。

## M6 Market Intelligence V2

状态：`BLOCKED`

原因：依赖 M1～M5 基本验收；根据本阶段纪律，不提前启动。

## 当前执行顺序

1. `DEV-001`
2. `DEV-101`
3. `DEV-103`
4. `DEV-201`
5. `DEV-205`
6. 完整测试与本文件复核
7. 停止，等待是否进入 Shopee 真实账号阶段的明确指令

## 当前外部阻塞

- Shopee SG 官方测试/真实店账号及必要权限。
- TikTok Development Shop（仅在 Shopee 条件不具备时考虑）。
- 真实历史订单、广告、费用、退款和结算数据。
