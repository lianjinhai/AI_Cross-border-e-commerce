# FRONTEND V9 · 验收报告 v2（UX-F 全量终验）

> 验收对象：UX-A→E 五阶段交付物（11 提交：f690fea / aed39e8 / 1dd1526 / 2128b60 / 7dd4f69 / c142577 / 2e0ecd8 / 9f4eb68 / eda8729 / e0128a2 / 6a67b17）
> 验收方式：QA 独立重跑 + 总调度独立复核（2026-10-13，UX-F 终验官完成全部验证证据采集）
> 判定：**PASS — 可切换**（P0: 0 / P1: 0 / P2: 3，均非阻断）

## 0. 总判定

| 维度 | 结论 |
|---|---|
| 20 条质量标准 | 18 通过 + 2 排期项（见 §3） |
| 7 类用户旅程 | 7/7 关键路径 200 探活通过，无硬性断点 |
| 测试 | frontend-v9 **295/295**；旧 frontend **171/171**（77 基线超集）；backend **937 passed**；ruff 全绿；文档门禁 total=0 |
| 构建 | vite build 成功；首屏 eager bundle ≈524KB，61 个路由懒加载分包，vendor 手工分包 |
| 切换/回退 | 旧前端 5173 与新前端 5174 均可独立运行；切换=部署层切入口，**零后端动作**；回退=切回旧产物 |

## 1. 全站覆盖矩阵核对（30/30）

- 30 个界面全部有归宿：新页面 / 合并 / 302 旧路径重定向，**无孤儿页面**。
- 遗留 StubPage 仅 2 处：`/app/listings/:id`（单条详情由列表+Receipts/Reviews 分步流承载，独立路由为后续项）、`/app/compliance`（报告中心，并入合规工作台审批流的排期项）——均已在页面标注未交付，**无可点击假入口**。
- V9-E1 四项「待接入」复查通过：AI 会话持久化（副驾驶无历史入口）、定价/广告/客服「查看依据」深链发送端（未接，接收端就绪）、Support→Knowledge 反向互跳（未接）、最后 OWNER 降级（前端未拦截，后端兜底）——全部无假入口。

## 2. 7 类用户旅程走查（J1–J7）

| 旅程 | 角色 | 关键路径探活 | 断点 |
|---|---|---|---|
| J1 | U1 零经验新手 | /app（onboarding 卡）→ /app/market/discovery → 转池 → /app/products | 无 |
| J2 | U2 1688 卖家 | /app/products 采集 → 代发向导 → /app/launch 创建 | 无 |
| J3 | U3 工厂主 | /factory/products 供给目录维护 | 无 |
| J4 | U4 已有店铺卖家 | /app/channels/shops 授权 → /app/launch/:id 双模式详情 | 无 |
| J5 | U5 团队管理者 | /app/settings/team → 审批 /app/ads → /app/analytics/bi | 无 |
| J6 | U6 平台管理员 | /console/login → /console/overview → 代客进入/退出（token 还原） | 无 |
| J7 | U7 工厂协作者 | 登录落 /factory/products，访问 /app 被重定向 | 无 |

dev 探活含旧 302 路径（/dashboard、/orders、/users、/platform-admin?tab=audit 等）全部 200，无 404。

## 3. 20 条质量标准判定

| # | 标准 | 判定 | 备注 |
|---|---|---|---|
| 1 | 全部旧页面有新版本或合并归属 | ✅ | §1 |
| 2 | 视觉与交互风格统一 | ✅ | SectionState 自 UX-E 起收敛；UX-D 存量风格分叉已登记接受（V9-D2） |
| 3 | 登录与 Workspace 切换 | ✅ | defaultLanding 分流 + WorkspaceSwitcher + 代客横幅 |
| 4 | 新手进入引导 | ✅ | onboarding 卡（6 画像分流） |
| 5 | 工厂从 SKU 开始经营 | ✅ | /factory/products 供给目录 CRUD |
| 6 | 已有店铺从实际经营数据开始 | ✅ | 工作台接 workbench BFF partial 完整度透出 |
| 7 | 商品/货源/店铺/Listing 自然流转 | ✅ | 选品转池、渠道只读、授权向导、单页分步流 |
| 8 | Launch Center 链接实际业务操作 | ✅ | 动作经 /actions 四闸，失败可重试，409 回填 |
| 9 | 订单/采购/履约/财务归属正确 | ✅ | 状态机与后端 allowed 映射 diff 一致 |
| 10 | AI 建议有证据与执行状态 | ✅ | AiActionCard 三段式；waiting/notconfigured 态诚实 |
| 11 | 企业和个人共用业务底座 | ✅ | 同 /app/* 域，权限/工作区差异 |
| 12 | 工厂权限独立 | ✅ | factory_network portal 作用域隔离，无卖家数据引用 |
| 13 | 旧权限隔离无退化 | ✅ | 角色过滤/白名单/路由守卫全量平移+测试锁定 |
| 14 | 重要操作有明确反馈 | ✅ | 回执/确认/错误原因/重试入口 |
| 15 | 完整加载/空/失败/外部等待态 | ✅ | SectionState 五态 + WaitingExternal/NotConfigured |
| 16 | 常见屏幕尺寸可用 | ⏳ 排期 | 桌面走查通过；平板/手机简化布局待下批 |
| 17 | 前后端契约一致 | ✅ | 契约回写后逐端点核对（多轮 QA diff） |
| 18 | 现有业务回归通过 | ✅ | 旧 frontend 171/171、backend 937 passed |
| 19 | 无正式页面静态假数据 | ✅ | 红线 grep 全过，待接入项无假入口 |
| 20 | 切换与回退方案 | ✅ | 双前端并存，部署切入口，零后端动作 |

## 4. 缺陷与遗留

| 编号 | 级别 | 内容 | 处置 |
|---|---|---|---|
| V9-E2 | P2 | console/Tenants.vue 未展示 license_note（授权备注）列（后端 admin.py 字段仍在） | 登记在案，接受（纯展示遗漏） |
| — | 排期 | /app/listings/:id 独立详情页、/app/compliance 报告中心 | UX 后续批次，页面已标注 |
| V9-E1 | 备注 | AI 会话持久化/深链发送端/反向互跳/最后 OWNER 约束 | 后端能力未就绪，维持「待接入」 |

## 5. 切换建议

**可以切换。** 前置动作（切换日执行）：
1. 部署层将入口切至 frontend-v9 产物（旧 5173 保留为回退）；
2. 旧 302 路径查表生效，深链兼容；
3. 观察 1 周期（建议 1 周）后再删除 frontend/ 目录（单前端回归），删除前跑旧 frontend 最后一次基线留档。

风险备注：backend 存在 UX-04 WIP（workbench.py 未提交），切换不影响其合入；合入后 frontend-v9 workbench 域链路即完整。
