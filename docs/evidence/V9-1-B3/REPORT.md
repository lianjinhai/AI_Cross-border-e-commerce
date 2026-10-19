# B3 真实浏览器验收报告（选定报价 → 成本口径闭环）

- **批次**：`test(v9.1): B3 真实浏览器验收（隔离库）+ 实测缺陷修复`
- **范围**：B3 选定报价持久化、失效三档、成本口径（店铺/通用 + 市场）、详情与比选一致性
- **方法**：真实 Chrome（内置 `agent-browser`，headless）+ 隔离副本库 + 真实后端 + Vite dev
  - 数据库：`erp.db` 冷备副本 `s2.db`（仓库外），`scripts/migrate.py` 升级到 Alembic head（`20261019_30`）
  - 后端：`uvicorn` 于 `127.0.0.1:8001`，`ERP_DB_URL` 指向 `s2.db`
  - 前端：`frontend-v9` dev server 于 `localhost:5174`，`VITE_API_PROXY_TARGET=http://127.0.0.1:8001`
  - 登录：真实表单（`admin`），非 localStorage 注入
- **结论**：**B3 PASS**（功能、口径、只读 fail-closed、窄屏可用）。验收过程中发现并修复 6 项实测缺陷（见下），修复后回归全绿。

## 种子数据（隔离库内，商品 #63 `S2-E2E-SKU`）

| 报价 | 供应商 | 价格 | 币种 | 库存 | 有效期 | 来源/核验 | 用途 |
|------|--------|------|------|------|--------|-----------|------|
| #61 | S2供应商甲 | 5.00 | CNY | 在库 | 未填 | 人工/已核验 | 正常选定基线 |
| #62 | S2供应商乙 | 3.00 | USD | 在库 | 未填 | 人工/已核验 | 跨币种（不可直接比金额） |
| #63 | S2供应商甲 | 20.00 | CNY | 缺货 | 未填 | 人工/已核验 | `OUT_OF_STOCK` |
| #64 | S2供应商甲 | 7.00 | CNY | 在库 | 已过期 | 人工/已核验 | `EXPIRED` |
| #65 | S2供应商乙 | 6.00 | CNY | 在库 | 未填 | 爬取/待核实 | `UNVERIFIED` |

销售店铺：#13 `S2验收店A`（shopee / SG）、#14 `S2验收店B`（tiktok / TH）。

## 检查明细（检查 → 期望 → 实测 → 结果）

| # | 检查 | 期望 | 实测 | 结果 |
|---|------|------|------|------|
| 1 | 商品库搜索 `S2-E2E` | 命中 1 行，可进入详情 | 1 行；`详情` 跳 `/app/products/63` | PASS |
| 2 | 详情供给区报价表 | 5 条，含来源/核验/库存/有效期 | 5 条，库存显「在库/缺货/—」 | PASS |
| 3 | 详情概览「选定报价成本」 | 未选定时不伪造数值 | 「未选定」，最低在库 ¥5 | PASS |
| 4 | 比选页选定 #61 | 写入成功并新 GET 读回 | `已选定 #61`；成本卡 `offer_id=61` | PASS |
| 5 | 成本依据报价标签 | 选定后标「用户选定」 | 「用户选定（成本按该报价）」 | PASS |
| 6 | 切店铺「全部店铺」 | 通用试算，不冒充店铺利润 | `通用试算：未绑定店铺`，总成本 35.44 CNY | PASS |
| 7 | 切店铺 `S2验收店A` | 店铺口径 + 市场 SG，且重算 | `店铺「S2验收店A」· 市场 SG`，总成本 60.25 CNY | PASS |
| 8 | 切店铺 `S2验收店B` | 口径随店铺变化（市场 TH） | `店铺「S2验收店B」· 市场 TH`，总成本 47.44 CNY | PASS |
| 9 | 跨币种比选 | 不得直接比金额 | `price` 判定「未知·币种不同（CNY vs USD）」 | PASS |
| 10 | 选定缺货报价 #63 | 保留偏好可试算，但显式阻断承诺 | `选定报价限制（OUT_OF_STOCK）` + 文案「不得据此对外报价或采购」 | PASS |
| 11 | 选定过期报价 #64 | 同上（EXPIRED） | `选定报价限制（EXPIRED）` | PASS |
| 12 | 选定未核验报价 #65 | 同上（UNVERIFIED） | `选定报价限制（UNVERIFIED）` | PASS |
| 13 | 选定后删除该报价（MISSING） | 回退最低在库价并标注未被采用 | `offer_id=61` + `自动最低在库价（已选定报价未被采用）` + `选定报价限制（MISSING）` | PASS |
| 14 | 详情页同步 MISSING | 提示失效与回退依据 | 「已选定报价已失效…已回退为最低在库报价（offer_id=61）」 | PASS |
| 15 | 新开页面 + 刷新 | 选定状态持久化 | 详情两次加载均「选定报价成本：¥5」 | PASS |
| 16 | viewer 只读账号 | 写操作 fail-closed | `选定此报价` disabled，tooltip「只读账号无写权限（fail-closed）」；`清除选定` 同样 disabled | PASS |
| 17 | 1440 / 768 / 390 视口 | 无横向溢出，标题可读 | `scrollWidth == clientWidth`（1425/753/375）；标题宽 601/223px | PASS |
| 18 | 390px 比选表 | 固定列不得盖住整表 | 窄屏取消固定列，行内可见供应商/价格/库存 | PASS |

## 验收中发现并修复的缺陷（S2 期间）

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| D1 | 选店铺后 `market` 仍为 `null`，成本口径空转 | `pricing.calc` 只校验店铺，未把店铺市场作为目的国 | `CalcIn` 显式目的国优先，缺省取 `shop.market`（服务端唯一推导点），前端只展示 |
| D2 | 店铺切换器下拉只有 `1..14` 纯数字，且 1688 货源店铺混入销售店铺 | `/shops` 返回 `shop_name`/`role`，壳内读 `name`/`type` | `storeScope.toShellShop` 作为唯一 DTO 适配点；`filterSalesShops` 兼容 `role` |
| D3 | 切换店铺后成本卡不重算 | `useWorkspaceShell()` 每次调用新建 `selectedShopId` ref，页面拿到的是挂载快照 | 店铺范围提升为模块级共享状态（持久化仍以 `v9_selected_shop` 为准） |
| D4 | 比选表「库存」列渲染裸 `true/false` | 模板直接输出布尔 | `matchingView.stockLabel()` 译为「在库/缺货/—」 |
| D5 | 本位币 CNY 报价被标「汇率未知」 | `renderMoney` 对所有缺 `fxDate` 的币种都标 | 本位币 CNY 不标（假缺项），外币仍标 |
| D6 | 390px 页头副标题竖排（1 字/行），窄屏顶栏被裁成「· ⏻」 | `PageHeader` flex 不可换行、标题区未给 `min-width:0`；顶栏 extras 无溢出策略 | 页头可换行 + 标题区 flex-basis；≤560 隐藏面包屑、extras 横向滚动；比选表窄屏取消固定列 |

## 回归

- 后端：`pytest tests/test_selected_offer.py tests/test_product_overview.py tests/test_pricing_outputs.py tests/test_store_scope.py tests/test_security.py` → **57 passed**
- 前端：`vitest run` → **56 files / 710 tests passed**（新增 `money`、`store-scope`、`stockLabel` 三组口径用例）
- SFC 编译校验：`Matching.vue` / `ProductDetail.vue` OK

## 截图

| 文件 | 视口 | 说明 |
|------|------|------|
| `v1-products-list-1440.png` | 1440×900 | 商品库按 SKU 搜索命中 1 行 |
| `v2-detail-1440.png` | 1440×900 | 商品详情：5 条报价、选定报价成本、成本缺项 |
| `v3-matching-1440.png` | 1440×900 | 比选页：选定 #61、逐字段优劣、成本卡（通用试算） |
| `v4-shop-scope-sg-1440.png` | 1440×900 | 切店铺后：`店铺「S2验收店A」· 市场 SG` |
| `v5-expired-offer-1440.png` | 1440×900 | 选定过期报价：EXPIRED 限制提示 |
| `v6-missing-offer-1440.png` | 1440×900 | 选定报价被删：MISSING 回退与「未被采用」标注 |
| `v7-detail-missing-1440.png` | 1440×900 | 详情页同步失效提示（offer_id=61 回退） |
| `v8-viewer-readonly-1440.png` | 1440×900 | viewer 只读：选定/清除按钮 disabled |
| `v9-matching-390.png` | 390×844 | 窄屏比选页（无固定列、标题可读） |
| `v10-detail-390.png` | 390×844 | 窄屏详情页 |

## 复现步骤（仓库外数据）

```bash
# 1) 隔离库
cp backend/erp.db "$TEMP/s2.db"            # 冷备副本，勿用主库
cd backend && ERP_DB_URL="sqlite:///$TEMP/s2.db" python scripts/migrate.py

# 2) 后端 8001
ERP_DB_URL="sqlite:///$TEMP/s2.db" python -m uvicorn app.main:app --port 8001

# 3) 前端 5174（代理到 8001）
cd frontend-v9 && VITE_API_PROXY_TARGET=http://127.0.0.1:8001 npx vite --port 5174

# 4) 真实浏览器
#    open http://localhost:5174/console/login → 表单登录 → /app/products → 搜索 S2-E2E
#    → 详情 → 进入比选与选定 → 选定 #61 → 切店铺 → 返回详情 → 刷新
```

## 已知限制（不阻塞 B3）

1. 报价过期与否在**未选定**时不单独打标：前端不自行推断失效（唯一实现在后端 `offer_state`），只在选定后由服务端返回的 `offer_state` 呈现；过期日期本身仍如实展示。
2. ≤560px 比选表仍需横向滚动才能看全列（已取消固定列，避免遮挡）。
3. 侧栏在 390px 折叠为图标条，二级入口需进入页面后使用页内导航（沿用 B1 基线）。
