# ADR-0024：前端权限 fail-closed 降级

- **状态**：Accepted
- **决策编号**：[`DECISIONS.md` D24](../DECISIONS.md#L1351)
- **日期**：2026-09-24

## Context

Phase 1.8「删除旧逻辑入口」的最后一个阻塞项。`frontend/src/permissions.js` 保留
legacy `localStorage.erp_user` 兜底，此前它**会授予写权限**
（`LEGACY_CAPABILITIES` 手工维护的角色→权限表）。

**为什么不能直接删**：

- Context 请求可能失败（网络抖动、后端 5xx、F5 刷新瞬间）→ 直接删会让所有按钮消失；
- 而「Context 不可用 → 跳登录页」会引入**无限重定向环**：守卫的 `authenticated`
  只判 token 存在，后端 5xx 时 token 仍有效 → 跳 `/login` → `defaultLanding`
  弹回 `/dashboard` → **循环**。

同时存在一个安全语义问题：前端手工维护的兜底表**可被客户端伪造**——
伪造 `localStorage.erp_user.role` 即可让写按钮出现。

## Decision

**写权限 fail-closed，路由兜底保留**：

| 维度 | 处理 | 理由 |
|---|---|---|
| **写权限**（`canWrite`/`canAdmin`/`canApprove`/`can`） | ❌ **fail-closed**：Context 不可用时一律 `false`，`LEGACY_CAPABILITIES` **整体删除** | 写权限是安全边界，不能靠客户端兜底表授予 |
| **路由/菜单/展示**（`roleKey`/`routeRedirect`/`defaultLanding`） | ✅ **保留 legacy 兜底** | 否则 Context 故障时平台管理员与工厂账号会被弹到无权页面 |

**为什么这个切分是对的**：已核实 `can()` 在 8 个视图的用法**全部是写操作**
（`*:write` + `compliance:approve`），**无任何读权限依赖它** → fail-closed
不会导致「页面读不出来」，只会让写按钮消失，**正好等于「只读降级」**。

## Consequences

**收益**

- 前端不再持有第二份权限真相；伪造 localStorage 无法获得写权限；
- Context 故障时**优雅降级为只读**，而非白屏或重定向环。

**残留风险（显式记录，勿当已解决）**

伪造 `localStorage.erp_user.role` **仍能影响路由与菜单**（可进 `/platform-admin`
界面渲染，接口返回 403）。这是 A′ 方案的固有残留——路由兜底必须保留。

**属 UI 层问题，非数据越权**：后端独立鉴权已实测兜住——viewer 写商品 403、
viewer 读 `/api/admin/users` 404、viewer 进 `/api/admin/overview` 403、
viewer 代客进入 403。

**若后续要彻底去 legacy**：必须先为「Context 故障时的路由策略」单独设计
（例如显式「身份加载失败」页），**不能直接删 `routeRedirect` 兜底**。

## Alternatives considered

| 方案 | 否决理由 |
|---|---|
| **直接删除 legacy 兜底（A 方案）** | Context 故障时所有按钮消失；改跳登录页会引入无限重定向环 |
| **保留 legacy 兜底且继续授予写权限（原状）** | 写权限可被客户端伪造，安全边界形同虚设 |
| **Context 不可用 → 跳登录页** | 守卫 `authenticated` 只判 token 存在，后端 5xx 时 token 仍有效 → 无限重定向环；需同时改守卫契约 + 清 token + 加提示，代价远超收益 |
| **写权限与路由一起 fail-closed** | 会让平台管理员与工厂账号在 Context 故障时被弹到无权页面，体验更差 |

## References

- 权威源：[`DECISIONS.md` D24](../DECISIONS.md#L1351)（含 13 个断言变红的回退法验证）
- 相关决策：D15 / D23（Phase 1.8）、D25（代客身份序列化）、D26（Membership 写入侧）
- 规范：T-31（安全边界与体验兜底必须分开决策）、T-32（前端权限兜底表一律视为缺陷）