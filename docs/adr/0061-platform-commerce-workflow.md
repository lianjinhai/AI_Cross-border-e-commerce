# ADR-0061：平台商品生命周期增量编排

状态：Accepted（设计冻结，功能未验收）。日期：2026-10-11。

## Context

现有发布任务无法完整表达多店铺独立进度、外部审核、核价、合规材料和在售核验。用户 V2 要求保留现有 ERP 与身份、Agent OS 冻结边界。

## Decision

复用 Workflow 三表，通过 flow_kind 隔离旧任务；Profile 发布后不可变。确定性引擎计算合法动作，AI 建议经现有 Action 门禁执行。执行、平台、验证三类状态独立，HTTP 成功不能直接成为 ACTIVE。

Shop 与店铺派生 Listing 管理独立销售对象。按需求增量加入素材、核价、备货、事件事实，状态和事件同事务。Guided/Professional 共用页面、DTO 和权限。

## Consequences

必须新增迁移、旧流程恢复隔离和 P0 回归；只在隔离副本演练。历史图片、发布结果和证据不会自动变为可信。Temu 样本为 CONTRACT_TEST/UNVERIFIED，真实联调另需授权。

## Alternatives

拒绝另建 ERP、在 Adapter 或 Vue 硬编码生命周期、让 AI 直接维护状态。

## References

唯一权威源：[D61](../DECISIONS.md#L3419)。详细设计：[领域架构](../PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md)、[状态模型](../PLATFORM_WORKFLOW_STATE_MODEL.md)。本文件不构成实施或运行验收证据。
