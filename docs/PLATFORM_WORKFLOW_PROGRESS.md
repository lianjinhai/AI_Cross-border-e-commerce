# Platform Workflow / Launch Center 进度

> 最后更新：2026-10-11。状态：DESIGN_FROZEN / IMPLEMENTING_P0。目标：用户 V2 全量设计、实施和本地验收；真实平台联调取决于授权，不假装完成。

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
| B Profile/Runtime/Transition | NOT_STARTED | 复用三表和旧引擎机制 |
| C 隔离迁移演练 | PARTIAL | Expand 1a/1b 合成历史库已演练；完整副本仍待验证，主库不动 |
| D 领域服务 | NOT_STARTED | Costing/核价/备货/Artifact/Asset/Label |
| E 前端 | NOT_STARTED | 同页双模式、渠道/深链、Factory 投影 |
| F 本地 Profile | NOT_STARTED | SIMPLE_CONTRACT / COMPLEX_CONTRACT |
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
