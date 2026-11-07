# V9-1-M2-D · 素材上传与哈希可信来源

> 执行日期：2026-11-07　基线：`main` @ `1306096`（本批改动提交前）
> 结论：**PASS（含明确边界）**——哈希改由服务端按字节算出，未接入存储时**显式拒绝且零写入**；
> 但本地目录只保证单机持久，多副本 / 对象存储 / CDN / 防盗链仍属 B03–B09，**未接入**。

## 1. 这批要解决什么

素材登记 `POST /api/products/{id}/assets` 收的是**客户端声明**的 `content_hash`，而
`asset_schema.AssetRegistration` 只能校验它是 `^[a-f0-9]{64}$`——编一个「看起来像 sha256」的串就能过。
于是「图片权利证据」成了一张没人能复核的空头承诺，正是 R3-1B「不得生成假哈希」要挡的东西。

同一片区域还有两处错位，一起收口：

1. **指路指错**：素材权利不通过时 `launch_handlers.missing_blockers` 一律返回
   `MISSING_DATA` → `ACTION COMPLETE_DATA`「补充商品资料」。用户点进去只能改标题分类，
   补不出图片授权证据——跑一趟白跑。
2. **前端死路**：`ProductDetail.loadAssets` 写着 `assetReadyFlag.value = true`，而这个变量
   **从未声明**。`<script setup>` 是 ES module（严格模式），赋值未声明标识符抛 `ReferenceError`，
   被同一段 `try/catch` 吞成 `assetError='素材加载失败'`——**素材表在任何环境都渲染不出来**。

## 2. 做了什么

### 2.1 `app/services/asset_upload.py`（新）

| 能力 | 语义 |
|---|---|
| `storage_dir()` | 读 `settings.asset_upload_dir`；空 = **上传服务未接入** |
| `capability()` | `{connected, reason, max_bytes, content_types}`，供接口与前端如实展示 |
| `save(data, content_type, filename)` | 落 `<root>/<sha[:2]>/<sha><ext>`，先写 `.part` 再 `replace`；返回 `{uri, content_hash, size, content_type, stored}` |
| `verify_reference(uri)` | 按 `asset://<sha256>/<name>` 回读文件**重算** sha256 比对 |

门禁：`MAX_BYTES = 8 MiB`；`ALLOWED_CONTENT_TYPES = {image/jpeg, image/png, image/webp}`。
未接入存储时 `save()` 直接抛 `UploadUnavailable`（`ASSET_UPLOAD_UNAVAILABLE`），**不落盘、不写库**。

### 2.2 两个新端点（`app/routers/product_assets.py`）

- `GET /api/products/{id}/assets/upload-capability?shop_id=` —— 先过 `upload_context`（范围/权限），
  再返回能力快照；
- `POST /api/products/{id}/assets/upload`（multipart `shop_id` + `file`）—— 256 KiB 分块读，
  超限 413 `ASSET_TOO_LARGE`；未接入 409；类型不合规 400。

### 2.3 登记时引用必须可复核（`app/services/product_assets.py`）

`_require_trustworthy_reference(request)`：`asset://` 引用回存储重算比对，
不一致 409 `ASSET_HASH_MISMATCH`，文件不在 409 `ASSET_FILE_MISSING`。
外部 `https` 引用**仍只登记不下载**（不引入隐式抓取），但也不因登记而变成已核验。

### 2.4 阻断码 `ASSET_RIGHTS_MISSING`（`launch_repair.py` / `launch_handlers.py`）

- `_BY_CODE` 新增该码：`kind=ROUTE`、`path=/app/products`（有 `product_id` 时收敛到详情页）、
  **不再给 `COMPLETE_DATA`**（那个动作在完成条件不满足时只会再 409，等于死路）；
- `repair_action()` 末尾按 `asset_upload.capability()` 翻 `connected`：未接入 → `connected=false`
  并写明「商品页可查看素材区，但不能登记新素材，也不会用客户端声明的哈希凑合」；
- `missing_blockers()` 新增 `_missing_code()`：`assets.reasons` 非空**且**步骤是
  `DATA_PREPARATION` 才走 `ASSET_RIGHTS_MISSING`；材料类（COMPLIANCE/LABEL/EVIDENCE）保持原样落合规页。

### 2.5 前端（`frontend-v9`）

- `api/domains/products.js`：`fetchAssetUploadCapability()` / `uploadAsset()`（multipart，前端不碰哈希）；
- `shared/productDetailView.js`：新增纯函数 `assetUploadGate()`（**fail-closed**：能力为 null 也禁用）
  与 `assetHashOrigin()`（`asset://` → `server` 只读回填）；组件逻辑抽成纯函数，本仓无
  `@vue/test-utils` 也能测；
- `pages/product/ProductDetail.vue`：素材区加「上传素材」按钮（`el-upload` 手动模式，不用它内置上传通道）、
  未接入时黄色说明条、哈希框只读回填；同时删掉上面那行未声明变量的赋值。

## 3. 验收逐条

| 判据 | 结果 | 证据 |
|---|---|---|
| 未接上传服务提交返回明确错误码 | ✅ | `test_upload_is_refused_and_writes_nothing_when_service_missing`：409 `ASSET_UPLOAD_UNAVAILABLE` |
| 且**无任何素材记录被创建** | ✅ | 同上 `_assert_no_rows()`；真机 `products_assets` 计数 2 → 2（`run-log.txt`） |
| 接好后正常流程可回读版本 | ✅ | `test_upload_returns_server_computed_hash_and_round_trips_version`：服务端哈希 → 登记 v1 → 列表回读 → 追加 v2（`parent_asset_id` 指向 v1）；真机截图 07 |
| 编造哈希必须被拒 | ✅ | `test_fabricated_hash_is_rejected_for_uploaded_file`：409 `ASSET_HASH_MISMATCH` + 零写入 |
| 引用不存在的文件必须被拒 | ✅ | `test_missing_uploaded_file_is_rejected`：409 `ASSET_FILE_MISSING` |
| 类型/大小是门禁 | ✅ | `test_upload_rejects_unsupported_type_and_oversize`：400 `ASSET_TYPE_UNSUPPORTED` / 413 `ASSET_TOO_LARGE` |
| 能力如实上报 | ✅ | `test_upload_capability_reports_the_gap`：`connected=false` + 原因含 `ERP_ASSET_UPLOAD_DIR` |
| 只读身份不能上传 | ✅ | `test_read_only_account_cannot_upload`：403 且零行零文件记录 |
| 缺素材不再指去补充资料 | ✅ | `test_missing_asset_gate_points_at_asset_registration_not_product_copy`：`ASSET_RIGHTS_MISSING` + `ROUTE` + `/app/products/42` |
| 材料类步骤不被抢走 | ✅ | `test_label_step_gap_still_points_at_compliance_not_assets`：LABEL → `MISSING_DATA` → `/app/compliance` |
| 缺失态能看出「为什么不能用」 | ✅ | 截图 `08-asset-missing-1440.png`：黄条写「未配置 ERP_ASSET_UPLOAD_DIR…不能上传新文件；系统不会用客户端声明的哈希凑合」，上传按钮禁用 |
| 界面佐证 | ✅ | `07-asset-normal-1440.png`（登记后素材表出现 `asset://…` 行）、`07b-asset-upload-dialog-1440.png`（哈希只读回填）、`08-asset-missing-1440.png` |
| 主库未写 | ✅ | 真机隔离副本库；主库 SHA256 `d79bd669…` 前后一致（`run-log.txt`） |

**变异验证**（证明用例真的在挡东西）：把 `product_assets._require_trustworthy_reference(request)`
调用去掉，`test_asset_reference_is_untrusted_without_storage` /
`test_fabricated_hash_is_rejected_for_uploaded_file` / `test_missing_uploaded_file_is_rejected`
立刻 3 红；改回即绿。

回归：`pytest tests/test_asset_upload.py` 8 passed；`-k "launch or asset or publish"` 291 passed；
后端全量 `pytest -q` **1059 passed / 2 xfailed / 1 xpassed / 0 failed**（M2-D 前为 1051）；
前端 `61 files / 777 tests` 全绿（JSON reporter 权威计数）；`ruff check app` 零告警（`ruff check .`
剩 8 条存量测试告警，见 `REPORT.md` §5 第 7 条）；`vite build` 通过；文档门禁 `total=0`。

## 4. 顺手修掉的既有缺陷

`ProductDetail.loadAssets` 里 `assetReadyFlag.value = true` 赋值给一个从未声明的变量。
严格模式下这是 `ReferenceError`，被同一个 `try` 吞成「素材加载失败」，**素材表永远渲染不出来**。
单测抓不到（本仓不 mount 组件），真机一看便知。已删除该行——加载/错误/空三态本来就由
`assetLoading` / `assetError` / `assetRows` 派生，不需要额外标志。

## 5. 边界（必须与完成一起读）

1. **本地目录不是对象存储**。只保证单机持久与可回读；多副本、对象存储、CDN、防盗链、签名 URL
   仍属 B03–B09，未接入。换机器/换目录后旧 `asset://` 引用会 `ASSET_FILE_MISSING`。
2. **上传成功 ≠ 权利成立**。`rights_status` / `rights_evidence_ref` / 核验状态仍由登记与
   `verify` 门禁决定；上传只解决「哈希是谁算的」。
3. **外部 https 引用仍不下载**。它继续只登记、只校验哈希形状——这是刻意保留的边界（隐式抓取
   会引入 SSRF 与不可控外呼），因此外链素材的可信度仍低于本系统上传。
4. **Launch 侧不加 `UPLOAD_ASSET` 动作**。素材登记是商品级操作，复用既有 `/products/{id}/assets*`
   接口；再造一条流程内通道就是重复 Service（违反 P0-4 红线）。代价：Launch 详情页只能「跳过去补」，
   补完需手动刷新流程。
5. **按钮禁用文案在别处**。`launch_nba.action_block_reason` 对 `COMPLETE_DATA` 仍给通用句
   「完成条件尚未被服务端事实满足」——具体缺项在点击后的 409 里逐条给出。没把原因塞进 plan，
   是为了不混淆状态模型 §6 的 `blocking_reason` 语义（那是步骤级，不是动作级）。
6. **截图用本地契约样本**（`launch_e2e.py --profile simple` 的种子商品 + 销售店铺），不是 `COMPLEX_CONTRACT`：
   复杂链路的中间步骤仍未接通。与本目录 M2-A 的口径一致。
7. `ruff check .` 仍有 8 条**存量**测试告警（见 `REPORT.md` §5 第 7 条），不在本批新增。
