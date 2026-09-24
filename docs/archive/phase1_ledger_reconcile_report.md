# P1-03 Alembic 账本对齐报告

> 日期：2026-09-23 ｜ 状态：**RESOLVED（方案已验证，待维护窗口执行）**
> 方法：只读主库 + 临时副本演练。主库 `backend/erp.db` 全程未被修改。

## 1. 问题

主库 `alembic_version = 20260922_01`，代码 head = `20260922_06`，相差 5 个 revision。
直接 `alembic upgrade head` 会重复建表或部分失败，因此 Phase 1.0 将其列为 P0 阻断项。

## 2. 逐 revision 漂移比对（只读实测）

| revision | 期望结构 | 主库实际 | 结论 |
|---|---|---|---|
| 02 | suppliers 新增 7 列 + `uq_supplier_source` 唯一索引 | 7 列**全部已存在**；索引**缺失** | **部分漂移** |
| 03 | opportunity_supplier_matches 新增 4 列 | 全部已存在 | 已满足 |
| 04 | supplier_offers 新增 `currency` | 已存在 | 已满足 |
| 05 | forecast_snapshots 2 列 + matches `promoted_at` + 2 张新表 | 全部已存在 | 已满足 |
| 06 | platform_publish_attempts 4 列 + purchase_orders 5 列 | 全部已存在 | 已满足 |

**漂移根因**：应用层 `app/db.py::_migrate_sqlite()` 会在启动时自动补列（create_all + ALTER TABLE），
但**不会创建唯一索引**。因此列全部就位，唯一索引漏建，账本停留在 01。

## 3. 索引缺失的真实原因（关键发现）

在临时副本上直接执行 `alembic upgrade head`，在 revision 02 报错：

`
sqlalchemy.exc.IntegrityError: UNIQUE constraint failed:
suppliers.tenant_id, suppliers.name, suppliers.source_url
[SQL: CREATE UNIQUE INDEX uq_supplier_source ON suppliers (tenant_id, name, source_url)]
`

主库 `suppliers` 表存在 3 组重复键（共 11 行冗余）：

| tenant_id | name | source_url | 重复数 | id |
|---|---|---|---|---|
| 1 | `probe supplier` | `''` | 10 | 9-16, 18, 19 |
| 0 | `probe supplier` | `''` | 2 | 17, 20 |
| 1 | （中文供应商名） | `''` | 2 | 21, 22 |

绝大多数是历史自动化测试残留（`probe supplier`），不是真实业务数据。

## 4. 验证过的对齐方案

在临时副本（`sqlite3.Connection.backup()` 生成，主库未动）上执行，**全部通过**：

1. 去重 `suppliers`：每组保留最小 id，删除其余（实测删除 11 行，剩 11 行）；
2. 执行 `alembic upgrade head`：5 个 revision 全部成功，退出码 0；
3. 结果核对：

| 指标 | 结果 |
|---|---|
| `alembic_version` | `20260922_06` ✅ |
| 表数量 | 45（无意外新增） |
| `uq_supplier_source` | 已创建 ✅ |
| `PRAGMA integrity_check` | `ok` ✅ |
| `PRAGMA foreign_key_check` | 仅剩 1 项：`users.id=4` → `tenants.id=0`（Revision C 处理） |
| 模型 vs schema 差异 | 0 表缺失、0 列缺失 ✅ |
| 业务数据保真 | tenants 7 / users 12 / orders 523 / products 53 / shops 13 |

## 5. 正式执行步骤（维护窗口内）

> 前置：完成一次备份与恢复演练（P1-04），确认 8000 端口无监听，库文件时间不再变化。

1. 用 `sqlite3.Connection.backup()` 生成带时间戳的冷备 + manifest；
2. 记录执行前去重清单（`tenant_id` / `name` / `source_url` / 保留 id）；
3. **人工复核** 3 组重复项，确认无真实业务语义差异（当前证据：均为测试残留或同名不同批次录入）；
4. 执行去重 SQL（保留最小 id），**不删除 tenants / users / orders / products 任何行**；
5. 执行 `alembic upgrade head`（已实测幂等安全）；
6. 校验 `alembic_version`、`uq_supplier_source`、`integrity_check`、行数 manifest；
7. 若任一步失败：停止，从第 1 步冷备恢复。

## 6. 回滚方案

- **执行前失败**：直接丢弃副本，主库无变化；
- **执行中失败**：停止服务 → 用冷备覆盖 `erp.db` → 重启验证；
- **执行后发现问题**：`alembic downgrade 20260922_01`（各 revision 均实现了 downgrade），
  或冷备恢复（优先）；
- 去重删除的 11 行如需找回：从冷备中 `SELECT` 并按 id 回插。

## 7. 对 P1-05 的解锁意义

P1-03 从 `BLOCKED` 变为 `RESOLVED`。P1-05（Expand Migration A）的剩余前置：

1. P1-04 备份恢复演练通过（并行进行中）；
2. P1-01 预检器在停写快照上全 P0 PASS（并行进行中）；
3. tenant 0 业务数据（39 行）处理清单评审通过；
4. 用户确认维护窗口。

## 8. 未决风险

| 风险 | 等级 | 说明 |
|---|---|---|
| 重复供应商语义确认 | P1 | 需业务方确认被删的 11 行确无独立价值（**已确认零引用**） |
| `users.id=4` FK 违规 | P0 | Revision C 将 `tenant_id` 改 nullable 后置 NULL 解决 |
| 去重后引用完整性 | **已排除** | 实测：11 个待删 id 在全部 9 张含 `supplier_id` 的表中**零引用**；6 处关联行全部指向保留 id（9/17/21） |
| 应用层自动补列机制 | P1 | `_migrate_sqlite()` 应在上线前收敛，避免继续绕过 Alembic |

### 8.1 引用完整性实测证据

待删 id：`10,11,12,13,14,15,16,18,19,20,22`（11 个）
保留 id：`9,17,21`（3 个，各自是所在重复组的最小 id）

| 表 | 指向待删 id | 指向保留 id |
|---|---:|---:|
| opportunity_supplier_matches | 0 | 4 |
| supplier_catalog_products | 0 | 1 |
| supplier_portal_members | 0 | 1 |
| purchase_orders / settlements / supplier_offers / supplier_scores / supplier_evidence / opportunity_attributions | 0 | 0 |

**结论：去重不产生任何孤儿引用，可直接执行。**
