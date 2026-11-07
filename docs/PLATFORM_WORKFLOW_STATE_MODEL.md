# Platform Workflow 状态与迁移 V2

> 最后更新：2026-10-10。状态：FROZEN_FOR_IMPLEMENTATION；实现状态见 `docs/PLATFORM_WORKFLOW_PROGRESS.md`。
> 实体/权限/API 以 `docs/PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md` 为准。

## 1. 三类状态严格分离

| 维度 | 字段 | 取值 |
|---|---|---|
| Run 执行 | execution_status | NOT_STARTED、READY、RUNNING、WAITING_USER、WAITING_EXTERNAL、WAITING_APPROVAL、BLOCKED、FAILED、COMPLETED、CANCELLED |
| Step 执行 | step_status | PENDING、READY、RUNNING、WAITING_EXTERNAL、WAITING_USER、WAITING_APPROVAL、COMPLETED、BLOCKED、FAILED、SKIPPED |
| 平台商品 | platform_status | UNKNOWN、NOT_SUBMITTED、SUBMITTED、UNDER_REVIEW、ACCEPTED、ACTIVE、PAUSED、REJECTED、OFFLINE |
| 证据核验 | verification_status | UNKNOWN、MANUAL_REPORTED、PENDING_VERIFICATION、VERIFIED、REJECTED、EXPIRED |

旧 Workflow status 保持旧语义。READY 表示有可执行步骤；ACCEPTED 表示平台接受，不等于在售；COMPLETED 表示本轮上线任务完成，不删除实例/监控。只有 platform_status=ACTIVE 且 verification_status=VERIFIED 才展示“已核验在售”。CONTRACT_TEST 环境即使具有该组合也只能显示“测试在售”。

## 2. 步骤定义

Profile steps 每项含 step_code、step_name、business_type、execution_mode、actor、sequence、required、blocking、applicability_condition、dependencies、entry_condition、completion_condition、evidence_requirements、available_actions、timeout_policy。

business_type：DATA_PREPARATION、PLATFORM_SUBMISSION、PLATFORM_REVIEW、PRICE_REVIEW、HUMAN_DECISION、STOCK_PREPARATION、COMPLIANCE、LABEL、EVIDENCE、PLATFORM_ACTIVATION、MONITORING。

execution_mode：SYSTEM_TASK、AI_ASSISTED、ADAPTER_TASK、MANUAL_TASK、EXTERNAL_WAIT。actor：SYSTEM、AI、USER、PLATFORM、FACTORY、REVIEWER。AI_ASSISTED 不授予自动完成权。

条件 DSL 只允许 all/any/not、eq/in/present、verified_artifact、asset_rights_allowed、cost_snapshot_current、capability_available、dependency_completed 等已注册谓词。输入来自服务端事实；客户端不能传任意条件代码或覆盖已发布 Profile。

实现语法（schema_version=1）：条件为布尔常量或单操作符对象；all/any 接条件数组，not 接单条件；eq/in 接 `{field,value}`，present 接字段路径；业务谓词接事实标识。例如 `{verified_artifact: "MARKET_REQUIRED"}`。路径只遍历服务端字典，禁止 eval 和属性执行；UNKNOWN 用 None 表达，not UNKNOWN 仍是 UNKNOWN。业务谓词只接受服务端明确布尔事实，不接受字符串“已核验”。条件中的 dependency_completed 必须引用 DAG 上游。深度、节点、列表及整份定义大小均有界。样本完成条件引用业务事实，不设置通用用户完成标记。

dependencies 是 step_code DAG，sequence 仅用于展示排序。可选步骤也有 applicability：条件 FALSE 才可 SKIPPED，条件 UNKNOWN 必须 BLOCKED；required 的适用步骤禁止手动跳过。并行节点各自求可执行性。已完成上游资料变更时，依赖该资料的确认应失效并留事件，不能静默保持旧批准。

## 3. Step 合法迁移

| 来源 | 目标 | 必须满足 |
|---|---|---|
| PENDING | READY | 适用条件为真、依赖满足、进入条件满足 |
| PENDING | SKIPPED | 确定性适用条件为假；保存理由与版本 |
| PENDING/READY | BLOCKED | 缺事实、权限/能力/合规条件不满足，保存 blocker |
| READY | RUNNING | 成功领取短任务、revision 一致、动作权限有效 |
| READY/RUNNING | WAITING_USER/WAITING_EXTERNAL/WAITING_APPROVAL | 已创建待办、外部意图或审批对象；释放租约 |
| RUNNING | COMPLETED | 业务 handler 结果与 completion_condition 均通过，证据版本固定 |
| WAITING_USER | READY | 人工提交证据被接受，重新求规则；按钮不能直接变 COMPLETED |
| WAITING_EXTERNAL | READY | 可信新外部事实到达，重新求规则 |
| WAITING_APPROVAL | READY | 有效批准且输入未变；必须再走执行与完成检查 |
| RUNNING | FAILED | 重试耗尽/不可重试异常，保留意图/现场 |
| BLOCKED | READY/PENDING | 缺项补齐后重新求依赖；不会无条件跳过 |
| FAILED | READY | 显式 RETRY，允许重试且外部不确定结果已核对；新失败 Action 需新建 |
| COMPLETED | BLOCKED | 上线前依赖证据撤销/过期/版本变化；保存旧完成证据和失效事件 |

REJECTED 是外部/证据状态，不借用 FAILED 抹去原因；重新报价或补交创建新 round/version，旧记录保留。已上线后的材料失效创建监控阻断/整改任务，不伪造平台已下架。

## 4. Run 聚合与终止

每次合法事务后从适用步骤计算，不接受客户端直接 set status。优先级：显式取消→CANCELLED；不可恢复失败→FAILED；无阻断且全部上线 required 完成→COMPLETED；存在必需阻断→BLOCKED；存在运行→RUNNING；存在可执行→READY；其余按 WAITING_APPROVAL、WAITING_USER、WAITING_EXTERNAL、NOT_STARTED 聚合。并行可做任务始终在 current_steps/available_actions 显示，不因摘要 BLOCKED 消失。

current_step 为展示焦点，不是唯一可运行节点。progress.total 是适用 required 上线步骤数，MONITORING 不进入分母；completed 仅满足条件的 COMPLETED；分母为零视为 Profile 错误。未适用步骤显示跳过原因，不算虚假完成。

CANCEL 仅允许未核验 ACTIVE 的流程，已有外部副作用时先核查撤销语义。ACTIVE/PAUSED 结束须确认 OFFLINE；取消不自动调用下架/退款。ENDED 以 ended_at 表达，不增加三套互相矛盾的终态。RELAUNCH 创建新轮次，不能将旧 COMPLETED 改回 PENDING。执行完成后的平台监控仍可更新 platform_status。

## 5. 平台状态与验证

| 事实 | 映射/行为 |
|---|---|
| HTTP 成功且有提交编号 | SUBMITTED；verification_status 仅表示回执验证，不表示在售 |
| 已签名/可信 read-back 审核中 | UNDER_REVIEW |
| 平台接受或核价通过 | ACCEPTED；继续履约/合规要求 |
| 平台明确商品可销售 + 所有 required 通过 + 在售证据 VERIFIED | ACTIVE |
| 人工自报“已上架” | 记录 MANUAL_REPORTED，平台摘要保持待核验，不直接 ACTIVE |
| Reviewer 核对可追溯外部材料 | 可升级证据 VERIFIED，source 保持 MANUAL，不显示 API verified |
| 平台已暂停/下架 | PAUSED/OFFLINE；保留已有上线历史和收入事实 |
| 不认识的 raw_status | UNKNOWN + PLATFORM_ERROR；原始记录保留，不自动推进 |

人工核验要求核验者具备对应审核权限且与报告者不同；仅打勾、不附来源/时间/外部对象不能核验。首期生产 Adapter 未声明 activation read-back 能力时使用该显式人工核验流程。

每次外部事件保留 raw_status、source、source_time、received_time、external_reference、external_object_type、mapping_version、source_revision。对已处理序号更旧的事件仅留审计，不回退状态；无法确定顺序的冲突进入人工核对。

## 6. 阻断原因与 NBA

blocker.code 固定为 MISSING_DATA、ASSET_RIGHTS_MISSING、PLATFORM_PENDING、COMPLIANCE_BLOCK、PRICE_UNACCEPTABLE、SUPPLY_UNAVAILABLE、STOCK_REQUIRED、USER_ACTION_REQUIRED、EXTERNAL_SERVICE_REQUIRED、PLATFORM_ERROR；另有 API 错误码不混用。每项含 message、step_code、owner_actor、evidence_refs、repair_action，可同时返回多项。`ASSET_RIGHTS_MISSING` 专指素材/权利证据缺口（M2-D）：入口指向商品详情素材区，`repair_action.connected` 随素材上传服务是否接入翻转；不得折回 MISSING_DATA 让用户去「补充商品资料」。

NBA = 服务端合法动作集合中的首选项，默认按安全依赖、阻断解除、到期时间、sequence 排序。AI 排序须仍为同一合法集合子集；若建议已过期返回 executable=false 和原因。所有动作携带 expected_revision、不可变证据指纹，提交后重新校验。

## 7. 动作目录与审批

| Action | 权限 | 风险/批准 | 效果与回滚 |
|---|---|---|---|
| COMPLETE_DATA | launch:manage + product:write/listing:write（按目标） | LOW，本地资料确认 | 引用已有资料，版本变化使确认失效 |
| SUBMIT_PLATFORM | launch:submit + listing:write | MEDIUM，复用 PUBLISH_LISTING 人工批准 | 保存提交意图；外部撤销另行批准 |
| REPORT_PRICE | launch:price_review | LOW，仅记录 | 新 PriceReview round，平台来源未验证则待核验 |
| ACCEPT_PRICE / COUNTER_PRICE | launch:price_review | MEDIUM，首期人工批准 | AiAction 目标 PriceReview；外部回执未确认保持等待；撤销以补偿动作完成 |
| ABANDON_PRODUCT | launch:manage | MEDIUM，人工确认 | 终止未上线本轮，不删除 Product；已在售不能借此下架 |
| REQUEST_STOCK / CONFIRM_STOCK | launch:stock_prepare | MEDIUM，本地确认；采购 HIGH 另行审批 | 更新 StockPreparation，不改销售库存；错误用新修订纠正 |
| UPLOAD_ARTIFACT / VERIFY_ARTIFACT | launch:compliance_manage；核验另需 compliance:approve | 上传 LOW、核验 MEDIUM 人工 | 新证据版本；核验撤回追加事件，保留历史 |
| GENERATE_LABEL / REGENERATE_LABEL | launch:label_manage | LOW，只本地生成 | 新 Asset 版本，无材料拒绝；不用反向删除审计 |
| UPLOAD_PHYSICAL_EVIDENCE / VERIFY_EVIDENCE | launch:label_manage；核验另需 compliance:approve | 上传 LOW、核验 MEDIUM 人工 | 新资产/核验事实，拒绝后补交新版本 |
| CONFIRM_ACTIVATION | launch:submit + compliance:approve（人工核验路径） | MEDIUM，独立人工核验 | 由可信材料/回读推进；误判产生更正事件，不擦除历史 |
| RETRY / CANCEL / RELAUNCH | launch:manage | 本地 LOW；外部补偿不包含在内 | 按本节前置条件运行，不复用失败或拒绝的 Action |

人工资料命令由 Service 校验并审计；AI 发起的经营写入必须复用 AiAction。Action 幂等摘要统一包含 tenant/workspace/run/step/action/input_revision/payload_hash，失败/拒绝后的新请求另加 predecessor_action_id；成功重放返回原结果，当前权限仍检查。外部调用幂等键持久化在意图中，网络重试不生成新键。

## 8. 两个本地 Profile 的 DAG

SIMPLE_CONTRACT：INFORMATION → COMPLIANCE → SUBMISSION → ACTIVATION；ACTIVATION 之后 MONITORING。mode=CONTRACT_TEST、verification=UNVERIFIED，测试事件来源明确。支持声明的四种履约模式时，分别增加对应的供给/库存前置检查，不把平台备货强加给 DROPSHIP。

COMPLEX_CONTRACT（用户全托管样本，PLATFORM_STOCK）：

```text
PRODUCT_INFORMATION → PLATFORM_ATTRIBUTES → PRODUCT_CREATED → PRICE_REVIEW → PRICE_DECISION
PRODUCT_INFORMATION → MARKET_COMPLIANCE
PRICE_DECISION → FIRST_ORDER → STOCK_PREPARATION
MARKET_COMPLIANCE + PLATFORM_ATTRIBUTES → LABEL_PREPARATION
STOCK_PREPARATION + LABEL_PREPARATION → PHYSICAL_EVIDENCE
PRICE_DECISION + MARKET_COMPLIANCE + PHYSICAL_EVIDENCE → READY_FOR_SALE → ACTIVE → MONITORING
```

这是 DAG，可并行准备合规与等待核价。COUNTER 回到外部等待但不在 DAG 加环：创建新核价 round，PRICE_DECISION 的当前证据指向新轮次。required 节点不能被低成本“通用完成”接口跳过。

## 9. 故障与超时

短任务租约到期可由同 flow_kind worker 领取；依据持久 checkpoint 先核查外部结果。等待步骤只有 deadline_at，无占用线程。timeout_policy 定义 notify_after、fail_after、max_attempts、retryable_errors；无明确 deadline 不凭空失败。通知事件按 run/step/deadline 去重。进程重启不得重发已成功的发布、采购或已拒绝审批。

## 10. 当前实现边界（2026-10-12）

`launch_rules.evaluate_readiness` 实现依赖图就绪计算、阻断聚合、进度分母和已完成依据失效处理；`launch_runtime.refresh_launch` 将结果以 revision CAS 与事件同事务写入。它不自动完成步骤，不重启 WAITING/FAILED 任务，不替代动作 handler。服务端事实未知时保持未知；上线后整改不更改平台状态。合法动作、依赖证据版本指纹、审批恢复和外部同步仍待后续领域服务与执行器接入。
