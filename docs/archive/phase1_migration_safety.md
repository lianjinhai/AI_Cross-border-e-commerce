# Phase 1 Workspace Identity Migration Safety Checklist

> 阶段：Phase 1.0 迁移安全分析  
> 审计时间：2026-09-22 18:46–18:58（Asia/Shanghai）  
> 目标数据库：`backend/erp.db`  
> 执行性质：只读检查；未备份、未迁移、未回填、未改代码  
> 当前结论：**NO-GO，禁止直接执行 Workspace Identity Migration**

## 0. 执行摘要

Phase 0 的冻结架构可以实施，但当前主库尚不满足安全迁移条件。

迁移前必须先关闭以下四个门禁：

1. **迁移账本漂移**：代码中的 Alembic head 为 `20260922_06`，主库记录为 `20260922_01`，但数据库已经存在部分 02–06 的结构；禁止直接 `upgrade` 或盲目 `stamp`。
2. **Tenant 0 孤立数据**：主库有 1 个 superadmin 和 38 行业务记录使用 `tenant_id=0`，但不存在 Tenant 0；这些数据不能自动归入任何 Workspace。
3. **运行中数据库无法形成冷备基线**：8000 端口仍有服务监听，数据库在审计期间继续变化，且文件被进程占用，SHA-256 计算失败。
4. **Supply/Sales 分类错误**：13 个 1688 Shop 全部标记为 `sales`，523 条 Order 全部没有 `shop_id`；不能依据当前 Shop/Order 关系回填销售归属或计算可信 GMV。

Phase 1.0 只冻结迁移方法和验收清单。下一步先完成“只读预检器 + 测试 + Alembic 账本对齐方案”，再进入任何 DDL。

---

## 1. 审计范围与方法

### 1.1 已检查

- `docs/final_architecture_assessment.md` 第 1–196 行：ADR-F01～ADR-F15；
- 同文件第 635–910 行：Migration、实施顺序、风险、测试门禁和 P1-01～P1-06；
- SQLAlchemy 模型、认证、用户管理、Factory Portal、Setting、Shop/Order 同步；
- Alembic revision 链和数据库当前 revision；
- 主 SQLite 数据库的表、行数、索引、外键、完整性、Tenant 分布和角色分布；
- 当前运行状态和数据库文件锁定状态。

### 1.2 只读保证

- SQLite 使用 `mode=ro` URI 打开；
- 检查在只读事务中执行并 rollback；
- 未执行 `CREATE`、`ALTER`、`UPDATE`、`DELETE`、`INSERT`、`VACUUM`、`stamp` 或 Alembic upgrade；
- 未读取或输出 Setting 值、OAuth Token、App Secret 或密码哈希；
- 本轮只新增本文档和进度文档。

### 1.3 快照限制

审计期间应用仍在运行，数据库 `LastWriteTime` 从 17:57 更新到 18:58。因此本文行数是审计时点快照，不是静态冻结值。正式迁移必须在停止写入后重新生成 manifest。

---

## 2. 当前数据库规模

### 2.1 文件与 SQLite 状态

| 项目 | 当前值 |
|---|---:|
| 主库文件 | `backend/erp.db` |
| 文件大小 | 2,007,040 bytes，约 1.91 MiB |
| 表数量 | 45 |
| 总行数 | 2,916 |
| Page Size | 4,096 bytes |
| Page Count | 490 |
| Freelist | 0 |
| Journal Mode | `delete` |
| Quick Check | `ok` |
| 审计连接 Foreign Keys | `0` |
| Foreign Key 定义数 | 44 |
| Foreign Key Check 违规 | 1 |
| Alembic 当前 revision | `20260922_01` |
| 代码 Alembic head | `20260922_06` |

应用没有看到统一启用 SQLite `PRAGMA foreign_keys=ON` 的连接事件；当前数据不能假设一直受外键保护。

### 2.2 重点表规模

| 表 | 行数 | 迁移关注点 |
|---|---:|---|
| tenants | 7 | 将各生成一个 WorkspaceProfile |
| users | 12 | 身份回填、superadmin 0、legacy 字段 |
| settings | 4 | 全局 key，需要后续作用域拆分 |
| shops | 13 | 全部是 1688 且标为 sales |
| orders | 523 | 全部 shop_id 为空 |
| suppliers | 22 | 2 行 tenant_id=0 |
| supplier_portal_members | 1 | Factory Collaborator，不应成为普通成员 |
| products | 53 | 本阶段禁止修改；4 行 tenant_id=0 |
| listings | 26 | 本阶段不改；保存历史用户引用 |
| platform_publish_attempts | 0 | requested_by 当前无数据 |
| ai_logs | 911 | 4 行 tenant_id=0 |
| pricing_records | 823 | 本阶段禁止修改 |
| forecast_snapshots | 144 | 本阶段禁止修改 |
| workflow_runs | 24 | 身份迁移不重写 Workflow |
| workflow_steps | 45 | 身份迁移不重写 Workflow |

### 2.3 用户与角色分布

| 旧角色 | 状态 | 数量 | 安全映射 |
|---|---|---:|---|
| admin | active | 7 | OWNER |
| operator | active | 1 | OPERATOR |
| viewer | active | 2 | READ_ONLY |
| supplier | active | 1 | Factory Collaborator 关系，不创建普通 Membership |
| superadmin | active | 1 | Platform Identity，不创建 Membership |

当前没有 `compliance_approver` 数据，但兼容映射必须支持：

- `viewer` 与指令中的 `readonly` → `READ_ONLY`；
- `compliance_approver` 与指令中的 `compliance` → `COMPLIANCE`；
- `supplier` 与指令中的 `factory` → `FACTORY_COLLABORATOR` 上下文。

按照冻结架构，预期回填结果应为：

- WorkspaceProfile：7；
- 普通 WorkspaceMembership：10；
- OWNER：7；
- OPERATOR：1；
- READ_ONLY：2；
- Platform Identity：1 个 superadmin；
- Factory Collaborator：1 个现有 SupplierPortalMember；
- 不自动生成 supplier 的普通 WorkspaceMembership。

这里明确采用 ADR-F05：Factory Collaborator 不成为普通 Workspace Member。`FACTORY_COLLABORATOR` 可以作为 Context 中的受限身份名称，但其事实关系仍来自 Factory/Supplier Collaborator 绑定。

### 2.4 Tenant 0 数据

主库有 39 行使用不存在的 Tenant 0：

| 表 | 行数 |
|---|---:|
| users | 1 |
| products | 4 |
| market_trends | 12 |
| suppliers | 2 |
| shops | 2 |
| category_mappings | 2 |
| schedules | 2 |
| knowledge_docs | 2 |
| ai_logs | 4 |
| ad_campaigns | 2 |
| orders | 2 |
| conversations | 2 |
| messages | 2 |

唯一正式 FK 违规是 `users.tenant_id=0 → tenants.id` 不存在。但其他 tenant_id 字段多数没有 Tenant FK，因此没有被 `foreign_key_check` 报告。

安全处理原则：

- superadmin 用户迁成 Platform Identity，最终 tenant_id 为 NULL；
- 其余 38 行业务数据进入“待归因清单”，不得跟随 superadmin 一起改成 NULL；
- 禁止自动归到 Tenant 1 或最近一次代管 Tenant；
- 能从 TenantAccessLog、创建时间和业务关联证明归属的，形成显式修复映射；
- 无法证明的，保留隔离快照并标记 `UNASSIGNED_LEGACY`，不进入新 Workspace 经营统计。

---

## 3. 影响表

### 3.1 第一批直接新增/修改

| 对象 | 变更类型 | 说明 |
|---|---|---|
| workspace_profiles | 新表 | tenant_id 唯一；类型、状态、阶段、onboarding |
| workspace_roles | 新表 | 系统模板和 Workspace 自定义角色 |
| permissions | 新表/固定目录 | 权限代码目录，需稳定且可测试 |
| role_permissions | 新表 | Role 与 Permission 关系 |
| workspace_memberships | 新表 | User 与 Tenant/Workspace 的关系 |
| membership_data_scopes | 新表 | Store、Factory 等资源范围 |
| users | 分阶段修改 | legacy 字段保留；后续 tenant_id nullable；禁止物理删除 |

`WorkspaceContext Service` 必须先以 legacy adapter 方式落地，再让新代码依赖 Context。它本身不要求先改数据库。

### 3.2 兼容读取和审计涉及

| 表 | 原因 |
|---|---|
| tenants | Workspace Boundary，不删除、不改主键 |
| supplier_portal_members | Factory Collaborator 上下文 |
| suppliers | Factory scope 验证 |
| tenant_access_logs | 区分平台代管和普通 Workspace switch |
| listings | created_by/last_edited_by 历史引用 |
| supplier_catalog_products | updated_by 历史引用 |
| platform_publish_attempts | requested_by 历史引用 |
| settings | Platform/Workspace Setting 分类 |
| shops、oauth_states | Workspace Credential 和 Store scope |
| orders、settlements、platform_settlement_records | Supply/Sales 和 Store 归属只读校验 |

### 3.3 本阶段明确禁止修改

- Product 业务模型；
- Order 业务模型；
- Finance 指标和结算模型；
- Factory 业务流程；
- Capability Profile；
- Business Path；
- AI Copilot；
- Dashboard。

Setting 和 Supply/Sales 的 P0 修复应使用独立 revision/任务，不能混进 Identity 核心建表 revision。

---

## 4. 当前外键与未来约束

### 4.1 当前关键外键

- `users.tenant_id → tenants.id`，NO ACTION；
- `supplier_portal_members.user_id → users.id`，NO ACTION；
- `supplier_portal_members.supplier_id → suppliers.id`，NO ACTION；
- `supplier_catalog_products.updated_by → users.id`，模型定义；
- `listings.created_by/last_edited_by → users.id`，模型定义；
- `platform_publish_attempts.requested_by → users.id`，模型定义；
- OAuthState 关联 Shop；
- 大量业务 tenant_id 只有索引，没有 Tenant FK。

当前实际 SQLite DDL 与 ORM 已有漂移：部分后来补入的用户列和 `orders.shop_id` 在数据库中没有 ORM 声明对应的正式 FK。这也是 Alembic 账本不能盲目提升的原因。

### 4.2 新约束设计

#### workspace_profiles

- FK `tenant_id → tenants.id`；
- UNIQUE `(tenant_id)`；
- 删除策略 RESTRICT/NO ACTION，不级联删除 Tenant。

#### workspace_memberships

- FK `tenant_id → tenants.id`；
- FK `user_id → users.id`；
- FK `role_id → workspace_roles.id`；
- UNIQUE `(user_id, tenant_id)`；
- status：ACTIVE / INVITED / DISABLED / REMOVED；
- 不使用级联物理删除 User。

#### role_permissions

- UNIQUE `(role_id, permission_id)`；
- Role/Permission 删除优先禁用，不物理删除历史引用。

#### membership_data_scopes

- FK `membership_id → workspace_memberships.id`；
- UNIQUE `(membership_id, resource_type, resource_id, access_level)`；
- Membership 使用软删除，因此不依赖 cascade 清理经营事实。

### 4.3 不在第一批做的约束

- 不给全库所有 tenant_id 一次性补 Tenant FK；
- 不把 Order/Settlement.shop_id 改为非空；
- 不给历史 Product、Order、Finance 表做批量重建；
- 不把 Store Scope 约束直接加到所有业务表。

---

## 5. Migration 顺序

采用：`Preflight → Compatibility Layer → Ledger Reconcile → Backup → Expand → Seed → Backfill → Dual Read → Validate → Switch`。

### Step 0：维护窗口与写入冻结

1. 发布维护提示；
2. 停止 API、Scheduler 和任何 Worker/脚本写入；
3. 确认 8000 端口无监听；
4. 确认数据库文件时间不再变化；
5. 重新执行只读 manifest。

没有写入冻结，不允许生成迁移基线。

### Step 1：可重复只读预检器

预检器只输出报告和非零退出码，不自动修数据：

- schema fingerprint；
- Alembic current/head；
- row-count manifest；
- foreign_key_check；
- tenant 0 与 orphan tenant；
- 跨 tenant 关联；
- role mapping 候选；
- Setting key 分类候选；
- Shop.role、source Order、空 Store 归属；
- User 历史引用。

### Step 2：Identity Compatibility Layer

在数据库变更前新增只读 WorkspaceContext Service：

- `get_current_user()`；
- `get_current_workspace()`；
- `get_current_membership()`；
- `get_current_role()`；
- `get_permissions()`；
- `get_data_scope()`。

初始实现只包装现有 User/Tenant，并明确标记 `source=LEGACY_FALLBACK`。旧业务代码暂不批量改写；所有新增代码只能依赖 Context。

Fallback 日志只记录 trace_id、user_id、legacy tenant_id、目标 workspace id 和原因，不记录 token、用户名、凭证或 PII。

### Step 3：Alembic 账本对齐

当前数据库 `current=01`、代码 `head=06`，但后续表/列已经部分存在。

必须：

1. 为 02–06 每个 revision 建立期望 schema fingerprint；
2. 与主库表、列、索引、唯一约束和 FK 逐项比对；
3. 若完全一致，才可在备份后有审计记录地 stamp 06；
4. 若不一致，编写单独的 forward reconciliation revision/脚本；
5. 禁止直接 `alembic upgrade head`，避免重复建表或部分失败；
6. 禁止仅因表名存在就 stamp。

### Step 4：备份与恢复演练

完成第 7 节的备份策略并在临时路径恢复验证。未通过恢复演练，不进入 DDL。

### Step 5：Expand Revision A

仅新增：

- workspace_profiles；
- workspace_roles；
- permissions；
- role_permissions；
- workspace_memberships；
- membership_data_scopes；
- 必要索引和唯一约束。

不修改 users，不回填数据，不改业务表。

### Step 6：Seed 与 Backfill Revision/Command B

1. 插入稳定的 Permission 目录；
2. 插入 OWNER、OPERATOR、READ_ONLY、COMPLIANCE Role Template；
3. 为 7 个真实 Tenant 创建 ORGANIZATION WorkspaceProfile；
4. 为 10 个普通用户创建 Membership；
5. supplier 保持 Factory Collaborator；
6. superadmin 保持 Platform Identity；
7. 使用幂等 upsert/唯一约束，重复运行不增加记录；
8. 输出 inserted/skipped/conflict 数量。

### Step 7：Users Revision C

在 Membership 回填和验证通过后，单独处理 users：

- SQLite 使用 Alembic batch rebuild 将 tenant_id 改 nullable；
- 保留 tenant_id、role、全部 User ID 和 username；
- 将唯一 superadmin tenant_id 从 0 改为 NULL；
- 业务 tenant 0 数据不跟随改动；
- 增加 ACTIVE/DISABLED/DELETED 兼容状态规则；
- 旧 lowercase 值由 Service 规范化，不在同一 migration 强制全量改大小写。

这是高风险 revision，必须单独备份和验证。

### Step 8：认证双读

读取顺序：

1. 指定/活动 Workspace 的 ACTIVE Membership；
2. 若不存在且仍处兼容窗口，读取 legacy User.tenant_id/User.role；
3. 每次 fallback 产生结构化日志和 metric；
4. Platform Super Admin 没有业务 Workspace 时不得调用租户业务 API；
5. Factory Collaborator 从 SupplierPortalMember 生成严格受限 Context。

### Step 9：Context API 与 Switch

身份层稳定后再新增：

- `GET /api/v1/me/workspaces`；
- `POST /api/v1/me/workspaces/{id}/switch`；
- `GET /api/v1/me/workspace-context`。

为保持现有 `/api` 兼容，可提供明确别名，但两条路径必须调用同一 Service，禁止出现两套授权实现。

### Step 10：独立 P0 修复

- Setting 作用域拆分；
- 1688 Shop role 盘点和修复；
- source Shop 禁止销售订单同步；
- tenant 0 业务数据归因/隔离；
- 这些任务使用独立 Migration 和验收，不与 Membership 建表捆绑。

---

## 6. 数据校验方案

### 6.1 迁移前 Manifest

写入不含敏感值的 manifest：

- 数据库 SHA-256；
- 文件字节数、page count、journal mode；
- Alembic revision；
- schema/index/FK fingerprint；
- 每表 row count；
- 每 Tenant 的 User 和核心业务行数；
- FK/orphan/cross-tenant 检查；
- Setting key 名称，不含 value；
- Shop.role/platform 分布；
- Order source/platform/store 分布。

### 6.2 Expand 后

- 所有既有表 row count 必须与冻结 manifest 一致；
- 所有既有业务表 schema fingerprint 不变；
- 新表为空且唯一约束/FK/索引存在；
- 应用旧版本仍可启动和登录。

### 6.3 Backfill 后硬性断言

```text
workspace_profiles = 7
workspace_memberships = 10
OWNER = 7
OPERATOR = 1
READ_ONLY = 2
普通 active 用户缺 Membership = 0
重复 (user_id, tenant_id) = 0
supplier 普通 Membership = 0
superadmin 普通 Membership = 0
WorkspaceProfile 无效 tenant_id = 0
Membership 无效 user_id/tenant_id/role_id = 0
```

若迁移前用户数据变化，以维护窗口重新生成的 manifest 重新计算，不使用本文旧数字硬写迁移逻辑。

### 6.4 Users Revision 后

- User 总数仍为 12；
- User ID、username、password_hash、token_version 不变；
- 只有 Platform Super Admin 的 legacy tenant_id 从 0 变 NULL；
- 普通用户 tenant_id 和 role 仍保留；
- User 历史引用无 orphan；
- `foreign_key_check=0`，或已备案的非身份历史问题保持可解释且不新增。

### 6.5 双读一致性

对每个普通旧用户比较：

- legacy tenant 与 Membership workspace；
- legacy role 与 Role Template；
- 旧 require_* 结果与 permission 结果；
- Factory Portal legacy 访问与 collaborator scope；
- 跨 Workspace 访问必须拒绝；
- fallback 日志数量逐步下降，不能长期静默存在。

### 6.6 Supply/Sales 守门校验

- 1688 Shop 必须为 source，例外必须有证据；
- source Shop 销售同步 API 返回明确拒绝；
- source Shop 关联销售 Order 数为 0；
- 1688 采购不进入 GMV；
- 当前 523 条无 shop_id 历史订单保持 UNASSIGNED，不自动伪造 Store；
- BI/Finance 不把 tenant 0 或未确认 source 数据纳入生产可信指标。

---

## 7. 数据库备份策略设计

### 7.1 当前 SQLite 备份

正式迁移前必须创建两个独立副本：

1. **一致性在线备份**：使用 SQLite Backup API 生成 timestamped backup；
2. **停写冷备**：停止应用后复制 `erp.db` 原文件。

当前 sqlite3 CLI 不存在，需提供最小、可审计的 Backup API 脚本。脚本只能接受明确源文件和目标目录，禁止覆盖已有备份。

备份目录建议位于项目外的受控路径，结构：

```text
phase1-backups/
└── 20260922-HHMMSS/
    ├── erp-online.db
    ├── erp-cold.db
    ├── manifest.json
    ├── schema.sql
    └── SHA256SUMS
```

要求：

- 不提交 Git，不放入 Docker image；
- 目录 ACL 仅限迁移操作人；
- 备份包含加密 Token/Secret，仍按敏感数据加密保存；
- manifest 不输出密码哈希、Token、Secret 或 Setting value；
- 至少保留迁移前、迁移后和最近一次已验证版本；
- 保留期和销毁需要审计记录。

### 7.2 备份验证

每个副本必须：

- SHA-256 可计算且匹配 manifest；
- `PRAGMA quick_check=ok`；
- row-count 和 schema fingerprint 与停写基线一致；
- 能在独立临时路径打开；
- 使用当前旧版本应用完成登录、租户隔离、商品/订单只读烟测；
- 不连接真实平台，不触发 Scheduler 或外部副作用。

### 7.3 恢复演练

演练在临时目录执行：

1. 从备份恢复为临时数据库；
2. 以旧应用版本和禁用 Scheduler/外部调用方式启动；
3. 验证登录、租户、User、商品和订单只读路径；
4. 对比 manifest；
5. 记录恢复耗时和结果。

只有恢复演练成功，才允许迁移生产文件。

### 7.4 实际回滚

若 Migration 或验证失败：

1. 立即保持维护模式；
2. 停止应用和所有写入者；
3. 将失败数据库重命名保存，不直接删除；
4. 从已验证冷备恢复主文件；
5. 校验 SHA-256、quick_check、row count 和 revision；
6. 使用迁移前应用构建启动；
7. 执行最小烟测后恢复服务；
8. 保存失败库、日志和 migration output 供复盘。

项目目录当前不是 Git 工作区，因此迁移前还必须保存不可变的应用源码/构建清单和依赖锁文件，否则数据库恢复后无法保证回到匹配的应用版本。

### 7.5 未来 PostgreSQL

进入 PostgreSQL 后使用两层保护：

- 逻辑备份：custom-format `pg_dump`，支持选择性恢复；
- 存储快照/PITR：用于大规模失败恢复；
- 迁移前后均保存 Alembic revision、schema dump、row manifest；
- 恢复演练必须在独立数据库实例完成。

---

## 8. 回滚方案

### 8.1 代码回滚

- WorkspaceContext Service 初始只做包装，可由 feature flag 回退 legacy adapter；
- 新 Context API 不替换旧 `/auth/me`；
- 旧 require_* 在双读期保留；
- 前端尚未接入，本阶段无 UI 回滚面。

### 8.2 Schema 回滚

- Expand Revision A 的 downgrade 只删除新空表；
- 一旦写入 Membership，优先 forward-fix，不轻易 drop；
- Users batch rebuild 作为独立 revision，可用冷备恢复；
- 不通过 downgrade 删除历史 Membership 或审计记录；
- Setting/Supply 修复是独立 revision，互不绑架。

### 8.3 数据回滚

- Backfill 记录 batch_id 和来源 User/Tenant/role；
- 只撤销本 batch 新增的 Membership/Profile；
- 不修改或删除业务表数据；
- tenant 0 归因需要独立映射清单，禁止无清单反向修改；
- 每次回填幂等，重复运行得到相同结果。

---

## 9. 风险登记

| 风险 | 等级 | 当前事实 | 门禁/缓解 |
|---|---|---|---|
| Alembic 账本与结构漂移 | P0 | current 01，head 06 | 逐 revision schema fingerprint，禁止盲升/盲 stamp |
| 运行中数据库无静态基线 | P0 | 8000 监听，文件持续变化且锁定 | 维护窗口、停写、双备份、SHA manifest |
| Tenant 0 孤立业务数据 | P0 | 39 行、13 张表 | superadmin 与业务数据分开处理；不可自动归属 |
| FK 未实际强制 | P0 | audit connection foreign_keys=0 | 连接级启用方案、preflight、PG 集成验证 |
| 1688 被标为 sales | P0 | 13/13 Shop | 独立盘点修复，source/sales 双重门禁 |
| Order 无 Store 归属 | P1 | 523/523 shop_id=NULL | 保持 UNASSIGNED，不伪造回填 |
| supplier 回填为普通成员 | P1 | 指令角色名与 ADR-F05 易冲突 | 保留 Collaborator 关系，不建普通 Membership |
| SQLite users 表重建失败 | P1 | tenant_id nullable 需 batch rebuild | 单独 revision、停写冷备、恢复演练 |
| 物理删除 User 造成历史 orphan | P1 | 当前 delete_user 使用 db.delete | 先改软删除/成员移除，再开放多 Workspace |
| legacy/new 权限不一致 | P1 | role 硬编码 | 双读对比、fallback 日志、权限矩阵测试 |
| 备份含敏感凭证 | P1 | Shop Token/Secret 在库中 | 加密、ACL、禁入版本库、审计销毁 |
| 无 Git 发布基线 | P1 | 项目根不是 Git 仓库 | 保存源码/依赖/构建 manifest |

---

## 10. Phase 1.0 Checklist

| 检查项 | 状态 | 结论 |
|---|---|---|
| 冻结架构分段读取 | PASS | ADR 与 Migration/风险/测试段已完整读取 |
| 当前数据库规模 | PASS | 45 表、2,916 行、约 1.91 MiB |
| 影响表识别 | PASS | 身份、新表、历史引用和配置边界已列出 |
| 外键检查 | FAIL | 1 个正式违规；FK 未统一启用 |
| Alembic 一致性 | FAIL | current 01 / head 06，存在结构漂移 |
| Tenant 归属一致性 | FAIL | 39 行 tenant_id=0 |
| Supply/Sales 边界 | FAIL | 13 个 1688 Shop 均为 sales |
| Store 归属 | WARN | 523 条订单无 shop_id |
| Backup 策略 | DESIGNED | 尚未执行；需维护窗口和恢复演练 |
| Migration 顺序 | DESIGNED | Expand/Backfill/Users rebuild 已拆分 |
| 回滚方案 | DESIGNED | 冷备恢复 + 兼容层回退 |
| 数据校验方案 | DESIGNED | manifest、硬性断言和双读对比已定义 |

### 允许进入 Phase 1.1 的条件

以下条件全部满足后，才可开始 Identity Compatibility Layer 和测试实现：

- 本文档评审通过；
- P1-01 预检器范围确认；
- supplier 不回填普通 Membership 的冻结规则被执行；
- 确定维护窗口和备份落点；
- 明确 Alembic 01→06 账本对齐方式；
- tenant 0 业务数据采用隔离/显式映射，禁止自动归属；
- 不在第一批 revision 修改 Product、Order、Finance 或 Factory 业务。

### Phase 1.0 结论

迁移方案可行，但当前数据库不满足直接迁移条件。下一任务应是：

1. 实现只读、可重复的 migration preflight；
2. 增加 Identity Compatibility Layer 的 legacy-only 测试；
3. 形成 02–06 schema fingerprint 对齐报告；
4. 在不执行 DDL 的情况下完成 Migration A/B/C 的精确设计；
5. 用户确认维护窗口后才执行备份和迁移。

