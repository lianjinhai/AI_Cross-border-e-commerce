# FRONTEND_V9_VISUAL_ACCEPTANCE.md

> V9 真实视觉验收基线。本文件记录「在同一屏幕、相同角色、可比较数据」下，旧前端 vs V9 的逐项对照与验收方法。
> 当前状态：已建立 V9 独立验收入口（8001 静态接管版 / 5174 dev），旧前端（8000）保留可回退。
> 说明：真实 13 页浏览器逐页截图需在有 GUI 的验收会话执行；本文件给出**可复现的验收清单与判据**，避免「用设计效果图冒充系统截图」。

---

## 一、验收环境与入口

| 角色 | 入口 | 说明 |
|---|---|---|
| V9 接管（正式） | `http://127.0.0.1:8001/` | 后端托管 `frontend-v9/dist`，可登录 |
| V9 开发联调 | `http://127.0.0.1:5174/` | Vite dev，`/api` 经 `VITE_API_PROXY_TARGET` 指向 8001 |
| 旧前端（回退） | `http://127.0.0.1:8000/` | 托管 `frontend/dist` |

测试角色：`admin/admin123`（OWNER 全权限）、`ops/ops123`（OPERATOR）、`viewer/viewer123`（READ_ONLY）。
外部平台未授权时，相关能力须显示「待接入 / 人工处理」，**禁止假按钮 / 假成功态**。

## 二、13 页对照清单（旧 → V9 → 判据）

| # | 页面 | 旧路由/组件 | V9 路由/组件 | 必验判据 | 旧→V9 信息架构是否变化 |
|---|---|---|---|---|---|
| 1 | 登录后首页 | /dashboard Dashboard.vue | /app WorkspaceHome | 8 域侧栏出现、按 Workspace/经营阶段组织、Task Center 入口 | 待截图 |
| 2 | 左侧导航 | 旧 11 域 | V9 8 域 | workbench/discovery/supply/channel/orders/optimize/finance/ai，设置沉入账号菜单 | 待截图 |
| 3 | 商品列表 | /products | /app/products | 8 类数据真实性标签、11 态渲染、待接入页无假按钮 | 待截图 |
| 4 | 商品详情 | 旧 | /app/products/:id | EvidencePanel、MoneyValue | 待截图 |
| 5 | Launch Center | /launch | /app/launch | V9 设计、十步校验链状态可见 | 待截图 |
| 6 | 店铺管理 | /shops | /app/channels/shops | 渠道推荐 CH-01、店铺详情 CH-03 | 待截图 |
| 7 | 供应商管理 | /suppliers | /app/supply/suppliers | 货源 SU-01、匹配 SU-04 | 待截图 |
| 8 | 订单详情 | /orders | /app/orders | 订单工作台、履约状态 | 待截图 |
| 9 | 财务分析 | /finance | /app/analytics/finance | 真实利润、预测 BI-02 | 待截图 |
| 10 | AI 运营 | /workflows | /app/ai/workflows | Agent Runs、AI Actions（待接入标记）| 待截图 |
| 11 | Workspace 设置 | /users | /app/settings/team | requiresOwner、权限矩阵 | 待截图 |
| 12 | 工厂门户 | /factory-portal | /factory/products | 工厂协作角色投影 | 待截图 |
| 13 | 平台管理后台 | /platform-admin | /console/overview | 平台管理员后台 | 待截图 |

> 注：V9 的 15 个新页 + 8 域导航已在 `frontend-v9/src` 落地并通过 417 测试与 build；
> 但**逐页浏览器截图必须在上表入口实际打开并保存**才算「视觉验收完成」。

## 三、每页必须检查的 8 个维度（指令 §六）

1. 信息架构是否改变（相对旧界面）；
2. 页面结构是否改变；
3. 主要操作是否更清晰；
4. 业务数据是否正确（真实后端，非 mock）；
5. 新视觉组件（BusinessStatus/NextActionPanel/AsyncActionDialog/MoneyValue/EntityLink/DataQualityBanner）是否真正被引用；
6. 是否存在旧组件混入；
7. 是否存在空白页 / 占位页（待接入页应显式标记，非空白）；
8. 是否存在响应式问题。

**禁止**用设计效果图冒充实际系统截图；截图必须来自 8001/5174 真实渲染。

## 四、真实业务操作验收（指令 §八，真实本地后端 + 隔离测试库）

须验证：登录 → Workspace 切换 → 页面权限 → 商品/供应商/店铺查看 → Launch 列表与详情 → 跨页跳转 → AI 建议 → 审批 → 数据分析 → 工厂门户。
- B03–B09 动作未实现：必须显示「待接入 / 人工处理」，**不得出现假按钮 / 假成功**。
- 无外部平台授权：用标记为测试数据或 Contract 环境，**不得冒充已接入真实平台**。

## 五、尚未接管的旧页面 / 业务能力（下一批必修）

| 类别 | 项 | 状态 | 原因 |
|---|---|---|---|
| 部署 | 正式入口 8000 仍指旧 dist | 待切换 | 需设 `ERP_FRONTEND_DIST` 指向 V9 并重启（可回退）|
| 部署 | Dockerfile 只构建旧 frontend | 待补 | 需新增 V9 构建阶段 + entrypoint 注入 |
| 页面 | /app/optimization/experiments 策略实验 | StubPage（P2）| 蓝图 P2 待接入 |
| 能力 | B03–B09 动作 | 待接入 | 后端 Action 框架仅 B01/B02 落地 |
| 页面 | 部分 P1 页真实数据 | 部分待接入 | 后端端点未核 §7#10 |
