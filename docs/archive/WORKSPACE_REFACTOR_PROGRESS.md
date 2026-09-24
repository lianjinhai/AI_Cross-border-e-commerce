# Workspace Refactor Progress

> 更新日期：2026-09-22  
> 状态仅使用：TODO / IN_PROGRESS / BLOCKED / DONE / VERIFIED。

## 总体门禁

| 门禁 | 状态 | 说明 |
|---|---|---|
| 先审计后编码 | DONE | DEV-010 已完成只读审计 |
| 保留 Tenant 数据边界 | DONE | 确认 Tenant≈Workspace Boundary |
| 显式兼容迁移设计 | TODO | DEV-011 前置 |
| 多 Workspace 身份回归 | TODO | Membership 落地后验证 |
| A-G 浏览器 E2E | TODO | DEV-029 |

## DEV 任务

| 任务 | 状态 | 当前结论/依赖 |
|---|---|---|
| DEV-010 现有 User/Tenant/Role/Workspace 审计 | DONE | 审计与最小改造顺序已落盘；未改业务代码 |
| DEV-011 Workspace 领域抽象 | TODO | 依赖迁移前数据检查与兼容契约 |
| DEV-012 PERSONAL / ORGANIZATION 支持 | TODO | 依赖 DEV-011 |
| DEV-013 一个 User 多个 Workspace | TODO | 依赖 Membership 与认证双读 |
| DEV-014 Business Capability Profile | TODO | 依赖 Workspace 基座 |
| DEV-015 Business Stage | TODO | 依赖 Context 与真实状态规则 |
| DEV-016 新 Onboarding | TODO | 依赖 Profile/Stage API |
| DEV-017 Business Path | TODO | 依赖 Capability Profile |
| DEV-018 workspace-context API | TODO | 依赖 011-017 的读模型 |
| DEV-019 Workspace Switcher | TODO | 依赖服务端 switch 和 context |
| DEV-020 Guided / Professional Experience | TODO | 依赖 Context 与路径 |
| DEV-021 自适应 Dashboard | TODO | 复用现有 Professional KPI |
| DEV-022 一级导航治理 | TODO | 保留旧 URL；由服务端 navigation 驱动 |
| DEV-023 Supply / Market / Channel 概念治理 | TODO | P0：先隔离 source 销售订单同步 |
| DEV-024 Organization Role/Permission 兼容 | TODO | 依赖 Membership |
| DEV-025 Factory Collaborator 隔离 | TODO | 保留 Portal；扩展多关系和数据范围 |
| DEV-026 AI Copilot 接入 Workspace Context | TODO | 依赖统一指标和 Context |
| DEV-027 Opportunity User Fit | TODO | 复用 ProductScore，新增独立适配结果 |
| DEV-028 兼容迁移 | TODO | 每阶段显式 migration 与 rollback |
| DEV-029 E2E 测试 | TODO | 覆盖 A-G 及切换并发/缓存隔离 |

## 当前阻断项

| 项目 | 状态 | 说明 |
|---|---|---|
| Workspace-scoped Setting | TODO | P0：现有全局 key 需先盘点归属再迁移 |
| source/sales 订单边界 | TODO | P0：1688 source 可进入销售订单同步，需在个性化经营前修复 |
| superadmin tenant_id=0 | TODO | P1：PostgreSQL/显式 FK 下不兼容，需迁为平台身份 |

## 本轮变更记录

### DEV-010

1. 修改目标：完成 Workspace/Capability 重构前的真实代码审计；
2. 修改文件：仅文档；
3. 新增文件：`docs/WORKSPACE_CAPABILITY_REFACTOR_AUDIT.md`、本进度文件；
4. 数据库 Migration：无；
5. API 变化：无；
6. UI 变化：无；
7. 测试变化：无；
8. 已通过测试：本轮为只读审计，完成静态代码证据核对；
9. 未完成事项：DEV-011 至 DEV-029；
10. 风险：全局 Setting、source 订单污染、单 Tenant User、superadmin 0；
11. Acceptance Criteria：DEV-010 满足；整轮产品验收尚未满足；
12. 下一任务：DEV-011 的迁移前检查、领域契约与增量 Workspace 基座。
