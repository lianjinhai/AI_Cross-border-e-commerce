# V9-1-M2 · M2-A 核价：报价轮次与低价阻断

> 执行日期：2026-11-07　基线：`main` @ `1963887`（本批改动提交前）
> 结论：**PASS（含明确边界）**——报价轮次是只增不改的真实写入路径，低价门禁在动作层阻断并给出真入口；
> 但**不含平台往返**，`PRICE_REVIEW` 完成 ≠ 平台已接受价格。

## 1. 这批要解决什么

`PRICE_REVIEW` 的完成条件早已冻结为：

```
all[ present(pricing.review_id), cost_snapshot_current(PRICE_REVIEW) ]
```

但仓库里**没有任何代码生产这两个事实**：`REPORT_PRICE` / `ACCEPT_PRICE` / `COUNTER_PRICE`
三个动作 `connected=False`，定价页只能试算，`PricingRecord` 存的是「算过一次利润」的拆解快照。
结果就是——核价步骤永远停在 `READY`，低价只有一个「未接入」的入口，用户被挡住也不知道下一步。

## 2. 做了什么

### 2.1 新表 `price_rounds`（Revision 32，只增不改）

| 字段 | 作用 |
|---|---|
| `tenant_id` / `product_id` / `run_id` | 归属与隔离；`run_id` 可空（定价页手工试报不属于任何流程） |
| `round_no` | 按 `(tenant_id, product_id)` 递增，`UNIQUE` 兜底并发 |
| `action` | `REPORT` / `ACCEPT` / `COUNTER` |
| `price` / `currency` | **币种必填**，空串即拒绝；不默认 USD |
| `margin` / `min_margin` / `margin_ok` | 本轮的门槛判定留痕（不是重算，是当时的事实） |
| `cost_snapshot` / `cost_fingerprint` | 成本来源快照 + 指纹，用于判「还是不是当前成本」 |
| `decision` | 人工决定留痕：`{decision, by, actor_role, at, note, source_round_id}` |
| `created_by` / `created_at` | 谁、何时 |

**没有 update / delete 代码路径**：每轮都是新行，`round_no` 唯一约束挡住并发重号。

### 2.2 服务层 `app/services/pricing_rounds.py`

- `quote()`：算一轮的毛利与成本快照。**复用唯一一份利润实现** `costing.calc_profit`，
  非 USD 报价先折人民币再折 USD，缺汇率 fail-closed（不猜汇率凑一个能过门禁的毛利）。
- `append()`：只增；`decision_of()` / `snapshot_current()` / `pricing_facts()` 供条件求值。
- `snapshot_current()` 返回 `True/False/None`：`None` 是 UNKNOWN（算不出成本），
  既不放行也不谎称「已失效」。

### 2.3 三个动作接通（`connected=True`）

| 动作 | 载荷 | 语义 |
|---|---|---|
| `REPORT_PRICE` | 必填 `price` + `currency` | 落一轮我方申报价；过门禁后完成「平台核价」步骤 |
| `COUNTER_PRICE` | 必填 `price` + `currency` | 还价 = 新报一轮，决策置 `COUNTER`，**决策步骤不完成** |
| `ACCEPT_PRICE` | 无必填 | 接受最新评审轮；**接受前按当前成本重算**，成本变了当场重新阻断 |

### 2.4 低价门禁

`margin < min_margin` → `409 ACTION_PRECONDITION_FAILED`，`blockers[0]` 是完整三要素：

```json
{"code": "PRICE_UNACCEPTABLE",
 "message": "售价毛利 4.4% 低于最低要求 15.0%，不能提交核价",
 "step_code": "PRICE_REVIEW", "owner_actor": "PLATFORM", "evidence_refs": [],
 "repair_action": {"label": "去定价页测算达标售价", "kind": "ROUTE",
                   "path": "/app/pricing", "connected": true, "reason": ""}}
```

**不写任何行**：保持「校验链零状态变更」的既有约定（拒绝不落审计行，代价已在边界里写明）。

### 2.5 事实与谓词的镜像通道

`asserted_world()` 原来只特判 `platform_status` 与 `ACTIVATION` 谓词，handler 刚写下的轮次
在事务内看不见。本批加了通用通道 `StepEffect.facts / .predicates`（浅合并且**不落 step.result**），
让 `pricing.review_id` 与 `cost_snapshot_current` 在本次收敛重算里成立；下次请求由 `launch_facts`
重新读库——事实的持久来源仍只有 DB 一处。

### 2.6 前端

- `LaunchActionDialog`：核价动作出现「申报价 + 币种」两个必填项，币种**无默认值**（不替用户假定 USD）。
- `shared/pricingRounds.js`：纯函数视图模型（币种绑定、门槛文案、只读语义），12 例以上单测。
- `Pricing.vue`：新增「核价报价轮次」只读区块（历史表 + 门槛判定 + 低价红条），文案写明写入口在 Launch。

## 3. 验收逐条

| 判据 | 结果 | 证据 |
|---|---|---|
| 正例（正常轮次） | ✅ | `test_report_price_records_a_round_and_completes_review`：落 1 行、步骤 COMPLETED、回执带 `round_no=1`/`margin_ok=true`；真机截图 01 三轮 |
| 反例（低价被阻断） | ✅ | `test_low_price_is_blocked_and_writes_nothing`：409、`PRICE_UNACCEPTABLE`、**0 行写入**、revision 不变；真机截图 02 |
| 越权（403） | ✅ | `test_read_only_role_cannot_report_price`：`READ_ONLY` → `PERMISSION_DENIED` 403，无轮次无事件 |
| 历史不被覆盖 | ✅ | `test_accept_price_completes_decision_and_keeps_history`：`round_no=[1,2,3]`，第一行三字段一字未动 |
| 成本变动重新阻断 | ✅ | `test_cost_change_invalidates_the_round`：供应商调价后 `PRICE_REVIEW` → BLOCKED「依据已失效」 |
| 币种必带 | ✅ | `test_price_without_currency_is_rejected`（422）+ `test_quote_requires_currency_and_positive_price` |
| 口径单一 | ✅ | `test_margin_gate_uses_the_single_costing_implementation`：与 `costing.calc_profit` 同一 `margin` |
| 迁移可回滚 | ✅ | `test_price_rounds_migration_is_reversible`：升→插→重复轮次号被 UNIQUE 拒→有数据拒降级→清空后真降级→再升 |
| 主库未写 | ✅ | `run-log.txt` 首尾 SHA256 一致；主库无 `price_rounds` 表 |
| 界面佐证 2 张 | ✅ | `01-costing-normal-1440.png`、`02-costing-blocked-1440.png` |

回归：`pytest tests/test_launch_price_rounds.py` 8 passed；`-k "launch or pricing or migration"`
246 passed（含新增 9 例）；前端 `61 files / 771 tests`（JSON reporter 权威计数）；
`ruff check app` 全过（`ruff check .` 剩 8 条**存量**测试告警，见 §5）；
`vite build` 通过；文档门禁 `total=0`。

后端全量 `pytest -q`：**1050 tests / 1 failed**。失败项是
`test_listing_actions.py::test_workflow_pauses_before_publish_and_resumes_only_after_execution[True]`，
**属既有失败，不是本批引入的回归**——在干净的 `1963887` worktree 上跑同一个全量，
这条同样红（那份基线还有 2 条本批已修，见 §4）。根因本次定位到链路末端：

1. `test_api.py` 调 `POST /api/shops/purge_demo_data` 清空演示租户的 products / listings；
2. `ai_actions` **不在** `_PURGE_PLAN` 里，审批记录残留且继续指向已删除的 listing；
3. SQLite 的 `INTEGER PRIMARY KEY` 删除后会**复用**行号，新 listing 拿到同一个 id；
4. 发布意图守卫 `_existing_intent` 见到「同 target 的 SUCCESS 提案 + 不同 fingerprint」，
   按设计拒绝 409「已发布内容或目标店铺发生变化」。守卫判定没错，错的是 id 复用让两个不同实体撞了。

判别力：断开上述任一环该用例即绿，单跑该文件恒绿。修法涉及「清理演示数据是否连审批记录
一起删」这一语义取舍（审计保留 vs 引用完整性），已作为独立任务登记，不在本批改（§5 第 6 条）。

## 4. 顺手修掉的既有缺陷

1. `launch_rules._message` 只要见到 `margin`/`min_margin` 就改写成「毛利 X% 低于最低要求 Y%」，
   不看是否真的低于——成本变动导致的重阻断会显示成「毛利 89.5% 低于最低要求 15.0%」这种
   自相矛盾的文案。已加 `margin < floor` 守卫，非低价场景保留原原因。
2. `test_selected_offer.py` 写悬空 `selected_offer_id` 时借的是**共享连接池**里的连接。
   `PRAGMA foreign_keys` 是连接级状态，归还后连接仍带 `OFF`，后续用例只要复用到它，外键就
   静默失效——实测 `test_tenant_id_foreign_keys::test_tenant_zero_sentinel_is_rejected`
   报 `DID NOT RAISE IntegrityError`（探针读到的 `PRAGMA foreign_keys` 就是 `0`）。
   原来「finally 里补 `PRAGMA ...=ON`」并不可靠：SQLite 在事务中会忽略这条 PRAGMA。
   改为**一次性引擎写坏数据后 dispose**，池里不再留下带 `OFF` 的连接；并补上用例收尾
   「把选定重置回合法报价」，否则全库 `PRAGMA foreign_key_check` 会看到孤儿行，
   让清理用例误判成「漏删」。
3. `tenant_data_purge._PURGE_PLAN` 补 `price_rounds`（`→ workflow_runs` / `→ products`），
   否则清理演示数据会在 DELETE 时撞外键 500——这条是本批新表带出来的，属必改项。

## 5. 边界（必须与完成一起读）

1. **没有平台往返**。本批核价是**本地报价轮次**：记录申报价、成本快照与人工决策。
   仓库里没有核价适配器，所以 `REPORT_PRICE` 不写任何外部引用，
   `PRICE_REVIEW` 完成只代表本地评审记录成立，**不代表平台已接受价格**。
2. **拒绝不落审计行**。低价被拒时零写入（遵循框架「校验链零状态变更」）。
   如果以后要留「曾被拒过几次」的证据，需要新增独立审计表，不能把半成品轮次写进历史。
3. **截图用的是本地契约样本**（`M2A_SCREEN_PROFILE`），不是 `COMPLEX_CONTRACT`：
   复杂链路的中间步骤（平台属性、提交审批）仍未接通，跑不到核价。这一点与 P0 批的口径一致。
4. **定价页不能提交轮次**。写入口只有 Launch 动作——定价页没有 run/revision 上下文，
   允许它写就会让「谁批的、依据哪份成本」断链。
5. `ACCEPT_PRICE` 接受的是**最新一轮**，不支持指定历史某轮（没有 UI 也没有载荷字段）。
6. **全量回归还剩 1 条既有失败**（§3 末尾已给完整根因）：清理演示数据不删 `ai_actions`，
   清理后 id 复用让发布意图守卫误判。修它要动「清理语义 + 审计保留」的边界，
   已单独登记任务；本批不夹带，也不把它写成「已修」。
7. `ruff check .` 的 8 条告警全在 `tests/`（`test_product_overview.py` 4 条、
   `test_selected_offer.py` 2 条、`test_business_profile.py` / `test_orders_shop_scope.py` 各 1 条），
   均为存量未用变量/未用导入，**不在本批新增**；`ruff check app` 为零。
