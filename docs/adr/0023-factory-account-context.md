# ADR-0023：工厂账号 Context 通道 —— 精确白名单

- **状态**：Accepted
- **决策编号**：[`DECISIONS.md` D23](../DECISIONS.md#L1251)
- **日期**：2026-09-24
- **修订关系**：修订 D15 §二/§六的前提（「工厂账号拿不到 Context」已不成立）

## Context

Phase 1.8 的「删除 legacy 入口」此前**暂缓**，理由写在 D15 第二节：
工厂账号拿不到 Context，删掉 legacy 兜底会让工厂门户直接不可用。

同时存在一个**真实的 fail-open 缺陷**：`build_factory_context()` 查询
`SupplierPortalMember` 时**只按 user_id 过滤、未校验 `status`**，而路由层
`_portal_scope` 一直带 `status == "active"`。

两条路径判定不一致 → **绑定停用后门户 API 拒绝（403），但 Context 仍宣称
`supply:read/supply:write`**。

**为什么这是缺陷而非小瑕疵**：

1. `/api/me/workspace-context` 现已对工厂开放，Context 是前端**权威**权限来源
   （`permissions.js` 的 legacy 仅兜底）→ 表现为「界面按钮可点、实际请求 403」；
2. `require_permission()` 的**后端鉴权**也以 Context 为权威判定路径
   （`auth.py:221-229`），**不只是显示问题**；
3. **MEMBERSHIP 路径一直带 `status='ACTIVE'`**（`_MEMBERSHIP_QUERY`），
   工厂路径是**唯一**漏检的分支——属实现疏漏，非有意设计。

## Decision

**放行只读端点，不放行写语义端点**。`app/auth.py` 原先 403 挡住工厂账号，
现改为**精确白名单**（`_FACTORY_SCOPE_PATHS`）：

| 路径 | 放行 | 理由 |
|---|---|---|
| `/api/factory-network/portal/*` | ✅ | 门户资料（原有） |
| `/api/auth/me` | ✅ | 原有 |
| `/api/me/workspaces` | ✅ **新增** | 只读：让工厂身份可被前端解析 |
| `/api/me/workspace-context` | ✅ **新增** | 只读：Context 权威源 |
| `/api/me/workspaces/{id}/switch` | ❌ **刻意拒绝** | **写语义**（审计 + 未来持久化）；工厂的活动 Workspace 由 `SupplierPortalMember` 唯一确定，**不存在可切换的第二个 Workspace**，放行只会扩大攻击面 |

**同时修复 fail-open**：补 `status == "active"`，停用绑定的处理与「未绑定」一致
（`permissions=∅`、`workspace_id=None`），仍可访问门户自身资料。

**为什么用精确白名单而不是前缀匹配**：`path.startswith("/api/me/")` 会把
`/switch` 一并放行。这不是假想风险——回退法实测（把白名单改成前缀匹配）
立刻被 `test_factory_portal_account_reaches_read_only_context` 抓住。

## Consequences

**收益**

- Phase 1.8「删除旧入口」的**阻塞项已清除**；
- 工厂身份的权限判定在 Router 与 Service 两层**一致**；
- 停用绑定不再授予任何权限。

**代价 / 残留**

- **legacy 兜底仍不能删**，但理由已变：原「工厂拿不到 Context」已解决，
  现为「**Context 请求可能失败**」（网络抖动、后端 5xx、F5 刷新瞬间）——
  否则这些场景下所有按钮会消失；
- 剩余工作是把兜底从「身份来源之一」降级为「异常降级路径」，建议在 Phase 2
  与 Agent Tool Layer 一起做（两者都涉及权限判定入口的统一）。

## Alternatives considered

| 方案 | 否决理由 |
|---|---|
| **前缀匹配 `startswith("/api/me/")`** | 会把 `/switch`（写语义）一并放行；回退法实测确认被抓 |
| **继续对工厂账号 403 挡住 `/api/me/*`** | Phase 1.8 无法推进，工厂门户不可用 |
| **放行 `/switch`** | 工厂不存在可切换的第二个 Workspace，放行只扩大攻击面 |
| **只修 Context 放行、不修 fail-open** | 停用绑定仍会宣称写权限，属真实安全缺陷 |

## References

- 权威源：[`DECISIONS.md` D23](../DECISIONS.md#L1251)（含端到端真实链路输出与回退法验证表）
- 相关决策：D15（Phase 1.8 优先级与 legacy 保留依据，前提由本决策修订）、
  D24（legacy 兜底降级为只读）
- 契约：`docs/phase1_interfaces.md` §6/§7
- 规范：T-22（白名单必须精确匹配）、T-23（同实体跨层查询条件必须一致）