# 归档索引

> 本目录存放**一次性报告**（已完成使命、仅供追溯）。活文档在 `docs/` 根目录。
> 归档规则见 `docs/CODE_AND_DIRECTORY_STANDARD.md` §10（Doc-2）。

## 归档清单

| 文件 | 类型 | 归档日期 | 说明 |
|---|---|---|---|
| `V9_1_AI_DEVELOPMENT_PROMPTS_2026-10-18.md` | 原型落地开发提示词 | 2026-10-18 | 10 张链鲸原型与现有 V9 源码映射、总开发提示词、分批指令与独立验收提示词 |
| `FRONTEND_DESIGN_AUDIT_2026-10-18.md` | 前端设计现状审查 | 2026-10-18 | V9 外壳、核心页面、源码确认问题及后续原型对照底稿；未做浏览器视觉验收 |
| `DEVELOPMENT_SUMMARY_2026-10-14.md` | 开发总结与交接快照 | 2026-10-14 | 当前代码/提交/历史验收分层，Launch 与 V9 成果、Agent 遗留、工作区增量及后续任务 |
| `final_architecture_assessment.md` | 架构评估报告 | 2026-09-23 | Phase 0 最终业务架构冻结依据（662 行） |
| `phase1_migration_safety.md` | 迁移安全分析 | 2026-09-23 | Phase 1.0 只读审计报告（457 行） |
| `phase1_migration_abc_design.md` | 迁移设计 | 2026-09-23 | Revision A/B/C 精确设计；**已执行完成** |
| `phase1_ledger_reconcile_report.md` | 根因分析报告 | 2026-09-23 | P1-03 账本漂移根因（suppliers 重复键 + 漏建唯一索引）；**已修复** |
| `WORKSPACE_CAPABILITY_REFACTOR_AUDIT.md` | 审计报告 | 2026-09-23 | Workspace 能力重构盘点（444 行） |
| `WORKSPACE_REFACTOR_PROGRESS.md` | 进度快照 | 2026-09-23 | 已被 `docs/WORKSPACE_MIGRATION_PROGRESS.md` 取代 |
| `production-gap-analysis.md` | 差距分析 | 2026-09-23 | 商用化差距盘点（289 行） |
| `PRODUCTION_READINESS_PROGRESS.md` | 进度快照 | 2026-09-23 | 已被活文档取代 |
| `全量商用化整改方案.md` | 整改方案 | 2026-09-23 | 整改方案（83 行） |
| `当前项目能力与后续开发报告-20260922.md` | 阶段报告 | 2026-09-23 | 2026-09-22 能力与后续开发（195 行） |
| `官方平台验收运行手册.md` | 操作手册 | 2026-09-23 | 官方平台验收操作（50 行） |
| `UI_REFACTOR_BLUEPRINT.md` | 设计蓝图 | 2026-09-23 | UI 重构蓝图（48 行） |
| `子代理实施索引-20260922.md` | 追溯索引 | 2026-09-23 | 2026-09-22 轮次子代理索引（17 行） |
| `20261001-D58-跨境成本与E2E验收.md` | 验收报告 | 2026-10-01 | D58 跨境到岸成本批次：预检契约精确化、E2E 通过与主库迁移验收 |

## 保留在 `docs/` 根的活文档

> ⚠️ **本清单已废止，改为单一来源**：活文档总索引见 [`docs/DOCUMENT_MAP.md`](../DOCUMENT_MAP.md)
> （按「我要做什么」与「文档状态」分类，并由 `check_docs_consistency.py` 的 H 项强制同步）。
>
> **废止原因**：本清单曾列 11 个活文档，而实际有 18 个（漏 7 个，含 4 份零引用文档）。
> 同一份信息维护在两个地方必然漂移——保留清单 = 保留漂移源。
