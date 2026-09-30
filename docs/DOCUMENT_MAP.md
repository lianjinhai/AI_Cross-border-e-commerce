# 文档地图（DOCUMENT_MAP）

> **本文件回答一个问题：我该读哪份文档？**
> 维护规则见 `docs/CODE_AND_DIRECTORY_STANDARD.md` §10（Doc-11）。
> **本文件的清单由 `backend/scripts/check_docs_consistency.py` 的 H 项强制校验**
> ——新增/删除文档后必须同步本表，否则 CI 变红。

---

## 1. 按「我要做什么」查找

| 我要…… | 先读 | 再读 |
|---|---|---|
| 了解项目全貌 | `README.md` | `docs/项目介绍与功能地图.md` |
| **动手写代码** | `AGENTS.md`（AI 助手）/ `CONTRIBUTING.md`（人类） | `docs/CODE_AND_DIRECTORY_STANDARD.md` |
| 开发 AI / Agent 能力 | `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md`（**强制先读**） | `docs/CONTRACT.md` |
| 改接口 | `docs/CONTRACT.md` | `docs/DECISIONS.md` |
| 改数据库 / 迁移 | `docs/CODE_AND_DIRECTORY_STANDARD.md` §7 | `docs/backup_restore_runbook.md` |
| 备份 / 恢复 | `docs/backup_restore_runbook.md` | — |
| 查某个决策的来龙去脉 | `docs/adr/README.md`（索引） | `docs/DECISIONS.md`（权威源） |
| 查历史进度 / 谁做过什么 | `docs/WORKSPACE_MIGRATION_PROGRESS.md` | `docs/子代理实施索引-<日期>.md` |
| 接续 Agent 写入迁移 | `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` §18.3.1 | `docs/DECISIONS.md` 最新决策与 `docs/子代理实施索引-20260930.md` |
| 找已归档的一次性报告 | `docs/archive/README.md` | — |

---

## 2. 活文档清单（`docs/` 根目录，全部须同步维护）

### 2.1 冻结契约类（**改动需走评审**）

| 文档 | 状态 | 作用 |
|---|---|---|
| `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` | **FROZEN**（2026-09-23） | Agent OS 架构 V1.0；后续 AI 能力开发必须遵循 |
| `docs/phase1_interfaces.md` | **FROZEN**（2026-09-23） | Workspace Context Service 与 Context API 接口契约 |
| `docs/CODE_AND_DIRECTORY_STANDARD.md` | 生效 | 代码与目录规范（**上位文档**，含债务台账 §11） |
| `docs/CONTRACT.md` | 生效 | 接口契约 |

### 2.2 权威事实源类

| 文档 | 状态 | 作用 |
|---|---|---|
| `docs/DECISIONS.md` | 活（追加式） | **架构决策唯一权威源**（ADR） |
| `docs/baseline.json` | 活（脚本生成） | **测试基线单一事实源**，禁止手工编辑 |
| `docs/adr/README.md` | 活（镜像层） | ADR 索引，权威源为 `DECISIONS.md` |

### 2.3 运维 / 进度类

| 文档 | 状态 | 作用 |
|---|---|---|
| `docs/backup_restore_runbook.md` | 生效 | 备份与恢复运维手册 |
| `docs/WORKSPACE_MIGRATION_PROGRESS.md` | 活 | Workspace 迁移进度与遗留项（R-*） |
| `docs/子代理实施索引-20260923.md` | 活（按日追加） | 子代理追溯索引（AGENTS.md §9 要求）；**文件名含日期，新增按日新建并在本表登记** |
| `docs/子代理实施索引-20260930.md` | 活（按日追加） | 总调度最小任务派发、精简交接、验证及资源归属记录；未完成记录保留 |

### 2.4 全景 / 参考类

| 文档 | 状态 | 作用 |
|---|---|---|
| `docs/项目介绍与功能地图.md` | 活 | 功能全景（模块、接口、能力清单） |
| `docs/需求分析与详细设计说明书V8.0.md` | 历史基线 | 原始需求与设计（Phase 0 输入） |

### 2.5 **方案 / 设计稿类（待实施，未定稿）**

> ⚠️ **本类文档不是规范，不构成约束**。它们是「论证中或已论证待实施」的方案，
> 实施后才升级为契约或并入既有文档。**读它们时务必先看文档顶部的「状态」行。**

| 文档 | 状态 | 作用 | 实施后去向 |
|---|---|---|---|
| `docs/页面操作权限对照表.md` | 实施依据 | 页面-操作-权限 key 对照（权威源为 `workspace_context.py` 的 `ROLE_PERMISSIONS`） | 保持（随权限矩阵同步） |
| `docs/phase1_setting_scope_design.md` | DESIGNED（**未执行 DDL**） | P1-10 Setting 作用域隔离设计 | 实施后并入 `phase1_interfaces.md` 或归档 |
| `docs/角色权限体系梳理方案.md` | 论证中 → 待定稿 | 角色与权限体系梳理 | 定稿后拆为规范 + 实施 |
| `docs/角色界面差异化设计方案.md` | **待论证** | 角色专属工作台设计（当前仅权限裁剪，无角色界面） | 论证后实施 |
| `docs/权限体系问题排查与专家探讨.md` | 排查记录 | 权限体系 4 个问题的排查与专家意见 | 问题修完后归档 |
| `docs/AI原生能力升级方案.md` | **待专家论证** | AI 能力升级（数据飞轮/主动智能/可解释决策） | 论证后按 Agent OS 架构实施 |
| `docs/M4客服知识自进化方案与论证.md` | 论证完成，**待实施**（P2，高风险） | 客服知识自动进化 | 实施后并入 Agent OS 或归档 |

---

## 3. 归档目录

`docs/archive/` 存放**一次性报告**（已完成使命、仅供追溯）。清单见
`docs/archive/README.md`。归档规则：`docs/CODE_AND_DIRECTORY_STANDARD.md` §10（Doc-2）。

---

## 4. 新增文档时怎么做

1. 判断类型：**活文档**（长期维护）还是**一次性报告**（完成后归档）？
2. 一次性报告 → 直接写进 `docs/archive/`，并在 `docs/archive/README.md` 登记。
3. 活文档 → 写进 `docs/` 根，并**在本文件第 2 节对应分类下补一行**（H 项会校验）。
4. 若该文档有「状态」（FROZEN / DESIGNED / 待论证），**必须在文档顶部显式声明**。
