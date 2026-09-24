# 贡献指南（CONTRIBUTING.md）

> **本文件写给「人」；写给 AI 助手的协作规范在 [`AGENTS.md`](AGENTS.md)。**
> 两者互补：`AGENTS.md` 侧重红线与约束，本文件侧重**环境搭建、开发循环、调试与评审流程**。
> 代码与目录的**上位规范**是 [`docs/CODE_AND_DIRECTORY_STANDARD.md`](docs/CODE_AND_DIRECTORY_STANDARD.md)，
> 与本文件冲突时**以它为准**。

**最后更新**：2026-09-24　**状态**：生效

---

## 1. 环境要求

| 项 | 要求 | 备注 |
|---|---|---|
| Python | **3.11+** | 开发机实测 3.11.6；CI 固定 `3.11` |
| Node | **18+** | CI 固定 `20`；开发机实测 v22.16.0 / npm 10.9.2 |
| Git | 必需 | 当前**唯一**回滚手段（见 §7） |
| Docker | 可选 | 仅当你要验证生产镜像或 HTTPS 链路 |

不强制虚拟环境（本机开发一直用全局 Python）。如需隔离，自建 venv 后按 §2 重装依赖；
`.venv/`、`venv/` 已在 `.gitignore` 中。

> 本项目在 **Windows + PowerShell** 上开发，有若干真实踩过的坑，见 §10。

---

## 2. 首次搭建

```powershell
cd AI-电商ERP

# 1) 后端依赖：用锁定清单，与 CI / Docker 镜像完全一致（D-9）
cd backend
pip install -r requirements-dev.lock.txt

# 2) 前端依赖 + 构建（后端会托管 frontend/dist）
cd ../frontend
npm install
npm run build

# 3) 启动（首次启动自动建库 + 灌入确定性演示数据）
cd ../backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 **http://127.0.0.1:8000**，用演示账号登录：`admin` / `admin123`（管理员）、
`ops` / `ops123`（运营）、`viewer` / `viewer123`（只读）。

**前后端分离开发**（前端热更新）：

```powershell
cd backend  ; python -m uvicorn app.main:app --port 8000   # API
cd frontend ; npm run dev                                  # http://localhost:5173
```

`frontend/vite.config.js` 已把 `/api` 代理到 `http://127.0.0.1:8000`，无需额外配置。

- 数据库：`backend/erp.db`（SQLite），由 `app/seed.py` 自动建库并灌演示数据。
  该文件**不入库**，删掉即可重建。
- 大模型**可选**：不配 `ERP_LLM_API_KEY` 时全部 Agent 走确定性规则引擎，功能完整可用（D3）。
  变量清单见 `.env.example`。

---

## 3. 开发循环

```powershell
# ① 改代码

# ② 先跑最相关的测试文件（快）
cd backend
python -m pytest tests/test_security.py -q

# ③ 跑全量后端测试（基线见 §4）
python -m pytest -q

# ④ 反序再跑一遍（D16 强制自检项：顺序依赖是「单跑绿、全量红」的唯一根因）
$files = Get-ChildItem tests\test_*.py | Sort-Object Name -Descending |
         ForEach-Object { "tests/" + $_.Name }
python -m pytest @files -q

# ⑤ 静态检查（只检查，不改动）
python -m ruff check .
```

改动前端时：

```powershell
cd frontend
npm run test:watch     # 开发期持续跑
npm test               # 提交前跑一次全量（vitest run）
npm run build          # 提交前必须构建成功
```

提交前先 `git add --dry-run .` 核对没有 `.db` / 冷备 / 日志 / 临时脚本混入（§7）。

---

## 4. 测试基线

**当前基线以 `docs/baseline.json` 为单一事实源**（由 `backend/scripts/refresh_test_baseline.py`
从真实测试采集，**禁止手工编辑该文件**）：

| 项 | 基线 | 命令 |
|---|---|---|
| 后端 | 见 `docs/baseline.json` 的 `backend.tests`（正序与反序均应一致） | `cd backend && python -m pytest -q` |
| 前端 | 见 `docs/baseline.json` 的 `frontend.tests` | `cd frontend && npm test` |
| 静态检查 | All checks passed | `cd backend && python -m ruff check .` |

**任何提交不得低于此基线。** 施工导致用例数变化时：

1. 运行 `cd backend && python scripts/refresh_test_baseline.py` 更新事实源；
2. 运行 `python scripts/check_docs_consistency.py` 确认文档无漂移（CI 也会拦）。

> **为什么改成引用而非直接写数字**：此前基线数字手工维护在 6 个文档里，实测
> **同时过期且互不一致**——同一时点并存 199 / 257 / 264 / 179 / 165 五个不同的
> 「当前基线」，真实值是 291。人工抄写必然漂移且无人察觉（数字看起来都合理）。
> 收敛到单一事实源 + 自动校验后才可能长期保持一致（见规范 §10 Doc-5）。

铁律（完整规则见规范 §8 的 `T-*` 编号）：

- **禁止为让测试通过而放宽断言**（T-4）。断言必须能在被测代码出错时失败；
  `>= 0`、空集合上的 `all(...)`、`try/except: pass` 都属恒真断言（T-8）。
- 新增业务能力必带测试；修 Bug **先写能复现的失败测试**（T-1）。
- 新增回归测试必须用「**临时回退修复 → 确认测试失败 → 恢复**」证明判别力（T-11）；
  变异时**只改被测逻辑、保留守护断言**（T-14）——两者一起改等于自己拆掉报警器。
- 涉及权限/租户隔离 → 同步更新 `backend/tests/test_security.py` 的权限矩阵（T-3）。
- 涉及数据库结构 → 同步更新 `backend/tests/test_migration_preflight.py`（T-5）。
- 测试**禁止**在业务库建 `schedules` 记录（T-17）；任何删库路径必须过
  `conftest.py::_guard_test_db_path`（T-10）。
- 需要全量数据时**分页遍历**（`fetch_all`），禁止用大 `page_size` 一把梭（T-15）。

测试库默认 `backend/test_erp_<pid>.db`（进程隔离，可并行跑）；需要固定名时：

```powershell
$env:ERP_TEST_DB='test_erp_worker2.db'; python -m pytest -q
```

---

## 5. 数据库与迁移

结构变更**必须**走 Alembic 迁移，禁止手工改表（M-1）。

```powershell
cd backend

# ① 冷备（动主库数据前必做；正式迁移的备份放项目外受控目录）
python scripts\backup_restore_drill.py backup --db erp.db --out-dir D:\phase1-backups\20260924-HHMMSS

# ② 验证备份（退出码 0 才算通过）
python scripts\backup_restore_drill.py verify --backup D:\phase1-backups\20260924-HHMMSS\erp-20260924-HHMMSS.db

# ③ 预检（12 项，只读；P0 未清零不得执行 DDL）
python scripts\migration_preflight.py

# ④ 新增迁移：手写 migrations/versions/20260924_NN_<主题>.py
#    命名与 revision 保持一致；头部写法参考目录内最近一篇

# ⑤ 执行（脚本先自动生成带时间戳的 .bak-* 备份，再升级到 head）
python scripts\migrate.py

# ⑥ 复验
python scripts\migration_preflight.py
python scripts\e2e_feasibility.py
```

硬约束：

- 迁移文件**只增不改**；已执行的迁移禁止编辑（含改注释）。唯一例外是 D9，**已用完**。
- 每个迁移必须实现可用的 `downgrade()`；无法回滚必须写明原因（M-3）。
- 回填类迁移必须**幂等**并带硬性断言（M-4）。
- 禁止在迁移中 import `app.models`（M-6），用原生 SQL 或 `sa.table()`。
- 新增含 `tenant_id` 的表必须同时声明 `tenant_id → tenants.id` 外键（M-7）。
- **WAL 陷阱**（M-9）：只比文件哈希**不能**证明数据没变，必须同时比行数；
  从冷备恢复时必须把 `erp.db` + `erp.db-wal` + `erp.db-shm` **一起删**，
  否则残留 WAL 回放会把被污染的数据「复活」进来。
- 备份/恢复的完整步骤与退出码约定见 [`docs/backup_restore_runbook.md`](docs/backup_restore_runbook.md)。

---

## 6. 代码规范

完整规范见 [`docs/CODE_AND_DIRECTORY_STANDARD.md`](docs/CODE_AND_DIRECTORY_STANDARD.md)。
以下是最高频的几条：

**依赖方向**（规范 §3，红线）：

```
routers/ → agents/ → tools/ → services/ → models.py
```

- `services/` **禁止** import `routers/`（L-1）
- `agents/` **禁止** import `routers/`（L-2）
- `agents/` **禁止** import 其他 `agents/`（L-3：禁止 Agent 之间 P2P 调用，
  只能由 Orchestrator 编排）
- 禁止用函数体内延迟 import 掩盖循环依赖；确需延迟导入必须写明原因（L-6）

**规模阈值**（规范 §5）：

| 类型 | 警戒线 | 硬上限 |
|---|---|---|
| Python 模块 | 300 行 | 500 行 |
| Python 函数 | 50 行 | 80 行 |
| Vue 单文件组件 | 300 行 | 400 行 |
| 测试文件 | 400 行 | 600 行 |

`app/models.py` 是**唯一例外**（允许更长，但必须保持纯定义，禁止混入业务逻辑）。

**其它高频约束**：

- **禁止裸 `except:`**；捕获必须记录或转换（S-5）。面向用户的错误信息用中文（S-6）。
- UTF-8 无 BOM；中文注释与中文用户提示一律保留（S-3）。
- 导入分组：标准库 → 第三方 → 本地，组间空行；禁止 `import *`（S-2）。
- **依赖锁定规则**（D-9）：`requirements*.txt` 是**声明**，`requirements*.lock.txt` 是**锁定**。
  新增/升级依赖 → 改声明 → 重新生成锁文件 → **重跑全量测试** → 才提交。
  禁止手工编辑锁文件；锁文件首行 `# -*- coding: utf-8 -*-` **不可删**（旧版 pip 在中文
  Windows 上按 GBK 解码会直接崩溃）。
- `pytest` / `ruff` 只属开发依赖，**禁止**放回运行时声明（会把测试框架装进生产镜像）。

**目录纪律**（规范 §2.1）：`app/` 内禁止出现数据库文件/日志/临时脚本（D-1）；
运维脚本一律放 `backend/scripts/`（D-2）；本地业务库唯一为 `backend/erp.db`（D-3）；
一次性报告放 `docs/archive/`（D-4）。

---

## 7. 提交规范

**提交信息格式**：`<域>: <动作> <对象>`，例如：

```
workspace: 修复 superadmin 越权写入
auth: 修代客态 /api/auth/me 500
docs: D24/D25/D26 决策记录 + T-24~T-32 规范
```

域取业务域（`workspace` / `auth` / `orders` / `docs` / `infra` 等），动作用动词，对象说清改了什么。

**分支**：主干 `main`。当前仓库**尚无远端**（`git remote -v` 为空），本地提交即唯一回滚手段。
建立远端后建议：`main` 受保护，改动走短分支 + PR。CI 配置见 `.github/workflows/ci.yml`，
push/PR 自动跑后端 `ruff check` + `pytest`、前端 `npm test` + `npm run build`。

**禁止提交**（`.gitignore` 已覆盖，仍需自查）：

- 数据库与旁文件：`*.db`、`*.db-wal`、`*.db-shm`、`*.db-journal`、`*.db.bak-*`
- 依赖与构建产物：`node_modules/`、`dist/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`
- 环境与密钥：`.env`、`.env.*`（`.env.example` 例外）
- 冷备与临时脚本：`backend/backups/`、`_erp_backups/`、`_wip_backup/`、根目录 `_*.py`
- 编辑残留：`*.orig`、`*.bak`、`*.rej`；Windows 垃圾文件 `nul`

---

## 8. 提交前检查清单

**完整清单是 [`AGENTS.md`](AGENTS.md) §10 与规范 §12**（唯一权威，本文件不复制以免漂移）。
人视角的最小自检：

- [ ] 相关测试 + 全量测试 + **反序测试**全绿，且不低于 §4 基线
- [ ] `python -m ruff check .` 全绿
- [ ] 改了前端 → `npm test` 与 `npm run build` 都过
- [ ] 改了结构 → 迁移 `downgrade()` 可用，`migration_preflight.py` 12 项全 PASS
- [ ] 改了权限/租户 → `test_security.py` 权限矩阵已更新
- [ ] 涉及「可运行/可部署」结论 → 真跑 `scripts/e2e_feasibility.py`
      （改 Docker 加跑 `docker_feasibility.py`；改 TLS/代理加跑 `tls_feasibility.py`）
- [ ] `git add --dry-run .` 无 `.db` / 冷备 / 日志 / 临时脚本
- [ ] 偏离规范之处已在 `docs/DECISIONS.md` 记录
- [ ] 相关文档已同步（`docs/CONTRACT.md`、Agent OS 架构、规范本身）

---

## 9. 遇到问题怎么查

| 我想知道 | 看哪里 |
|---|---|
| 项目定位、功能全景 | `README.md`、`docs/项目介绍与功能地图.md` |
| 代码与目录规范、全部 `T-*` / `M-*` / `S-*` 编号 | `docs/CODE_AND_DIRECTORY_STANDARD.md` |
| 「为什么当初这样决定」 | `docs/DECISIONS.md`（**权威源**）；快速索引 `docs/adr/README.md` |
| 接口契约（数据模型 / Agent 签名 / API） | `docs/CONTRACT.md` |
| 备份、恢复、真实回滚步骤 | `docs/backup_restore_runbook.md` |
| Workspace 身份迁移进度 | `docs/WORKSPACE_MIGRATION_PROGRESS.md` |
| 怎么加 AI 能力（Agent / Orchestrator / Action） | `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md`（**动 AI 前必读**） |
| 已知债务与整改时机 | `docs/CODE_AND_DIRECTORY_STANDARD.md` §11 台账 |
| 历史一次性报告 | `docs/archive/`（索引见其 `README.md`） |

调试提示：

- **服务起不来**：先看生产门禁报错 `validate_production_settings()`——生产模式要求
  JWT 密钥 ≥32 字节、非默认管理员口令、`ERP_CREDENTIAL_KEY`、明确 CORS 白名单，
  并显式声明 TLS 终止位置（`ERP_TRUST_PROXY_HEADERS=1` 或 `ERP_TLS_TERMINATED_ELSEWHERE=1`）。
- **「单跑绿、全量红」**：顺序依赖，按 §3 第 ④ 步反序复现。
- **测试库冲突 / 想并行跑**：用 `ERP_TEST_DB` 指定独立库名。
- **主库出现异常调度**：检查 `schedules.enabled`——残留任务会持续运行，
  不会被「不查询」规避（T-17 / D20）。

---

## 10. Windows 特有陷阱

以下每一条都是本项目真实踩过的坑：

1. **行尾必须是 LF**。`.gitattributes` 已锁 `* text=auto eol=lf`，但本机
   `git config core.autocrlf=true`；`docker-entrypoint.sh` 一旦变成 CRLF，
   容器启动直接报 `bad interpreter: /bin/sh^M`。改完文件可自查：

   ```powershell
   $t = [System.IO.File]::ReadAllText('路径'); $t.Contains("`r`n")
   ```

   若为 `True`，用 ``-replace "`r`n","`n"`` 归一后 `[System.IO.File]::WriteAllText(...)`
   写回（默认 UTF-8 无 BOM）。`*.bat` / `*.cmd` / `*.ps1` 例外，保持 CRLF。

2. **写 markdown 时，PowerShell 会把反引号当转义符吃掉**。这是本项目**潜伏最久**的
   事故（从首次提交起 20 轮未发现）：在 PowerShell 双引号字符串里，`` `r `` 是回车、
   `` `n `` 是换行、`` `e `` 是 ESC(0x1B)、三个反引号会被压成一个。实测后果：

   - 4 个文档共 **18 处代码围栏**从 `` ``` `` 塌缩成 `` ` ``；
   - 3 个标识符被吃掉首字符：`roleKey`→`oleKey`、`routeRedirect`→`outeRedirect`、
     `erp_user.role`→`rp_user.role`，并残留一个不可见 ESC 字符；
   - `DECISIONS.md` 里 `D:\nodejs\node.exe` 被撕成 3 行。

   **规则**：写文档一律用 `[System.IO.File]::WriteAllText`（单引号 here-string），
   或在 Python 里用 `write_bytes`。**禁止**用 PowerShell 双引号字符串拼 markdown。

3. **Python 的 `write_text` 在 Windows 上会把 `\n` 写成 CRLF**。默认
   `newline=None` 会做翻译，而仓库 `.gitattributes` 锁 `eol=lf`。写文件时必须显式
   `newline="\n"`（或写完用 `write_bytes` 归一），否则每次编辑都污染整个文件行尾。

4. **丢弃输出用 `> $null`，不要用 `> nul`**。PowerShell 会把 `nul` 当普通文件名，
   生成垃圾文件 `nul`（`.gitignore` 里专门列了它）。

5. **子进程必须显式 `encoding="utf-8"`**。Windows 默认按 GBK 解码子进程输出，
   读中文日志会直接抛 `UnicodeDecodeError`。

6. **管道会吃掉退出码**。`... | Select-String ...` 之后 `$LASTEXITCODE` 不可靠；
   先重定向到文件（`> log.txt 2>&1`）再读 `$LASTEXITCODE`。

7. **读中文输出**：设 `$env:PYTHONIOENCODING='utf-8'`，读文件加 `-Encoding UTF8`。

8. **SQLite 旁文件**：脚本异常退出会留下 `-wal` / `-shm`；清理时三个文件一起删（M-9）。

---

## 附：本文件与其它文档的关系

| 文档 | 读者 | 内容 |
|---|---|---|
| **本文件** | 人 | 环境搭建、开发循环、调试、提交与评审流程 |
| [`AGENTS.md`](AGENTS.md) | AI 助手 | 协作红线、开工前必做、子代理协作、检查清单 |
| [`docs/CODE_AND_DIRECTORY_STANDARD.md`](docs/CODE_AND_DIRECTORY_STANDARD.md) | 两者 | 代码与目录的**上位规范**（唯一权威） |

**最后更新**：2026-09-24　**状态**：生效
