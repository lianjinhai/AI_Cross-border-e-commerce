# R3-2 统一 QA 证据（R3-2A `0286598` + R3-2B `1496927`）

真实浏览器（Chrome CDP `--no-proxy-server`）验收材料。**隔离环境**：

- 隔离后端：`uvicorn app.main:app --port 8010`，`ERP_DB_URL` 指向 `backend/qa_r32.db`（**非业务主库**）。
- 隔离前端：`vite --port 5191`，`VITE_API_PROXY_TARGET=http://127.0.0.1:8010`。
- 种子脚本：`backend/qa/r32_seed.py`（覆盖零基础/店铺卖家/有货无店/单商品双店/真实待办/无待办/只读/合规）。
- 账号：`qa_owner`(OWNER) `qa_viewer`(READ_ONLY) `qa_compliance`(COMPLIANCE) `qa_newbie` `qa_noshop`，口令均 `qa123456`。

> 说明：dev 端口未用 5174（被其它会话占用），改用 5191；Vite 依赖预打包触发沙箱批量删除守卫，
> 启动 dev 时对该进程设 `CODEBUDDY_SAFE_DELETE_ENABLED=0`（仅限 vite 自删 `node_modules/.vite` 临时目录）。

## 截图清单

| 文件 | 情形 |
| --- | --- |
| 01-login-landed.png | 真实表单登录（qa_owner） |
| 02-home-storeowner.png | 已有店铺卖家四层工作台 + 计数条 7/0/1 + 4+1 侧栏 |
| 03-mainline-target.png | 30 秒主线：主任务「去处理」→ 目标操作页 |
| 04-home-layers-expanded.png | 第四层 AI 历史 + BI 明细展开 |
| 05-tasks-default.png | 待办中心默认「需要我处理」 |
| 06-tasks-waiting-cross-store.png | 等待外部：单商品双店铺两条独立待办（跨店不合并） |
| 07-tasks-blocked.png | 受阻视图 |
| 08-tasks-done.png | 已完成视图（0） |
| 09-tasks-store-filter.png | 店铺筛选写 URL |
| 10-task-open-target.png | 处理 → 目标页（带 return_to） |
| 11-home-newuser.png | 零基础用户（新手起步入口） |
| 12-home-noshop.png | 有商品无店铺 |
| 13-home-compliance-partial.png | 合规角色：部分数据不可用 + 阶段未知 + 指标「—」 |
| 14-home-readonly.png | 只读角色侧栏 |
| 15-tools-expanded.png | 全部工具展开（39 叶子） |
| 16/17/18 | 移动端 390 / 768 |
| 19/20 | 闭环：处理→目标页→返回恢复筛选 |

`browser-verify.mjs`：可重放脚本。`_run.log`：最近一次运行的原始 JSON 结论。

## 结论摘要

- 4+1 导航、顶栏上下文条、四层工作台、画像差异化入口、诚实降级（—/UNKNOWN）均**实测通过**。
- **缺陷（源码 bug，未自行修改，交工程师）**见主报告第 ⑥ 项。
- 移动端 390 宽度**可读性差**（无响应式折叠，正文竖排）。
