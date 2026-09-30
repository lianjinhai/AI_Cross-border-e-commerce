# 工程接口契约（CONTRACT）V1.0

所有子代理必须严格遵守本契约。**只允许创建/修改自己名下的文件**，禁止 git 操作，禁止修改他人文件。

## 0. 全局约定

- 项目根：`F:\Desktop\个人文件\软件开发计划\AI-电商ERP`
- 后端 Python 3.11 + FastAPI + SQLAlchemy 2.0 + SQLite；前端 Vue3 + Element Plus + ECharts。
- 后端只依赖 `backend/requirements.txt` 内的包，禁止新增第三方依赖。
- 时间字段全部 naive UTC；金额：售价/利润用 USD，采购/物流成本用 CNY（汇率从 Setting.fx 读，默认 7.12）。
- 多租户：所有查询必须按 `tenant_id` 过滤。
- 响应风格：列表 `{"items":[...], "total":n, "page":p, "page_size":s}`；单对象直接返回 dict；错误 `HTTPException(status, detail="中文信息")`。
- 写接口用 `Depends(require_write)`；管理接口用 `Depends(require_admin)`；只读用 `Depends(get_current_user)`。
- 序列化统一用 `app.serialize.to_dict(obj)` / `app.serialize.page(...)`。
- 文件末尾不留多余空行问题；每个后端文件完成后执行 `python -m py_compile <file>` 自检。

## 1. 已就绪的地基（可直接 import）

```python
from app.config import settings                     # settings.db_url / sync_workflow / llm_* / frontend_dist
from app.db import Base, engine, SessionLocal, get_db, init_db
from app.models import (Tenant, User, Setting, Product, ProductScore, MarketTrend,
    Supplier, SupplierOffer, SupplierScore, Listing, ComplianceReport, PricingRecord,
    AdCampaign, Order, Conversation, Message, WorkflowTemplate, WorkflowRun,
    WorkflowStep, KnowledgeDoc, AiLog)
from app.serialize import to_dict, page
from app.auth import hash_password, verify_password, create_token, get_current_user, require_write, require_admin
from app.ai.llm import ModelRouter, LLMUnavailable, get_llm_config, set_llm_config, parse_json
from app.ai.knowledge import retrieve                 # retrieve(db, tenant_id, query, top_k=4) -> [{id,title,source,content,score}]
from app.agents.base import BaseAgent                 # BaseAgent(tenant_id)，支持 with；.ask_json(action, system, prompt, fallback, small_task=False) -> (dict, "llm"|"rule")
```

Setting 表约定 key：`llm`（见 ai/llm.py DEFAULT_LLM）、`platform_fees`（{"shopee":0.06,"amazon":0.15,"shopify":0.02,"ebay":0.12,"temu":0.05,"tiktok":0.08}）、`fx`（{"USD":7.12,"EUR":7.8}）、`rules`（{"min_margin":0.15,"target_margin":0.35,"logistics_base":18.0,"logistics_per_kg":8.0,"ads_default":1.5}）。读取方式：`db.get(Setting, key)`，不存在用上述默认。

## 2. 智能体层契约（agents/*）

所有 Agent：构造 `XxxAgent(tenant_id: int)`，支持 `with`；类属性 `name` 指定如下。下列为早期方法清单，数据库访问约束以 Agent OS §18.3 和 `docs/DECISIONS.md` D37~D47 的迁移现状为准。返回**纯 dict/list**（不要返回 ORM 对象）。LLM prompt 用中文+结构化要求，fallback 必须完整可用。

### 2.1 DiscoveryAgent（name="discovery"，文件 agents/discovery.py）
市场发现+选品（对应规划第七章）。评分公式：`total = 0.35*demand + 0.20*(100-competition) + 0.30*profit + 0.15*(100-risk)`。
- `scan_trends() -> list[dict]`：基于现有商品类目+固定关键词池 upsert 12 条 MarketTrend（同 keyword+platform 更新数值），返回 to_dict 列表。
- `expand_keywords(keyword: str) -> {"keywords": [str]}`：8-12 个扩展词（类目词+属性词+平台词+长尾组合；LLM 可增强）。
- `score_product(product_id: int) -> dict`：写一条 ProductScore，返回 `{"product_id","demand","competition","profit","risk","total","reasons":[str],"model","score_id"}`。规则依据：MarketTrend 匹配类目→demand；类目商品数→competition；利润率(见 PricingAgent 成本)→profit；标题命中品牌/敏感词→risk。reasons 为中文依据说明（2-4条）。
- `score_batch(product_ids: list[int]) -> {"results":[score dict]}`
- `pick_candidates(limit: int = 3, min_total: float = 60) -> {"items":[score dict + {"title","category"}], "context_patch": {"product_ids":[int]}}`：取每个商品**最新**评分排序。

### 2.2 ProductAgent（name="product"，文件 agents/discovery.py 同文件）
商品标准化（第八章）。`_CJK_CATEGORY_MAP`：关键词→标准类目（家居/3C配件/宠物用品/户外运动/美妆工具/母婴用品/服饰配件/厨房用品）。
- `standardize(product_id: int) -> {"product_id","category","attrs":{...},"dedupe_hash","is_duplicate":bool,"duplicate_of":int}`：dedupe_hash=sha256(类目+规范化标题前20字+主要属性)；同 tenant 内重复则 is_duplicate=True, duplicate_of=已存在商品id。
- `standardize_batch(params: dict, context: dict) -> {"standardized":[int],"duplicates":[int],"context_patch":{}}`：product_ids 优先 params["product_ids"]，否则 context["product_ids"]。

### 2.3 SupplierAgent（name="supplier"，文件 agents/supplier.py）
- `match_best(product_id: int) -> dict`：该商品所有 SupplierOffer 按 价格40%+发货时效30%+供应商rating/stability30% 打分选最优，返回 `{"product_id","supplier":{...},"offer":{...},"reason":str}`；无 offer 返回 `{}`。
- `match_best_batch(params, context) -> {"matches":[{"product_id","supplier_id","supplier_name","offer_id","price","ship_days"}], "context_patch":{"offers":{str(pid):{"supplier_id","price","ship_days"}}}}`
- `score_supplier(supplier_id: int) -> dict`：写 SupplierScore，返回 `{"supplier_id","quality","cost","delivery","stability","total","reasons":[str],"model","score_id"}`。quality=rating/5*100；cost=按该供应商 offers 均价相对全站分位；delivery=(14-ship_days)/14*100；stability 原值。total=0.35*quality+0.25*cost+0.2*delivery+0.2*stability。
- `forecast(product_id: int) -> dict`：`{"product_id","weekly_demand","onhand","shortage_risk","suggest_restock_qty","trend":[{week,demand} x4]}`。销量=近28天 Order(qty) 按周分桶→简单线性外推下周需求；onhand 取 attrs.get("onhand",0)；shortage_risk: onhand<1周→high，<2周→mid，否则 low；suggest_restock_qty=max(0, 4周需求-onhand)。
- `forecast_batch(params, context) -> {"forecasts":[forecast dict], "context_patch":{"shortages":[{product_id,title,weekly_demand,onhand,shortage_risk,suggest_restock_qty}]}}`（product_ids 缺省=全部 active 商品）

### 2.4 PricingAgent（name="pricing"，文件 agents/pricing.py）
真实利润公式（第十一章）：`profit = price - (purchase_cny + logistics_cny + platform_fee_rate*price*fx + ads_cost_cny)/fx`。
- `calc_profit(product_id: int, price: float | None = None) -> dict`：`{"product_id","purchase_cost","logistics_cost","platform_fee_rate","ads_cost","price","profit","margin","currency","fx"}`。price 缺省=attrs.get("sale_price")；采购价=最优 SupplierOffer.price（无则 attrs.supplier_price）；logistics=rules.logistics_base + logistics_per_kg*attrs.weight_kg（默认1kg）；platform_fee_rate 从 Setting.platform_fees[attrs.get("platform","shopee")]；ads_cost=rules.ads_default（CNY）。
- `suggest_price(product_id: int) -> dict`：Agent 只输出分析及内部 `_analysis_record`，id/created_at 为 null；不写 PricingRecord、不修改售价、不生成 Action。成本包含采购、物流和广告；目标价=cost_cny*(1+target_margin)/(fx*(1-fee_rate))，下限=cost_cny*(1+min_margin)/(fx*(1-fee_rate))；需求/竞争作市场修正，非有限 LLM 价格退回规则。HTTP 由 Orchestrator 调用分析产物服务，复核 finance:write、Workspace、身份和商品归属，返回真实 PricingRecord id/created_at；reason._persistence 保存服务端来源与去重键（D50）。
- `reprice_batch(params, context)`：显式 params.product_ids 优先，其次 context.product_ids；均未提供时读取全部 active 商品，上限 200。返回完整分析列表 repriced 和逐商品 errors，不再静默吞掉分析异常。调度层整批原子保存可用产物，errors 非空时 business_status=blocked，context_patch.pricing_record_ids 返回记录引用。同一服务端范围、Workspace、请求人、商品复用原始快照，不覆盖已保存分析；新请求范围可保存新快照。Workflow 缺少可信发起人时阻断人工恢复。

### 2.5 AdsAgent（name="ads"，文件 agents/pricing.py 同文件）
- `suggest_for_product(product_id: int, platform: str = "facebook") -> dict`：草稿 `{"name","platform","product_id","keywords":[8-12个]（expand_keywords+商品标题词）、"budget","status":"draft","reason":str}`，不落库。
- `draft_batch(params, context)`：Agent 只返回 CREATE_AD_CAMPAIGN_DRAFT 提案（id=null、status=PROPOSED），不创建 AdCampaign。Orchestrator 绑定可信身份，提交 LOW / finance:write / AUTO_SAFE Action；Executor 仅创建本地 draft，日预算限 5～500 USD，不启动投放。返回 campaign_drafts（真实 id、action_id、action_status）与 context_patch.campaign_ids。显式空商品范围不回退全量；完全未提供范围才读取已发布商品。同一服务端工作流范围幂等，失败终态不自动重试（D49）。
- `optimize_budget(campaign_id: int) -> dict`：按 ROI 产出建议：roi>2→预算+30%（上限500），roi<0.8→-40%，0.8-2→维持；返回 `{"campaign_id","old_budget","new_budget","action","reason","roi"}`，**不改预算**。路由将变更建议提交为 HIGH 风险 `ADJUST_AD_BUDGET` Action，审批后由 Executor 写入（D47）。
- `roi_report() -> {"summary":{"total_spend","total_revenue","roi","avg_ctr"},"campaigns":[campaign dict + {"roi","ctr","cvr"}]}`。

### 2.6 ListingAgent（name="listing"，文件 agents/listing.py）
- `generate(product_id: int, platform: str = "shopee", language: str = "en") -> dict`：只返回 `CREATE_LISTING_DRAFT` 提案，Agent 不建 Listing 行。保留知识增强、文案自检及模板降级；HTTP/工作流由 Orchestrator 提交并自动执行草稿 Action，返回真实 Listing id、status="draft"、action_id、action_status="SUCCESS"（D48）。
- `optimize(listing_id: int) -> dict`：只返回 `UPDATE_LISTING_CONTENT` 提案；执行器仅允许修改内容未变化的草稿。HTTP 返回执行后 Listing dict 与 Action 引用；已发布内容或陈旧提案返回 409。
- `publish(listing_id: int, shop_id: int | None = None) -> dict`：只返回 `PUBLISH_LISTING` 提案。HTTP 先复核当前内容，提交后返回 `status="PENDING_APPROVAL"`、`action_id`、`approval_required=true`，**不立即上架**。调用 Action approve 后，还必须独立调用 execute；成功结果在 outcome.result。真实/演示/本地发布都需审批；执行时再次核对权限、内容指纹、规则、复核结论及店铺归属。
- `generate_batch(params, context) -> {"listings":[Listing dict], "context_patch":{"listing_ids":[int]}}`：platform/language 取 params（默认 shopee/en），product_ids 取 params 或 context。
- `publish_batch(params, context)`：Agent 保留每项提案，Orchestrator 汇总为 published/pending/blocked；context_patch 包含 pending_action_ids、published_product_ids。有未执行或拒绝动作时 business_status="blocked"，暂停下游。人工执行后 resume 不重跑成功上游；同一范围的拒绝/失败 Action 不被自动换成新提案。

### 2.7 ComplianceAgent（name="compliance"，文件 agents/compliance.py）
- `check(target_type: str, ref_id: int) -> dict`：创建 ComplianceReport。检测项（每命中一条计一次扣分）：
  1. 品牌风险：文本含品牌黑名单词（从 KnowledgeDoc 检索"商标黑名单"+内置兜底列表 Apple/iPhone/Samsung/Nike/Adidas/Disney/LEGO/LV/Rolex/Pokemon 等）→ level=high，每词扣50（单一品牌词命中即 high）。
  2. 违禁宣称：最/第一/顶级/ No.1 /cure/FDA approved/杀菌/防癌/100% safe → level=mid，扣15。
  3. 图片风险：images 为空→mid 扣20；URL 含 watermark/logo→mid 扣15。
  4. 平台规则：retrieve() 知识库平台规则相关命中作参考（LLM 模式下作为上下文）。
  score=max(0,100-扣分)；risk_level：score<60→high，<85→mid，else low。suggestions 每个问题给中文整改建议。同步写 Listing.risk_level（若 target 是 listing）。返回 to_dict(report)+`"model"`。
- `check_product(product_id)` / `check_listing(listing_id)`：薄封装调 check。
- `check_batch(params, context) -> {"reports":[report dict], "context_patch":{"risk_high":[ref_id...]}}`：items=params["items"] 或由 product_ids/listing_ids 构造（context["product_ids"]→product 检查，context["listing_ids"]→listing 检查）。

### 2.8 SupportAgent（name="support"，文件 agents/support.py）
- `classify(text: str) -> str`：意图 order_status（订单/发货/到货/where is my order/delivered）/logistics（物流/快递/tracking/shipping）/refund（退款/退货/refund/return/broken/损坏）/product_qa（尺寸/材质/颜色/尺码/how to use）/other。
- `auto_reply(conversation_id: int) -> dict`：取最近 buyer 消息→classify→按意图回复（order_status：查 conversation.order_id 的订单状态，中文模板；logistics：物流说明+预计时效；refund：安抚+售后流程+提醒人工跟进；product_qa：商品 attrs 问答+知识库 retrieve 辅助；other：通用回应）。写入 Message(role="agent", auto=True, intent=意图)，更新 conversation.last_message_at。返回 to_dict(Message)。

### 2.9 OrchestratorAgent（name="orchestrator"，文件 agents/orchestrator.py）
总调度（第四章）。`chat(message: str) -> {"reply": str, "intent": str, "actions":[str], "data": any}`。
意图路由（关键词匹配，中文优先）：
- 选品/发现/机会/爆款 → DiscoveryAgent.pick_candidates(3)，data=items，actions=["pick_candidates"]
- 趋势/市场/热销 → scan_trends 摘要
- 定价/价格/利润 → reprice_batch 后汇总 top5（"已生成 N 条定价建议…"）
- 铺货/上架/发布 → 返回引导语 + 提示去 AI 工作流页运行 auto_listing（不自动执行）
- 供应商/货源/采购 → 全部供应商 score_supplier 后 top3 摘要
- 客服/消息/售后 → open 会话数统计摘要
- 报告/经营/分析/BI → 计算 GMV/订单/利润/ROI 汇总文字
- 兜底：LLM 可用→自由对话；否则返回能力清单帮助文案。
每次 chat 写 AiLog(agent="orchestrator", action="chat")。

## 3. 工作流引擎契约（workflows/engine.py，A2 名下）

```python
REGISTRY: dict[tuple[str,str], Callable[[int, dict, dict], dict]]  # (agent, action) -> fn(tenant_id, params, context) -> output dict
```
注册项：`("discovery","pick_candidates") ("product","standardize_batch") ("supplier","match_best_batch") ("supplier","forecast_batch") ("compliance","check_batch") ("listing","generate_batch") ("listing","publish_batch") ("pricing","reprice_batch") ("ads","draft_batch") ("discovery","scan_trends")`。Agent 实例在 dispatch 内按需创建（`with`），lazy import 防循环依赖。

```python
def start_run(tenant_id: int, template_key: str, context: dict | None = None) -> dict:
    # 找 WorkflowTemplate(key==template_key) -> 建 WorkflowRun(status="running", name=template.name, context=context or {})
    # 按 template.steps 顺序建 WorkflowStep(seq 从 1, status="pending")
    # settings.sync_workflow 为真 -> 同步调 run_workflow(run_id)；否则 threading.Thread(target=run_workflow, args=(run_id,), daemon=True).start()
    # 返回 to_dict(run)（含 steps 由调用方另查）

def run_workflow(run_id: int) -> None:
    # 独立 SessionLocal。顺序执行 pending 步骤：status=running+started_at -> dispatch(tenant_id, params=step参数或{}, context=run.context)
    # output 全量存 step.output；run.context.update(output.get("context_patch", {}))
    # 成功：status=success+finished_at；异常：step failed+error，run.status=failed+error+finished_at，后续步骤保持 pending
    # 全部成功：run.status=success+finished_at
def run_step(agent_name: str, action: str, tenant_id: int, params: dict, context: dict) -> dict  # REGISTRY 查找，未注册 -> raise ValueError
```

## 4. 模拟采集服务契约（services/mock_market.py，B3 名下）

```python
PRODUCT_TEMPLATES: list[dict]  # ≥40 条 {title_zh, title_en, category, attrs:{weight_kg, material, color, moq, supplier_price(CNY), sale_price(USD), onhand}, scene_words}
def gen_products(keyword: str | None = None, count: int = 8) -> list[dict]      # 模拟 1688 采集结果，确定性随机
def insert_products(db, tenant_id: int, items: list[dict], source_platform="1688") -> list[Product]
def collect(db, tenant_id: int, platform: str, keyword: str | None, count: int) -> dict   # -> {"collected": n, "items": [to_dict(Product)]}
def gen_order(db, tenant_id: int, platform: str | None = None) -> Order          # 随机商品→下单（含成本/利润换算）
```

## 5. 路由层契约（routers/*，B1/B2）

每个文件 `router = APIRouter(prefix="/xxx", tags=["xxx"])`；统一在 main.py 注册（prefix="/api"）。列表接口分页参数 `page:int=1, page_size:int=20`，`total=db.query(...).count()`。

**分页参数约束（2026-09-24 起，`app/pagination.py`）**：

- `page_num >= 1`，`1 <= page_size <= 200`（`MAX_PAGE_SIZE`），越界一律 **422**；
- **超上限刻意报错、不做静默截断**：调用方做「集合比对」时若只拿到第一页，
  漏掉的记录不会被发现（实测测试库 `orders` 恰好 500 条，与旧的硬编码
  `page_size=500` 相等，数据一涨就会假绿）；
- 需要全量时**必须分页遍历**（参考 `tests/conftest.py` 的 `fetch_all` 夹具、
  `scripts/security_data_audit.py` 的 `get_all`），禁止用大 `page_size` 一把梭；
- `limit` 类参数（非分页）沿用各自上限并在服务端 `min()` 夹取。

### B1 名下
- **auth.py** `/auth`：`POST /login {"username","password"} -> {"token","user":{...}}`（验证失败 400）；`GET /me -> user dict`；`GET /users`(admin) 列表；`POST /users`(admin) {"username","password","role","display_name"}；`PUT /users/{id}`(admin)；`DELETE /users/{id}`(admin，不能删自己)。
- **products.py** `/products`：`GET ""?keyword&category&status&page&page_size`（keyword 模糊匹配 title/sku）；`POST ""` 创建；`GET /{id}` 详情（附 scores 最新5、offers（带 supplier_name）、listings、pricing 最新1、compliance 最新1）；`PUT /{id}`；`DELETE /{id}`（软删 status="deleted"）；`POST /collect`（require_write，body {"source_platform","keyword","count"} → mock_market.collect）；`POST /{id}/standardize`（ProductAgent）。
- **discovery.py** `/discovery`：`GET /trends`；`POST /trends/scan`（scan_trends，require_write）；`POST /expand {"keyword"}`；`POST /score/{product_id}`；`POST /pick {"limit":3}`；`GET /scores?product_id=`；`GET /performance/{product_id}?window_days=30`（M1 真实经营表现；**校验商品归属，跨租户/不存在 -> 404**；window_days 夹紧 `[1,365]`）。
- **suppliers.py** `/suppliers`：`GET ""` 列表（附最新 score）；`POST ""`；`PUT /{id}`；`GET /{id}` 详情（offers+score）；`POST /{id}/score`（SupplierAgent）；`POST /match {"product_id"}`；`GET /forecast?product_id=`（有 product_id 单品，无则 forecast_batch 全部）；`GET /offers?product_id=`。
- **listings.py** `/listings`：`GET ""?product_id&platform&status&page&page_size`（附 product title）；`POST /generate {"product_id","platform","language"}`；`POST /{id}/optimize`；`POST /{id}/publish`（ValueError→HTTPException 400）；`DELETE /{id}`。
- **compliance.py** `/compliance`：`GET /reports?target_type&ref_id&page&page_size`；`POST /check {"target_type":"product"|"listing","ref_id"}`；`GET /reports/{id}`。

### B2 名下
- **pricing.py** `/pricing`：`GET ""?product_id&page&page_size`（记录列表，附 title）；`POST /calc {"product_id","price"?}`；`POST /suggest {"product_id"}`。
- **ads.py** `/ads`：`GET /campaigns`（roi_report 结果）；`POST /campaigns`（草稿/表单创建，可含 id 列表批量）；`POST /campaigns/{id}/optimize` 返回预算建议、`action_id` 与 `PENDING_APPROVAL`，预算不立即改变；`POST /suggest {"product_id","platform"}`。
- **actions.py** `/actions`（D47～D49）：`GET ""?status=&action_type=` 查当前 Workspace 的指定类型 Action，缺省仍为 ADJUST_AD_BUDGET；另支持 PUBLISH_LISTING、CREATE_LISTING_DRAFT、UPDATE_LISTING_CONTENT、CREATE_AD_CAMPAIGN_DRAFT，权限按服务端目录。`POST /{id}/approve|reject {"note"}` 仅人工审批动作可用；`POST /{id}/execute` 对已批准 Action 幂等执行，复核当前执行人及原请求者的真实权限、租户状态和服务授权。FAILED/REJECTED 不允许重试同一 Action；结果/失败现场保存在 outcome。Listings 页面提供独立发布审批队列。
- **orders.py** `/orders`：`GET ""?platform&status&keyword&page&page_size`；`POST /sync {"platform","count":5}`（gen_order×n，require_write）；`PUT /{id}/status {"status"}`（校验合法值）。
- **support.py** `/support`：`GET /conversations?status&page&page_size`（附 last message + buyer_name）；`POST /conversations {"platform","buyer_name","content",?order_id,?product_id}`（创建会话+首条 buyer 消息）；`GET /conversations/{id}`（含 messages）；`POST /conversations/{id}/reply {"content"}`（operator 回复）；`POST /conversations/{id}/auto_reply`（SupportAgent）；`POST /conversations/{id}/close`。
- **bi.py** `/bi`：
  - `GET /dashboard -> {"gmv","orders","profit","ad_spend","roi","refund_rate","active_listings","open_conversations","sales_trend":[{date,gmv,orders}×30],"category_dist":[{category,revenue}],"platform_dist":[{platform,revenue}],"top_products":[{product_id,title,units,revenue}×5],"recent_runs":[run dict×5]}`
  - `GET /profit?days=30 -> {"days","series":[{date,revenue,cost,profit,margin}],"summary":{...}}`
  - `GET /report -> {"report": str, "generated_at"}`（AI 经营报告：组装 KPI 数据 ask_json 生成 markdown，失败用模板文案）
- **workflows.py** `/workflows`：`GET /templates`；`POST /run {"template_key","context"?}`（require_write → start_run 返回 run dict+steps）；`GET /runs?limit=20`（倒序）；`GET /runs/{id}`（run+steps）。
- **knowledge.py** `/knowledge`：`GET /docs?keyword&page&page_size`；`POST /docs`；`PUT /docs/{id}`；`DELETE /docs/{id}`；`GET /search?q=&top_k=4`（knowledge.retrieve）。
- **ai.py** `/ai`：`GET /settings`（llm+platform_fees+fx+rules，api_key 脱敏为 bool `has_key`）；`PUT /settings`（admin；body 任意子集，llm 走 set_llm_config，其余 upsert Setting）；`POST /chat {"message"}`（OrchestratorAgent.chat，require_write）；`GET /logs?limit=50 -> {"items":[...]}`（倒序）；`GET /decisions?subject_type&subject_id&agent&limit=50`（M6 决策依据链，`{"items","total"}`，每条含 `decision` + `evidence`）。
- **alerts.py** `/alerts`（M3 主动巡检，**只告警不执行**）：`GET ""?status&level&limit=100 -> {"items","returned","total","counts":{high,mid,low,open}}`。**级别排序在 SQL 内完成后再 limit**（high 优先，避免高风险被大量低风险挤出结果）；`total` 是**符合条件的总数**（不受 limit 影响，供分页用），`returned` 才是本次返回条数；`counts` 走数据库聚合，同样不受 limit 影响。`PUT /{id}/ack`（require_write，标记已处理，不删除）；`GET /rules -> {"items":[...]}`（9 条，首次访问自动初始化）；`PUT /rules/{id}`（require_write，`{enabled?,level?,threshold?}`，threshold 按 key 合并）；`POST /scan`（require_write，手动触发一轮，返回 `{created,skipped,by_rule,scanned_at}`）。

## 6. main.py + seed.py（B3 名下）

**main.py**：`create_app()`；CORS allow_origins=["*"]；按第5节顺序 include_router 到 `/api`；`@app.on_event("startup")` 里 `init_db()` + `seed_if_empty()`；若 `settings.frontend_dist` 存在：mount `/assets` StaticFiles + `GET /{path:path}` SPA 兜底回 index.html（`/api` 开头的路径返回 JSON 404）。末尾 `app = create_app()`，`if __name__ == "__main__": uvicorn.run(...)`。

**seed.py**：`seed_if_empty() -> bool`（Tenant 存在即 False）。创建：租户"演示商家"；用户 admin/admin123(admin)、ops/ops123(operator)、viewer/viewer123(viewer)；4 个 Setting（默认值见第1节）；mock_market 生成 24 个商品；8 个供应商 + 每商品 2-3 条 offers；MarketTrend 12 条；ProductScore 24 条（本地简单公式，同第2.1权重）；Listing 6 条（前6商品，draft/en，shopee+amazon 混合）；ComplianceReport 4 条（low/mid/high 覆盖）；PricingRecord 12 条；AdCampaign 6 条（running×3/draft×2/paused×1，spend/revenue/impressions/clicks/orders 数值自洽）；Order 500 条（random.seed(42)，近60天，状态分布 pending10%/paid20%/shipped30%/delivered35%/refunded5%）；Conversation 8 条（含 2-4 条 buyer 消息，部分带 order_id/product_id）；KnowledgeDoc 8 篇（标题：平台违禁词与宣称规范/商标黑名单清单/图片版权合规指引/各平台佣金费率表/选品评分标准说明/动态定价公式说明/客服回复规范/广告投放优化指南，每篇 300-600 字实用内容）；WorkflowTemplate 3 个：
  - `auto_listing`「自动铺货全流程」steps=[discovery/pick_candidates{limit:3}, product/standardize_batch, supplier/match_best_batch, compliance/check_batch, listing/generate_batch{platform:"shopee",language:"en"}, listing/publish_batch, ads/draft_batch{platform:"facebook"}]
  - `reprice`「全店动态定价」steps=[pricing/reprice_batch]
  - `restock`「补货预警分析」steps=[supplier/forecast_batch]
  - AiLog 10 条样例。**确定性**：random.seed(42)。所有创建走 db.add/commit。

## 7. 测试契约（`tests/`，B3 名下）

**环境与库隔离（由 `tests/conftest.py` 统一提供）**：`ERP_DB_URL` 指向测试库、`ERP_SYNC_WORKFLOW=1`；会话级夹具删除旧库文件（**含 `-wal`/`-shm` 旁文件**）→ `TestClient(app)`（触发 startup 建表 + 种子）。

测试库默认名 `test_erp_<pid>.db`（PID 隔离，支持并发/重复运行），可用 `ERP_TEST_DB` 覆盖为固定名。**测试模块禁止跨文件 import 夹具**（会引入收集顺序依赖）。

**覆盖范围**：登录/鉴权 401、商品列表与详情、采集、选品评分、供应商评分与预测、合规检测(product)、Listing 生成→发布、定价建议、订单同步、客服 auto_reply、工作流 auto_listing 运行至 success 且 steps 全 success、BI dashboard、知识库搜索、AI chat；另有安全矩阵（RBAC、跨租户隔离、JWT 撤销）、四域深度对抗（状态机/越权/财务口径/协议签名）、Phase 1 Workspace 系列、Supply/Sales 边界、店铺归档、配置作用域、生产口令生效、迁移预检与备份演练。断言核心字段存在与状态流转，不追求覆盖全部分支。

**当前基线**：测试用例数以 `docs/baseline.json` 为单一事实源（由 `backend/scripts/refresh_test_baseline.py` 采集）。
测试必须可重复（同库连跑两次）且可并发（多进程独立库）。

## 8. 前端契约（C1 名下框架+全部页面）

- 目录 `frontend/`：package.json（deps: vue ^3.5 / vue-router ^4.5 / element-plus ^2.9 / @element-plus/icons-vue ^2.3 / axios ^1.7 / echarts ^5.6；dev: vite ^5.4 / @vitejs/plugin-vue ^5.2；scripts: dev `vite --port 5173`，build `vite build`）；vite.config.js（vue 插件 + `server.proxy["/api"]="http://127.0.0.1:8000"`）；index.html（title「AI 电商ERP · 智能运营平台」，lang=zh-CN）。
- `src/main.js`：createApp + ElementPlus 全量 + icon 注册 + router + `import 'element-plus/dist/index.css'`。
- `src/api.js`：axios 实例 baseURL `/api`；请求拦截加 `Authorization: Bearer localStorage.erp_token`；响应拦截：401→清 token 跳 `/login`；业务错误统一 `ElMessage.error(err.response?.data?.detail || '请求失败')` 后 reject。导出默认实例 + `export const fmtMoney/v/vRate` 等小工具（如需要）。
- `src/router.js`：`/login`→Login；`/`→Layout 重定向 dashboard，children：dashboard/discovery/products/listings/compliance/shops/suppliers/factory-portal/pricing/ads/orders/refunds/settlements/support/workflows/knowledge/bi/finance/alerts/ai-decisions/users/settings/platform-admin（全部用懒加载 `() => import(...)`）；全局前置守卫：无 token 且非 /login → /login，并按 `permissions.routeRedirect` 做角色分流。
- `src/styles.css`：全局微调（页面容器 16px 内边距、卡片间距、统计卡栅格）。
- `Layout.vue`：el-container；侧边栏分组菜单【概览】驾驶舱/BI经营分析、【商品】商品发现/商品池/Listing工作台/合规检测、【采购】供应商/动态定价、【运营】广告增长/订单管理/智能客服、【系统】AI工作流/知识库/AI设置；顶部面包屑+用户名下拉（退出登录）；`<router-view/>`。
- 页面统一模式：`onMounted` 拉数据 + el-table + el-pagination + 操作列按钮 + el-drawer/dialog 表单；加载 `v-loading`；成功 `ElMessage.success`；金额 `toFixed(2)` 前缀 `$`。
- 各页面核心交互：
  - **Dashboard**：6 个统计卡（GMV/订单数/真实利润/广告ROI/在售Listing/待处理会话）+ 30日GMV&订单双轴折线 + 类目分布饼图 + 最新工作流运行表（状态 tag）。
  - **Discovery**：趋势表（扫描趋势按钮）+ 关键词扩展输入 + 商品机会分表格（每行「评分」按钮 + 进度条展示 total）+ 一键选品（POST /discovery/pick，结果卡片）。
  - **Products**：筛选/新增/采集对话框（平台+关键词+数量）/行操作：详情抽屉（评分、供应商报价、Listing、定价、合规报告 tab）、标准化按钮、删除。
  - **Listings**：筛选；「AI 生成」对话框（选商品+平台+语言）；行：优化/发布（发布前若 risk_level==high 确认提示）/删除；状态与风险 tag。
  - **Compliance**：检测对象切换(product/listing)+ID 输入 → POST /check；报告列表抽屉（issues 表格 + 建议）。
  - **Suppliers**：列表（评分列 progress）；「AI 评分」按钮；详情抽屉（offers 表）；预测区（全部补货预警表：风险 tag + 建议补货量）。
  - **Pricing**：定价记录表（商品/成本/建议价/利润率 progress）；「重新计算」按钮（calc）；「AI 建议」按钮（suggest）后刷新。
  - **Ads**：汇总卡（总花费/总收入/ROI）；campaigns 表（roi/ctr/cvr 列）；「AI 选词建议」对话框；「预算优化」提交待审批 Action，下方队列支持批准、拒绝和执行（D47）。
  - **Orders**：筛选（平台/状态/关键词）；「同步订单」按钮；状态下拉改状态。
  - **Support**：左侧会话列表（平台 tag + 最后消息摘要）+ 右侧消息时间线；底部输入框回复；「AI 自动回复」按钮。
  - **Workflows**：模板卡片区（三个模板：图标+步骤节点串）→「运行」；运行历史表；详情抽屉：el-steps 展示每步状态/耗时/输出摘要（JSON 前 200 字），运行中每 2s 轮询直到 finished。**调度任务**：类型列支持三种 kind（工作流·key / 趋势扫描 / 主动巡检，由 `kindLabel()` 统一渲染）；新建对话框的类型下拉含「主动巡检」（`alert_scan`），种子数据预置「每 6 小时经营风险巡检」（默认停用，可在表内一键启用）。
  - **Knowledge**：文档 CRUD + 搜索框（/search 高亮结果）。
  - **BI**：「生成 AI 经营报告」按钮 → markdown 纯文本展示（pre-wrap）；利润趋势图（revenue/cost/profit 三线）+ 类目利润条形图；days 切换 7/30/90。
  - **Settings**：LLM 配置表单（api_key 密码框/base_url/model/启用开关，显示 has_key 状态）+ 平台费率表 + 汇率 + 规则参数表单；保存 PUT /ai/settings；AI 调用日志表（GET /ai/logs）。
  - **Alerts**（风险巡检，M3）：4 个级别统计卡（高/中/低/待处理）+ 告警表（级别 tag/告警/详情/规则/状态/确认按钮，支持按级别与状态筛选）+「立即巡检」按钮（POST /alerts/scan）；下方「巡检规则配置」表（级别下拉 + 启用开关即时保存，展示当前阈值）。写操作按 `canWrite()` 隐藏。
  - **AiDecisions**（AI 决策依据，M6）：筛选（Agent / 对象类型）→ 决策表（ID/Agent/动作/对象/判定结果/模型 tag：大模型 or 规则/时间）；点行开抽屉展示 `decision` 与 `evidence` 的 JSON，并单列「判定理由」列表。纯只读。
  - **Discovery 表现分**：右侧「一键 AI 选品」卡下方新增「查商品表现分」区（输入商品 ID → GET /discovery/performance/{id}），展示表现分/窗口/售出与销售额/毛利率与退款率/售罄率；无真实销售时标注「中性分」。
- C1 完成后执行 `npm install`（生成 node_modules 与 lockfile），**不执行 build**（C2 页面可能未完成）。

## 9. 文件归属总表

| 子代理 | 独占文件 |
|---|---|
| A1 | app/agents/discovery.py、app/agents/supplier.py、app/agents/pricing.py |
| A2 | app/agents/listing.py、app/agents/compliance.py、app/agents/support.py、app/agents/orchestrator.py、app/workflows/engine.py |
| B1 | app/routers/auth.py、products.py、discovery.py、suppliers.py、listings.py、compliance.py |
| B2 | app/routers/pricing.py、ads.py、orders.py、support.py、bi.py、workflows.py、knowledge.py、ai.py |
| B3 | app/services/mock_market.py、app/seed.py、app/main.py、tests/test_api.py |
| C1 | frontend/ 全部（package.json、vite.config.js、index.html、src/{main.js,api.js,router.js,styles.css,App.vue,views/*}） |

App.vue 只做 `<router-view/>`。
