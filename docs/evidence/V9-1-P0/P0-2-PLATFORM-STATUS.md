# P0-2 证据：平台状态摄入通道与在售判定可达

> 承接 `REPORT.md`（P0-1 审计）的结论 F3。**本批只做「摄入通道 + 状态机」，不接真实平台 API。**

## 1. 要解决的问题（来自 P0-1）

P0-1 审计发现：`ACCEPTED`、`UNDER_REVIEW` 两个平台状态**在枚举里有定义、在迁移规则里有目标，但全代码库从未被写入**。
后果是 `is_verified_online()` 这个「已在售」判定虽然实现正确，却**永远无法到达**——链路上没有任何一处能把 `platform_status` 推到 `ACCEPTED`。

同时 `Profile.status_mapping`（各平台原始状态 → 内部状态的映射表）是**死配置**：库里存了、管理端能配，但没有任何代码消费它。

判定：**不是判定逻辑错了，是缺少摄入通道。** P0-2 的任务是补通道，不是改判定。

## 2. 改了什么

| 层 | 文件 | 职责 |
|---|---|---|
| 纯函数 | `backend/app/workflows/launch_status.py` | 状态机与映射，无 IO、无 DB，可单测 |
| 编排 | `backend/app/workflows/launch_status_sync.py` | 校验 → 映射 → 记账 → 校验迁移 → CAS 写入 → 事件 |
| 迁移 | `backend/migrations/versions/20261106_31_platform_event_provenance.py` | 给 `platform_publish_attempts` 补 4 个溯源列 |
| 入口 | `backend/app/routers/launch.py` | `POST /api/launch/{run_id}/sync` 的 `mode="platform_status"` |
| 契约 | `docs/CONTRACT.md` | 新增「P0-2 平台状态摄入契约」卡片 |
| 去重 | `launch_handlers.py` / `launch_nba.py` / `launch_actions.py` / `launch_plan.py` | 3 处重复的「在售」谓词收敛为 `is_verified_online(run)` |

### 2.1 状态机的三条硬防线

```
UNKNOWN / NOT_SUBMITTED → SUBMITTED → UNDER_REVIEW → ACCEPTED → (REJECTED)
                                                              ACTIVE 只能由核验置位
```

1. **`ACTIVE` 不在任何目标的集合里。** 摄入路径物理上无法把状态置成「在售」——
   `ACTIVE` 只能由 `CONFIRM_ACTIVATION` 独立核验流程写入。这条是防止「平台回传一个 API 字段就等同于已上线」的伪造成功。
2. **未注册的 `raw_status` 不推进。** 映射不到 → 落 `UNKNOWN + PLATFORM_ERROR`，同时写 `PlatformStatusUnmapped` 事件，`platform_status` 原地不动。
3. **旧序号的乱序事件不回退。** `source_revision` 小于已记录的 `last_revision` → 只留审计事件 `PlatformStatusStaleIgnored`，状态不回归。

### 2.2 为什么 `ACTIVE` 要单独留一条路

`verification_status` 与 `platform_status` 是**两个不同语义**（详见 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md` §1）：
- `platform_status` = 平台侧怎么说的（可被外部事件影响）
- `verification_status` = 我们**自己核验过**没有（只能由人工/核验流程置位）

`is_verified_online(run)` 要求**两者同时成立**。所以即便平台侧回传 `ACTIVE`，只要 `verification_status != "VERIFIED"`，仍不算在售。
这是有意的双锁：外部说在售 ≠ 我们确认在售。

## 3. 怎么验证的（可复现）

### 3.1 21 个用例

```bash
cd backend && python -m pytest tests/test_launch_platform_status.py -v
```

```
# 映射（纯函数）
test_map_uses_profile_status_mapping_exact_match
test_map_falls_back_to_case_insensitive
test_unregistered_raw_status_never_advances          (参数化 ×4)
test_mapping_to_non_platform_state_is_rejected
test_missing_status_mapping_degrades_to_error
# 迁移（纯函数）
test_forward_chain_is_allowed
test_active_is_never_a_transition_target
test_backward_and_shortcut_transitions_are_rejected
test_rejected_can_be_resubmitted_and_same_state_is_idempotent
test_stale_event_detection
test_verified_online_and_activated_helpers
# HTTP 契约（真走过路由）
test_platform_status_chain_is_reachable
test_unmapped_raw_status_keeps_state_and_records_error
test_stale_revision_is_audited_without_regression
test_backward_transition_is_rejected
test_active_cannot_be_injected
test_revision_conflict_is_reported
test_attempt_provenance_is_recorded
```

结果：`21 passed`。

其中最关键的一条是 `test_platform_status_chain_is_reachable`：它用真 HTTP 请求把 `SUBMITTED → UNDER_REVIEW → ACCEPTED` 走通，
断言 `platform_status` 真的变了、`PlatformStatusChanged` 事件真的落了。**这正是 P0-1 说「从不可达」的那条路。**

### 3.2 迁移可逆性（副本库实测，不碰主库）

在 `backend/erp.db` 的副本上跑 `downgrade()` → `upgrade()`，观察列的存在性：

```
降级前含新列: True
降级后含新列: False
重升级后含新列: True
```

主库当前状态：`alembic_version = 20261106_31`，4 个新列 `source / source_time / external_reference / source_revision` 均已存在，`platform_publish_attempts` 行数未变（0 行，无数据损失）。

> `downgrade()` 在**表内有数据时会主动抛错**，不静默丢列。这是有意的：溯源信息一旦产生就不该被回滚悄悄抹掉，需要前向修复。

### 3.3 全量回归对照（排除「我改坏了」）

在 HEAD 基线的独立 worktree 上跑全量，与本次工作区逐条比对：

| | 基线 `778eb35` | 本次工作区 |
|---|---|---|
| `test_docs_consistency` | 2 失败 | **0 失败**（已修好） |
| `test_listing_actions` | 1 失败 | 1 失败（同一条） |
| `test_shop_archive_and_purge` | 2 失败 | 2 失败（同两条） |
| `test_tenant_id_foreign_keys` | 1 失败 | 1 失败（同一条） |
| `test_workspace_identity_migration` | 0 | 1 error（teardown 守卫，见下） |

4 个隔离性失败在两边的**用例名完全相同**，是既有的「单跑绿、全量红」问题（连接级 `PRAGMA foreign_keys` 污染 + 共享 tenant 顺序依赖），本次改动未引入。

那个 teardown error 的真实堆栈是 `conftest.py` 会话级 fixture 删除 `backend/test_erp_*.db` 时被 safe-delete 批量守卫（累计 270 个路径 > 阈值 50）拦截抛 `SystemExit(1)`，落在会话最后一个测试头上。属环境守卫与 pytest teardown 的冲突，与业务代码无关；单独跑该文件 9 passed。

### 3.4 界面佐证（真机拍摄）

两张图都是在**隔离副本库**（主库冷拷贝到 Temp，`ERP_DB_URL` 指过去）+ 真 uvicorn（`:8011`）+ 真 Chromium（1440×900）下拍的，主库 `backend/erp.db` 全程未被写入。

| 图 | 画面 | 验的是什么 |
|---|---|---|
| `01-waiting-external-1440.png` | 执行状态「等待平台反馈 1/2」、平台状态「平台审核中」、验证状态「未核验」 | 未拿到平台回执时**不得**呈现为上线（红线段） |
| `02-verified-online-1440.png` | 执行状态「已完成 2/2」、平台状态「在售」、验证状态「已核验」 | 只有 `ACTIVE` **且** `VERIFIED` 双绿才是「已核验在售」 |

图 1 的推进过程是真实的，不是改库造的：先 `POST /launch/36/actions/COMPLETE_DATA` 完成「商品资料」步骤（1/2），
再 `POST /launch/36/sync` 带 `mode=platform_status, raw_status=SHOPEE_REVIEWING`，由 P0-2 新通道把
`SUBMITTED → UNDER_REVIEW`。页面随即出现黄色横幅「等待平台核验 · 等待外部平台回执，流程尚未上线，**请勿视为已发布**」——
这正是 README §三 第 3 条要求的红线文案。

**两点如实说明**：

1. 图 1 的 `WAITING_EXTERNAL` 步骤态是副本上补写的。原因是本批最小 Profile 的「在售核验」步骤虽为 `EXTERNAL_WAIT`，
   但当前规则引擎只把它算成 `READY`，不会自己进入 `WAITING_EXTERNAL`——这本身是一个独立缺口（见 §4），
   不属于 P0-2 摄入通道的职责，已在下方记录待办。
2. 图 2 出现「整改阻断（已完成历史记录保留，不因整改擦除）」，是副本上把步骤态直接置 `COMPLETED` 而**证据未同步**导致的
   副产物。它恰好说明守卫在工作：状态改了但证据没跟上就会被拦。真实流程完成时会带 Activation 证据，不会有这条阻断。

## 3.5 顺带发现的新缺口：`EXTERNAL_WAIT` 步骤不会自动进等待态

做界面佐证时发现：Profile 里声明为 `execution_mode=EXTERNAL_WAIT` 的步骤，完成后依赖满足时状态落在 `READY`，
而不是 `WAITING_EXTERNAL`。也就是说 `launch_rules._step_status` 里「`old in WAITING` 就保留」这条只对**已经**在等待态的步骤生效，
没有任何代码把首次进入等待的步骤写进去。

影响：`WAITING_EXTERNAL` 这个执行态在真实流程里同样**没有生产者**——和 P0-1 发现的 F3 是同一类问题（枚举有、写入点没有），
只是发生在执行态而非平台态。

建议：新开一个单元（暂记 **P0-2b**）补 `EXTERNAL_WAIT` 步骤进入等待态的写入，并同步补测试。
本批不擅自扩范围，避免把「补摄入」和「补执行态」混在一个提交里。

## 4. 明确没有做的事（不得包装成已完成）

- **没有接任何真实平台 API。** 摄入入口现在是 HTTP 端点，由调用方推数据进来。Shopify/Amazon 等真实回传仍是 `WAITING_EXTERNAL`。
- **前端没有入口。** `frontend-v9` 里还没有触发 `mode=platform_status` 的界面，当前只能靠 curl / 测试驱动。
- **管理端没有映射编辑器。** `Profile.status_mapping` 仍只能应用内写库，没有 HTTP 端点。
- **`verification_status` 的人工核验界面仍未做。** 所以 `is_verified_online()` 虽然可达，实操上还需人工置 `VERIFIED`。
- **`EXTERNAL_WAIT` 步骤不会自动进 `WAITING_EXTERNAL`**（见 §3.5）。执行态的这一缺口留给 P0-2b，本批未动。

因此本批的正确表述是：**「摄入通道已建，在售判定在链路上可达」**，**不是**「平台已对接」或「已上线」。

## 5. 复现命令汇总

```bash
# 纯函数 + HTTP 契约
cd backend && python -m pytest tests/test_launch_platform_status.py -q

# Launch 域整体回归
cd backend && python -m pytest tests/test_launch_api.py tests/test_launch_platform_status.py -q

# 文档门禁（须 total=0）
cd backend && python scripts/check_docs_consistency.py --json
```
