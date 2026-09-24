# ADR-0026：Membership 写入侧 —— 唯一写入口

- **状态**：Accepted
- **决策编号**：[`DECISIONS.md` D26](../DECISIONS.md#L1483)
- **日期**：2026-09-24

## Context

Phase 1.1~1.7 实现了 `resolve_workspace_context` 的**双读**（MEMBERSHIP 优先、
LEGACY 兜底），迁移 `20260923_08` 也回填了存量数据。但**写入侧从未实现**：
全仓没有任何代码路径为新建租户/新建用户补身份行（`rg "INSERT INTO workspace"` 为空）。

由此产生**三个同源缺陷**（均为真库实测）：

| # | 缺陷 | 实测证据 | 严重度 |
|---|---|---|---|
| 1 | `POST /api/admin/tenants` 不建 `workspace_profiles` | 新租户 admin 的 Context `source=LEGACY_FALLBACK`（演示租户是 `MEMBERSHIP`） | **中**：Phase 1.8 删旧入口后新租户会**失去身份来源** |
| 2 | `POST /api/auth/users` 不建 `workspace_memberships` | 新用户 `source=LEGACY_FALLBACK`、membership 行数 0 | 中：同上 |
| 3 | `PUT /api/auth/users/{id}` 改角色只写 `users.role` | operator 降为 viewer 后 Context **仍返回 OPERATOR**（MEMBERSHIP 是权威路径，旧 `role_key` 继续生效） | **高**：**降权被静默忽略**，属安全缺陷 |
| 4 | `DELETE /api/auth/users/{id}` 未清身份行 | `IntegrityError: FOREIGN KEY constraint failed`（`PRAGMA foreign_keys=ON`） | 中：删账号直接 500 |

缺陷 1/2 是「新数据拿不到身份」，3 是「旧数据改不动权限」，4 是「删不掉」——
**根因完全相同**：身份表没有写入口。

## Decision

新增 `app/services/membership_service.py` 作为**唯一写入口**，四个函数对应四个场景：

- `ensure_workspace_profile()`：幂等建 profile（**不覆盖已有名称**——租户改名
  不应静默改写 Workspace 名称，改名属 Phase 2 的 Workspace 管理界面）；
- `sync_membership()`：幂等 upsert，覆盖「新建」与「改角色」两种场景；
- `remove_user_memberships()` / `remove_user_portal_bindings()`：删账号前清理。

**为什么必须共用 `normalize_legacy_role`**：写侧若自己维护一份 legacy→role_key
映射，就会出现「写进去的角色读不出来」（例如 `compliance_approver` 一边映射
COMPLIANCE、另一边漏掉）。**写侧与读侧必须同一张表。**

**渐进启用**：`workspace_profiles` / `workspace_memberships` 由 Alembic 创建，
`models.py` 刻意不注册（否则 `create_all` 会绕过 Phase 1 的维护窗口门禁）。
因此写侧表未落地时**全部 no-op**，行为与 Phase 1.1 完全一致。

**一个反例（刻意不用探测门禁）**：`remove_user_portal_bindings` 操作的是
`supplier_portal_members`——它是 ORM 模型，`create_all` 一定会建表。若也用
`membership_table_available` 门禁，该函数会在迁移前静默 no-op，
反而**漏掉清理、删账号时撞外键**。

## Consequences

**收益**

- 新租户 / 新用户**从创建起就拿到 MEMBERSHIP 身份**，Phase 1.8 可推进；
- 改角色**真正生效**（降权不再被静默忽略）；
- 删账号不再 500。

**代价 / 硬约束**

- 身份写入**必须走 `membership_service`**，禁止在其他路由内直接写身份表
  （否则会再次漂移出第二份映射）；
- `membership_service` 的表可用性探测**只用于由迁移创建的表**；
  对 `create_all` 一定建表的 ORM 表使用探测门禁会制造静默 no-op（T-29）；
- 改角色时必须同时维护 `users.role` 与 membership 行，两者需保持一致。

## Alternatives considered

| 方案 | 否决理由 |
|---|---|
| **在各路由内直接写身份表** | 会重复实现 legacy→role_key 映射，读写两侧必然漂移 |
| **写侧自建映射表** | 实测同类缺陷形态：`compliance_approver` 一边映射 COMPLIANCE、另一边漏掉 |
| **对 `supplier_portal_members` 也用表探测门禁** | 迁移前会静默 no-op → 漏清理 → 删账号撞外键 |
| **改角色只写 `users.role`** | MEMBERSHIP 是权威路径，旧 `role_key` 继续生效 → 降权静默失效 |
| **把身份表注册进 `models.py`** | `create_all` 会绕过 Phase 1 的维护窗口门禁（规范 §2 D-7） |

## References

- 权威源：[`DECISIONS.md` D26](../DECISIONS.md#L1483)（含四项缺陷复现与真服务复验）
- 相关决策：D24（前端 A′ 方案）、D15 / D23（Phase 1.8）
- 契约：`docs/phase1_interfaces.md` §6/§7
- 规范：T-27（双读改造必须同时实现写入侧）、T-28（写侧与读侧必须共用同一张映射表）、
  T-29（探测门禁只用于由迁移创建的表）