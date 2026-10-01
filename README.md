# AI 电商ERP · AI 原生跨境电商智能运营平台

> 从「自动铺货工具」升级为「AI 自主经营系统」——基于《AI原生跨境电商运营平台需求分析与详细设计说明书 V8.0》全面实现的 MVP 工程。

系统通过多智能体（Multi-Agent）、大模型（Model Router）、RAG 知识库与自动化工作流，覆盖完整业务闭环：

**市场发现 → AI选品 → 供应商分析 → 利润计算 → 合规检测 → Listing生成 → 一键铺货 → 广告增长 → 动态定价 → 订单处理 → 客服服务 → 经营分析 → AI优化**

## ✨ 核心能力

| 模块 | 能力 | 对应规划章节 |
|---|---|---|
| 商品发现 Agent | 趋势扫描、关键词扩展、机会评分（需求/竞争/利润/风险四维加权） | 第七、八章 |
| **真实采集** | 三层管线：1688 官方 API（HMAC-SHA1 签名，配置 Key 优先走此）→ 无头浏览器渲染（Playwright 过反爬/等渲染）→ 粘贴网页源码兜底；含 JSON-LD/1688/京东内嵌 JSON 解析、SSRF 防护、验证码页识别。订单 CSV 导入（去重/状态映射/SKU 关联）与商品、订单 CSV 导出 | 第六、八章 |
| **采购闭环** | 补货预警 → 一键生成采购单（自动选最优货源报价）→ 提交供应商 → 收货入库（虚拟库存实时增加，预警自动消除）；支持报价单录入 | 第十四章 |
| **发货流程** | 已付款订单一键发货：生成物流单号（tracking_no）、状态流转 | 第九章 |
| **售后逆向** | 退款单全状态机（待审核→已同意→已退货→已退款/已拒绝）：重复退款拦截、金额按数量比例校验、退货入库可回补虚拟库存、整单退款自动联动订单状态 | 第十三章 |
| **规则引擎（防封店）** | 每平台规则包（标题/描述上限、违禁词表、禁售类目、图片要求、调用限流 QPS），版本化可远程更新（ERP_RULES_URL）；发布前三道关：规则包强制校验 → 平台必填字段校验 → 类目映射校验，任一不通过拒绝发布并给出原因 |
| **平台控制台(SaaS 超管)** | superadmin 登录后进入独立控制台（与租户业务菜单完全隔离）：运营总览 / 租户管理（开通·一次性初始密码·续期·停用）/ 访问审计（代客进入留痕）/ 系统维护（清空演示数据·平台规则更新检查）；服务授权到期/停用自动 403 门禁；代客访问签发租户上下文 token | 第三十一、三十三章 |
| **账期结算** | 供应商账期（15/30/45 天）：按供应商汇总已收货未结算采购单生成对账单 → 确认 → 标记付款；应付账龄总览（逾期笔数/金额标红） | 第十四章 |
| **店铺授权** | 平台适配器架构（各平台差异全部内聚）：1688（auth.1688.com OAuth + oauth2/getToken POST，按官方文档实现）/ Shopee（v2 HMAC-SHA256 签名、media_space 图片预上传、product/add_item）/ TikTok（HMAC-SHA256 签名 token/refresh/order.search）/ Amazon（能力清单禁用，不做假实现）；本地开发用「粘贴授权码」与公网回调等价；授权后真实拉单；密钥脱敏；数据来源标注 demo/api |
| **数据来源透明** | 订单同步标注来源（demo=模拟 / api=平台真实拉取）；「清空演示数据」一键删除种子数据（保留账号/店铺/设置），接入真实数据源 | 工程规范 |
| **发货流程** | 已付款订单一键发货：生成物流单号（tracking_no）、状态流转 | 第九章 |
| 商品分析 Agent | 类目映射、属性抽取、去重指纹 | 第八章 |
| 供应链 Agent | 最优货源匹配、供应商评分、销量预测、缺货预警 | 第十四章 |
| Listing Agent | 多语言文案生成、优化、一键发布（发布前强制合规校验） | 第五、九章 |
| 合规 Agent | 商标侵权/违禁宣称/图片风险/平台规则四维扣分制检测 | 第十章 |
| 定价 Agent | 真实利润公式（售价-采购-物流-佣金-广告）、成本加成+市场修正动态定价 | 第十一章 |
| 广告 Agent | AI 选词、预算 ROI 优化（>2 加预算/<0.8 降预算）、ROI 报告 | 第十二章 |
| 客服 Agent | 意图识别（订单/物流/售后/咨询）+ 知识库辅助自动回复 | 第十三章 |
| 总调度 Agent | 自然语言意图路由，调度全部专业 Agent（前端 AI 助手对话入口） | 第四章 |
| 工作流引擎 | 模板化多 Agent 流水线：自动铺货 7 步全链路 / 全店定价 / 补货预警 | 第十六章 |
| 自主经营调度器 | 定时自动执行工作流/趋势扫描（分钟级间隔、启停管理、执行统计） | 第四十二章 |
| 私域源头工厂 | 用户建档与尽调、工厂受限门户自维护商品/产能、机会 Agent、单位经济性门禁、候选供给转报价 | 供应链闭环 |
| BI 中心 | 统一 GMV/净收入/贡献利润/ROAS/ROI/退款率、数据质量门禁、预测监控、AI 经营报告 | 第十五章 |
| 模型体系 | Model Router（大模型+规则引擎双模）、RAG 知识库、AI 审计日志 | 第五章、二十一章 |

## 🚀 快速开始

### 环境要求
- Python 3.11+
- Node 18+（仅构建前端需要；已构建的可直接用）

### 一键启动（后端托管前端）

```bash
# 1. 后端
cd backend
# 锁定版本安装：与 CI、Docker 镜像完全一致（可复现）
pip install -r requirements-dev.lock.txt

# 2. 构建前端（首次）
cd ../frontend
npm install && npm run build

# 3. 启动（自动建库 + 灌入演示数据）
cd ../backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 **http://127.0.0.1:8000** 即可使用。

### 演示账号

| 账号 | 密码 | 角色 |
|---|---|---|
| admin | admin123 | 管理员（全部权限） |
| ops | ops123 | 运营（业务读写） |
| viewer | viewer123 | 只读 |

### 前后端分离开发

```bash
cd backend  && python -m uvicorn app.main:app --port 8000   # API
cd frontend && npm run dev                                   # http://localhost:5173（已配代理）
```

### 接入真实大模型（可选）

系统**离线零配置可完整运行**（全部 Agent 内置确定性规则引擎兜底）。接入 LLM 后自动升级为 AI 生成/分析：

方式一：页面「AI 设置」填 API Key（支持智谱 GLM / DeepSeek / OpenAI / Ollama 等任意 OpenAI 兼容接口）。

方式二：环境变量
```bash
export ERP_LLM_API_KEY=your-key
export ERP_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
export ERP_LLM_MODEL=glm-4-flash
```

### Docker 一键部署

```bash
# 首次部署前先准备 .env（compose 强制要求这四项，缺失会直接报错退出）
cat > .env <<'EOF'
ERP_JWT_SECRET=<至少 32 字节随机串>
ERP_ADMIN_PASSWORD=<强口令，不得为 admin123>
ERP_CREDENTIAL_KEY=<Fernet 密钥，用于加密店铺凭证>
ERP_CORS_ORIGINS=https://your-domain.example
EOF

docker compose up -d --build           # SQLite 版，数据持久化在 erp-data 卷
```

容器启动时会自动执行 `alembic upgrade head` 再拉起服务；迁移失败则容器不启动（宁可起不来，也不让旧 schema 带新代码对外服务）。

> **生产前置条件**：`ERP_ENV=production` 已由 compose 固定，`validate_production_settings()` 会拒绝弱 JWT 密钥、默认管理员口令、缺失凭证密钥、空 CORS，并要求**明确声明 TLS 终止位置**（见下）。

#### HTTPS 部署（二选一）

生产门禁要求显式声明 TLS 位置，否则拒绝启动——这是为了避免「静默以 http 对外服务」。

**方案 A：自带 Caddy 反向代理（推荐，自动申请续期证书）**

    # .env 追加：
    #   ERP_DOMAIN=erp.your-domain.com    # A 记录须指向本机公网 IP
    #   ACME_EMAIL=ops@your-domain.com    # 证书到期提醒
    docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d

Caddy 自动申请 Let's Encrypt 证书，暴露 80/443，并把真实客户端信息透传给应用。
**应用容器不再映射 8000**（覆盖层用 `!reset` 清空），确保外部无法绕过 TLS 直连。

**方案 B：复用已有的 nginx / traefik / 云负载均衡**

基础 compose 已声明「TLS 由外部终止」，并把端口绑定收紧为 **`127.0.0.1:8000`**
（只允许本机代理转发，避免 8000 直接暴露到网络）。在宿主机代理里转发到
`http://127.0.0.1:8000` 即可，无需额外配置。

> 若代理**不在本机**（如独立网关），需自行设置 `ERP_TRUST_PROXY_HEADERS=1` 与
> `ERP_TRUSTED_PROXY_HOSTS=<代理 IP 段>`，并确保外部无法直连应用端口——
> 否则任何人都能伪造 `X-Forwarded-For` 污染审计信息。

> **验证 TLS 链路**（真起 Caddy + 真应用容器，8 项检查；离线可用自签证书）：
> `cd backend && python scripts/tls_feasibility.py`

> MySQL 切换：`docker-compose.yml` 的 mysql profile 尚未接入（缺驱动与 `depends_on`），需先补 `pymysql` 依赖并把 `ERP_DB_URL` 指向 mysql 服务，详见 `docs/CODE_AND_DIRECTORY_STANDARD.md` DEBT-22。

### CI

`.github/workflows/ci.yml`：push/PR 自动跑后端 pytest + 前端构建。

### 测试

```bash
cd backend
python -m pytest -q          # 后端全量测试（用例数以 docs/baseline.json 为单一事实源，勿在此写死数字）

# 端到端可行性验证：真启动服务 + 真实 HTTP + 静态前端检查（在数据库副本上跑，不碰业务库）
python scripts/e2e_feasibility.py

# Docker 生产镜像可行性验证：真构建 + 真运行 + 真登录（需 docker）
python scripts/docker_feasibility.py
```

### 数据库迁移

生产或已有 SQLite 数据库升级前，先停止写入，再运行：

```bash
cd backend
python scripts/migrate.py
```

SQLite 会先生成带时间戳的同目录备份，再执行兼容补列并升级至 Alembic `head`。生产环境必须显式配置 `ERP_DB_URL`，并在发布前使用数据库快照演练恢复。

### 常用环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `ERP_DB_URL` | 数据库连接（可换 MySQL） | SQLite `backend/erp.db` |
| `ERP_JWT_SECRET` | JWT 密钥（生产必须修改） | dev-secret |
| `ERP_SYNC_WORKFLOW` | 1=工作流同步执行（调试） | 0（后台线程） |
| `ERP_PORT` / `ERP_HOST` | 监听地址 | 127.0.0.1:8000 |

## 🏗️ 架构

```
AI-电商ERP/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口 + 静态托管前端
│   │   ├── config.py          # 环境变量配置
│   │   ├── db.py / models.py  # SQLAlchemy 2.0 模型（52 张表）
│   │   ├── auth.py            # JWT + RBAC（admin/operator/viewer）
│   │   ├── seed.py            # 确定性演示数据（24商品/500订单/8供应商/8知识文档/3工作流模板）
│   │   ├── ai/
│   │   │   ├── llm.py         # Model Router：OpenAI 兼容协议 + JSON 容错解析
│   │   │   └── knowledge.py   # RAG-Lite 检索（中文二元组分词 TF 计分）
│   │   ├── agents/            # 9 个智能体（BaseAgent 双模执行 + AI 审计）
│   │   ├── workflows/engine.py# 工作流引擎（状态机 + context_patch 数据流）
│   │   ├── routers/           # 23 个路由模块（/api 前缀，含调度管理）
│   │   ├── services/          # scraper 真实URL抓取 / mock_market 演示源 / scheduler 自主经营调度器
│   └── tests/                 # 13 个测试文件 / 139 个用例（采集/CSV/采购发货/售后结算/OAuth/规则/租户门禁/安全矩阵/归档/配置隔离）

> 协议真实性声明：各平台认证与接口按官方公开文档实现并标注出处（代码内含文档链接），
> 规则包为官方文档整理快照（带版本日期），可通过 ERP_RULES_URL 对接远程规则源持续更新；
> 平台接口字段如有变更，以平台最新文档为准，系统会将平台真实报错原样透传。
> 演示账号与种子数据仅用于本地演示（可一键清空），商用前请配置真实凭证并清空演示数据。
├── frontend/                  # Vue3 + Element Plus + ECharts（28 个视图组件）
└── docs/                      # 契约、决策记录、需求说明书
```

关键设计：
- **LLM/规则双模**：每个 Agent 方法通过 `ask_json()` 优先 LLM 结构化输出，任何失败自动降级规则引擎——演示/生产/离线三种形态同一套代码。
- **统一经营口径**：财务决策区统一使用 USD 记账口径；GMV、净收入、贡献利润、ROAS/ROI、退款率均有可查询定义。订单行成本、平台/支付/税费/物流费用和广告花费分别入账，按交易时点之前最近汇率换算；缺失汇率的数据会显式排除并告警，不会静默混算。
- **结算对账**：平台结算单按 `平台 + 外部结算单号` 幂等写入，可核对应结净额、实际到账和差异。
- **私域工厂闭环**：ERP 用户录入自己认识的源头工厂并完成尽调；工厂账号只能维护本厂商品、MOQ、价格、库存、月产能和交期。系统将市场商品与工厂目录进行可解释匹配，仅在工厂已尽调且数据新鲜完整时允许转成报价，之后仍须经过 ListingReviewAgent 和人工审批才能上架。
- **机会收益门禁**：自动铺货工作流在标准化之后运行私域工厂机会 Agent，综合能力匹配、90 天数据新鲜度、产能、库存、图片、预计售价、单件利润和贡献利润率。私域报价未达标时不会生成，但不会错误阻断已有的 1688 或其他合格货源。
- **真实流程保护**：自动工作流不再把本地模拟发布标成平台成功；真实拉单使用店铺级同步并更新既有订单状态；失败恢复跳过已成功步骤，降低重复副作用风险。
- **角色工作区**：管理员可维护租户用户与角色；合规审批员聚焦复核；viewer 隐藏关键写操作；工厂账号只维护本厂目录；超级管理员代客访问具有明确进入与返回状态。
- **财务工作台**：前端可维护日级汇率、订单行、订单费用和平台结算，并查看应结、实结及差异；Dashboard、BI 与 AI 报告共用统一真实数据口径。
- **合规门禁**：Listing 发布前校验最新合规报告，高风险（如商标侵权）直接拒绝发布。
- **多租户预留**：全部业务表带 `tenant_id`，查询强制过滤。

## 🗺️ 与规划书的差距（路线图）

本仓库实现 V8.0 规划的核心闭环（第 1-21 章主体）。以下为生产化路线：
- 平台 OpenAPI 真实对接（Shopee/Amazon SP-API/1688 分销，替换 `services/mock_market.py` 适配器）
- 向量数据库升级 RAG（当前为 TF 检索，接口已抽象）
- MySQL/PostgreSQL + Redis + 消息队列（第 27-29 章）、K8s 部署（第 36 章）
- 图片合规走多模态模型识别（当前为规则启发）

## 📄 文档

- [docs/需求分析与详细设计说明书V8.0.md](docs/需求分析与详细设计说明书V8.0.md) — 原始规划
- [CONTRIBUTING.md](CONTRIBUTING.md) — **人类开发者贡献指南**（环境搭建 / 开发循环 / 迁移流程 / Windows 陷阱）
- [AGENTS.md](AGENTS.md) — **AI 助手协作规范**（红线、开工前必做、提交前检查清单）
- [docs/CONTRACT.md](docs/CONTRACT.md) — 工程接口契约（数据模型/Agent 签名/API 端点）
- [docs/DECISIONS.md](docs/DECISIONS.md) — 技术选型与开源调研决策记录
- [docs/archive/官方平台验收运行手册.md](docs/archive/官方平台验收运行手册.md) — Shopee、TikTok、eBay、Walmart、Lazada 官方环境逐级验收与证据要求
