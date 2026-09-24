# Phase 1 接口契约（Workspace Identity）

> 版本：1.0 ｜ 日期：2026-09-23 ｜ 状态：FROZEN（新增代码必须遵守）
> 上游依据：`docs/archive/phase1_migration_safety.md`、`docs/archive/WORKSPACE_CAPABILITY_REFACTOR_AUDIT.md`
> 冻结范围：Workspace Context Service 与 Context API。本文档变更需走评审。

## 0. 为什么要有这份契约

Phase 1 要把"一个用户固定属于一个租户"改造成"用户可加入多个 Workspace"。
改造期间新旧两套身份会并存，所以必须先冻结"谁读什么、按什么顺序读、读不到怎么办"，
否则各业务模块会各自实现一套授权，最终出现两套真相。

## 1. 术语

| 术语 | 含义 | 当前对应 |
|---|---|---|
| Workspace | 经营空间边界（数据隔离单位） | 现有 `tenants` 表 |
| Membership | 用户在某 Workspace 中的成员关系与角色 | 当前不存在，需新建 |
| Legacy Identity | 现有 `User.tenant_id` + `User.role` 单租户身份 | 现有 users 表 |
| Platform Identity | 平台服务商身份，不属于任何业务 Workspace | `role='superadmin'` |
| Factory Collaborator | 工厂门户协作身份，受限 Context | `role='supplier'` + SupplierPortalMember |
| Data Scope | 成员在 Workspace 内可见的数据范围 | 当前不存在，默认 WORKSPACE_ALL |

## 2. WorkspaceContext 数据契约

新增代码只能通过 `WorkspaceContext` 获取身份，不得直接读 `User.tenant_id` 或 `User.role`。

```python
@dataclass(frozen=True)
class WorkspaceContext:
    user_id: int                      # users.id
    username: str                     # 仅用于审计，不得写入日志
    display_name: str
    workspace_id: int | None          # 业务 Workspace；Platform Identity 为 None
    workspace_name: str
    workspace_kind: str               # ORGANIZATION / PERSONAL / FACTORY / PLATFORM
    membership_id: int | None         # 无 Membership 时为 None
    role: str                         # 见第 3 节角色枚举
    permissions: frozenset[str]       # 见第 4 节权限目录
    data_scope: str                   # 见第 5 节
    source: str                       # MEMBERSHIP / LEGACY_FALLBACK / PLATFORM / FACTORY
    is_impersonating: bool            # superadmin 代客访问
    trace_id: str                     # 每次请求生成，用于日志串联
```

`source` 语义（必须显式，禁止默认值猜测）：

- `MEMBERSHIP`：来自 ACTIVE WorkspaceMembership（目标态）；
- `LEGACY_FALLBACK`：来自 `User.tenant_id` + `User.role`（兼容期）；
- `PLATFORM`：Platform Identity，无业务 Workspace；
- `FACTORY`：Factory Collaborator，严格受限。

## 3. 角色枚举（冻结）

| 新角色 | 含义 | 由 legacy 映射而来 |
|---|---|---|
| `OWNER` | Workspace 所有者，可管理成员与配置 | `admin` |
| `OPERATOR` | 日常经营操作，可写业务数据 | `operator` |
| `READ_ONLY` | 只读观察 | `viewer` |
| `COMPLIANCE` | 合规审批，可写审批类动作 | `compliance_approver` |
| `PLATFORM_ADMIN` | 平台服务商，无业务 Workspace 数据权 | `superadmin` |
| `FACTORY_COLLABORATOR` | 工厂协作，仅限本厂资料 | `supplier` |

兼容规则：legacy 值大小写不敏感；`admin`/`owner` 均归一化为 `OWNER`；
未知值一律降级为 `READ_ONLY` 并产生一条结构化告警日志（不得静默放行）。

## 4. 权限目录（冻结 key，实现可分批）

命名规则：`<领域>:<动作>`，动作取值 `read` / `write` / `approve` / `admin`。

```
workspace:read          workspace:write        workspace:member:admin
product:read            product:write
supply:read             supply:write
listing:read            listing:write
order:read              order:write
finance:read            finance:write
purchase:read           purchase:write
settlement:read         settlement:write
refund:read             refund:write
compliance:read         compliance:approve
ai:read                 ai:write
platform:admin
```

角色 → 权限默认映射（Phase 1 基线，后续由 `role_permissions` 表承载）：

| 角色 | 权限 |
|---|---|
| `OWNER` | 全部业务权限 + `workspace:member:admin` |
| `OPERATOR` | 除 `workspace:member:admin` 与 `platform:admin` 外的业务权限 |
| `READ_ONLY` | 所有 `*:read` |
| `COMPLIANCE` | `compliance:read` + `compliance:approve` + `listing:read` + `product:read` |
| `PLATFORM_ADMIN` | 仅 `platform:admin` |
| `FACTORY_COLLABORATOR` | 仅 `supply:read` + `supply:write`（且受数据范围二次限制） |

## 5. Data Scope 枚举（冻结）

| 值 | 含义 |
|---|---|
| `WORKSPACE_ALL` | Workspace 内全部数据（默认） |
| `SHOP_SCOPED` | 仅授权店铺及其订单（预留，Phase 3 启用） |
| `SELF_ONLY` | 仅自己创建的数据（预留） |
| `FACTORY_SELF` | 仅本厂资料（Factory Collaborator 强制） |

Phase 1 只实现 `WORKSPACE_ALL` 与 `FACTORY_SELF`；其余值必须显式声明，禁止默认降级。

## 6. 读取顺序（冻结，双读期唯一合法顺序）

1. 若为 Platform Identity（superadmin 且未代客访问）→ `source=PLATFORM`，`workspace_id=None`，
   不得访问任何租户业务数据；
2. 若为 Factory Collaborator → 由 `SupplierPortalMember` 生成 `source=FACTORY` 受限 Context；
3. 若存在指定/活动 Workspace 的 `ACTIVE` Membership → `source=MEMBERSHIP`；
4. 否则若处于兼容窗口 → 由 `User.tenant_id` + `User.role` 生成 `source=LEGACY_FALLBACK`；
5. 以上皆无 → 401（未登录）或 403（无可用 Workspace），不得隐式放行。

每次 `LEGACY_FALLBACK` 必须产生一条结构化日志与计数指标。

## 7. 日志与 PII 红线

允许记录：`trace_id`、`user_id`、`legacy tenant_id`、`target workspace_id`、`source`、`reason`、`role`。

禁止记录：token、密码、password_hash、username、邮箱、手机号、店铺凭证、买家信息。

## 8. Context API 契约（P1-09）

全部挂在 `/api` 前缀下（与现有路由一致），两条路径必须调用同一 Service。

| 方法 | 路径 | 说明 | 状态码 |
|---|---|---|---|
| GET | `/api/me/workspaces` | 当前用户可访问的 Workspace 列表 | 200 |
| POST | `/api/me/workspaces/{workspace_id}/switch` | 切换活动 Workspace | 200 / 403 / 404 |
| GET | `/api/me/workspace-context` | 当前活动 Context 快照 | 200 |

响应字段（冻结）：

`GET /api/me/workspaces` → `{"items":[{"id":int,"name":str,"kind":str,"role":str,"source":str,"is_active":bool}],"total":int}`

`GET /api/me/workspace-context` → `{"user_id":int,"workspace_id":int|null,"workspace_name":str,"workspace_kind":str,"role":str,"permissions":[str],"data_scope":str,"source":str,"is_impersonating":bool,"trace_id":str}`

`POST .../switch` → `{"ok":true,"workspace_id":int,"role":str,"source":str}`；切换失败必须返回明确原因，禁止静默回退到旧 Workspace。

约束：

- 未登录 → 401；
- 请求的 workspace 不在可访问列表 → 403（存在但无权限）或 404（不存在）；
- Platform Identity 调用 `switch` → 403（平台身份无业务 Workspace）；
- Factory Collaborator 只能看到自己的 Factory Workspace。

## 9. 兼容期禁止事项

1. 禁止在业务模块新增 `User.tenant_id` 直读（新增代码必须走 Context）；
2. 禁止出现两套授权实现（同一判断只能有一处）；
3. 禁止把 `LEGACY_FALLBACK` 静默当作正常路径（必须有日志与指标）；
4. 禁止在本阶段修改 Product、Order、Finance、Factory 业务表结构；
5. 禁止未经备份与演练执行 DDL。

## 10. 验收标准

- `WorkspaceContext` 全部字段有类型与取值约束；
- 四种 `source` 各有单元测试覆盖；
- legacy 角色归一化与未知角色降级有测试；
- 双读顺序有测试，且 fallback 日志不含 PII；
- Context API 三端点行为符合第 8 节状态码表；
- 全量后端回归通过，主库 `erp.db` 未被修改。
