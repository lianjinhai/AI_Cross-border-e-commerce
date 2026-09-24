# ADR-0007：店铺删除语义 —— 归档式软删除

- **状态**：Accepted
- **决策编号**：[`DECISIONS.md` D7](../DECISIONS.md#L79)
- **日期**：2026-09-23

## Context

`app/db.py` 开启 SQLite 外键强制（`PRAGMA foreign_keys=ON`）后，
`DELETE /api/shops/{id}` **立刻暴露为 500**。

实测有 **5 张表**引用 `shops.id`：

| 引用表 | 约束 |
|---|---|
| `oauth_states` | 非空 |
| `platform_publish_attempts` | 非空 |
| `orders` | — |
| `purchase_orders` | — |
| `platform_settlement_records` | — |

**关键认识**：原先的物理删除**从未真正安全**，只是 SQLite 默认不强制外键掩盖了它。
即这是一个一直存在的缺陷，不是开启外键才引入的。

## Decision

**删除店铺 = 归档**：

- `shops.archived_at` 置位（`NULL` = 正常可用）；
- 凭证清空（`app_secret` / `access_token` / `refresh_token`）；
- 状态置 `expired`；
- **不物理删除行**。

配套新增 `services/shop_scope.py::active_shop()` 作为**统一可见性守卫**，
列表、`_owned`、订单导入、代发、上架发布、平台守门均排除归档店铺。

## Consequences

**收益**

- 订单 / 采购单 / 结算单的店铺归属**得以保留**，财务对账与审计留痕不被破坏；
- 用户可见行为与「删除」一致（店铺从列表与所有可写入口隐藏）；
- 凭证即时失效，安全语义与删除等价。

**代价**

- 店铺行**永久保留**（含 `shop_name` 等非敏感字段）；
- 若未来需彻底清除，**必须先经合规确认**，再单独执行带级联策略的清理任务；
- 可见性守卫若散落在各路由、靠人肉记得排除归档行，会漏（见 DEBT-21）。

## Alternatives considered

| 方案 | 否决理由 |
|---|---|
| **保持物理删除** | 会抹掉订单/采购单/结算单的店铺归属，破坏财务对账与审计留痕 |
| **级联删除（`ON DELETE CASCADE`）** | 用户点「删除店铺」不应连带销毁历史订单——语义上不可接受 |
| **归档 + 定期物理清理** | 清理任务本身需要级联策略与合规判断，复杂度高且非当前需求 |

## References

- 权威源：[`DECISIONS.md` D7](../DECISIONS.md#L79)
- 关联债务：DEBT-19（已清）、DEBT-21（可见性守卫统一，Phase 2）
- 相关决策：D20（可逆处置优先于删除行）、D26（删除账号前清理身份行）