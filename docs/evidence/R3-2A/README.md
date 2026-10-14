# R3-2A 证据：4+1 入口导航收敛 + 顶栏上下文条

> 批次：AI-电商ERP V9.1 R3-2A ｜ 基线 HEAD：`ce2211e` ｜ 日期：2026-10-14
> 实现：`frontend-v9` 导航树由 **8 域 26 项** 收敛为 **4+1 入口**（mybiz/goods/orders/revenue/tools）；
> 顶栏新增持续可见的 **Workspace/店铺范围 + 任务三计数** 上下文条（baseline §3）。

## 1. 复现方式

前提：`frontend-v9` dev 服务器（5174）与后端（8000）已启动。

```bash
# 单测 + 构建
cd frontend-v9 && npm test && npx vite build --outDir .verify --emptyOutDir   # 沙箱下 dist 清理受 safe-delete 限制，用临时 outDir 验证

# 浏览器验收（CDP 直连系统 Chrome）
cd ../docs/evidence/R3-2A
NO_PROXY=127.0.0.1,localhost node browser-verify.mjs
```

## 2. 浏览器实测结论（脚本输出，1440×900）

| 断言 | OWNER（admin） | READ_ONLY（viewer） |
|---|---|---|
| 侧栏顶层入口 | 4 分组（我的生意/我的商品/我的订单/我的收益）+ 1 折叠项（全部工具） | 同左 |
| 叶子总数 | **39**（8 域 34 + settings 5，无遗漏） | **33**（隐藏 5 条 settings + 合规工作台） |
| tools 默认态 | `is-opened=false`（折叠） | `is-opened=false` |
| tools 展开态 | 点击标题后 `is-opened=true` | 可展开 |
| 顶栏上下文条 | 演示商家 · 全部店铺 ｜ 待我处理 3 ｜ 等待外部 0 ｜ 被阻断 0 | 演示商家 · 全部店铺 ｜ 待我处理 **—** ｜ 等待外部 0 ｜ 被阻断 0 |
| 只读横幅 | 不显示 | **显示**（只读模式） |
| 叶子导航 | 点「上线中心」→ `location.pathname=/app/launch` ✓ | — |

> 关键红线验证：READ_ONLY 的「待我处理」源被跳过（无审批/复核权限）→ 计数 `null` → 渲染 **「—」而非 0**，符合 baseline §5「失败/不可得不得当 0」。

## 3. 截图

| 文件 | 内容 |
|---|---|
| `01-sidebar-owner.png` | OWNER 侧栏：4 入口 + 全部工具（折叠） |
| `02-tools-expanded-owner.png` | OWNER 展开「全部工具」工具柜 |
| `03-topbar-context-owner.png` | OWNER 顶栏整屏（含上下文条） |
| `03b-topbar-crop.png` | 顶栏 2× 特写：Workspace · 店铺 · 三计数·面包屑 |
| `04-sidebar-readonly.png` | READ_ONLY 侧栏（无 settings / 无合规工作台 / 只读横幅） |
| `05-leaf-launch-owner.png` | 点击「上线中心」落地 `/app/launch` |

## 4. 与任务契约的差异登记

1. **settings 归位**：任务要求 settings 5 条 path 进 `tools`（与 baseline §2 工具柜「…、设置」一致）；
   本批据此把 `/app/settings/*` 从账户菜单回归 tools。配套将 `NON_OWNER_HIDDEN_PATHS`
   扩为**全部 `/app/settings/*`**，与 `routeRedirect` 的 `OWNER_ONLY_PREFIX` 守卫严格一致，
   避免非 OWNER 侧栏出现「可点但必被逐出」的死项（**收紧**，非放宽）。
2. **COMPLIANCE 可见面**：任务描述为「仅 goods 内合规两项 + tools 内合规工具」，但
   `COMPLIANCE_ALLOWED_PATHS`（菜单与路由守卫**同一事实源**）被 `permissions.test.js`
   与 `routeRedirect` 冻结为 6 条（含 `/app`、`/app/analytics/bi`、`/app/listings`、`/app/launch`）。
   为「不破坏守卫/不改路由表/不放宽既有断言」，本批**保持该白名单冻结**，COMPLIANCE 菜单
   即白名单映射结果（mybiz+goods+revenue+tools，6 条叶子）。已登记为遗留项（见 §5），
   建议后续单独评审是否收紧守卫白名单。
3. **面包屑**：未改路由 `meta`（铁律：不动路由注册）。`meta.domain → 新入口` 映射留待后续，
   面包屑继续按既有 `meta.domain/title` 渲染（`document.title`/守卫不受影响）。

## 5. 遗留风险

- COMPLIANCE 守卫白名单与 ownership matrix §5 的可见性描述存在口径差（见差异登记 2），
  本批未动守卫以免连带破坏 `permissions.test.js`；后续若收紧需同步改守卫 + 断言。
- `sections.in_progress` 未直接暴露 `platform_status`，故「等待外部」以 `execution_status`
  为主口径；若后端后续在 `in_progress` 补 `platform_status`，`isWaitingExternalItem` 已兼容。
