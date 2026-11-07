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

Setting 表约定 key：`llm`（见 ai/llm.py DEFAULT_LLM）、`platform_fees`（{"shopee":0.06,"amazon":0.15,"shopify":0.02,"ebay":0.12,"temu":0.05,"tiktok":0.08}）、`fx`（{"USD":7.12,"EUR":7.8}）、`rules`（{"min_margin":0.15,"target_margin":0.35,"logistics_base":18.0,"logistics_per_kg":8.0,"ads_default":1.5}；D58 起另可选配 `payment_fee_rate`/`refund_rate`/`tax_rebate_rate`/`vat_in_rate`/`clearance_fee_cny`/`landed_cost_include_vat`/`destination_compliance_enforce`，默认值均不改变既有口径）。读取方式：`db.get(Setting, key)`，不存在用上述默认。

**跨境到岸成本服务（D58，可直接 import，纯领域计算不建会话）**：

```python
from app.services import duty, logistics, platform_fees, compliance_registry, regions
duty.compute_landed_cost(db, tenant_id, country="DE", hs_code="610910", declared_value_cny=500, qty=1)
#   -> {duty_cny, import_vat_cny, clearance_cny, total_cny, rate_type, rate, rate_source,
#       rate_configured, de_minimis_exempt, estimated, vat_rate, reason, note}
logistics.quote(db, tenant_id, attrs, destination_country="US")   # -> {billing_weight_kg, total_cny, source, breakdown}
platform_fees.resolve(db, tenant_id, "shopee", category="", site="")  # -> {total_rate, source, ...}
compliance_registry.check_evidence(db, tenant_id, product, "DE")  # -> {required, missing, expired, satisfied, passed, blocking}
regions.normalize_country("美国") / regions.region_code("DE")     # -> "US" / "EU"
```

约定：`tenant_id IS NULL` 的配置行是平台内置口径；代码内 `DEFAULT_*` 兜底保证主库未灌数据时仍可用；缺少输入（如未给目的国）时**只降级不静默**——返回显式原因字段而非"看起来正常的 0"。

## 2. 智能体层契约（agents/*）

所有 Agent：构造 `XxxAgent(tenant_id: int)`，支持 `with`；类属性 `name` 指定如下。下列为早期方法清单，数据库访问约束以 Agent OS §18.3 和 `docs/DECISIONS.md` D37~D52 的迁移现状为准。返回**纯 dict/list**（不要返回 ORM 对象）。LLM prompt 用中文+结构化要求，fallback 必须完整可用。

### 2.1 DiscoveryAgent（name="discovery"，文件 agents/discovery.py）
市场发现+选品（对应规划第七章）。当前规则评分含真实经营表现：`total = 0.30*demand + 0.15*(100-competition) + 0.25*profit + 0.10*(100-risk) + 0.20*performance_score`，无真实销售的新品表现取 50。历史 LLM 提示仍使用四维权重，不能把历史四维说明等同规则实际公式。
- `scan_trends() -> dict`：Agent 只经 Product/Market Tool 读取，输出 `REFRESH_BUILTIN_TRENDS` 提案，不直接 upsert。可信调度复核 `product:write` 后经中央 Action 执行器刷新 12 条内置估算；HTTP 保持 `items` 列表返回，聊天与 Workflow 走同一入口。演示来源必须为 builtin，不能覆盖 csv/api；失败整批回滚，同范围恢复原 Action，已变化依据不能借旧成功结果覆盖。（D56 代码及隔离验收完成，主库待部署；最终验收见最新子代理索引。）
- `expand_keywords(keyword: str) -> {"keywords": [str]}`：8-12 个扩展词（类目词+属性词+平台词+长尾组合；LLM 可增强）。
- `score_product(product_id: int) -> dict`：Agent 只经 Tool 返回分析及内部 `_score_analysis/_score_evidence`，不保存评分/决策、不触发表现缓存写入。HTTP 经 `invoke_discovery`、产物服务复核 product:write/可信身份/Workspace/商品归属，在单一事务保存既有 ProductScore + AiDecision，返回真实 score_id 及既有分数字段，内部标记不暴露（D52）。规则依据为趋势、类目密度、属性成本、品牌风险和真实经营表现；LLM 未使用的真实订单输入明确标为 not_used。
- `score_batch(product_ids: list[int])`：产物服务整批原子保存；每项错误显式返回 errors/business_status=blocked，失败批次不新增部分评分，context_patch={}。同 scope 复用原评分与决策，新 scope 可新增；服务端 AiDecision.evidence._persistence 保存来源、身份、scope、score_id 与不可变指纹，不修改历史记录。
- `pick_candidates(limit: int = 3, min_total: float = 60, explore=True, explicit_ids=None)`：未指定商品时只读每商品最新评分，保留探索配额；显式清单经 Orchestrator 评分与持久化，保留 picked_product_ids/context_patch 语义。显式空清单不回退全池；显式选品上限 50、批量评分上限 200，超限/非法 ID 拒绝，不静默截掉或漏项。Workflow discovery.pick_candidates 使用服务端身份及 run/step 范围，缺身份阻断；聊天选品也走同一调度入口。

### 2.2 ProductAgent（name="product"，文件 agents/discovery.py 同文件）

商品标准化（第八章）。`_CJK_CATEGORY_MAP`：关键词→标准类目（家居/3C配件/宠物用品/户外运动/美妆工具/母婴用品/服饰配件/厨房用品）。
- `standardize(product_id: int) -> dict`：Agent 经 Tool 读取，返回内部 `_action_proposal`，不改商品。HTTP 经 `invoke_product` 提交既有 UPDATE_PRODUCT_CONTENT（LOW / product:write / AUTO_SAFE），Executor 复核身份与原始内容，只允许规则类目、weight_kg/material/color 和服务端指纹；保留售价、采购、库存等其他属性。返回执行结果（product_id/category/attrs/dedupe_hash/is_duplicate/duplicate_of）及 action_id/action_status；查重在锁内验证（D51）。
- `standardize_batch(params: dict, context: dict)`：Agent 返回 proposals/errors；Workflow 调度返回 standardized/duplicates/results/errors/business_status/context_patch。范围优先 params.product_ids，其次 context.product_ids；均未指定时取最多 200 个 active 商品，显式空范围不扩散。同范围重放原 Action；服务端清单保存在 Action evidence 与步骤 output，零 Action 失败也能恢复原范围；客户端 `_action_` 键不得冒充。失败批次 blocked 且 context_patch={}，不缩掉失败商品。

### 2.3 SupplierAgent（name="supplier"，文件 agents/supplier.py）
- `match_best(product_id: int) -> dict`：该商品所有 SupplierOffer 按 价格40%+发货时效30%+供应商rating/stability30% 打分选最优，返回 `{"product_id","supplier":{...},"offer":{...},"reason":str}`；无 offer 返回 `{}`。
- `match_best_batch(params, context) -> {"matches":[{"product_id","supplier_id","supplier_name","offer_id","price","ship_days"}], "context_patch":{"offers":{str(pid):{"supplier_id","price","ship_days"}}}}`
- `score_supplier(supplier_id: int) -> dict`：Agent 只读 Tool 并返回评分提案 `{"supplier_id","quality","cost","delivery","stability","total","reasons":[str],"model"}`，不含 `score_id`；SupplierScore 由可信产物服务 `finalize_supplier_scores` 校验分值范围/模型取值/租户归属后原子保存并回填 `score_id`（D57）。quality=rating/5*100；cost=按该供应商 offers 均价相对全站分位；delivery=(14-ship_days)/14*100；stability 原值。total=0.35*quality+0.25*cost+0.2*delivery+0.2*stability。
- `forecast(product_id: int) -> dict`：`{"product_id","title","weekly_demand","onhand","shortage_risk","suggest_restock_qty","trend":[{week,demand} x12],"forecast","backtest","data_quality","features","candidates","_snapshot"}`。销量=近 12 周（84 天）Order(qty) 按周分桶，4 个基线模型（last_week / mean_12w / intermittent / 加权移动平均）滚动回测按 WAPE + 绝对 Bias 选优，仅按已记录促销/缺货做保守校正；onhand 取 attrs.get("onhand",0)；shortage_risk: onhand<1周→high，<2周→mid，否则 low；suggest_restock_qty=max(0, 4周需求-onhand)。Agent 不写库；ForecastSnapshot 由 `finalize_forecast` 保存，`commercial_gate`/`automation_allowed` 由服务端用 `forecast_monitoring` 重算并回填 `snapshot_id`（D57）。
- `forecast_batch(params, context) -> {"forecasts":[forecast dict], "context_patch":{"shortages":[{product_id,title,weekly_demand,onhand,shortage_risk,suggest_restock_qty}]}}`（product_ids 缺省=全部 active 商品）；批量保存逐条宽容（单条失败跳过，与旧语义一致），经 `finalize_forecast_batch` 提交。

### 2.4 PricingAgent（name="pricing"，文件 agents/pricing.py）
真实利润公式（第十一章，D58 扩展）：`profit = price - (purchase_cny + logistics_cny + duty_cny + import_vat_cny + clearance_cny + platform_fee_rate*price*fx + payment_fee_rate*price*fx + refund_rate*(purchase+logistics+duty) - tax_rebate_rate*purchase/(1+vat_in_rate) + ads_cost_cny)/fx`。
- `calc_profit(product_id, price=None, destination_country="", channel_type="", site="", qty=1) -> dict`：既有字段（`product_id`/`purchase_cost`/`logistics_cost`/`platform_fee_rate`/`ads_cost`/`price`/`profit`/`margin`/`currency`/`fx`）保持不变，新增 `hs_code`/`destination_country`/`duty_cost`/`import_vat_cost`/`clearance_cost`/`payment_fee_rate`/`refund_rate`/`tax_rebate_rate`/`landed_cost_applied`/`landed_cost_detail`/`logistics_detail`/`fee_detail`/`cost_total_cny`/`cost_breakdown`（8 项以上）。price 缺省=attrs.get("sale_price")；采购价=最优 SupplierOffer.price（无则 attrs.supplier_price）；物流经 `services/logistics.quote`（命中路由按费率表，否则回退 `rules.logistics_base + logistics_per_kg*weight_kg`）；平台费率经 `services/platform_fees.resolve`（表优先，兜底与旧 `Setting.platform_fees` 一致）；**未给目的国时关税/进口 VAT/清关费为 0、新增费率默认 0，利润数值与旧实现逐分一致**。
- `suggest_price(product_id: int) -> dict`：Agent 只输出分析及内部 `_analysis_record`，id/created_at 为 null；不写 PricingRecord、不修改售价、不生成 Action。成本包含采购、物流和广告；目标价=cost_cny*(1+target_margin)/(fx*(1-fee_rate))，下限=cost_cny*(1+min_margin)/(fx*(1-fee_rate))；需求/竞争作市场修正，非有限 LLM 价格退回规则。HTTP 由 Orchestrator 调用分析产物服务，复核 finance:write、Workspace、身份和商品归属，返回真实 PricingRecord id/created_at；reason._persistence 保存服务端来源与去重键（D50）。
- `suggest_price(product_id: int) -> dict`：Agent 只输出分析及内部 `_analysis_record`，id/created_at 为 null；不写 PricingRecord、不修改售价、不生成 Action。成本包含采购、物流和广告；目标价=cost_cny*(1+target_margin)/(fx*(1-fee_rate))，下限=cost_cny*(1+min_margin)/(fx*(1-fee_rate))；需求/竞争作市场修正，非有限 LLM 价格退回规则。HTTP 由 Orchestrator 调用分析产物服务，复核 finance:write、Workspace、身份和商品归属，返回真实 PricingRecord id/created_at；reason._persistence 保存服务端来源与去重键（D50）。
- `reprice_batch(params, context)`：显式 params.product_ids 优先，其次 context.product_ids；均未提供时读取全部 active 商品，上限 200。返回完整分析列表 repriced 和逐商品 errors，不再静默吞掉分析异常。调度层整批原子保存可用产物，errors 非空时 business_status=blocked，context_patch.pricing_record_ids 返回记录引用。同一服务端范围、Workspace、请求人、商品复用原始快照，不覆盖已保存分析；新请求范围可保存新快照。Workflow 缺少可信发起人时阻断人工恢复。

### 2.5 AdsAgent（name="ads"，文件 agents/pricing.py 同文件）
- `suggest_for_product(product_id: int, platform: str = "facebook") -> dict`：草稿 `{"name","platform","product_id","keywords":[8-12个]（expand_keywords+商品标题词）、"budget","status":"draft","reason":str}`，不落库。
- `draft_batch(params, context)`：Agent 只返回 CREATE_AD_CAMPAIGN_DRAFT 提案（id=null、status=PROPOSED），不创建 AdCampaign。Orchestrator 绑定可信身份，提交 LOW / finance:write / AUTO_SAFE Action；Executor 仅创建本地 draft，日预算限 5～500 USD，不启动投放。返回 campaign_drafts（真实 id、action_id、action_status）与 context_patch.campaign_ids。显式空商品范围不回退全量；完全未提供范围才读取已发布商品。同一服务端工作流范围幂等，失败终态不自动重试（D49）。
- `optimize_budget(campaign_id: int) -> dict`：按 ROI 产出建议：roi>2→预算+30%（上限500），roi<0.8→-40%，0.8-2→维持；返回 `{"campaign_id","old_budget","new_budget","action","reason","roi"}`，**不改预算**。路由将变更建议提交为 HIGH 风险 `ADJUST_AD_BUDGET` Action，审批后由 Executor 写入（D47）。
- `roi_report() -> {"summary":{"total_spend","total_revenue","roi","avg_ctr"},"campaigns":[campaign dict + {"roi","ctr","cvr"}]}`。

### 2.6 ListingAgent（name="listing"，文件 agents/listing.py）

发布/复核安全补充（D53）：共享内容指纹 V2 包含目标平台与商品标题；历史 V1
复核须重新运行，不改历史记录、不自动批准。
- `generate(product_id: int, platform: str = "shopee", language: str = "en") -> dict`：只返回 `CREATE_LISTING_DRAFT` 提案，Agent 不建 Listing 行。保留知识增强、文案自检及模板降级；HTTP/工作流由 Orchestrator 提交并自动执行草稿 Action，返回真实 Listing id、status="draft"、action_id、action_status="SUCCESS"（D48）。
- `optimize(listing_id: int) -> dict`：只返回 `UPDATE_LISTING_CONTENT` 提案；执行器仅允许修改内容未变化的草稿。HTTP 返回执行后 Listing dict 与 Action 引用；已发布内容或陈旧提案返回 409。
- `publish(listing_id: int, shop_id: int | None = None) -> dict`：只返回 `PUBLISH_LISTING` 提案。HTTP 先复核当前内容，提交后返回 `status="PENDING_APPROVAL"`、`action_id`、`approval_required=true`，**不立即上架**。调用 Action approve 后，还必须独立调用 execute；成功结果在 outcome.result。真实/演示/本地发布都需审批；执行时再次核对权限、内容指纹、规则、复核结论及店铺归属。
- `generate_batch(params, context) -> {"listings":[Listing dict], "context_patch":{"listing_ids":[int]}}`：platform/language 取 params（默认 shopee/en），product_ids 取 params 或 context。
- `publish_batch(params, context)`：Agent 保留每项提案，Orchestrator 汇总为 published/pending/blocked；context_patch 包含 pending_action_ids、published_product_ids。有未执行或拒绝动作时 business_status="blocked"，暂停下游。人工执行后 resume 不重跑成功上游；同一范围的拒绝/失败 Action 不被自动换成新提案。

#### 上架复核（D54，ListingReviewAgent）

D61 发布回执增量（2026-10-11）：`GET /api/listings/{listing_id}/publication-attempts` 使用现有 page_num/page_size 分页，校验 Listing 与 Shop 的 tenant 归属并排除归档店铺。每条返回 shop_id/shop_name/external_id/external_object_type/platform_status/verification_status/received_at/can_query_submission，不返回凭证。UI 只查询用户选择的回执所属店铺，不按平台猜第一家店。

D61 店铺范围增量：统一读取既有 membership_data_scopes 的 SHOP_SCOPED.shop_ids；多条受限记录取交集，WORKSPACE_ALL 不覆盖限制，未知类型、空集合或损坏配置拒绝访问。店铺列表和发布回执/Action 队列在分页前过滤；店铺详情操作及发布提案、审批、执行和成功重放校验当前范围。受限成员不能创建未授权的新店铺或执行全 Workspace 演示数据清理。Membership 停用不能回退旧角色，发布执行前同时复核原发起人和批准人的当前权限与范围。此增量不宣称尚未实现的 Launch/资产/同步全链 Scope 已验收。

D61 店铺市场增量：`POST /api/shops` 与 `PUT /api/shops/{id}` 支持 market、store_type、account_type、business_mode、fulfillment_mode；能力证据和 capability_revision 不接受前端写入。market 归一为当前支持的具体国家，空值可保存但阻断真实发布，EU/未知代码返回 422。真实发布只用 Shop.market，不回退到商品国家或 Adapter 第一个市场；准入校验异常同样阻断。店铺上下文及准入结论参与发布审批指纹，修改后必须重新提案。Adapter 另验证目标市场在其声明发布范围内。DROPSHIP/PLATFORM_STOCK/SELF_STOCK/FACTORY_DIRECT 为履约枚举，历史空值不推测。

发布 execute 的 outcome.result 增加 shop_id、attempt_id 和三类事实字段。`status=published` 是旧 API 的提交兼容投影，**不表示 ACTIVE**；真实提交得到 SUBMITTED/PENDING_VERIFICATION，演示为 SUBMITTED/UNKNOWN，本地模拟为 NOT_SUBMITTED/UNKNOWN。母稿三态保持 UNKNOWN；店铺事实读取 PlatformPublishAttempt。Walmart Feed 类型为 SUBMISSION，提交响应的原始 ACTIVE 也不得直接升级为 VERIFIED。已有历史记录默认 UNKNOWN，不自动补造可信回执。

- `review(listing_id, rule_sync=None)`：Agent 只返回分析及内部 `_review_analysis`，无 ORM/规则同步写入。HTTP 经 `invoke_review` 及可信产物服务保存既有 ListingReviewDecision，返回真实 review_id/decision/reasons/rule_version/rule_source/evidence，自动来源元数据不暴露在该响应。
- 普通复核需 listing:write；人工审批入口内部复核需 compliance:approve，合规员仍无发布权限。保存前重验身份、Workspace、租户/商品归属、内容、完整规则、最新报告和人工依据；批次原子保存，陈旧或伪造输出拒绝。
- `review_batch(params, context)`：可信 Workflow 使用原请求者与 run/step 范围，最多 50 个正整数 Listing ID；显式空列表不扩张。返回 approved/blocked/business_status/context_patch；服务端步骤局部清单用于恢复，同范围清单或依据改变返回 409。合法人工确认可解除原人工阻断；明确违规/高风险不能强制覆盖。
- ERP_RULES_URL 配置时由可信服务独立会话同步规则，写入前再次验权；同步失败转人工且其摘要纳入依据。人工审批保留填写依据和禁止编辑人自批，不复制自动来源元数据；旧批准不覆盖新的同步失败或规则/报告变化。
- 单项及批量发布先调用可信复核；新产物在执行发布时验证规则全文和最新报告依据。历史人工结论无新摘要时须重新人工确认，不回填升级；复核不等于批准发布 Action，发布仍需独立审批与执行。

### 2.7 ComplianceAgent（name="compliance"，文件 agents/compliance.py）
- `check(target_type: str, ref_id: int) -> dict`：Agent 只经 Tool 返回内部 `_compliance_analysis`，不创建报告或修改风险副本。HTTP/Workflow 经 `invoke_compliance` 及可信服务，复核 compliance:check、当前身份/Workspace/归属与不可变依据，在同一事务保存既有 ComplianceReport/AiDecision 及 Listing 风险 Action，返回真实报告字段（D55）。检测项（每命中一条计一次扣分）：
  1. 品牌风险：文本含品牌黑名单词（从 KnowledgeDoc 检索"商标黑名单"+内置兜底列表 Apple/iPhone/Samsung/Nike/Adidas/Disney/LEGO/LV/Rolex/Pokemon 等）→ level=high，每词扣50（单一品牌词命中即 high）。
  2. 违禁宣称：最/第一/顶级/ No.1 /cure/FDA approved/杀菌/防癌/100% safe → level=mid，扣15。
  3. 图片风险：images 为空→mid 问题扣15；URL 含 watermark/logo_/_logo/shuiyin→mid 问题扣15。保留旧 Listing images=[] 口径，迁移不偷偷改用关联商品图片。
  4. 平台规则：retrieve() 知识库平台规则相关命中作参考（LLM 模式下作为上下文）。
  score=max(0,100-扣分)；risk_level：score<60→high，<85→mid，else low。suggestions 每个问题给中文整改建议。模型输出须有限、字段合法、不高于规则分数且不低于规则风险；非法、遗漏或 LLM 单独 high 降级规则。Listing.risk_level 仅由 UPDATE_LISTING_COMPLIANCE_RISK（LOW/compliance:check/AUTO_SAFE）执行器投影可信最新报告，不改内容、不授权发布。
- `check_product(product_id)` / `check_listing(listing_id)`：薄封装调 check。
- `check_batch(params, context)`：原始 Agent 只返回 analyses；可信入口返回 reports/business_status/context_patch（risk_high、blocked_product_ids、blocked_listing_ids 及服务端步骤局部 manifest）。最多 100 个不重复目标，显式空清单不扩张；派发前记录原范围，失败恢复不能换目标。任一保存/Action 失败整批回滚，异常显式阻断；有 high 时 business_status=blocked，不继续自动下游。相同 scope 重放原报告并核验最新依据，旧 low 不覆盖新 high；合规只读知识使用 TF，无 ai:read 时明确 builtin/not_used，不扩大知识或发布权限。

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
- **suppliers.py** `/suppliers`：`GET ""` 列表（附最新 score）；`POST ""`；`PUT /{id}`；`GET /{id}` 详情（offers+score）；`POST /{id}/score`（经 `invoke_supplier` 可信派发，需 `supply:write`，产物服务保存）；`POST /match {"product_id"}`（只读匹配，Agent 直调）；`GET /forecast?product_id=`（有 product_id 单品，无则 forecast_batch 全部，均经可信派发并落 ForecastSnapshot）；`GET /offers?product_id=`；`POST /offers`（人工录入，非 Agent 写入）。
- **listings.py** `/listings`：`GET ""?product_id&platform&status&page&page_size`（附 product title）；`POST /generate {"product_id","platform","language"}`；`POST /{id}/optimize`；`POST /{id}/publish`（ValueError→HTTPException 400）；`DELETE /{id}`。
- **compliance.py** `/compliance`：`GET /reports?target_type&ref_id&page&page_size`；`POST /check {"target_type":"product"|"listing","ref_id"}`；`GET /reports/{id}`。

### B2 名下
- **pricing.py** `/pricing`：`GET ""?product_id&page&page_size`（记录列表，附 title）；`POST /calc {"product_id","price"?,"destination_country"?,"channel_type"?,"site"?,"qty"?}`（给出目的国即计入关税/进口 VAT/清关费与路由物流费，响应含 `cost_breakdown` 等 8 项以上明细，D58）；`POST /suggest {"product_id"}`。
- **cross_border.py** `/cross-border`（D58，读 `finance:read` / 写 `finance:write`；`tenant_id IS NULL` 的平台内置行租户只读）：
  - `GET /duty-rates?country=`、`POST /duty-rates`、`PUT|DELETE /duty-rates/{id}`（目的国 × HS 前缀 × 生效期；`rate_type=ad_valorem|fixed_per_item`，欧盟按 HS 子目每件 €3 过渡期）；
  - `GET /logistics-routes`、`POST /logistics-routes`、`PUT|DELETE /logistics-routes/{id}`（计费重 = max(实重, 体积重=长×宽×高/体积系数)，`billing_method=per_kg|per_cbm|per_item` + 燃油/旺季附加）；
  - `GET /platform-fees?platform=`、`POST /platform-fees`、`PUT|DELETE /platform-fees/{id}`（平台 × 类目 × 站点 × 生效期，费率 = 佣金 + 交易手续费 + 服务费）；
  - `GET /compliance-rules?country=`、`POST /compliance-rules`、`PUT|DELETE /compliance-rules/{id}`（目的国 × 类目 × 认证项）；
  - `GET /products/{id}/compliance?country=`（返回 `required/missing/expired/satisfied/passed/blocking`）；`POST /products/{id}/compliance`（登记证据 `{destination_country,requirement,evidence_ref,valid_until}`，按 租户+商品+目的国+认证项 幂等 upsert）；
  - `POST /landed-cost {"product_id","destination_country"?,"price"?,"channel_type"?,"site"?,"qty"?}`（直接转调 `services/costing.calc_profit`，不复制口径）。
  - **口径提示**：四张配置表的 `GET` 会附带未被覆盖的代码兜底参考行（`id=null`、`source="default"`）；`PUT/DELETE` 只能作用于本租户行，平台内置行与参考行一律 404。
- **ads.py** `/ads`：`GET /campaigns`（roi_report 结果）；`POST /campaigns`（草稿/表单创建，可含 id 列表批量）；`POST /campaigns/{id}/optimize` 返回预算建议、`action_id` 与 `PENDING_APPROVAL`，预算不立即改变；`POST /suggest {"product_id","platform"}`。
- **actions.py** `/actions`（D47～D51）：`GET ""?status=&action_type=` 查当前 Workspace 的指定类型 Action，缺省仍为 ADJUST_AD_BUDGET；另支持 PUBLISH_LISTING、CREATE_LISTING_DRAFT、UPDATE_LISTING_CONTENT、CREATE_AD_CAMPAIGN_DRAFT、UPDATE_PRODUCT_CONTENT，权限按服务端目录。`POST /{id}/approve|reject {"note"}` 仅人工审批动作可用；`POST /{id}/execute` 对已批准 Action 幂等执行，复核当前执行人及原请求者的真实权限、租户状态和服务授权。FAILED/REJECTED 不允许重试同一 Action；结果/失败现场保存在 outcome。Listings 页面提供独立发布审批队列。
- **orders.py** `/orders`：`GET ""?platform&status&keyword&shop_id&page&page_size`（**shop_id 范围端到端鉴权见下方 D63 卡片**）；`POST /sync {"platform","count":5}`（gen_order×n，require_write）；`PUT /{id}/status {"status"}`（校验合法值）。
  - **D63 订单列表 shop_id 范围鉴权卡（GET /orders）**
    - 参数：`shop_id: int | None`。不传 → 返回本租户全部订单（B1 默认不变），响应 `scope = {"shop_id": null, "shop_name": null}` 表示「全店」。
    - 归属规则：传入后先用 `services.shop_scope.active_shop(db, user.tenant_id, shop_id)` 解析；该函数对「不存在 / 跨租户(tenant_id 不符) / 已归档(archived_at 非空)」一律返回 None。
    - 状态码：`None` → **404** `店铺不存在或无访问权限`（跨租户、已归档、id 不存在一视同仁，避免泄露目标是否存在）；解析成功但 `role != "sales"`（货源 source 店铺）→ **400** `「{店名}」是 {平台} 货源店铺（source）：货源店铺(source)不能同步销售订单，请选择销售店铺（sales）`（与 CSV 导入路径文案一致）。
    - 通过后仅对 `Order.shop_id == shop_id` 过滤（叠加既有 `tenant_id` 过滤），并回显 `scope = {"shop_id", "shop_name"}` 供前端显示真实范围；既有 `items/total/page/page_size` 键不变。
    - 反模式禁止（D63）：绝不允许「静默忽略 shop_id」或「返回 200 + 空集冒充已筛选」；跨租户一律 404 而非 200+空 / 200+他租户行。
    - 隔离证明：`tests/test_orders_shop_scope.py` 覆盖——同租户双店互相隔离、跨租户 404、货源店 400、无 shop_id 默认全量、富化字段逐行正确、A→B→A 切换无残留泄漏。
- **business_profiles.py** `/business-profile`（D63 经营画像，V9.1 原型 02 服务端持久化）：
  - **D63 经营画像契约卡（GET/PUT /business-profile）**
    - 数据模型：`business_profiles` 表（迁移 `20261018_29`，含真实 downgrade）。一张表两类行：`user_id` 非空 = 个人偏好行（direction / budget_amount / budget_currency），按 (tenant_id, workspace_id, user_id) 唯一；`user_id` 为空 = 空间共享行（target_market / risk），由部分唯一索引 `ix_business_profiles_shared`（WHERE user_id IS NULL）保证 (tenant_id, workspace_id) 唯一。写共享字段复用既有 `workspace:write` 能力 key，未新造权限。
    - 作用域：**服务端 Workspace Context 是唯一事实**（legacy 路径 workspace_id = user.tenant_id）；请求体 Schema 不含 `workspace_id`，客户端多传也会被忽略。测试证明不存在 tenant 之外的孤儿行。
    - `GET ""` → 合并视图：`{direction, budget:{amount,currency}, target_market, risk, completed, completed_at, updated_at, sources:{direction:'USER'|null, target_market:'WORKSPACE'|null, risk:'WORKSPACE'|null}}`。缺失字段一律 `null`，绝不臆造。
    - `PUT ""`（require_write）→ 幂等 upsert：仅写入请求体**显式提供**的字段（`model_fields_set` 区分「显式 null = 清除」与「缺省 = 保持原值」）；等价两次 PUT 命中同一行，仅刷新 `updated_at`。
    - 校验（422 且点名字段）：`budget_amount` 有限数且 ≥0（0.0 是合法零值，与未填 null 严格区分）；`budget_currency` 3 位大写且必须落在已知币种集 = FX 子系统（exchange_rates 本租户 + 平台内置 + Setting('fx') 键）**恒定并入系统基线 {USD, EUR, CNY}**（订单默认 USD、定价 CNY 计价，本位币不因环境未配汇率被拒），基线外未知币种拒绝不静默强制；`risk` ∈ 低/中/高；`target_market` ≤64 字符。
    - `completed` 为**服务端推导**：direction / budget_amount / budget_currency / target_market / risk 全部非空才为 true（判定集中在 `routers/business_profiles.py::is_profile_complete`），客户端声明 `completed:true` 不生效。
    - 错误契约：只读账号（viewer）PUT → 403（require_write）；无 `workspace:write` 写共享字段 → 403；校验失败 → 422 带字段名；无 409（upsert 幂等无冲突态）。
    - 读回证明：`tests/test_business_profile.py` 覆盖——save→GET 读回一致、重新登录（真实 /auth/login 新 token）读回一致、同租户用户 B 不可见用户 A 的个人字段、跨租户（legacy 下即跨工作区）零泄漏、客户端 workspace_id 被忽略且无孤儿行、幂等单行、三类 422 点名字段、completed 服务端推导 + 显式 null 清除、viewer 403。
  - **B3 报价诚实性与选定契约卡（SupplierOffer 扩展 + PUT /products/{id}/selected-offer）**
    - 数据模型（迁移 `20261019_30`，仅加列，含真实 downgrade）：`supplier_offers` 增 `valid_until`（DateTime 可空，None=长期有效）、`source_kind`（String(32)，默认 manual；manual=人工录入即视为已核实来源、scraped/imported=待核实）、`verification_status`（String(24)，默认 unverified；**manual 来源在业务上即视为已核实来源（人工录入可追责），verified 仅平台核验、非工商尽调**）；`products` 增 `selected_offer_id`（Integer 可空，FK `supplier_offers.id`，约束名 `fk_products_selected_offer_id_supplier_offers`）= 用户显式选定的报价。
    - `PUT /products/{product_id}/selected-offer`（require_write）body `{"offer_id": int | null}`：商品不归本租户 → 404 `商品不存在`；offer 缺失/跨租户 → 404 `报价不存在或无访问权限`；`offer.product_id != product_id` → 400 `报价不属于该商品`；null = 显式清除。幂等，200 返回 `{product_id, selected_offer_id, updated_at}`。**选定是 Product 级的「优先采购来源」，不代表每个市场/店铺拥有相同物流、税费与利润**（Store 级利润口径仍由订单真实数据与 costing 元素决定）。
    - **costing 采用选定**：`services/costing.py::best_purchase` 命中 `selected_offer_id`（行存在且匹配租户+商品）时**直接采用其 to_cny 价格与其 offer_id，即使缺货也尊重用户显式选择**（缺货由下游渲染层诚实展示）；未选定/选定失效时回退「在库最低价」并返回该 offer_id——消费方必须按返回的 offer_id 展示「成本依据报价」，**不得把回退结果继续标注为「用户选定」**。
    - **选定失效规则（唯一实现 `services/costing.py::offer_state` → `(state, limits)`，前端禁止自行推断）**：`MISSING`=报价行已删除/跨租户/非本商品 → 选择失效，成本回退最低在库价，`limits` 提示重新比选；`EXPIRED`（`valid_until` 已过）/ `OUT_OF_STOCK`（`in_stock=false`）/ `UNVERIFIED`（`source_kind != manual` 且 `verification_status ∉ {manual,verified}`）→ **保留用户偏好且允许试算**，但 `limits` 明确阻断据此对外报价、采购与上线承诺；`OK`=无限制；未选定为 `null`。已核实口径：`manual` 来源视为人工已核实（可追责），其余来源须 `verification_status` 为 `manual`/`verified`。
    - **成本上下文与口径（`POST /pricing/calc`）**：`CalcIn` 增可选 `shop_id`。给出时必须通过 `services/shop_scope.active_shop` 校验归属：未知/跨租户/已归档 → 404 `店铺不存在或无访问权限`；`role != "sales"`（货源店铺） → 422（货源店不承载销售成本口径）。响应在既有键上增 `shop_id`、`market`、`qty`、`is_generic_estimate`（`shop_id` 为空即通用试算，**不得展示为某店铺确认利润**）、`offer_state`、`offer_limits`（与 overview 同源）。Product 级选定仅是「优先采购来源」，不代表每个 Store 的运费/税费/平台费相同。
    - **市场口径唯一推导（B3 S2 实测修正）**：`market` = 显式 `destination_country` 优先，缺省取该销售店铺的 `Shop.market`；两者皆空才为 `null`。禁止「选了店铺却回显 market=null」——否则到岸成本（关税/进口 VAT/清关）静默不计，成本口径空转。前端只展示 `market`，不得自行从店铺推断。
    - **本位币不计汇率（展示口径）**：`shared/money.js::renderMoney` 对 `CNY`（`BASE_CURRENCY`）不再附加「汇率未知」；仅外币缺 `fxDate` 时才标注。给本位币标「汇率未知」属假缺项，会误导用户以为成本不可算。
    - **店铺 DTO 适配唯一入口**：`GET /shops` 返回 `shop_name`/`role`，壳层组件读 `name`/`type` → 一律经 `shared/storeScope.js::toShellShop` 归一（`workspaceShell.loadShops` 内调用）。跳过该层会导致下拉框只剩数字 id、且货源店铺（`role=source`）被当销售店铺列出。
    - `GET /suppliers/offers?product_id=` 富化（向后兼容，`items` 键不变）：每项增 `valid_until / source_kind / verification_status / is_selected` + 嵌套 `supplier {id,name,region,supplier_type,verification_status,rating,certifications,capabilities}`（批量加载无 N+1）；顶层增 `selected_offer_id`。`POST /offers`（OfferIn）增可选 `valid_until`（可解析性校验，422 点名字段）、`source_kind`、`verification_status`（值域 manual/verified/unverified/scraped，越界 422）。
    - `cost_completeness(db, tenant_id, product)` → `(missing, complete)`：`purchase`=无在库报价且 attrs.supplier_price 缺失（costing 将退化为 10.0 占位价）、`fx`=非 CNY 报价缺折算汇率、`hs_code`=无 HS 编码（关税按兜底税率估算）。供 overview 与前端诚实展示「成本缺项」。
    - 隔离与读回证明：`tests/test_selected_offer.py` 覆盖——save→overview.supply+offers.is_selected 读回一致、重新登录读回一致、costing 采用选定（offer_id 断言）、跨租户 404、跨商品 400、显式 null 清除、幂等双 PUT、OfferIn 新字段 roundtrip + 422 点名、供应商富化存在。
  - **B3 商品概览聚合契约卡（GET /api/products/{product_id}/overview）**
    - 顶层键固定：`{product, supply, channels, performance, stage, generated_at}`；商品不归本租户 → 404。
    - `supply`：`{offers_count, selected_offer_id, selected_offer_price_cny(选定报价折 CNY，失效/未选为 null), min_offer_price_cny(**真正的最低在库价**，`best_purchase(honor_selection=False)`——绝不被选定覆盖，供与选定价对比), cost_missing:[str], cost_complete:bool, selected_offer_missing:bool(选定悬空=true，直库损坏防御信号；= state 为 MISSING), selected_offer_state:str|null(OK/EXPIRED/OUT_OF_STOCK/UNVERIFIED/MISSING，唯一实现 costing.offer_state), selected_offer_limits:[str](可直接展示的阻断原因，OK/未选为空数组), cost_offer_id:int|null(成本引擎实际采用的报价=选定优先)}`。
    - `channels`：**直接调用 `launch_dto.channels_dto`（与 GET /products/{id}/channels 同一实现，零 SQL 复制）**；上下文/渲染异常时降级为空渠道，绝不让 overview 500。多店铺状态独立（AC-12.1/12.3 沿用）。
    - `performance`：复用 `product_performance.read_performance`，`has_data` 为假或异常时为 **null（绝不臆造 0/演示数据）**。
    - `stage`：可解释阶梯 `{key, label, reasons:[中文]}`——`NO_SUPPLY`（0 报价且 0 已核验素材）→ `SUPPLY_READY`（≥1 报价）→ `CHANNEL_PENDING`（有报价无渠道）→ `LAUNCHING`（有渠道未在售）→ `OPERATING`（有真实订单表现）。每次跃迁必须由真实字段支撑，商品行存在≠完成。
    - 列表信号：`GET /api/products` 每项增 `signals: {offers_count, channels_count, assets_verified_count}`（3 条 GROUP BY 批量聚合，无 N+1），既有键不变；前端 signals 缺失时显示「—」不编造阶段。
    - 聚合证明：`tests/test_product_overview.py` 覆盖——顶层键精确、channels 形状与端点一致、阶梯进阶、多店独立不互相覆盖、performance 空安全、列表批量计数。

- **support.py** `/support`：`GET /conversations?status&page&page_size`（附 last message + buyer_name）；`POST /conversations {"platform","buyer_name","content",?order_id,?product_id}`（创建会话+首条 buyer 消息）；`GET /conversations/{id}`（含 messages）；`POST /conversations/{id}/reply {"content"}`（operator 回复）；`POST /conversations/{id}/auto_reply`（SupportAgent）；`POST /conversations/{id}/close`。
- **bi.py** `/bi`：
  - `GET /dashboard -> {"gmv","orders","profit","ad_spend","roi","refund_rate","active_listings","open_conversations","sales_trend":[{date,gmv,orders}×30],"category_dist":[{category,revenue}],"platform_dist":[{platform,revenue}],"top_products":[{product_id,title,units,revenue}×5],"recent_runs":[run dict×5]}`
  - `GET /profit?days=30 -> {"days","series":[{date,revenue,cost,profit,margin}],"summary":{...}}`
  - `GET /report -> {"report": str, "generated_at"}`（AI 经营报告：组装 KPI 数据 ask_json 生成 markdown，失败用模板文案）
- **workflows.py** `/workflows`：`GET /templates`；`POST /run {"template_key","context"?}`（require_write → start_run 返回 run dict+steps）；`GET /runs?limit=20`（倒序）；`GET /runs/{id}`（run+steps）。D61 增量：这些旧入口仅处理 flow_kind=LEGACY_AUTOMATION，详情/恢复/模板解析拒绝 PLATFORM_LAUNCH；创建调度、种子模板修补、旧领取/续租/恢复和 BI 运行列表同样隔离。历史类型由 20261012_24 安全默认保留，不把旧 success 视为平台 ACTIVE。

D61 Profile 服务（尚未开放 HTTP）：`backend/app/workflows/profiles.py` 在现有 WorkflowTemplate 上创建/编辑草稿、发布不可变版本、退役及按可信 Shop/Product 选择；事务由调用方提交。草稿更新与发布要求 expected_hash，已发布内容不可改；同 key/version 数据库唯一，读取时校验定义摘要。全域 OWNER 管理定义，查询和选择复核 Context/Store Scope。按匹配维度精度排序、同 family 选最新匹配发布版，多 family 同级歧义返回 PROFILE_AMBIGUOUS；CONTRACT_TEST 和 PRODUCTION 严格分选。定义快照只证明规则内容，不能证明平台已经授权或商品在售。后续 Launch 路由还需正式 launch 权限及实例状态机，当前旧 Workflow API 不暴露这些定义。
- **schedules.py** `/schedules`（D56）：读列表；创建/修改/删除/`POST /{id}/run` 需 `ai:write`，趋势绑定/执行另验 `product:write`。创建/显式启用由服务器保存真实 requested_by/workspace_id，不接受客户端身份；代客绑定/触发拒绝。历史无身份、撤权或归属变化显式失败。手动/定时共同条件领取，正在执行返回 409；异步工作流为 dispatched（detail 含 run# 与状态），不是最终成功，须查对应 run；崩溃 running 租约未自动回收，需人工核查。结构变更需显式 Alembic 20261001_19，主库本批未升级。
- **knowledge.py** `/knowledge`：`GET /docs?keyword&page&page_size`；`POST /docs`；`PUT /docs/{id}`；`DELETE /docs/{id}`；`GET /search?q=&top_k=4`（knowledge.retrieve）。
- **ai.py** `/ai`：`GET /settings`（llm+platform_fees+fx+rules，api_key 脱敏为 bool `has_key`）；`PUT /settings`（admin；body 任意子集，llm 走 set_llm_config，其余 upsert Setting）；`POST /chat {"message"}`（OrchestratorAgent.chat，require_write）；`GET /logs?limit=50 -> {"items":[...]}`（倒序）；`GET /decisions?subject_type&subject_id&agent&limit=50`（M6 决策依据链，`{"items","total"}`，每条含 `decision` + `evidence`）。
- **alerts.py** `/alerts`（M3 主动巡检，**只告警不执行**）：`GET ""?status&level&limit=100 -> {"items","returned","total","counts":{high,mid,low,open}}`。**级别排序在 SQL 内完成后再 limit**（high 优先，避免高风险被大量低风险挤出结果）；`total` 是**符合条件的总数**（不受 limit 影响，供分页用），`returned` 才是本次返回条数；`counts` 走数据库聚合，同样不受 limit 影响。`PUT /{id}/ack`（require_write，标记已处理，不删除）；`GET /rules -> {"items":[...]}`（9 条，首次访问自动初始化）；`PUT /rules/{id}`（require_write，`{enabled?,level?,threshold?}`，threshold 按 key 合并）；`POST /scan`（require_write，手动触发一轮，返回 `{created,skipped,by_rule,scanned_at}`）。

### 只读 BFF（workbench，D-后端，UX-04a）

- **workbench.py** `/workbench`（`backend/app/routers/workbench.py`，随 `main.py` 的 `prefix="/api"` 注册）：**只读聚合**，仅 `GET`，不写库、不新增表/迁移、不新增写端点。聚合实现落 `backend/app/services/workbench.py`，**只组合既有 `services/`、`workflows/` 函数**（`launch_list.list_launches`、`commercial_analytics.metric_summary`/`quality_report`、`alerting.list_alerts`、`action_queue`、`review_outputs.review_queue_count`、`open_1688.get_config`），不重写其 SQL。
  - `GET /workbench/todo?limit=50&include_history=false` → `{"items":[{"type":"launch|action|alert|review","title","count","severity":"low|mid|high","due_at","route":{"path","return_to"},"ref"}],"counts":{"launch","action","alert","review"},"generated_at","partial","sources":{"launch","action","alert","review"}}`。`route.return_to` **仅取白名单** `/launch|/listings|/products|/shops`（与 `frontend/src/utils/navigationReturn.js` 同源），否则 `null`。
  - `GET /workbench/overview?limit=50` → `{"sections":{"metrics","in_progress","top_today","need_human","ai_done","exceptions"},"data_quality","persona":null,"next_actions","signals","generated_at","partial","sources":{"bi","launch","alert","review","workflow","todo"}}`。
  - **鉴权（逐源）**：未持某源读权限 → 该源 `skipped`（从结果剔除，不报错）；单源失败 → 端点仍 **200**，`partial=true`、`sources[源]="failed"`，对应 section 缺省。`COMPLIANCE` 投影剥离价格/库存动作（复用 `backend/app/workflows/launch_action_catalog.py` 的 `PRICE_STOCK_ACTIONS`，不新造口径）；`FACTORY_COLLABORATOR` 返回空待办（`items` 空、`sources` 全 `skipped`）。
  - **`signals`（`derived:true, authoritative:false`）**：`has_sales_shop`/`sales_shop_count`/`has_factory`/`factory_match_count`/`has_1688_credential`/`member_count`/`order_count_30d`；任一键无权限/不可得即 `null` 且 `partial=true`，**不猜测、不默认填值**；`has_1688_credential` 仅返回存在性布尔，**绝不返回密钥值**。
  - **单一实现重构（消除内联查询重复）**：`GET /listings/review-queue` 的查询抽到 `backend/app/services/review_outputs.py`（`review_queue`/`review_queue_count`）；`GET /actions` 的查询抽到 `backend/app/services/action_queue.py`——router 与 BFF 共用同一实现。两端点既有响应结构与语义不变。

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

D61 Launch 创建内部服务（尚未开放 HTTP）：`app/workflows/launch_records.py` 将店铺派生 Listing、固定版本 Run、步骤和 LaunchCreated 事件置于同一调用方事务；服务不提交，调用方回滚则全部消失。SQLite 显式开启外层写事务后才用保存点，避免 SAVEPOINT 提前提交。tenant/product/shop 活跃槽数据库唯一；相同幂等键同请求重放、不同请求拒绝；新鲜 Context/Store Scope 每次重验。派生稿清空历史审批/回执，发布目标只能是绑定店铺。八项 launch 权限按冻结角色矩阵增量授予，COMPLIANCE 不获得通用写入权限，工厂不获得通用 Launch 权限。已有 Launch 时演示数据清理返回 409，保留审计。此阶段仅创建 NOT_STARTED/PENDING，不提供动作执行、状态迁移或在售核验。

D61 就绪刷新内部服务（未开放 HTTP）：`refresh_launch(db, ctx, run_id, expected_revision)` 要求 launch:manage、新鲜身份及店铺范围，校验固定定义/步骤和经营上下文；过期 revision 返回 REVISION_CONFLICT，定义损坏或上下文变化拒绝。刷新不执行发布、采购或核验，不提升平台/验证状态；相同结果不生成重复事件，状态与事件由调用方统一提交。动作与事实服务接入前不能将 READY 理解为已经完成或允许自动发布。

D61 Product Asset：GET /api/products/{id}/assets 要求 shop_id，采用 page_num/page_size（上限 200）返回版本历史；POST 同路径要求 shop_id、asset_key、expected_version（新建为 0）、类型、URI、内容摘要、权利状态、来源及适用市场/平台。OWNED 需明确来源，授权/许可状态还必须附 rights_evidence_ref；登记不直接 VERIFIED，也不强制第二人审批所有自有素材。POST /api/products/{id}/assets/{asset_id}/verify 另需 compliance:approve、expected_version、decision（VERIFIED/REJECTED）、evidence_ref 和 reason；提交人与核验者必须不同，核验追加版本。所有入口重验 Context/Store Scope，不接收客户端 Workspace 身份；URI 仅登记、不触发下载，日期统一 UTC。素材版本、授权有效期与核验结果进入真实发布门禁及审批指纹；缺记录、权利未知、受限、缺授权证明、审核驳回或过期均拒绝。

S3 Action 契约（列表/详情/回执/能力矩阵）：`GET /api/actions` 的 `action_type` 与 `status` 省略或传 `ALL` 表示全部；`action_type` 只接受 `action_system.HANDLERS` 已注册类型，未知类型/状态返回 400。分页主口径为 `page_num/page_size`，`limit` 仅作旧调用兼容；响应固定 `{items,total,page_num,page_size}`，`total` 是筛选后总数而非当页条数。「全部」口径自动收窄为当前身份持权类型集合（PUBLISH_LISTING 另受店铺范围约束），只读身份查全部返回 403 而不是空列表。`GET /api/actions/{id}` 返回含 `agent_type/required_permission/created_at/updated_at` 的单条详情，`GET /api/actions/{id}/result` 返回 `{status,outcome,terminal,executed_by,executed_at}`，无结果时 `outcome={}`、`terminal=false`，不伪造成功。`GET /api/ai/capabilities` 是能力边界的唯一口径：逐动作给 `enabled/blocked_reasons/handler_registered/risk/approval_required/required_permission`，来源为 `POLICIES+HANDLERS+CONTRACTS+WorkspaceContext+StoreScope`，只读不含凭证；前端不得自行推断能力或渲染未注册动作。审批入参统一为 `note`（拒绝接口同样收 `note`，前端 `reason` 必须映射为 `note`）；对免审批动作调用 approve 返回 409「此 Action 不需要人工审批」。执行前服务端复核 agent/permission/risk/approval/target_type/execution_mode 与策略一致，不一致 409；需审批动作缺 `approved_by` 拒绝执行。服务启动时把 `updated_at` 早于 10 分钟的 `EXECUTING` 收敛为 `FAILED`（`outcome.recovered_on_startup=true`），在途执行不动，收敛后可重试。

S4 AI 内部闭环契约（来源标注与重复请求）：Agent 的 `ask_json` 必须返回 `(result, mode)`，`mode` 只能是 `llm`/`rule`；模型不可用、超时或返回非 dict/空对象时降级规则引擎，并在 `AiLog` 留一条 `mode=llm, ok=false` 记录（不得只留 rule 日志）。`UPDATE_PRODUCT_CONTENT` 的 Action 证据必须包含 `source`（`llm`/`rule`）与 `model_mode`，供前端与审计区分「大模型建议」与「规则引擎结果」；无 key 时一律 `rule`，禁止标成 llm。单商品直接标准化（无 `scope_manifest`）在目标值与最近一次 SUCCESS 完全一致时复用该 Action 并返回 `idempotent_replay=true`，不再新建第二个写动作；比较对象是 `payload` 去掉 `before` 后的目标值（`before.updated_at` 每次不同，不能参与相等判断）。批量/工作流入口必须各自落 Action 以保存 `scope_manifest`，不复用。高风险动作（如 `ADJUST_AD_BUDGET`）固定 `PENDING_APPROVAL`，拒绝后业务对象不得变化且不可再执行（409），通过后执行一次，重复执行幂等且不得二次写入。

S5 订单详情与成本口径契约：`GET /api/orders/{id}` 返回 `{order, lines, fees:{items,total_by_currency}, purchases:{items,total_by_currency,link,note}, refunds, fulfillment, totals, source}`，`order` 内含 `shop_name/product_title`。范围与身份每次重验：`resolve_workspace_context` + `resolve_store_scope(...).require(order.shop_id)`，跨租户与不存在一律 404（不借 403/404 差异探测他人订单）；只读身份可看详情，发货仍要求 `order:write`。口径三条硬约束：① `order.amount/cost/profit` 是**订单币种原值**，服务端不做汇率换算（`source.honesty` 明示）；② 采购单是供应商 CNY 应付，只出现在 `purchases` 与 `totals.purchases_by_currency`，**与订单成本不是同一口径、不得相加或换算**（`purchases.note` 固化说明，`mixed_currency` 标记订单币种≠CNY 且存在应付）；③ 平台结算走 `GET /api/finance/settlement-reconciliation` 独立对账，不并入订单详情（`totals` 无 settlement 字段）。`fees` 按币种汇总且不冲减 `amount`。物流轨迹未接入，`fulfillment.tracking_available` 恒为 `false`，只回 `tracking_no`，响应中不得出现 `events/trajectory` 等伪造轨迹字段。前端订单详情抽屉按 `id` 重新 `GET /orders/{id}`，不复用列表行、不把订单 ID 复制进 URL 或第二个请求参数。演示数据清理必须处理 `products.selected_offer_id ↔ supplier_offers.product_id` 外键环：删除 `supplier_offers` 前先置空本租户商品的 `selected_offer_id`（`_CYCLE_BREAKS` 登记），否则真实存在选定报价时会 500。

P0-2 平台状态摄入契约（`POST /api/launch/{run_id}/sync` 的 `mode` 扩展）：原 `mode` 仅接受 `refresh`，现增加 `platform_status`。请求体在 `mode`/`expected_revision` 之外新增 `raw_status`（≤256）、`source`（`API`/`MANUAL`/`DEMO`，默认 `MANUAL`）、`source_time`（平台侧时间，可选）、`external_reference`（≤128）、`source_revision`（≥0，用于乱序丢弃）。旧客户端只传 `mode`+`expected_revision` 时行为不变；`platform_status` 仍不是入参（`extra=forbid`），无法直写状态。响应 `{refreshed:false, changed, platform_status, raw_status, error, revision, launch}`。

`raw_status` 经 Profile 定义的 `status_mapping.statuses` 映射为 `platform_status`：先精确匹配、再大小写不敏感回退；未注册或映射到非 `PLATFORM_STATES` 的值一律 `UNKNOWN` + `error=PLATFORM_ERROR`，**保持原状态且不涨 revision**。`source_revision` 不大于上次已处理序号时 `error=STALE_EVENT`，只记审计事件、不回退状态。合法迁移显式枚举，`ACTIVE` **不在任何迁移目标内**——摄入永远不能置在售，在售只能由 `CONFIRM_ACTIVATION` 独立核验（仍需材料引用、备注、核验人独立）。本入口**不改 `verification_status`**：平台接受（`ACCEPTED`）不等于已核验在售。每次摄入在 `platform_publish_attempts` 留痕 `raw_status`/`source`/`source_time`/`received_at`/`external_reference`/`source_revision`/`mapping_version`，并写 `PlatformStatusChanged` / `PlatformStatusUnmapped` / `PlatformStatusStaleIgnored` 事件。

P0-3 多轮历史读契约（同一销售对象仅一个活跃槽）：`GET /api/launch` 默认只返回 `active_slot == 1` 的活跃轮次；带 `include_history=true` 才返回历史轮次。列表 DTO 的 `is_history` 是 `active_slot is None` 的投影，是**判断活跃/历史的唯一权威字段**——列表项**不含** `active_slot`、`status`、`round_no`，前端不得自造。`previous_run_id` 只在详情 DTO 中，列表侧拿不到，因此前端轮次编号的口径固定为「同一 `product_id + shop_id` 内按 `created_at` 升序（同时间用 `id` 兜底）」，不是 `previous_run_id` 链。分页默认 `page_size=20`、上限 200，轮次超过一页时编号会失真，取数方必须显式放大 `page_size`，并在 `total` 大于返回条数时把截断显式暴露，不得静默编号。语义红线：**活跃槽只表示占位，ACTIVE / PAUSED 都不释放它**，所以「有活跃槽」不等于「已上线」；只在 CANCEL / END 时写 `ended_at` 并置 `active_slot=None`。

P0-4 阻断补齐入口契约：每个 `blocker` 必须三要素齐全——`code`（状态模型 §6 固定枚举）、非空 `message`、`repair_action`，**禁止 `repair_action: null`**（裸 409 不再允许）。`repair_action` 固定为 `{kind, label, path, action, connected, reason}`：`kind ∈ {ROUTE, ACTION, UNAVAILABLE}`；`path` 必须以 `/app` 开头且指向前端已挂真实组件的路由（占位页不得作为入口）；`ACTION` 时 `action` 为该步骤可执行的 Launch 动作名；`connected=false` 表示该补齐动作背后的领域服务尚未接入（B03–B09），此时 `reason` 必填且前端必须同屏展示「未接入」，不得只画一个点不动的按钮。`kind=UNAVAILABLE` 前端不提供跳转。未知阻断码一律给兜底待办入口而非空值。低价门禁的事实来源是**本地利润试算**（`services/costing.calc_profit` 的 `margin` 与租户设置 `min_margin`，默认 0.15，事实投影为 `facts.pricing.{price,margin,min_margin,target_margin,margin_ok}`），**不是**平台核价轮次；这门禁只回答「这个价能不能报」，**不能**据此声称已核价——「已核价」自 M2-A 起由 `price_rounds` 评审轮次提供（见下条 M2-A 契约卡）。算不出利润时 `facts.pricing` 缺省，条件求值为 UNKNOWN，步骤按「缺少进入条件资料」阻断，不得默认放行。

M2-A 核价轮次契约：`price_rounds` 是**只增不改**的报价历史（`round_no` 按 `(tenant_id, product_id)` 递增 + 唯一约束兜底），服务层不提供任何 update/delete。三个动作的分工固定：`REPORT_PRICE`/`COUNTER_PRICE` 必填 `price` + `currency`（3 位字母，**空币种一律 422，禁止默认 USD**）；`ACCEPT_PRICE` 无必填，接受**最新评审轮**且在受理前按当前成本重算。低价（`margin < min_margin`）一律 `409 ACTION_PRECONDITION_FAILED` + `PRICE_UNACCEPTABLE` 阻断项，**零写入**。毛利口径只有一个实现：`costing.calc_profit`（非 USD 先折人民币再折 USD，缺汇率 fail-closed）。成本快照以 `cost_fingerprint` 判定「是否还是当前成本」：采购价 / 报价来源 offer / 汇率 / 佣金率 / 成本合计 / 毛利门槛任一变化即失配，`cost_snapshot_current` 转 false，已完成的核价**重新阻断**——不是一次性通过永久生效。事实投影为 `facts.pricing.{review_id, review_round_no, price, currency, margin, min_margin, margin_ok, quote_action, decision}`：没有轮次就不给 `review_id`，条件求值 UNKNOWN，`PRICE_REVIEW` 保持未完成，**不得**凭空造一个 review_id。**红线**：本系统没有核价适配器，`REPORT_PRICE` 不写外部引用，`PRICE_REVIEW` 完成只代表本地评审记录成立，**不等于平台已接受价格**；定价页只读轮次（`GET /pricing/rounds`），写入口仅限 Launch 动作，避免「谁批的、依据哪份成本」断链。
