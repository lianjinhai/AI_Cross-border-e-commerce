# V9.1 S5 验收报告：销售准备、成本决策与订单履约联动

- 执行日期：2026-10-20
- 基线提交：`d4cbb78`（S4）
- 结论：**S5 内部闭环 PASS**；外部发布/物流/平台回执维持 BLOCKED（如实标注，不伪造）
- 验收方式：隔离副本库 + 真 uvicorn + 真实 HTTP（**22/22 PASS**），主库 SHA256 前后一致

## 1. 门槛逐条判定

| # | 门槛 | 判定 | 证据 |
|---|---|---|---|
| 1 | 成本与订单范围一致（同一店铺范围） | PASS | 详情入口 `resolve_workspace_context` + `resolve_store_scope.require(order.shop_id)`；越权/跨租户 404 |
| 2 | 页面跳转不复制 ID | PASS | 详情抽屉按 `row.id` 调 `GET /orders/{id}`，不复用列表行数据、不把 ID 拼进路由 |
| 3 | 订单/采购/结算三套口径不混算 | PASS | 真机：EUR 订单金额 `120.00`、CNY 采购应付 `90.00`、结算 `120-12.5=107.5` 三处独立读数 |
| 4 | 关联真实（商品/采购/履约/费用） | PASS | `sales_order_id=524`、`shop_name/product_title` 非空、费用按币种汇总 `{EUR: 12.5}` |
| 5 | 外部等待不误报上线/成交 | PASS | 订单 `source=import`；代发 `mode=demo` + `DEMO...` 单号；`tracking_available=false` 且无轨迹字段 |
| 6 | 利润风险页不另写前端公式 | PASS | `Bi.vue` 取后端利润序列，`LandedCost.vue` 复用 backend costing，仅做百分比展示 |
| 7 | Finance Agent 只分析不执行金融动作 | PASS（沿用既有） | 财务口径无 AI 执行型 Action，`settlement` 仅事实写入 |
| 8 | 上线工作台复用 DAG 并展示阻断/回执 | PASS（沿用既有） | `LaunchDetail.vue`：WAITING_EXTERNAL 显式标注、`lastReceipt.{changed,stillMissing,nextAction}` |

## 2. 本批改动

- `backend/app/routers/orders.py`：新增 `GET /orders/{id}`（订单事实 + 行 + 费用 + 关联采购 + 退款 + 履约 + 口径说明）。
- `backend/app/services/tenant_data_purge.py`：修复 B3 遗留外键环 —— `products.selected_offer_id → supplier_offers.id`
  与 `supplier_offers.product_id → products.id` 互引，纯拓扑序无解；清理前显式置空 `selected_offer_id`，
  并以 `_CYCLE_BREAKS` 登记，静态顺序守护据此豁免该边。
- `backend/tests/test_order_detail.py`（新，4 项）：真实关联不混币种 / 轨迹不伪造 / 越权与缺失 404 / 只读可看不可发货。
- `backend/tests/test_shop_archive_and_purge.py`：拓扑序守护支持显式断环；新增
  `test_purge_succeeds_when_product_has_selected_offer`（用真实 API 造出「已选定报价」状态，证明清理不是靠演示数据恰好为空蒙过）。
- `frontend-v9/src/shared/orderDetailView.js`（新）：`feeLabel/feeTotalsText/purchaseTotalsText/refundTotalText/detailWarnings`。
- `frontend-v9/src/api/domains/orders.js`：`fetchOrder(id)`。
- `frontend-v9/src/pages/fulfillment/Orders.vue`：列表加「详情」入口 + 详情抽屉（订单信息 / 钱款网格 / 订单行 / 费用事实 / 关联采购 / 退款）。

## 3. 验证记录

| 验证 | 命令 / 方式 | 结果 |
|---|---|---|
| S5 真机门槛 | 隔离副本库 + uvicorn:8139 | **22/22 PASS**，主库 SHA256 `1216b7124595` 不变 |
| 订单详情单测 | `pytest tests/test_order_detail.py` | **4 passed** |
| 订单/店铺归档回归 | `pytest test_order_detail test_orders test_orders_shop_scope test_shop_archive_and_purge test_role_permissions` | **24 passed**（修复外键环前为 23 passed / 1 failed） |
| 选定报价/商品总览联动 | `pytest test_order_detail test_shop_archive_and_purge test_selected_offer test_product_overview` | **29 passed** |
| 前端全量单测 | `vitest run` | **729 passed / 58 files** |
| 前端构建（SFC 编译） | `vite build --outDir $TEMP/dist_s5` | 成功（9.47s） |
| 文档门禁 | `check_docs_consistency.py --json` | `total=0` |

真机关键读数（隔离库）：
- 导入订单 `#524`：`source=import`、`currency=EUR`、`amount=120.0`、`cost=70.0`、`profit=50.0`（未换算）。
- 费用 `commission 12.5 EUR` → `fees.total_by_currency={"EUR":12.5}`，`totals.amount` 仍 `120.0`（不冲减）。
- 代发采购 `PO-DS2026102010462599`：`sales_order_id=524`、`purchases_by_currency={"CNY":90.0}`、`mixed_currency=true`、
  回执 `mode=demo` / `DEMO202610201046250899`（演示通道如实标注，不称真实下单）。
- 发货：`status=shipped`、`tracking_no=SF1792464385397`、`tracking_available=false`，响应无 `events/trajectory`。
- 结算：`S5-SETTLE-1` gross 120 / fee 12.5 / net 107.5 → `reconciled=true`、`variance=0`；订单详情 `totals` 无结算字段。

## 4. 失败与修复

1. **代发 400「无报价记录」**：业务前置校验真实存在（成本必须可归集），非接口缺陷。验收脚本改为先
   `POST /suppliers` + `POST /suppliers/offers` 再代发，符合真实业务顺序。
2. **`test_purge_plan_order_is_topologically_valid` 失败（B3 遗留缺陷）**：
   `products.selected_offer_id` 在 B3 新增后与 `supplier_offers.product_id` 形成外键环，清理计划无纯拓扑解。
   该缺陷在「演示数据里恰好没有选定报价」时不会被真实清理用例暴露，属潜在 500。
   修复方式为显式断环 + 静态守护豁免 + 真实状态回归用例（见 §2）。

## 5. 未完成能力（如实记录，不伪造）

| 能力 | 状态 | 说明 |
|---|---|---|
| 物流轨迹 / 到达时间 | BLOCKED（外部） | 未接入承运商轨迹 API，仅回单号；前端显示「轨迹未接入」 |
| 平台真实结算单回执 | BLOCKED（外部） | 结算为人工/回调写入的事实记录，`source` 未标成平台实时拉取 |
| 1688 真实代发下单 | BLOCKED（外部授权） | 演示店铺走 `demo` 通道并标注；真实店铺需 OAuth 授权 |
| 订单全量聚合（多店 GMV 汇总） | 未接入 | 详情仅单订单；列表无跨店铺金额聚合口径 |
| 图片 07/08/09/10 逐图像素级复原 | 未做 | 原型图未入库，本批按「交互与后端闭环」验收，不做视觉百分比结论 |
