# Platform Workflow 迁移与安全计划 V2

> 最后更新：2026-10-11。状态：FROZEN_FOR_IMPLEMENTATION / Expand 1a 合成历史库已演练 / 主库未修改。
> 领域字段以 `docs/PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md` 为准；此处定义实施顺序与安全门禁。

## 1. 目标与绝对边界

只增加模型能力，保留 Tenant 主键、商品/Listing/订单/财务数据和 legacy Workflow。迁移只新增 revision，不修改已执行迁移；不 import app.models。设计基点的最新迁移为 20261001_21，本轮新 revision 从其后继开始，创建前重新检查唯一 head。主库当前 revision 未核实，不沿用历史文档数值。

设计阶段不执行主库预检/DDL。实际演练只使用已验证绝对路径的隔离副本或合成历史库；创建生成物前写入 .gitignore 和 .dockerignore。禁止服务默认启动后连回 backend/erp.db，禁止用 create_all 冒充旧库升级。

2026-10-11 实施：唯一 head 已推进至 20261011_22，前驱为 20261001_21。为先修复发布语义，Expand 1 拆出 1a（Listing/PlatformPublishAttempt 三态及回执元数据），未改变冻结领域模型；Shop 上下文、派生外键与体验偏好仍待后继迁移。`backend/tests/test_launch_publication_migration.py` 在临时合成历史库先运行只读 preflight，再验证升级、历史状态 UNKNOWN、FK/integrity、无新事实降级、再次升级和有事实拒绝降级。该证据不代表完整主库副本或 PostgreSQL 演练完成。

## 2. 增量拆分

| 修订批次（文件名实施时确定） | 内容 | 依赖/检查 |
|---|---|---|
| Expand 1 | Shop 上下文、Listing 店铺派生与提交/在售字段，WorkspaceProfile 默认体验及 Membership 偏好 | 旧行为缺值不猜；列 nullable/明确安全默认 |
| Expand 2 | WorkflowTemplate/Run/Step 的 flow_kind、显式关系、版本、三类状态、active_slot、revision 与索引；WorkflowEvent | 旧运行回填 LEGACY_AUTOMATION，恢复器先隔离；无自动转 Launch |
| Expand 3 | ProductAsset、PriceReview、StockPreparation；扩展 ProductComplianceEvidence 版本和核验信息 | FK 顺序正确；唯一性变更先检查重复；历史证据 UNKNOWN |
| Permissions | launch 权限目录、角色映射；不改变工厂角色身份 | 双来源代码/数据库一致；不提升 COMPLIANCE 的发布/财务权 |
| Safe backfill | 历史行安全默认、图片 UNKNOWN 版本和来源、已知引用核对 | 每条有批次/来源，幂等；不能推断市场、Store、认证和 ACTIVE |

表名遵循现有复数：product_assets、price_reviews、stock_preparations、workflow_events。全部 tenant_id FK→tenants；workspace_id 暂按现有 AiAction 的可信快照方式存储并 Service 验证映射，避免在 ORM 中无身份表 metadata 时假建身份表；正式迁移检查 workspace_profiles 映射存在。

高频 FK：Run→Product/Shop/Listing/Template/previous Run；Step→Run/User/Supplier；Asset→Product/parent Asset/User；Review→Run/Step/PricingRecord/AiAction/User；Stock→Run/Step/Supplier/PurchaseOrder/Warehouse；Event→Run/Step/User；Evidence→Asset/User。所有删除采用限制或显式归档，禁止级联删除历史经营/审计。

## 3. 唯一约束与并发

WorkflowTemplate 新 Profile 唯一 tenant/profile_key/version；legacy key 读取继续限定 flow_kind，不受新 Profile 版本影响。WorkflowRun 唯一 tenant/product/shop/active_slot（活跃=1、历史=NULL），另需创建请求 idempotency_key 唯一。WorkflowStep 对 Launch 的 run/step_code 唯一，旧 step_code=NULL 不冲突。

ProductComplianceEvidence 从 tenant/product/country/requirement 唯一改为 tenant/product/country/platform/requirement/version 唯一；platform 非空默认空串保证跨方言唯一性；历史 version=1。旧 upsert 路由改为追加新版本并返回当前有效视图，旧查询必须同步改成按要求选择最新适用且已核验版本，不能任意取一行。

Run.revision 使用条件更新完成乐观锁。SQLite 用短事务，外部请求不持锁；PostgreSQL 使用同等条件更新和唯一键。不依赖 Redis 提供最终唯一性，不把“先查不存在再 insert”当并发保障。

## 4. 数据回填与兼容

1. Shop 的市场/模式不能由平台默认站点回填；空值在新 Launch 创建和真实发布时明确要求补充，旧读接口继续可用。
2. Listing 母稿保留 shop_id=NULL。仅用户派生新草稿时绑定店铺；历史多店发布事实继续由 PlatformPublishAttempt 承载，不任意认领。
3. 历史 published 不回填 ACTIVE；新 platform_status=UNKNOWN、verification_status=UNKNOWN。可显示“历史发布记录，未核验在售”。
4. Workflow 旧行填 LEGACY_AUTOMATION；其 execution_status 不参与旧运行。旧模板 steps 结构不改；旧 status 原样保留。
5. Product.images 以原 URL/商品/source 生成 UNKNOWN Asset，不改原图列表，不推断版权；重复执行按稳定 asset_key/content hash 不重复插入。
6. 旧证书保留 evidence_ref/valid_until，核验状态 UNKNOWN；没有核验人不设 VERIFIED。新门禁启用前列出待补资料，不静默改变历史证书来源。
7. 未创建 Launch 的旧渠道查询返回可追溯的发布尝试/UNASSIGNED，不伪造流程。
8. 旧 /api/listings 发布仍可用，但真实发布走相同市场/素材/Scope 门禁；兼容不等于保留 unsafe bypass。local/demo 清楚标注来源，不能升级生产验证状态。

## 5. 副本演练与执行门禁

先确认源库只读、停止任何会写目标的进程；按 `docs/backup_restore_runbook.md` 生成一致冷备。禁止将运行中的 WAL 主文件单独复制当完整快照。合成历史库也必须记录 before 数据与结构。

迁移前对隔离目标运行 `backend/scripts/migration_preflight.py --db <隔离绝对路径> --planned-upgrade <唯一head> --json`，P0=0 后才 upgrade。目标等于主库、路径越界或输出目录非允许范围时脚本直接拒绝。连接必须显式 ERP_DB_URL，测试启动检查数据库绝对地址。

必须保存证据：源/目标路径、before revision、计划 head、preflight、upgrade 输出、FK/integrity、各旧表行数与业务内容摘要、历史 Workflow 恢复、版本唯一性、重复回填、downgrade 和再次 upgrade。主库保护不能只比主 .db 哈希，需包含 WAL/SHM 和只读行数/逻辑摘要；不能用 checkpoint 写主库来满足“只读检查”。

空库、既有 21 库、主库备份副本三种路径区分报告；不能用空库成功证明历史数据升级成功。PostgreSQL 完整迁移验证为生产门禁；本机无服务时明确未验证，不把 SQLite 结果推广为多方言成功。

## 6. 回滚

应用回滚先关闭新入口和本任务 worker，确认没有执行中的外部动作。若无新领域数据，可按 downgrade 逆序删增量索引/列/表，恢复旧证据唯一键；有多版本数据或外部事实时 downgrade 必须拒绝并解释，先导出/备份或 forward-fix，不能悄悄删历史。

结构回滚不撤销真实平台发布、采购或价格决定。此类补偿走新 Action 和真实授权。旧 API、legacy status 和未改历史字段应可继续读；不把数据回滚与业务撤销混为一件事。

## 7. 设计安全检查清单

- [x] 设计中新增高频关系有结构列、索引和 FK/tenant 归属校验要求。
- [x] 设计要求 flow_kind 贯通领取、恢复、Schedule、列表和统计。
- [x] 状态设计区分发布、在售和证据；UNKNOWN 不自动放行。
- [x] 回填设计不为历史图片/证据/市场虚构可信默认值。
- [x] active_slot 设计支持多轮历史，矩阵包含并发唯一性验收。
- [x] 设计要求权限常量与数据库目录一致，Factory 仍只限本厂。
- [x] 迁移约束明确禁止 import app.models、修改旧 revision、试验主库。
- [x] 矩阵要求验证有数据拒绝 downgrade 和无数据 roundtrip。

此清单完成只表示可以写迁移代码；运行安全通过必须有实际演练证据，不能在设计阶段勾选为已执行。
