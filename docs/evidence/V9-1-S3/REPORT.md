# V9.1 S3 验收报告：AI 能力、目标入口与 Action 契约对齐

- 执行日期：2026-10-20
- 基线提交：`8c53de2`（B3 收口）
- 结论：**S3 PASS**（门槛 6 项全部有真实 API 证据；1 项既有缺陷已定位并修复）
- 验收方式：隔离副本库 + 真 uvicorn + 真实 HTTP（`26/26 PASS`），主库 SHA256 前后一致

## 1. 门槛逐条判定

| # | 门槛 | 判定 | 证据 |
|---|---|---|---|
| 1 | 真实 API 可列出 Action | PASS | `GET /api/actions?action_type=ALL&status=ALL` → `total=13`，跨 3 种类型 |
| 2 | 可定位单条 Action | PASS | `GET /api/actions/{id}` → 200，含 `required_permission/agent_type/created_at`；不存在 → 404 |
| 3 | 可从僵死态恢复 | PASS | 种入 `EXECUTING`（2 小时前）→ 启动后 `GET` 读回 `FAILED`，`outcome.recovered_on_startup=true` |
| 4 | 筛选/总量正确 | PASS | `page_size=3` 时单页 ≤3、`total` 不随分页变化；`page_num=2` 返回不同集合；按类型筛选只含该类型；未知类型/状态 → 400 |
| 5 | 只读与越权不能审批执行 | PASS | viewer：能力矩阵 `enabled=0`、全部带「缺少权限」；`GET /actions?ALL` → 403；approve/execute → 403 |
| 6 | 未注册能力明确不可执行 | PASS | 能力矩阵只出现 `POLICIES` 的 8 个类型（无 `REPRICE`/`RESTOCK`）；`action_type=REPRICE` → 400；免审批动作 approve → 409「此 Action 不需要人工审批」 |

补充：owner 执行 `CREATE_LISTING_DRAFT` → `SUCCESS`，`GET /actions/{id}/result` 的 `outcome.result` 含真实 Listing 行（id=43），刷新可重读。

## 2. 本批改动

**后端**
- `action_queue.query_actions()`：类型/状态可为「全部」，返回 `(rows, total)`；`_scope_condition` 在「全部」口径下按权限收窄（PUBLISH_LISTING 无店铺范围时排除），保留 `list_actions` 兼容层。
- `routers/actions.py`：`GET /actions` 支持 `ALL`、`page_num/page_size`（`limit` 兼容）、`total`；新增 `GET /actions/{id}` 与 `GET /actions/{id}/result`；权限判定改为「按类型校验 / 全部=本人权限类型集合」。
- `services/ai_capabilities.py`（新）：由 `POLICIES + HANDLERS + CONTRACTS + WorkspaceContext + StoreScope` 计算能力矩阵（`enabled`/`blocked_reasons`/`summary`），只读、无凭证。
- `routers/ai.py`：`GET /ai/capabilities`。
- `services/action_system.recover_stuck_actions()`：启动时把超过 10 分钟的 `EXECUTING` 收敛为 `FAILED` 并写 `recovered_on_startup`，在途的不动。
- `services/ai_actions.action_dict()`：补 `agent_type/required_permission/executed_by/created_at/updated_at/executed_at`。
- `tests/test_action_contract.py`（新，4 项）：全部筛选+总量、详情+回执、能力矩阵阻断原因、启动恢复。

**前端**
- `api/domains/actions.js`：`fetchActions`（单请求分页）、`fetchAction`、`fetchActionResult`；`reject` 保持 `reason → note` 映射。
- `api/domains/ai.js`：`fetchCapabilities`。
- `pages/aiops/AiActions.vue`：一次请求取全量（不再按状态各查一页拼接）、服务端分页与总数；类型下拉来自能力矩阵；逐行按 `required_permission` fail-closed；不可操作时优先展示服务端阻断原因。
- `shared/actionView.js`（新，纯函数）+ `tests/shared/actionView.test.js`（10 项）。
- `components/ApprovalPanel.vue`：列表请求带 `type`。

## 3. 验证记录

| 验证 | 命令 | 结果 |
|---|---|---|
| 后端 Action 关联回归 | `pytest tests/test_action_contract.py tests/test_role_permissions.py tests/test_action_system.py tests/test_ai_action_migration.py tests/test_ad_draft_actions.py tests/test_launch_actions.py tests/test_listing_actions.py tests/test_trend_actions.py tests/test_workbench.py` | **96 passed** |
| 前端全量单测 | `node node_modules/vitest/vitest.mjs run` | **720 passed / 57 files** |
| 前端构建 | `vite build --outDir <temp>` | 成功（2685 modules） |
| SFC 编译 | `@vue/compiler-sfc` 校验 `AiActions.vue`、`ApprovalPanel.vue` | OK |
| S3 门槛真机验收 | 隔离副本库 + uvicorn:8137 | **26/26 PASS**，主库 SHA256 不变 |

## 4. 缺陷与修复

### DEFECT-S3-01（既有，非本批引入）：发布日期定时炸弹

- 现象：`test_listing_actions.py` 4 项在 2026-10-20 集体失败，`POST /listings/{id}/publish` 返回
  `409 上架复核未通过：平台规则已超过30天未更新（2026-09-19）`。
- 根因：`platform_rules.DEFAULT_RULE_PACKS` 的 `version` 写死为 `2026-09-19`；
  `review_analysis.evaluate_review` 以「包版本距今 >30 天」判定 `manual_required`，
  `orchestrator.invoke_listing` 对非 `approved` 一律 409。测试通过 `client` 使用内置包，
  于是**每到第 31 天就必然变红**，与当批代码无关。
- 修复：`tests/test_listing_actions.py` 增加 `_fresh_rule_pack` 夹具（仅发布链测试显式请求），
  为 shopee 种入当日版本规则包；新增 `test_stale_rule_pack_blocks_publish_with_reason`
  锁定「过期必须 409 + 明确原因 + 不改 Listing + 不产出 Action」。
- **未做**：没有通过改内置包日期让测试变绿——那会掩盖真实策略。生产侧规则刷新
  （`ERP_RULES_URL` / 规则包更新）与「过期后的人工放行路径」列入 S5/S6 待办。

### DEFECT-S3-02（本批自检发现）：能力矩阵前端兜底权限用错维度

- `AiActions.vue` 曾以 `can('order:write')` 作为无 `required_permission` 行的兜底。
- 修复：兜底固定为 `false`（fail-closed）；后端 `action_dict` 已保证每行都带
  `required_permission`，无需猜测权限维度。

## 5. 明确未覆盖 / 待后续

- `grep` 到 `features/aicopilot/AiCopilot.vue` 只用 3 个固定 action key 做导航映射，
  本次未改：orchestrator 返回的 key 有限且未注册 key 已走 WaitingExternal，不构成「假入口」。
- 过期建议的「事实版本」复核目前覆盖 `ADJUST_AD_BUDGET`（预算/花费/收入）与发布类店铺范围；
  其余低风险动作靠 policy 一致性校验，不做业务事实快照比对。
- 真实模型驱动的完整闭环属 S4，本批只用受控 Action 验证契约。
