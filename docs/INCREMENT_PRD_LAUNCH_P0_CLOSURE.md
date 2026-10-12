# 增量 PRD：Launch Center P0 闭环（B01/B02/B10 + F01/F02/F03）

> 版本：v1（2026-10-12）。依据提交 `5a0ae0f` 的代码现状撰写；所有「未实现」判断以当前代码为准，不把历史文档中未实现的字段当作已存在。
> 上游依据：`docs/LAUNCH_CENTER_PRODUCT_DESIGN.md`（FROZEN，DTO/权限/API 依据）、`docs/PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md`、`docs/PLATFORM_WORKFLOW_STATE_MODEL.md`、`docs/PLATFORM_WORKFLOW_PROGRESS.md`。

## 0. 项目信息

- Language：中文
- Programming Language：后端 Python 3.11 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + SQLite；前端 Vue3 + Vite + Element Plus
- Project Name：launch_center_p0_closure
- 原始需求复述（关键部分）：业务闭环「选择商品 → 选择店铺 → 系统引导直到上线」尚未完成，前端入口分散、缺少统一流程入口。用户不需要记住去哪个菜单，就能知道商品进行到哪里、为什么卡住、由谁处理、下一步怎么做。

## 1. 本轮目标与范围

**目标**：在既有 Launch runtime（版本化 Profile、Run/Step/Event 持久化、店铺派生草稿、确定性就绪度 DAG 与原子刷新、素材权利门禁）之上，补齐「动作执行 → 确定性 NBA → Launch API → 上线中心页面」的 P0 最小闭环，使引导、阻断、负责人、下一步在本地可端到端验证。

### 做（P0）

| 编号 | 内容 |
|---|---|
| B01 | 动作执行框架：幂等（Idempotency-Key）、`expected_revision` CAS、权限/Scope 校验、步骤状态机守卫、不可变事件与回执、失败重试（RETRY）、取消（CANCEL/ABANDON_PRODUCT）、进程级恢复（重读不重发） |
| B01 | Handler：COMPLETE_DATA、SUBMIT_PLATFORM（复用 PUBLISH_LISTING 审批队列）、CONFIRM_ACTIVATION（独立人工核验路径）、RETRY、CANCEL |
| B02 | 确定性 Next Best Action：allowed_actions / blocked_reason / owner / next_best_action；AI 只解释或排序 |
| B10 | Launch API：GET context、POST launch（创建/relaunch）、GET 列表、GET 详情、GET steps、POST actions/{action}、POST sync、GET events；P1：GET products/{id}/channels |
| F01 | 上线中心列表（商品、店铺、市场、阶段、进度、阻断、下一动作、负责人；筛选） |
| F02 | 上线中心详情（流程时间线含并行分组；步骤详情含材料/平台反馈/证据/错误/可执行动作） |
| F03 | Guided/Professional 基础版双模式（同页切换信息密度） |
| B12（本轮部分） | 接口契约测试、动作/NBA 单测、HTTP 权限/Scope/分页测试、Playwright F01-F03 本地 E2E、全量回归门禁 |

### 不做（明确排除）

- B03-B09：核价、备货、合规 Artifact、标签、实拍等领域服务及其动作 handler。这些步骤的动作本轮 `executable=false` 并展示禁用原因（「未接通/领域服务建设中」），这是冻结设计「缺 API 的步骤保留为人工/外部任务，界面显示未接通」的落实，不是遗漏。
- B11：外部事件/Webhook 接入（`/api/launch/webhooks/...`）与真实平台 Adapter 联调，继续标注 UNVERIFIED。
- F04-F10：Asset Center 共享组件、Product 深链集成、Factory 门户投影等前端增量。
- PATCH /api/launch/context 与 Membership 体验偏好列（F03 仅基础版）。
- AI 生成建议内容：本轮 `recommendations` 仅允许 `source=rule` 的确定性解释条目。
- 主库迁移、真实店铺写入、外部账号访问。

**闭环边界（诚实声明）**：本轮闭环的是流程机制与可视/可执行性——创建、引导、动作、事件、刷新、取消/重试/恢复全链路本地可跑。受领域服务进度约束，本地样本中仅「商品资料」步骤可被确定性完成，其余步骤保持就绪度规则给出的真实状态（READY 但动作未接通，或 PENDING/BLOCKED）并给出原因与负责人。不得将此轮宣传为「业务全链路已上线」。

## 2. 用户故事

### OWNER / OPERATOR（运营）

1. 作为运营，我想在上线中心看到我负责商品的全部上线流程、当前阶段、卡点与下一步，不用记住去哪个菜单。
2. 作为运营，我想对就绪的资料步骤执行完成动作，且系统按服务端事实校验，不接受我的勾选代替核验。
3. 作为运营，我想提交平台发布并复用既有审批队列；成功后明确看到「已提交，等待平台」，而不是「已在售」。
4. 作为运营，我想取消未上线的流程或重试失败步骤；取消不得悄悄调用外部下架或退款。
5. 作为 Owner，我想以独立核验人身份完成在售核验（与报告人不同），核验记录可追溯；误判可更正但不擦除历史。

### COMPLIANCE（合规员）

1. 作为合规员，我想在合规投影下处理合规步骤与证据，看不到核价、供应价与财务载荷。
2. 作为合规员，我不想收到价格、备货类动作按钮；越权调用返回 403。

### READ_ONLY（只读成员）

1. 作为只读成员，我想查看状态、阻断原因与负责人，但没有写按钮；直接调用写接口返回 403。

### Factory（工厂协作方）

1. 作为工厂协作方，我想通过既有供应门户看本厂指派步骤；不能通过 URL 读取卖家的上线详情（404）。

## 3. 功能需求与验收标准

优先级：P0=必须有，P1=应该有，P2=nice to have。验收标准为可测试断言。

### FR-1 Launch 列表 API（P0，B10）

- AC-1.1 `GET /api/launch` 支持分页（`page_num`/`page_size`，上限 200，超限 422）与筛选参数；服务端先 Store Scope 过滤再排序分页，`total` 不含不可见记录。
- AC-1.2 列表项包含 F01 全部列字段：商品、店铺、市场、履约方式、执行/平台/验证三态、进度（完成数/总数）、阻断摘要、下一动作、责任人、AI 建议占位。
- AC-1.3 默认仅返回活跃轮次（`active_slot=1`）；`include_history=true` 时含已结束轮次并以 `is_history` 标注。
- AC-1.4 `mine=true` 返回存在分配给当前用户的非终态步骤（READY/WAITING_USER/WAITING_APPROVAL/FAILED）的 Launch。
- AC-1.5 「等待平台」筛选按 `platform_status ∈ {SUBMITTED, UNDER_REVIEW}` 或存在 WAITING_EXTERNAL 步骤匹配；「被阻断」筛选按执行态 BLOCKED/FAILED 匹配。
- AC-1.6 排序默认 `created_at` 倒序；本轮不开放自定义排序参数（传入即 422）。

### FR-2 Launch 详情 API（P0，B10）

- AC-2.1 `GET /api/launch/{id}` 返回冻结详情 DTO 全字段（架构 §8）：三态、`profile{key,version,hash}`、`revision`、`progress`、`current_steps`、`blockers`、`available_actions`、`next_best_action`、`recommendations`、`steps`、`last_synced_at`、`professional_links`、`monitoring`。
- AC-2.2 具备 `launch:manage` 的调用方读取详情时执行确定性刷新（复用 launch_runtime 计算段；无变化不增版）；只读方仅计算不落库、不改变 `revision`。
- AC-2.3 `monitoring` 在经营数据未接入时返回 `UNAVAILABLE` 与原因，不用 Workspace 总额冒充单店表现。
- AC-2.4 `recommendations` 本轮仅 `source=rule` 的确定性解释条目；无 AI 生成内容。
- AC-2.5 `environment=CONTRACT_TEST` 或 Profile `verification_status=UNVERIFIED` 时，详情携带 `verification_notice="本地流程验证，不代表真实平台接入"`。

### FR-3 步骤 DTO 与角色投影（P0，B10）

- AC-3.1 `GET /api/launch/{id}/steps` 返回步骤 DTO：状态、依赖、证据要求、证据引用、外部反馈（status/reference/type）、责任人、动作清单（含禁用原因）。
- AC-3.2 COMPLIANCE 角色投影：DTO 不含价格、成本、利润率、备货数量字段；价格/备货动作不出现在其动作清单（自本轮起即为契约，后续领域接入不得破坏）。
- AC-3.3 READ_ONLY：可读列表/详情/步骤/事件；所有写端点 403。
- AC-3.4 Factory 身份访问全部 `/api/launch/*` 返回 404（不泄露存在性）；工厂入口维持既有供应门户。

### FR-4 动作执行框架（P0，B01）

- AC-4.1 重复提交同一幂等键与相同载荷返回同一执行结果（同一 `event_id` 与回执），不重复创建事件、不重复产生外部意图。
- AC-4.2 同一幂等键不同载荷返回 409 `IDEMPOTENCY_CONFLICT`，且零状态变更。
- AC-4.3 `expected_revision` 与当前 `run.revision` 不一致返回 409 `REVISION_CONFLICT`，响应带 `current_revision`，状态零变更。
- AC-4.4 动作不在该步骤冻结快照的 `available_actions` 内返回 409 `ACTION_NOT_ALLOWED`。
- AC-4.5 步骤状态不满足动作来源状态返回 409 `STEP_STATE_CONFLICT` 并附阻断原因。
- AC-4.6 缺少权限返回 403 且不产生事件；跨租户/跨 Scope 返回 404。
- AC-4.7 缺少 `Idempotency-Key` 请求头返回 400 `IDEMPOTENCY_REQUIRED`（键非空且 ≤128 字符）。
- AC-4.8 每次执行写入不可变 `WorkflowEvent`，`before/after/payload` 含 action、payload_hash、证据指纹、run revision、actor。
- AC-4.9 两个动作并发使用同一 `expected_revision`，只有一个成功，另一个 409（步骤条件更新保证）。
- AC-4.10 高危动作（SUBMIT_PLATFORM/CONFIRM_ACTIVATION/CANCEL）409 时不自动重发；响应信息足以让前端保留用户未提交输入并刷新状态。

### FR-5 COMPLETE_DATA（P0，B01）

- AC-5.1 「商品资料」步骤在其 `completion_condition` 被服务端事实确定满足（如 SIMPLE 样本：`product.title` 存在且素材权利 `PUBLISHABLE`）时可执行；执行后 `step_status=COMPLETED`，证据固定为 `{input_revision, facts_digest, completed_by, completed_at}`。
- AC-5.2 条件不满足（如素材权利未通过）返回 409 `ACTION_PRECONDITION_FAILED`，`blockers` 含具体缺项（复用 `asset_rights.reasons`），步骤保持 READY。
- AC-5.3 动作不接受任何客户端「完成标记」参数；payload 仅允许备注类字段。
- AC-5.4 完成事实未接入的步骤（如平台属性、上线前检查）其 COMPLETE_DATA `executable=false` 且带 `disabled_reason`，调用返回 409 而不是假成功。

### FR-6 SUBMIT_PLATFORM（P0，B01）

- AC-6.1 预检（复用 `publish_facts`：平台规则、合规闸门、素材权利、上架复核、店铺授权/市场/绑定）任一失败返回 409，不创建 AiAction、不产生 Attempt。
- AC-6.2 预检通过时创建或复用 `PUBLISH_LISTING` AiAction（`PENDING_APPROVAL`），步骤转 `WAITING_APPROVAL`，事件含 `action_id` 与指纹；同一 Launch 步骤在既有 Action 处于非终态（PENDING_APPROVAL/APPROVED/EXECUTING/SUCCESS）时重复提交复用同一 Action，不产生第二个意图；既有 Action 已终态（REJECTED/FAILED）时同内容重提创建新意图（客户端须带新幂等键），不得死锁复用终态 Action。
- AC-6.3 审批与执行复用既有 `/api/actions/{id}/approve|execute`；执行成功产生 succeeded Attempt 后，详情/sync 刷新使步骤按完成条件完成并固定回执证据（`attempt_id`、`external_id`、`platform_status=SUBMITTED`、`verification_status`）。
- AC-6.4 提交成功不得将 `platform_status` 置 ACTIVE、不得置 `verification_status=VERIFIED`；界面文案为「已提交，等待平台」。
- AC-6.5 执行失败（AiAction FAILED）时步骤转 FAILED 并记录错误，RETRY 可用；外部结果不确定时步骤保持 RUNNING 并标注「结果待核查」，不自动重发。
- AC-6.6 店铺派生草稿绑定校验：非绑定店铺提交返回 409（复用 `publish_targets` 约束）。

### FR-7 CONFIRM_ACTIVATION（P0，B01）

- AC-7.1 执行者须同时具备 `launch:submit` 与 `compliance:approve`，且与提交/报告人不同，否则 403/409。
- AC-7.2 payload 必须含 `material_ref` 与 `note`（来源/时间/外部对象）；仅勾选无法执行（409 `ACTION_PRECONDITION_FAILED`）。
- AC-7.3 执行后写核验记录（步骤证据 + 事件：`reviewer_id`/`material_ref`/`note`/`reviewed_at`），`platform_status=ACTIVE`、`verification_status=VERIFIED`（source=MANUAL，不显示 API verified），步骤 COMPLETED。
- AC-7.4 CONTRACT_TEST 环境下界面显示「测试在售」及「本地流程验证，不代表真实平台接入」，不得显示真实已核验在售表述。
- AC-7.5 误判更正通过新事件完成，不擦除历史核验记录。
- AC-7.6 已核验在售的流程不能通过 CANCEL 下架（409）。

### FR-8 RETRY / CANCEL / 恢复（P0，B01）

- AC-8.1 FAILED 步骤 RETRY 后回 READY（或经规则重算），`attempts+1`，事件记录 predecessor；复用失败/拒绝的 Action 被拒绝。
- AC-8.2 外部不确定结果未核对前 RETRY 返回 409（结果待核查）。
- AC-8.3 CANCEL 仅允许未核验 ACTIVE 的流程；执行后 `execution_status=CANCELLED`、写 `ended_at`、释放 `active_slot`，事件记录；不调用任何外部下架/退款。
- AC-8.4 CANCELLED 为终态（写 `ended_at`、释放 `active_slot`）；COMPLETED 流程保留活跃槽（见 §8.1），本轮不可 relaunch、不可 CANCEL。重新上线必须创建新轮次（`previous_run_id` 仅接受已 CANCEL 结束的同一销售对象流程），旧回执/审批不继承。
- AC-8.5 进程重启后：有持久外部意图的 RUNNING 步骤只重读不重发；无意图的 RUNNING 步骤恢复为 READY；已成功外部调用不重复（Attempt 幂等）。
- AC-8.6 ABANDON_PRODUCT 与 CANCEL 同语义终止本轮，不删除 Product。

### FR-9 确定性 Next Best Action（P0，B02）

- AC-9.1 `allowed_actions` 仅含 `executable=true` 的动作，每项带 `step_code`、所需权限、`approval_required`、`expected_revision`、证据指纹、`risk`。
- AC-9.2 输入仅为服务端事实（就绪度计划、步骤状态、阻断原因、负责人、当前权限）；同一事实两次计算输出一致（确定性）。
- AC-9.3 `blocked_reason` 来自就绪度计划 blockers，每项含 `code/message/step_code/owner_actor`。
- AC-9.4 `owner` 为当前焦点步骤的负责人（actor + `assigned_user_id`；PLATFORM→平台；FACTORY→工厂门户；SYSTEM/REVIEWER→角色提示）。
- AC-9.5 `next_best_action` 按冻结排序（安全依赖 → 阻断解除 → 到期时间 → sequence）取首项；无 executable 动作时返回首项禁用动作及原因。
- AC-9.6 步骤 READY 但动作未接通时返回 `disabled_actions[{action, disabled_reason}]`，供 UI 展示禁用原因。
- AC-9.7 AI 层只能解释或重排 `allowed_actions` 的子集；AI 输出不得包含集合外动作；过期建议返回 `executable=false` 与原因。
- AC-9.8 并行分支：运行摘要 BLOCKED 时，其他 READY 节点仍出现在 `allowed_actions`/`current_steps`，不因摘要消失。

### FR-10 同步 sync（P0，B10）

- AC-10.1 仅支持 `mode=refresh`；其他模式返回 422 `SYNC_MODE_UNSUPPORTED` 并带 `supported` 列表。
- AC-10.2 refresh 重读服务端事实并按 revision CAS 落库；无变化不增版；并发旧 revision 409 `REVISION_CONFLICT`。
- AC-10.3 sync 不接受人工状态输入：载荷中出现 `platform_status`/`verification_status`（含试图指定 VERIFIED/ACTIVE）返回 422。
- AC-10.4 READ_ONLY 调用 sync 返回 403；`launch:manage` 可调用。
- AC-10.5 每次成功 sync 更新 `last_synced_at`，不触发 revision 变化。
- AC-10.6 列表逐行计算时单行事实异常（如 `LAUNCH_CONTEXT_CHANGED`）不使整页失败，该行以降级阻断摘要展示。

### FR-11 事件审计（P0，B10）

- AC-11.1 `GET /api/launch/{id}/events` 分页返回不可变事件（`sequence` 升序），字段含 `event_type/actor_id/source/occurred_at/before/after/payload`。
- AC-11.2 事件 payload 经脱敏（复用 `pii_redact`），不含凭证、买方 PII。
- AC-11.3 事件只增不改：无更新/删除端点；越界页码返回空列表而非错误。

### FR-12 商品渠道聚合（P1，B10）

- AC-12.1 `GET /api/products/{id}/channels` 返回该商品各销售店铺的当前活跃 Launch 与历史轮次；Scope 外店铺不出现且不计入总数。
- AC-12.2 母稿 `Listing.status=published` 不渲染为「已核验在售」；平台状态与验证状态分列展示。
- AC-12.3 同平台多店不合并为一行。

### FR-13 上线入口与创建（P0，B10）

- AC-13.1 `GET /api/launch/context` 返回 Scope 内销售店铺、`effective_experience_mode`、launch 权限键、`can_create` 及不可创建原因（如无适用 Profile、店铺缺市场/履约配置）。
- AC-13.2 `POST /api/launch` 复用 `create_launch`：同键同载荷重放返回同一流程；同键异载荷 409；已存在活跃流程返回 409 + `existing_launch_id`（前端打开已有流程，不静默重启）。
- AC-13.3 relaunch：`previous_run_id` 必须指向已结束（CANCELLED）的同一销售对象流程，否则 409；新轮次创建新草稿与新发布意图。COMPLETED 流程本轮保留活跃槽，不能作为 `previous_run`（见 §8.1）。
- AC-13.4 创建成功返回详情 DTO（含首屏就绪度与 NBA）。
- AC-13.5 `environment=PRODUCTION` 因无已发布生产 Profile 自然返回 404 `PROFILE_NOT_FOUND`，不伪造可用性。

### FR-14 前端 F01 上线中心列表（P0）

- AC-14.1 列齐全：商品、目标平台/Store、国家、履约方式、当前执行/平台状态、完成数/总数、阻断摘要、下一动作、责任人。
- AC-14.2 「等待平台」状态显示文字「等待平台反馈」，不使用失败红色；UNKNOWN 不显示为绿色完成。
- AC-14.3 筛选：商品/Store/平台/市场/执行状态/责任人/需我处理/历史；默认仅活跃轮次，可展开历史重上线。
- AC-14.4 分页与 Scope：服务端先 Scope 后分页，总数不含不可见记录；跨 Scope 记录不出现在任何页。
- AC-14.5 空状态分因展示（无商品/无销售店/无适用 Profile/无匹配筛选/没有权限/请求失败）且可重试；未知状态下禁止继续执行旧动作（按钮禁用并引导刷新）。
- AC-14.6 CONTRACT_TEST 行显示「本地流程验证，不代表真实平台接入」标注。
- AC-14.7 点击行进入详情并带回列表筛选状态（`return_to`）。

### FR-15 前端 F02 上线中心详情（P0）

- AC-15.1 左侧流程时间线按 sequence 展示并行分组与依赖标记；不是固定线性进度条。
- AC-15.2 「可并行处理」区列出其他 READY 节点；当前焦点不是唯一可操作步骤。
- AC-15.3 点击步骤右侧展示：说明、要求（evidence_requirements）、缺项、证据（evidence_refs/result）、外部反馈（external_status/reference/type）、责任人、下一动作、可执行动作。
- AC-15.4 三类状态摘要（执行/平台/验证）分区明确；等待平台与失败文案区分。
- AC-15.5 动作执行使用 `expected_revision` 与 `Idempotency-Key`；409 时保留用户未提交输入、刷新状态并说明变化，不自动再次确认高风险动作。
- AC-15.6 超时/不确定显示「结果待核查」，不诱导连续重发。
- AC-15.7 禁用动作按钮展示禁用原因（含「未接通/领域服务建设中」）。
- AC-15.8 COMPLETED 依据失效显示整改阻断，不擦除历史完成。
- AC-15.9 Factory 身份访问详情 404；READ_ONLY 无写按钮。

### FR-16 前端 F03 Guided/Professional 基础版（P0）

- AC-16.1 同一路由同一组件切换信息密度；不更换页面、不重新鉴权、不改变数据与权限。
- AC-16.2 GUIDED 使用业务语言摘要（数值来自 DTO，如「你的商品已完成 4/9；平台正在核价」），保留关键风险、费用、批准提示和证据来源。
- AC-16.3 PROFESSIONAL 同页展开 raw 状态、external_reference/type、mapping_version（步骤）、Profile hash、revision、同步时间；未接入字段显示「未接入」占位，不伪造数值。
- AC-16.4 浏览器临时切换不具有授权含义，刷新后回到 Workspace 默认（`context.effective_experience_mode`）并明示。
- AC-16.5 两种模式对同一 Launch 实例状态一致（切换前后 DTO 不变）。

### FR-17 诚实标注与测试 Profile（P0）

- AC-17.1 所有 CONTRACT_TEST Profile/流程在列表、详情、动作回执、事件中可识别 `environment` 与 `verification_status=UNVERIFIED`。
- AC-17.2 测试数据不计入经营指标（复用既有 source/demo/contract 排除规则）。
- AC-17.3 未接入领域（核价/备货/Artifact/Label/实拍/监控）全部显示未接通，不得伪装完成。

### FR-18 测试与门禁（P0，B12 本轮部分）

- AC-18.1 新增测试覆盖：动作框架（幂等/并发/权限/Scope/状态守卫）、NBA 确定性、HTTP 契约（分页/筛选/错误结构/投影）、取消/重试/恢复语义。
- AC-18.2 全量 pytest 正反序通过数不低于进度文档 §12 基线（821 passed / 2 xfailed / 1 xpassed），并补齐记录 §13 未记录的全量结果。
- AC-18.3 Playwright F01-F03 以真实本地后端 + 隔离库运行，不只 mock DTO 截图；API/数据库断言证明状态与隔离。
- AC-18.4 ruff、文档一致性检查（total=0）、`git diff --check` 通过。
- AC-18.5 本轮预计零迁移；若 CONFIRM_ACTIVATION 核验记录需独立表，按既有 Expand 纪律做最小迁移 + 合成历史库 roundtrip 演练。不访问主库/真实店铺/外部账号。

## 4. 动作执行矩阵

### 4.1 通用执行前校验（所有动作）

1. 身份与范围：`fresh_context` 复核当前身份；`resolve_store_scope` 解析店铺范围；`owned_launch` 校验租户/Workspace/flow_kind/店铺归属（失败 404，不泄露存在性）。
2. 版本：`expected_revision == run.revision`，否则 409 `REVISION_CONFLICT`（带 `current_revision`）。
3. 生命周期：`ended_at is None` 且 `execution_status != CANCELLED`，否则 409 `LAUNCH_ENDED`。
4. 动作目录：动作 ∈ 该步骤冻结快照的 `available_actions`，否则 409 `ACTION_NOT_ALLOWED`。
5. 步骤状态：满足动作的来源状态（见矩阵），否则 409 `STEP_STATE_CONFLICT`。
6. 权限：按状态模型 §7 动作目录校验（缺权限 403，零状态变更）。
7. 幂等：`Idempotency-Key` 必填（≤128 字符）；同键同载荷重放原结果（仍复核当前权限），同键异载荷 409。
8. 就绪度：动作必须出现在当前 NBA 的 `allowed_actions`（即前置被规则确定满足），否则 409 `ACTION_PRECONDITION_FAILED` 并附 blockers。

### 4.2 矩阵

| 步骤类型 | 允许动作（本轮） | 权限 | 状态流转 | 执行后效果（事件/回执） | 失败与重试 | 取消与恢复 |
|---|---|---|---|---|---|---|
| DATA_PREPARATION | COMPLETE_DATA | `launch:manage` + `product:write`/`listing:write`（按目标） | READY → COMPLETED | `LaunchActionExecuted` 事件；证据固定 `{input_revision, facts_digest, completed_by, completed_at}`；回执 `{step_code, step_status, evidence_digest}` | 条件不满足 409，不产生 FAILED；完成后依据失效由既有规则转整改阻断 | 不适用 |
| PLATFORM_SUBMISSION | SUBMIT_PLATFORM | `launch:submit` + `listing:write` | READY → RUNNING → WAITING_APPROVAL；回执到达后按完成条件 COMPLETED | 创建/复用 `PUBLISH_LISTING` AiAction（PENDING_APPROVAL）；事件含 `action_id`、指纹、`expected_revision`；回执 `{action_id, approval_required:true}` | 预检失败 409 不建 Action；执行失败 AiAction FAILED、步骤 FAILED、RETRY 可用；外部不确定保持 RUNNING「结果待核查」不重发 | 取消不自动撤销外部提交 |
| PLATFORM_ACTIVATION | CONFIRM_ACTIVATION | `launch:submit` + `compliance:approve`，且核验人 ≠ 报告人 | READY → COMPLETED（附核验记录） | 核验记录写入步骤证据 + 事件（reviewer/material_ref/note/reviewed_at）；`platform_status=ACTIVE`、`verification_status=VERIFIED`（source=MANUAL）；CONTRACT_TEST 标注测试在售 | 材料不足 409；误判以更正事件处理，不擦除历史 | 已核验在售不可 CANCEL |
| 任意 FAILED 步骤 | RETRY | `launch:manage` | FAILED → READY（经规则重算） | `LaunchActionRetried` 事件，记录 predecessor 与 attempts+1 | 外部不确定结果未核对返回 409；不允许复用失败/拒绝的 Action（须新幂等键） | — |
| Run 级 | CANCEL / ABANDON_PRODUCT | `launch:manage` + 人工确认（note + confirm） | 任意未激活 → CANCELLED | `LaunchCancelled` 事件；`ended_at` 写入、`active_slot` 释放；不调用外部下架/退款 | — | 终态；恢复 = relaunch 新轮次（`previous_run_id`）；本轮「结束」仅此一条路径（§8.1） |
| 进程级（无用户动作） | 恢复扫描 | `launch:manage`（经 sync） | RUNNING/WAITING_* 保持或回收 | 重启后有意图 RUNNING 只重读不重发；无意图 RUNNING → READY；已成功外部调用不重复（Attempt 幂等） | — | — |

### 4.3 本轮不实现 handler 的动作（B03-B09 范围）

REPORT_PRICE、ACCEPT_PRICE、COUNTER_PRICE、REQUEST_STOCK、CONFIRM_STOCK、UPLOAD_ARTIFACT、VERIFY_ARTIFACT、GENERATE_LABEL、REGENERATE_LABEL、UPLOAD_PHYSICAL_EVIDENCE、VERIFY_EVIDENCE：步骤仍按冻结定义出现在 DTO 与动作清单中，但 `executable=false` 且 `disabled_reason` 指向责任领域与后续批次；直接调用返回 409 `ACTION_NOT_ALLOWED`（附原因）。COMPLIANCE 步骤在本地样本中为 READY 且其上传/核验动作处于上述禁用状态，界面显示「未接通」，负责人为合规角色。

### 4.4 失败、重试、取消与恢复语义（通用）

- **失败分类**：handler 异常 → 步骤 FAILED、`attempts+1`、错误脱敏入库；错误在 `timeout_policy.retryable_errors` 且未耗尽时 RETRY 可用。外部调用结果不确定（UNCERTAIN）→ 步骤保持 RUNNING 并标注「结果待核查」，sync/read-back 解决，禁止自动重发。
- **重试**：仅显式 RETRY；新请求必须带新幂等键并在事件中记录 predecessor；重试不复用已失败/已拒绝的 AiAction。
- **取消**：仅未核验 ACTIVE 的流程；纯本地状态变更 + 事件；不具备外部补偿语义（撤销另行审批）。
- **恢复**：进程重启不重发已成功外部调用（Attempt/AiAction 幂等重放）；WAITING 步骤恢复等待；CANCELLED/COMPLETED 不恢复，重新上线走新轮次。

## 5. NBA 规则（B02）

### 5.1 确定性输入（仅服务端事实）

- 就绪度计划（`evaluate_readiness` 输出：步骤状态、runnable_steps、blockers、progress）
- 步骤持久状态与冻结定义快照（`available_actions`、actor、sequence、timeout_policy）
- 阻断原因（`blockers[]`：code/message/step_code/owner_actor）
- 负责人（步骤 actor + `assigned_user_id`；运行创建者兜底）
- 当前身份权限与 Store Scope
- handler 可用性（本轮已实现动作清单）

### 5.2 输出结构

```json
{
  "allowed_actions": [
    {"action": "COMPLETE_DATA", "step_code": "INFORMATION", "permission": "launch:manage",
     "approval_required": false, "risk": "LOW", "expected_revision": 2,
     "evidence_fingerprint": "<facts_digest>"}
  ],
  "disabled_actions": [
    {"action": "UPLOAD_ARTIFACT", "step_code": "COMPLIANCE",
     "disabled_reason": "合规材料服务未接入（后续批次）"}
  ],
  "blocked_reason": [
    {"code": "COMPLIANCE_BLOCK", "message": "...", "step_code": "COMPLIANCE", "owner_actor": "USER"}
  ],
  "owner": {"actor": "USER", "user_id": 1, "role_hint": "OPERATOR"},
  "next_best_action": {"action": "COMPLETE_DATA", "step_code": "INFORMATION", "executable": true},
  "ordering": "rule"
}
```

排序（冻结）：安全依赖（不依赖外部确认者优先）→ 阻断解除（可解除阻断者优先）→ 到期时间 → sequence。`next_best_action` 取排序首项；无 executable 动作时返回首项禁用动作及原因。

### 5.3 AI 边界

AI 只能对 `allowed_actions` 做解释或重排（子集），不得新增动作、不得放宽前置；AI 建议过期时返回 `executable=false` 与原因；所有动作提交时携带 `expected_revision` 与不可变证据指纹并重新校验。本轮 `recommendations` 仅 `source=rule` 条目。

## 6. Launch API 契约草案

### 6.1 端点

| 方法与路径 | 优先级 | 权限 | 语义 |
|---|---|---|---|
| GET /api/launch/context | P0 | launch:read | Scope 内销售店铺、`effective_experience_mode`、launch 权限键、`can_create` 与原因 |
| POST /api/launch | P0 | launch:create（+listing:write/product:read） | 创建/relaunch；`Idempotency-Key` 头；body `{product_id, shop_id, parent_listing_id?, previous_run_id?, environment?}` |
| GET /api/launch | P0 | launch:read | 列表：`page_num`/`page_size`（≤200）+ 筛选；先 Scope 后分页 |
| GET /api/launch/{id} | P0 | launch:read | 详情 DTO；launch:manage 调用方触发确定性刷新 |
| GET /api/launch/{id}/steps | P0 | launch:read | 步骤 DTO（角色投影） |
| POST /api/launch/{id}/actions/{action} | P0 | 见矩阵 | body `{step_code, expected_revision, payload, note?}` + `Idempotency-Key` 头 |
| POST /api/launch/{id}/sync | P0 | launch:manage | body `{mode:"refresh", expected_revision}` |
| GET /api/launch/{id}/events | P0 | launch:read | 事件分页（脱敏） |
| GET /api/products/{id}/channels | P1 | product:read + Scope | 商品渠道聚合 |

### 6.2 关键 DTO 字段

**LaunchListItem**：`id, environment, verification_notice?, product{id,title,sku,category}, store{id,name,platform}, market, fulfillment_mode, execution_status, platform_status, verification_status, progress{completed,total}, blocked_summary[{code,message,step_code,owner_actor}], next_action{action,step_code,executable,reason?,owner}, owner{actor,user_id,role_hint?}, profile{key,version}, revision, is_history, created_at`。

**LaunchDetail**（ListItem +）：`profile.hash, current_steps[], blockers[], available_actions[], next_best_action, recommendations[{target,reason,source}], steps[StepDTO], last_synced_at, professional_links[{product_id,listing_id,shop_id,step_code,return_to}], monitoring{status,reason}, previous_run_id`。

**StepDTO**：`step_code, step_name, business_type, execution_mode, actor, sequence, required, dependencies[], step_status, blocking_reason{}, evidence_requirements[], evidence_refs[], external{status,reference,type}, assigned_user_id, input_revision, available_actions[{action, executable, disabled_reason?}]`。

**ActionExecuteResponse**：`{revision, action, status: EXECUTED|PENDING_APPROVAL|FAILED, step{step_code,step_status}, receipt{...}, event_id, launch: LaunchDetail}`。

**SyncRequest/Response**：请求 `{mode, expected_revision}`；响应 `{refreshed: bool, revision, launch: LaunchDetail}`。

**ContextResponse**：`{shops[{id,name,platform,market,store_type,account_type,business_mode,fulfillment_mode,is_demo,status}], effective_experience_mode, permissions[], can_create, blocked_reason?}`。

### 6.3 分页与筛选参数（GET /api/launch）

`page_num`（≥1）、`page_size`（1-200，超限 422）、`product_id?`、`shop_id?`、`platform?`、`market?`、`execution_status?`、`owner_user_id?`、`mine?`、`waiting_platform?`、`blocked_only?`、`include_history?`。响应 `{items[], total, page_num, page_size}`。未知筛选值返回 422 并列出合法值，不静默忽略。

### 6.4 错误码

统一错误体 `{code, message, blockers[], current_revision?}`；跨 Scope 404；权限 403；状态/版本冲突 409；参数 422。

| code | HTTP | 含义 |
|---|---|---|
| IDEMPOTENCY_REQUIRED | 400 | 缺少/非法幂等键 |
| IDEMPOTENCY_CONFLICT | 409 | 同键不同载荷 |
| REVISION_REQUIRED / REVISION_CONFLICT | 400 / 409 | 版本缺失 / 版本已变化（带 current_revision） |
| LAUNCH_NOT_FOUND | 404 | 不存在或越权（不泄露存在性） |
| PERMISSION_DENIED | 403 | 缺权限 |
| SCOPE_DENIED | 403 | 店铺范围拒绝 |
| LAUNCH_ENDED | 409 | 已结束/已取消流程 |
| ACTION_NOT_ALLOWED | 409 | 动作不在目录/状态不允许/handler 未接通 |
| ACTION_PRECONDITION_FAILED | 409 | 前置校验失败（附 blockers） |
| STEP_STATE_CONFLICT | 409 | 步骤状态冲突 |
| ACTIVE_LAUNCH_EXISTS | 409 | 已有活跃流程（带 existing_launch_id） |
| SYNC_MODE_UNSUPPORTED | 422 | 不支持的同步模式（带 supported） |
| PROFILE_NOT_FOUND / PROFILE_AMBIGUOUS | 404 / 409 | 无匹配/多匹配 Profile |
| LAUNCH_CONTEXT_CHANGED | 409 | 店铺经营上下文已变化 |

## 7. 前端 F01-F03 验收标准（引用产品设计 §2/§3/§7）

- **F01（§2）**：列、筛选、空状态、等待平台文案、UNKNOWN 不绿、活跃/历史、服务端 Scope 后分页——见 AC-14.1~14.7。
- **F02（§3/§4）**：同页同一 DTO；时间线并行分组与依赖标记；右侧任务详情（说明/要求/缺项/证据/外部反馈/责任人/下一动作）；「可并行处理」区；三类状态摘要；动作禁用原因；409 保留输入；超时「结果待核查」——见 AC-15.1~15.9。
- **F03（§3）**：GUIDED/PROFESSIONAL 同页同实例同状态同权限；业务语言摘要；专业字段展开（raw 状态、external_reference/type、mapping_version、Profile hash、同步时间）；未接入字段占位；浏览器临时切换不具有授权含义——见 AC-16.1~16.5。
- **通用（§6/§7）**：状态不只靠颜色（文字+图标）；键盘可操作；窄屏上方步骤选择、下方详情，关键按钮无横向溢出；Playwright 以真实本地后端 + 隔离库运行，API/数据库断言证明状态与隔离；Factory 不可见数据；授权失效后不可继续写。

## 8. 待确认问题：已由架构定稿（2026-10-12，归档）

以下三条原待确认问题已与 `software-architect` 对齐并定稿于 `docs/INCREMENT_DESIGN_LAUNCH_P0_CLOSURE.md`（D5/R4/R11），结论如下：

1. **CONFIRM_ACTIVATION 核验记录存储**（已定稿，采纳默认假设）：核验事实落盘到 `WorkflowStep.result`（`activation_verification.current/history`）+ 不可变事件，零新迁移；更正走 history 追加 + `correction_of`，不擦除历史。`launch_facts` 据核验记录派生 `verified_artifact: ACTIVATION` 谓词，使 PLATFORM_ACTIVATION 完成条件可被服务端事实满足。生产环境接受人工核验作为首期在售路径（冻结状态模型 §5），强制独立核验人与可追溯材料。
2. **SUBMIT_PLATFORM 身份标识**（已定稿，含一处修订）：`agent_type="listing"`、evidence 增加 `{launch_id, step_code}` 按默认假设采纳；**scope_key 修订为 `launch:{run_id}:{step_code}:{n}`（n 为提交序号）**——因 `action_system._scope_action` 会按 scope_key 复用任意终态 Action，纯格式下「被拒后同内容重提」必然死锁；序号后缀后非终态仍复用同一 Action（AC-6.2 不破坏），终态强制新建意图（AC-8.1）。
3. **F03 偏好持久化**（已定稿，采纳默认假设）：`effective_experience_mode` 恒为 GUIDED 常量；浏览器临时切换不持久化；PATCH context 与 Membership 偏好列后续增量再做。

### 8.1 产品决策：完成态流程的轮次语义（R6，已决策）

架构侧提出：COMPLETED 流程本轮保留 `active_slot=1`（不写 `ended_at`，否则 refresh 对已结束流程 409，且上线后监控无法再更新平台状态），因此**完成态不可 relaunch、不可 CANCEL**，本轮「结束」仅 CANCEL 一条路径。

**产品决策：接受，且与冻结架构一致**——`PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md` §3 已规定「执行流程 COMPLETED 不释放销售对象；只有显式取消未激活流程，或经核验下架并结束经营轮次，才清空 active_slot、记录 ended_at」。因此：

- 本轮 relaunch 仅支持引用已 CANCEL 结束的流程（`previous_run_id`）；COMPLETED 流程不可作为 `previous_run`。
- 「完成后再开新轮次」登记为后续增量的产品需求：需先定义「经核验下架 → 结束经营轮次 → 释放槽位」的语义（依赖 B11 外部事件/Webhook 与监控增量），不在本轮范围，不谎称已支持。

## 9. 复用与实现要点（供架构师参考，非实现指令）

- 动作执行复用 `action_system` 的 Guardrail 模式（策略目录、权限复核、审批、幂等事务）与 `action_publish` 的外部幂等模式（指纹比对、Attempt 持久化、回执）；Launch 动作不新建第二套审批体系。
- 就绪度与刷新复用 `launch_rules.evaluate_readiness` + `launch_runtime.refresh_launch`（revision CAS + 同事务事件）；详情只读计算复用其计算段，不新增第二套规则。
- 权限与 Scope 复用 `launch_access`/`store_scope`/`action_identity`；分页复用 `pagination.PageNum/PageSize`；事件脱敏复用 `pii_redact.redact`。
- 新增事件类型建议：`LaunchActionExecuted`、`LaunchActionFailed`、`LaunchActionRetried`、`LaunchCancelled`、`LaunchActivationVerified`（与既有 `LaunchCreated`/`LaunchReadinessChanged` 同表、同不可变语义）。
