# Phase 1 Migration A/B/C 精确设计

> 日期：2026-09-23 ｜ 状态：**DESIGNED（未执行）**
> 前置：P1-03 已 RESOLVED（`docs/phase1_ledger_reconcile_report.md`）
> 原则：Expand → Seed/Backfill → Contract，三段分离，每段独立验收与备份。

## 0. 执行门禁（全部满足才可开始）

| 门禁 | 状态 |
|---|---|
| P1-03 账本对齐方案验证 | ✅ RESOLVED |
| P1-01 预检器在停写快照全 P0 PASS | 待执行 |
| P1-04 备份 + 恢复演练通过 | 待执行 |
| tenant 0 处理清单评审 | 待评审 |
| 维护窗口确认（8000 端口无监听） | **待用户确认** |

## 1. Revision A（Expand，只加结构，不动数据）

新建文件：`backend/migrations/versions/20260923_07_workspace_identity_expand.py`
`revision = "20260923_07"`，`down_revision = "20260922_06"`

### 1.1 新增表（6 张）

`workspace_profiles`

| 列 | 类型 | 约束 |
|---|---|---|
| id | Integer | PK |
| tenant_id | Integer | FK tenants.id, **unique**, index, NOT NULL |
| name | String(128) | NOT NULL |
| kind | String(32) | NOT NULL, default `'ORGANIZATION'`（ORGANIZATION/PERSONAL/FACTORY） |
| status | String(16) | NOT NULL, default `'active'` |
| owner_user_id | Integer | FK users.id, nullable |
| created_at | DateTime | NOT NULL |

说明：与 `tenants` 一对一，避免修改 tenants 表；未来 Personal 空间用 `kind='PERSONAL'`。

`workspace_roles`（角色模板目录）

| 列 | 类型 | 约束 |
|---|---|---|
| id | Integer | PK |
| key | String(32) | unique, NOT NULL（OWNER/OPERATOR/READ_ONLY/COMPLIANCE） |
| name | String(64) | NOT NULL |
| description | String(256) | default `''` |
| is_system | Boolean | NOT NULL, default true |

`permissions`（权限目录）

| 列 | 类型 | 约束 |
|---|---|---|
| id | Integer | PK |
| key | String(64) | unique, NOT NULL（见契约第 4 节 20 个 key） |
| domain | String(32) | NOT NULL |
| action | String(16) | NOT NULL |
| description | String(256) | default `''` |

`role_permissions`

| 列 | 类型 | 约束 |
|---|---|---|
| id | Integer | PK |
| role_key | String(32) | FK workspace_roles.key, index, NOT NULL |
| permission_key | String(64) | FK permissions.key, index, NOT NULL |
| — | — | **unique(role_key, permission_key)** |

`workspace_memberships`（核心表）

| 列 | 类型 | 约束 |
|---|---|---|
| id | Integer | PK |
| workspace_id | Integer | FK workspace_profiles.id, index, NOT NULL |
| user_id | Integer | FK users.id, index, NOT NULL |
| role_key | String(32) | FK workspace_roles.key, NOT NULL |
| status | String(16) | NOT NULL, default `'ACTIVE'`（ACTIVE/SUSPENDED/REMOVED） |
| is_primary | Boolean | NOT NULL, default false |
| source | String(24) | NOT NULL, default `'LEGACY_BACKFILL'` |
| created_at | DateTime | NOT NULL |
| updated_at | DateTime | NOT NULL |
| — | — | **unique(workspace_id, user_id)** |

`membership_data_scopes`

| 列 | 类型 | 约束 |
|---|---|---|
| id | Integer | PK |
| membership_id | Integer | FK workspace_memberships.id, index, NOT NULL |
| scope_type | String(32) | NOT NULL, default `'WORKSPACE_ALL'` |
| scope_ref | JSON | nullable（如 `{"shop_ids":[1,2]}`） |
| created_at | DateTime | NOT NULL |

### 1.2 索引

- `ix_workspace_memberships_user_status` on (user_id, status)
- `ix_workspace_memberships_workspace_status` on (workspace_id, status)
- `ix_workspace_profiles_tenant` on (tenant_id)（unique 已隐含）

### 1.3 Revision A 明确不做

- 不修改 `users` 表（tenant_id 仍 NOT NULL）；
- 不回填任何数据；
- 不触碰 Product/Order/Finance/Factory 业务表；
- 不删除任何旧列或旧索引。

### 1.4 downgrade

按依赖逆序 drop 6 张表。因无数据写入其他表，downgrade 安全。

## 2. Revision B（Seed + Backfill，幂等）

新建文件：`backend/migrations/versions/20260923_08_workspace_identity_backfill.py`
`revision = "20260923_08"`，`down_revision = "20260923_07"`

### 2.1 Seed 权限目录（20 个 key，按契约第 4 节）

用 `INSERT ... ON CONFLICT DO NOTHING`（SQLite 3.24+ 支持）或先查后插。
`role_permissions` 按契约第 4 节映射表填充。

### 2.2 Seed 角色模板（4 个）

`OWNER` / `OPERATOR` / `READ_ONLY` / `COMPLIANCE`，`is_system=true`。

### 2.3 回填 workspace_profiles

```sql
INSERT INTO workspace_profiles (tenant_id, name, kind, status, created_at)
SELECT id, name, 'ORGANIZATION', 'active', CURRENT_TIMESTAMP
FROM tenants
WHERE id <> 0;
```

**实测数据（2026-09-23 只读复核）**：`tenants` 表共 **7 行且不存在 id=0 的行**；
`tenant_id=0` 的 39 行只存在于业务表与 `users.id=4`（superadmin）。
因此 `WHERE id <> 0` 是**防御性写法**（防止未来出现 id=0 租户），
实际期望 `workspace_profiles` 行数为 **7**。

tenant 0 的 39 行业务数据**不归属任何 Workspace**，属隔离处理范围，不自动归属。

### 2.4 回填 workspace_memberships（期望 10 条）

规则（冻结，见 `docs/phase1_migration_safety.md` 第 5 节 Step 6）：

| legacy role | 回填角色 | 数量（审计基线） |
|---|---|---|
| admin | OWNER | 7 |
| operator | OPERATOR | 1 |
| viewer | READ_ONLY | **2** |
| compliance_approver | COMPLIANCE | 0 |
| superadmin | **不回填**（Platform Identity） | 1 |
| supplier | **不回填**（Factory Collaborator） | 1 |

实测角色分布（`lower(role)` 分组）：admin 7 / viewer 2 / operator 1 / superadmin 1 / supplier 1，合计 12。
实际期望数 = 12 - 1(superadmin) - 1(supplier) = **10 条**。

> superadmin 的 `tenant_id=0` 在 `tenants` 表中**不存在**，
> 因此下方 JOIN 写法会自动排除它，无需额外 `WHERE` 条件；
> 但为可读性与防御性，SQL 中仍显式排除 `LOWER(u.role) = 'superadmin'` 之外的路径。

SQL 骨架：

```sql
INSERT INTO workspace_memberships
  (workspace_id, user_id, role_key, status, is_primary, source, created_at, updated_at)
SELECT wp.id, u.id,
       CASE LOWER(u.role) WHEN 'admin' THEN 'OWNER'
                          WHEN 'operator' THEN 'OPERATOR'
                          WHEN 'viewer' THEN 'READ_ONLY'
                          WHEN 'compliance_approver' THEN 'COMPLIANCE'
            END,
       'ACTIVE', 1, 'LEGACY_BACKFILL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM users u
JOIN workspace_profiles wp ON wp.tenant_id = u.tenant_id
WHERE LOWER(u.role) IN ('admin','operator','viewer','compliance_approver');
```

### 2.5 硬性断言（回填后立即校验，失败即回滚）

| 断言 | 期望 |
|---|---|
| workspace_profiles 行数 | **7**（tenants 表全部行；无 id=0 租户） |
| workspace_memberships 行数 | 10 |
| OWNER 数量 | 7 |
| OPERATOR 数量 | 1 |
| READ_ONLY 数量 | **2** |
| superadmin 的 membership 数 | 0 |
| supplier 的 membership 数 | 0 |
| 每用户 membership 数 > 1 的用户 | 0 |
| 引用不存在的 workspace_id | 0 |
| 引用不存在的 user_id | 0 |

### 2.6 幂等要求

重复执行不得新增记录。所有 INSERT 必须带唯一约束冲突处理；
执行后输出 `inserted / skipped / conflict` 三个计数。

### 2.7 不处理项

- tenant 0 的 39 行业务数据**不归属**任何 Workspace（保持隔离，后续独立任务）；
- 不修改 `users.role`（保留 legacy 值供双读比对）。

## 3. Revision C（Users 表改造，高风险）

新建文件：`backend/migrations/versions/20260923_09_users_nullable_workspace.py`
`revision = "20260923_09"`，`down_revision = "20260923_08"`

### 3.1 变更内容

SQLite 必须用 `op.batch_alter_table` 重建表：

1. `users.tenant_id` 改为 **nullable**；
2. 保留 `tenant_id`、`role`、全部 User ID 与 username（不删列）；
3. `users.id=4`（superadmin）的 `tenant_id` 从 `0` 改为 **NULL**；
4. 增加状态兼容规则：`status` 仅接受 `ACTIVE/DISABLED/DELETED`（旧 lowercase 由 Service 规范化，**不在本 migration 强制改大小写**）；
5. 保持 `username` 唯一约束不变。

### 3.2 前置条件

- Revision B 的 10 条 membership 已回填并通过全部断言；
- **第二次独立备份**（Revision C 前单独做一次）；
- FK 违规（`users.id=4` → `tenants.id=0`）在此 revision 后归零。

### 3.3 验证断言

| 断言 | 期望 |
|---|---|
| users 总数 | 12（不变） |
| tenant_id 为 NULL 的用户 | 1（superadmin） |
| tenant_id = 0 的用户 | 0 |
| FK 违规总数 | 0 |
| username 重复 | 0 |
| 每用户 membership 仍可关联 | 10 |

### 3.4 downgrade

`tenant_id` 改回 NOT NULL，superadmin 的 NULL 还原为 0。
**注意**：若已存在 tenant_id 为 NULL 的其他用户，downgrade 会失败——这是有意的安全设计。

## 4. 执行顺序与回滚点

```
[冷备 1] → Revision A → 验证 → [冷备 2] → Revision B → 断言
   → [冷备 3] → Revision C → 断言 → 双读启用 → 观察期 → 前端接入
```

| 阶段 | 失败处理 |
|---|---|
| Revision A 失败 | downgrade 到 20260922_06，或冷备 1 恢复 |
| Revision B 断言失败 | downgrade 到 20260923_07，或冷备 2 恢复 |
| Revision C 失败 | **优先冷备 3 恢复**（batch rebuild 风险最高） |

## 5. 与代码的衔接点

Revision B 完成后，`backend/app/services/workspace_context.py` 的
`resolve_workspace_context()` 只需在 `TODO(P1-06)` 处插入 MEMBERSHIP 分支：

```python
if membership_table_available(db):
    membership = (db.query(WorkspaceMembership)
                   .filter(WorkspaceMembership.user_id == user.id,
                           WorkspaceMembership.status == "ACTIVE")
                   .order_by(WorkspaceMembership.is_primary.desc())
                   .first())
    if membership:
        return build_membership_context(db, user, membership, trace)
```

调用方零改动。`membership_table_available()` 已实现，可用于渐进启用。

## 6. 未决事项

| 事项 | 需要谁决定 |
|---|---|
| tenant 0 的 39 行业务数据归属或删除 | 用户/业务方 |
| 维护窗口时间 | 用户 |
| 重复供应商 11 行删除确认 | 用户/业务方 |
| Revision C 是否同期启用双读 | 用户 |
