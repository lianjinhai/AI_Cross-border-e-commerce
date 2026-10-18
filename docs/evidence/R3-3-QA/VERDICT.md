# R3-3 独立验证结论

- **判定：PASS**（真实浏览器 22/22 项通过，2026-10-18）
- 验证方式：真实后端 + 真实前端 dev + 真实 Chrome（CDP 直连）跑三条旅程，**不使用组件挂载或 mock**
- 隔离基座：后端 `:8011`（`backend/qa_r33.db`，每轮由基线快照还原）+ 前端 `:5193`（`--host 127.0.0.1`）；**不触碰业务主库 `backend/erp.db`**，不触碰 workbench WIP
- 可复现入口：`bash docs/evidence/R3-3-QA/_r33_run.sh`
- 机器可读结果：`docs/evidence/R3-3-QA/r33-browser-result.json`

## 1. 为什么必须做这一步

R3-3 三条链路此前只有单测（552 用例）与 `vite build` 通过，**没有真实浏览器证据**——而单测覆盖不到「事件对象被当成参数传进深链」「DTO 嵌套字段与模板读的平铺字段不一致」这类问题。
本轮实测**发现 4 个单测抓不到的真实缺陷**，均已修复并给出红→绿回归证明。

## 2. 本轮发现并修复的缺陷

| # | 缺陷（用户可见后果） | 根因 | 修复 | 回归证明 |
|---|---|---|---|---|
| D1 | 从商品详情点「创建上线流程」后，URL 变成 `shop_id=[object PointerEvent]`；向导店铺为空、**创建按钮永久禁用**，J1 链路直接断死 | `ProductDetail.vue` 模板写 `@click="goCreateLaunch"`（漏括号），PointerEvent 被当 `shopId`；`buildLaunchDeepLink` 又无脑 `String(shopId)` | 模板改 `goCreateLaunch()`；`buildLaunchDeepLink`/`launchWizardStartStep` 增加 `toPositiveInt` 守卫，非正整数（事件对象/`abc`/`3.5`/`0`）一律丢弃 | 还原旧实现 → `product-detail-view.test.js` **2 项 FAIL**；恢复修复 → 28/28 通过 |
| D2 | 上线中心列表**「商品」「店铺」整列为空**，用户无法辨认每行是什么商品/店铺（J1 落地页失去可读性） | 后端 `launch_list_item` 返回嵌套 `product{title}` / `store{name}`，模板读平铺 `product_title` / `shop_name` | 两列改读嵌套字段并保留平铺兜底 | 浏览器 A4：列表三行均渲染出「瑜伽垫 · 加厚防滑 / 美国站一号店」 |
| D3 | 上线向导与筛选下拉的店铺名显示为 `#3` / `#4`，确认页店铺为「—」，用户不知道选的是哪个店 | `GET /launch/context` 的店铺 DTO 字段是 `name`（`launch_dto._shop_context`），代码读 `shop_name` | 新增 `shopLabel()`（`name` → `shop_name` → `#id` 兜底），筛选下拉/向导下拉/确认页统一 | 浏览器 A7/A8：下拉出现「美国站一号店/美国站二号店」，确认页显示「美国站二号店」 |
| D4 | 「已有同商品同店铺流程」去重分支直达既有流程时**丢掉 return_to**，用户再点「返回」只能靠浏览器后退（商品上下文丢失） | 该分支 `router.push('/app/launch/{id}')` 未带来源 | 与成功分支一致：`detailPath(id, sourceReturn ‖ 列表筛选)` | 浏览器 A9/A11（成功分支）覆盖 return_to 端到端；去重分支同源修复 |
| D5 | 明细缺失时按店铺筛选，只显示「没有匹配结果」，会被读成「本店真的没有待办」 | 摘要行 `store='—'`，筛选必然 0 行，页面把它当普通空结果 | 新增 `filterGapNote()`：说明「后端仅提供来源分组摘要，无法按店铺筛选（不代表该店铺没有待办）」 | 浏览器 C5 + `task-center-view.test.js` 4 项新用例 |

另修：`LaunchCenter.vue` 补「返回待办」（`return_to=/app/tasks…` 时）——待办摘要行的来源页正是上线中心，此前该页没有显式回跳出口，J2「待办→来源页→返回」缺最后一环。

## 3. 22 项检查（全部 PASS）

**A. J1 商品详情 → 上线 → 返回商品详情**

| 检查 | 证据 |
|---|---|
| A0 真实表单登录离开登录页 | 落到 `/app` |
| A1 商品详情渲染、可写角色见「创建上线流程」、无 `[object Object]` | `#26 瑜伽垫 · 加厚防滑` |
| A2 深链带 `product_id=26`、`from=/app/products/26`，**不写 `[object …]` 的 shop_id** | `shopId=null` |
| A3 上线中心识别来源并提供「返回来源」 | 按钮存在 |
| A4 列表商品/店铺列真实有值 | `["4","瑜伽垫 · 加厚防滑","美国站一号店",…]` |
| A5 深链进入向导跳过「选商品」 | steps: 选商品 inactive / 选店铺 **active** |
| A6 直接给店铺选择 | `hasShopSelect=true, hasProductSelect=false` |
| A7 店铺下拉用真实店名 | 选项 `["美国站一号店","美国站二号店"]` |
| A8 确认步如实回显商品与店铺 | `商品 #26 瑜伽垫…` / `店铺 美国站二号店` |
| A9 创建后进入详情且 `return_to=/app/products/26` | `/app/launch/5?return_to=/app/products/26` |
| A10 详情页出现「返回」（白名单接受） | 按钮存在 |
| A11 返回后**真的回到商品详情** | 回到 `/app/products/26`，标题「瑜伽垫 · 加厚防滑」 |

**B. J0 新手 5 步旅程（qa_newbie，无店铺）**

| 检查 | 证据 |
|---|---|
| B1 首步渲染旅程条（第 1/5 步） | 「研究商品方向」 |
| B2 首步有「下一步」出口 | 「下一步：选择货源 →」 |
| B3 五步逐步推进无中断 | 1 研究商品方向 → 2 选择货源 → 3 查看成本/风险 → 4 准备销售渠道 → 5 建立商品销售准备 |
| B4 `journey=j0` 上下文保持 | 5/5 步 URL 均带 `journey=j0` |
| B5 末步有出口并回工作台 | 点「完成准备」→ `/app?journey=j0` |

**C. J2 待办 → 处理 → 返回（用有真实行级明细的「被阻断」视图）**

| 检查 | 证据 |
|---|---|
| C1 真实明细行、店铺/商品不为「—」、无 `[object Object]` | `瑜伽垫 · 加厚防滑 / 美国站一号店 / 执行受阻` |
| C2 处理入口带 `return_to=/app/tasks?view=blocked` | `/app/launch/4?return_to=%2Fapp%2Ftasks%3Fview%3Dblocked` |
| C3 落点页有「返回待办」 | 按钮存在 |
| C4 返回后筛选态完整恢复 | 仍为「被阻断（1）」视图 |
| C5 明细缺失→按店铺筛选给出真实原因 | 展示「无法按店铺筛选（这不代表该店铺没有待办）」 |

## 4. 未修复但必须记录的缺口（不掩盖）

| 缺口 | 现象 | 归属 |
|---|---|---|
| 进行中（READY）流程在待办中心**无视图可见** | `fromInProgress` 把 READY 判为 `view='active'`，而 `TASK_VIEWS` 只有 todo/waiting/blocked/done → 这些行在任何标签页都不出现；但顶栏「待我处理」会计入。属 R3-2 冻结口径遗留 | 前端 + 后端待办契约（建议 R3-4 明确「待我处理」是否包含 active） |
| 「下一动作」直接渲染枚举 `CANCEL` | 上线列表/详情未做动作中文映射，GUIDED 模式下不是业务语言 | 前端（需先有权威动作词典，避免自行臆造译名） |
| 后端 G1–G5（已记录于 `BACKEND_DEPENDENCY_GAPS.md`） | 待办无 item 级 id/owner/due、`mine=true` 漏等待外部、部分来源失败沟通、计数与列表口径 | 后端 workbench WIP 所有者 |
| `LaunchDetail.vue` 双白名单冗余 | `/app` 入白名单后，J2 的 `safeReturnToTasks` 分支成为冗余；当前保留不影响正确性 | 前端清理项（牵动共享导航事实源，未在本轮改动） |

## 5. 证据清单

- 截图：`31`–`36`（J1）、`37`+`38-step1..5`（J0）、`39`–`42`（J2）
- 机读结果：`r33-browser-result.json`（22 项逐条 pass/detail）
- 运行日志：`_r33_backend.log` / `_r33_frontend.log` / `_r33_browser.log`
- 排障探针（证明缺陷归因，不是脚本臆测）：`probe-result.json`、`probe2-result.json`、`probe3-result.json`、`probe4-result.json`
- 驱动：`browser-verify-r33.mjs`（22 检查）、`_r33_run.sh`（基线还原 + 端口预检 + 就绪轮询）

## 6. 本轮代码与验证基线

- 改动文件：`ProductDetail.vue`、`LaunchCenter.vue`、`TaskCenter.vue`、`shared/productDetailView.js`、`shared/taskCenterView.js` + 2 个测试文件
- 单测：**46 文件 / 559 用例全绿**（R3-3 交付时为 552）
- 构建：`vite build` 通过（9.66s）
- 文档门禁：`check_docs_consistency.py` → `total=0`
