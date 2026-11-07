# V9-1-M2-E · 标签包：依据不足不得生成

> 执行日期：2026-11-07　基线：`main` @ `f064848`（本批改动提交前）
> 结论：**PASS（含明确边界）**——依据不足时 `GENERATE_LABEL` **409 逐条点名缺哪条、去哪补、零写入**；
> 补齐证据后可生成；证据一变（过期 / 被替换）标签包立刻失效且步骤重新阻断。
> 但本批**只生成内容与依据指纹**：不打印、不上传、不向平台发送，印刷信息缺口显式列出。

## 1. 这批要解决什么

标签是整个上线链上**最容易凭空捏造**的一步：印一张写着 CE / EPR 的标签，比拿到 CE 证书便宜太多。
此前 `GENERATE_LABEL` / `REGENERATE_LABEL` 是禁用态（`DISABLED_LABEL`），于是有两种坏结局：

1. 用户绕过流程，在群里/表格里自己拼一版标签 —— 依据没人核，出了问题查不到是「按哪份证书印的」；
2. 一旦接通但门禁写松（「没查到要求就当没要求」），系统会自动给所有市场发绿灯标签 ——
   而 `compliance_registry.check_evidence()` 对**未收录国家**返回的正是 `passed=True, required=[]`。
   照抄这个 `True` 就是合规事故。

所以本批的核心不是「把标签画出来」，而是**把「依据」变成可计算、可失效、可追溯的东西**：
一版标签包必须钉住「当时用的哪些要求 + 哪几条证据引用 + 各自有效期」，任何一项变了，
这版标签就不再成立。

## 2. 做了什么

### 2.1 迁移 Revision 33：`label_packages`（`backend/migrations/versions/20261107_33_label_packages.py`）

| 口径 | 实现 |
|---|---|
| 只增不改 | 无 UPDATE 路径；重生成 = `version + 1` 追加新行 |
| 依据必须可追溯 | `basis`（要求 + 证据引用 + 有效期）与 `basis_fingerprint`（sha256）双列落库 |
| 内容可复核 | `content` + `content_digest`（sha256） |
| 缺口不隐藏 | `open_items`（本系统给不出的印刷字段）显式落库 |
| 幂等/防重 | `UNIQUE(tenant_id, product_id, shop_id, destination_country, version)` |
| 降级安全 | `downgrade()` 有数据时 `raise RuntimeError("...拒绝有损降级...")` |

`upgrade()` 用 `sa.inspect(bind).has_table` 幂等跳过；6 条索引覆盖租户/商品/店铺/运行/步骤/国家维度。
新表已登记进 `services/tenant_data_purge.py` 的 `_PURGE_PLAN`（按 FK 拓扑序，位于 `PriceRound` 之后），
否则「清理演示数据」会撞外键。

### 2.2 服务层（`app/services/label_packages.py`）

- `resolve_basis(db, tenant_id, product, country, at=None)` —— **唯一依据口径**。复用
  `compliance_registry.check_evidence()`，但补上它缺的那一半：`required == []`（该国未收录）
  → `covered=False`，理由写明「这是『未知』而不是『无需认证』，不能据此生成标签」；
- `_fingerprint()` —— sha256(`{country, requirements[[name,mandatory]], satisfied[[name,evidence_ref,valid_until]]}`)，
  证据引用换一版、证书续期一天，指纹都变；
- `generate(..., require_existing=False)` —— 前置校验在此收口，`require_existing=True` 时
  无旧版一律 `LABEL_PACKAGE_ABSENT`（「重新生成」不能凭空造第 1 版，否则版本号与审计链对不上）；
- `basis_current()` / `latest()` / `history()` / `label_facts()` —— 供读模型与前端。

### 2.3 两个动作真正接通（`launch_action_catalog.py` / `launch_handlers.py`）

- `GENERATE_LABEL` / `REGENERATE_LABEL`：`connected=True`，权限 `launch:label_manage`；
  来源状态 `{READY, BLOCKED, COMPLETED}` —— 三个都是真实来源：首次生成 / 依据失效后重生成 /
  已有一版想再版。**只给 READY 会让用户卡死在阻断态**（与 `WAITING_EXTERNAL` 同源的坑）；
- 回执固定声明 `"note": "本地生成的标签包；未打印、未上传、未向平台发送"`，
  并断言 `predicates={"verified_artifact": {"LABEL_PACKAGE": True}}`；
- `launch_facts` 增加 `facts["label"]`（含 `complete/reasons/package_current`），
  `verified_artifact["LABEL_PACKAGE"]` 由 `package_current` 决定 —— 依据一变，完成条件自动不成立。

### 2.4 阻断码 `LABEL_BASIS_MISSING`（`launch_rules.py` / `launch_repair.py`）

- `BLOCK_CODES["LABEL"]`：**不折回** `COMPLIANCE_BLOCK`（那是合规材料步骤的码）；
- `_label_message()` 把 `facts.label.reasons` 拼进原因（最多 3 条 + 总数），
  与 409 时逐条给出的 `blockers` 同一口径；
- `repair_action()` 新增条目：`kind=ROUTE`、`path=/app/products[/{id}]`、
  `label="去商品详情补目的国合规证据"`、`connected=True`。

### 2.5 只读端点与前端

- `GET /api/cross-border/products/{id}/labels`（`routers/cross_border.py`）：
  只读、`{items[], basis?}`；给 `country` 必带 `basis`，给 `shop_id` 追加 `basis.package_current`。
  **不提供写入口** —— 标签生成必须走上线流程的 `GENERATE_LABEL`（依据门禁 + 版本 CAS），
  不造第二扇门；
- `frontend-v9/src/shared/complianceView.js`：纯函数 `complianceBasisView()` / `labelHistoryView()`
  （组件逻辑抽纯函数，本仓无 `@vue/test-utils` 也能测）；
- `features/product/ComplianceEvidence.vue`：商品详情页「目的国合规要求与证据」卡片 ——
  要求 × 状态 × 证据表、补录证据对话框、标签版本只读表、加载失败 **fail-closed 清空依据**。

## 3. 验收逐条

| 判据（任务原文） | 结果 | 证据 |
|---|---|---|
| 依据缺失时推进动作被阻断，**非 500** | ✅ | `test_missing_evidence_blocks_generation_and_writes_nothing`：409 `ACTION_PRECONDITION_FAILED` + `LABEL_BASIS_MISSING` |
| 依据缺失时**非静默成功** | ✅ | 同上：`label_packages` 计数 0、`revision` 未变、步骤仍 `READY` |
| 依据不足时**返回缺什么依据** | ✅ | 同上：消息里逐条出现 `CE` / `EPR`；真机第 4 步 `缺项命中=['CE','EPR']` |
| 依据不足时**返回去哪里补** | ✅ | `repair_action.path = /app/products/{id}`、`connected=True`；真机第 5 步同值 |
| **补齐后可推进** | ✅ | `test_generate_after_evidence_registered_marks_label_verified`：v1 落库、步骤 `COMPLETED`、`marks` 全部挂到具体证据；真机第 7–9 步 |
| 依据不足**不得用虚构认证填充** | ✅ | 标签 `marks` 只来自 `satisfied` 的证据引用（`all(mark["evidence_ref"] ...)`）；`open_items` 显式列出「进口商 / 责任人 / 批号 / 生产日期」等印刷信息 **本系统给不出** |
| 未收录国家不得当作「无需认证」 | ✅ | `test_uncovered_country_is_blocked_not_silently_passed`：先核实 `check_evidence` 对 SG 返回 `passed=True, required=[]`，再断言生成被 409 阻断且消息含「未收录」「不是「无需认证」」 |
| 依据变了标签包立刻失效 | ✅ | `test_expired_evidence_reblocks_a_completed_step`（过期）/ `test_replacing_evidence_invalidates_the_package`（被替换）：`basis_current=False`、步骤回 `BLOCKED`、阻断码 `LABEL_BASIS_MISSING` |
| 只增不改 | ✅ | `test_regenerate_appends_a_version_and_keeps_history`：v1 的 `content_digest`/`basis_fingerprint` 逐字节不变；真机第 14/16 步 |
| 无旧版不许「重新生成」 | ✅ | `test_regenerate_without_a_package_is_rejected`：409 `LABEL_PACKAGE_ABSENT` |
| 越权不可生成 | ✅ | `test_read_only_role_cannot_generate_a_label`：403 `PERMISSION_DENIED`、零标签包、事件数不变 |
| 迁移可逆 / 唯一约束有效 | ✅ | `test_label_packages_migration.py`：真实 alembic 走链、`head=20261107_33`、同版本号被唯一约束挡住、有数据拒绝降级、清空后可回滚再升级 |
| 端点只读 | ✅ | `test_label_packages_endpoint_is_read_only`：`POST` 405、不存在 404、空列表无 `basis` |
| 新拍证据截图 | ✅ | `09-label-normal-1440.png`（依据齐备 + 两版标签）、`10-label-insufficient-1440.png`（阻断态）、`11-launch-label-blocked-1440.png`（流程内阻断 + 补齐入口） |
| 阻断态可读（参照 R3-2） | ✅ | 截图 10：红色「EU 还缺 1 项依据，不能生成标签包 / CE 证据已过期（有效期至 2020-01-01）」+ 表格 `已过期` 红字 + 橙色「依据已失效，需在流程内重新生成」 |
| 主库未被写 | ✅ | 真机隔离副本库；主库 SHA256 `d79bd669…` 与 7517 行前后一致（`run-log-label.txt` §7） |

真机闭环：`backend/scripts/label_e2e.py`（复用 `launch_e2e.py` 的冷备→副本→迁移→真 uvicorn 基座），
**21 步全 PASS**，日志 `docs/evidence/V9-1-M2/run-log-label.txt`。

**变异验证**（证明用例真的在挡东西）：

| 变异 | 结果 |
|---|---|
| 去掉 `generate()` 里的 `resolve_basis(...)` 前置校验 | `test_missing_evidence_blocks_generation_and_writes_nothing` 立刻红（直接落库 v1） |
| 把 `covered=False` 判成 `covered=True`（即信任 `check_evidence.passed`） | `test_uncovered_country_is_blocked_not_silently_passed` 红：SG 静默通过并落库 |
| 撤掉 `_status` 里 `revoked and complete is not True` 分支 | `test_read_model_keeps_the_reblocked_step_blocked` 红：第二次读取返回 `READY` |

## 4. 顺手修掉的两处既有缺陷

### 4.1 被撤销的完成，读一次就「洗干净」

`launch_rules._status` 对 `COMPLETED` 的依据失效会返回 `BLOCKED`，但 `BLOCKED` **不是粘滞态**：
同一次请求里「`_refresh_once` 写入 BLOCKED → `launch_plan` 再求值一次」就变成 `READY`。
症状是**同一步骤的状态取决于被读了几次**，而且洗白时 `blocking_reason` 一起消失 ——
用户看到的是一颗绿灯，拿不到「缺哪条证据」，这正是本批要挡的东西。

修法：`evaluate_readiness(..., revoked=...)` 新增入参，`revoked_codes(steps)` 由
`input_revision > 0` 派生（`input_revision` 的唯一写入点就是「COMPLETED 被降级」，
比 `step.result` 精确 —— 重试也写 result，但那不是完成作废）。撤销过、且完成条件尚未
重新满足的步骤稳定停在 `BLOCKED`；完成条件一恢复即回 `READY`（不是死端）。
四个调用点（`launch_plan` / `launch_dto` / `launch_state.converge` / `launch_status_sync`）全部接上。

### 4.2 新增用例污染了后续上架用例

`test_tenant_compliance_rule_covers_a_country` 会插入一条**租户级** SG 要求行，之前没删。
同一次会话里后续任何 SG 市场的上架用例都被按「缺 LABELING 认证」拦下，
表现为一条与标签毫无关系的「上架合规闸门未通过」——
`test_deep_domains` 与 `test_product_assets` 的发布用例就是这么红的。已改为 `try/finally` 删行，
并在 `_cleanup` 里按唯一标记兜底删除。

### 4.3 一条「单跑绿、全量红」的存量用例

`test_deep_domains.py::TestFunctionDomain::test_illegal_order_ship` 原来同步 2 条 `demo:shopee`
演示订单后取 `items[0]`，再把状态改成 `pending`（这步的响应码没断言）后发货断言 400。
演示同步的状态本身随机，且 `items[0]` 是哪一单取决于**此前累计的演示订单量**——
本批多出 14 条用例把数据量推过临界点后，全量稳定红、单跑绿，看起来像标签功能引入的回归
（在基线 `f064848` 的临时工作树上跑全量是绿的，正是这个差别暴露了它）。

按同一文件下一条用例既有的写法改成「自己导一条 pending 订单」，不再依赖演示数据：
改后 `test_a*/b*/c*/d*` 组合 366 passed（改前 365 passed + 1 failed）。

## 5. 边界（必须与完成一起读）

1. **不打印、不上传、不发送**。本批只生成内容与依据指纹；打印、平台标签模板、面单对接仍属
   B03–B09，未接入。回执里把这句话写死，避免被当成「已交给平台」。
2. **印刷信息给不出**。进口商 / 责任人 / 授权代表 / 批号 / 生产日期不在本系统数据范围，
   一律进 `open_items`，不猜、不填占位符。
3. **「未收录」≠「无要求」**。目的国要求来自 `DestinationComplianceRule` 与合规档案；
   没收录就阻断并指路，不自动放行。租户可补录要求行（`test_tenant_compliance_rule_covers_a_country`），
   这就是「去哪里补」的闭环。
4. **依据齐备 ≠ 认证真实**。`marks` 只声明「系统里有这几份证据引用」，证书真伪由合规员核验；
   本系统不联网查证书。
5. **标签包不随证据自动重算**。依据变了只是「这版不再当前」，要新版必须再走一次
   `REGENERATE_LABEL`（版本只增不改，历史不擦除）。
6. **`ACTIVATION` 之后仍可能阻断**。上线后证据失效只产生整改阻断，不擦除历史完成、
   也不伪造平台下架（沿用状态模型 §3 既有口径）。
7. **截图用本地契约样本**（`label_e2e.py` 的种子商品 + `labelprobe` 店铺，`CONTRACT_TEST` / `UNVERIFIED`），
   与 M2-A / M2-D 的口径一致；页面上「本地流程验证，不代表真实平台接入」的提示保持可见。

## 6. 回归数字

- 本批新增/改动用例：`test_launch_label_packages.py` 11 passed、`test_label_packages_migration.py` 1 passed；
- Launch 相关：`test_launch_rules` / `test_launch_state` / `test_launch_gate_repair` / `test_launch_external_wait` /
  `test_launch_api` / `test_launch_platform_status` / `test_launch_recovery` / `test_launch_nba` /
  `test_launch_actions` 共 **150 passed**；
- 后端全量：`pytest -q` **1076 用例全绿 / 0 failed**（结果落仓库外 junit 解析，
  不使用收尾摘要，避免被 safe-delete 门禁截断）；
- 前端：`npx vitest run` **61 files / 760 tests passed**（含新增 `tests/compliance-view.test.js` 12 条）；
  `npx vite build` 通过；
- `ruff check app` 零告警（新增脚本与用例一并纳入检查）；
- 文档门禁 `check_docs_consistency.py --json` → `total=0`。
