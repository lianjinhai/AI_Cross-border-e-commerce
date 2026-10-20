# V9.1 S4 验收报告：最小 AI 内部业务链

- 执行日期：2026-10-20
- 基线提交：`8f43d6c`（S3）
- 结论：**S4 内部编排 PASS；真实模型实测 BLOCKED**（未配置 `api_key`，按计划不得把 fixture 当真实 AI 成功）
- 验收方式：隔离副本库 + 真 uvicorn + 真实 HTTP（`19/19 PASS`），主库 SHA256 前后一致

## 1. 门槛逐条判定

| # | 门槛 | 判定 | 证据 |
|---|---|---|---|
| 1 | 真实商品入口提交目标，服务端装载身份/范围/能力 | PASS | `POST /api/products/{id}/standardize` → `invoke_product` 先 `require_action_permission(product:write)`，Agent 经 Tool 取事实 |
| 2 | Agent 经 Tool 取事实，不直连库 | PASS | `_tool_product` / `find_duplicate`；既有 `test_product_agent_never_reads_or_writes_business_orm` 守护 |
| 3 | 模型输出结构化并二次校验 | PASS（规则模式） | `ask_json` + `safe_fields` 白名单；无效结构降级并留 `llm ok=false` 审计 |
| 4 | 产物持久化 + 生成既有 Action | PASS | Action `#11`：`target_type=product`、`expected_impact.payload`、`evidence.source=rule`、`scope_key` |
| 5 | Policy/权限/风险/审批按既有策略 | PASS | 低风险 `UPDATE_PRODUCT_CONTENT` 自动执行；高风险 `ADJUST_AD_BUDGET` 强制 `PENDING_APPROVAL` |
| 6 | 审批拒绝/通过两条分支 | PASS | 拒绝 → `REJECTED`、活动预算仍 50、再执行 409；通过 → `SUCCESS`、预算 100→60 |
| 7 | Executor 幂等 + 回执 + 刷新一致 | PASS | 重复执行预算仍 60（无二次下调）；`GET /actions/{id}/result` 终态可查 |
| 8 | 重复请求复用或明确冲突 | PASS（本批补齐） | 同商品重复标准化 → 复用 Action `#11`，`idempotent_replay=true`，Action 总数不变 |
| 9 | 越权阻断 | PASS | viewer 触发标准化 → 403 |
| 10 | 模型失败不造成功建议 | PASS | 模型不可用/结构无效 → `mode=rule` 且 `AiLog` 有失败痕迹，不标 llm |

## 2. 本批改动

- `agents/discovery.py`：`standardize()` 保留 `ask_json` 的 mode，写入 `_action_proposal_evidence = {source, model_mode}`。
- `services/product_outputs.py`：
  - `finalize_product` 透传来源证据；
  - 新增 `_unchanged_success`：单商品直接调用且目标值与最近一次 SUCCESS 完全一致时复用该 Action
    （排除 `payload.before`，因其含 `updated_at` 必然变化）。批量/工作流仍各自建 Action，
    以保证 `scope_manifest` 断点恢复语义不被破坏。
- `agents/base.py`：模型返回空对象/非 dict 时补记一条 `llm ok=false` 审计，再降级规则引擎
  （此前只有 rule 日志，事后无法判断模型是否回过）。
- 测试：`test_product_standardization.py` +5（来源证据、降级痕迹、重复复用），
  并移除 `test_workflow_with_zero_actions...` 中「把全部活跃商品标记 deleted」的破坏性清理
  （它会让后续用例取不到商品，属测试顺序耦合，非本功能缺陷）。

## 3. 验证记录

| 验证 | 命令 | 结果 |
|---|---|---|
| S4 真机门槛 | 隔离副本库 + uvicorn:8138 | **19/19 PASS**，主库 SHA256 不变 |
| 标准化专项 | `pytest tests/test_product_standardization.py` | **27 passed** |
| 关联回归 | `product_standardization + ai_native_p1 + discovery/pricing_outputs + tool_layer + action_system/contract + listing_actions + workflow_kind/profiles` | **38 passed**（修复顺序耦合后） |
| 文档门禁 | `check_docs_consistency.py --json` | `total=0` |

真机关键读数（隔离库）：
- 标准化 Action `#11`：`SUCCESS`，`evidence.source=rule`，商品类目 `旧类目 → 家居`，
  `weight_kg=0.3 / material=PP / color=多色`；重复请求返回同一 `action_id`。
- 预算拒绝：Action `#12` → `REJECTED`，活动预算保持 `50.0`，再执行 409。
- 预算通过：Action `#13` → `APPROVED → SUCCESS`，预算 `100.0 → 60.0`，重复执行仍 `60.0`。

## 4. 真实模型实测：BLOCKED（如实记录）

- `get_llm_config()`：`model=glm-4-flash`、`base_url=https://open.bigmodel.cn/api/paas/v4`、**`api_key` 为空** → `ModelRouter.available=False`。
- 按计划「未经授权不使用新外部账号或额外付费服务」，本批**没有**请求任何外部模型。
- 因此本批只能判定：**内部编排链路通过、规则模式（离线降级）真机通过；模型驱动验收待配置授权 key 后补做**。
- 可复验命令（配置 key 后）：
  1. `PUT /api/ai/settings` 写入 `api_key`（或环境变量 `ERP_LLM_API_KEY`）；
  2. 重跑同一真机脚本，断言 `Action.evidence.source == "llm"` 且 `AiLog.mode == "llm"`；
  3. 断网/改错 base_url 复验「降级 + `llm ok=false` 审计」不被误报为 llm。

## 5. 未覆盖

- workbench/任务详情的跨域待办联动未在本批做实机断言（S3 已保证 Action 队列同源，S5 再验跨域）。
- 阈值：`recover_stuck_actions` 为 10 分钟，重启恢复在 S3 已有测试与真机证据。
- 仅验证 `UPDATE_PRODUCT_CONTENT`（低风险）与 `ADJUST_AD_BUDGET`（高风险）两类；其余动作按注册表存在，未逐条真机跑通。
