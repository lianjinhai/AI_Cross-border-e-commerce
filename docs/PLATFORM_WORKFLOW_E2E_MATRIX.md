# Platform Workflow 验收矩阵 V2

> 最后更新：2026-10-11。状态：FROZEN_FOR_IMPLEMENTATION / P0_PARTIAL。不得将测试计划当通过结果。
> 依据：`docs/PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md`、`docs/PLATFORM_WORKFLOW_STATE_MODEL.md`、`docs/LAUNCH_CENTER_PRODUCT_DESIGN.md`、`docs/PLATFORM_WORKFLOW_MIGRATION_PLAN.md`。

## 1. 证据规则

每项记录 case_id、代码提交、命令、环境、fixture 来源、实际断言、结果、产物位置。单元测试证明规则；真实隔离后端/数据库证明事务和权限；Playwright 证明用户路径；迁移 roundtrip 证明历史兼容。截图不能替代数据库与 API 断言。除以下局部证据外，当前结果均 NOT_RUN。

2026-10-11，P0-1 意图查询子项：`backend/tests/test_publish_intent_store.py` 的 6 个内存 SQLite 用例覆盖不同店铺待审批/成功互不阻挡、同店重放与冲突、同 trace 双店、失败重试隔离及旧 payload/本地兼容。先运行前 5 个用例得到 5 failed，修复后与 Action/Listing/security 回归运行得到 32 passed。完整 P0-1 仍未通过：并发提交、两店独立外部回执和 published 返回路径尚待实现。代码与证据随本批 Git 提交追溯，不能将单元测试推广为双店上线 E2E。

真实平台账号联调为 CONDITIONAL_EXTERNAL，不属于本地 Contract 成功证据。未授权时保持 RESTRICTED/UNVERIFIED，不用测试桩连接生产 URL。

## 2. P0 独立回归

| ID | 测试输入/动作 | 必须断言 |
|---|---|---|
| P0-1 Store 发布意图 | 同稿两个 Store、同店重复/并发请求 | 两店意图/回执独立；同店幂等；不能全局拦第二店或复用第一店 external_id |
| P0-2 发布语义 | Feed HTTP 成功，未返回在售事实 | SUBMITTED 非 ACTIVE；只有核验正确商品回读后 ACTIVE |
| P0-3 市场 | 商品写 US、目标店 TR；无市场；校验异常 | 只用真实目标国家；缺失/异常阻断真实发布；不能 Adapter 首市场兜底 |
| P0-4 图片权利 | UNKNOWN、RESTRICTED、过期/错市场授权、衍生图 | 正式自动发布拒绝；有效 proof 通过；去 Logo 不改变 rights |
| P0-5 核价 | 两轮核价、币种缺失、FX 缺失、低底价、成本变更 | 不 AUTO_SAFE 接受，快照不可变；旧批准失效；回执不覆盖前轮 |
| P0-6 Scope | 跨 tenant、受限 Store、停用 Membership、SELF_ONLY 未支持 | API/Action/同步/资产下载/列表全部拒绝或过滤；无 fallback 提权 |
| P0-7 恢复隔离 | legacy 与 Launch 同处 queued/租约过期 | 旧恢复器不领取 Launch，新恢复器不领取 legacy；各自恢复一次 |
| P0-8 执行重验 | 批准后撤权、换市场、改资料、换 Profile/成本 | 执行拒绝，目标未变；保留拒绝原因/原审批；不能重放成功绕权限 |

## 3. 业务与界面

| ID | 场景 | 证据/断言 |
|---|---|---|
| UX-A | PERSONAL + GUIDED 简单 Profile | 选择商品/店铺→启动→资料→合规→提交→核验；界面显示当前/缺项/责任人/下一步；数据库三状态正确 |
| UX-B | PROFESSIONAL | 与 A 同 DTO/权限；展开价格、证据、raw status、版本；切模式不增动作 |
| UX-C | 同商品双店 | 简单与复杂 Profile 并行；一店核价不影响另一店进度；Product channels 可进入各实例 |
| UX-D | 低核价 | AI 建议重报/拒绝且 evidence 完整；接受按钮说明阻断；直接请求也拒绝 |
| UX-E | 缺/过期 Artifact | BLOCKED 和 COMPLIANCE_BLOCK，补交→审核→合法恢复；上传本身不通过 |
| UX-F | 标签/实拍 | 无认证不生成标志；缺标签输入不能生成；驳回实拍→新版本补交→独立审核 |
| UX-G | 状态同步 | 真实隔离 ingestion 推进界面；重复不重复事件，错店/乱序不误推进 |
| UX-H | v1→v2 | 新实例选择 v2；旧实例 DAG/映射/hash 不变；不能编辑 PUBLISHED |
| UX-I | 并行 | 复杂 Profile 核价等待时仍能准备合规；依赖未满足不能执行实拍 |
| UX-J | 专业页往返 | Listing/Pricing/Compliance/Supplier 深链固定 launch/shop，保存后返回刷新；伪造参数无权限 |
| UX-K | 历史与重上线 | ACTIVE/PAUSED 仍占活跃槽；核验 OFFLINE 后结束，新轮次新草稿/Action；旧事件不污染新轮次 |
| UX-L | 空/错误/窄屏 | 无店铺/无 Profile/加载失败区分；409 保留表单不自动重发；键盘可用和关键按钮不溢出 |

## 4. 履约、业务事实和 AI

| ID | 场景 | 必须断言 |
|---|---|---|
| BIZ-1 | DROPSHIP | 不因启动 Launch 创建采购/平台库存；按销售订单后采购，供应承诺/交期有来源 |
| BIZ-2 | PLATFORM_STOCK | requested/approved/prepared 区分；部分备货不增销售库存；关联 PO/Warehouse 有归属 |
| BIZ-3 | SELF_STOCK | 库存证据时效/仓库归属/单件仓储费用正确；不足阻断 |
| BIZ-4 | FACTORY_DIRECT | 工厂只读/提交本厂指派步骤；请求与响应均无他厂/财务/买方数据 |
| BIZ-5 | Unit Economics | Store/国家/币种/报价时点贯通；采购物流费用退款税FX全部明细；估算项标注，快照变化触发失效 |
| BIZ-6 | 素材资产 | 版本不可覆盖、父图权利约束、proof 期限/范围；标签 manifest 绑定证据版本 |
| BIZ-7 | AI 边界 | 所有 Agent 经 Orchestrator/Tool；Pricing 只分析；建议字段完整且动作是确定性集合子集 |
| BIZ-8 | 销售监控 | source 1688 不进 Launch/GMV；contract/demo 不进真实指标；店铺无法关联的数据返回不可用 |
| BIZ-9 | 通用模型 | Profile 类型/Actor 与平台无关；无 Temu 专表/Agent，TemuAdapter 能力未被测试样本打开 |

## 5. 可靠性与权限

| ID | 故障注入 | 必须断言 |
|---|---|---|
| REL-1 | 提交后进程退出 | intent 先于外部请求，重启 read-back，不重复发布 |
| REL-2 | 状态事务中途失败 | Run/Step/Event 一起回滚，无状态已变但事件丢失 |
| REL-3 | Outbox 消费后确认前退出 | 至少一次投递、消费者 event_id 幂等，只产生一次建议/通知 |
| REL-4 | 租约过期双 worker | revision/唯一键保证唯一有效执行；旧 owner 不覆盖新租约 |
| REL-5 | 无查询能力的 UNCERTAIN | 显式人工核对，不盲重发、不标 ACTIVE |
| REL-6 | Webhook 假签名/旧时间/错店/重复异载荷 | 拒绝，审计脱敏；同 event_id 不可替换载荷 |
| REL-7 | UNKNOWN raw status | 保留原始来源/映射版本，阻断自动推进 |
| REL-8 | 等待数小时/超时 | 无长期占 worker；通知按 deadline 去重；按 policy 超时 |
| SEC-1 | OWNER/OPERATOR/READ_ONLY/COMPLIANCE | API、Action、菜单矩阵与设计一致；合规投影无财务 |
| SEC-2 | Factory/Platform/代客 | 受限门户、无业务空间拒绝、代客身份审计可追溯 |
| SEC-3 | Membership/Store 变更 | 查询和执行都重新解析；未知 scope fail closed；不使用客户端权限 |

## 6. 迁移与回归门禁

MIG-1 空库 upgrade；MIG-2 历史 21 库 upgrade 与原业务内容保留；MIG-3 一致备份副本 upgrade/preflight/FK/integrity；MIG-4 回填重复执行；MIG-5 无新数据 downgrade→upgrade；MIG-6 有版本/外部事实 downgrade 拒绝；MIG-7 保护主库路径与 WAL/SHM；MIG-8 PostgreSQL 完整迁移（生产门禁，未运行不冒认）。

Legacy 回归包括原模板运行/失败/审批/恢复/调度、原 Listing 草稿/复核、商品与采购/库存/订单/财务/1688 隔离、Workspace 双读/Factory 门户。权限用例同步到 `backend/tests/test_security.py`。

实施结束须执行后端 pytest 正序与反序、ruff、前端 npm test/build、文档一致性；基线统一引用 `docs/baseline.json`。真实启动隔离服务执行 `backend/scripts/e2e_feasibility.py`，另执行本轮 Playwright；涉及 Docker/依赖/构建链变更执行容器可行性及相关 TLS 验证。不能为绿灯放宽既有断言。

## 7. 结果登记

当前所有 case 为 NOT_RUN，原因是本批只设计。具体命令、退出码与失败项在 `docs/PLATFORM_WORKFLOW_PROGRESS.md` 逐批追加。验收矩阵中的要求只有对应当前提交的权威证据才能改为 PASS；平台真实验收与本地 Contract 验收分别报告。
