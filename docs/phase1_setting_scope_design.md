# P1-10 Setting 作用域隔离设计

> 日期：2026-09-23 ｜ 状态：**DESIGNED（未执行 DDL）**
> 独立 Migration，**不与 Identity 建表混合**（`docs/archive/phase1_migration_safety.md` 第 5 节 Step 10）。

## 1. 问题（已实测确认）

`settings` 表当前结构：

| 列 | 类型 | 约束 |
|---|---|---|
| key | String(64) | **PRIMARY KEY** |
| value | JSON | |
| updated_at | DateTime | |

主键只有 `key`，**没有租户维度**。实测存在 4 个 key：

| key | 内容 | 真实归属 |
|---|---|---|
| `llm` | api_key / base_url / model | **全局**（平台级密钥，正确） |
| `platform_fees` | 各平台费率 | **应为租户级** |
| `fx` | 汇率 USD/EUR | **应为租户级** |
| `rules` | 毛利/物流/广告参数 | **应为租户级** |

### 阻断性影响

`PUT /api/ai/settings`（`backend/app/routers/ai.py` 第 51 行）用 `require_admin` 保护，
即**任意租户的 admin 都能改写全局配置**，直接影响其他所有租户的定价与利润计算。
这是一个跨租户写入漏洞，不是单纯的架构问题。

## 2. 隔离设计（Revision D，独立于 A/B/C）

新建文件：`backend/migrations/versions/20260923_10_setting_scope.py`

### 2.1 表结构变更

采用 **Expand → Backfill → 双读 → Contract** 四步，但本 revision 只做 Expand + Backfill：

新增 `tenant_settings` 表：

| 列 | 类型 | 约束 |
|---|---|---|
| id | Integer | PK |
| tenant_id | Integer | index, NOT NULL |
| key | String(64) | NOT NULL |
| value | JSON | NOT NULL |
| updated_at | DateTime | NOT NULL |
| — | — | **unique(tenant_id, key)** |

`settings` 表**保持不变**（保留为平台级配置：`llm`、`open_1688`）。

### 2.2 Backfill

把现有 `platform_fees` / `fx` / `rules` 三行**复制**（不是移动）到所有真实租户：

`sql
INSERT INTO tenant_settings (tenant_id, key, value, updated_at)
SELECT t.id, s.key, s.value, CURRENT_TIMESTAMP
FROM tenants t CROSS JOIN settings s
WHERE s.key IN ('platform_fees','fx','rules') AND t.id <> 0;
`

`settings` 中的原行保留，作为**平台默认值**（租户无覆盖时回退使用）。

### 2.3 读取优先级（代码侧，Service 统一实现）

`
租户级 tenant_settings(tenant_id, key)
    ↓ 不存在
平台级 settings(key)
    ↓ 不存在
代码内 _SETTING_DEFAULTS
`

### 2.4 写入规则（代码侧）

| key | 允许写入者 | 写入目标 |
|---|---|---|
| `llm` / `open_1688` | **仅 superadmin** | `settings`（平台级） |
| `platform_fees` / `fx` / `rules` | 该租户 admin | `tenant_settings`（租户级） |

**关键修复**：`PUT /api/ai/settings` 必须按 key 分流，禁止租户 admin 写入平台级 key。

## 3. 代码改动清单（DDL 之后执行）

| 文件 | 改动 |
|---|---|
| `backend/app/services/settings_service.py` | **新建**：统一 `get_setting(db, tenant_id, key)` / `set_setting(db, tenant_id, key, value)`，实现三级回退 |
| `backend/app/routers/ai.py` | `_read_setting` 改为调用 Service；`put_settings` 按 key 分流 + 平台级 key 限 superadmin |
| `backend/app/ai/llm.py` | `get_llm_config` 保持读平台级（无需改） |
| `backend/app/services/commercial_analytics.py` 等读取 `rules`/`fx`/`platform_fees` 的位置 | 改为通过 Service 读取 |

## 4. 验收标准

| 验收项 | 方法 |
|---|---|
| 租户 A 改 `rules` 不影响租户 B | 双租户 API 测试 |
| 租户 admin 改 `llm` 被拒绝 | 403 断言 |
| superadmin 改 `llm` 成功 | 200 断言 |
| 租户无覆盖时回退平台默认值 | 单测 |
| 三处回退顺序正确 | 单测 |
| 现有 51 项回归全通过 | pytest |

## 5. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 改动定价/利润计算路径 | **P0** | 先写 Service + 单测，再切换调用方，逐个验证 |
| 遗漏读取点导致部分走全局 | P1 | 用 `rg` 全量搜索 `Setting` 与 key 字面量后逐点确认 |
| 租户数增长导致 `tenant_settings` 膨胀 | P2 | 只回填 3 个 key × 6 租户 = 18 行，规模可控 |

## 6. 未决事项

| 事项 | 需要谁决定 |
|---|---|
| `llm` 密钥是否允许租户自备（BYOK） | 用户/业务方 |
| 是否允许租户覆盖平台费率默认值 | 用户/业务方 |
| Revision D 与 A/B/C 的执行先后 | 用户（建议 A/B/C 之后） |
