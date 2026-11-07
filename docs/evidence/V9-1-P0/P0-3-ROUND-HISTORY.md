# P0-3 证据：多轮上线历史与唯一活跃槽

> 验收口径（原文）：「新拍 `04-transition-history-1440.png`，要能看到多轮历史与当前活跃槽」。

## 1. 立项复核：后端早就够了，缺的是界面

动手前先复核，结论是**唯一活跃槽与多轮历史在数据层已经成立**，本批不需要新增表、索引或端点：

| 能力 | 实现位置 | 结论 |
|---|---|---|
| 一个销售对象只有一个活跃槽 | `models.py` 的 `uq_launch_active_slot` 唯一索引 + `ck_workflow_runs_active_slot` 检查约束 | 已有 |
| 重复发起被拦 | `launch_records.py` 的 `_reject_active` → `ACTIVE_LAUNCH_EXISTS` 409 | 已有 |
| 新轮次挂到上一轮 | `launch_records.py` 的 `_previous` → `RELAUNCH_NOT_READY` 校验 | 已有 |
| 终止才释放槽位 | `launch_handlers.py` 的 CANCEL 写 `ended_at` + `active_slot=None` | 已有 |
| 列表可带历史 | `routers/launch.py` 的 `include_history` → `launch_list.py` 收窄 `active_slot == 1` | 已有 |
| 历史标志进 DTO | `launch_dto.py` / `launch_list.py`：`is_history = active_slot is None` | 已有 |

**真正的缺口只有一处**：详情页从头到尾没有轮次视图。用户在一轮被取消后重新发起，界面只显示当前这一轮——
看不到「这是第几轮」、看不到上一轮怎么结束的、也看不到「为什么不能再开一轮」。

## 2. 前端交付（3 处改动）

| 文件 | 改动 |
|---|---|
| `frontend-v9/src/shared/launchRounds.js`（新增） | 纯函数 `buildRoundChain` / `roundChainHint`，负责排序、编号、标记当前、汇总异常 |
| `frontend-v9/src/pages/product/LaunchDetail.vue` | 新增「轮次历史」卡片；`runId` 改为响应式 + `watch`；新增 `loadRounds` / `goRound` |
| `frontend-v9/tests/launch-rounds.test.js`（新增） | 16 个用例 |

### 2.1 为什么抽成纯函数

前端未装 `@vue/test-utils`，组件逻辑只能靠「抽成纯函数」才可测。因此排序、编号、
异常判定全部落在 `launchRounds.js`，`LaunchDetail.vue` 只负责渲染与取数。

### 2.2 编号口径

列表 DTO **没有** `previous_run_id`（只有详情有），所以按 `created_at` 升序编号，
同一时间戳用 `id` 兜底，保证稳定。查询侧已按 `product_id + shop_id` 收窄，
不会把其它销售对象混进来。

### 2.3 槽位标签不叫「成功」

历史轮次标「历史」（灰），活跃槽标「活跃槽」（绿），并配一句说明：

```
同一销售对象仅一个活跃槽；在售或暂停都不会释放它
```

刻意回避「在售 / 成功」这类词——活跃槽只表示**占位**，与是否真的上线成功无关。

## 3. 过程中撞到的两个既有缺陷

### 3.1 `loadSteps` 返回形状被误读，连带拖垮整页（已修）

第一次拍的图 4 里轮次表是空的（「暂无轮次记录」），但接口返回 3 条。抓控制台得到：

```
TypeError: u.value.find is not a function
```

根因：`GET /launch/{id}/steps` 返回的是 `{items, revision, profile}`，而旧代码读 `stepData.steps`。
`steps` 于是变成 `undefined` → 归一化后成对象 → `steps.value.find` 抛错 → **整个 `try` 块中断**，
同页 `Promise.all` 里的事件流与轮次加载根本没执行。

这是既有缺陷，不是本批引入的；但它会让「任意一路失败拖垮整页」，一并修掉：

- 详情拉取失败才走错误态（403 → 无权限，其它 → 错误）；
- 步骤 / 事件 / 轮次三路各自 `try`，任一失败只降级自己；
- 步骤列表归一化为数组，兼容裸数组与 `items` / `steps` 两种字段。

### 3.2 默认分页 20 轮，轮次编号会静默失真（已修）

列表默认 `page_size=20`，上限 200。同一销售对象轮次超过 20 时，前端拿到的只是前 20 条，
**「第 N 轮」的编号就是错的，而页面看上去完全正常**——这属于「伪造」范畴，必须显式暴露。

改法：
- 取数显式带 `page_size=200`（`page_size` 是已声明参数，不会触发 `FILTER_INVALID`）；
- `buildRoundChain` 接收服务端 `total`，`total > 条数` 时推一条异常并渲染成红条：
  「共 N 轮，本次仅取到 M 轮，轮次编号可能不完整」。

## 4. 验证

### 4.1 单测（16 项，`tests/launch-rounds.test.js`）

```
排序编号：升序编号 / 同时间按 id 稳定
当前标记：只标一个 / 不传不标
活跃槽  ：正常 1 个不报错 / >1 显式报异常 / 全历史为 0
分页截断：total 大于条数报异常 / 相等不报
健壮性  ：丢弃无数字 id 脏数据 / 空输入不抛错
语义    ：槽位标签区分历史与活跃
文案    ：历史只读 / 无槽可新开 / 有槽说明不释放 / 多槽优先报异常
```

前端全量：`59 files / 745 tests passed`（此前一次跑出 57/673，是 2 个测试文件写盘 EPERM 未收集，已复核为环境噪声）。

### 4.2 后端用例（验收项「历史能按轮次完整回读」原本没有覆盖，本批补上）

复核时发现 `include_history` 在 `tests/` 下**没有任何用例**，而它正是本批验收口径之一，
于是补 `tests/test_launch_api.py::test_round_history_replays_after_cancel`：

```
创建第 1 轮 → CANCEL（断言 receipt.active_slot_released）   → 槽位释放
带 previous_run_id 创建第 2 轮
默认列表           → 只有第 2 轮，is_history=False，total=1
include_history    → [第2轮, 第1轮]，is_history=[False, True]，total=2
第 2 轮详情        → previous_run_id == 第 1 轮
库里 active_slot=1 → 恰好 1 条
槽位未释放再创建   → 409 ACTIVE_LAUNCH_EXISTS（不接受「有历史就放行」）
```

「不能为同一销售对象开第二个活跃槽」原本已有覆盖，无需新增：
`test_launch_records.py` 的 `test_idempotency_and_active_object_conflicts`（顺序重复）、
`test_concurrent_creation_has_single_sales_object`（两线程并发，只允许 1 个 int 结果）、
`test_database_slot_constraint_and_bound_listing_target`（库级约束）。

`pytest -q -k "workflow or launch"` → `186 passed`。

### 4.3 真实链路（只调 API，不改库）

全新隔离副本库 `Temp/p03_shot/erp.db` + 真 uvicorn `:8013`，通过「创建 → 取消 → 重新发起」走三轮：

```
run 36  active_slot=NULL   is_history=true    READY / NOT_SUBMITTED    ← 第 1 轮
run 37  active_slot=NULL   is_history=true    READY / NOT_SUBMITTED    ← 第 2 轮
run 38  active_slot=1      is_history=false   WAITING_EXTERNAL / UNDER_REVIEW  ← 第 3 轮（活跃槽）
```

`include_history=true` 返回 3 条。第三轮随后由真实动作推进到 `UNDER_REVIEW`（承接 P0-2b），
所以图上第 3 轮显示「等待平台反馈 / 平台审核中」。

### 4.4 图 4

`04-transition-history-1440.png`（1440 视口，全页）：轮次历史三行——第 1 轮「历史 / 待执行 / 未提交」、
第 2 轮同、第 3 轮「活跃槽 / 等待平台反馈 / 平台审核中 / 当前查看」。
同时可见状态汇总三格、等待态横幅与事件流，控制台无报错。

### 4.5 轮次跳转（顺带验证响应式修复）

点第 1 轮的「查看」后：

```
URL     /app/launch/38  →  /app/launch/36
提示    同一销售对象仅一个活跃槽…  →  这是历史轮次，仅可只读回看；同一销售对象的活跃槽只有一处
第一行末列  查看  →  当前查看
```

路由参数变化但组件被复用，旧写法（`Number(route.params.id)`）不会重新取数；
改成 `ref` + `watch` 后验证通过。

## 5. 边界（不得包装成已完成）

- **只做读视图，没做「发起新一轮」入口**。重新发起仍需走原有创建接口，
  `previous_run_id` 由调用方给；本批不加向导、不改创建链路。
- **轮次序号的权威定义不在本轮次里**。用的是「同销售对象按创建时间升序」，
  不是数据库里的 `previous_run_id` 链；若将来允许乱序补录，编号口径要重新对齐。
- **活跃槽 ≠ 在售**。ACTIVE / PAUSED 都不释放槽位，所以「有活跃槽」不代表「已上线」，
  文案已按此写死。
- **异常分支只做了渲染，没有真实数据触发过**。多个活跃槽、分页截断两条只由单测覆盖，
  唯一索引下无法在真机上自然造出多活跃槽。

## 6. 复现

```bash
cd frontend-v9 && npx vitest run tests/launch-rounds.test.js
cd frontend-v9 && npm test
cd backend && python -m pytest tests/test_launch_api.py -q -k round_history
cd backend && python -m pytest -q -k "workflow or launch"
cd backend && python scripts/check_docs_consistency.py --json   # 要求 total=0
```
