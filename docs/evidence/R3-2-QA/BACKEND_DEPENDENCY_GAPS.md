# R3-2 后端依赖缺口登记（workbench 域 · WIP · 只读登记，不修改）

- 登记人：team-lead（R3-2 收口）
- 日期：2026-10-14
- 依据：只读审阅 `backend/app/routers/workbench.py`、`backend/app/services/workbench.py`
- 纪律：以上两文件为**未提交 WIP**（UX-04 域），由该域负责人处置。R3-2 收口**不修改**其内容。
- 消费方：`frontend-v9/src/shared/taskCenterView.js`、`frontend-v9/src/shared/workspaceHomeView.js`。
  原则：缺口存在时前端必须**准确降级**（可展示聚合计数、明确标注「明细未接入」），**禁止伪造**。

---

## G1　待办项缺少 item 级稳定 ID 与 ref

- **现状**：`services/workbench.py` 的 `_todo_item(...)` 产出字段仅
  `{type, title, count, severity, due_at, route{path, return_to}, ref}`；
  四个 `_todo_*` 生产者**均未传 `ref`**（恒为 null），item 亦无后端权威 `id`。
- **影响**：跨域待办每一项没有后端稳定标识，跨端/跨服务无法对账；
  前端只能用「type + 业务键」自造 id（`taskCenterView.js` bug5 的修复即此兜底）。
- **需要后端补**：每类待办提供稳定 `id`（launch→launch id、review→队列项 id、alert→alert id）
  与 `ref{product_id, store_id, ...}`。

## G2　`mine=True` 遗漏「非本人负责」的 waiting-external

- **现状**：`_todo_launch` 与 `_in_progress_section` 均硬编码
  `list_launches(..., mine=True, ...)`。
- **影响**：他人负责、但本租户应当知晓的 waiting-external 任务，在**待办计数**与
  **进行中列表**中被同时剔除；OWNER 视角会漏项。
- **需要后端补**：可配置口径（mine / tenant 全量）＋真实 `owner` 字段，
  供前端渲染「我的 / 全部」。

## G3　待办项无 item 级明细（owner / due / 步骤 / 商品·店铺）

- **现状**：item 只有聚合 `title` + `count`；无 `owner`；`due_at` 形参存在但**无调用方传值**；
  无 product / store / step 明细。
- **影响**：统一待办列表只能显示聚合条目（如「待你处理的上线流程 ×N」），
  无法在列表内呈现每个任务的商品/店铺/步骤/负责人/截止，用户须跳转目标页才能看到细节。
- **需要后端补**：item 级明细（至少 `owner`、`due_at`、product/store 引用、`step_code`）。

## G4　部分源失败的前端可沟通性不足

- **现状**：`_collect` / `_produce` 失败时置 `sources[kind]='failed'` 且 `partial=true`，
  但失败源对应的 item **直接缺席**；`build_overview` 再把 todo 的全部子源折叠为单一
  `sources['todo']`（任一子源 failed → 'failed'），**丢失「哪个子源失败」**。
- **影响**：前端无法区分「该域 0 条」与「该域查询失败」；overview 层只能得到笼统 `partial`。
- **需要后端补**：overview 透出 todo 子源明细（或直接透传 `todo.sources`），
  前端据此对每个域显示「未接入 / 加载失败 / 0 条」三态。
- **附带语义问题**：`partial` 判定把「信号因无权限而为 None」与「源失败」混为一谈
  （`partial = any(failed) or any(signal is None)`），语义过载，建议拆分。

## G5　计数与列表查询口径一致性

- **现状**：`_todo_launch` 回 `count = total`（不受分页限制）；而 `_in_progress_section`
  以 `page_size=limit` 仅回数组、**不回 total**。
  两者 `mine=True` 作用域一致，但「计数」与「列表长度」在首页各层来自**不同调用**
  （`todo.total` vs `in_progress` 数组长度）。
- **影响**：当数据量超过 `limit` 时，首页「进行中」层（数组长度）、顶栏计数、待办计数可能不一致。
- **需要后端补**：统一口径——所有「计数」来自同一 `total` 查询、与列表同一 where 子句；
  或 overview 直接透出 total。
- **现状说明**：前端已用 `deriveWorkbenchCounts` 做**单一事实源**收敛分叉，
  但**根因在后端**，前端只能兜底。

---

## 收口结论

以上 5 项为**后端依赖缺口**，非前端缺陷，不阻塞 R3-2 前端判定，
但决定前端「真实任务事实」能达到的**明细深度**。在能力就绪前，前端策略：
展示聚合计数 + 显式「明细未接入 / 未接入」标注，**绝不伪造**任务负责人/截止/步骤/商品明细。
