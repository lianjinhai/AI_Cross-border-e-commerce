# ADR 目录（架构决策记录 · 镜像与索引层）

> **本目录不产生第二份真相。**
> 决策的**唯一权威源**是 [`docs/DECISIONS.md`](../DECISIONS.md)。本目录是它的
> **面向外部的可独立引用层**，服务于三类场景：对外交付、审计取证、新成员快速理解。

---

## 1. 与 `DECISIONS.md` 的分工

| 维度 | `docs/DECISIONS.md`（权威源） | `docs/adr/`（本目录） |
|---|---|---|
| 地位 | **唯一权威源（single source of truth）** | 镜像 / 索引层，**从属**于权威源 |
| 内容形态 | 全量、按 D 编号追加、含完整实测证据与过程 | 高价值决策的**自包含摘要** |
| 谁在维护 | 每次决策发生时由执行者追加 | 只在「架构边界或安全模型变更」时新增 |
| 冲突时以谁为准 | **以 `DECISIONS.md` 为准** | 若本目录与权威源不一致，**判本目录为错** |
| 引用方式 | 按 D 编号引用（`D7`、`D22`） | 按 `ADR-NNNN` 引用，并在文末回指 D 编号 |

**为什么不把 `DECISIONS.md` 拆散**：它已被 `AGENTS.md` §11 与多份文档交叉引用为
「架构决策记录（ADR）」，直接拆分会打断既有引用链（`rg "DECISIONS.md"` 命中多处）。
因此本目录**只增不改**，不搬迁权威源。

---

## 2. 决策索引表（全量）

覆盖 `DECISIONS.md` 中**全部** D 编号。行号锚点指向该决策标题所在行，**已逐条核对**
（核对时间 2026-09-25）。

| 编号 | 标题 | 状态 | 关键词 | 锚点 |
|---|---|---|---|---|
| D1 | 开源同类项目调研：为什么自研而不是二开 | Accepted | 自研、二开、GPL 许可证风险 | [`L3`](../DECISIONS.md#L3) |
| D2 | 技术栈 | Accepted | FastAPI、SQLAlchemy 2.0、Vue3、pbkdf2、单体模块化 | [`L20`](../DECISIONS.md#L20) |
| D3 | LLM 双模架构（本系统最重要的决策） | Accepted | `ask_json`、规则引擎无缝降级、零配置可跑 | [`L27`](../DECISIONS.md#L27) |
| D4 | 合规门禁语义 | Accepted | 品牌词命中扣 50 分、高风险直接拒绝发布 | [`L35`](../DECISIONS.md#L35) |
| D5 | 工作流数据流 | Accepted | 模板步骤、`context_patch`、JSON 列不可变检测 | [`L39`](../DECISIONS.md#L39) |
| **D16(a)** | 跨境平台角色与接入顺序 | Accepted | 1688 固定货源端、TikTok→Shopee→Amazon | [`L42`](../DECISIONS.md#L42) |
| **D17(a)** | 销售渠道扩展分层 | Accepted | `protocol_ready_unverified`、`sandbox` 默认 | [`L49`](../DECISIONS.md#L49) |
| D6 | 代码与目录规范：存量渐进、增量强制 | Accepted | ruff + CI 门禁、不搞一次性全量整改 | [`L58`](../DECISIONS.md#L58) |
| D7 | 店铺删除语义：归档式软删除 | Accepted | `shops.archived_at`、凭证即时失效、`active_shop()` | [`L79`](../DECISIONS.md#L79) |
| D8 | 生产部署基线：显式门禁、容器跑迁移、健康检查 | Accepted（TLS 部分由 D22 补全） | compose 密钥必填、entrypoint 跑迁移、`HEALTHCHECK` | [`L107`](../DECISIONS.md#L107) |
| D9 | 迁移例外：修改已执行的 Revision C | Accepted（**一次性例外**） | 违反「迁移只增不改」的破例与约束 | [`L126`](../DECISIONS.md#L126) |
| D10 | 生产口令必须真正生效 + 测试夹具下沉 conftest | Accepted | `ERP_ADMIN_PASSWORD` 真生效、`token_version`、conftest | [`L142`](../DECISIONS.md#L142) |
| D11 | 测试可重复性：幂等种子 + 测试库隔离 | Accepted | `DEFAULT_SETTINGS`、`ERP_TEST_DB`、WAL 旁文件 | [`L187`](../DECISIONS.md#L187) |
| D12 | 并行工具引入代码的缺陷根治 | Accepted | 租户隔离、告警去重、阈值生效 | [`L221`](../DECISIONS.md#L221) |
| D13 | 并行工具代码的第二轮缺陷根治 | Accepted | 缓存指纹、告警可见性、巡检可调度 | [`L268`](../DECISIONS.md#L268) |
| D14 | 并行工具代码的第三轮根治 + 测试假绿审计 | Accepted | 恒真断言、自证式断言 | [`L311`](../DECISIONS.md#L311) |
| D15 | Phase 1.8 前端身份切 Context —— 优先级规则与「legacy 必须保留」的依据 | Accepted（**部分被 D23 / D24 修订**） | Context 无条件优先、legacy 兜底、代客一致性 | [`L375`](../DECISIONS.md#L375) |
| D16 | 测试可信度收口 —— 「断言存在」不等于「行为被守住」 | Accepted | 回退法、顺序依赖、定时炸弹、测试库与生产同构 | [`L486`](../DECISIONS.md#L486) |
| D17 | 可行性验证必须真启动服务 | Accepted | 真启动 uvicorn、T-13、隔离性检测有效性 | [`L683`](../DECISIONS.md#L683) |
| D18 | 仓库纳入 Git —— 唯一 P0 债务清零 | Accepted | `git init -b main`、`.gitattributes` 锁 LF、`fsck` | [`L806`](../DECISIONS.md#L806) |
| D19 | 分页参数必须有上限 | Accepted | `MAX_PAGE_SIZE=200`、静默截断导致假绿 | [`L873`](../DECISIONS.md#L873) |
| D20 | 主库残留计划任务必须停用 | Accepted | `schedules.enabled`、可逆处置不删行 | [`L960`](../DECISIONS.md#L960) |
| D21 | Docker 生产镜像端到端实测 | Accepted | `docker_feasibility.py`、锁定清单结构检查 | [`L1022`](../DECISIONS.md#L1022) |
| D22 | TLS 落地 —— 并把「修复」里藏的 3 个缺陷挖出来 | Accepted | Caddy、可信代理网段、`tls_feasibility.py` | [`L1127`](../DECISIONS.md#L1127) |
| D23 | G-3 工厂账号 Context 通道 | Accepted | 精确路径白名单、fail-open 修复、`status` 校验 | [`L1249`](../DECISIONS.md#L1249) |
| D24 | 前端 legacy 兜底降级为「只读」而非删除 | Accepted | 写权限 fail-closed、`LEGACY_CAPABILITIES` 整体删除 | [`L1349`](../DECISIONS.md#L1349) |
| D25 | 代客态 `/api/auth/me` 500 | Accepted | 鸭子类型身份对象、收敛到唯一序列化入口 | [`L1403`](../DECISIONS.md#L1403) |
| D26 | Membership 只有读取侧、没有写入侧 | Accepted | `membership_service.py`、共用 `normalize_legacy_role` | [`L1481`](../DECISIONS.md#L1481) |
| D27 | tenant_id 外键收敛：平台级表用 NULL 而非 0 哨兵值 | Accepted | 48/48 表受约束、`foreign_key_check` 0 违规 | [`L1567`](../DECISIONS.md#L1567) |
| D28 | 平台适配器拆包（1303 行 → 12 模块） | Accepted | 兼容门面、`monkeypatch` 静默失效陷阱 | [`L1677`](../DECISIONS.md#L1677) |
| D29 | 消除 Agent 间 P2P（L-3 架构红线） | Accepted | 共享领域计算下沉 `services/costing.py` | [`L1768`](../DECISIONS.md#L1768) |
| D30 | 文档一致性治理：脱节变成 CI 可拦的缺陷类别 | Accepted | `docs/baseline.json` 单一事实源、A/B/C 三项检查 | [`L1838`](../DECISIONS.md#L1838) |
| D31 | 内容损坏治理：潜伏 20 轮的反引号转义事故 | Accepted | 18 处围栏塌缩、D/E 两项检查 | [`L1918`](../DECISIONS.md#L1918) |
| D32 | 引用完整性治理：代码位置引用（F）+ ADR 索引锚点（G） | Accepted | 行号越界 11 处、锚点漂移 5 处、同名文件歧义保守跳过 | [`L1983`](../DECISIONS.md#L1983) |
| D33 | 文档地图：消除孤儿文档，「我该读哪份」的单一来源 | Accepted | 4 份零引用文档、H 项检查、T-53 消除第二份清单 | [`L2063`](../DECISIONS.md#L2063) |
| D34 | 僵尸状态治理：已完成的任务不得留下「进行中」标记 | Accepted | 2 处僵尸状态、I 项检查、T-54 | [`L2122`](../DECISIONS.md#L2122) |
| D35 | Agent 契约声明冻结：能力边界从文档搬进代码 | Accepted | 8 条契约、构建期权限自检、L-3 白名单反向断言（T-55）、SupportAgent 冲突（DEBT-34） | [`L2173`](../DECISIONS.md#L2173) |
| D36 | 源码文本卫生门禁：行尾契约必须覆盖全仓 | Accepted | 400 处 CRLF 实测漏检、K 项检查、T-56、3 个游离残留清理 | [`L2242`](../DECISIONS.md#L2242) |
| D37 | Tool Layer 落地：Agent 访问业务能力的唯一入口 | Accepted | 22 个冻结方法、写闸对 OWNER 也生效、审计独立会话、清单由解析 §10.4 表格校验、DEBT-35/36 | [`L2296`](../DECISIONS.md#L2296) |
| D38 | Agent 侧迁移启动：第二批 Tool 清单 + compliance 首个迁移 | Accepted | 补批「只增不改」、`BaseAgent.tool()` 唯一入口、审计行证明迁移、棘轮 57 → 56（1 处为写路径） | [`L2384`](../DECISIONS.md#L2384) |
| D39 | Conversation Tool 与 support:read 权限：Agent 侧迁移第二例 | Accepted | 冻结目录「只增不改」补 `support:read`（走迁移）、Tool 字段口径排除 `buyer_name`、棘轮 57 → 53 | [`L2444`](../DECISIONS.md#L2444) |
| D40 | listing.py 读取迁移 + platform_rules 字段级核心拆分 | Accepted | 判定核心与 ORM 适配器拆开、写路径集中 `_write_listing`、发布门禁反向断言、棘轮 53 → 48 | [`L2504`](../DECISIONS.md#L2504) |
| D41 | 第二批清单补 3 个方法 + supplier.py 迁移 | Accepted | 聚合下推 SQL、`supplier_ids` 三形态收口、报价候选上限 200（登记在案）、棘轮 48 → 41 | [`L2568`](../DECISIONS.md#L2568) |

**总计 43 条索引项，覆盖 D1~D41 全部编号**（D16/D17 各含早期重复编号一条，用 `(a)` 后缀区分）。

> **`D16(a)` / `D17(a)` 是什么**：`DECISIONS.md` 中 **D16 与 D17 各被使用了两次**
> （详见第 6 节「已知问题」）。本表用 `(a)` 后缀区分这两条**早期**决策，
> **不修改权威源**，仅在本索引层消除歧义。

---

## 3. 状态定义

| 状态 | 含义 | 出现该状态时的动作 |
|---|---|---|
| **Proposed** | 已提出，尚未生效 | 不得据此实现代码 |
| **Accepted** | 已采纳并生效，**当前有效** | 实现必须遵循 |
| **Superseded** | 已被后续决策取代，**不再有效** | 必须同时标注取代者编号；不得再引用为现行依据 |
| **Deprecated** | 仍然有效但**已不推荐**新代码使用 | 存量可保留，新增须走替代方案 |
| **Rejected** | 曾考虑并**明确否决** | 仅作历史记录，防止重复提议 |

### 现有 D 编号的状态映射

| 状态 | D 编号 | 说明 |
|---|---|---|
| **Accepted** | D1~D14、D16(a)、D17(a)、D16~D41 | 当前全部有效 |
| **Accepted（含修订）** | D8、D15、D16 | 见下表「修订关系」 |
| **Accepted（一次性例外）** | D9 | 破例本身已用完，约束继续生效：除「修复使迁移完全无法执行」外，已执行迁移只增不改 |
| **Superseded** | — | 暂无 |
| **Deprecated** | — | 暂无 |
| **Rejected** | — | 暂无（D1 表格中被否决的候选项目属**方案**层否决，非 D 编号） |

### 修订关系（非取代，原文仍有效）

| 被修订 | 修订者 | 关系 |
|---|---|---|
| D8「TLS 未纳入本次范围」 | **D22** | D22 完成 TLS 落地，**补全** D8 的显式留白；D8 其余内容仍有效 |
| D15 §二「工厂账号拿不到 Context」 | **D23** | 该前提**已不成立**（通道已打通）；D15 其余内容（Context 优先、代客一致性、展示/权限分离）仍有效 |
| D15 §六第 1 条 | **D23** | 同上 |
| D15 §二「legacy 兜底不能删」的理由 | **D24** | 理由已从「工厂拿不到 Context」改为「Context 请求可能失败」；结论「不能直接删」**不变** |
| D16 §8.3 | D16 自身 | 该节**修正了 D16 原文**关于明文截断的截断说法（原文不成立，已实测复核） |
| D20 §五、D16 §8.5 | 未处理 | 主库 probe 残留数据，**仍为遗留项** |

> **重要**：以上均为「修订 / 补全」，**不是 Superseded**。被修订段落作为
> **决策历史**保留——理解当时为何那样判断，比只看最终结论更重要。

---

## 4. 新增流程

### 4.1 常规决策（默认路径）

1. 在 `docs/DECISIONS.md` **末尾追加**新决策，编号取当前最大 D 编号 + 1
   （**当前最大为 D41，下一条是 D42**）；
2. 沿用权威源既有字段风格：`## D<n>：<标题>（<日期>）` + `**背景**` / `**决策**` /
   `**理由**` / `**验证**` / `**关联**` + 补充规范编号表（`T-*` / `DP-*` / `S-*` / `V-*`）；
3. 回到本文件第 2 节**补一行索引**（编号 / 标题 / 状态 / 关键词 / 锚点），
   锚点行号**必须重新核对**（追加会使后续行号不变，但插入会漂移）；
4. **默认到此结束**——不新建 `adr/NNNN-*.md` 文件。

### 4.2 什么时候才需要单独拆出 `adr/NNNN-*.md`

仅当决策**同时满足**「改变架构边界或安全模型」与「需要被外部独立引用」时。
判定清单（**满足任一项**才拆）：

- [ ] 改变了**安全模型**（鉴权、权限、信任边界、fail-open/fail-closed 语义）；
- [ ] 改变了**数据所有权或租户隔离边界**；
- [ ] 确立了**外部契约**（接口语义、错误语义、兼容性承诺）；
- [ ] 引入了**不可逆或高代价**的结构变更（迁移策略、存储语义、删除语义）；
- [ ] 会成为**后续多个决策的前置**（被反复引用为「依据」）。

**明确不拆**：一次性缺陷修复、测试基建改进、流程约定、验证脚本新增、
纯运维处置——这些留在权威源即可。**拆 26 个是重复劳动，且制造第二份真相。**

### 4.3 拆出时的写法要求

- 文件名：`adr/NNNN-<短横线英文名>.md`，`NNNN` 四位补零，**按原 D 编号顺序**
  （例：D3 → `0003-llm-dual-mode.md`）；
- 必须**自包含**，固定五节：`Context` / `Decision` / `Consequences` /
  `Alternatives considered` / `References`；
- `References` **必须回指** `DECISIONS.md` 的 D 编号与锚点，禁止只写 `ADR-NNNN`；
- **不得**复制权威源的实测证据表、验证日志、缺陷清单——摘要结论即可，
  细节一律回指权威源。

---

## 5. 已独立成文的 ADR

按「改变架构边界或安全模型」标准筛出 **7 条**：

| ADR | 标题 | 对应 D | 为何值得独立成文 |
|---|---|---|---|
| [`0003`](0003-llm-dual-mode.md) | LLM 双模架构 | D3 | 定义整个 AI 能力的**运行时契约**：LLM 与规则引擎必须同构，是全部 Agent 的前提 |
| [`0007`](0007-shop-archive-soft-delete.md) | 店铺删除语义：归档式软删除 | D7 | **数据保留边界**：确立「不物理删除业务实体」原则，影响财务对账与审计留痕 |
| [`0018`](0018-git-version-control.md) | 仓库纳入 Git 与 LF 行尾锁定 | D18 | **工程安全底座**：唯一回滚手段 + 行尾契约（CRLF 会导致容器启动即失败） |
| [`0022`](0022-tls-trusted-proxy.md) | TLS 落地与可信代理边界 | D22 | **信任边界**：转发头信任来源限定，伪造客户端 IP 会污染审计日志 |
| [`0023`](0023-factory-account-context.md) | 工厂账号 Context 通道：精确白名单 | D23 | **鉴权边界**：前缀匹配会连带放行写语义端点；并修复 fail-open 缺陷 |
| [`0024`](0024-frontend-permission-fail-closed.md) | 前端权限 fail-closed 降级 | D24 | **安全边界与体验兜底分离**：前端手工权限表一律视为缺陷 |
| [`0026`](0026-membership-write-side.md) | Membership 写入侧：唯一写入口 | D26 | **数据所有权**：身份表缺写入口会导致降权静默失效（安全缺陷） |

---

## 6. 已知问题（登记，未在权威源修正）

### 6.1 `DECISIONS.md` 中 D16 / D17 编号重号

| 编号 | 出现位置 | 实际主题 | 本索引记为 |
|---|---|---|---|
| D16 | [`L42`](../DECISIONS.md#L42)（**用 `#` 一级标题**） | 跨境平台角色与接入顺序（2026-09-21） | `D16(a)` |
| D17 | [`L49`](../DECISIONS.md#L49)（**用 `#` 一级标题**） | 销售渠道扩展分层（2026-09-21） | `D17(a)` |
| D16 | [`L486`](../DECISIONS.md#L486) | 测试可信度收口（2026-09-24） | `D16` |
| D17 | [`L683`](../DECISIONS.md#L683) | 可行性验证必须真启动服务（2026-09-24） | `D17` |

**成因**：这两条 2026-09-21 的早期决策以 `#` 一级标题写入，**跳过了 D6~D15 的编号**，
后被 D6 起的后续决策在文末顺序追加时**覆盖了编号**。

**现状处置**：**不修改权威源**（避免打断既有引用链），仅在本索引层用 `(a)` 后缀消歧。

**风险**：文档中单独出现「D16」/「D17」时**有歧义**。实测现有引用
（`docs/CODE_AND_DIRECTORY_STANDARD.md` 的 M-9 / T-12 / T-13 说明、
`docs/WORKSPACE_MIGRATION_PROGRESS.md` 第 44 行）**均指 2026-09-24 的那两条**，
暂未发现指向 `(a)` 的引用。

**建议后续处置**（需负责人裁决）：把早期两条重编号为 `D16(a)`/`D17(a)` 或
统一改为 `D0.1`/`D0.2` 式历史编号；**不建议**改成新编号（会打断引用链）。

---

## 7. 关联文档

| 文档 | 关系 |
|---|---|
| [`docs/DECISIONS.md`](../DECISIONS.md) | **权威源**，本目录的全部内容以其为准 |
| `docs/CODE_AND_DIRECTORY_STANDARD.md` | §10 Doc-1 规定 ADR 写法；§11 债务台账 DEBT-07 |
| `AGENTS.md` | §11 关键文档索引收录本文件 |
| `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` | Agent 层架构冻结（其决策另见权威源） |

---

**最后更新**：2026-09-27　**状态**：生效（镜像层，权威源为 `docs/DECISIONS.md`）
