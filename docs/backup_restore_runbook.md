# SQLite 备份与恢复演练运维手册

> 适用版本：Phase 1 Workspace 身份迁移（P1-04）
> 工具：`backend/scripts/backup_restore_drill.py`
> 关联文档：`docs/archive/phase1_migration_safety.md` 第 7 节、第 8 节

## 0. 为什么必须做这件事

Workspace 身份迁移包含 DDL（建表、加列、回填）。一旦执行，数据库结构就与迁移前不兼容。
如果没有**可验证的备份**和**实际演练过的恢复流程**，迁移失败时将无法回到可用状态。

因此本手册定义一条硬性门禁：

> **迁移前必须完成至少一次完整恢复演练，并留存 manifest 与演练报告。**
> 没有演练证据，不得执行任何 DDL。

### 为什么不能直接复制文件

项目主库当前为 `journal_mode=delete`，但应用运行期间 SQLite 可能切换到 WAL。
WAL 模式下，最新事务可能还在 `-wal` 旁文件里；此时用资源管理器或 `Copy-Item`
直接复制 `erp.db`，得到的副本可能**缺少最新数据，甚至内部不一致**。

本工具一律使用 SQLite 官方备份 API（`sqlite3.Connection.backup()`），由 SQLite
自身保证事务一致性；备份完成后把副本归一到 `DELETE` 日志模式，使其成为不依赖
旁文件的单文件制品。

### 只读保证

工具对主库**只读**：

- 连接使用 `file:...?mode=ro` URI，并设置 `PRAGMA query_only=ON`；
- 不执行任何 `INSERT` / `UPDATE` / `DELETE` / DDL；
- 不复制主库文件，因此不会产生 `-wal` / `-shm` / `-journal` 旁文件；
- `backup` 与 `drill` 都会在运行前后比对主库 SHA256，若发生变化会在输出中给出 WARN。

## 1. 备份前检查清单

逐项确认后才开始备份。任何一项不满足，先处理再继续。

| # | 检查项 | 命令 / 方法 | 通过标准 |
|---|---|---|---|
| 1 | 应用已停止写入 | 确认运维已进入维护窗口，前端与 API 不再接受业务请求 | 无人正在下单、同步订单、跑工作流 |
| 2 | 8000 端口无监听 | `Get-NetTCPConnection -LocalPort 8000 -State Listen` | 无输出（无进程监听） |
| 3 | 无 python 进程持有库 | `Get-Process python -ErrorAction SilentlyContinue` | 无相关进程；若有，先确认不是本项目的服务 |
| 4 | 库文件时间不再变化 | `Get-Item backend\erp.db \| Select-Object Length, LastWriteTime` 连续观察 1 分钟 | `LastWriteTime` 与 `Length` 均不再变化 |
| 5 | 无残留旁文件 | 检查 `backend\erp.db-wal`、`erp.db-shm`、`erp.db-journal` 是否存在 | 不存在（存在则说明仍有写入者或上次未干净关闭） |
| 6 | 磁盘空间充足 | `Get-PSDrive F` | 可用空间 ≥ 库文件大小的 10 倍 |
| 7 | 备份路径不在项目内 | 使用项目外的受控目录 | 备份不进 Git、不进 Docker 镜像 |

> 若第 4、5 项不满足，说明仍有写入者。此时生成的备份会带
> `changed_during_backup=true` 标记，**不得**作为迁移基线使用。

### 备份目录位置

默认输出到 `backend/backups/`（仅用于本地开发演练）。

**正式迁移的备份必须放在项目外的受控路径**，例如 `D:\phase1-backups\20260922-HHMMSS\`，
并限制目录 ACL 仅迁移操作人可访问——因为备份包含加密后的 Token / Secret 等敏感数据。

## 2. 备份命令

在 `backend` 目录下执行：

```powershell
cd backend
python scripts\backup_restore_drill.py backup --db erp.db --out-dir D:\phase1-backups\20260922-230000
```

- `--db`：主库路径，默认在 `backend` 下使用 `erp.db`；
- `--out-dir`：备份输出目录，不存在会自动创建；默认 `backend/backups/`；
- 输出文件：`erp-YYYYmmdd-HHMMSS.db` 与同名 `erp-YYYYmmdd-HHMMSS.db.manifest.json`；
- **绝不覆盖已有备份**：同名冲突时自动追加序号（`erp-...-2.db`）；
- 加 `--json` 可得到机器可读输出，便于归档。

### 输出解读

```
[PASS] source_read_only: ... 以只读方式打开，未被修改
[PASS] backup_created: ...erp-20260923-192946.db (2007040 bytes, sha256=...)
[PASS] integrity_check: ok
[PASS] foreign_key_check: 无外键违规
[PASS] inventory: 表 45 张，总行 2916 行，alembic current=20260922_01
[PASS] source_stability: 备份期间主库哈希未变化（已确认停写）
[PASS] manifest_written: ...
```

关注两点：

- `source_stability` 必须是 **PASS**。若为 WARN，说明备份期间仍有写入，需重新备份；
- `foreign_key_check` 若显示存量违规，会如实写入 manifest 并在演练时要求显式声明基线。

### manifest 字段说明

| 字段 | 含义 |
|---|---|
| `created_at` | 备份时间（带时区） |
| `source.path` / `size_bytes` / `sha256` / `mtime` | 源库路径、大小、SHA256、修改时间 |
| `source.changed_during_backup` | 备份期间源库是否变化（必须为 `false`） |
| `backup.file_name` / `size_bytes` / `sha256` | 备份文件名、大小、SHA256 |
| `database.table_count` / `total_rows` | 表数量、总行数 |
| `database.alembic_current` | 备份时点的 Alembic revision |
| `database.schema_fingerprint` | schema 摘要，用于证明结构一致 |
| `database.row_counts` | 逐表行数 |
| `integrity_check` | `PRAGMA integrity_check` 结果 |
| `foreign_key_check` | `PRAGMA foreign_key_check` 结果与违规明细 |
| `tool.version` / `python` / `sqlite` | 工具版本与运行环境版本 |

> manifest 不含 `username`、`password_hash`、`token`、`secret`、setting value 等敏感值，
> 只记录表名、计数与哈希，可安全归档和贴进变更单。

## 3. 验证命令

任何备份在使用前都必须重新校验一次：

```powershell
cd backend
python scripts\backup_restore_drill.py verify --backup D:\phase1-backups\20260922-230000\erp-20260922-230000.db
```

校验项：文件 SHA256、文件大小、`integrity_check`、`foreign_key_check`、
表数量、总行数、逐表行数、`alembic_current`、schema 摘要。

- 全部一致：退出码 `0`，输出 `校验通过`；
- 任一项不一致：退出码 `1`，逐项列出 FAIL 原因（例如 `sha256` 或 `total_rows`）；
- 备份文件本身损坏到无法读取：同样退出码 `1`，并提示 `数据库无法读取`；
- 路径写错、manifest 缺失等操作性问题：退出码 `2`，并给出排查提示。

> 只要 `verify` 不是 0，这个备份就**不能**用于迁移或回滚。

## 4. 恢复演练命令

```powershell
cd backend
python scripts\backup_restore_drill.py drill --db erp.db --work-dir D:\phase1-backups\drill --json
```

演练流程：

1. 只读打开主库，采集基线（表数、行数、alembic、schema 摘要、完整性、外键）；
2. 用备份 API 备份到临时目录；
3. 从该备份恢复到**另一个全新路径**（模拟真实恢复）；
4. 对恢复库逐项与源库比对：表数、总行数、逐表行数、alembic 版本、schema 摘要；
5. 以**只读**方式打开恢复库，验证关键表可查询：`tenants`、`users`、`orders`、
   `products`、`shops`、`settings`；
6. 输出 PASS / FAIL 逐项结果；
7. 默认清理临时文件；加 `--keep` 保留备份与恢复库以便取证。

退出码：全部通过 `0`；任一失败 `1`；参数或环境错误 `2`。

### 存量外键违规的处理

若库中存在迁移前已知的存量外键违规（例如 `users` 引用了不存在的 `tenants` 行），
默认严格模式下演练会判 FAIL。确认这些违规属于已知存量后，用 `--fk-baseline` 显式声明：

```powershell
python scripts\backup_restore_drill.py drill --db erp.db --work-dir D:\phase1-backups\drill --fk-baseline "users.4->tenants"
```

- 恢复库违规**与基线完全一致** → PASS（仍须按 `phase1_migration_safety.md` 在迁移前处置）；
- 出现基线之外的新违规，或基线中的违规消失 → FAIL。

### 演练报告留存

演练完成后，把 `--json` 输出保存为报告文件，与 manifest 一起归档：

```powershell
python scripts\backup_restore_drill.py drill --db erp.db --json > D:\phase1-backups\drill-report-20260922.json
```

报告需记录：演练时间、表数、行数、alembic current、integrity 结果、
外键违规数、恢复耗时、逐项 PASS/FAIL。这是 P1-04 的验收证据。

## 5. 真实回滚步骤

### 何时使用备份覆盖

满足以下任一条件，即进入回滚流程：

- Migration 执行报错或中途中断；
- 迁移后校验（行数、外键、Alembic revision、关键业务查询）不通过；
- 迁移后应用无法启动，或登录、租户隔离、商品/订单只读路径异常；
- 出现无法在维护窗口内定位的数据异常。

**决策原则**：迁移后问题无法在维护窗口内确认修复，就立即回滚，不要在压力下边修边试。

### 回滚操作顺序

1. **保持维护模式**，前端与 API 继续拒绝业务请求，不要让用户写入。
2. **停止应用和所有写入者**：确认 8000 端口无监听、无 python 进程持有库文件。
3. **保存失败库，不要删除**：
   ```powershell
   Move-Item -LiteralPath backend\erp.db -Destination backend\erp.db.failed-20260922-231500
   ```
   同时保留 `erp.db-wal` / `erp.db-shm`（若存在），供复盘分析。
4. **从已验证的备份恢复主文件**。先确认该备份已通过 `verify`：
   ```powershell
   python scripts\backup_restore_drill.py verify --backup D:\phase1-backups\20260922-230000\erp-20260922-230000.db
   ```
   然后恢复到 `backend\erp.db`。推荐做法是用工具恢复到临时路径并确认无误后，
   再放置到目标位置：
   ```powershell
   python scripts\backup_restore_drill.py drill --db D:\phase1-backups\20260922-230000\erp-20260922-230000.db --keep --work-dir D:\phase1-backups\restore
   ```
   用 `--keep` 保留的 `restored.db` 作为恢复源，复制到 `backend\erp.db`。
   > 注意：这里的 `--db` 是**备份文件本身**，用于验证它能被正确恢复；
   > 不要直接对主库执行覆盖。
5. **校验恢复结果**（见第 6 节清单），确认 SHA256、行数、Alembic revision 与基线一致。
6. **回滚代码**到迁移前的构建版本（见下）。
7. **执行最小烟测**：登录、租户隔离、商品列表、订单列表。
8. **恢复服务**，并在变更单中记录回滚时间点、原因与证据文件。

### 如何回滚代码

数据库回滚后，应用代码必须回到与备份匹配的版本，否则新代码会访问不存在的表/列。

- 项目目录当前**不是 Git 工作区**，因此迁移前必须另外保存不可变的应用源码快照或构建清单
  与依赖锁文件（`backend/requirements.txt` 的实际安装版本）；
- 回滚时用该快照替换 `backend/app`、`backend/migrations` 与前端构建产物；
- 确认 `alembic.ini` 与 `migrations/versions/` 目录内容与备份时点一致；
- 不要使用"最新代码 + 旧数据库"的组合，这是最常见的二次故障来源。

### 如何通知干系人

回滚开始与结束时各通知一次，内容包括：

1. **开始**：发生什么（迁移失败/校验不通过）、已采取的措施、预计恢复时间、业务影响范围；
2. **结束**：回滚完成时间、数据丢失边界（回滚到备份时点，备份之后的新增写入会丢失）、
   当前服务状态、后续复盘安排。

通知对象：业务负责人、运营（订单/客服受影响方）、迁移操作人、复核人。
不要在通知中粘贴含敏感数据的日志或 manifest 明细。

> **数据丢失边界**：回滚会把数据库恢复到备份时点，备份之后产生的业务写入会丢失。
> 这也是必须在停写维护窗口内操作的原因——停写期间没有新写入，回滚不丢业务数据。

## 6. 回滚后验证清单

逐项打勾后才允许恢复服务：

| # | 验证项 | 命令 / 方法 | 通过标准 |
|---|---|---|---|
| 1 | 文件 SHA256 一致 | `Get-FileHash backend\erp.db -Algorithm SHA256` | 与备份 manifest 的 `backup.sha256` 一致 |
| 2 | 完整性检查 | `python scripts\backup_restore_drill.py verify --backup <恢复后文件>` | 退出码 0 |
| 3 | 表数量与总行数 | 上一步输出中的 `table_count` / `total_rows` | 与 manifest 记录一致 |
| 4 | Alembic revision | `alembic current`（由迁移操作人执行） | 等于备份时点的 `alembic_current` |
| 5 | 外键状态 | `verify` 输出的 `foreign_key_check` | 与备份时点一致（含已知存量违规） |
| 6 | 无残留旁文件 | 检查 `erp.db-wal` / `erp.db-shm` / `erp.db-journal` | 不存在 |
| 7 | 应用可启动 | 启动服务并访问 `/docs` 或健康检查 | 正常响应，无启动异常 |
| 8 | 登录可用 | 使用运维测试账号登录 | 登录成功，角色正确 |
| 9 | 租户隔离 | 分别用两个不同租户的账号查看商品/订单 | 各自只见本租户数据 |
| 10 | 商品只读路径 | `GET /api/products` | 返回 200，条数与库中一致 |
| 11 | 订单只读路径 | `GET /api/orders` | 返回 200，条数与库中一致 |
| 12 | 调度器与外部调用 | 确认 Scheduler 未触发平台写请求 | 无外部副作用 |

> 第 8-11 项按 `phase1_migration_safety.md` 第 7.2 / 7.3 节要求，需使用**迁移前版本**的
> 应用完成；演练与真实回滚都应遵守，且不得连接真实平台。

## 7. 备份保留策略

| 类别 | 保留规则 | 说明 |
|---|---|---|
| 常规备份 | **保留最近 7 份** | 覆盖最近一周的日常备份，超出的可销毁 |
| 迁移前基线 | **永久保留一份** | Phase 1 迁移前停写时点的备份，是最终回滚依据 |
| 迁移后验证版 | 至少保留最近一次已验证版本 | 用于对比迁移结果 |
| 失败库 | 复盘完成后按需保留 | 至少保留到复盘结论归档 |

### 销毁要求

- 销毁任何备份前，先确认它不是"迁移前基线"；
- 销毁需要审计记录：销毁时间、文件路径、SHA256、操作人、销毁原因；
- 备份包含加密 Token / Secret，销毁时应安全删除（而非仅移入回收站）。

### 目录组织建议

```text
D:\phase1-backups\
├── 20260922-230000\                 # 迁移前基线（永久保留）
│   ├── erp-20260922-230000.db
│   ├── erp-20260922-230000.db.manifest.json
│   └── drill-report-20260922.json
├── 20260923-010000\                 # 迁移后验证版
└── daily\                           # 常规备份，保留最近 7 份
```

## 8. 迁移到 PostgreSQL 后的对应做法

进入 PostgreSQL 后，SQLite 备份 API 不再适用，改为两层保护：

| 层次 | 手段 | 用途 |
|---|---|---|
| 逻辑备份 | `pg_dump --format=custom` | 支持选择性恢复（单表、单 schema），日常与迁移前基线 |
| 物理/快照 | 存储快照或 PITR（WAL 归档） | 大规模失败、误删数据的快速恢复 |

### 对应关系

| SQLite 做法 | PostgreSQL 对应做法 |
|---|---|
| `backup_restore_drill.py backup` | `pg_dump --format=custom --file=...` |
| `verify`（SHA256 + integrity_check） | `pg_restore --list` 校验 + 在独立库实际 `pg_restore` 一次 |
| `drill`（恢复到全新路径） | 恢复到**独立数据库实例/独立库**，不得覆盖生产库 |
| `PRAGMA integrity_check` | `pg_dump` 成功 + `pg_restore` 成功 + 关键表行数比对 |
| `PRAGMA foreign_key_check` | 迁移后约束校验查询（`NOT VALID` 约束的 `VALIDATE CONSTRAINT`） |
| `alembic_version` 比对 | `SELECT * FROM alembic_version` 比对 |
| manifest（SHA256 + 行数 + revision） | 备份清单：dump 文件哈希、revision、schema dump、逐表行数 |

### PostgreSQL 迁移前后的要求

1. 迁移前后**都要**保存 Alembic revision、schema dump 与行数清单；
2. 恢复演练必须在独立数据库实例完成，禁止在生产实例上演练；
3. `pg_dump` 与 SQLite 一样，必须在**停写窗口**内执行，或使用一致性快照导出；
4. 恢复演练同样要求留存报告与清单文件，作为迁移门禁证据。

### 演练脚本的过渡

`backup_restore_drill.py` 是针对 SQLite 的实现，PostgreSQL 阶段需要独立的脚本或
运维流程。但本手册定义的门禁不因数据库类型而放宽：

> **迁移前必须完成一次可验证的恢复演练并留存 manifest 与报告。**

## 9. 常见问题

### 库文件被占用 / 备份失败

现象：`SQLite 操作失败`、`database is locked`、或无法创建备份文件。

排查顺序：

1. 确认应用已停止：`Get-NetTCPConnection -LocalPort 8000 -State Listen` 应无输出；
2. 确认无 python 进程持有库：`Get-Process python -ErrorAction SilentlyContinue`；
3. 确认没有其他工具（DB Browser、VS Code 插件）打开了 `erp.db`；
4. 确认备份目录可写、磁盘空间充足。

### `verify` 报 `sha256` 不一致

备份文件被改动或损坏。**不要继续使用该备份**，改用其他已验证副本重新执行
`verify`；若所有副本都不一致，重新执行 `backup`（需重新确认停写）。

### 演练 `source_stability` 为 WARN

说明备份期间仍有写入者。这不是工具问题，而是流程问题：请回到第 1 节清单，
彻底停写后重新演练。

### `foreign_key_check` 显示存量违规

这是迁移前已知的数据债（参见 `docs/archive/phase1_migration_safety.md` 第 4 节）。
演练时用 `--fk-baseline` 声明，但**迁移前必须实际处置**，不能只靠声明绕过。

### 为什么默认输出到 `backend/backups/`

仅为本地开发与演练提供便利默认值。**正式迁移备份必须输出到项目外的受控路径**，
因为备份包含敏感数据，不应进入项目目录、Git 或 Docker 镜像。

## 10. 快速参考

```powershell
cd backend

# 1) 备份（正式迁移请指定项目外受控目录）
python scripts\backup_restore_drill.py backup --db erp.db --out-dir D:\phase1-backups\20260922-230000

# 2) 验证备份
python scripts\backup_restore_drill.py verify --backup D:\phase1-backups\20260922-230000\erp-20260922-230000.db

# 3) 恢复演练（并留存报告）
python scripts\backup_restore_drill.py drill --db erp.db --json > D:\phase1-backups\drill-report-20260922.json

# 4) 演练需保留产物时
python scripts\backup_restore_drill.py drill --db erp.db --work-dir D:\phase1-backups\drill --keep

# 5) 存在已知存量外键违规时
python scripts\backup_restore_drill.py drill --db erp.db --fk-baseline "users.4->tenants"
```

### 退出码约定

| 退出码 | 含义 | 处理 |
|---|---|---|
| `0` | 全部通过 | 可继续后续步骤 |
| `1` | 校验/演练失败 | **停止**，按失败项排查，不得执行 DDL |
| `2` | 参数或运行环境错误 | 按错误提示修正后重试 |

## 11. 迁移门禁

执行 Phase 1 任何 DDL 之前，以下证据必须齐备：

- [ ] 停写维护窗口已确认（应用停止、8000 端口无监听、库文件时间不再变化）；
- [ ] 迁移前基线备份已生成，且 `source.changed_during_backup=false`；
- [ ] 该备份已通过 `verify`（退出码 0）；
- [ ] 恢复演练已通过（`drill` 退出码 0）；
- [ ] 演练报告与 manifest 已归档；
- [ ] 迁移前应用源码/构建清单与依赖锁文件已保存；
- [ ] 存量外键违规处置方案已评审。

> **迁移前必须完成一次演练并留存 manifest 与报告。**
> 缺少任何一项证据，本次迁移为 NO-GO。
