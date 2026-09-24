# Workspace Migration Progress

> 更新日期：2026-09-24（Phase 1 收尾 + 外键强制整改 + 测试可重复性加固）
> 冻结依据：`docs/archive/final_architecture_assessment.md`（已归档）
> 规范依据：`docs/CODE_AND_DIRECTORY_STANDARD.md`
> 状态：TODO / IN_PROGRESS / BLOCKED / DONE / VERIFIED

## Phase 1 总体状态

| 工作包 | 状态 | 当前结果 |
|---|---|---|
| Phase 1.0 Migration Safety Analysis | **VERIFIED** | 只读审计完成，报告落盘 |
| P1-01 可重复 Migration Preflight | **VERIFIED** | 12 项检查全部 PASS，`exit_code=0` |
| P1-02 Identity Compatibility Layer | **VERIFIED** | `workspace_context.py` + 14 项测试通过 |
| P1-03 Alembic Ledger Reconcile | **VERIFIED** | 根因（suppliers 重复键 + 漏建唯一索引）已修复，账本对齐 |
| P1-04 Backup & Restore Drill | **VERIFIED** | 工具 + 运维手册 + 16 项测试；已实际生成 2 次冷备 |
| P1-05 Expand Migration A | **VERIFIED** | `20260923_07` 已在主库执行 |
| P1-06 Role Seed & Membership Backfill B | **VERIFIED** | `20260923_08` 幂等回填：7 profiles / 10 memberships / 24 permissions / 4 roles / 59 role_permissions |
| P1-07 Users Nullable/Soft-delete Migration C | **VERIFIED** | `20260923_09` 已在主库执行，FK 违规归零 |
| P1-08 Authentication Dual Read | **VERIFIED** | Membership 优先 + legacy fallback，10 项双读测试通过 |
| P1-09 Workspace Context API | **VERIFIED** | `/api/me/*` 三端点 + 10 项测试通过 |
| P1-10 Setting Scope Fix | **VERIFIED** | `20260923_10` 已在主库执行；`tenant_settings` 三级回退 + 写入按 key 分流（租户 admin 写平台级 key → 403）；5 项测试通过；端到端实证租户间不再串扰 |
| P1-11 Supply/Sales Guard | **VERIFIED** | 守门实现 + 9 项测试；13 个 1688 店铺 role 已修正为 `source` |
| P1-12 superadmin 越权写入修复 | **VERIFIED** | 平台身份禁止直连租户业务 API，必须经代客进入（含审计） |

**Phase 1 主库迁移：已执行完成（含 Revision D/E）。**

### 部署层（Phase 1 之外的 P0 债务，2026-09-24 收口）

| 债务 | 状态 | 结果 |
|---|---|---|
| DEBT-23 无 HTTPS / 反向代理 | ✅ **已完成** | Caddy 自动 ACME + TLS 覆盖层；应用侧两道闸（`ERP_TRUST_PROXY_HEADERS` + `ERP_TRUSTED_PROXY_HOSTS`）；新增 `scripts/tls_feasibility.py`（真 HTTPS 端到端 8 项全 PASS）。**上一版改动藏的 3 个真实缺陷已修**，详见 `docs/DECISIONS.md` D22 |

> **验证方式**：`cd backend && python scripts/tls_feasibility.py`（真 Caddy +
> 真应用容器，离线可用自签证书）。8 项含「应用真的采信转发头」——
> 只验「HTTPS 能通」会漏掉该缺陷。

## 主库实际状态（2026-09-24 11:40 实测）

| 指标 | 值 |
|---|---:|
| Alembic current / head | `20260924_15` / `20260924_15`（一致；`13→14→15` 已按 runbook 执行） |
| 表数量 | 57（Phase 1 后 52 + AI 原生能力 5） |
| 总行数 | 3,169（**2026-09-24 12:50 复测**；其中 16 行为 02:39 前遗留的测试命名数据，详见 `DECISIONS.md` D16 §8.5） |
| `integrity_check` | ok |
| `foreign_key_check` 违规 | **0**（迁移前 1） |
| tenants | 2（演示租户 + 平台；5 个 probe 残留租户已于 2026-09-24 清理） |
| users | 7（`tenant_id IS NULL` = 1，即 superadmin；`tenant_id = 0` = **0**） |
| workspace_profiles | 2 |
| workspace_memberships | 5 |
| workspace_roles | 4 |
| permissions | 25（新增 `compliance:check`，Revision 15） |
| role_permissions | 62（OWNER/OPERATOR/COMPLIANCE × `compliance:check`） |
| orders | 521 |
| products | 49 |
| shops | 11（全部 `1688` + `role=source`，与平台默认一致） |
| shops 归档行 | 0（Revision E 新增 `archived_at` 列，历史数据未被改动） |
| tenant_settings | 6（2 租户 × 3 key） |
| suppliers | 10 |
| listings | 26 |
| purchase_orders | 16 |
| settlements | 3 |
| product_performances | 1（M1 飞轮缓存，`20260924_12` 新建） |
| ai_decisions | 2（M6 决策依据链，只增不删） |
| alert_rules / alert_events | 9 / 2（M3 主动巡检） |
| **tenant_id = 0 孤儿业务数据** | **0 行（已清零，原 37 行）** |
| WAL 检查点 | 已执行 `wal_checkpoint(TRUNCATE)`，`-wal` 归零 |

> **2026-09-24 11:40 复验**：Revision 14（`knowledge_candidates`）与 Revision 15（`compliance:check`
> 权限）均按 runbook 执行（冷备 `_erp_backups/erp-20260924-103216.db` → 副本演练 → 主库 upgrade）。
> 预检 **12 项全 PASS（`P0_fail=0`）**；数据零损失（除权限表按设计 +1/+3 行，其余 55 张表行数不变）；
> `integrity_check=ok`、`foreign_key_check` 违规 0。

## Revision D / E（2026-09-23 追加）

| Revision | 内容 | 主库状态 |
|---|---|---|
| `20260923_10` | `tenant_settings`（租户级配置隔离）+ 回填 7 租户 × 3 key = 21 行 | 已执行 |
| `20260923_11` | `shops.archived_at`（店铺归档式软删除，可空，0 行被改动） | 已执行 |
| `20260924_12` | AI 原生能力 4 表：`product_performances` / `ai_decisions` / `alert_rules` / `alert_events`（幂等建表 + 索引） | 已执行 |
| `20260924_13` | `market_trends` 增加 `source` / `updated_at` + `ix_market_trends_source`（M5 真实趋势接入） | 已执行（2026-09-24） |

**外键强制整改**：开启 `PRAGMA foreign_keys=ON` 后暴露并修复 2 个 P0 缺陷——
① 删店铺物理删除撞 5 张表外键（改为归档，见 `DECISIONS.md` D7）；
② `purge_demo_data` 未按外键拓扑序删除（抽出 `services/tenant_data_purge.py`）。
新增回归测试 `tests/test_shop_archive_and_purge.py`（3 项）。
**当前测试基线以 `docs/baseline.json` 为单一事实源**（由 `backend/scripts/refresh_test_baseline.py`
采集，禁止手工编辑）；另有 `ruff` 全绿 / 预检器 12 项全 PASS。

## 本轮新增交付物

| 文件 | 内容 |
|---|---|
| `docs/phase1_interfaces.md` | FROZEN 接口契约（Context 字段、角色、权限、读取顺序、API） |
| `docs/archive/phase1_ledger_reconcile_report.md` | P1-03 账本对齐报告（根因与实测证据，已归档） |
| `docs/archive/phase1_migration_abc_design.md` | Revision A/B/C 精确设计（期望数量与断言，已归档） |
| `docs/phase1_setting_scope_design.md` | P1-10 配置隔离设计（跨租户漏洞证据） |
| `docs/CODE_AND_DIRECTORY_STANDARD.md` | **代码与目录规范 V1.0**（含存量债务台账） |
| `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` | **Agent OS 架构冻结 V1.0**（24 章） |
| `AGENTS.md` | 项目协作规范入口 |
| `backend/app/services/workspace_context.py` | P1-02 身份兼容层 + P1-08 双读 |
| `backend/app/routers/me.py` | P1-09 Context API |
| `backend/migrations/versions/20260923_07/08/09` | Revision A/B/C |
| `backend/scripts/migration_preflight.py` | P1-01 只读预检器（12 项） |
| `backend/scripts/backup_restore_drill.py` | P1-04 备份/校验/恢复演练 |
| `backend/scripts/audit_shop_roles.py` | 店铺 role 只读盘点 |
| `backend/pyproject.toml` | ruff 规则集（代码规范门禁） |
| `backend/requirements-dev.txt` | 开发依赖 |
| `backend/tests/test_workspace_context.py` | 14 项 Context 测试 |
| `backend/tests/test_workspace_context_api.py` | 10 项 API 测试 |
| `backend/tests/test_workspace_identity_migration.py` | 9 项迁移结构测试 |
| `backend/tests/test_workspace_dual_read.py` | 10 项双读测试 |
| `backend/tests/test_migration_preflight.py` | 12 项预检器测试 |
| `backend/tests/test_backup_restore_drill.py` | 16 项备份工具测试 |
| `backend/tests/test_supply_sales_guard.py` | 9 项 Supply/Sales 守门测试 |

## 本轮验证证据（2026-09-23 实测）

| 验证项 | 结果 |
|---|---|
| 后端全量回归 | **131 passed** <!-- docs-ok: 2026-09-23 当次实测史实 --> |
| 前端测试 | **32 passed** <!-- docs-ok: 2026-09-23 当次实测史实 --> |
| 代码检查 | `ruff check` → **All checks passed** |
| 预检器 | 12 项全 PASS，`exit_code=0` |
| 主库迁移执行 | `20260922_01` → `20260923_09`，退出码 0 |
| 回填数量 | 7 profiles / 10 memberships / 24 permissions / 4 roles / 59 role_permissions（与设计一致） |
| 主库 FK 违规 | 0（迁移前 1） |
| 主库 integrity_check | ok |
| tenant 0 孤儿数据 | 37 行 → **0 行** |
| 1688 店铺 role | 13 行 `sales` → 11 行 `source`（与平台默认一致） |
| 服务启动冒烟 | `/api/health` ok；admin 可登录并读业务数据；superadmin 被限制在平台作用域 |
| 冷备 | 2 份（`erp-20260923-194756.db`、`erp-20260923-202524.db`），均 `changed_during_backup=false`、verify PASS |
| 源码冷备 | `_erp_backups\src-20260923-before-ruff\`（186 文件 / 2.53 MB） |

## 已修复的真实缺陷

| 缺陷 | 影响 | 修复 |
|---|---|---|
| superadmin 可直连租户业务 API | 以空 tenant 写入，产生孤儿数据（历史 37 行） | 平台身份限制在平台作用域，必须经代客进入（带审计） |
| `test_security.py` 固化越权行为 | 测试在保护错误行为 | 权限矩阵更正为「superadmin 租户业务接口一律 403」 |
| `test_api.py` 断言语义错位 | 把「租户停用」误断言为「租户到期」 | 断言改为匹配实际分支 |
| `routers/purchases.py` `DropshipIn` 重复定义 | 第二个定义静默覆盖第一个 | 删除重复定义 |
| `platform_adapters.py` 发布前校验未按声明字段校验 | `price/stock/images` 缺失时不被拦截（削弱防封店门禁） | 按 `publish_required_system_fields` 逐项校验 |
| `security_data_audit.py` 无护栏 | 对主库运行会持续写入探测数据 | 增加端口护栏，默认拒绝对 8000（主库）运行 |

## Go / No-Go

**当前：GO（Phase 1 已完成，可进入 Phase 2 规划）。**

Phase 1 解除条件核对：

- [x] Alembic schema fingerprint 对齐
- [x] 停写维护窗口和备份路径确认
- [x] 备份恢复演练通过
- [x] tenant 0 数据处理完成（37 行 → 0 行）
- [x] 预检器所有 P0 检查通过（12/12）
- [x] Membership 回填期望数量确认

## 遗留项（移交 Phase 2）

> 状态核实日期：**2026-09-24**（逐项对主库/代码实测，非沿用历史结论）

| 编号 | 事项 | 严重度 | 状态 | 说明 |
|---|---|---|---|---|
| R-01 | ~~仓库未纳入 Git~~ | ~~**P0**~~ | ✅ **已完成（2026-09-24）** | 已 `git init -b main` + 首次提交 `6215d49`（208 文件 / 0.87 MB / `fsck` 干净）；提交前补齐 `.gitignore` 冷备目录与临时脚本缺口，新增 `.gitattributes` 锁定 LF 行尾（防 `docker-entrypoint.sh` 变 CRLF 导致容器 `bad interpreter`） |
| R-02 | ~~P1-10 Setting 隔离未实施~~ | ~~P1~~ | ✅ **已完成** | 迁移 `20260923_10_setting_scope.py` 已执行；`services/settings_service.py` 三级回退 + 写入按 key 分流；5 项测试通过 |
| R-03 | ~~40 张含 `tenant_id` 的表缺外键~~ | ~~P1~~ | ✅ **已完成（2026-09-24）** | 迁移 `20260924_16` 补齐；**2026-09-24 复测：48 张含 `tenant_id` 的表，48 张全部声明 `FK → tenants`，缺口 0**（原写「43 张 / 缺 40 张」是迁移前快照）。对应 DEBT-03 已关闭 |
| R-04 | `workspace_profiles.owner_user_id` 全为 NULL | P2 | **未完成** | 实测：2 行，`owner_user_id` **均为 NULL**（未回填）。Workspace 所有者字段在 Phase 1 未被写入，Phase 2 引入 Workspace 管理界面时补齐 |
| R-05 | `membership_data_scopes` 0 行 | P2 | **未完成** | 实测 0 行。Guardrail 第二道闸（数据范围）暂无数据支撑，Phase 2 落地时填充 |
| R-06 | ~~tenants 中 5 个 `probe tenant` 测试残留（id 2,3,4,5,7）~~ | ~~P2~~ | ✅ **已完成（2026-09-24）** | 实测仅剩 2 个租户（id 1 演示商家、id 6 隔离测试租户）；5 个 probe tenant 及其 25 行关联数据已清理（清理前冷备 `_erp_backups/erp-20260924-010314-pre-probe-cleanup.db`）。**残余**：`users` 2 / `products` 13 / `schedules` 11 行仍是 probe 命名，见下方「主库残余测试数据」 |
| R-07 | ~~前端 `routeRedirect` 基于 legacy `erp_user.role`~~ | ~~P2~~ | ✅ **已完成（2026-09-24）** | 路由分流与菜单权限已切 Context 优先：① `permissions.js` 新增 `resolveIdentity()`，**Context 无条件优先**，legacy 仅兜底（`routeRedirect`/`defaultLanding`/`/login` 分支全部走它）；② 守卫同时传 `user`（兜底）与 `context`（权威）；③ `Layout.vue` 菜单判断改 `roleKey()`；④ `Users.vue` 改用 `contextUserId()`；⑤ `PlatformAdmin.vue` 改 `roleKey()==='PLATFORM_ADMIN'` 且代客不再伪造 legacy 角色。**legacy 保留为兜底**（工厂账号 `/api/me/*` 403 属既有契约 G-3，见 `permissions.js` 文件头），删除入口待工厂 Context 通道落地 |
| R-08 | ~~`backend/` 根目录 3 个 `.db`（其中 2 个无引用）~~ | ~~P2~~ | ✅ **已完成** | 实测仅剩 `erp.db`；测试库已改 PID 隔离并自动清理 |
| R-09 | ~~`docs/` 活文档与一次性报告混放~~ | ~~P2~~ | ✅ **已完成** | 11 篇活文档 / 14 篇已归档（`docs/archive/`）；活跃文档失效引用已归零 |

**剩余 2 项**：R-04 / R-05（均为 P2，Phase 2 处理）。
**R-01 已于 2026-09-24 完成**（仓库纳入 Git，唯一 P0 债务清零）。
**R-07 已于 2026-09-24 完成**（Phase 1.8 前端 Context 接入收口）。

### Phase 1.8 完成度（2026-09-24）

| 子项 | 状态 | 说明 |
|---|---|---|
| 前端路由分流切 Context | ✅ 完成 | `resolveIdentity()` Context 无条件优先；守卫同时传 `user` + `context` |
| 菜单与权限判断切 Context | ✅ 完成 | `Layout.vue` 全部走 `roleKey()`/`canAdmin()`；`ROLE_LABELS` 覆盖新枚举 |
| 页面身份来源收口 | ✅ 完成 | `Users.vue`→`contextUserId()`；`PlatformAdmin.vue`→`roleKey()`；代客不再伪造角色 |
| 代客会话一致性 | ✅ 完成 | 进入/退出/401 三条路径统一清 Context + 代客标记；`me.py` 三端点透传 `is_impersonating` |
| 工厂账号 Context 通道（G-3） | ✅ **已完成（2026-09-24）** | `/api/me/workspaces` 与 `/api/me/workspace-context` 已对工厂账号放行（**只读**，`/switch` 仍拒——工厂无可切换项）。真启动服务端到端实测通过：工厂真登录后取到 `source=FACTORY` 的 Context。**顺带修掉一个 fail-open 缺陷**（`build_factory_context` 未校验绑定 `status`，见 `docs/DECISIONS.md` D23） |
| 删除 legacy 入口 | ✅ **已完成（2026-09-24，D24）** | 采纳「写权限 fail-closed + 路由兜底保留」：canWrite/canAdmin/canApprove/can 在 Context 不可用时**一律 false**，LEGACY_CAPABILITIES 兜底表**整体删除**；
oleKey/
outeRedirect/defaultLanding 的 legacy 兜底保留（否则 Context 故障时平台/工厂账号会被弹到无权页面，且改跳登录页会引入重定向环）。**残留**：伪造 rp_user.role 仍能影响路由与菜单（UI 层，非数据越权，后端已实测兜住） |

> **legacy 依赖点已收敛到 3 处**（`permissions.js` 文件头声明的 `currentUser()`/`role()`/
> `LEGACY_ROLE_MAP`），其余代码禁止再读 `localStorage.erp_user.role`。
> 新增回归测试锁死守卫传参契约（`permissions.test.js` 的 `Phase 1.8 guard argument contract`）。

> **R-06 已处置（2026-09-24）**：5 个 `probe tenant`（id 2,3,4,5,7）及其 25 行关联数据
> （5 users / 5 workspace_profiles / 15 tenant_settings / 5 workspace_memberships）已清理，
> 清理前冷备 `_erp_backups/erp-20260924-010314-pre-probe-cleanup.db`
> （sha256 `4121CCAE...7B1F94`）。清理后 `integrity ok` / FK 违规 0 / 预检 12 项全 PASS。
> **教训**：测试若跑在业务库上会留下永久污染；现已强制测试库隔离（`test_erp_<pid>.db`），
> 新增测试**禁止**连接 `backend/erp.db`。

### 主库残余测试数据（2026-09-24 15:04 处置）

**新发现的真问题**：11 个测试残留的计划任务（10 个 `probe` + 1 个 `验收-趋势扫描`）
**处于 `enabled=1` 状态、每小时真实执行**，已累计 50 次以上。
这不是静态脏数据，而是**正在持续运行的后台任务**——每次启动服务都会触发。

| 项 | 处置前 | 处置后 |
|---|---:|---:|
| `schedules` 中 `enabled=1` | **12** | **1**（仅合法的「每日市场趋势扫描」） |
| 主库总行数 | 3,169 | 3,169（**未删任何行**） |
| `integrity_check` | ok | ok |
| `foreign_key_check` 违规 | 0 | 0 |
| 预检 | 12 项全 PASS | 12 项全 PASS |
| `e2e_feasibility` | 7 步全 PASS | 7 步全 PASS |

**处置方式**：仅 `UPDATE schedules SET enabled = 0`（**可逆、不删行**），
处置前冷备 `backend/backups/erp-20260924-150445.db`。
行保留的原因：`run_count` / `last_run_at` 是排查线索，删掉会丢失取证信息。

**仍存在的静态残余**（未处置，属"脏演示数据"）：

| 表 | 数量 | 内容 |
|---|---:|---|
| `users` | 2 | `probe-user-tmp`、`probe_x`（另有 `compliance_test`、`factory_portal_test` 属功能验证账号） |
| `products` | 13 | 10 条 `probe item`、2 条「门禁验证商品 无图」、2 条「权限探针」 |
| `schedules` | 11 | 上述已停用的 `probe` 任务（保留取证） |

**未处置原因**：删除会牵动 `compliance_reports` / `product_scores` / `listings` /
`orders` 等外键链，属主库写操作，需先出清理方案再执行。**已登记待裁决**。

> 完整债务台账见 `docs/CODE_AND_DIRECTORY_STANDARD.md` §11。
