# Platform Commerce Workflow 架构 V2

> 最后更新：2026-10-10。状态：FROZEN_FOR_IMPLEMENTATION（V2 设计一致性与迁移安全设计检查通过）；并非运行验收或主库部署完成。实现状态见 `docs/PLATFORM_WORKFLOW_PROGRESS.md`。
> 依据：用户 V2 总指令、`docs/PLATFORM_COMMERCE_WORKFLOW_GAP_ANALYSIS.md`、`docs/phase1_interfaces.md`、`docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md`。

## 1. 权威定义与兼容边界

本文是领域实体、权限、API 的权威设计；状态取值以 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md` 为准，迁移以 `docs/PLATFORM_WORKFLOW_MIGRATION_PLAN.md` 为准，交互以 `docs/LAUNCH_CENTER_PRODUCT_DESIGN.md` 为准。设计不是实现证据。

Tenant 仍为隔离边界。workspace_id 来自可信 Context，tenant_id 通过现有映射服务解析，两者不得直接假定数值相等。保持 User/Membership 读取顺序、工厂协作身份和冻结 Context API 字段集。新增业务 API 统一 `/api`，不单独引入 `/api/v1`。

Shop 仍是 Store。Product、Order、Finance、Supplier、Purchase 不另建同义模型。既有 Workflow 三表增加 flow_kind：LEGACY_AUTOMATION 与 PLATFORM_LAUNCH。旧模板、列表、调度、领取、恢复及统计只处理 LEGACY_AUTOMATION；Launch 由同一 Workflow 子系统的新确定性迁移模块处理，复用租约、幂等和 Orchestrator，不创建第二套引擎事实表。

V2 对历史 ADR-F07 的局部增量：原 Listing 母稿保留（shop_id=NULL），允许用户为目标店铺派生独立 Listing（shop_id 非空、parent_listing_id 可空）。不批量复制旧稿，不修改旧稿归属；Launch 必须绑定店铺稿。此变更由 V2“同品多 Store 独立 Listing 与 Launch”授权；影响仅新增发布对象，需登记决策与兼容测试。

## 2. 分层与调用

```text
Launch UI / API → Context + Scope → Workflow transition
                                      ├→ Business Services → models
                                      ├→ Adapter Gateway → registered Adapter
                                      └→ Orchestrator → existing Agent → read-only Tool
                                                                    ↓ recommendation
                                      AI Action → Guardrail → Executor → transition/service
事务提交：业务变更 + Workflow 状态 + WorkflowEvent
Outbox worker → 已注册消费者（Orchestrator / 通知 / 经营监控）
```

禁止 Service import Router；避免 workflow/Agent/Action 循环依赖：状态机依赖纯规则和领域服务，Orchestrator 在上层接入，Executor handler 调用状态机公共命令。Agent 只返回分析，不触及 Run/Step ORM。同步和证据核验无需 LLM。

PricingAgent 保持只分析，继续禁止其直接提交业务 Action。用户确认或既有 Operation 领域经 Orchestrator 生成核价执行提案；不得为了核价新建未登记 Agent。Finance Insight 作为证据，不冒充接受价格的授权。

## 3. 销售对象与实例唯一性

首期销售对象键为 tenant_id + product_id + shop_id（Shop 对应一个配置市场；多市场卖家账号分别配置站点 Shop）。同一键只有一个占用 active_slot=1 的 Launch，数据库唯一约束兜住并发；结束历史 active_slot=NULL，可以保留多轮。

ACTIVE 和 PAUSED 仍占用 active_slot，执行流程 COMPLETED 不释放销售对象。只有显式取消未激活流程，或经核验下架并结束经营轮次，才清空 active_slot、记录 ended_at。新一轮 relaunch 必须引用 previous_run_id、创建新店铺草稿和新发布意图，旧回执/批准不继承。FAILED 保留占用，用户明确取消或重试。不存在“刷新就新建一个实例”。

POST 创建使用 Idempotency-Key；同键同载荷重放，同键异载荷 409。不同键指向已有活跃销售对象返回 409 + 可访问的 existing_launch_id，前端打开已有流程，不默默重启。

## 4. 字段与关系（增量）

所有新业务表均带 id 主键、tenant_id→tenants.id 外键、workspace_id（可信快照）、created_at；跨表还需 Service 校验 tenant 一致。日期保存 UTC，页面按 Workspace 时区显示。金额采用 Decimal/定点值与币种；不使用浮点相等作为审批依据。

| 既有实体 | 增量字段及语义 |
|---|---|
| Shop | market（目标国家码）、store_type、account_type、business_mode、fulfillment_mode、capability_revision、capability_evidence（来源/授权时间/能力集合，不含密钥） |
| Listing | nullable shop_id→shops、parent_listing_id→listings；platform_status、verification_status、external_object_type；旧 status 保留内容/提交兼容投影，不作为在售依据 |
| WorkflowTemplate | flow_kind、profile_key、version、definition_status（DRAFT/PUBLISHED/RETIRED）、environment（CONTRACT_TEST/PRODUCTION）、verification_status、platform、market、store_type、account_type、business_mode、fulfillment_mode、category_scope、schema_version、definition_hash、status_mapping；steps 保存受 schema 校验的声明式 DAG |
| WorkflowRun | flow_kind、workspace_id、product_id→products、shop_id→shops、listing_id→listings、definition_id→workflow_templates、workflow_version、definition_snapshot/hash、environment、platform、market、fulfillment_mode、execution_status、platform_status、verification_status、current_step、blocked_reason、next_action、revision、active_slot、idempotency_key、previous_run_id→workflow_runs、started_at、completed_at、ended_at、last_synced_at、created_by→users |
| WorkflowStep | step_code、business_type、execution_mode、actor、required、step_status、assigned_user_id→users、assigned_supplier_id→suppliers、external_status/reference/type、blocking_reason、data_snapshot、result、evidence_refs、input_revision、deadline_at；保留原 run_id、seq、attempts、时间和 legacy 字段 |
| ProductComplianceEvidence | platform、artifact_type、version、verification_status、valid_from、source、verified_by→users、verified_at、asset_id→product_assets；destination_country 保持市场字段；旧 requirement 仍是要求标识，不将所有 Artifact 塞成认证 |
| PlatformPublishAttempt | external_object_type、raw_status、platform_status、verification_status、received_at、mapping_version；保留 tenant/listing/shop 唯一性与 checkpoint；重新上线使用新 Listing，避免改历史唯一键 |
| AiAction | 复用现有字段；evidence 固定 run/step/shop/profile/version/成本与资料摘要；不新增 AI 专用表 |

WorkflowRun.status、WorkflowStep.status 保留 legacy 小写语义。Launch 分别使用 execution_status、step_status，不将 WAITING_APPROVAL 塞入原 String(16)。JSON 只保存不可变 schema/快照/可变结构证据，不隐藏 product/shop/run/review 等高频关系。

| 新实体 | 必须持久化的字段 | 唯一键/索引 |
|---|---|---|
| ProductAsset | product_id FK、parent_asset_id FK、asset_key、version、asset_type、uri、content_hash、rights_status、source、rights_evidence_ref、market、platform、verification_status、valid_from/until、manifest、created_by FK | tenant/product/asset_key/version 唯一；tenant/product/market/platform/type 索引 |
| PriceReview | run_id FK、step_id FK、round、declared_price、platform_review_price、currency、internal_floor_price、estimated_contribution_profit、estimated_margin、pricing_record_id FK、cost_snapshot/hash、data_quality、decision/reason、source、external_reference、reviewed_at、decided_by FK、action_id FK | run/round 唯一；run/decision 索引 |
| StockPreparation | run_id FK、step_id FK、supplier_id FK、purchase_order_id FK、warehouse_id FK、requested_qty、approved_qty、prepared_qty、stock_mode、status、external_reference、planned_ship_date、source、verification_status、revision | run/step 唯一；tenant/supplier/status、run/status 索引 |
| WorkflowEvent | run_id FK、step_id FK 可空、sequence、event_type、idempotency_key、actor_id FK 可空、source、occurred_at/received_at、before/after、payload（脱敏回执）、profile_version、mapping_version、delivery_status、attempts、next_attempt_at、lease_owner/until、consumer_receipts | run/sequence 唯一；tenant/idempotency_key 唯一；delivery_status/next_attempt_at 索引 |

WorkflowEvent 事件主体不可变，仅投递元数据可更新。首期固定少量消费者，consumer_receipts JSON 保存各消费者确认，消费者以 event_id 幂等；将来高并发/复杂订阅再拆 delivery 表。Label Package 为 ProductAsset.asset_type=LABEL_PACKAGE，manifest 固定条码、制造商、责任人、产地、产品信息、认证证据版本及生成器版本。

Stock 数量 CHECK：0≤prepared_qty≤approved_qty≤requested_qty；批准/备妥不足时仍未满足全量要求，若 Profile 允许部分批次必须明确所需数量。PriceReview.round 与 Asset/Evidence.version 为正整数，金额非负、币种必填；每个新 round/版本追加写，决定与核验变更通过事件保存前后态，成本快照不能原地覆盖。发布环境从实例固定，不接受客户端把 CONTRACT_TEST 改成 PRODUCTION。

## 5. 履约模型

fulfillment_mode 必填、由用户声明或 Store 已核验配置确定，AI 不能猜。business_mode 表示全托管/半托管/普通卖家等平台经营方式，不能替代履约方式。

| 模式 | 供应/采购/库存关系 | 流程与经济性 |
|---|---|---|
| DROPSHIP | 可用 SupplierOffer/供应承诺；销售 Order 产生后引用 PurchaseOrder 做代发；不创建预先平台库存 | 上线前确认供应可用、MOQ/交期；计按单物流和供应风险，不虚构已采购金额 |
| PLATFORM_STOCK | StockPreparation 管请求/批准/备妥；可关联采购和平台 Warehouse；可售库存须有独立回执 | 上线前备货/标签/实拍；计算预付款、仓储和预计交期，缺数据明确标缺 |
| SELF_STOCK | Warehouse + InventorySnapshot 为库存事实；采购收货作为来源，平台预留不能直接改 attrs.onhand | 验证可用库存与仓龄成本；数据版本参与核价 |
| FACTORY_DIRECT | SupplierPortalMember 绑定本厂步骤；供给/产能和交付证据来自 Supplier | 直供承诺和交期独立核验；平台是否要求备货由 Profile 决定 |

供应库存、销售可用库存、平台备货、采购承诺分别保留，StockPreparation 只引用、不暗改库存。1688 source Shop 不能成为 Launch 目标或进入销售 GMV。FIRST_ORDER 在复杂样本是“平台首批备货任务”，execution_mode=MANUAL_TASK，有来源和外部编号；不是销售 Order。生产 Profile 必须给其明确业务解释。

## 6. Profile 选择与能力

先匹配 platform/market/store_type/account_type/business_mode/fulfillment_mode/category_scope，再选择发布版本。精确维度优先于显式 ANY，多个同优先候选返回 PROFILE_AMBIGUOUS，零候选返回 PROFILE_NOT_FOUND；不能取数据库第一条。市场为空直接阻断，EU 区域不能替代具体目的国，区域规则由 Profile 显式展开。

发布校验：DAG 无环、引用存在、step_code 唯一、条件属于受限 DSL、动作在注册目录、所有 required 节点能到达 activation、MANUAL_TASK 有完成证据、外部状态映射包含未知处理。禁止 eval/Python 表达式。PUBLISHED 内容/hash 不可更新；新版本插新行，退役旧版本仅影响新实例。

能力结果包含 AVAILABLE/RESTRICTED/UNVERIFIED/UNAVAILABLE、source、checked_at、revision、sync_modes。Adapter 类能力仅是上限；Store 授权/市场/模式能力取交集。缺 API 的步骤保留为人工/外部任务，界面显示未接通。复杂 CONTRACT_TEST Profile 不给 TemuAdapter 赋予 can_publish=True，不声称全 Temu 官方流程。

## 7. 统一权限与数据范围

新增权限沿用冒号：launch:read/create/manage/price_review/stock_prepare/compliance_manage/label_manage/submit。发布同时要求 listing:write，操作采购还要求 purchase:write；批准证据另需 compliance:approve，不能因 upload 权限自证通过。

| 角色 | 默认增量权限 |
|---|---|
| OWNER | 全部 launch 权限；按原权限可审核证据 |
| OPERATOR | 全部 launch 权限，可录入资料/提交，但不能仅凭此获得 compliance:approve |
| READ_ONLY | launch:read |
| COMPLIANCE | launch:read、launch:compliance_manage；详情投影仅资料/合规，隐藏核价、供应价与财务 |
| PLATFORM_ADMIN | 无业务 launch 权限；代客仍按可信目标 Context 和审计执行 |
| FACTORY_COLLABORATOR | 不新增 launch 权限；走供应门户专用步骤投影，保持 supply:read/write + FACTORY_SELF |

统一 Scope 服务消费 membership_data_scopes，不改身份模型：scope_type=SHOP_SCOPED 时 scope_ref={shop_ids:[...]}；WORKSPACE_ALL 只在无受限配置或明确全域授权时有效；未知/格式损坏/空店铺集合拒绝，SELF_ONLY 未实现时拒绝。Membership 存在但已停用不得借 LEGACY_FALLBACK 继续写。每次列表过滤、详情、下载、动作、同步、Action 执行均调用同一守卫，不能只裁剪菜单。

Factory 投影按当前绑定 supplier_id 和 step.assigned_supplier_id 校验；仅显示该步骤所需商品摘要/数量/截止日/材料，不返完整 Run、成本、其他供应商、买家或店铺凭证。

## 8. API 及 DTO 契约

| 方法和路径 | 语义 |
|---|---|
| GET /api/launch/context | 身份核验后的可用店铺/能力/有效体验模式/权限，不改冻结 /me 响应 |
| PATCH /api/launch/context | 保存本人体验偏好；无 Membership 时仅 OWNER 可改 Workspace 默认，其他 legacy 用户仅本地临时切换 |
| GET /api/launch/profiles | 可选择 Profile 元数据、适用维度和验证来源 |
| POST /api/launch/profiles | OWNER 管理草稿；publish 动作校验 schema 和固定版本 |
| POST /api/launch/profiles/{id}/publish | 发布不可变定义；不得冒充官方验证 |
| GET /api/launch | 分页、状态/商品/店铺过滤，先 scope 后排序/分页 |
| POST /api/launch | product_id、shop_id、可选 listing_id、fulfillment_mode；身份/市场从服务端解析 |
| GET /api/launch/{id} | 共享详情 DTO，含步骤、建议、领域数据与专业页链接 |
| GET /api/launch/{id}/steps | 受限步骤 DTO |
| POST /api/launch/{id}/actions/{action} | step_code、expected_revision、业务载荷、Idempotency-Key；执行前重验 |
| POST /api/launch/{id}/sync | 选择允许的 sync mode；人工输入不能指定 VERIFIED |
| GET /api/launch/{id}/events | 脱敏审计、同步和历史分页 |
| POST /api/launch/{id}/relaunch | 原实例已结束才允许；新一轮/草稿/审批 |
| GET /api/products/{id}/channels | 各销售店铺当前实例、平台状态和历史链接 |
| GET/POST /api/products/{id}/assets | 资产版本列表/新增，不接受改旧版本 |
| GET/POST /api/products/{id}/compliance-artifacts | Artifact 当前有效版/新增版；核验走动作 |
| GET /api/factory-network/portal/launch-steps | Factory 受限待办 |
| POST /api/factory-network/portal/launch-steps/{id}/confirm | 本厂步骤证据提交；不能核验自己上传的认证或激活商品 |
| POST /api/launch/webhooks/{platform}/{shop_id} | 独立签名认证，无普通用户 Context；服务端由已配置 Store 解析 tenant，拒绝伪造归属 |

错误结构 {code,message,blockers[],current_revision?}；跨 scope 返回 404；权限不足 403；状态/版本冲突 409；字段不合法 422。外部调用返回 UNCERTAIN 仍保留意图，不返回假成功。

详情 DTO：id、product、store、platform、market、fulfillment_mode、execution_status、platform_status、verification_status、profile{key,version,hash}、revision、progress{completed,total}、current_steps[]、blockers[]、available_actions[]、next_best_action、recommendations[]、steps[]、last_synced_at、professional_links、monitoring。每条建议固定 target、evidence、source、reason、risk、expected_impact、approval_required、executable；来源为 rule 时明确标注。

## 9. Costing、素材和核验

扩展现有 Costing Service 的显式输入 platform/shop/market/currency/at/fulfillment_mode，旧调用保持兼容。单件口径统一，批次金额先除有效数量；报价、费率、物流、广告、退款、税、FX、仓储记录来源和时点。核价回传不可变 PriceReview round 与成本快照/hash，安全价按同一函数求满足 min_margin 的价格，不另建公式。缺币种/汇率/成本、过期、低底价或快照变化均阻断 AUTO_SAFE，首版价格决定均需人工审批；允许将来规则授予安全阈值，但不默认放开。

Asset 的 rights_status 与 verification_status 是两个维度。OWNED 声明仍需来源，授权/许可需对应 proof 与期限/市场/平台范围；UNKNOWN/RESTRICTED 阻断真实自动发布，继承素材的衍生图不能清洗权利。发布执行重算使用资产集合摘要，不能只校验旧 Product.images。

Artifact 按 Product/Market/Platform/Category/适用日期求要求，只有 VERIFIED 且未失效的匹配版本算满足。历史证书引用自动回填 UNKNOWN，不伪造审核人。Label manifest 中认证标志必须可追溯到有效证据，确定性生成器仅组合允许字段。实拍提交是 PENDING_VERIFICATION，Reviewer 核验后才通过。

## 10. 可靠性与上线后经营

所有入口进入统一 ingestion，固定 run/shop/object_type/external_id、event_id、source_time、received_time、source_revision、raw_status、mapping_version。验签通过只证明来源，不证明在售；按发布版本映射和证据条件推进。错店拒绝、重复同载荷重放、同键异载荷冲突、旧/乱序事件留痕不回退，未知映射阻断。支持可靠 revision 时优先比较 revision；仅时间且同时间冲突时转人工。

状态迁移用 run.revision 条件更新，失败整事务回滚。WorkflowEvent 与状态同事务；消费者至少一次投递，以 event_id 去重；失败指数退避、有界重试和死信人工重放，等待期间不占 Worker。外部意图先持久化，超时优先 read-back；不支持查证的 UNCERTAIN 只能人工核对，不自动重发。

ACTIVE 后 monitoring 只读取该 Store 的真实 sales Order/OrderLine、既有利润/风险服务；source/demo/contract 数据排除，无法可靠关联的指标明确 UNAVAILABLE，不用全 Workspace 总额冒充单店表现。凭证失效、证据过期、平台暂停产生事件与待办，不自动改平台真实状态。监管或平台规则更新可触发重新核验，但不能悄悄重写旧 Profile。

## 11. 变更纪律与完成证据

本轮不重做 Agent Runtime 未完成的全局迁移，不安装新 Agent 框架。Launch 需要的 Action、Tool、事件目录按现有冻结机制追加登记；任何执行权限不能经 Finance Agent 绕过。

设计需检查：所有关系在迁移计划有位置、所有状态在状态模型有合法迁移、所有前端动作在服务端目录有权限、每个 P0 和用户验收项在 E2E 矩阵有证据要求。通过后再冻结，缺陷可修但变更字段/语义须追加 ADR 并同步六份文档。完成以实际测试、迁移演练、浏览器证据为准，进度表不代替证据。
