# V9.1 P0-1 验收报告：三状态枚举对齐与写入点清单

- 执行日期：2026-11-06
- 基线提交：`35de90c`
- 执行单元：`【P0-1】三状态枚举对齐与写入点清单`
- 结论：**P0-1 PASS（仅分析，未改代码）**；发现 1 项高优先级缺口、3 项中/低问题，均如实记录，不掩盖
- 本批性质：**只读审计**。本单元不产出截图；本批 4 张界面佐证随 P0-2 / P0-3 / P0-4 交付

## 1. 门槛逐条判定

| # | 门槛 | 判定 | 证据 |
|---|---|---|---|
| 1 | 三字段清单完整（含义 / 允许值 / 写入点 / 读取点） | PASS | 本文 §2 §3 §4 三张表 |
| 2 | 每个写入点能归属到唯一内核 | PASS | 5 个写入点全部收敛到 §3；`execution_status` 只有 1 个计算源（`launch_rules.evaluate_readiness`） |
| 3 | 无一处三状态互串 | PASS | 脚本核验违规 2 处，逐条确认**均非三状态互串**：1 处是 Profile 定义层同名字段，1 处是供应商域独立枚举（见 §5） |
| 4 | 客户端无法直接 set 状态 | PASS | 全仓无任何 router 写 `WorkflowRun` 三字段；`routers/launch.py` 仅把 `execution_status` 当**查询过滤参数**并按枚举校验 |
| 5 | 未伪造在售 | PASS（沿用既有） | `launch_state.plan_changes` 的 receipt 投影**仅**对 `NOT_SUBMITTED`/`UNKNOWN` 生效，注释明确「绝不自动置 ACTIVE/VERIFIED」 |

## 2. 三状态定义表（权威源对齐）

| 字段 | 载体 | 定义位置 | 枚举来源 | 值域 |
|---|---|---|---|---|
| `execution_status` | `WorkflowRun` | `backend/app/models.py` 的 `WorkflowRun` | `launch_list.EXECUTION_STATES`（frozenset） | 10 值：NOT_STARTED / READY / RUNNING / WAITING_USER / WAITING_EXTERNAL / WAITING_APPROVAL / BLOCKED / FAILED / COMPLETED / CANCELLED |
| `step_status` | `WorkflowStep` | `backend/app/models.py` 的 `WorkflowStep` | `launch_rules.STEP_STATES`（frozenset） | 10 值：PENDING / READY / RUNNING / WAITING_EXTERNAL / WAITING_USER / WAITING_APPROVAL / COMPLETED / BLOCKED / FAILED / SKIPPED |
| `platform_status` | `WorkflowRun`、`Listing`、`PlatformPublishAttempt` | `backend/app/models.py` | `profile_schema.PLATFORM_STATES`（set） | 9 值：UNKNOWN / NOT_SUBMITTED / SUBMITTED / UNDER_REVIEW / ACCEPTED / ACTIVE / PAUSED / REJECTED / OFFLINE |
| `verification_status` | `WorkflowRun`、`Listing`、`PlatformPublishAttempt`、`WorkflowTemplate`、`ProductAsset` | `backend/app/models.py` | **无集中常量**（见 §6 F4） | 运行事实 6 值：UNKNOWN / MANUAL_REPORTED / PENDING_VERIFICATION / VERIFIED / REJECTED / EXPIRED |

**与文档的一致性**：四张枚举表与 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md` §1 完全一致，无缺项、无多项。

## 3. 写入点表（全部 5 处）

| # | 写入内容 | 位置 | 方式 | 客户端可否触发 |
|---|---|---|---|---|
| W1 | 建单初值 `NOT_STARTED` / `NOT_SUBMITTED` / `UNKNOWN` | `backend/app/workflows/launch_records.py` | 显式构造 | 间接（创建上线流程） |
| W2 | `execution_status` 计算 | `backend/app/workflows/launch_rules.py` 的 `evaluate_readiness` → `_summary` → `_run_status` | **纯函数，不碰 DB** | 否 |
| W3 | 三字段统一落库 | `backend/app/workflows/launch_state.py` 的 `plan_changes` | 返回 diff，由调用方应用 | 否 |
| W4 | run 级断言 `ACTIVE` + `VERIFIED` | `backend/app/workflows/launch_submit.py` 的 `confirm_activation`（经 `run_overrides` 参数进 W3） | handler 断言 | 是（需 `CONFIRM_ACTIVATION` 动作 + 双权限） |
| W5 | attempt 级 `SUBMITTED` + `UNKNOWN`/`PENDING_VERIFICATION` | `backend/app/services/action_publish.py` 的 `_external_publish` | 显式赋值 | 是（需 `PUBLISH_LISTING` 审批通过） |

**W3 是唯一落库闸门**：`plan_changes` 全仓只有 2 个消费者——`launch_actions.py`（动作事务内）与 `launch_runtime.py`（刷新）。任何状态变更都必须经这两条路径，没有旁路。

**W2 的聚合优先级**（`_run_status`，与文档 §4 一致）：
CANCELLED → FAILED → COMPLETED → BLOCKED → RUNNING → READY → WAITING_APPROVAL → WAITING_USER → WAITING_EXTERNAL → NOT_STARTED。

> 注：`COMPLETED` 的判定是 `all_completed and (not blocked or activated)`。`activated` 为真时允许「已完成 + 有阻断」并存，这是文档 §4「上线后材料失效产生整改阻断、不擦除历史完成」的**有意设计**，不是 bug——后人勿按缺陷修。

**W4 的四道前置**（`confirm_activation` 内强制，缺一即 409）：
1. `material_ref` 与 `note` 必填（来源 / 时间 / 外部对象）
2. 核验人不得是提交人或执行人（`_reject_self_verification`）
3. `source` 固定 `MANUAL`，不冒充 API 核验
4. 误判更正追加历史，不擦除（`correction_of`）

这与文档 §5「人工自报 → `MANUAL_REPORTED`，不直接 ACTIVE；Reviewer 核对可追溯材料 → 可升级 VERIFIED，source 保持 MANUAL」的**独立核验路径**一致。**未发现伪造在售的写入路径。**

## 4. 读取与判定点表

| 判定用途 | 位置 | 依赖字段 |
|---|---|---|
| 步骤就绪度 / 完成条件 | `backend/app/workflows/launch_rules.py` 的 `_status` | `step_status` |
| Run 状态聚合 | `backend/app/workflows/launch_rules.py` 的 `_run_status` | 全部 `step_status` |
| 上线后整改变理分支 | `backend/app/workflows/launch_plan.py` 的 `activated_flag` | `platform_status ∈ {ACTIVE,PAUSED,OFFLINE}` 且 `completed_at` 非空 |
| 「已核验在售」判定 | `launch_nba.py`、`launch_handlers.py`、`launch_actions.py` **各 1 处**（见 §6 F5） | `platform_status == ACTIVE` 且 `verification_status == VERIFIED` |
| 等待外部筛选 | `backend/app/workflows/launch_list.py` 的 `_PLATFORM_WAITING` | `SUBMITTED` / `UNDER_REVIEW` |
| 列表状态过滤 | `backend/app/workflows/launch_list.py` | `execution_status`（白名单校验） |
| 工作台严重度 | `backend/app/services/workbench.py` | `execution_status ∈ {BLOCKED,FAILED}` → severity high |
| Profile 环境/核验声明 | `backend/app/workflows/launch_dto.py` | **`definition.verification_status`**（注意：非运行事实，见 F1） |
| 步骤落地 | `backend/app/workflows/launch_state.py` 的 `land_completed_waits` | 步骤 `business_type` + `activation_verification.current` |

## 5. 混用核验记录

用脚本对全仓 `app/**/*.py`（排除 tests）提取「`*_status` 字段被与字符串字面量比较」的全部位置，逐条比对文档枚举。

```
A. 违规检查：字段被与「不属于自己枚举」的值比较
[!] verification_status == 'UNVERIFIED'   workflows/launch_dto.py:46
[!] verification_status == 'verified'     routers/factory_network.py:191,196,259
小计违规: 2
```

**两条均不是三状态互串**，逐条定性：

1. `launch_dto.py:46` 的 `definition.verification_status == "UNVERIFIED"` —— 比较对象是 **Profile 定义**的字段，值域是 `Literal["UNKNOWN","UNVERIFIED"]`，不是运行事实枚举。**同一字段名的第三套语义**，见 F1。
2. `factory_network.py` 的 `verification_status == "verified"` —— **供应商域**独立枚举（小写 `manual`/`verified`/`unverified`/`scraped`），与 Launch 域无关。见 F2。

**结论：三状态（execution / platform / verification 运行事实）之间不存在互串。**

### 检查过但确认无违规的项（留痕，避免后人重复排查）

| 项 | 检查结果 |
|---|---|
| `Listing.status = "published"` 是否被当成「已上线」 | **无违规**。前端 `frontend-v9/src/shared/statusDict.js` 映射为「**已发布**」；`listingFlow.js` 仅用它决定是否展示回执。`WaitingExternalState.vue` 与 `LaunchDetail.vue` 均有显式红线注释禁止写「已上线」。 |
| `activated` 允许「COMPLETED + 阻断」并存 | **无违规**，见 §3 W2 注 |
| 客户端能否 PATCH 状态 | **不能**。`routers/launch.py` 的 `execution_status` 仅作查询参数并按 `EXECUTION_STATES` 校验 |

## 6. 发现的问题

### F1（中）`verification_status` 一名三义，`UNVERIFIED` 与 `UNKNOWN` 极易混

| 域 | 值域 | 默认值 | 位置 |
|---|---|---|---|
| 运行事实（Launch） | UNKNOWN / MANUAL_REPORTED / PENDING_VERIFICATION / VERIFIED / REJECTED / EXPIRED | UNKNOWN | `WorkflowRun` 等 |
| **Profile 定义** | **UNKNOWN / UNVERIFIED** | **UNVERIFIED** | `backend/app/workflows/profile_schema.py` |
| 供应商 | manual / verified / unverified / scraped | unverified | `Supplier` / `SupplierOffer` |

`UNVERIFIED`（定义层含义：「该 Profile 不做核验」）与 `UNKNOWN`（运行层含义：「核验结果未知」）是**两个完全不同的意思**，字面上只差两个字母。当前靠「一个在 definition 上、一个在 run 上」隔离，测试覆盖不到跨层误读。

**建议**（不阻塞 P0）：Profile 定义字段改名 `verification_mode`，值改为 `SKIP` / `UNVERIFIED`；若暂不改名，至少在 `profile_schema.py` 加类型别名并在字段处注明「非运行事实」。

### F2（低）供应商域与 Launch 域共用 `verification_status` 列名，靠大小写区分

无 `CheckConstraint`、无集中常量、无类型别名，仅靠「Launch 全大写 / 供应商全小写」的约定区分。一旦有人写错大小写，`VERIFIED` 与 `verified` 在 SQLite 与 Python 比较中行为不同，且没有断言能抓到。

**建议**：`Supplier` / `SupplierOffer` 列改名 `supplier_verification_status`，或加 CHECK 约束钉死小写集合。

### F3（高，影响 P0-2）`platform_status` 的 `ACCEPTED` / `UNDER_REVIEW` 只定义不实现

| 值 | 定义 | 写入 | 判断 | 后果 |
|---|---|---|---|---|
| `ACCEPTED` | 有（`profile_schema.PLATFORM_STATES`） | **零处** | **零处** | 平台「接受」这一事实在系统里不存在 |
| `UNDER_REVIEW` | 有 | **零处** | 仅 `launch_list._PLATFORM_WAITING` 做筛选 | **该筛选分支永远不命中** |

状态模型 §5 要求的状态链是 `UNKNOWN → SUBMITTED → UNDER_REVIEW → ACCEPTED → ACTIVE`，中间两环目前**没有生产者**。

**对 P0-2 的直接结论**：P0-2 不能只做「可信在售判定」——判定逻辑（`platform_status==ACTIVE and verification_status==VERIFIED`）已经存在且正确，真正缺的是**中间状态的写入路径**。P0-2 的实施范围必须扩为「补 `UNDER_REVIEW` / `ACCEPTED` 的外部事实摄入 + 保留原判定」，否则会出现「判定写好了但永远进不去 ACTIVE」的空转。

### F4（中）`verification_status` 没有集中常量集合

其它三个字段都有 frozenset/set 常量（`STEP_STATES` / `EXECUTION_STATES` / `PLATFORM_STATES`），唯独 `verification_status` 的全部取值散落在字符串字面量里，没有任何一处可被引用、可被单测断言。

**建议**：在 `profile_schema.py` 或新建常量模块补 `VERIFICATION_STATES`，纳入 P0-2 的单测断言（「写入值必须 ∈ 集合」）。

### F5（低）「已核验在售」判定重复 3 份

同一谓词 `platform_status == "ACTIVE" and verification_status == "VERIFIED"` 在三处各写一遍：`launch_nba.py`、`launch_handlers.py`、`launch_actions.py`。改口径要改三处，漏一处就出现两个真相。

**建议**：抽成单一函数（如 `launch_state.is_verified_online(run)`），三处改为调用。可与 P0-2 同批完成。

## 7. 本批改动

**无代码改动**（本单元为只读审计）。新增文件仅本报告：

- `docs/evidence/V9-1-P0/REPORT.md`（新）

审计脚本为一次性工具，落在仓库外（`%TEMP%`），不纳入版本控制。

## 8. 验证记录

| 验证 | 命令 / 方式 | 结果 |
|---|---|---|
| 三字段写入点枚举 | `grep -rn "\.execution_status *=\|\.platform_status *=\|\.verification_status *=" backend/app` | 5 处（含 2 处为本审计要区分的域外字段） |
| 混用自动核验 | 自建脚本扫描 `backend/app/**/*.py`（排除 tests），提取字段-字面量比较并比对文档枚举 | 违规 2 处，逐条定性后**均非三状态互串**（见 §5） |
| 枚举覆盖度 | 同上脚本 §C | `platform_status` 用到 5/9，缺 `SUBMITTED`(仅写不判)、`UNDER_REVIEW`、`ACCEPTED`、`REJECTED` → 印证 F3 |
| 枚举一致性 | 人工比对 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md` §1 四张表 | 4/4 完全一致 |
| 客户端写入旁路 | `grep -rn "<三字段>" backend/app/routers/` | 无 router 写入；`launch.py` 仅查询参数 |

> `platform_status` 覆盖度补注：`SUBMITTED` 虽无直接比较，但经 W5 → `_receipt()` → W3 receipt 投影写入 `WorkflowRun`，属**写而不判**；`UNDER_REVIEW` / `ACCEPTED` 则**既不写也不判**。

## 9. 对后续单元的影响

| 单元 | 影响 |
|---|---|
| **P0-2 可信在售判定** | 范围必须从「补判定」扩为「补 `UNDER_REVIEW`/`ACCEPTED` 摄入 + 复用既判定」；顺带做 F4 常量与 F5 抽函数 |
| P0-3 Run/Step/Event 与 Transition | 无需改动三状态口径；`land_completed_waits` 已按 `business_type` 分流，可直接复用 |
| P0-4 三门禁 | 阻断码体系（`BLOCK_CODES`）与本次审计无冲突 |
| M2 / GAP 各单元 | 新增金额与证据字段须遵守 F1/F2 的命名边界，**不要新增第三个 `verification_status` 语义** |

---

*本报告为只读审计结论，未改动任何业务代码；基线 `35de90c`。*
