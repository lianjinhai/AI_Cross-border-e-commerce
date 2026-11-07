# P0-4 证据：三道门禁给出补齐入口 + 双 Profile 真机

> 验收口径（原文）：三道门禁（低价、缺材料、标签依据不足）必须**阻断并返回可执行补齐动作**，
> 禁止只返回裸 409；每道门禁一正一反共 6 条单测；`curl` 记录阻断响应体含「阻断码 + 原因 + 补齐动作」；
> 跑 `scripts/launch_e2e.py` 的 SIMPLE + COMPLEX，主库 SHA256 前后一致；
> 新拍 `03-blocked-lowprice-1440.png`，真机日志落 run.log（仓库 `*.log` 被忽略，实际文件为 `run-log.txt`）。

## 1. 根因：`repair_action` 恒为 `None`

状态模型 §6 早就要求每个 blocker 含 `message / step_code / owner_actor / evidence_refs / repair_action`，
但实现里**四处产生点全部写死 `None`**：

| 产生点 | 场景 |
|---|---|
| `launch_rules.py` 的 `_blocker` | 就绪度算出的步骤阻断 |
| `launch_handlers.py` 的 `missing_blockers` | 动作前置不满足（素材缺项） |
| `launch_actions.py` 的 `_step_state_conflict` | 步骤状态冲突 |
| `launch_submit.py` 的 `_blockers` | 提交/核验领域失败 |

所以前端只拿得到原因、拿不到下一步——这就是「裸 409」的全部内容。

## 2. 改动

### 2.1 新增 `backend/app/workflows/launch_repair.py`

把「阻断码 → 补齐入口」做成唯一映射，三条硬约束写进模块文档：

1. **只指向真实存在的页面**。素材中心 `/app/products/assets` 仍是 `StubPage`，
   因此不拿它当补齐入口；材料类一律指向真实页面 `/app/compliance`。
2. **能不能真补齐要说清楚**。`connected=False` = 背后领域服务未接入（B03–B09），
   页面可看但不能在此完成。
3. **永不返回 `None`**。未知码给兜底待办入口，让「没有专用入口」也成为一条显式信息。

| 阻断码 | 补齐动作 | 入口 | connected |
|---|---|---|---|
| `MISSING_DATA`（资料类） | ACTION `COMPLETE_DATA` | `/app/products/{id}` | true |
| `MISSING_DATA`（材料类：COMPLIANCE/LABEL/EVIDENCE） | ROUTE | `/app/compliance` | false |
| `COMPLIANCE_BLOCK` | ROUTE | `/app/compliance` | false |
| `PRICE_UNACCEPTABLE` | ROUTE | `/app/pricing` | false |
| `SUPPLY_UNAVAILABLE` | ROUTE | `/app/supply/purchases` | true |
| `STOCK_REQUIRED` | ACTION `REQUEST_STOCK` | `/app/fulfillment` | false |
| `USER_ACTION_REQUIRED` | ROUTE | `/app/tasks` | true |
| `PLATFORM_PENDING` / `PLATFORM_ERROR` / `EXTERNAL_SERVICE_REQUIRED` | UNAVAILABLE | `/app/launch` | false |
| 其它（`STEP_STATE_CONFLICT` / `ACTION_PRECONDITION_FAILED`…） | ROUTE 兜底 | `/app/tasks` | true |

### 2.2 低价门禁的事实来源（没有另造一套定价域）

`facts` 新增 `pricing`，取自**既有** `services/costing.calc_profit` 与租户设置 `min_margin`（默认 15%）：

```python
pricing = {"price": …, "margin": …, "min_margin": …, "margin_ok": margin >= floor}
```

口径边界写进了函数注释：这是**本地利润试算**，不是平台核价轮次 `PriceReview`（后者属 B03–B09 未接入），
不能用本事实冒充「已核价」。算不出来时返回 `None` → 条件求值为 UNKNOWN → 步骤因「缺少进入条件资料」
阻断，**不会被默认放行**。

同时 `facts.product` 补了 `id`，让补齐入口能收敛到具体商品详情页而不是列表页。

### 2.3 原因说人话

`_blocker` 增加 `_message`：低价阻断从通用的「进入条件未满足」细化为
「售价毛利 -27.5% 低于最低要求 15.0%，不能进入核价」；标签阻断细化为「标签包缺少可用依据
（LABEL_PACKAGE 未核验或已失效）」。无法细化时保留原文，不编造细节。

### 2.4 前端：阻断必须带入口才叫「可处理」

| 文件 | 改动 |
|---|---|
| `frontend-v9/src/shared/launchRepair.js`（新增） | 纯函数 `repairView` / `blockerView` / `blockerHeadline` / `unrepairableCount` |
| `frontend-v9/src/features/launch/BlockerList.vue`（新增） | 阻断清单：码 + 原因 + 补齐按钮 + 未接入说明 |
| `frontend-v9/src/pages/product/LaunchDetail.vue` | 新增「阻断与补齐」区；动作失败态复用同一列表 |

纯函数化的原因和 P0-3 一样：前端未装 `@vue/test-utils`，逻辑不进组件才可测。

两条渲染红线：
- `kind = UNAVAILABLE` 不给跳转按钮（没有值得去的页面）；
- `connected = false` 时按钮照给（页面本身有效，如定价页能算利润），但**必须同时显示未接入原因**，
  不做「看起来能完成、点了无事发生」的按钮。

### 2.5 `scripts/launch_e2e.py` 支持双 Profile

新增 `--profile {probe,simple,complex}`（默认 `probe`，原行为不变）：
按 Profile 的平台/市场/履约模式造店铺与素材，按 Profile 取首个资料步骤，
并新增第 6b 步断言「阻断项三要素齐全」（每条阻断都要有 `code`、非空 `message`、
`repair_action.path` 以 `/app` 开头）。`contract_profiles` 在 `ERP_DB_URL` 生效后才导入，
否则会把 `app.config` 提前求值、隔离基座失效。

## 3. 验证

### 3.1 三道门禁 6 条单测（`tests/test_launch_gate_repair.py`）

```
缺材料  test_missing_material_gate_blocks_and_points_to_the_product        正例
        test_missing_material_gate_passes_when_materials_are_complete      反例
低价    test_low_margin_gate_blocks_with_numeric_reason_and_pricing_entry  正例
        test_low_margin_gate_passes_above_floor                            反例
标签    test_label_evidence_gate_blocks_and_points_to_compliance           正例
        test_label_evidence_gate_passes_when_label_verified                反例
```

正例统一断言三要素且 `path` 以 `/app` 开头；反例断言未触发时 `blocking_reason == {}`（防门禁过宽）。
另 11 条参数化用例覆盖「补齐入口永不缺席」（含未知码）。

结果：`17 passed`；`pytest -q -k launch` → `171 passed`；`ruff check` 全部通过；
前端 `tests/launch-repair.test.js` → `12 passed`；前端全量 `60 files / 757 tests passed`
（P0-3 收口时为 59 / 745，本批新增 1 文件 12 例）。

### 3.2 双 Profile 真机

三条 Profile 各 `15 步 / PASS 15`、`exit=0`：

| Profile | 选中 | 完成步骤 | 主库 SHA256 |
|---|---|---|---|
| probe（回归） | `ACTION_PROBE` | `INFO` | `d79bd669…` 前后一致 |
| simple | `SIMPLE_CONTRACT` | `INFORMATION` | `d79bd669…` 前后一致 |
| complex | `COMPLEX_CONTRACT` | `PRODUCT_INFORMATION` | `d79bd669…` 前后一致 |

主库行数 `7517` 全程未变。**诚实的边界**：complex Profile 只走到第一个资料步骤——
后续核价/备货/标签/实物材料动作全部 `connected=False`（B03–B09 未接入），
本批不把「能创建、能算就绪度、阻断带入口」包装成「复杂链路已跑通」。

### 3.3 两道门禁的真实响应体（详见 `run-log.txt`）

缺材料（`run 36`，HTTP 409）：

```json
{"code": "MISSING_DATA",
 "message": "图片缺少唯一的当前权利记录：https://example.com/p04-blocked.jpg",
 "step_code": "INFO",
 "repair_action": {"label": "补充商品资料", "kind": "ACTION", "action": "COMPLETE_DATA",
                   "path": "/app/products/63", "connected": true, "reason": ""}}
```

低价（`run 37`，`execution_status=BLOCKED`，进度 1/3）：

```json
{"code": "PRICE_UNACCEPTABLE",
 "message": "售价毛利 -27.5% 低于最低要求 15.0%，不能进入核价",
 "step_code": "PRICE_REVIEW",
 "repair_action": {"label": "前往定价与利润试算", "kind": "ROUTE", "action": null,
                   "path": "/app/pricing", "connected": false,
                   "reason": "核价领域服务未接入（B03–B09），定价页可试算但不能提交核价轮次"}}
```

**标签依据不足没有真机截图**：它的阻断形态与缺材料同属 `COMPLIANCE_BLOCK`，
由 6 条单测覆盖，未单独造现场——这一点在下节边界里写明，不当成已完成。

### 3.4 图 3

`03-blocked-lowprice-1440.png`（1440 视口全页，run #37）：同一屏可见
状态汇总「已阻断 · 完成 1/3」、阻断卡片「PRICE_UNACCEPTABLE + 毛利 -27.5% vs 15.0% +
前往定价与利润试算按钮 + 核价服务未接入说明」、时间线「平台核价 已阻断」带同一原因、
可执行动作 `REPORT_PRICE` 灰显「该能力尚未接入」。控制台无报错。

## 4. 边界（不得包装成已完成）

- **补齐动作大多补不完**。素材上传、核价轮次、标签生成、备货、实物材料核验全部 `connected=False`。
  本批只把「阻断 → 下一步」的链路打通，并如实标注哪一步走不通；真正的补齐能力是 M2-A..M2-E。
- **低价门禁用的是本地利润试算**（`min_margin` 租户设置），不是平台核价结果。
  平台核价属 M2-A，本批不冒充。
- **标签依据不足只有单测覆盖**，没有独立真机截图。
- **复杂 Profile 未跑通全程**：到核价即被低价门禁阻断（这正是本批要证明的行为），
  后续步骤因领域服务缺失无法推进。
- **`/app/products/assets` 仍是占位页**，所以材料类补齐指向 `/app/compliance`；
  素材中心落地后需要回来收紧这条映射。