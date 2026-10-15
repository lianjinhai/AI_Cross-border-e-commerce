# R3-2 统一 QA · 第 2 轮（Round 2）正式结论

- 结论文件：`docs/evidence/R3-2-QA/ROUND2_CONCLUSION.md`
- 日期：2026-10-14
- 范围：R3-2A（`0286598`）+ R3-2B（`1496927`）+ R3-2B 修复（`3380e1e`）
- 口径：第 1 轮已 PASS with notes 并抓到 5 项源码缺陷；第 2 轮只做**定向补充验证**（不重复全量回归），补齐第 1 轮缺证项。
- 隔离基座：隔离库 `backend/qa_r32.db` + 隔离后端 `127.0.0.1:8010` + V9 dev `127.0.0.1:5191`（**未触碰主库与 workbench WIP**）。

## 一、正式判定

> # 判定：**PASS**

依据：
1. 第 1 轮抓到的 5 项缺陷（bug1–bug5）全部修复，且以**可复现 diff**（`_oldproof`）证明「修复前 FAIL / 修复后 PASS」；
2. 10 项核心核验点全部取得**真实后端 + 真实浏览器**证据（见 §二）；
3. 未发现任何**影响核心操作**的缺陷（用户可登录 → 见主任务 → 一键直达目标页 → 完成处理 → 返回不丢上下文）；
4. 后端 workbench 能力缺口（§四）**不阻塞**前端核心操作——前端对缺失明细**准确降级、不伪造**，符合 R3-2B 验收强化要求。

---

## 二、10 项核验（真实证据）

| # | 核验点 | 结果 | 证据 |
|---|---|---|---|
| 1 | 商品/店铺对象不渲染为 `[object Object]` | ✅ | API：`inProgress[].product`/`.store` 为字符串（瑜伽垫·加厚防滑 / 美国站一号店）；UI：`被阻断`视图行内产品/店铺为真实文案；`hasObjectObject:false` |
| 2 | 筛选在**真实对象形状**下可用 | ✅ | 回归证明 `_oldproof`：旧筛选命中 0（FAIL）→ 新命中 `['launch:41']`（PASS）；浏览器层「全部待办」为后端**来源摘要**（无 store 字段）→ 页面显式 `gap-note` 降级，不伪造行 |
| 3 | 首页阻断/主任务提取正确 | ✅ | `storeowner_home.primaryTask="待人工复核的 Listing"`；计数条 `被阻断=1`；四层结构 `hasLayer1..4=true` |
| 4 | `return_to` 无重复嵌套 | ✅ | 主线：`/app/launch?return_to=/app/tasks`，`returnToCount=1, nested=false`；过滤态闭环：`/app/launch/4?return_to=%2Fapp%2Ftasks%3Fview%3Dblocked`，`return_to` 单一且**携带完整筛选上下文**；返回后 `?view=blocked` 保留、行数=1（`queryPreserved=true`） |
| 5 | 任务 ID 稳定（非数组下标） | ✅ | 回归证明：旧 `todo:launch:0`（含下标，FAIL）→ 新 `todo:launch:待你处理的上线流程`（PASS） |
| 6 | 首页/TaskCenter/顶栏计数一致 | ✅ | 三方同源 `deriveWorkbenchCounts`：顶栏(首页)=`2/0/1`、首页计数条=`2/0/1`、顶栏(任务中心)=`2/0/1`、TaskCenter 计数条=`2/0/1`；「全部待办（7）」= `todo.counts` 求和（launch3+action1+alert2+review1） |
| 7 | 390/768 无阻塞性溢出 | ✅ | 390：`bodyScrollW=390 == viewport=390`；768：`viewport=768`；移动端任务表可渲染 |
| 8 | 单商品双店任务保持独立 | ✅ | `inProgress` 中「弹力带·家用健身」同时出现在**美国站一号店**与**美国站二号店**两行，未合并 |
| 9 | Workspace/身份切换不串数据 | ✅ | 4 个身份入口互不相同：`qa_owner`=店铺经营(2/0/1)、`qa_compliance`=通用工作台(1/0/0，菜单收窄)、`qa_viewer`(READ_ONLY)=店铺经营(待我处理=`—`)、`qa_newbie`/`qa_noshop`=起步阶段(0/0/0) |
| 10 | 无权限者被正确限制 | ✅ | 前端：COMPLIANCE 侧栏收敛为 7 项、`partialBanner=true`；READ_ONLY 无权限计数渲染 `—`（`null` 而非伪 0）；后端：无权限源 `sources[kind]='skipped'`、overview 各源 `skipped` |

### 30 秒主线（时延）
- `mainline_30s`：点击主任务 → 目标页 `elapsedMs = 1482ms`（远低于 30s 阈值），落地 `/app/compliance/approvals?return_to=/app/tasks`。

---

## 三、第 1 轮缺陷回归证明（可复现 diff）

`frontend-v9/tests/_oldproof.test.js` 用 `frontend-v9/_oldproof/*`（旧版 `1496927`）与新实现（`3380e1e`）对拍：

| 缺陷 | 旧（1496927） | 新（3380e1e） |
|---|---|---|
| bug1 对象渲染 | `"[object Object] 的上线流程"` → **FAIL** | `"弹力带 的上线流程"` → **PASS** |
| bug2 按店铺筛选 | `rows=0` → **FAIL** | `rows=['launch:41']` → **PASS** |
| bug4 return_to 重复 | `...return_to=/app/tasks&return_to=...` `count=2` → **FAIL** | `count=1` → **PASS** |
| bug5 稳定 id | `todo:launch:0`（含下标）→ **FAIL** | `todo:launch:待你处理的上线流程` → **PASS** |
| bug3 首页阻断摘要 | `workspaceHomeView.js` 对象直插 → 修复后 `displayName()` 归一化 | 修复（并入 3380e1e） |

---

## 四、剩余后端依赖（**不阻塞**，属 workbench 域 WIP）

详见 `docs/evidence/R3-2-QA/BACKEND_DEPENDENCY_GAPS.md`。摘要：

- **G1** 待办项缺 item 级稳定 `id` 与 `ref`（后端恒 null）→ 前端以「type+业务键」自造；
- **G2** `mine=True` 硬编码 → 遗漏「非本人负责」的 waiting-external；
- **G3** 待办项无 item 级明细（owner / due / 步骤 / 商品·店铺）→ 列表只能显示来源摘要；
- **G4** 部分源失败沟通不足（失败源 item 缺席 + overview 折叠子源 + `partial` 语义过载）；
- **G5** 计数与列表查询口径（`todo.total` vs `in_progress` 数组长度）根因在后端。

> 处置原则：以上属其他工程师 WIP，本轮**只登记不修改**；前端在能力就绪前**准确降级、绝不伪造**任务负责人/截止/步骤/明细。

---

## 五、发现的问题与处置

| 项 | 类型 | 处置 |
|---|---|---|
| 第 1 轮 bug1–bug5 | 前端源码缺陷 | ✅ 已修（`3380e1e`），附回归证明 |
| 测试 SAMPLE 与后端 DTO 形状失真（根因） | 测试夹具缺陷 | ✅ 已修：夹具对齐真实对象形状（避免再次漏检） |
| Round2 驱动 502 / `NOT_READY` | **验证脚本缺陷（非产品缺陷）** | ✅ 已修：① 代理劫持 `127.0.0.1` → 统一 `NO_PROXY`/`--no-proxy-server`；② Vite `--host localhost` 仅绑 IPv6 `[::1]`，就绪探针探 `127.0.0.1` 被拒 → 改为 `--host 127.0.0.1` |
| 驱动标签 `受阻` 未命中（实为`被阻断`）、在空视图点「处理」 | 验证脚本缺陷 | ✅ 已修：改用正确标签；闭环改在**有真实行**的视图执行 |

---

## 六、可复现验证入口

```bash
# 前置：清代理，避免 502
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
export NO_PROXY="127.0.0.1,localhost" no_proxy="127.0.0.1,localhost"

# 1) 单元/组件测试（510 用例 / 45 文件）
cd frontend-v9 && npx vitest run

# 2) 缺陷回归证明（4 用例：旧 FAIL / 新 PASS）
cd frontend-v9 && npx vitest run tests/_oldproof.test.js

# 3) 真实浏览器全量（12 类情形 + 截图）
bash docs/evidence/R3-2-QA/_round2_run.sh      # → _round2_browser.log + 01..18*.png

# 4) 定向补充（三方计数 + 被阻断视图 + 闭环 return_to）
bash docs/evidence/R3-2-QA/_round2_supp.sh     # → _supp_browser.log + 21..25*.png

# 5) 筛选上下文闭环（返回不丢 view）
bash docs/evidence/R3-2-QA/_round2_loop.sh     # → _loop_browser.log + 26..27*.png
```

## 七、证据清单

- `_round2_test.log`：**510 passed / 45 files / exit=0**
- `_oldproof_run.log`：**4 passed**（旧 FAIL / 新 PASS 对拍）
- `_round2_browser.log`：真实浏览器 12 类情形 JSON 结论（本轮补齐）
- `_supp_browser.log`：三方计数一致 + `被阻断`视图 1 行真实明细 + `return_to` 唯一
- `_loop_browser.log`：`returnToCount=1, nested=false, queryPreserved=true, rowsAfterBack=1`
- 截图：`01..18`（全量）+ `21..27`（补充/闭环）
- `BACKEND_DEPENDENCY_GAPS.md`：后端依赖缺口 G1–G5
