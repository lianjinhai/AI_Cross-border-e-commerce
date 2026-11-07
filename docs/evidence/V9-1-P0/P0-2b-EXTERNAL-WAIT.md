# P0-2b 证据：`EXTERNAL_WAIT` 步骤的等待态有生产者

> 承接 `P0-2-PLATFORM-STATUS.md` §3.5 记录的新缺口。**本批修正了原方案的一个错误假设。**

## 1. 缺口回顾

P0-2 交付时发现：Profile 里 `execution_mode=EXTERNAL_WAIT` 的步骤，依赖满足后落在 `READY`，
没有任何代码把它写进 `WAITING_EXTERNAL`。当时判断这与 P0-1 的 F3 同类（枚举有、生产者没有）。

## 2. 原方案是错的，必须先说清楚

P0-2b 立项时写的做法是「依赖满足 + `EXTERNAL_WAIT` → 直接落 `WAITING_EXTERNAL`」。
**这个方案会打断两条已接通的链路**，读代码后才发现：

| 动作 | 原 `source_states` | 若步骤提前变等待态 |
|---|---|---|
| `SUBMIT_PLATFORM` | `{READY}` | 提交按钮变灰，永远发不出去 |
| `CONFIRM_ACTIVATION` | `{READY, COMPLETED}` | 核验按钮变灰，在售永远确认不了 |

也就是说：按原方案改，`WAITING_EXTERNAL` 会从「没有生产者」变成「有生产者但堵死下游」。

根因是把两件事混为一谈：

- **`WAITING_APPROVAL`** = 等内部审批（人）
- **`WAITING_EXTERNAL`** = 已向外发出意图，等外部事实回来

依赖满足 ≠ 外部意图已发出。提交动作本身还要走审批队列（`submit_platform` 断言的是
`WAITING_APPROVAL`），所以「依赖满足就进等待」在业务上根本不成立。

## 3. 正确语义（以状态模型 §3 为准）

`docs/PLATFORM_WORKFLOW_STATE_MODEL.md` §3 给了两条迁移：

```
READY/RUNNING → WAITING_EXTERNAL    已创建待办、外部意图或审批对象；释放租约
WAITING_EXTERNAL → READY            可信新外部事实到达，重新求规则
```

所以 `WAITING_EXTERNAL` 有**一个入口、一个出口**，缺一不可：

| 方向 | 触发条件 | 本批实现 |
|---|---|---|
| 进入 | 依赖 + 进入条件满足，但**平台还没给出接受事实** | 落 `WAITING_EXTERNAL` |
| 离开 | 收到可信外部事实 `ACCEPTED` / `ACTIVE` | 回到 `READY`（可核验） |

「可信外部事实」的唯一来源就是 P0-2 建的摄入通道（`sync mode=platform_status`）。
两个单元在这里接上了：**P0-2 负责把事实带进来，P0-2b 负责让步骤对事实作出反应。**

## 4. 改动（3 个文件）

| 文件 | 改动 |
|---|---|
| `backend/app/workflows/launch_rules.py` | 新增 `_external_arrived` / `_awaits_external`；`_status` 增加进入与出口两个分支 |
| `backend/app/workflows/launch_action_catalog.py` | `CONFIRM_ACTIVATION.source_states` 增加 `WAITING_EXTERNAL` |
| `backend/tests/test_launch_actions.py` | 两处 `READY` 断言改为 `WAITING_EXTERNAL`（**收紧**，非放宽） |

### 4.1 为什么只对 `PLATFORM_ACTIVATION` 生效

`EXTERNAL_WAIT` 在 Profile 里有三种用法（`contract_profiles.py`）：
`ACTIVATION` / `ACTIVE`（`PLATFORM_ACTIVATION`）、`PRICE_REVIEW`（`PRICE_REVIEW`）。

只有 `PLATFORM_ACTIVATION` 同时具备两个条件：
1. 有**真实外部事实源**（`platform.status`，且 P0-2 已能摄入）
2. handler **已接通**（`CONFIRM_ACTIVATION`）

`PRICE_REVIEW` 属 B03–B09 未接通（`REPORT_PRICE.connected is False`）。如果它也落
`WAITING_EXTERNAL`，用户看到的是「在等平台报价」，而真相是「这个能力还没做」——
这违反「未接入必须显式」的红线。所以它保持 `READY` + 禁用按钮 + `disabled_reason`。

### 4.2 为什么 `CONFIRM_ACTIVATION` 要接受等待态

平台可能**已经在售**，但 `ACCEPTED` 事实因网络/对接原因没到。此时把核验按钮锁死
会让用户无路可走。放行 `WAITING_EXTERNAL` 后，人工核验（`source=MANUAL`）仍要过
三道前置：材料引用 + 备注、双权限、核验人 ≠ 提交人。**状态放行不等于校验放行。**

## 5. 验证

### 5.1 11 个用例（`tests/test_launch_external_wait.py`）

```
正例：等待态有生产者
  test_activation_waits_for_external_fact[SUBMITTED]      → WAITING_EXTERNAL
  test_activation_waits_for_external_fact[UNDER_REVIEW]   → WAITING_EXTERNAL
  test_missing_platform_fact_still_waits                  → WAITING_EXTERNAL（事实缺失也不放行）
正例：唯一出口
  test_accepted_fact_releases_to_ready[ACCEPTED]          → READY
  test_accepted_fact_releases_to_ready[ACTIVE]            → READY
  test_waiting_external_exits_to_ready_on_new_fact        → 已持久等待态能出来，不粘死
  test_waiting_external_stays_when_fact_unchanged         → 事实没变时保持等待
反例：不得扩大影响面
  test_manual_task_step_is_unaffected                     → MANUAL_TASK 仍 READY
  test_dependency_unsatisfied_never_waits                 → 依赖未满足仍 PENDING
  test_other_external_wait_types_keep_ready               → PRICE_REVIEW 仍 READY + 未接通
动作契约
  test_confirm_activation_accepts_waiting_external        → source_states 含等待态
```

结果：`11 passed`；`pytest -k launch` → `153 passed`。

### 5.2 真机链路（不改库）

在**全新**隔离副本库（`Temp/p02b_shot/erp.db`）+ 真 uvicorn `:8012` 上，只调 API：

```
初始              execution=READY            platform=NOT_SUBMITTED   0/2
完成 INFO         execution=WAITING_EXTERNAL platform=NOT_SUBMITTED   1/2   ← 自动出现
摄入 UNDER_REVIEW execution=WAITING_EXTERNAL platform=UNDER_REVIEW    1/2   ← 保持不变
摄入 ACCEPTED     execution=READY            platform=ACCEPTED        1/2   ← 出口放行
```

第三步 `WAITING_EXTERNAL` 是**流程自己走出来的**，全程没有 UPDATE 任何表。
这直接验证了立项时的那条验收：「真实流程（非改库）能把一个 run 推到 `execution_status=WAITING_EXTERNAL`」。

### 5.3 图 1 已重拍

`01-waiting-external-1440.png` 现在来自 run #37：执行状态「等待平台反馈 1/2」、
平台状态「平台审核中」、验证状态「未知」，横幅「流程尚未上线，请勿视为已发布」，
且「可并行处理（0 项）· 当前没有可并行处理的节点」——等待态没有被当成待办推给用户。

**上一版图 1 里人工补写的步骤态已不存在。**

## 6. 边界（不得包装成已完成）

- **图 2 仍是副本构造**。`02-verified-online-1440.png` 的 `ACTIVE + VERIFIED` 没有走
  `CONFIRM_ACTIVATION`，因为本批最小 Profile 里没有 `PLATFORM_SUBMISSION` 步骤，
  核验前置 `_reject_self_verification` 会以「尚未提交平台」409 拒绝。该图仍有「整改阻断」
  横幅（状态改了但证据未同步），已在上一份报告说明。真实闭环需完整 Profile + 审批链。
- **`PRICE_REVIEW` 仍然不可推进**，属 B03–B09 领域服务未接通，不在本批范围。
- **没有新增任何 DB 写入点**。所有变更都在 `evaluate_readiness` 纯函数层，
  仍经 `launch_state.plan_changes` 单一闸口落库。
- 前端未改。图 1 的渲染是既有组件能力，本批只让后端状态第一次真的走到这条分支。

## 7. 复现

```bash
cd backend && python -m pytest tests/test_launch_external_wait.py -q
cd backend && python -m pytest -k launch -q
cd backend && python scripts/check_docs_consistency.py --json   # 要求 total=0
```
