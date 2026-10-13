# Platform Workflow / Launch Center 进度

> 最后更新：2026-10-13。状态：DESIGN_FROZEN / IMPLEMENTING_P0。目标：用户 V2 全量设计、实施和本地验收；真实平台联调取决于授权，不假装完成。

## 1. 当前基点和授权

审计提交 47161d1，业务源码基点 d14232e。V2 已授权完成六份一致设计后继续可回滚实现与隔离测试，不再停在审计。主库迁移、真实资金或店铺写入未获本轮授权。

上一目标已完成审计；本目标的当前进展是新证据读取与设计产出，不是重复审计或等待。未派发子代理，无需清理宿主过程记录。

## 2. 设计输入覆盖

已读：差距报告全文（截断中段分段重读）、Phase 1 接口契约全文、Agent OS 全文（分段 1—260、261—523、524—783、784—1063、1064—1323、1324—末尾）、最终架构评估全文（1—70、71—330、331—610、611—末尾）。长文档按 segmented-progress-reader 技能读取；实现以当前代码为准，不把历史未实现字段当已存在。

关键确定：Tenant 隔离不变；Workflow 三表加 kind；三类状态分离；同销售对象一个活跃槽、可多轮历史；Pricing 仍只分析；Shop 作为 Store；旧 Listing 母稿保留，V2 允许店铺派生稿；Factory 仍走本厂门户投影。

## 3. 里程碑

| 阶段 | 状态 | 当前证据 / 下一步 |
|---|---|---|
| 已有审计 | DONE | 47161d1；不重复产出 |
| 六份一致设计 | DONE | 已生成架构、状态、产品、迁移、矩阵和本进度；检查记录见下节 |
| 设计冻结与决策登记 | DONE | 已校对关系、状态、权限/API；D61 登记 V2 增量；实现验收未完成 |
| A P0 修复 | IN_PROGRESS | 意图与店铺回执隔离已有 Contract 证据；可信在售及其余门禁待实现 |
| B Profile/Runtime/Transition | IN_PROGRESS | Profile 定义与持久化已实现；Run/Step/事件及 Transition 待实现 |
| C 隔离迁移演练 | PARTIAL | Expand 1a/1b 合成历史库已演练；完整副本仍待验证，主库不动 |
| D 领域服务 | NOT_STARTED | Costing/核价/备货/Artifact/Asset/Label |
| E 前端 | NOT_STARTED | 同页双模式、渠道/深链、Factory 投影 |
| F 本地 Profile | PARTIAL | SIMPLE_CONTRACT / COMPLEX_CONTRACT 定义与校验；完整执行 E2E 未实现 |
| G Playwright/故障恢复/全量门禁 | NOT_STARTED | 不用文档检查替代功能验收 |
| H 真实平台联调 | CONDITIONAL_EXTERNAL | 未访问外部账号；Temu 保持受限/未核验 |

## 4. 检查和风险

本批仅 Markdown 修改，未启动服务、未执行迁移、未修改主数据库。初稿文档检查 `python backend/scripts/check_docs_consistency.py --json` 退出码 0、total=0，`git diff --check` 通过。所有 E2E case 当前 NOT_RUN。

设计交叉检查（人工静态审查，不能替代实现测试）：

| 检查 | 结果与证据 |
|---|---|
| 三类状态与 DTO | 架构 §8 只引用 execution_status/platform_status/verification_status；状态文档 §1 唯一枚举；产品 §3 同 DTO |
| 活跃与历史 | 架构 §3 active_slot 在 ACTIVE/PAUSED 不释放，状态 §4 与迁移 §3 一致；修正审计的单一长期实例建议 |
| 实体完整性 | 补齐 Run.idempotency_key、Profile environment/verification 与 definition_status，迁移涵盖对应增量；Stock 数量边界明确 |
| 冻结身份兼容 | Context 字段不变、Factory 门户投影不增角色；新偏好通过 Launch context API；权限按现有冒号风格 |
| Action/Finance | Pricing 只分析、价格命令从合法 Orchestrator/User 路径提出；矩阵 BIZ-7 约束，不放宽原拒绝策略 |
| 迁移安全设计 | 逐项核对迁移 §7；所有检查限定为设计，实际 MIG-1—8 尚未执行 |
| 测试覆盖 | P0-1—8 独立；UX-A—L、BIZ-1—9、REL-1—8、SEC-1—3、MIG-1—8 覆盖 V2 各项要求，无通过冒认 |

审查修正：初稿遗漏显式创建请求幂等字段、Profile 测试环境字段和体验偏好写入口，已补齐后冻结。后续不能因已有文档冻结而省略实现安全测试。

风险：历史 Listing/证据/图片缺少核验和归属，不能自动升为可信；旧 Context 公开字段冻结，额外业务上下文用 Launch context；新增表 FK 与 ORM 身份表未注册兼容；PostgreSQL 实测环境未核实；构建依赖如需变更须跑对应容器门禁。

## 5. 连续实施的下一步

设计交叉检查与 D61 登记已完成。2026-10-11 文档一致性检查 total=0。P0-1 首批新增独立内存数据库测试，修复前 5 failed，修复后与现有 Action、Listing 回归合计 25 passed；定向 ruff 通过。修复覆盖待处理意图、HTTP scope 和失败重试键按店铺筛选，保留同店冲突拒绝。

补充本地发布与旧 payload 兼容后，连同权限回归共 32 passed。全量正序 pytest：728 passed / 2 xfailed / 1 xpassed；后三项来自既有合规关键词待定样本，不计为本轮能力通过。前端 npm test：77 passed；npm run build 通过；全仓 backend ruff 通过。

后端反序运行使用 pytest collection hook 将全部 items.reverse()：728 passed / 2 xfailed / 1 xpassed，与正序一致。最终文档一致性 total=0。无运行中的验证进程；未作可部署或真实平台接通结论，隔离服务 E2E 与 Playwright 仍待后续实现后执行。

以上为 066f36d 检查点结果；后续增量如下。

## 6. 2026-10-11 发布回执与状态增量

- 去除 Listing 全局 published 的发布短路，以 tenant/listing/shop Attempt 作为外部重放依据。HTTP 双店审批链先复现第二店未调用发布（1 failed），修复后两店独立回执、各自重放与分页均有断言。
- 增加三态/回执列与 migration 20261011_22。历史保持 UNKNOWN，提交只产生 SUBMITTED，演示不产生 VERIFIED；原始响应 ACTIVE 也不能直接成为在售。Walmart 明确 SUBMISSION 类型和查询能力。
- 新增按店铺回执分页接口及前端组件，删除按平台取第一店的查询逻辑；列表和审批文案说明提交不等于在售，保留跨店再次提交入口。
- 合成历史库预检只读、升级/降级/再升级、有事实拒绝降级已通过。迁移快照对外键排序规范化，保留列/索引/FK/行数断言。旧最小结构测试分别固定自身 19/20 迁移边界，不再用不完整 schema 冒充任意 head；原有数据与约束断言不变。
- 阶段验证：发布/Adapter 37 passed；迁移/跨境成本 43 passed；新增回执接口/安全矩阵 7 passed。后端全量正反序均 731 passed / 2 xfailed / 1 xpassed，既有合规待定标记保持；最终前端 79 passed、构建通过，Ruff 通过，文档一致性 total=0，git diff --check 通过。无运行中的测试进程。

未完成：Store Scope 全链、真实在售核验服务、店铺派生稿、完整副本迁移、Workflow runtime、业务服务、Launch Center 和 Playwright。不能将此批当作 P0 全部完成；主库与真实店铺仍未操作。

## 7. 店铺市场与经营上下文（本批完成）

已增加 Shop 的市场/店铺类型/账户类型/经营模式/履约方式及只读能力元数据，复用原店铺创建/配置界面。迁移 20261011_23 不猜历史值，合成历史库已验证只读预检、upgrade/downgrade/upgrade、保留行/索引/FK 以及有配置拒绝降级。

真实发布和 Adapter 共用 market 门禁；有 Shop 时不再读取 Product 的国家或平台首站点。缺配置、区域代替国家、未知代码、检查异常均阻断；Adapter 声明范围不匹配也拒绝。无 Shop 的只读预览仍允许读取 Product 明确声明，取消平台默认猜测。店铺上下文和当前准入结论纳入审批指纹，HTTP 验证批准后换市场执行 FAILED、没有产生 Attempt。

测试前提修正：旧美国合规样本现在明确填写 Shop.market=US，保留 FCC 缺失/齐备双向断言；纯协议/类目补丁测试显式隔离合规依赖，真实数据库合规测试继续独立覆盖。第一次全量回归另遇前端构建清理 dist 与文档扫描并发的竞态，后续门禁改为串行，不放宽断言。阶段 63 项市场/合规/适配器测试、44 项迁移/上下文测试及独立批准后换市场测试通过；前端 79 passed、构建通过。最终正反序均 742 passed / 2 xfailed / 1 xpassed，Ruff 通过，文档一致性 total=0，git diff --check 通过；无运行中的验证进程。

仍需继续：Store Scope 和撤权执行重验、Asset 权利门禁、可信核价快照、flow_kind 与版本化 runtime、完整 Launch Center/E2E。本阶段不会标记整体目标完成，主库与外部店铺未操作。

## 8. 店铺范围与发布审批撤权（本批完成）

统一 StoreScope 服务读取既有 Membership 数据范围，无新增身份模型或迁移。多条 SHOP_SCOPED 取交集，默认全域记录不放大限制；未知、损坏、空集合拒绝。认证和 Action 的新鲜身份检查拒绝停用 Membership 回退旧权限。店铺列表/操作、发布意图/审批/执行/成功重放，以及分页前的发布回执和 Action 队列已接入。受限成员禁止创建未授权店铺和全租户演示数据清理。批准人撤权重验保留代客审批来源，不以管理员执行替代原批准人的有效授权。

隔离测试：原六项 Scope 用例通过；新增双店发布队列/回执过滤及成功重放拒绝、发起人/批准人审批后范围变化，连同现有发布、安全矩阵和 Action 回归共 29 passed。最终全量后端正序与反序均为 751 passed / 2 xfailed / 1 xpassed（既有合规待定样本保持）；前端 79 passed、构建通过；全仓 Ruff 与文档一致性检查通过，git diff --check 通过。验证进程已结束。没有作完整运行/部署/E2E 完成声明。

剩余：所有新的 Launch、同步和资产入口仍需复用同一 Scope 服务；P0-6 尚未全链完成。当前没有运行数据库迁移、访问主库或真实店铺。下一阶段继续 Asset/核价安全基础与 flow_kind/版本化 Runtime；不会将这批权限修复当成 Launch Center 已交付。

## 9. 新旧 Workflow 类型隔离（本批完成）

增加 WorkflowTemplate/Run.flow_kind，旧自动化显式保持 LEGACY_AUTOMATION。旧领取、续租、启动恢复、人工恢复、模板解析、调度创建、启动模板修补、旧列表/详情和 BI 运行列表均限定类型，避免未来 PLATFORM_LAUNCH 被 Agent 循环误执行。没有复制 Workflow 表或修改旧步骤状态语义。

新增 20261012_24 迁移（Expand 2a），只读预检和历史合成库 roundtrip 已通过；含平台流程时拒绝降级。4 项针对性测试通过，包括过期运行和排队运行均不能被旧引擎领取、恢复、执行，旧 API/调度/模板修补隔离。首次全量暴露旧预检用例固定 head 和行尾问题：统一 LF，预检计划读取唯一代码 head，具体迁移升级/回滚边界和数据断言不变；相关 65 项回归通过。

最终后端正反序均 755 passed / 2 xfailed / 1 xpassed，前端 79 passed、构建通过，全仓 Ruff 和文档一致性 total=0，git diff --check 通过。全部验证进程已结束。主库没有执行迁移，完整 Runtime/Profile/事件关系和界面仍未交付，新恢复器的反向隔离仍需实施验证。下一步扩展不可变 Profile、店铺派生草稿及实例/步骤/事件持久化；素材与可信核价门禁完成前不开放真实 Launch。

## 10. Profile 定义、版本与匹配（本批完成）

复用 WorkflowTemplate 增加 Profile 维度、版本、状态、环境、摘要和映射，新增迁移 20261012_25。Draft 修改/发布使用摘要条件更新，发布后拒绝内容更新；退役只改选择状态，内容快照保留。数据库 tenant/profile_key/version 唯一，历史 profile_key=NULL 不影响同名旧模板。每次读取定义校验结构与 hash，异常拒绝；没有新增 Profile 同义表。

定义 schema 包含通用步骤类型/执行模式/actor、人工证据、动作目录、超时和受限条件 DSL。校验环、缺失依赖、条件暗含依赖、required 节点到核验的路径、监控位置；UNKNOWN 不自动通过。匹配按可信 Shop/Product/Context，要求真实目标国家/履约模式、拒绝货源店铺，精确维度优先，同级多 Profile 明确歧义。写服务仅现有全域 OWNER，接口与 launch 权限目录尚待统一接入。

新增 simple/complex CONTRACT_TEST 定义，不注册生产 Adapter 能力；复杂图允许资料后并行合规、核价，首单是平台备货任务，非伪造销售订单。样本完成条件引用服务端业务事实而非客户端完成标记；运行时事实构造和执行尚未实现。

35 项定义/持久化/迁移/旧隔离针对性测试通过。最终后端正反序均 786 passed / 2 xfailed / 1 xpassed（既存待定样本），前端 79 passed、构建通过，全仓 Ruff 通过。合成历史库预检只读，升级/降级/再升级、有数据拒绝降级和版本唯一性已验证。主库、真实账号均未操作，完整 Launch/E2E 不作完成声明。所有测试与构建进程已结束；下一步为 Run/Step/Event 与店铺派生 Listing 的事务持久化，以及 launch 权限/API 接入。

## 11. Run/Step/Event 与店铺派生稿（本批完成）

新增迁移 26/27，复用 WorkflowRun/Step 和 Listing，新增批准设计中的 WorkflowEvent。创建服务固定 Profile 快照，在同一事务写入草稿、实例、步骤和事件；提供幂等重放与数据库活跃槽约束，外层回滚不留残余。创建与 Profile 保存点统一处理 SQLite 延迟 BEGIN，防止 RELEASE SAVEPOINT 提前提交。Store Scope 每次重新读取，发布派生稿限定绑定店铺；权限目录同步角色矩阵，不扩大合规员通用写入或工厂权限。

全量回归发现权限夹具未跑新增迁移、历史 Action 迁移测试错误使用任意 head、旧租户外键清单尚未区分新增事件表，以及演示清理遗漏新引用。分别补齐权限真实迁移、固定 D47 自身边界、独立核对新增表实际外键，并在已有 Launch 时拒绝旧清理以保留审计；原有断言保持。

本批未开放 Launch HTTP，不包含确定性迁移、合法动作/NBA、同步、Outbox 投递或完整 UI；P0 素材/核价与派生稿全链 Scope 仍待实施。主库、外部平台均未操作。最终后端正序与反序均 799 passed / 2 xfailed / 1 xpassed（既有合规待定样本）；前端 79 passed、构建通过，Ruff 与文档一致性检查通过。创建、权限与迁移定向测试通过；没有将合成历史库验证扩称完整主库副本演练。所有测试和构建进程已结束，下一步实施确定性迁移、业务事实读取和合法动作。

## 12. 确定性就绪度与事务刷新（本批完成）

新增 launch_rules 的 DAG 规则计算和 launch_runtime 刷新服务。依赖按拓扑处理，sequence 仅显示；未知适用性阻断，明确不适用才跳过；即使事实满足也不自动完成步骤。并行分支在摘要 BLOCKED 时仍可显示可运行节点。上线前完成依据失效会递归阻断后继；上线后保留完成历史并返回整改阻断，监控失败不抹掉上线里程碑。

刷新读取固定定义、校验摘要和步骤完整性，重新验证当前 Context/Store Scope 和商品/草稿/店铺关系，以 Run.revision 条件更新。步骤变化与 LaunchReadinessChanged 事件在一个保存点中写入，调用方回滚或事件故障均不留下半步状态。相同事实刷新不重复增版；并发旧 revision 拒绝。没有接入旧 Workflow Worker，也不从请求传入事实。

事实读取目前只包含商品标题、草稿标题和精确店铺/草稿的 succeeded 提交回执；原始 ACTIVE 不变成在售，生产实例不采用 demo 回执。Asset/核价/合规等尚待领域服务接入，保持 UNKNOWN。31 项就绪度与创建持久化测试通过，另 3 项旧引擎隔离通过。尚无完整动作 handler、合法动作/NBA、HTTP Launch 或界面，不能作为生命周期闭环验收。最终后端正反序均 821 passed / 2 xfailed / 1 xpassed（既有合规待定标记）；前端 79 passed、构建通过，Ruff 与文档一致性 total=0，git diff --check 通过。所有验证进程已结束。本批无新迁移，主库和外部账号未操作；下一步接入领域事实与动作门禁。

## 13. 素材版本、权利核验及发布门禁（实施中）

新增 ProductAsset 和迁移 20261012_28（Expand 3a），按冻结字段保存适用市场/平台、版本、来源、权利证据、内容摘要、有效期与独立核验记录。只追加版本，登记为 MANUAL_REPORTED；独立核验是可用能力，选择核验时提交人不可自审；UNKNOWN/RESTRICTED 即使经过审核也不能发布。核验与撤销均保留历史版本，保存点服从调用方事务，版本唯一键防并发覆盖。旧 Product.images 原样保留，不自动生成有权素材。

新增现有 /api/products/{id}/assets 的 GET/POST 与 /{asset_id}/verify；分页前校验可信 Context、Membership、Store Scope 和市场范围。调用方不能传 tenant/workspace/verification_status；角色矩阵已增加接口探针。Asset 服务接入 Launch 的 PUBLISHABLE 谓词，真实发布 facts 及 Adapter 两侧检查，审批指纹包含素材版本和权利依据，撤销/过期/换素材会阻断或改变指纹。本地与 demo 发布保持无外部副作用的兼容路径，但 Launch 不因此将无权素材判定为可用。

23 项素材专项测试通过（含 HTTP、并发、scope、授权撤销、正反门禁与审批指纹）；合成历史库只读预检、roundtrip、实际 FK 和有记录拒绝降级通过。原合规正向测试显式补充有权素材样本，保留成功发布与必填字段断言；纯协议恢复测试隔离权利数据库依赖，真实门禁另测。

限制：本批管理素材 URI/摘要和人工核验，不下载或托管文件，未证明远端可变 URI 的实际字节始终与摘要一致；不可将登记摘要称为自动文件真实性验证。完整素材中心前端、文件存储/上传及历史 UNKNOWN 回填仍待后续；合规 Artifact、Label Package、核价和完整 Launch 动作尚未交付。主库、外部账号均未操作。全量验证待记录。首次全量仅发布幂等样本缺少权利登记失败；该样本改为通过 ASGI TestClient 登记/核验，保留仅一次 Adapter 调用及回执重放断言，并定向清理测试素材，避免影响后续演示清理测试。

边界校正：初稿错误地把所有权利声明升级为必须双人核验，超出冻结设计 §9 且阻碍个人用户；已改为 OWNED 明确来源、授权/许可明确 proof 和适用范围即可进入权利判断，仍保留 MANUAL_REPORTED 标签，不伪称独立审核。UNKNOWN/RESTRICTED、缺证明、驳回/失效始终阻断；认证 Artifact 的 VERIFIED 门槛不因此放宽。

## 14. 动作执行框架与业务处理器（本批完成）

T01（提交 `56a6760`）从既有 runtime 抽出共享内核：`launch_action_catalog`（动作元数据目录与载荷契约，17 个动作、完成标记键拒绝、note 截断）、`launch_state`（快照/纯函数 diff/事件/序号/AiAction 投影/回执落地/事实指纹），并把 `submit_action` 扩展出 `commit`/`extra_evidence`（净增 3 行，不新建第二套审批体系）。

T02 实现动作执行框架与处理器：`launch_actions.execute_launch_action` 按十步校验链（幂等重放 → 生命周期 → revision CAS → 目录 → 载荷 → 权限 → 就绪度门禁 → 状态机守卫 → handler → 收敛落库+事件），步骤条件更新与 run CAS 双保险，幂等重放仍复核当前权限且不重发外部意图；`launch_handlers` 接通 COMPLETE_DATA / RETRY / CANCEL / ABANDON_PRODUCT；`launch_submit` 接通 SUBMIT_PLATFORM（复用 PUBLISH_LISTING 审批队列，scope_key 带提交序号避免终态 Action 复用死锁）与 CONFIRM_ACTIVATION（双权限 + 核验人独立，核验记录入步骤证据与不可变事件，`source=MANUAL`）；`launch_plan` 抽出只读计算段并新增进程级恢复扫描（无意图 RUNNING → READY，有意图只重读不重发）；`launch_runtime.refresh_launch` 改为委托 `launch_plan` + `launch_state.converge`。

行为边界：未接通领域动作（B03-B09）一律 409 `ACTION_NOT_ALLOWED` 并给出禁用原因；提交只产生 `SUBMITTED`，原始响应 ACTIVE 也不自动置 `ACTIVE`/`VERIFIED`；取消为纯本地终态（写 `ended_at`、释放 `active_slot`），不调用外部下架/退款；已核验在售不可取消；`CANCELLED` 后重新上线必须走新轮次。

测试：新增 `tests/test_launch_actions.py` 22 项（覆盖 AC-4~8）。后端全量正序与反序均 **897 passed / 2 xfailed / 1 xpassed**（既有合规待定样本保持，同时补齐 §13 素材批次的全量结果）；`ruff check` 全绿；文档一致性 `total=0`，`test_docs_consistency` 43 passed。

未完成 / 边界：本轮闭环的是流程机制与可执行性——本地契约样本中仅「商品资料」步骤可被确定性完成，合规/核价/备货/标签/实拍等步骤仍保持就绪度规则给出的真实状态并给出原因与负责人，不得宣传为业务全链路已上线；Launch HTTP（B10/T03）与上线中心前端（F01-F03）尚未交付；主库与外部平台未操作。

## 15. 确定性 NBA 与 Launch API（本批完成）

T03（提交 `1feb18f`）交付 B02 与 B10：`launch_nba` 以纯函数按固定规则序计算 allowed/disabled/blocked 与 Next Best Action（不落库、不读时钟，同输入同输出；`COMPLETE_DATA` 需 `completion_satisfied`，`CANCEL` 需流程可取消）；`launch_dto` 承担响应投影（含 `StepDTO` 的 COMPLIANCE 角色剔除价格/成本/利润率/备货动作、事件载荷深度脱敏、`missing_evidence` 确定性派生、`verification_notice` 固定文案）；`launch_list` 先 Store Scope 后 SQL 筛选再分页，逐行重算时就绪度/事实异常降级为单条 `blocked_summary` 而非整页失败；`profiles.probe_profile` 提供忽略类目匹配的可用性探测。

API：新增 `routers/launch.py` 八端点（`/context` 声明早于 `/{run_id}` 保证路由顺序；写路径服务函数不提交、由路由层统一 commit/rollback）与 `routers/product_channels.py`（`GET /products/{id}/channels`），`main.py` 注册两个路由。统一错误 envelope `{code,message,blockers,current_revision?,existing_launch_id?}`；列表分页字段为 `page_num`；未知查询参数或未知筛选值 422 `FILTER_INVALID`；只读方（`launch:read`）的详情/列表/步骤/事件端点零写入且不改 revision；Factory 身份统一 404。

测试：新增 `tests/test_launch_nba.py` 10 项与 `tests/test_launch_api.py` 16 项（覆盖 AC-1/2/3/9/10/11/12/13）。后端全量正序与反序均 **923 passed / 2 xfailed / 1 xpassed**（≥ 897 基线）；`ruff check` 全绿；`git diff --check` 干净。

未完成 / 边界：仍是零迁移（核验记录落 `WorkflowStep.result` + `WorkflowEvent`，审批关联落 `AiAction.evidence`），未新增表或列；未接通领域动作（B03-B09）与真实平台联调不变；上线中心前端（F01-F03）与 B12 全量门禁（含 Playwright E2E）尚未交付。下一步：F01 上线中心列表与数据层（T04）。

## 16. 启动恢复扫描补齐（本批完成）

复核 §14/§15 时发现一处设计偏差：设计 D12/R9 要求「进程重启即回收」——`main.py` lifespan 在 `recover_incomplete_runs()` 之后以系统身份扫描未结束 `PLATFORM_LAUNCH` 的 `RUNNING` 步骤；但 §14 实际只把恢复逻辑挂在 `launch_state.converge`（由 `refresh_launch` 触发），而 `recover_incomplete_runs()` 仅处理 `LEGACY_AUTOMATION`（engine.py:368）。后果是进程崩溃后若无 manage 用户打开/同步该流程，`RUNNING` 步骤会长期停留。

修复（提交 `934f922`）：新增 `launch_recovery.recover_launch_steps(db)`，扫描未结束（`ended_at is None` 且未 `CANCELLED`）流程，复用既有 `launch_plan.recover_running_steps` 做只读判定后统一落库——无持久外部意图的 `RUNNING` 回退 `READY`；有意图的保持 `RUNNING` 并首次写 `result.pending_verification=true`（不重发）；每个被回收步骤写一条 `LaunchRecovered` 事件（`source=SYSTEM`、`actor_id=None`、`idempotency_key=launch:{run}:recovery:{step_code}:{revision}`），CAS 失败即放弃该 run（零状态变更零事件），二次启动零新事件（幂等）。`main.py` lifespan 在 `recover_incomplete_runs()` 之后接线，自建 `SessionLocal()` 会话。零迁移，只写既有列。

偏差（登记）：设计 §`launch_recovery.py` 另列 `recover_run_steps(db, run)` 供 sync 单 run 复用，未单独实现——sync 路径 `refresh_launch → converge` 已内含 `recover_running_steps` 且额外做投影/回执落地（为超集），再引入并行单 run 写路径会造成语义分叉；判定不需要。未强抽 `refresh_launch` 的 CAS 落库段为共享内核，原因：恢复是「逐步骤 `LaunchRecovered`」、刷新是「单条 `LaunchReadinessChanged`」，语义不同，强合会污染既有 30+ 刷新/动作用例——改用「最小独立落库段 + 复用 `launch_state` 内核」，`refresh_launch` 零改动。

测试：新增 `tests/test_launch_recovery.py` 4 例（无意图回退 / 有意图标注不重发 / 二次调用幂等 / 已结束 run 不动）。后端全量正序与反序均 **927 passed / 2 xfailed / 1 xpassed**；`ruff check` 全绿。

未完成 / 边界：启动扫描当前持单事务跨全部候选 run（重启时候选通常极少），未做每 run 独立事务；`recover_run_steps` 薄封装未提供。下一步：F01 上线中心列表与数据层（T04）。

## 17. 上线中心列表与数据层（本批完成）

T04（提交 `1e6a331`）交付 F01：新增 `frontend/src/composables/launchCenter.js`（数据层：context/列表/详情/步骤/事件/动作执行/sync；动作执行必带 `Idempotency-Key` 与 `expected_revision`；含可 vitest 直测的纯函数——执行/平台状态文案、空态分因、Guided 摘要、`return_to` 站内白名单校验、幂等键生成、错误 envelope 解析与 409 保留输入）与 `frontend/src/views/LaunchCenter.vue`（11 列 + 11 项筛选 + 服务端分页用 `page_num` + 空态分因可重试 + 行点击进详情带 `return_to`）。

配套修改：`api.js` 响应拦截器在 `detail` 为对象时取 `detail.message`（此前会渲染 `[object Object]`）；`router.js` 新增 `/launch` 列表路由（详情路由留 T05）；`Layout.vue`「商品」组新增「上线中心」并把 `/launch` 加入合规员菜单白名单（非 OWNER 隐藏列表不含 `/launch`）；`permissions.js` 新增 `APPROVER_PREFIX_PATHS=['/launch']`，合规员放行 `/launch` 与 `/launch/:id`，其余路径仍精确匹配。

AC 落地：AC-14.2 已核验——`WAITING_EXTERNAL` 文案「等待平台反馈」用中性 `info`（非失败红），`UNKNOWN` 用 `info`（不显示为绿色完成）；AC-14.6 `verification_notice`（「本地流程验证，不代表真实平台接入」）；AC-14.7 `return_to` 还原筛选；AC-16.4 `experienceMode` 读 `context.effective_experience_mode` 兜底 `GUIDED`；AC-17.1 列表行可识别 `environment`/`verification_status`。

测试：新增 `frontend/tests/launch-center.test.js` 28 例 + `permissions.test.js` 仅新增 1 例（未改既有断言）；`npm test` 8 文件 **108 passed**（≥ 前端基线 77）；`npm run build` 通过（路由级代码分割生效）。

未完成 / 边界：行点击导航到 `/launch/:id` 需 T05 注册详情路由（当前点击暂无匹配路由）；责任人筛选用 `owner_user_id` 数字输入（无用户列表端点，未新增后端）。下一步：F02/F03 详情双模式与 B12 全量门禁（T05）。

## 18. 上线流程详情与双模式（本批完成）

T05（提交信息 `launch: 实现上线流程详情与双模式`）交付 F02/F03：新增 `views/LaunchDetail.vue`（薄编排：加载详情、模式切换、同步刷新、动作流）与五个组件——`components/LaunchStatusSummary.vue`（执行/平台/验证三类状态分区，等待平台与失败文案区分，`monitoring` 恒 `UNAVAILABLE` 显示原因原文，COMPLETED 且存在阻断时显示「整改阻断」且不擦除历史）、`LaunchTimeline.vue`（按 `sequence` 并行分组 + `dependencies` 依赖标记 + 「可并行处理」READY 区，非固定线性进度条）、`LaunchStepPanel.vue`（说明/要求/缺项/证据/外部反馈/责任人/可执行动作，禁用按钮展示原因含「未接通/领域服务建设中」，PROFESSIONAL 展开 raw 字段且缺失项显示「未接入」）、`LaunchActionDialog.vue`（备注 + `material_ref`；高危/取消类二次确认；执行带 `expected_revision` + `Idempotency-Key`；409 保留未提交输入、刷新状态、重置二次确认且不自动重发；超时/不确定显示「结果待核查」）与 `LaunchExperienceToggle.vue`（GUIDED/PROFESSIONAL 同页切换，不持久化、不写 URL、不重新鉴权）。

数据层（`composables/launchCenter.js`）补充详纯函数：`professionalFields`/`notConnected`（未接入占位，0 不被吞）、`evidenceText`、`needsDoubleConfirm`/`actionPayload`/`requiresMaterial`/`requiresNote`（按 per-action 载荷契约构造，避免未知键 422）、`isUncertainError`（断网/未知码判为结果待核查）、`groupStepsBySequence`/`parallelReadySteps`。配套修改：`router.js` 新增 `launch/:id` 详情路由；`Layout.vue` `activeMenu` 把 `/launch/:id` 归一到 `/launch` 以保证菜单高亮。

双模式契约：两模式读**同一份 DTO**、状态一致（AC-16.5）；切换不改变数据与权限（AC-16.1）；刷新型初值来自 `context.effective_experience_mode` 兜底 `GUIDED` 并明示（AC-16.4）；PROFESSIONAL 展开 raw 状态、`external_reference/type`、`mapping_version`、Profile `hash`、`revision`、同步时间，DTO 缺失字段一律「未接入」不伪造（AC-16.3/17.3）。

测试：`frontend/tests/launch-center.test.js` 增补至 39 例；`npm test` 8 文件 **119 passed**（≥ 前端基线 77）；`npm run build` 通过（`LaunchDetail` 独立 chunk 生效）。B12 全量门禁结果见 §19。

未完成 / 边界：专业页深联（`professional_links` 目标页深联处理）留 F04+，本批只出合规链接；责任人仍以 `assigned_user_id` 展示（无成员列表端点）。

## 19. B12 全量门禁（本批完成）

本轮 P0 闭环（T01–T05）的 B12 门禁由主理人独立执行，全部通过。

**静态与回归门禁**
- 后端 `pytest -q -p no:randomly` 正序：**927 passed / 2 xfailed / 1 xpassed**；反序（测试文件倒序）：**927 passed / 2 xfailed / 1 xpassed**（≥ §12 基线 821；本轮新增动作/状态/恢复/NBA/API 用例后基线提升到 927）。
- `ruff check .` 全绿；`check_docs_consistency.py --json` → `total=0`；`git diff --check` 干净。
- 前端 `npm test` 8 文件 **119 passed**（≥ 前端基线 77）；`npm run build` 通过。

**真机门禁（真实 uvicorn + 隔离副本库，不碰主库）**
- `scripts/e2e_feasibility.py` → **exit 0**：7 项业务闭环 7/7 PASS（采购→收货→结算、订单→发货→退款、采集→选品→Listing→发布、AI 工作流、调度、知识库、AI 助手），静态前端托管 PASS，§7 主库隔离性 PASS。
- `scripts/launch_e2e.py`（本轮新增，提交 `02a1007`）→ **exit 0**：14 步全 PASS——context/NBA 前置、`POST /launch` 幂等（同键重放同一 run）、列表 `page_num`、未知查询参数 422 `FILTER_INVALID`、详情递归断言无 `price/cost/margin/stock` 违禁键、steps、`COMPLETE_DATA`（revision 2→3）、`sync`（`last_synced_at` 落库）、事件升序含 `LaunchActionExecuted`；并以 sqlite 只读副本库断言 `workflow_runs.revision` 与 HTTP 终值一致、`INFO` 步骤 `COMPLETED` 且 `result` 含完成证据、事件行存在；主库 SHA256 与行数升级前后不变。
- **浏览器真机走查 F01–F03**（`agent-browser`，真实后端 + 隔离副本库 + 生产构建产物；环境无 Playwright 依赖，故用内置浏览器能力而非向项目引入依赖）：登录 → 上线中心列表（列齐全、筛选控件、分页「共 1 条」、`待执行` 中性 tag、`未提交`、核验标注）→ 详情业务视图（三区摘要、GUIDED 摘要「你的商品已完成 1/3；待执行」、监控未接入原因为原文、`professional_links` INFO → /listings）→ 切换专业视图（Profile `ACTION_PROBE v1`、Profile hash、`revision 3`、环境 `CONTRACT_TEST`、验证状态 `UNKNOWN`、同步时间；时间线按 sequence 分组带依赖标记；可并行处理区；步骤面板 raw 字段缺失项显示「未接入」）。走查全程后主库 SHA256 仍为 `4fadccfc…`、行数 5951，隔离成立。

**门禁缺陷修复（既有，非本轮引入）**：`e2e_feasibility.py` 原以「迁移前后总行数相等」为不变量，与 Expand 迁移实践冲突（D61 迁移 `20261012_27` 合法播种权限目录使副本 5951→5978），导致 T-13 门禁长期误红；已改为逐表「不许丢表 / 不许丢行」的单调不减断言（提交 `214bdcc`），并以探针验证仍能捕获丢行/丢表。

**未完成 / 边界**：本轮仍是零迁移；未接通领域动作（B03-B09）与真实平台联调不变；浏览器走查为主理人手工人机协同执行（非 CI 内自动化），后续如需纳入 CI 可按 `agent-browser` 或 Playwright 补充；主库、真实店铺、外部账号全程未操作。
