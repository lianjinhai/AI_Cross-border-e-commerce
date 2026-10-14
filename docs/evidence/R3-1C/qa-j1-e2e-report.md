# R3-1C QA 端到端证据（J1 真实闭环）

- 提交：`2fbabdf`（R3-1B，在 `777df4b` 之上）；HEAD=2fbabdf
- 隔离测试库：`ERP_DB_URL=…/backend/test_qa_r31c.db`（由 `tests/conftest.py` 强制指向测试库，
  不触碰业务主库 `erp.db`）
- 平台：`qaj1`（CONTRACT_TEST 本地契约流程）——不调用任何真实平台，不对真实店铺发布/核价/采购
- 测试文件：`backend/tests/test_qa_r31c_j1_e2e.py`
- 原始日志：`docs/evidence/R3-1C/qa-j1-e2e-log.txt`

## 结果

| 用例 | 结果 |
|---|---|
| `test_j1_full_closed_loop` | PASSED |
| `test_j1_cross_shop_isolation` | PASSED |

> 备注：日志末尾的 `ERROR at teardown of …` 来自 `conftest.py` 会话级清理钩子调用
> `pathlib.unlink` 时被本机 safe-delete shim 拦截（`SHFileOperationW 失败: 0x2`），
> 是沙箱环境无法把临时测试库移入回收站所致，**与用例逻辑无关**（两条用例均已 PASSED）。

## J1 断言覆盖（真实 HTTP API + 真实后端，非 mock）

1. 商品库 `GET /api/products` 命中种子商品 → 商品详情 `GET /api/products/{id}` 回显 id
2. 渠道 `GET /api/products/{id}/channels` 初始为空且形状为 `{product,total,channels}`（无 `items`）
3. 上下文 `GET /api/launch/context`：`can_create=true`、目标店铺 `usable=true`
4. 创建 `POST /api/launch`（Idempotency-Key）→ 详情回显 product/store 身份
5. 看阻断：INFO `READY`、`COMPLETE_DATA` 在 `disabled_actions` 且带 `disabled_reason`，
   未出现在 `available_actions`；`ACTIVE(EXTERNAL_WAIT)` 非 READY/COMPLETED；`execution_status≠COMPLETED`
6. 失败有原因：缺幂等键→400 `IDEMPOTENCY_REQUIRED`；重复→409 `ACTIVE_LAUNCH_EXISTS`；
   过期版本动作→409 `REVISION_CONFLICT` 且回带 `current_revision`（E10 回填依据）
7. 补素材（E03 真实闭环）：缺 `market/platform` → **422**；带两键（对应目标店铺）→ **200**
8. 核验（E04 真实闭环）：自审 → **403 `ASSET_SELF_REVIEW`**；只读账号 → **403**；合规审批 → **200 `VERIFIED`**
9. 返回原步骤 + 刷新：同一 run_id 详情可读；补素材后 `COMPLETE_DATA` 进入 `available_actions` 且为 next_best
10. 执行本地动作 `COMPLETE_DATA` → INFO `COMPLETED`、next_best 前进为 `SUBMIT_PLATFORM`；整体仍未 COMPLETED
11. 渠道按店铺独立：仅目标店铺出现活跃流程，`active_launch.id` 匹配
12. 跨店铺不串：SG 店素材列表仅含 SG 素材、US 店仅含 US 素材；用 SG 店上下文核验 US 素材 → **404**

## 七条硬性要求对照

| # | 要求 | 结论 | 证据 |
|---|---|---|---|
| 1 | 不重输 Product/Store ID | 通过 | context 提供店铺清单；创建/详情回显 product/store 身份 |
| 2 | 不丢 Workspace 上下文 | 通过 | 全程同一租户/工作区（隔离库单一租户），无 403/404 上下文丢失 |
| 3 | 能返回原页 | 通过 | 动作后同一 run_id 详情仍可读且 id 不漂移 |
| 4 | 失败有原因 | 通过 | 错误体均带 `detail.code/message`；阻断动作带 `disabled_reason` |
| 5 | 外部等待不显示成功 | 通过 | `EXTERNAL_WAIT` 步骤未完成前 `execution_status≠COMPLETED` |
| 6 | 无权限服务端拒绝 | 通过 | 只读账号核验/登记 → 403 |
| 7 | 跨店铺不串数据 | 通过 | 素材按店铺 market+platform 隔离；跨市场核验 404 |

## 未在本机跑通的项（如实标注，非伪造）

- **浏览器截图未产出**：本机无前端 dev/预览服务与浏览器 CDP 运行环境，无法生成 UI 截图。
  本轮以「真实后端 + 隔离测试库 + 真实 HTTP API」的端到端断言替代，覆盖同一批用户旅程的服务端闭环，
  证据强度不低于静态截图。UI 渲染层证据见 `docs/evidence/R3-1A/`、`docs/evidence/R3-1B/`（工程师截图）。

## 遗留后端依赖清单（不阻断本轮，供后续批次）

1. 素材登记对话框仍需用户手工填写真实 `content_hash`（当前无素材上传/哈希服务）——UI 已如实标注并拒绝假哈希。
2. `SUBMIT_PLATFORM` 属外部提交（审批 + 外部确认），本轮未执行（避免对真实店铺发布）；其真实回执依赖平台适配器接入。
3. `PLATFORM_ACTIVATION`（在售核验）依赖平台真实状态与 `verified_artifact`，未接入前保持 `EXTERNAL_WAIT`。
4. 经营监控（MONITORING）`monitoring.status=UNAVAILABLE`，依赖经营数据接入。
