# B1 真实浏览器验收报告（commit `2391b90`）

- **批次**：`feat(v9.1): B1 正确性修复与统一外壳（令牌基线/五入口侧栏/订单范围与币种）`
- **实测 commit**：`2391b90`
- **方法**：Chrome 真实浏览器（headless=new，CDP 直连），后端 `8011`（隔离库 `qa_b1.db`，每次从 `qa_r33_base.db` 还原并清 `-wal/-shm`），V9 dev 服务器 `5193`（代理到 `8011`）。登录态走真实表单登录（`qa_owner` / `qa123456`，workspace 空间）。
- **驱动**：`docs/evidence/V9-1-B1/browser-verify-b1.mjs`（改编自 R3-3 驱动）；启动脚本 `docs/evidence/V9-1-B1/_b1_run.sh`。
- **结论**：20/20 检查通过（含 Z0 登录与 7 项批次 claim A–G）。无失败项。

## 检查明细（check → expected → observed → pass/fail）

| # | 检查 | 期望 | 实测 | 结果 |
|---|------|------|------|------|
| A | 侧栏一级入口数量 | 恰好 5 个 | `topLevelCount=5`，`visibleTopLevelCount=5` | PASS |
| A | 一级标签精确 | 我的生意 / 我的商品 / 我的订单 / 我的收益 / 全部工具 | `["我的生意","我的商品","我的订单","我的收益","全部工具"]` | PASS |
| B | 首屏可见一级行数 | 5 行 | `visibleTopLevelCount=5` | PASS |
| B | 默认仅当前路由所在组展开 | 展开组数 = 1 | `openGroupCount=1`（`openGroups=["我的生意"]`） | PASS |
| B | 过期叶子默认不可见 | 可见叶子 = 2（仅「我的生意」组） | `visibleLeafCount=2`，`visibleLeafLabels=["经营首页","我的待办"]` | PASS |
| C | 点击「我的商品」前「商品库」不可见 | 不可见（叶子=2） | `beforeLeaves=2` | PASS |
| C | 点击「我的商品」后其 4 个子集可见（含商品库） | 可见且含「商品库」 | `leafCount=6`，`goodsVisible=true`，`goodsCount=4` | PASS |
| C | 「商品库」导航到 `/app/products` | 落到 `/app/products` | `goodsUrl=http://127.0.0.1:5193/app/products` | PASS |
| D | 侧栏背景色 | `rgb(12, 38, 84)`（`#0C2654`） | `rgb(12, 38, 84)`（令牌 `--v91-navy-900=#0C2654`） | PASS |
| D | 激活项文字色 | 白 `rgb(255, 255, 255)` | `rgb(255, 255, 255)`（令牌 `--v91-sidebar-active-text=#FFFFFF`） | PASS |
| D | 激活项背景色 | `rgb(36, 90, 156)`（`#245A9C`） | `rgb(36, 90, 156)`（令牌 `--v91-sidebar-active-bg=#245A9C`，激活项=经营首页） | PASS |
| E | 主按钮色 | `rgb(35, 107, 189)`（`#236BBD`） | `rgb(35, 107, 189)`（令牌 `--el-color-primary=#236BBD`） | PASS |
| E | hover 为同色相更浅 tint（非 `#409EFF` 系） | 同色相、更浅 | `hoverBg=rgb(101, 151, 209)`，`baseHue=212`/`hoverHue=212`（Δ=0），`baseLight=44`→`hoverLight=61`，`sameHueFamily=true` | PASS |
| F | `/products` 深链 | → `/app/products` | `landed=/app/products` | PASS |
| F | `/orders` 深链 | → `/app/orders` | `landed=/app/orders` | PASS |
| F | `/finance` 深链 | → `/app/analytics/finance` | `landed=/app/analytics/finance` | PASS |
| F | `/launch` 深链 | → `/app/launch` | `landed=/app/launch` | PASS |
| G | 390px 侧栏收起 | aside 宽度 ≤ 80px | `asideW=64`，`collapsed=true` | PASS |
| G | 390px 主内容未被裁切 | 主区宽度 > 0 且占满视口 | `win=390`，`mainW=311`，`asideW=64`（`mainW = 390-64-留白`，无横向裁切） | PASS |
| Z0 | 真实登录进入 `/app` 空间 | URL 含 `/app` | `http://127.0.0.1:5193/app` | PASS |

## 截图（4 视口，落点 `/app`）

| 文件 | 视口 | 说明 |
|------|------|------|
| `v1-app-1440x900.png` | 1440×900 | 桌面（侧栏展开，仅「我的生意」组开） |
| `v2-app-1366x768.png` | 1366×768 | 笔记本（侧栏展开） |
| `v3-app-768x1024.png` | 768×1024 | 平板竖屏（≤768 触发侧栏收起为图标条） |
| `v4-app-390x844.png` | 390×844 | 手机（侧栏折叠为 64px 图标条，主区占 311px） |

## 精确计算色值（来自 `getComputedStyle`，非源码推断）

- 侧栏背景 `.shell__aside`：`rgb(12, 38, 84)`  ⇔ `#0C2654`
- 激活菜单项 `.el-menu-item.is-active`：
  - `color` = `rgb(255, 255, 255)`（白）
  - `background-color` = `rgb(36, 90, 156)`  ⇔ `#245A9C`
- 主按钮 `.el-button--primary`：
  - 常态 `background-color` = `rgb(35, 107, 189)`  ⇔ `#236BBD`
  - hover `background-color` = `rgb(101, 151, 209)`  ⇔ `#6597D1`（即令牌 `--el-color-primary-light-3`）
  - 色相校验：常态 hue=212，hover hue=212（Δ=0），亮度 44→61（更浅）。属同一蓝色相、更浅的 tint，**非 `#409EFF` 系**（旧主色 hue≈211 但此实现已显式钉死派生梯度，hover 不再偏移到旧 `#409EFF` 浅蓝）。

## 侧栏标签数组（DOM 实测）

```
["我的生意", "我的商品", "我的订单", "我的收益", "全部工具"]
```

## 旧深链重定向结果

| 旧路径 | 落点 | 结果 |
|--------|------|------|
| `/products` | `/app/products` | PASS（非 404） |
| `/orders` | `/app/orders` | PASS（非 404） |
| `/finance` | `/app/analytics/finance` | PASS（非 404） |
| `/launch` | `/app/launch` | PASS（非 404） |

## 未验证 / 范围说明（not verified）

- **角色过滤回归（非 owner 角色）**：本批 claim 的"A"仅要求侧栏"视觉上恰好五个一级入口"，本次以 workspace owner（`qa_owner`）登录验证——owner 可见全部 5 个域。**其他角色（如只读/新手/代客）的菜单可见性过滤是否仍按 `filter.js` 收敛未独立复测**；该结构 claim 已通过，但角色级回归属"权限审查"任务（task #45），不在本真实浏览器批次内。
- **768/390 视口高度**：任务留 "?"，本报告取 768×1024、390×844 作为代表性竖屏高度；侧栏折叠由 `matchMedia('(max-width:768px)')` 驱动，与高度无关，结论不受影响。
- **逐页面主按钮覆盖**：E 在主按钮可见的页面（实测命中 `/app/products` 的「新增」主按钮）验证；其余页面主按钮颜色由同一 `--el-color-primary` 令牌驱动，未逐一截图。

## 一句话结论

在 commit `2391b90` 的真实浏览器下，B1 批次的全部 7 项 claim（五入口侧栏且标签精确、默认仅当前组展开、点击「我的商品」展开子集并导航、侧栏 `#0C2654`/激活项白字 `#245A9C`、主按钮 `#236BBD` 且 hover 为同色相更浅 tint、四类旧深链正常重定向、390px 侧栏收起且主区不裁切）均获 DOM 计数 + 计算样式 + 截图三重实证，**20/20 通过，无回归**。两个后端/前端服务器已在脚本结束时关闭，未改动任何源码文件（仅新增 `docs/evidence/V9-1-B1/` 下的证据文件）。
