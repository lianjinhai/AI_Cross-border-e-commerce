# AGENTS.md — AI-电商ERP 项目协作规范

> 本文件是本仓库的**统一入口**，对所有在本项目工作的 AI 助手与开发者生效。
> 完整规范见 `docs/CODE_AND_DIRECTORY_STANDARD.md`；Agent 层架构见 `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md`。

## 0. 沟通约定

1. **默认使用中文回答**。涉及代码或命令时，先用大白话说明目的，再给具体操作。
2. 修改文件、运行命令、访问外部账号前，**先说明风险**。
3. 需求信息不完整时**先问缺什么**，不要自行编造。

## 1. 项目速览

- **定位**：AI 原生跨境电商经营平台（不是聊天机器人，是经营操作系统）。
- **后端**：Python 3.11 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + PyJWT + Alembic，数据库 SQLite（`backend/erp.db`，可切 MySQL/PG）。
- **前端**：Vue3 + Vite + Element Plus + ECharts + axios，测试用 vitest。
- **入口**：`backend/app/main.py`（FastAPI + 静态托管前端构建产物）。

### 常用命令

```bash
# 后端测试（基线见 docs/baseline.json）
cd backend && python -m pytest -q

# 前端测试（基线见 docs/baseline.json）与构建
cd frontend && npm test && npm run build

# 启动服务（开发）
cd backend && python -m uvicorn app.main:app --port 8000

# 代码检查（只检查不改动）
cd backend && python -m ruff check .

# 端到端可行性验证（真启动服务 + 隔离性校验，不碰主库）
cd backend && python scripts/e2e_feasibility.py

# Docker 生产镜像可行性验证（真构建 + 真运行 + 真登录，需 docker）
cd backend && python scripts/docker_feasibility.py

# HTTPS 链路可行性验证（真 Caddy + 真应用容器，8 项；离线可用自签证书）
cd backend && python scripts/tls_feasibility.py
```

## 2. 开工前必做

| 场景 | 必做动作 |
|---|---|
| 任何开发任务 | 确认工作区可回溯（见 §3 版本控制） |
| 改数据库结构 | 走 Alembic 迁移；先跑 `python scripts/migration_preflight.py` |
| 改权限/租户逻辑 | 同步更新 `backend/tests/test_security.py` 的权限矩阵 |
| 动主库数据 | **先冷备**（`python scripts/backup_restore_drill.py backup --db erp.db`），再执行，执行后立即校验 |
| 备份/恢复 | 遵循 `docs/backup_restore_runbook.md` |

## 3. 版本控制（P0）

**仓库已纳入 Git**（2026-09-24 首次提交 `6215d49`，分支 `main`）。`.gitignore` 与 CI 均已生效。

- 任务开始前必须确认有可用的回滚手段（Git 提交；涉及主库数据时仍须**先冷备**）。
- **禁止**提交：`*.db`、`node_modules/`、`dist/`、`__pycache__/`、`.pytest_cache/`、`.env`、`.zcode/`、`nul`。
- 冷备目录（`backend/backups/`、`_erp_backups/`）与根目录 `_*.py` 临时脚本**禁止**入库，已由 `.gitignore` 覆盖。
- 行尾由 `.gitattributes` 统一为 LF；`docker-entrypoint.sh` 等脚本若变成 CRLF，容器会报 `bad interpreter`。
- 提交信息：`<域>: <动作> <对象>`，例如 `workspace: 修复 superadmin 越权写入`。

## 4. 分层与依赖红线

```
routers/ -> agents/ -> tools/ -> services/ -> models.py
```

| 红线 | 内容 |
|---|---|
| L-1 | `services/` **禁止** import `routers/` |
| L-2 | `agents/` **禁止** import `routers/` |
| L-3 | `agents/` **禁止** import 其他 `agents/`（禁止 Agent 之间 P2P 调用，只能由 Orchestrator 编排） |
| L-6 | **禁止**用函数体内延迟 import 掩盖循环依赖；确需延迟导入必须写明原因 |

**Agent 层额外红线**（详见 Agent OS 架构文档 §3）：

1. 禁止临时创建 Agent；
2. 禁止 Agent 之间自由调用；
3. 禁止 Agent 直接操作数据库；
4. 禁止 Agent 绕过权限执行动作；
5. 禁止用聊天机器人代替 Agent 系统。

## 5. 目录纪律

| 编号 | 规则 |
|---|---|
| D-1 | `app/` 内禁止出现数据库文件、日志、临时脚本 |
| D-2 | 运维脚本一律放 `backend/scripts/` |
| D-3 | 本地数据库只有 `backend/erp.db`；禁止在 `backend/` 根目录新增其他 `.db` |
| D-4 | 一次性报告放 `docs/archive/`，活文档留 `docs/` 根 |
| D-5 | 生成物必须先写进 `.gitignore` + `.dockerignore`，再产生文件 |
| G-2 | 丢弃输出用 `> $null`，**不要**用 `> nul`（Windows 会生成垃圾文件） |

## 6. 代码规范要点

- **规模**：Python 模块警戒 300 行 / 硬上限 500 行；函数警戒 50 / 上限 80；Vue 组件警戒 300 / 上限 400。`models.py` 例外（允许更长但必须纯定义）。
- **命名**：模块 `snake_case`、类 `PascalCase`、常量 `UPPER_SNAKE`、私有成员 `_prefix`。
- **导入**：标准库 -> 第三方 -> 本地，组间空行；禁止 `import *`。
- **异常**：禁止裸 `except:`；捕获必须记录或转换。
- **编码**：UTF-8 无 BOM；中文注释与中文用户提示一律保留。
- **测试**：新增能力必带测试；**禁止为让测试通过而放宽断言**。

## 7. 数据库与迁移

1. 所有结构变更走 Alembic，**迁移文件只增不改**（已执行的禁止编辑）。
2. 每个迁移必须实现可用的 `downgrade()`；无法回滚要写明原因。
3. 回填类迁移必须**幂等**并带硬性断言。
4. 执行前：冷备 + `scripts/migration_preflight.py`；**P0 未清零不得执行**。
5. 迁移中禁止 import `app.models`。
6. 新增含 `tenant_id` 的表必须同时声明 `tenant_id` 到 `tenants.id` 的外键。
7. 新增 AI 能力禁止直接建表，须走 Agent OS 架构 §9 的 Action 模型。

## 8. Agent / AI 能力开发

开发任何 AI 能力前，**必须先读** `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md`（已冻结 V1.0）：

- 采用 8 个**领域能力 Agent**，禁止「老板 Agent / 运营 Agent / 采购 Agent」式员工角色建模；
- 所有 Agent 调用必须经 Orchestrator；Planner 负责拆解，输出 Task Graph；
- Agent 不得直接改业务数据，必须生成 AI Action，经 Policy / Permission / Risk / Approval 四道闸；
- 每次运行必须携带 Workspace Context（`workspace_id`、`workspace_type`、`user_id`、`permissions`、`data_scope`、`capability_profile`、`business_stage`）；
- 禁止无上下文 Agent。

## 9. 子代理协作

1. 子代理任务完成后，**只向主会话交接精简总结**：完成事项、关键结论、修改文件、验证结果、遗留风险、下一步。
2. 不要把完整推理、重复上下文或大段工具输出写入交接。
3. 子代理明确完成后必须先交接总结；主代理确认总结已写入索引后，应清理该子代理的完整过程记录。
4. 清理前保留可追溯索引（子代理 ID、父任务 ID、任务标题、最终总结、修改文件、验证结果、遗留事项）。
5. **仍为 open、未完成、无总结、交接失败或状态不明的子代理一律保留**；不得仅凭「长时间未更新」或「体积较大」删除。
6. 主任务正文、最终总结、未完成事项和必要索引必须保留。
7. 子代理追溯索引统一维护在 `docs/子代理实施索引-<日期>.md`。

## 10. 提交前检查清单

- [ ] 无 `.db` / 日志 / 临时文件进入仓库
- [ ] 未越层放置文件；依赖方向符合 §4 红线
- [ ] 文件与函数规模未超阈值
- [ ] 结构变更走迁移且 `downgrade()` 可用
- [ ] 新增能力带测试；权限改动已更新权限矩阵
- [ ] `pytest -q` 不低于 `docs/baseline.json` 的后端基线（反序跑同样）；`npm test` 不低于其前端基线；`ruff check` 全绿
- [ ] 涉及「可运行/可部署」结论时，已跑 `scripts/e2e_feasibility.py` 且全 PASS（T-13）
- [ ] 涉及容器 / TLS / 代理配置改动时，已跑 `scripts/docker_feasibility.py`（12 项）与 `scripts/tls_feasibility.py`（8 项）
- [ ] 改动构建链路（Dockerfile / 依赖文件 / .gitattributes / 入口脚本）后，已跑 `scripts/docker_feasibility.py` 且全 PASS（DP-1）
- [ ] 工作区已提交（§3）；提交前用 `git add --dry-run` 核对无 `.db` / 冷备 / 日志 / 临时脚本混入
- [ ] 偏离规范的实现已在 `docs/DECISIONS.md` 记录
- [ ] 相关文档已同步

## 11. 关键文档索引

| 文档 | 用途 |
|---|---|
| `docs/DOCUMENT_MAP.md` | **文档地图：我该读哪份文档？**（活文档 / 方案稿 / 归档总索引，H 项强制同步） |
| `docs/CODE_AND_DIRECTORY_STANDARD.md` | **代码与目录规范（本文件的上位文档）** |
| `CONTRIBUTING.md` | **面向人类开发者**的贡献指南（环境搭建 / 开发循环 / 迁移流程 / Windows 陷阱）；本文件面向 AI 助手，两者互补 |
| `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` | Agent 操作系统架构冻结 V1.0 |
| `docs/CONTRACT.md` | 接口契约 |
| `docs/DECISIONS.md` | 架构决策记录（ADR） |
| `docs/adr/README.md` | ADR 镜像/索引层（权威源为 `DECISIONS.md`；含全量 D 编号索引与状态定义） |
| `docs/backup_restore_runbook.md` | 备份与恢复运维手册 |
| `docs/WORKSPACE_MIGRATION_PROGRESS.md` | Workspace 迁移进度 |
| `docs/项目介绍与功能地图.md` | 功能全景 |
