# 项目目录与开发维护导览

> 更新日期：2026-10-29。本文基于当前工作区实际文件生成，含未提交改动；为导航文档，不替代架构契约或验收报告。
> 范围：完整列出 Git 管理及未忽略的工作区文件；依赖、缓存、数据库、备份和构建产物不展开。源码说明取自模块文档字符串；无说明时仅标注文件类别，避免臆测。
> 验证边界：本次未启动服务、未运行业务测试、未访问外部平台；文件存在不等于功能验收通过。

## 阅读目录

1. [项目定位与架构](#项目定位与架构)
2. [目录职责](#目录职责)
3. [业务功能与维护入口](#业务功能与维护入口)
4. [开发维护流程](#开发维护流程)
5. [部署与未完成边界](#部署与未完成边界)
6. [完整文件目录](#完整文件目录)
7. [后端模块介绍索引](#后端模块介绍索引)
8. [HTTP 接口声明索引](#http-接口声明索引)
9. [文档介绍索引](#文档介绍索引)

## 项目定位与架构

AI 原生跨境电商经营平台。Python/FastAPI 后端、SQLAlchemy 数据层、Vue 3 前端，提供商品发现、货源、商品资料、合规、上架、订单、售后、财务和 AI 运营能力。

请求通常由 routers 接收，业务能力落在 services；AI 路径经 Orchestrator 编排领域 Agent，通过 Tool 读取业务事实，写入走 Action 策略、权限、风险与审批。以上是目标架构，存量迁移是否完成须看架构与进度记录，不表示全仓已满足全部分层约束。

入口：`backend/app/main.py`；模型：`backend/app/models.py`；配置：`backend/app/config.py`；数据库连接：`backend/app/db.py`。启动生命周期会初始化数据库、处理种子数据、启动调度并恢复未完成任务，因此不可为只读审计随意启动生产实例。

## 目录职责

|目录|作用与维护要求|
|---|---|
|backend/app/routers|HTTP 边界：身份校验、输入输出与接口注册|
|backend/app/services|业务规则、事务、动作执行、工作空间与平台集成|
|backend/app/services/adapters|平台协议适配；逐平台核验支持范围和真实验收|
|backend/app/agents|领域 AI 能力与 Orchestrator；禁止领域 Agent 自由互调|
|backend/app/tools|Agent 数据读取契约、权限与审计|
|backend/app/ai|模型协议、知识检索基础设施|
|backend/app/workflows|通用工作流与 Launch 状态、动作、恢复机制|
|backend/migrations|数据库版本迁移；已执行迁移只增不改|
|backend/scripts|运维、备份、预检、验收；运行前确认副作用|
|backend/tests|后端业务、安全、恢复、隔离与契约回归|
|frontend/src|旧前端：views 页面、router 路由、组件与权限|
|frontend-v9/src|新前端：pages 页面、features 业务、api 接口、shells 外壳、shared 公用能力|
|docs|活文档、架构、契约、设计与进度；archive 为历史材料，evidence 为验收证据|
|.github|持续集成配置|
|backend/erp.db|本地业务数据库，禁止入库；修改前冷备|
|node_modules、dist、缓存目录|依赖或生成物，禁止作为业务源码维护|
|_erp_backups、backend/backups|冷备数据，禁止提交|

## 业务功能与维护入口

|业务|后端路由模块（backend/app/routers/）|关联实现与核验重点|
|---|---|---|
|身份与租户|auth、admin、me|auth.py、workspace_context、权限矩阵；核验跨租户/店铺范围|
|经营准备|business_profiles、workbench|经营画像持久化、工作台聚合、V9 起步链路|
|商品与市场|products、discovery、product_channels、product_assets|商品、渠道与素材；区分真实数据/演示/模型估算|
|货源与工厂|suppliers、factory_network|报价、工厂供给、供应商评分；核验选定货源与权限|
|Listing 与合规|listings、compliance|生成、复核、素材权利、规则与发布前门禁|
|上线中心|launch|workflows/launch_*；状态不等于真实平台已上架|
|渠道店铺|shops|授权、同步与平台适配；检查店铺归档和范围过滤|
|订单履约|orders、purchases、settlements|订单、采购、结算；核验库存/金额/币种及范围|
|售后客服|refunds、support、knowledge|退款、客服、知识检索；真实发送需单独验收|
|经营优化|pricing、ads、alerts|分析、广告与风险；分析结果不能当作外部执行结果|
|财务分析|finance、bi、cross_border|收入费用、经营统计、跨境到岸成本|
|AI 执行|ai、actions|Orchestrator、策略、审批、执行、幂等与回执|
|自动化|workflows、schedules|状态机、调度身份、失败恢复与重试|

前端定位方法：先在新前端 app 路由中查 URL，再查 pages/features，沿 API domain 找后端路由。旧前端入口为 frontend/src/router.js。避免仅修改旧页面后误认为新版同步生效。

## 开发维护流程

- 开工：读 AGENTS.md、CODE_AND_DIRECTORY_STANDARD.md，确认 Git 状态与回滚点；保留他人未提交改动。
- 接口变更：同步 CONTRACT.md、前端调用与 DTO、对应测试；业务规则放 services。
- AI 能力：先读 AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md；不得绕过 Workspace Context 与 Action 治理。
- 权限变更：同步 test_security.py 权限矩阵，并覆盖越权、跨租户、跨店与代客场景。
- 数据库变更：先冷备与 migration_preflight.py；新增 Alembic 版本和可用 downgrade，回填幂等。
- 页面变更：确认实际服务的前端身份，检查加载/空/错误/无权/成功状态及回跳上下文。
- 提交：只加入本任务文件，git add --dry-run 核对，禁止混入数据库、日志、缓存、备份。
- 文档变更：同步 DOCUMENT_MAP.md；决策写 DECISIONS.md，历史报告放 archive。

以下命令用于验证，会产生测试/构建产物；先确认测试库隔离，不应指向主库。请在对应目录分别执行。

```powershell
# backend：后端回归与静态检查
python -m pytest -q
python -m ruff check .
# frontend 或 frontend-v9：分别验证，不能互相替代
npm test
npm run build
```

可运行结论需额外执行 backend/scripts/e2e_feasibility.py；容器/构建链路改动执行 docker_feasibility.py；TLS 改动执行 tls_feasibility.py。脚本可能启动进程或容器，先阅读参数、隔离和清理机制。测试数字以实际执行结果为准，历史 baseline.json 不代表当前通过数量。

## 部署与未完成边界

- 同仓保留 frontend 与 frontend-v9；默认后端配置仍使用旧产物，ERP_FRONTEND_DIST 可切换。
- 当前根 Dockerfile 构建 frontend；新版源码存在不代表容器部署了新版。
- /api/build-info 返回实际前端身份、产物存在性和构建信息；排查界面不更新时先查它。
- 平台适配器存在不等于授权/发布/拉单全部完成真实店铺验收；逐项检查 limitations 与验收证据。
- V9 文档明确保留物流轨迹、AI 会话持久化、工厂订单结算等未接能力边界；以后以最新实现和证据更新。
- Launch 有流程编排和界面，不应将本地契约样本成功扩称真实商业全链路完成。
- 当前工作区已有其他未提交业务改动；本导览是工作区快照，不是发布版本清单。

## 完整文件目录

以下按目录排列全部可见项目交付文件；未忽略的新文件也纳入。文件名是导航证据，不是能力完成证明。

### `./`

- [.dockerignore](../.dockerignore)
- [.env.example](../.env.example)
- [.gitattributes](../.gitattributes)
- [.gitignore](../.gitignore)
- [.zcodeignore](../.zcodeignore)
- [AGENTS.md](../AGENTS.md)
- [CONTRIBUTING.md](../CONTRIBUTING.md)
- [Caddyfile](../Caddyfile)
- [Dockerfile](../Dockerfile)
- [README.md](../README.md)
- [docker-compose.tls.yml](../docker-compose.tls.yml)
- [docker-compose.yml](../docker-compose.yml)
- [docker-entrypoint.sh](../docker-entrypoint.sh)

### `.github/workflows/`

- [ci.yml](../.github/workflows/ci.yml)

### `backend/`

- [alembic.ini](../backend/alembic.ini)
- [pyproject.toml](../backend/pyproject.toml)
- [pytest.ini](../backend/pytest.ini)
- [requirements-dev.lock.txt](../backend/requirements-dev.lock.txt)
- [requirements-dev.txt](../backend/requirements-dev.txt)
- [requirements.lock.txt](../backend/requirements.lock.txt)
- [requirements.txt](../backend/requirements.txt)

### `backend/app/`

- [__init__.py](../backend/app/__init__.py)
- [auth.py](../backend/app/auth.py)
- [config.py](../backend/app/config.py)
- [db.py](../backend/app/db.py)
- [main.py](../backend/app/main.py)
- [models.py](../backend/app/models.py)
- [pagination.py](../backend/app/pagination.py)
- [proxy_headers.py](../backend/app/proxy_headers.py)
- [secure_types.py](../backend/app/secure_types.py)
- [seed.py](../backend/app/seed.py)
- [serialize.py](../backend/app/serialize.py)

### `backend/app/agents/`

- [__init__.py](../backend/app/agents/__init__.py)
- [base.py](../backend/app/agents/base.py)
- [capabilities.py](../backend/app/agents/capabilities.py)
- [compliance.py](../backend/app/agents/compliance.py)
- [contracts.py](../backend/app/agents/contracts.py)
- [discovery.py](../backend/app/agents/discovery.py)
- [factory_opportunity.py](../backend/app/agents/factory_opportunity.py)
- [listing.py](../backend/app/agents/listing.py)
- [listing_review.py](../backend/app/agents/listing_review.py)
- [orchestrator.py](../backend/app/agents/orchestrator.py)
- [pricing.py](../backend/app/agents/pricing.py)
- [supplier.py](../backend/app/agents/supplier.py)
- [support.py](../backend/app/agents/support.py)

### `backend/app/ai/`

- [__init__.py](../backend/app/ai/__init__.py)
- [knowledge.py](../backend/app/ai/knowledge.py)
- [llm.py](../backend/app/ai/llm.py)

### `backend/app/routers/`

- [__init__.py](../backend/app/routers/__init__.py)
- [actions.py](../backend/app/routers/actions.py)
- [admin.py](../backend/app/routers/admin.py)
- [ads.py](../backend/app/routers/ads.py)
- [ai.py](../backend/app/routers/ai.py)
- [alerts.py](../backend/app/routers/alerts.py)
- [auth.py](../backend/app/routers/auth.py)
- [bi.py](../backend/app/routers/bi.py)
- [business_profiles.py](../backend/app/routers/business_profiles.py)
- [compliance.py](../backend/app/routers/compliance.py)
- [cross_border.py](../backend/app/routers/cross_border.py)
- [discovery.py](../backend/app/routers/discovery.py)
- [factory_network.py](../backend/app/routers/factory_network.py)
- [finance.py](../backend/app/routers/finance.py)
- [knowledge.py](../backend/app/routers/knowledge.py)
- [launch.py](../backend/app/routers/launch.py)
- [listings.py](../backend/app/routers/listings.py)
- [me.py](../backend/app/routers/me.py)
- [orders.py](../backend/app/routers/orders.py)
- [pricing.py](../backend/app/routers/pricing.py)
- [product_assets.py](../backend/app/routers/product_assets.py)
- [product_channels.py](../backend/app/routers/product_channels.py)
- [products.py](../backend/app/routers/products.py)
- [purchases.py](../backend/app/routers/purchases.py)
- [refunds.py](../backend/app/routers/refunds.py)
- [schedules.py](../backend/app/routers/schedules.py)
- [settlements.py](../backend/app/routers/settlements.py)
- [shops.py](../backend/app/routers/shops.py)
- [suppliers.py](../backend/app/routers/suppliers.py)
- [support.py](../backend/app/routers/support.py)
- [workbench.py](../backend/app/routers/workbench.py)
- [workflows.py](../backend/app/routers/workflows.py)

### `backend/app/services/`

- [__init__.py](../backend/app/services/__init__.py)
- [action_content.py](../backend/app/services/action_content.py)
- [action_identity.py](../backend/app/services/action_identity.py)
- [action_policy.py](../backend/app/services/action_policy.py)
- [action_publish.py](../backend/app/services/action_publish.py)
- [action_queue.py](../backend/app/services/action_queue.py)
- [action_records.py](../backend/app/services/action_records.py)
- [action_system.py](../backend/app/services/action_system.py)
- [ad_campaigns.py](../backend/app/services/ad_campaigns.py)
- [agent_outputs.py](../backend/app/services/agent_outputs.py)
- [ai_actions.py](../backend/app/services/ai_actions.py)
- [alerting.py](../backend/app/services/alerting.py)
- [asset_rights.py](../backend/app/services/asset_rights.py)
- [asset_schema.py](../backend/app/services/asset_schema.py)
- [commercial_analytics.py](../backend/app/services/commercial_analytics.py)
- [compliance_analysis.py](../backend/app/services/compliance_analysis.py)
- [compliance_facts.py](../backend/app/services/compliance_facts.py)
- [compliance_outputs.py](../backend/app/services/compliance_outputs.py)
- [compliance_registry.py](../backend/app/services/compliance_registry.py)
- [compliance_risk.py](../backend/app/services/compliance_risk.py)
- [costing.py](../backend/app/services/costing.py)
- [discovery_outputs.py](../backend/app/services/discovery_outputs.py)
- [duty.py](../backend/app/services/duty.py)
- [inventory_service.py](../backend/app/services/inventory_service.py)
- [knowledge_learning.py](../backend/app/services/knowledge_learning.py)
- [logistics.py](../backend/app/services/logistics.py)
- [membership_service.py](../backend/app/services/membership_service.py)
- [mock_market.py](../backend/app/services/mock_market.py)
- [open_1688.py](../backend/app/services/open_1688.py)
- [outcome_attribution.py](../backend/app/services/outcome_attribution.py)
- [pii_redact.py](../backend/app/services/pii_redact.py)
- [platform_adapters.py](../backend/app/services/platform_adapters.py)
- [platform_fees.py](../backend/app/services/platform_fees.py)
- [platform_rules.py](../backend/app/services/platform_rules.py)
- [platforms.py](../backend/app/services/platforms.py)
- [pricing_outputs.py](../backend/app/services/pricing_outputs.py)
- [product_assets.py](../backend/app/services/product_assets.py)
- [product_outputs.py](../backend/app/services/product_outputs.py)
- [product_performance.py](../backend/app/services/product_performance.py)
- [product_standardization.py](../backend/app/services/product_standardization.py)
- [publish_gate.py](../backend/app/services/publish_gate.py)
- [regions.py](../backend/app/services/regions.py)
- [review_analysis.py](../backend/app/services/review_analysis.py)
- [review_outputs.py](../backend/app/services/review_outputs.py)
- [schedule_identity.py](../backend/app/services/schedule_identity.py)
- [scheduler.py](../backend/app/services/scheduler.py)
- [scraper.py](../backend/app/services/scraper.py)
- [settings_service.py](../backend/app/services/settings_service.py)
- [shop_scope.py](../backend/app/services/shop_scope.py)
- [store_scope.py](../backend/app/services/store_scope.py)
- [supply_outputs.py](../backend/app/services/supply_outputs.py)
- [tenant_data_purge.py](../backend/app/services/tenant_data_purge.py)
- [trend_candidates.py](../backend/app/services/trend_candidates.py)
- [trend_refresh.py](../backend/app/services/trend_refresh.py)
- [trend_source.py](../backend/app/services/trend_source.py)
- [workbench.py](../backend/app/services/workbench.py)
- [workspace_context.py](../backend/app/services/workspace_context.py)

### `backend/app/services/adapters/`

- [ali1688.py](../backend/app/services/adapters/ali1688.py)
- [base.py](../backend/app/services/adapters/base.py)
- [catmap.py](../backend/app/services/adapters/catmap.py)
- [contract.py](../backend/app/services/adapters/contract.py)
- [ebay.py](../backend/app/services/adapters/ebay.py)
- [lazada.py](../backend/app/services/adapters/lazada.py)
- [planned.py](../backend/app/services/adapters/planned.py)
- [registry.py](../backend/app/services/adapters/registry.py)
- [shopee.py](../backend/app/services/adapters/shopee.py)
- [tiktok.py](../backend/app/services/adapters/tiktok.py)
- [walmart.py](../backend/app/services/adapters/walmart.py)

### `backend/app/tools/`

- [__init__.py](../backend/app/tools/__init__.py)
- [audit.py](../backend/app/tools/audit.py)
- [base.py](../backend/app/tools/base.py)
- [compliance.py](../backend/app/tools/compliance.py)
- [contract.py](../backend/app/tools/contract.py)
- [conversation.py](../backend/app/tools/conversation.py)
- [finance.py](../backend/app/tools/finance.py)
- [knowledge.py](../backend/app/tools/knowledge.py)
- [listing.py](../backend/app/tools/listing.py)
- [market.py](../backend/app/tools/market.py)
- [memory.py](../backend/app/tools/memory.py)
- [order.py](../backend/app/tools/order.py)
- [product.py](../backend/app/tools/product.py)
- [registry.py](../backend/app/tools/registry.py)
- [store.py](../backend/app/tools/store.py)
- [supply.py](../backend/app/tools/supply.py)

### `backend/app/workflows/`

- [__init__.py](../backend/app/workflows/__init__.py)
- [conditions.py](../backend/app/workflows/conditions.py)
- [contract_profiles.py](../backend/app/workflows/contract_profiles.py)
- [engine.py](../backend/app/workflows/engine.py)
- [kinds.py](../backend/app/workflows/kinds.py)
- [launch_access.py](../backend/app/workflows/launch_access.py)
- [launch_action_catalog.py](../backend/app/workflows/launch_action_catalog.py)
- [launch_actions.py](../backend/app/workflows/launch_actions.py)
- [launch_dto.py](../backend/app/workflows/launch_dto.py)
- [launch_facts.py](../backend/app/workflows/launch_facts.py)
- [launch_handlers.py](../backend/app/workflows/launch_handlers.py)
- [launch_list.py](../backend/app/workflows/launch_list.py)
- [launch_nba.py](../backend/app/workflows/launch_nba.py)
- [launch_plan.py](../backend/app/workflows/launch_plan.py)
- [launch_records.py](../backend/app/workflows/launch_records.py)
- [launch_recovery.py](../backend/app/workflows/launch_recovery.py)
- [launch_rules.py](../backend/app/workflows/launch_rules.py)
- [launch_runtime.py](../backend/app/workflows/launch_runtime.py)
- [launch_state.py](../backend/app/workflows/launch_state.py)
- [launch_submit.py](../backend/app/workflows/launch_submit.py)
- [profile_schema.py](../backend/app/workflows/profile_schema.py)
- [profiles.py](../backend/app/workflows/profiles.py)
- [transactions.py](../backend/app/workflows/transactions.py)

### `backend/migrations/`

- [env.py](../backend/migrations/env.py)
- [script.py.mako](../backend/migrations/script.py.mako)

### `backend/migrations/versions/`

- [20260922_01_commercial_finance_baseline.py](../backend/migrations/versions/20260922_01_commercial_finance_baseline.py)
- [20260922_02_factory_supply_network.py](../backend/migrations/versions/20260922_02_factory_supply_network.py)
- [20260922_03_factory_opportunity_economics.py](../backend/migrations/versions/20260922_03_factory_opportunity_economics.py)
- [20260922_04_supplier_offer_currency.py](../backend/migrations/versions/20260922_04_supplier_offer_currency.py)
- [20260922_05_outcome_attribution.py](../backend/migrations/versions/20260922_05_outcome_attribution.py)
- [20260922_06_reliable_publish_dropship.py](../backend/migrations/versions/20260922_06_reliable_publish_dropship.py)
- [20260923_07_workspace_identity_expand.py](../backend/migrations/versions/20260923_07_workspace_identity_expand.py)
- [20260923_08_workspace_identity_backfill.py](../backend/migrations/versions/20260923_08_workspace_identity_backfill.py)
- [20260923_09_users_nullable_workspace.py](../backend/migrations/versions/20260923_09_users_nullable_workspace.py)
- [20260923_10_setting_scope.py](../backend/migrations/versions/20260923_10_setting_scope.py)
- [20260923_11_shop_archive.py](../backend/migrations/versions/20260923_11_shop_archive.py)
- [20260924_12_ai_native_capabilities.py](../backend/migrations/versions/20260924_12_ai_native_capabilities.py)
- [20260924_13_trend_source.py](../backend/migrations/versions/20260924_13_trend_source.py)
- [20260924_14_knowledge_candidates.py](../backend/migrations/versions/20260924_14_knowledge_candidates.py)
- [20260924_15_compliance_check_permission.py](../backend/migrations/versions/20260924_15_compliance_check_permission.py)
- [20260924_16_tenant_id_foreign_keys.py](../backend/migrations/versions/20260924_16_tenant_id_foreign_keys.py)
- [20260927_17_support_read_permission.py](../backend/migrations/versions/20260927_17_support_read_permission.py)
- [20260930_18_ai_actions.py](../backend/migrations/versions/20260930_18_ai_actions.py)
- [20261001_19_schedule_identity.py](../backend/migrations/versions/20261001_19_schedule_identity.py)
- [20261001_20_cross_border_cost.py](../backend/migrations/versions/20261001_20_cross_border_cost.py)
- [20261001_21_warehouses_inventory.py](../backend/migrations/versions/20261001_21_warehouses_inventory.py)
- [20261011_22_publication_states.py](../backend/migrations/versions/20261011_22_publication_states.py)
- [20261011_23_shop_context.py](../backend/migrations/versions/20261011_23_shop_context.py)
- [20261012_24_workflow_kind.py](../backend/migrations/versions/20261012_24_workflow_kind.py)
- [20261012_25_workflow_profiles.py](../backend/migrations/versions/20261012_25_workflow_profiles.py)
- [20261012_26_launch_runtime.py](../backend/migrations/versions/20261012_26_launch_runtime.py)
- [20261012_27_launch_permissions.py](../backend/migrations/versions/20261012_27_launch_permissions.py)
- [20261012_28_product_assets.py](../backend/migrations/versions/20261012_28_product_assets.py)
- [20261018_29_business_profiles.py](../backend/migrations/versions/20261018_29_business_profiles.py)
- [20261019_30_offer_selection.py](../backend/migrations/versions/20261019_30_offer_selection.py)

### `backend/qa/`

- [r32_seed.py](../backend/qa/r32_seed.py)

### `backend/scripts/`

- [audit_shop_roles.py](../backend/scripts/audit_shop_roles.py)
- [backup_restore_drill.py](../backend/scripts/backup_restore_drill.py)
- [check_docs_consistency.py](../backend/scripts/check_docs_consistency.py)
- [cleanup_probe_data.py](../backend/scripts/cleanup_probe_data.py)
- [docker_feasibility.py](../backend/scripts/docker_feasibility.py)
- [e2e_feasibility.py](../backend/scripts/e2e_feasibility.py)
- [git_bundle_backup.py](../backend/scripts/git_bundle_backup.py)
- [launch_e2e.py](../backend/scripts/launch_e2e.py)
- [live_acceptance.py](../backend/scripts/live_acceptance.py)
- [migrate.py](../backend/scripts/migrate.py)
- [migration_preflight.py](../backend/scripts/migration_preflight.py)
- [platform_contract_sandbox.py](../backend/scripts/platform_contract_sandbox.py)
- [project_goal_acceptance.py](../backend/scripts/project_goal_acceptance.py)
- [refresh_test_baseline.py](../backend/scripts/refresh_test_baseline.py)
- [security_data_audit.py](../backend/scripts/security_data_audit.py)
- [tls_feasibility.py](../backend/scripts/tls_feasibility.py)

### `backend/tests/`

- [__init__.py](../backend/tests/__init__.py)
- [action_helpers.py](../backend/tests/action_helpers.py)
- [asset_helpers.py](../backend/tests/asset_helpers.py)
- [conftest.py](../backend/tests/conftest.py)
- [migration_helpers.py](../backend/tests/migration_helpers.py)
- [test_action_contract.py](../backend/tests/test_action_contract.py)
- [test_action_system.py](../backend/tests/test_action_system.py)
- [test_ad_draft_actions.py](../backend/tests/test_ad_draft_actions.py)
- [test_admin_bootstrap_password.py](../backend/tests/test_admin_bootstrap_password.py)
- [test_agent_contracts.py](../backend/tests/test_agent_contracts.py)
- [test_agent_layer_boundaries.py](../backend/tests/test_agent_layer_boundaries.py)
- [test_ai_action_migration.py](../backend/tests/test_ai_action_migration.py)
- [test_ai_native_p0.py](../backend/tests/test_ai_native_p0.py)
- [test_ai_native_p1.py](../backend/tests/test_ai_native_p1.py)
- [test_ai_native_p2.py](../backend/tests/test_ai_native_p2.py)
- [test_api.py](../backend/tests/test_api.py)
- [test_backup_restore_drill.py](../backend/tests/test_backup_restore_drill.py)
- [test_business_profile.py](../backend/tests/test_business_profile.py)
- [test_cleanup_probe_data.py](../backend/tests/test_cleanup_probe_data.py)
- [test_commercial_data_integrity.py](../backend/tests/test_commercial_data_integrity.py)
- [test_compliance_keyword_invariants.py](../backend/tests/test_compliance_keyword_invariants.py)
- [test_compliance_outputs.py](../backend/tests/test_compliance_outputs.py)
- [test_cross_border.py](../backend/tests/test_cross_border.py)
- [test_deep_domains.py](../backend/tests/test_deep_domains.py)
- [test_discovery_outputs.py](../backend/tests/test_discovery_outputs.py)
- [test_docs_consistency.py](../backend/tests/test_docs_consistency.py)
- [test_e2e_copy_migration.py](../backend/tests/test_e2e_copy_migration.py)
- [test_identity_snapshot.py](../backend/tests/test_identity_snapshot.py)
- [test_launch_actions.py](../backend/tests/test_launch_actions.py)
- [test_launch_api.py](../backend/tests/test_launch_api.py)
- [test_launch_nba.py](../backend/tests/test_launch_nba.py)
- [test_launch_publication_migration.py](../backend/tests/test_launch_publication_migration.py)
- [test_launch_publication_schema.py](../backend/tests/test_launch_publication_schema.py)
- [test_launch_records.py](../backend/tests/test_launch_records.py)
- [test_launch_recovery.py](../backend/tests/test_launch_recovery.py)
- [test_launch_rules.py](../backend/tests/test_launch_rules.py)
- [test_launch_runtime_migration.py](../backend/tests/test_launch_runtime_migration.py)
- [test_launch_state.py](../backend/tests/test_launch_state.py)
- [test_listing_actions.py](../backend/tests/test_listing_actions.py)
- [test_membership_write.py](../backend/tests/test_membership_write.py)
- [test_migration_preflight.py](../backend/tests/test_migration_preflight.py)
- [test_order_detail.py](../backend/tests/test_order_detail.py)
- [test_orders.py](../backend/tests/test_orders.py)
- [test_orders_shop_scope.py](../backend/tests/test_orders_shop_scope.py)
- [test_pii_redact.py](../backend/tests/test_pii_redact.py)
- [test_platform_adapters.py](../backend/tests/test_platform_adapters.py)
- [test_platform_adapters_split.py](../backend/tests/test_platform_adapters_split.py)
- [test_pricing_outputs.py](../backend/tests/test_pricing_outputs.py)
- [test_product_asset_migration.py](../backend/tests/test_product_asset_migration.py)
- [test_product_assets.py](../backend/tests/test_product_assets.py)
- [test_product_overview.py](../backend/tests/test_product_overview.py)
- [test_product_standardization.py](../backend/tests/test_product_standardization.py)
- [test_profile_definition.py](../backend/tests/test_profile_definition.py)
- [test_publish_gate.py](../backend/tests/test_publish_gate.py)
- [test_publish_gate_failclosed_qa.py](../backend/tests/test_publish_gate_failclosed_qa.py)
- [test_publish_intent_store.py](../backend/tests/test_publish_intent_store.py)
- [test_publish_market_scope.py](../backend/tests/test_publish_market_scope.py)
- [test_publish_store_receipts.py](../backend/tests/test_publish_store_receipts.py)
- [test_qa_r31c_j1_e2e.py](../backend/tests/test_qa_r31c_j1_e2e.py)
- [test_review_fingerprint.py](../backend/tests/test_review_fingerprint.py)
- [test_review_outputs.py](../backend/tests/test_review_outputs.py)
- [test_role_permissions.py](../backend/tests/test_role_permissions.py)
- [test_schedule_identity_migration.py](../backend/tests/test_schedule_identity_migration.py)
- [test_security.py](../backend/tests/test_security.py)
- [test_selected_offer.py](../backend/tests/test_selected_offer.py)
- [test_setting_scope.py](../backend/tests/test_setting_scope.py)
- [test_shop_archive_and_purge.py](../backend/tests/test_shop_archive_and_purge.py)
- [test_shop_commerce_context.py](../backend/tests/test_shop_commerce_context.py)
- [test_shop_context_migration.py](../backend/tests/test_shop_context_migration.py)
- [test_store_scope.py](../backend/tests/test_store_scope.py)
- [test_supply_outputs.py](../backend/tests/test_supply_outputs.py)
- [test_supply_sales_guard.py](../backend/tests/test_supply_sales_guard.py)
- [test_tenant_id_foreign_keys.py](../backend/tests/test_tenant_id_foreign_keys.py)
- [test_tls_proxy_config.py](../backend/tests/test_tls_proxy_config.py)
- [test_tool_layer.py](../backend/tests/test_tool_layer.py)
- [test_trend_actions.py](../backend/tests/test_trend_actions.py)
- [test_warehouses_inventory.py](../backend/tests/test_warehouses_inventory.py)
- [test_workbench.py](../backend/tests/test_workbench.py)
- [test_workflow_kind.py](../backend/tests/test_workflow_kind.py)
- [test_workflow_kind_migration.py](../backend/tests/test_workflow_kind_migration.py)
- [test_workflow_profile_migration.py](../backend/tests/test_workflow_profile_migration.py)
- [test_workflow_profiles.py](../backend/tests/test_workflow_profiles.py)
- [test_workspace_context.py](../backend/tests/test_workspace_context.py)
- [test_workspace_context_api.py](../backend/tests/test_workspace_context_api.py)
- [test_workspace_dual_read.py](../backend/tests/test_workspace_dual_read.py)
- [test_workspace_identity_migration.py](../backend/tests/test_workspace_identity_migration.py)

### `docs/`

- [PROJECT_DIRECTORY_GUIDE.md](../docs/PROJECT_DIRECTORY_GUIDE.md)（本文）
- [AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md](../docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md)
- [AI原生能力升级方案.md](../docs/AI原生能力升级方案.md)
- [CODE_AND_DIRECTORY_STANDARD.md](../docs/CODE_AND_DIRECTORY_STANDARD.md)
- [CONTRACT.md](../docs/CONTRACT.md)
- [DECISIONS.md](../docs/DECISIONS.md)
- [DOCUMENT_MAP.md](../docs/DOCUMENT_MAP.md)
- [FRONTEND_API_ALIGNMENT.md](../docs/FRONTEND_API_ALIGNMENT.md)
- [FRONTEND_DESIGN_SYSTEM.md](../docs/FRONTEND_DESIGN_SYSTEM.md)
- [FRONTEND_IMPLEMENTATION_PLAN.md](../docs/FRONTEND_IMPLEMENTATION_PLAN.md)
- [FRONTEND_INFORMATION_ARCHITECTURE.md](../docs/FRONTEND_INFORMATION_ARCHITECTURE.md)
- [FRONTEND_PAGE_MATRIX.md](../docs/FRONTEND_PAGE_MATRIX.md)
- [FRONTEND_R3_APP_SHELL_DESIGN_BASELINE.md](../docs/FRONTEND_R3_APP_SHELL_DESIGN_BASELINE.md)
- [FRONTEND_R3_BACKEND_CAPABILITY_MAP.md](../docs/FRONTEND_R3_BACKEND_CAPABILITY_MAP.md)
- [FRONTEND_R3_PAGE_OWNERSHIP_MATRIX.md](../docs/FRONTEND_R3_PAGE_OWNERSHIP_MATRIX.md)
- [FRONTEND_R3_TASK_CONTRACT.md](../docs/FRONTEND_R3_TASK_CONTRACT.md)
- [FRONTEND_USER_JOURNEYS.md](../docs/FRONTEND_USER_JOURNEYS.md)
- [FRONTEND_UX_ACCEPTANCE.md](../docs/FRONTEND_UX_ACCEPTANCE.md)
- [FRONTEND_UX_AUDIT.md](../docs/FRONTEND_UX_AUDIT.md)
- [FRONTEND_UX_PROGRESS.md](../docs/FRONTEND_UX_PROGRESS.md)
- [FRONTEND_V9_ACCEPTANCE.md](../docs/FRONTEND_V9_ACCEPTANCE.md)
- [FRONTEND_V9_API_MAPPING.md](../docs/FRONTEND_V9_API_MAPPING.md)
- [FRONTEND_V9_BLUEPRINT_R1_GAP_ANALYSIS.md](../docs/FRONTEND_V9_BLUEPRINT_R1_GAP_ANALYSIS.md)
- [FRONTEND_V9_BLUEPRINT_R1_TASK_BREAKDOWN.md](../docs/FRONTEND_V9_BLUEPRINT_R1_TASK_BREAKDOWN.md)
- [FRONTEND_V9_CONTRACTS.md](../docs/FRONTEND_V9_CONTRACTS.md)
- [FRONTEND_V9_DESIGN_SYSTEM.md](../docs/FRONTEND_V9_DESIGN_SYSTEM.md)
- [FRONTEND_V9_IMPLEMENTATION_PLAN.md](../docs/FRONTEND_V9_IMPLEMENTATION_PLAN.md)
- [FRONTEND_V9_MASTER_DESIGN.md](../docs/FRONTEND_V9_MASTER_DESIGN.md)
- [FRONTEND_V9_NAVIGATION.md](../docs/FRONTEND_V9_NAVIGATION.md)
- [FRONTEND_V9_PAGE_MATRIX.md](../docs/FRONTEND_V9_PAGE_MATRIX.md)
- [FRONTEND_V9_PROGRESS.md](../docs/FRONTEND_V9_PROGRESS.md)
- [FRONTEND_V9_RUNTIME_VERIFICATION.md](../docs/FRONTEND_V9_RUNTIME_VERIFICATION.md)
- [FRONTEND_V9_USER_JOURNEYS.md](../docs/FRONTEND_V9_USER_JOURNEYS.md)
- [FRONTEND_V9_VISUAL_ACCEPTANCE.md](../docs/FRONTEND_V9_VISUAL_ACCEPTANCE.md)
- [INCREMENT_DESIGN_LAUNCH_P0_CLOSURE.md](../docs/INCREMENT_DESIGN_LAUNCH_P0_CLOSURE.md)
- [INCREMENT_PRD_LAUNCH_P0_CLOSURE.md](../docs/INCREMENT_PRD_LAUNCH_P0_CLOSURE.md)
- [LAUNCH_CENTER_PRODUCT_DESIGN.md](../docs/LAUNCH_CENTER_PRODUCT_DESIGN.md)
- [M4客服知识自进化方案与论证.md](../docs/M4客服知识自进化方案与论证.md)
- [PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md](../docs/PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md)
- [PLATFORM_COMMERCE_WORKFLOW_GAP_ANALYSIS.md](../docs/PLATFORM_COMMERCE_WORKFLOW_GAP_ANALYSIS.md)
- [PLATFORM_WORKFLOW_E2E_MATRIX.md](../docs/PLATFORM_WORKFLOW_E2E_MATRIX.md)
- [PLATFORM_WORKFLOW_MIGRATION_PLAN.md](../docs/PLATFORM_WORKFLOW_MIGRATION_PLAN.md)
- [PLATFORM_WORKFLOW_PROGRESS.md](../docs/PLATFORM_WORKFLOW_PROGRESS.md)
- [PLATFORM_WORKFLOW_STATE_MODEL.md](../docs/PLATFORM_WORKFLOW_STATE_MODEL.md)
- [PROJECT_MASTER_PLAN.md](../docs/PROJECT_MASTER_PLAN.md)
- [UI_REFACTOR_BLUEPRINT.md](../docs/UI_REFACTOR_BLUEPRINT.md)
- [UI_REFACTOR_BLUEPRINT_R3.md](../docs/UI_REFACTOR_BLUEPRINT_R3.md)
- [V9_1_DIRECTORY_AND_FILE_PLAN.md](../docs/V9_1_DIRECTORY_AND_FILE_PLAN.md)
- [V9_1_NEXT_EXECUTION_PLAN.md](../docs/V9_1_NEXT_EXECUTION_PLAN.md)
- [WORKSPACE_MIGRATION_PROGRESS.md](../docs/WORKSPACE_MIGRATION_PROGRESS.md)
- [backup_restore_runbook.md](../docs/backup_restore_runbook.md)
- [baseline.json](../docs/baseline.json)
- [class-diagram.mermaid](../docs/class-diagram.mermaid)
- [phase1_interfaces.md](../docs/phase1_interfaces.md)
- [phase1_setting_scope_design.md](../docs/phase1_setting_scope_design.md)
- [sequence-diagram.mermaid](../docs/sequence-diagram.mermaid)
- [子代理实施索引-20260923.md](../docs/子代理实施索引-20260923.md)
- [子代理实施索引-20260930.md](../docs/子代理实施索引-20260930.md)
- [权限体系问题排查与专家探讨.md](../docs/权限体系问题排查与专家探讨.md)
- [角色权限体系梳理方案.md](../docs/角色权限体系梳理方案.md)
- [角色界面差异化设计方案.md](../docs/角色界面差异化设计方案.md)
- [需求分析与详细设计说明书V8.0.md](../docs/需求分析与详细设计说明书V8.0.md)
- [页面操作权限对照表.md](../docs/页面操作权限对照表.md)
- [项目介绍与功能地图.md](../docs/项目介绍与功能地图.md)

### `docs/adr/`

- [0003-llm-dual-mode.md](../docs/adr/0003-llm-dual-mode.md)
- [0007-shop-archive-soft-delete.md](../docs/adr/0007-shop-archive-soft-delete.md)
- [0018-git-version-control.md](../docs/adr/0018-git-version-control.md)
- [0022-tls-trusted-proxy.md](../docs/adr/0022-tls-trusted-proxy.md)
- [0023-factory-account-context.md](../docs/adr/0023-factory-account-context.md)
- [0024-frontend-permission-fail-closed.md](../docs/adr/0024-frontend-permission-fail-closed.md)
- [0026-membership-write-side.md](../docs/adr/0026-membership-write-side.md)
- [0061-platform-commerce-workflow.md](../docs/adr/0061-platform-commerce-workflow.md)
- [README.md](../docs/adr/README.md)

### `docs/archive/`

- [20261001-D58-跨境成本与E2E验收.md](../docs/archive/20261001-D58-跨境成本与E2E验收.md)
- [DEVELOPMENT_SUMMARY_2026-10-14.md](../docs/archive/DEVELOPMENT_SUMMARY_2026-10-14.md)
- [FRONTEND_DESIGN_AUDIT_2026-10-18.md](../docs/archive/FRONTEND_DESIGN_AUDIT_2026-10-18.md)
- [PRODUCTION_READINESS_PROGRESS.md](../docs/archive/PRODUCTION_READINESS_PROGRESS.md)
- [README.md](../docs/archive/README.md)
- [UI_REFACTOR_BLUEPRINT.md](../docs/archive/UI_REFACTOR_BLUEPRINT.md)
- [V9_1_AI_DEVELOPMENT_PROMPTS_2026-10-18.md](../docs/archive/V9_1_AI_DEVELOPMENT_PROMPTS_2026-10-18.md)
- [WORKSPACE_CAPABILITY_REFACTOR_AUDIT.md](../docs/archive/WORKSPACE_CAPABILITY_REFACTOR_AUDIT.md)
- [WORKSPACE_REFACTOR_PROGRESS.md](../docs/archive/WORKSPACE_REFACTOR_PROGRESS.md)
- [final_architecture_assessment.md](../docs/archive/final_architecture_assessment.md)
- [phase1_ledger_reconcile_report.md](../docs/archive/phase1_ledger_reconcile_report.md)
- [phase1_migration_abc_design.md](../docs/archive/phase1_migration_abc_design.md)
- [phase1_migration_safety.md](../docs/archive/phase1_migration_safety.md)
- [production-gap-analysis.md](../docs/archive/production-gap-analysis.md)
- [全量商用化整改方案.md](../docs/archive/全量商用化整改方案.md)
- [子代理实施索引-20260922.md](../docs/archive/子代理实施索引-20260922.md)
- [官方平台验收运行手册.md](../docs/archive/官方平台验收运行手册.md)
- [当前项目能力与后续开发报告-20260922.md](../docs/archive/当前项目能力与后续开发报告-20260922.md)

### `docs/evidence/R3-1A/`

- [01-product-detail.png](../docs/evidence/R3-1A/01-product-detail.png)
- [01b-product-detail-asset-shop.png](../docs/evidence/R3-1A/01b-product-detail-asset-shop.png)
- [02-channels.png](../docs/evidence/R3-1A/02-channels.png)
- [03-channels-shops-detail.png](../docs/evidence/R3-1A/03-channels-shops-detail.png)
- [browser-verify.mjs](../docs/evidence/R3-1A/browser-verify.mjs)

### `docs/evidence/R3-1B/`

- [01-product-detail-register.png](../docs/evidence/R3-1B/01-product-detail-register.png)
- [02-product-detail-verify-gate.png](../docs/evidence/R3-1B/02-product-detail-verify-gate.png)
- [03-launch-detail-actions.png](../docs/evidence/R3-1B/03-launch-detail-actions.png)
- [browser-verify.mjs](../docs/evidence/R3-1B/browser-verify.mjs)
- [probe-shape.mjs](../docs/evidence/R3-1B/probe-shape.mjs)
- [probe-shape2.mjs](../docs/evidence/R3-1B/probe-shape2.mjs)
- [probe.txt](../docs/evidence/R3-1B/probe.txt)
- [probe2.txt](../docs/evidence/R3-1B/probe2.txt)
- [probe3.txt](../docs/evidence/R3-1B/probe3.txt)

### `docs/evidence/R3-1C/`

- [qa-j1-e2e-log.txt](../docs/evidence/R3-1C/qa-j1-e2e-log.txt)
- [qa-j1-e2e-report.md](../docs/evidence/R3-1C/qa-j1-e2e-report.md)

### `docs/evidence/R3-2-QA/`

- [01-login-landed.png](../docs/evidence/R3-2-QA/01-login-landed.png)
- [02-home-storeowner.png](../docs/evidence/R3-2-QA/02-home-storeowner.png)
- [03-mainline-target.png](../docs/evidence/R3-2-QA/03-mainline-target.png)
- [04-home-layers-expanded.png](../docs/evidence/R3-2-QA/04-home-layers-expanded.png)
- [05-tasks-default.png](../docs/evidence/R3-2-QA/05-tasks-default.png)
- [06-tasks-waiting-cross-store.png](../docs/evidence/R3-2-QA/06-tasks-waiting-cross-store.png)
- [07-tasks-blocked.png](../docs/evidence/R3-2-QA/07-tasks-blocked.png)
- [08-tasks-done.png](../docs/evidence/R3-2-QA/08-tasks-done.png)
- [09-tasks-store-filter.png](../docs/evidence/R3-2-QA/09-tasks-store-filter.png)
- [10-task-open-target.png](../docs/evidence/R3-2-QA/10-task-open-target.png)
- [11-home-newuser.png](../docs/evidence/R3-2-QA/11-home-newuser.png)
- [12-home-noshop.png](../docs/evidence/R3-2-QA/12-home-noshop.png)
- [13-home-compliance-partial.png](../docs/evidence/R3-2-QA/13-home-compliance-partial.png)
- [14-home-readonly.png](../docs/evidence/R3-2-QA/14-home-readonly.png)
- [15-tools-expanded.png](../docs/evidence/R3-2-QA/15-tools-expanded.png)
- [16-mobile-390-home.png](../docs/evidence/R3-2-QA/16-mobile-390-home.png)
- [17-mobile-390-tasks.png](../docs/evidence/R3-2-QA/17-mobile-390-tasks.png)
- [18-mobile-768-home.png](../docs/evidence/R3-2-QA/18-mobile-768-home.png)
- [19-closure-before.png](../docs/evidence/R3-2-QA/19-closure-before.png)
- [20-closure-target.png](../docs/evidence/R3-2-QA/20-closure-target.png)
- [21-supp-topbar-home.png](../docs/evidence/R3-2-QA/21-supp-topbar-home.png)
- [22-supp-topbar-tasks.png](../docs/evidence/R3-2-QA/22-supp-topbar-tasks.png)
- [23-supp-tasks-blocked.png](../docs/evidence/R3-2-QA/23-supp-tasks-blocked.png)
- [24-supp-tasks-todo.png](../docs/evidence/R3-2-QA/24-supp-tasks-todo.png)
- [25-supp-loop-target.png](../docs/evidence/R3-2-QA/25-supp-loop-target.png)
- [26-loop-filter-target.png](../docs/evidence/R3-2-QA/26-loop-filter-target.png)
- [27-loop-filter-restored.png](../docs/evidence/R3-2-QA/27-loop-filter-restored.png)
- [BACKEND_DEPENDENCY_GAPS.md](../docs/evidence/R3-2-QA/BACKEND_DEPENDENCY_GAPS.md)
- [README.md](../docs/evidence/R3-2-QA/README.md)
- [ROUND2_CONCLUSION.md](../docs/evidence/R3-2-QA/ROUND2_CONCLUSION.md)
- [_round2_loop.sh](../docs/evidence/R3-2-QA/_round2_loop.sh)
- [_round2_run.sh](../docs/evidence/R3-2-QA/_round2_run.sh)
- [_round2_supp.sh](../docs/evidence/R3-2-QA/_round2_supp.sh)
- [browser-verify-loop.mjs](../docs/evidence/R3-2-QA/browser-verify-loop.mjs)
- [browser-verify-supp.mjs](../docs/evidence/R3-2-QA/browser-verify-supp.mjs)
- [browser-verify.mjs](../docs/evidence/R3-2-QA/browser-verify.mjs)

### `docs/evidence/R3-2A/`

- [01-sidebar-owner.png](../docs/evidence/R3-2A/01-sidebar-owner.png)
- [02-tools-expanded-owner.png](../docs/evidence/R3-2A/02-tools-expanded-owner.png)
- [03-topbar-context-owner.png](../docs/evidence/R3-2A/03-topbar-context-owner.png)
- [03b-topbar-crop.png](../docs/evidence/R3-2A/03b-topbar-crop.png)
- [04-sidebar-readonly.png](../docs/evidence/R3-2A/04-sidebar-readonly.png)
- [05-leaf-launch-owner.png](../docs/evidence/R3-2A/05-leaf-launch-owner.png)
- [README.md](../docs/evidence/R3-2A/README.md)
- [browser-verify.mjs](../docs/evidence/R3-2A/browser-verify.mjs)

### `docs/evidence/R3-2B/`

- [01-workspace-home.png](../docs/evidence/R3-2B/01-workspace-home.png)
- [02-workspace-home-expanded.png](../docs/evidence/R3-2B/02-workspace-home-expanded.png)
- [03-task-center.png](../docs/evidence/R3-2B/03-task-center.png)
- [04-task-center-waiting-view.png](../docs/evidence/R3-2B/04-task-center-waiting-view.png)
- [05-task-center-store-filter.png](../docs/evidence/R3-2B/05-task-center-store-filter.png)
- [06-r32b-home.png](../docs/evidence/R3-2B/06-r32b-home.png)
- [07-r32b-task-center.png](../docs/evidence/R3-2B/07-r32b-task-center.png)
- [08-r32b-home-390.png](../docs/evidence/R3-2B/08-r32b-home-390.png)
- [08-r32b-home-768.png](../docs/evidence/R3-2B/08-r32b-home-768.png)
- [09-r32b-tasks-390.png](../docs/evidence/R3-2B/09-r32b-tasks-390.png)
- [09-r32b-tasks-768.png](../docs/evidence/R3-2B/09-r32b-tasks-768.png)
- [10-r32b-task-click.png](../docs/evidence/R3-2B/10-r32b-task-click.png)
- [browser-verify.mjs](../docs/evidence/R3-2B/browser-verify.mjs)
- [r32b-fix-verify.mjs](../docs/evidence/R3-2B/r32b-fix-verify.mjs)
- [r32b-fix-verify.txt](../docs/evidence/R3-2B/r32b-fix-verify.txt)
- [r32b-mobile-verify.mjs](../docs/evidence/R3-2B/r32b-mobile-verify.mjs)
- [r32b-mobile-verify.txt](../docs/evidence/R3-2B/r32b-mobile-verify.txt)

### `docs/evidence/R3-3-QA/`

- [31-j1-product-detail.png](../docs/evidence/R3-3-QA/31-j1-product-detail.png)
- [32-j1-launch-deeplink.png](../docs/evidence/R3-3-QA/32-j1-launch-deeplink.png)
- [33-j1-wizard-skip-product.png](../docs/evidence/R3-3-QA/33-j1-wizard-skip-product.png)
- [34-j1-wizard-confirm.png](../docs/evidence/R3-3-QA/34-j1-wizard-confirm.png)
- [35-j1-launch-detail.png](../docs/evidence/R3-3-QA/35-j1-launch-detail.png)
- [36-j1-back-to-product.png](../docs/evidence/R3-3-QA/36-j1-back-to-product.png)
- [37-j0-step1.png](../docs/evidence/R3-3-QA/37-j0-step1.png)
- [38-j0-step1.png](../docs/evidence/R3-3-QA/38-j0-step1.png)
- [38-j0-step2.png](../docs/evidence/R3-3-QA/38-j0-step2.png)
- [38-j0-step3.png](../docs/evidence/R3-3-QA/38-j0-step3.png)
- [38-j0-step4.png](../docs/evidence/R3-3-QA/38-j0-step4.png)
- [38-j0-step5.png](../docs/evidence/R3-3-QA/38-j0-step5.png)
- [39-j2-tasks-blocked.png](../docs/evidence/R3-3-QA/39-j2-tasks-blocked.png)
- [40-j2-task-target.png](../docs/evidence/R3-3-QA/40-j2-task-target.png)
- [41-j2-back-restored.png](../docs/evidence/R3-3-QA/41-j2-back-restored.png)
- [42-j2-filter-gap.png](../docs/evidence/R3-3-QA/42-j2-filter-gap.png)
- [VERDICT.md](../docs/evidence/R3-3-QA/VERDICT.md)
- [_r33_run.sh](../docs/evidence/R3-3-QA/_r33_run.sh)
- [browser-verify-r33.mjs](../docs/evidence/R3-3-QA/browser-verify-r33.mjs)
- [debug-probe.mjs](../docs/evidence/R3-3-QA/debug-probe.mjs)
- [debug-probe2.mjs](../docs/evidence/R3-3-QA/debug-probe2.mjs)
- [debug-probe3.mjs](../docs/evidence/R3-3-QA/debug-probe3.mjs)
- [debug-probe4.mjs](../docs/evidence/R3-3-QA/debug-probe4.mjs)
- [probe-result.json](../docs/evidence/R3-3-QA/probe-result.json)
- [probe2-result.json](../docs/evidence/R3-3-QA/probe2-result.json)
- [probe3-result.json](../docs/evidence/R3-3-QA/probe3-result.json)
- [probe4-result.json](../docs/evidence/R3-3-QA/probe4-result.json)
- [r33-browser-result.json](../docs/evidence/R3-3-QA/r33-browser-result.json)

### `docs/evidence/V9-1-B0/`

- [B0_REVIEW.md](../docs/evidence/V9-1-B0/B0_REVIEW.md)

### `docs/evidence/V9-1-B1/`

- [REPORT.md](../docs/evidence/V9-1-B1/REPORT.md)
- [_b1_run.sh](../docs/evidence/V9-1-B1/_b1_run.sh)
- [b1-browser-result.json](../docs/evidence/V9-1-B1/b1-browser-result.json)
- [browser-verify-b1.mjs](../docs/evidence/V9-1-B1/browser-verify-b1.mjs)
- [v1-app-1440x900.png](../docs/evidence/V9-1-B1/v1-app-1440x900.png)
- [v2-app-1366x768.png](../docs/evidence/V9-1-B1/v2-app-1366x768.png)
- [v3-app-768x1024.png](../docs/evidence/V9-1-B1/v3-app-768x1024.png)
- [v4-app-390x844.png](../docs/evidence/V9-1-B1/v4-app-390x844.png)

### `docs/evidence/V9-1-B3/`

- [REPORT.md](../docs/evidence/V9-1-B3/REPORT.md)
- [v1-products-list-1440.png](../docs/evidence/V9-1-B3/v1-products-list-1440.png)
- [v10-detail-390.png](../docs/evidence/V9-1-B3/v10-detail-390.png)
- [v2-detail-1440.png](../docs/evidence/V9-1-B3/v2-detail-1440.png)
- [v3-matching-1440.png](../docs/evidence/V9-1-B3/v3-matching-1440.png)
- [v4-shop-scope-sg-1440.png](../docs/evidence/V9-1-B3/v4-shop-scope-sg-1440.png)
- [v5-expired-offer-1440.png](../docs/evidence/V9-1-B3/v5-expired-offer-1440.png)
- [v6-missing-offer-1440.png](../docs/evidence/V9-1-B3/v6-missing-offer-1440.png)
- [v7-detail-missing-1440.png](../docs/evidence/V9-1-B3/v7-detail-missing-1440.png)
- [v8-viewer-readonly-1440.png](../docs/evidence/V9-1-B3/v8-viewer-readonly-1440.png)
- [v9-matching-390.png](../docs/evidence/V9-1-B3/v9-matching-390.png)

### `docs/evidence/V9-1-S3/`

- [REPORT.md](../docs/evidence/V9-1-S3/REPORT.md)

### `docs/evidence/V9-1-S4/`

- [REPORT.md](../docs/evidence/V9-1-S4/REPORT.md)

### `docs/evidence/V9-1-S5/`

- [REPORT.md](../docs/evidence/V9-1-S5/REPORT.md)

### `frontend/`

- [index.html](../frontend/index.html)
- [package-lock.json](../frontend/package-lock.json)
- [package.json](../frontend/package.json)
- [vite.config.js](../frontend/vite.config.js)

### `frontend-v9/`

- [.gitignore](../frontend-v9/.gitignore)
- [index.html](../frontend-v9/index.html)
- [package-lock.json](../frontend-v9/package-lock.json)
- [package.json](../frontend-v9/package.json)
- [vite.config.js](../frontend-v9/vite.config.js)

### `frontend-v9/src/`

- [App.vue](../frontend-v9/src/App.vue)
- [charts.js](../frontend-v9/src/charts.js)
- [main.js](../frontend-v9/src/main.js)
- [styles.css](../frontend-v9/src/styles.css)

### `frontend-v9/src/api/`

- [dto.js](../frontend-v9/src/api/dto.js)

### `frontend-v9/src/api/domains/`

- [actions.js](../frontend-v9/src/api/domains/actions.js)
- [admin.js](../frontend-v9/src/api/domains/admin.js)
- [ads.js](../frontend-v9/src/api/domains/ads.js)
- [ai.js](../frontend-v9/src/api/domains/ai.js)
- [alerts.js](../frontend-v9/src/api/domains/alerts.js)
- [auth.js](../frontend-v9/src/api/domains/auth.js)
- [bi.js](../frontend-v9/src/api/domains/bi.js)
- [businessProfile.js](../frontend-v9/src/api/domains/businessProfile.js)
- [compliance.js](../frontend-v9/src/api/domains/compliance.js)
- [crossBorder.js](../frontend-v9/src/api/domains/crossBorder.js)
- [discovery.js](../frontend-v9/src/api/domains/discovery.js)
- [factoryNetwork.js](../frontend-v9/src/api/domains/factoryNetwork.js)
- [finance.js](../frontend-v9/src/api/domains/finance.js)
- [knowledge.js](../frontend-v9/src/api/domains/knowledge.js)
- [launch.js](../frontend-v9/src/api/domains/launch.js)
- [listings.js](../frontend-v9/src/api/domains/listings.js)
- [me.js](../frontend-v9/src/api/domains/me.js)
- [orders.js](../frontend-v9/src/api/domains/orders.js)
- [platformCapabilities.js](../frontend-v9/src/api/domains/platformCapabilities.js)
- [pricing.js](../frontend-v9/src/api/domains/pricing.js)
- [products.js](../frontend-v9/src/api/domains/products.js)
- [purchases.js](../frontend-v9/src/api/domains/purchases.js)
- [refunds.js](../frontend-v9/src/api/domains/refunds.js)
- [schedules.js](../frontend-v9/src/api/domains/schedules.js)
- [settlements.js](../frontend-v9/src/api/domains/settlements.js)
- [shops.js](../frontend-v9/src/api/domains/shops.js)
- [suppliers.js](../frontend-v9/src/api/domains/suppliers.js)
- [support.js](../frontend-v9/src/api/domains/support.js)
- [users.js](../frontend-v9/src/api/domains/users.js)
- [workbench.js](../frontend-v9/src/api/domains/workbench.js)
- [workflows.js](../frontend-v9/src/api/domains/workflows.js)

### `frontend-v9/src/app/errors/`

- [Forbidden.vue](../frontend-v9/src/app/errors/Forbidden.vue)
- [NotFound.vue](../frontend-v9/src/app/errors/NotFound.vue)
- [ServerError.vue](../frontend-v9/src/app/errors/ServerError.vue)

### `frontend-v9/src/app/pages/`

- [StubPage.vue](../frontend-v9/src/app/pages/StubPage.vue)

### `frontend-v9/src/app/router/`

- [index.js](../frontend-v9/src/app/router/index.js)
- [legacy-redirects.js](../frontend-v9/src/app/router/legacy-redirects.js)
- [routes-uxd.js](../frontend-v9/src/app/router/routes-uxd.js)
- [routes-uxe-a.js](../frontend-v9/src/app/router/routes-uxe-a.js)
- [routes-uxe-b.js](../frontend-v9/src/app/router/routes-uxe-b.js)

### `frontend-v9/src/components/`

- [AdvancedFilter.vue](../frontend-v9/src/components/AdvancedFilter.vue)
- [AiActionCard.vue](../frontend-v9/src/components/AiActionCard.vue)
- [ApprovalPanel.vue](../frontend-v9/src/components/ApprovalPanel.vue)
- [AsyncActionDialog.vue](../frontend-v9/src/components/AsyncActionDialog.vue)
- [AuditTimeline.vue](../frontend-v9/src/components/AuditTimeline.vue)
- [BusinessStatus.vue](../frontend-v9/src/components/BusinessStatus.vue)
- [ConfirmDialog.vue](../frontend-v9/src/components/ConfirmDialog.vue)
- [DataQualityBanner.vue](../frontend-v9/src/components/DataQualityBanner.vue)
- [DataTable.vue](../frontend-v9/src/components/DataTable.vue)
- [EmptyState.vue](../frontend-v9/src/components/EmptyState.vue)
- [EntityLink.vue](../frontend-v9/src/components/EntityLink.vue)
- [ErrorState.vue](../frontend-v9/src/components/ErrorState.vue)
- [EvidencePanel.vue](../frontend-v9/src/components/EvidencePanel.vue)
- [FormSection.vue](../frontend-v9/src/components/FormSection.vue)
- [JourneyJ0Bar.vue](../frontend-v9/src/components/JourneyJ0Bar.vue)
- [LoadingState.vue](../frontend-v9/src/components/LoadingState.vue)
- [MetricCard.vue](../frontend-v9/src/components/MetricCard.vue)
- [MoneyValue.vue](../frontend-v9/src/components/MoneyValue.vue)
- [NavSearch.vue](../frontend-v9/src/components/NavSearch.vue)
- [NextActionPanel.vue](../frontend-v9/src/components/NextActionPanel.vue)
- [PageHeader.vue](../frontend-v9/src/components/PageHeader.vue)
- [RiskCard.vue](../frontend-v9/src/components/RiskCard.vue)
- [SectionState.vue](../frontend-v9/src/components/SectionState.vue)
- [StatusBadge.vue](../frontend-v9/src/components/StatusBadge.vue)
- [StoreSwitcher.vue](../frontend-v9/src/components/StoreSwitcher.vue)
- [TaskCard.vue](../frontend-v9/src/components/TaskCard.vue)
- [WorkflowStepper.vue](../frontend-v9/src/components/WorkflowStepper.vue)
- [WorkspaceSwitcher.vue](../frontend-v9/src/components/WorkspaceSwitcher.vue)

### `frontend-v9/src/composables/`

- [discoveryTransfer.js](../frontend-v9/src/composables/discoveryTransfer.js)
- [factoryCatalog.js](../frontend-v9/src/composables/factoryCatalog.js)
- [impersonation.js](../frontend-v9/src/composables/impersonation.js)
- [launchCenter.js](../frontend-v9/src/composables/launchCenter.js)
- [launchViews.js](../frontend-v9/src/composables/launchViews.js)
- [listingFlow.js](../frontend-v9/src/composables/listingFlow.js)
- [publicationReceipts.js](../frontend-v9/src/composables/publicationReceipts.js)
- [publishActionQueue.js](../frontend-v9/src/composables/publishActionQueue.js)
- [shopCommerce.js](../frontend-v9/src/composables/shopCommerce.js)
- [tenantAdmin.js](../frontend-v9/src/composables/tenantAdmin.js)
- [workbenchCounts.js](../frontend-v9/src/composables/workbenchCounts.js)
- [workbenchTodo.js](../frontend-v9/src/composables/workbenchTodo.js)
- [workspaceShell.js](../frontend-v9/src/composables/workspaceShell.js)

### `frontend-v9/src/features/aftersale/`

- [refundStateMachine.js](../frontend-v9/src/features/aftersale/refundStateMachine.js)

### `frontend-v9/src/features/aicopilot/`

- [AiCopilot.vue](../frontend-v9/src/features/aicopilot/AiCopilot.vue)
- [actions.js](../frontend-v9/src/features/aicopilot/actions.js)

### `frontend-v9/src/features/aiops/`

- [decisionsView.js](../frontend-v9/src/features/aiops/decisionsView.js)
- [knowledgeView.js](../frontend-v9/src/features/aiops/knowledgeView.js)
- [scheduleView.js](../frontend-v9/src/features/aiops/scheduleView.js)
- [workflowView.js](../frontend-v9/src/features/aiops/workflowView.js)

### `frontend-v9/src/features/fulfillment/`

- [orderStateMachine.js](../frontend-v9/src/features/fulfillment/orderStateMachine.js)
- [settlementStateMachine.js](../frontend-v9/src/features/fulfillment/settlementStateMachine.js)

### `frontend-v9/src/features/home/`

- [PartialDataBanner.vue](../frontend-v9/src/features/home/PartialDataBanner.vue)

### `frontend-v9/src/features/launch/`

- [LaunchActionDialog.vue](../frontend-v9/src/features/launch/LaunchActionDialog.vue)
- [LaunchExperienceToggle.vue](../frontend-v9/src/features/launch/LaunchExperienceToggle.vue)
- [LaunchStatusSummary.vue](../frontend-v9/src/features/launch/LaunchStatusSummary.vue)
- [LaunchStepPanel.vue](../frontend-v9/src/features/launch/LaunchStepPanel.vue)
- [LaunchTimeline.vue](../frontend-v9/src/features/launch/LaunchTimeline.vue)
- [NextActionButton.vue](../frontend-v9/src/features/launch/NextActionButton.vue)
- [WaitingExternalState.vue](../frontend-v9/src/features/launch/WaitingExternalState.vue)

### `frontend-v9/src/features/listings/`

- [ListingFlow.vue](../frontend-v9/src/features/listings/ListingFlow.vue)
- [PublicationReceipts.vue](../frontend-v9/src/features/listings/PublicationReceipts.vue)
- [PublishActions.vue](../frontend-v9/src/features/listings/PublishActions.vue)

### `frontend-v9/src/features/optimization/`

- [alertTargets.js](../frontend-v9/src/features/optimization/alertTargets.js)

### `frontend-v9/src/features/settings/`

- [roleGuides.js](../frontend-v9/src/features/settings/roleGuides.js)

### `frontend-v9/src/features/shops/`

- [ShopAuthWizard.vue](../frontend-v9/src/features/shops/ShopAuthWizard.vue)
- [ShopCommerceFields.vue](../frontend-v9/src/features/shops/ShopCommerceFields.vue)

### `frontend-v9/src/features/supply/`

- [purchaseStateMachine.js](../frontend-v9/src/features/supply/purchaseStateMachine.js)

### `frontend-v9/src/pages/aftersale/`

- [Refunds.vue](../frontend-v9/src/pages/aftersale/Refunds.vue)
- [Support.vue](../frontend-v9/src/pages/aftersale/Support.vue)

### `frontend-v9/src/pages/aiops/`

- [AiActions.vue](../frontend-v9/src/pages/aiops/AiActions.vue)
- [AiDecisions.vue](../frontend-v9/src/pages/aiops/AiDecisions.vue)
- [Knowledge.vue](../frontend-v9/src/pages/aiops/Knowledge.vue)
- [Workflows.vue](../frontend-v9/src/pages/aiops/Workflows.vue)

### `frontend-v9/src/pages/analytics/`

- [Bi.vue](../frontend-v9/src/pages/analytics/Bi.vue)
- [Finance.vue](../frontend-v9/src/pages/analytics/Finance.vue)
- [Forecast.vue](../frontend-v9/src/pages/analytics/Forecast.vue)
- [LandedCost.vue](../frontend-v9/src/pages/analytics/LandedCost.vue)

### `frontend-v9/src/pages/auth/`

- [Login.vue](../frontend-v9/src/pages/auth/Login.vue)

### `frontend-v9/src/pages/channel/`

- [Channels.vue](../frontend-v9/src/pages/channel/Channels.vue)
- [ShopDetail.vue](../frontend-v9/src/pages/channel/ShopDetail.vue)
- [Shops.vue](../frontend-v9/src/pages/channel/Shops.vue)

### `frontend-v9/src/pages/compliance/`

- [Approvals.vue](../frontend-v9/src/pages/compliance/Approvals.vue)
- [Compliance.vue](../frontend-v9/src/pages/compliance/Compliance.vue)

### `frontend-v9/src/pages/console/`

- [Adapters.vue](../frontend-v9/src/pages/console/Adapters.vue)
- [AiResources.vue](../frontend-v9/src/pages/console/AiResources.vue)
- [Audit.vue](../frontend-v9/src/pages/console/Audit.vue)
- [Maintenance.vue](../frontend-v9/src/pages/console/Maintenance.vue)
- [Overview.vue](../frontend-v9/src/pages/console/Overview.vue)
- [Rules.vue](../frontend-v9/src/pages/console/Rules.vue)
- [Tenants.vue](../frontend-v9/src/pages/console/Tenants.vue)

### `frontend-v9/src/pages/factory/`

- [Capability.vue](../frontend-v9/src/pages/factory/Capability.vue)
- [FactoryHome.vue](../frontend-v9/src/pages/factory/FactoryHome.vue)
- [FactoryProducts.vue](../frontend-v9/src/pages/factory/FactoryProducts.vue)
- [FulfillmentHistory.vue](../frontend-v9/src/pages/factory/FulfillmentHistory.vue)
- [StockingTasks.vue](../frontend-v9/src/pages/factory/StockingTasks.vue)

### `frontend-v9/src/pages/fulfillment/`

- [Fulfillment.vue](../frontend-v9/src/pages/fulfillment/Fulfillment.vue)
- [Orders.vue](../frontend-v9/src/pages/fulfillment/Orders.vue)
- [Settlements.vue](../frontend-v9/src/pages/fulfillment/Settlements.vue)

### `frontend-v9/src/pages/home/`

- [TaskCenter.vue](../frontend-v9/src/pages/home/TaskCenter.vue)
- [WorkspaceHome.vue](../frontend-v9/src/pages/home/WorkspaceHome.vue)

### `frontend-v9/src/pages/market/`

- [Candidates.vue](../frontend-v9/src/pages/market/Candidates.vue)
- [Discovery.vue](../frontend-v9/src/pages/market/Discovery.vue)
- [OpportunityDetail.vue](../frontend-v9/src/pages/market/OpportunityDetail.vue)

### `frontend-v9/src/pages/onboarding/`

- [Onboarding.vue](../frontend-v9/src/pages/onboarding/Onboarding.vue)

### `frontend-v9/src/pages/optimization/`

- [Ads.vue](../frontend-v9/src/pages/optimization/Ads.vue)
- [Pricing.vue](../frontend-v9/src/pages/optimization/Pricing.vue)
- [RiskAlerts.vue](../frontend-v9/src/pages/optimization/RiskAlerts.vue)

### `frontend-v9/src/pages/product/`

- [LaunchCenter.vue](../frontend-v9/src/pages/product/LaunchCenter.vue)
- [LaunchDetail.vue](../frontend-v9/src/pages/product/LaunchDetail.vue)
- [Listings.vue](../frontend-v9/src/pages/product/Listings.vue)
- [ProductDetail.vue](../frontend-v9/src/pages/product/ProductDetail.vue)
- [Products.vue](../frontend-v9/src/pages/product/Products.vue)

### `frontend-v9/src/pages/settings/`

- [AiSettings.vue](../frontend-v9/src/pages/settings/AiSettings.vue)
- [Credentials.vue](../frontend-v9/src/pages/settings/Credentials.vue)
- [TeamSettings.vue](../frontend-v9/src/pages/settings/TeamSettings.vue)
- [WorkspaceInfo.vue](../frontend-v9/src/pages/settings/WorkspaceInfo.vue)

### `frontend-v9/src/pages/supply/`

- [Matching.vue](../frontend-v9/src/pages/supply/Matching.vue)
- [Purchases.vue](../frontend-v9/src/pages/supply/Purchases.vue)
- [Sourcing.vue](../frontend-v9/src/pages/supply/Sourcing.vue)
- [Suppliers.vue](../frontend-v9/src/pages/supply/Suppliers.vue)

### `frontend-v9/src/permissions/`

- [permissions.js](../frontend-v9/src/permissions/permissions.js)

### `frontend-v9/src/shared/`

- [actionView.js](../frontend-v9/src/shared/actionView.js)
- [asyncAction.js](../frontend-v9/src/shared/asyncAction.js)
- [biCaliber.js](../frontend-v9/src/shared/biCaliber.js)
- [businessStatus.js](../frontend-v9/src/shared/businessStatus.js)
- [consoleAdapters.js](../frontend-v9/src/shared/consoleAdapters.js)
- [consoleAiResources.js](../frontend-v9/src/shared/consoleAiResources.js)
- [consoleRules.js](../frontend-v9/src/shared/consoleRules.js)
- [dataLabels.js](../frontend-v9/src/shared/dataLabels.js)
- [discoveryView.js](../frontend-v9/src/shared/discoveryView.js)
- [entityLink.js](../frontend-v9/src/shared/entityLink.js)
- [evidence.js](../frontend-v9/src/shared/evidence.js)
- [factoryCatalogSplit.js](../frontend-v9/src/shared/factoryCatalogSplit.js)
- [factoryHome.js](../frontend-v9/src/shared/factoryHome.js)
- [factoryTasks.js](../frontend-v9/src/shared/factoryTasks.js)
- [forecastView.js](../frontend-v9/src/shared/forecastView.js)
- [fulfillmentQueue.js](../frontend-v9/src/shared/fulfillmentQueue.js)
- [journeyJ0View.js](../frontend-v9/src/shared/journeyJ0View.js)
- [matchingView.js](../frontend-v9/src/shared/matchingView.js)
- [money.js](../frontend-v9/src/shared/money.js)
- [navigationReturn.js](../frontend-v9/src/shared/navigationReturn.js)
- [nextAction.js](../frontend-v9/src/shared/nextAction.js)
- [onboardingProfile.js](../frontend-v9/src/shared/onboardingProfile.js)
- [onboardingStart.js](../frontend-v9/src/shared/onboardingStart.js)
- [orderDetailView.js](../frontend-v9/src/shared/orderDetailView.js)
- [orderView.js](../frontend-v9/src/shared/orderView.js)
- [pageStates.js](../frontend-v9/src/shared/pageStates.js)
- [productDetailView.js](../frontend-v9/src/shared/productDetailView.js)
- [productsListView.js](../frontend-v9/src/shared/productsListView.js)
- [shopDetailView.js](../frontend-v9/src/shared/shopDetailView.js)
- [sourcingView.js](../frontend-v9/src/shared/sourcingView.js)
- [statusDict.js](../frontend-v9/src/shared/statusDict.js)
- [storeScope.js](../frontend-v9/src/shared/storeScope.js)
- [taskCenterView.js](../frontend-v9/src/shared/taskCenterView.js)
- [ui.js](../frontend-v9/src/shared/ui.js)
- [workbenchContext.js](../frontend-v9/src/shared/workbenchContext.js)
- [workspace.js](../frontend-v9/src/shared/workspace.js)
- [workspaceHomeView.js](../frontend-v9/src/shared/workspaceHomeView.js)
- [workspaceSwitcher.js](../frontend-v9/src/shared/workspaceSwitcher.js)

### `frontend-v9/src/shared/api/`

- [client.js](../frontend-v9/src/shared/api/client.js)
- [errors.js](../frontend-v9/src/shared/api/errors.js)

### `frontend-v9/src/shared/navigation/`

- [console-navigation.js](../frontend-v9/src/shared/navigation/console-navigation.js)
- [factory-navigation.js](../frontend-v9/src/shared/navigation/factory-navigation.js)
- [filter.js](../frontend-v9/src/shared/navigation/filter.js)
- [types.js](../frontend-v9/src/shared/navigation/types.js)
- [workspace-navigation.js](../frontend-v9/src/shared/navigation/workspace-navigation.js)

### `frontend-v9/src/shells/`

- [AppShellCore.vue](../frontend-v9/src/shells/AppShellCore.vue)
- [ConsoleShell.vue](../frontend-v9/src/shells/ConsoleShell.vue)
- [FactoryShell.vue](../frontend-v9/src/shells/FactoryShell.vue)
- [ShellBanner.vue](../frontend-v9/src/shells/ShellBanner.vue)
- [ShellContextBar.vue](../frontend-v9/src/shells/ShellContextBar.vue)
- [ShellSidebar.vue](../frontend-v9/src/shells/ShellSidebar.vue)
- [ShellTopbar.vue](../frontend-v9/src/shells/ShellTopbar.vue)
- [WorkspaceShell.vue](../frontend-v9/src/shells/WorkspaceShell.vue)

### `frontend-v9/src/styles/`

- [tokens.css](../frontend-v9/src/styles/tokens.css)

### `frontend-v9/tests/`

- [console-adapters.test.js](../frontend-v9/tests/console-adapters.test.js)
- [console-ai-resources.test.js](../frontend-v9/tests/console-ai-resources.test.js)
- [console-rules.test.js](../frontend-v9/tests/console-rules.test.js)
- [discovery-transfer.test.js](../frontend-v9/tests/discovery-transfer.test.js)
- [discovery-view.test.js](../frontend-v9/tests/discovery-view.test.js)
- [factory-catalog.test.js](../frontend-v9/tests/factory-catalog.test.js)
- [factory-home.test.js](../frontend-v9/tests/factory-home.test.js)
- [factory-tasks.test.js](../frontend-v9/tests/factory-tasks.test.js)
- [impersonation.test.js](../frontend-v9/tests/impersonation.test.js)
- [journey-j0-view.test.js](../frontend-v9/tests/journey-j0-view.test.js)
- [launch-center.test.js](../frontend-v9/tests/launch-center.test.js)
- [launch-create.test.js](../frontend-v9/tests/launch-create.test.js)
- [launch-views.test.js](../frontend-v9/tests/launch-views.test.js)
- [listing-flow.test.js](../frontend-v9/tests/listing-flow.test.js)
- [navigation-factory.test.js](../frontend-v9/tests/navigation-factory.test.js)
- [navigation-return.test.js](../frontend-v9/tests/navigation-return.test.js)
- [navigation.test.js](../frontend-v9/tests/navigation.test.js)
- [onboarding-profile.test.js](../frontend-v9/tests/onboarding-profile.test.js)
- [onboarding-start.test.js](../frontend-v9/tests/onboarding-start.test.js)
- [order-view.test.js](../frontend-v9/tests/order-view.test.js)
- [permissions-can.test.js](../frontend-v9/tests/permissions-can.test.js)
- [permissions.test.js](../frontend-v9/tests/permissions.test.js)
- [product-detail-view.test.js](../frontend-v9/tests/product-detail-view.test.js)
- [products-api-contract.test.js](../frontend-v9/tests/products-api-contract.test.js)
- [products-list-view.test.js](../frontend-v9/tests/products-list-view.test.js)
- [products-query.test.js](../frontend-v9/tests/products-query.test.js)
- [publication-receipts.test.js](../frontend-v9/tests/publication-receipts.test.js)
- [publish-actions.test.js](../frontend-v9/tests/publish-actions.test.js)
- [r3-2b-regression-proof.test.js](../frontend-v9/tests/r3-2b-regression-proof.test.js)
- [route-resolve-channels.test.js](../frontend-v9/tests/route-resolve-channels.test.js)
- [router-guard.test.js](../frontend-v9/tests/router-guard.test.js)
- [router.test.js](../frontend-v9/tests/router.test.js)
- [status-dict.test.js](../frontend-v9/tests/status-dict.test.js)
- [task-center-view.test.js](../frontend-v9/tests/task-center-view.test.js)
- [tenant-admin.test.js](../frontend-v9/tests/tenant-admin.test.js)
- [uxd-api-domains.test.js](../frontend-v9/tests/uxd-api-domains.test.js)
- [uxd-bi-caliber-alerts.test.js](../frontend-v9/tests/uxd-bi-caliber-alerts.test.js)
- [uxd-routes.test.js](../frontend-v9/tests/uxd-routes.test.js)
- [uxd-state-machines.test.js](../frontend-v9/tests/uxd-state-machines.test.js)
- [uxe-aicopilot-settings.test.js](../frontend-v9/tests/uxe-aicopilot-settings.test.js)
- [uxe-aiops-view.test.js](../frontend-v9/tests/uxe-aiops-view.test.js)
- [uxe-api-domains.test.js](../frontend-v9/tests/uxe-api-domains.test.js)
- [uxe-routes.test.js](../frontend-v9/tests/uxe-routes.test.js)
- [v91-shell-sidebar.test.js](../frontend-v9/tests/v91-shell-sidebar.test.js)
- [v91-tokens.test.js](../frontend-v9/tests/v91-tokens.test.js)
- [workbench-context.test.js](../frontend-v9/tests/workbench-context.test.js)
- [workbench.test.js](../frontend-v9/tests/workbench.test.js)
- [workspace-home-view.test.js](../frontend-v9/tests/workspace-home-view.test.js)
- [workspace-listener-safety.test.js](../frontend-v9/tests/workspace-listener-safety.test.js)
- [workspace.test.js](../frontend-v9/tests/workspace.test.js)

### `frontend-v9/tests/shared/`

- [actionView.test.js](../frontend-v9/tests/shared/actionView.test.js)
- [forecast.test.js](../frontend-v9/tests/shared/forecast.test.js)
- [matching.test.js](../frontend-v9/tests/shared/matching.test.js)
- [money.test.js](../frontend-v9/tests/shared/money.test.js)
- [order-detail-view.test.js](../frontend-v9/tests/shared/order-detail-view.test.js)
- [shop-detail.test.js](../frontend-v9/tests/shared/shop-detail.test.js)
- [sourcing.test.js](../frontend-v9/tests/shared/sourcing.test.js)
- [store-scope.test.js](../frontend-v9/tests/shared/store-scope.test.js)

### `frontend/src/`

- [App.vue](../frontend/src/App.vue)
- [api.js](../frontend/src/api.js)
- [charts.js](../frontend/src/charts.js)
- [main.js](../frontend/src/main.js)
- [permissions.js](../frontend/src/permissions.js)
- [router.js](../frontend/src/router.js)
- [styles.css](../frontend/src/styles.css)
- [ui.js](../frontend/src/ui.js)
- [workspace.js](../frontend/src/workspace.js)

### `frontend/src/components/`

- [Breadcrumb.vue](../frontend/src/components/Breadcrumb.vue)
- [EmptyState.vue](../frontend/src/components/EmptyState.vue)
- [ErrorState.vue](../frontend/src/components/ErrorState.vue)
- [LaunchActionDialog.vue](../frontend/src/components/LaunchActionDialog.vue)
- [LaunchExperienceToggle.vue](../frontend/src/components/LaunchExperienceToggle.vue)
- [LaunchStatusSummary.vue](../frontend/src/components/LaunchStatusSummary.vue)
- [LaunchStepPanel.vue](../frontend/src/components/LaunchStepPanel.vue)
- [LaunchTimeline.vue](../frontend/src/components/LaunchTimeline.vue)
- [MetricCard.vue](../frontend/src/components/MetricCard.vue)
- [NextActionButton.vue](../frontend/src/components/NextActionButton.vue)
- [NoPermissionState.vue](../frontend/src/components/NoPermissionState.vue)
- [NotConfiguredState.vue](../frontend/src/components/NotConfiguredState.vue)
- [PageHeader.vue](../frontend/src/components/PageHeader.vue)
- [PartialDataBanner.vue](../frontend/src/components/PartialDataBanner.vue)
- [PublicationReceipts.vue](../frontend/src/components/PublicationReceipts.vue)
- [PublishActions.vue](../frontend/src/components/PublishActions.vue)
- [ShopCommerceFields.vue](../frontend/src/components/ShopCommerceFields.vue)
- [SidebarNav.vue](../frontend/src/components/SidebarNav.vue)
- [StateWrapper.vue](../frontend/src/components/StateWrapper.vue)
- [StatusTag.vue](../frontend/src/components/StatusTag.vue)
- [WaitingExternalState.vue](../frontend/src/components/WaitingExternalState.vue)
- [WorkspaceSwitcher.vue](../frontend/src/components/WorkspaceSwitcher.vue)

### `frontend/src/composables/`

- [launchCenter.js](../frontend/src/composables/launchCenter.js)
- [navigation.js](../frontend/src/composables/navigation.js)
- [publicationReceipts.js](../frontend/src/composables/publicationReceipts.js)
- [publishActionQueue.js](../frontend/src/composables/publishActionQueue.js)
- [shopCommerce.js](../frontend/src/composables/shopCommerce.js)
- [statusDict.js](../frontend/src/composables/statusDict.js)
- [workbenchTodo.js](../frontend/src/composables/workbenchTodo.js)

### `frontend/src/styles/`

- [tokens.css](../frontend/src/styles/tokens.css)

### `frontend/src/utils/`

- [navigationReturn.js](../frontend/src/utils/navigationReturn.js)

### `frontend/src/views/`

- [Ads.vue](../frontend/src/views/Ads.vue)
- [AiAssistant.vue](../frontend/src/views/AiAssistant.vue)
- [AiDecisions.vue](../frontend/src/views/AiDecisions.vue)
- [Alerts.vue](../frontend/src/views/Alerts.vue)
- [BI.vue](../frontend/src/views/BI.vue)
- [Compliance.vue](../frontend/src/views/Compliance.vue)
- [ComplianceWorkbench.vue](../frontend/src/views/ComplianceWorkbench.vue)
- [Dashboard.vue](../frontend/src/views/Dashboard.vue)
- [Discovery.vue](../frontend/src/views/Discovery.vue)
- [FactoryPortal.vue](../frontend/src/views/FactoryPortal.vue)
- [Finance.vue](../frontend/src/views/Finance.vue)
- [Knowledge.vue](../frontend/src/views/Knowledge.vue)
- [LaunchCenter.vue](../frontend/src/views/LaunchCenter.vue)
- [LaunchDetail.vue](../frontend/src/views/LaunchDetail.vue)
- [Layout.vue](../frontend/src/views/Layout.vue)
- [Listings.vue](../frontend/src/views/Listings.vue)
- [Login.vue](../frontend/src/views/Login.vue)
- [Orders.vue](../frontend/src/views/Orders.vue)
- [PlatformAdmin.vue](../frontend/src/views/PlatformAdmin.vue)
- [Pricing.vue](../frontend/src/views/Pricing.vue)
- [Products.vue](../frontend/src/views/Products.vue)
- [Refunds.vue](../frontend/src/views/Refunds.vue)
- [RunStatus.vue](../frontend/src/views/RunStatus.vue)
- [Settings.vue](../frontend/src/views/Settings.vue)
- [Settlements.vue](../frontend/src/views/Settlements.vue)
- [Shops.vue](../frontend/src/views/Shops.vue)
- [Suppliers.vue](../frontend/src/views/Suppliers.vue)
- [Support.vue](../frontend/src/views/Support.vue)
- [Users.vue](../frontend/src/views/Users.vue)
- [Workflows.vue](../frontend/src/views/Workflows.vue)

### `frontend/tests/`

- [launch-center.test.js](../frontend/tests/launch-center.test.js)
- [launch-create.test.js](../frontend/tests/launch-create.test.js)
- [navigation-return.test.js](../frontend/tests/navigation-return.test.js)
- [navigation.test.js](../frontend/tests/navigation.test.js)
- [permissions-can.test.js](../frontend/tests/permissions-can.test.js)
- [permissions.test.js](../frontend/tests/permissions.test.js)
- [publication-receipts.test.js](../frontend/tests/publication-receipts.test.js)
- [publish-actions.test.js](../frontend/tests/publish-actions.test.js)
- [router-guard.test.js](../frontend/tests/router-guard.test.js)
- [router.test.js](../frontend/tests/router.test.js)
- [status-dict.test.js](../frontend/tests/status-dict.test.js)
- [workbench.test.js](../frontend/tests/workbench.test.js)
- [workspace-listener-safety.test.js](../frontend/tests/workspace-listener-safety.test.js)
- [workspace.test.js](../frontend/tests/workspace.test.js)

## 后端模块介绍索引

说明取自源码模块文档字符串首段；它表达代码意图，不代替实现审计。

|文件|源码说明|
|---|---|
|[backend/app/__init__.py](../backend/app/__init__.py)|未声明模块说明；按函数/类定义进一步定位。|
|[backend/app/agents/__init__.py](../backend/app/agents/__init__.py)|未声明模块说明；按函数/类定义进一步定位。|
|[backend/app/agents/base.py](../backend/app/agents/base.py)|Agent 基类：会话管理 + LLM/规则双模执行 + AI 审计日志。 所有专业 Agent 继承 BaseAgent，实现具体业务方法。 ask_json() 是核心模式：优先 LLM 产出结构化 JSON，任何失败自动降级到 确定性规则函数 fallback()，保证系统离线零配置也可完整运行。|
|[backend/app/agents/capabilities.py](../backend/app/agents/capabilities.py)|AI 能力矩阵（服务端唯一口径）：当前身份能用哪些 Action、不能用为什么。 为什么要单独成模块：前端过去只能靠「把架构里的动作全部渲染成按钮」来猜能力， 于是出现「按钮点了才知道没权限」和「不知道某个 Agent 到底有没有实现」。这里以 **代码注册表**为准（`action_policy.POLICIES` + `action_system.HANDLERS` + `contracts.CONTRACTS` + `workspace_context` 的权限），一次性把 「能力 / 风险 / 是否需审批 |
|[backend/app/agents/compliance.py](../backend/app/agents/compliance.py)|合规 Agent 仅经 Tool 读取和生成结构化分析；报告及风险副本由可信调度接管。|
|[backend/app/agents/contracts.py](../backend/app/agents/contracts.py)|Agent 契约声明（Agent OS §6.2 / §18.3 第 1 步）。 **本模块只放声明，不含任何业务逻辑、不做任何 I/O。** 为什么需要 `docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md` §6.2 要求每个 Agent 必须声明 8 项能力约束（`domain` / `capabilities` / `input_schema` / `output_schema` / `required_permissions` / `required_data_s|
|[backend/app/agents/discovery.py](../backend/app/agents/discovery.py)|商品发现 Agent（市场趋势/关键词扩展/选品评分）与商品标准化 Agent。 §18.3 第 2 步（D46）：读取全部经 Tool 层（Product / Market Tool）；写路径 （趋势刷新）仅输出提案，由中央 Action 执行器调用业务服务。 评分只输出分析产物，由 Orchestrator 保存评分和依据链。 商品标准化仅输出 UPDATE_PRODUCT_CONTENT 提案，由 Orchestrator 调度执行。|
|[backend/app/agents/factory_opportunity.py](../backend/app/agents/factory_opportunity.py)|私域工厂机会 Agent：市场机会、真实供给与单位经济性联合门禁。 §18.3 第 3 步：读取全部经 Tool 层（Supply / Product Tool，见 D43）；匹配快照与 报价 upsert 的写入已迁出到 ``services/supply_outputs.py``（可信产物服务）。本 Agent 只产出只读提案（规则计算 + 经 Tool 读取），由 Orchestrator 经可信身份派发 ``finalize_scan_private_supply_batch`` 在服务端校验、原子保存；A|
|[backend/app/agents/listing.py](../backend/app/agents/listing.py)|Listing Agent：AI 生成多语言商品文案 / 优化 / 一键发布（对应规划第五章 4.5 节、第九章）。 M2 知识增强：生成前注入知识库检索结果与平台规则包约束；生成后规则引擎自检， 违禁词/超长时带修正提示重试一次（上限 1 次）；仍违规则降级模板并标记待复核。 读取全部经 Tool 层；草稿、优化、发布只产生提案，Orchestrator 调度独立 Action 执行。|
|[backend/app/agents/listing_review.py](../backend/app/agents/listing_review.py)|上架复核 Agent：仅通过 Tool 读取并返回结构化分析，不写规则或复核表。|
|[backend/app/agents/orchestrator.py](../backend/app/agents/orchestrator.py)|总调度 Agent（Commerce Orchestrator，对应规划第四章 4.1）： 理解用户目标 → 意图路由 → 调度专业 Agent → 汇总结果。 读取纪律（§18.3 第 2 步 / D45） 本模块所有业务读取都走 Tool 层（Conversation / Listing / Supply / Order / Finance / Product Tool）；`chat()` 末尾的 `AiLog` 写入是 §18.3 第 3 步 （Action 层）欠账，迁移期间不得删除（否则对话不再留痕），见|
|[backend/app/agents/pricing.py](../backend/app/agents/pricing.py)|定价 Agent（真实利润/动态定价，第十一章）与广告增长 Agent（第十二章）。 §18.3 第 2 步：读取全部经 Tool 层（Product / Market / Listing / Finance Tool，见 D44）。预算和广告草稿经 Action；D50 定价仅输出分析，持久化由调度层接管。|
|[backend/app/agents/supplier.py](../backend/app/agents/supplier.py)|供应链 Agent：最优货源匹配 / 供应商评分 / 销量预测与缺货预警（对应规划第十四章）。 §18.3 第 3 步：读取全部经 Tool 层（见 base.py），评分快照 / 预测快照的写入已迁出到 ``services/supply_outputs.py`` 的可信产物服务。本 Agent 只产出只读提案（规则计算 + 经 Tool 读取），由 Orchestrator 经可信身份派发 ``finalize_supplier_scores`` / ``finalize_forecast`` 在服务端校验后原|
|[backend/app/agents/support.py](../backend/app/agents/support.py)|客服 Agent：意图识别 + 按意图自动回复（对应规划第十三章）。|
|[backend/app/ai/__init__.py](../backend/app/ai/__init__.py)|未声明模块说明；按函数/类定义进一步定位。|
|[backend/app/ai/knowledge.py](../backend/app/ai/knowledge.py)|RAG 知识检索（对应规划 5.3 RAG 知识库）。 双模式： - 配置 LLM Key → 调用 /embeddings 接口做真实向量检索（余弦相似度），向量缓存到文档行； - 未配置 / 调用失败 → 退回 TF 关键词计分（ASCII 按词、中文按二元组切分，标题加权）。|
|[backend/app/ai/llm.py](../backend/app/ai/llm.py)|Model Router：统一 LLM 接入层（对应规划书第五章）。 - 兼容 OpenAI Chat Completions 协议（智谱 GLM / DeepSeek / OpenAI / Ollama 等均可）。 - 运行时配置存于 Setting 表 key="llm"，可经 /api/ai/settings 在线修改。 - 未配置 api_key 时抛出 LLMUnavailable，Agent 层自动降级为规则引擎（离线可用）。|
|[backend/app/auth.py](../backend/app/auth.py)|认证与权限：PBKDF2 口令散列 + JWT，角色 superadmin/admin/operator/viewer。 superadmin = 平台服务商（SaaS 运营方），可管理租户与代客访问（带审计）； license 门禁：租户停用/服务到期后业务请求一律 403。|
|[backend/app/config.py](../backend/app/config.py)|全局配置：环境变量优先，未设置时使用开发默认值。|
|[backend/app/db.py](../backend/app/db.py)|数据库引擎与会话。|
|[backend/app/main.py](../backend/app/main.py)|应用入口：FastAPI + 全量路由 + 静态托管前端构建产物。 启动：python -m uvicorn app.main:app --port 8000 （或 python app/main.py）|
|[backend/app/models.py](../backend/app/models.py)|ORM 数据模型 —— 全系统的数据契约（对应规划书第18-21章数据库设计）。 多租户约定：业务表均带 tenant_id；演示部署默认单租户。|
|[backend/app/pagination.py](../backend/app/pagination.py)|分页参数统一约束。 **为什么需要这个模块**（审计 #10 / DEBT-27）： 1. **无上限会拉全表**：`page_size` 原本无上界，调用方传 `page_size=10**9` 会把整张表读进内存再序列化，是廉价 DoS 面。 2. **静默截断比报错更危险**：调用方拿 `page_size=500` 做「集合比对」时， 若实际数据 501 条，返回的第一页看起来完全正常，**漏掉的那条不会被发现**。 实测：测试库 `orders` 恰好 500 条，与硬编码的 `page_size=500|
|[backend/app/proxy_headers.py](../backend/app/proxy_headers.py)|反向代理转发头处理（安全边界，集中一处）。 ## 为什么需要这个模块 生产部署时应用位于 TLS 终止代理（Caddy / nginx / 云负载均衡）之后， 到达应用的连接来自代理容器，于是： - ``request.client.host`` 是代理地址，不是真实客户端（审计日志失去意义）； - ``request.url.scheme`` 恒为 ``http``，生成的回调地址会退化成内网 http。 处理方式是在 ASGI 层采信 ``X-Forwarded-For`` / ``X-Forwarded-Pr|
|[backend/app/routers/__init__.py](../backend/app/routers/__init__.py)|未声明模块说明；按函数/类定义进一步定位。|
|[backend/app/routers/actions.py](../backend/app/routers/actions.py)|AI Action 的租户内查看、人工审批与幂等执行。|
|[backend/app/routers/admin.py](../backend/app/routers/admin.py)|平台服务商（superadmin）路由：租户管理 / 服务授权 / 代客访问 / 审计。|
|[backend/app/routers/ads.py](../backend/app/routers/ads.py)|广告增长路由：ROI 报告 / 活动管理 / AI 选词 / 预算优化（第十二章）。|
|[backend/app/routers/ai.py](../backend/app/routers/ai.py)|AI 设置路由：模型配置 / 平台参数 / Orchestrator 对话 / 调用日志。|
|[backend/app/routers/alerts.py](../backend/app/routers/alerts.py)|主动巡检路由（M3）：告警列表/确认、规则配置、手动触发巡检。|
|[backend/app/routers/auth.py](../backend/app/routers/auth.py)|认证与用户管理路由。|
|[backend/app/routers/bi.py](../backend/app/routers/bi.py)|BI 商业智能路由：企业驾驶舱 / 利润分析 / AI 经营报告（第十五章）。|
|[backend/app/routers/business_profiles.py](../backend/app/routers/business_profiles.py)|经营画像 API（D63）：GET / PUT /api/business-profile。 读写一律以服务端 Workspace Context 为准，**绝不信任客户端传入的 workspace_id** （请求体 Schema 不含该字段；即便客户端多传，也会被忽略，文档见下）。 两类字段与两类行的映射： - 个人偏好（user_id 非空行）：direction、budget_amount、budget_currency； - Workspace 共享（user_id 为空行）：target_market、|
|[backend/app/routers/compliance.py](../backend/app/routers/compliance.py)|合规检测路由：检测报告查询 / 发起检测（第十章侵权检测）。|
|[backend/app/routers/cross_border.py](../backend/app/routers/cross_border.py)|跨境到岸成本配置路由：关税税率 / 物流路由 / 平台费率 / 目的国合规（D58）。 权限：读 = ``finance:read``（OWNER/OPERATOR/READ_ONLY），写 = ``finance:write`` （OWNER/OPERATOR）。配置行的写入永远落在**当前租户**名下（``tenant_id = user.tenant_id``）；``tenant_id IS NULL`` 的行是平台内置口径，租户只能读， 不能改也不能删（避免一个租户改掉所有租户共享的税率）。 计算端点不重复|
|[backend/app/routers/discovery.py](../backend/app/routers/discovery.py)|商品发现路由：趋势 / 关键词扩展 / 选品评分 / 一键选品。|
|[backend/app/routers/factory_network.py](../backend/app/routers/factory_network.py)|私域源头工厂网络：门户自维护、机会匹配、供给候选转化。|
|[backend/app/routers/finance.py](../backend/app/routers/finance.py)|财务基础数据：汇率、订单费用、订单行与平台结算对账。|
|[backend/app/routers/knowledge.py](../backend/app/routers/knowledge.py)|RAG 知识库路由：文档 CRUD / 检索（对应规划 5.3）。|
|[backend/app/routers/launch.py](../backend/app/routers/launch.py)|Launch Center API：八端点 + 统一错误 envelope（薄编排，设计 §3.2）。 错误体统一为 ``HTTPException.detail`` 对象 ``{code, message, blockers, current_revision?, existing_launch_id?}``；写路径服务函数不 commit，由本层统一 commit/rollback。 路由声明顺序：``/context`` 必须早于 ``/{run_id}``，否则 ``context`` 会被当作 run_i|
|[backend/app/routers/listings.py](../backend/app/routers/listings.py)|Listing 路由：AI 生成 / 人工编辑 / 优化 / 一键发布（第九章一键铺货）。|
|[backend/app/routers/me.py](../backend/app/routers/me.py)|Workspace Context API（P1-09）：身份快照查询 + 活动 Workspace 切换校验。 契约见 `docs/phase1_interfaces.md` 第 8 节（FROZEN）。 本模块不建表、不写库、不改 JWT：切换语义当前是"校验 + 审计"， 真正的持久化留给 P1-06（Membership 落地后）。|
|[backend/app/routers/orders.py](../backend/app/routers/orders.py)|订单路由：列表 / CSV导入导出 / 平台同步（模拟）/ 状态流转。|
|[backend/app/routers/pricing.py](../backend/app/routers/pricing.py)|动态定价路由：成本利润计算 / AI 定价建议（第十一章）。|
|[backend/app/routers/product_assets.py](../backend/app/routers/product_assets.py)|商品素材注册、历史分页与独立核验；不接受外部传入的 Workspace 身份。|
|[backend/app/routers/product_channels.py](../backend/app/routers/product_channels.py)|商品渠道聚合：GET /api/products/{id}/channels（P1，独立文件避免 products.py 超警戒线）。 只读聚合该商品各销售店铺的当前活跃 Launch 与历史轮次；Scope 外店铺不出现也不计入总数 （AC-12.1）；同平台多店不合并（AC-12.3）；母稿 Listing.status 不渲染为「已核验在售」（AC-12.2）。|
|[backend/app/routers/products.py](../backend/app/routers/products.py)|商品池路由：CRUD / 详情聚合 / 真实URL与批量采集 / 标准化 / CSV导出。|
|[backend/app/routers/purchases.py](../backend/app/routers/purchases.py)|采购路由：补货预警生成采购单 → 提交供应商 → 收货入库；1688 一件代发下单（第十四章自动采购）。 店铺角色契约：Shop.role = source（货源：1688 搜品/一件代发下单）\| sales（销售：上架/拉单）。 代发下单只接受 source 店铺，销售店铺调用会被 400 明确拒绝——两类店铺绝不可混用。|
|[backend/app/routers/refunds.py](../backend/app/routers/refunds.py)|售后逆向路由：退款单发起 → 审核 → 退货入库 → 退款完成（订单联动）。|
|[backend/app/routers/schedules.py](../backend/app/routers/schedules.py)|自主经营调度任务路由：定时自动运行工作流/趋势扫描。|
|[backend/app/routers/settlements.py](../backend/app/routers/settlements.py)|供应商账期结算路由：汇总已收货采购单 → 对账确认 → 付款完成 → 应付账龄总览。|
|[backend/app/routers/shops.py](../backend/app/routers/shops.py)|店铺授权路由：OAuth 授权链接 / 授权码交换 / 回调 / 真实拉单 / 演示数据清理。|
|[backend/app/routers/suppliers.py](../backend/app/routers/suppliers.py)|供应链路由：供应商 CRUD / AI 评分 / 最优货源 / 销量预测 / 报价单录入。|
|[backend/app/routers/support.py](../backend/app/routers/support.py)|智能客服路由：会话 / 消息 / AI 自动回复（第十三章）。|
|[backend/app/routers/workbench.py](../backend/app/routers/workbench.py)|首页经营工作台只读 BFF 路由（薄编排）：`GET /workbench/todo`、`GET /workbench/overview`。 只做参数校验 + 身份解析，聚合逻辑全部落在 `services/workbench.py`（只读、不写库）。 随 `main.py` 的 `prefix="/api"` 注册 → 实际路径 `/api/workbench/*`。|
|[backend/app/routers/workflows.py](../backend/app/routers/workflows.py)|AI 工作流路由：模板 / 运行 / 历史（第十六章多 Agent 协同）。|
|[backend/app/secure_types.py](../backend/app/secure_types.py)|数据库敏感字符串透明加密；兼容读取旧明文，重新写入后自动加密。|
|[backend/app/seed.py](../backend/app/seed.py)|种子数据：开箱即用的演示环境（确定性 random.seed(42)）。|
|[backend/app/serialize.py](../backend/app/serialize.py)|SQLAlchemy 模型 -> dict 的统一序列化。|
|[backend/app/services/__init__.py](../backend/app/services/__init__.py)|未声明模块说明；按函数/类定义进一步定位。|
|[backend/app/services/action_content.py](../backend/app/services/action_content.py)|可自动执行的草稿与商品内容业务校验；不自行提交事务。|
|[backend/app/services/action_identity.py](../backend/app/services/action_identity.py)|Action 身份复核：当前执行人和原发起人均按服务端真实权限检查。|
|[backend/app/services/action_policy.py](../backend/app/services/action_policy.py)|Action 类型、权限和风险的服务端目录；Agent 无权覆盖。|
|[backend/app/services/action_publish.py](../backend/app/services/action_publish.py)|发布业务服务：Action 负责审批，平台发布意图与 checkpoint 负责外部幂等。|
|[backend/app/services/action_queue.py](../backend/app/services/action_queue.py)|待处理 Action 的统一查询（单一实现）：`routers/actions.py` 与只读 BFF 共用。 为什么单独成模块：待审批 Action 的查询原先是内联在 `routers/actions.py` 里的， workbench 聚合若另写一份 SQL，就会出现两套「什么算待审批」的口径漂移——一处改了 店铺范围过滤、另一处忘了改，前端两处角标就会互相矛盾。这里把查询收敛为唯一实现， 路由与 BFF 都调用它，`PUBLISH_LISTING` 的店铺数据范围过滤只写一遍。 S3 扩展（能力/契约对齐）|
|[backend/app/services/action_records.py](../backend/app/services/action_records.py)|发布与复核共用的字段级内容指纹，不访问数据库。|
|[backend/app/services/action_system.py](../backend/app/services/action_system.py)|统一 Action Guardrail 与 Executor：服务端策略、权限、审批、幂等事务。|
|[backend/app/services/ad_campaigns.py](../backend/app/services/ad_campaigns.py)|广告活动的业务写入口；Action Executor 与人工操作共用业务校验。|
|[backend/app/services/adapters/ali1688.py](../backend/app/services/adapters/ali1688.py)|1688（货源平台）适配器 1688 授权、token 交换/刷新与代发订单拉取。|
|[backend/app/services/adapters/base.py](../backend/app/services/adapters/base.py)|BaseAdapter：平台适配器的统一契约与通用守卫。 子类只实现平台差异；发布三道关（规则包校验 / 必填字段 / 类目映射）与 平台级限流在基类内聚，避免各平台重复实现。|
|[backend/app/services/adapters/catmap.py](../backend/app/services/adapters/catmap.py)|类目映射：系统类目 → 平台类目。 各平台类目树格式不同（Shopee 纯 ID、TikTok 路径、Amazon PCP 代码），映射值存原样。|
|[backend/app/services/adapters/contract.py](../backend/app/services/adapters/contract.py)|平台适配器契约层：常量、环境开关、统一重试、异常与归一化数据结构。 本模块由原 `services/platform_adapters.py`（1303 行单文件）按 DEBT-05 拆分而来。 对外契约**不变**：`app.services.platform_adapters` 仍是唯一导入入口。 为什么把契约单独成层：`BaseAdapter` 与全部 13 个平台适配器都依赖这组名字， 把它放在最底层可消除循环依赖（原单文件靠"定义顺序"隐式满足）。|
|[backend/app/services/adapters/ebay.py](../backend/app/services/adapters/ebay.py)|eBay 适配器 eBay OAuth、订单归一化与上架。|
|[backend/app/services/adapters/lazada.py](../backend/app/services/adapters/lazada.py)|Lazada 适配器 Lazada 签名、偏移分页订单与上架。|
|[backend/app/services/adapters/planned.py](../backend/app/services/adapters/planned.py)|已调研 / 待接入平台适配器 PlannedSalesAdapter 基类 + 5 个路线图平台 + Amazon（能力清单全空，不做假实现）。|
|[backend/app/services/adapters/registry.py](../backend/app/services/adapters/registry.py)|适配器注册表：平台名 → 适配器类，以及前端消费的平台元数据。|
|[backend/app/services/adapters/shopee.py](../backend/app/services/adapters/shopee.py)|Shopee 适配器 v2 HMAC-SHA256 签名、订单拉取、上架预检与两步发布。|
|[backend/app/services/adapters/tiktok.py](../backend/app/services/adapters/tiktok.py)|TikTok Shop 适配器 token 端点、签名、图片预上传与商品发布（含断点续传）。|
|[backend/app/services/adapters/walmart.py](../backend/app/services/adapters/walmart.py)|Walmart 适配器 Walmart OAuth、游标分页订单与上架。|
|[backend/app/services/agent_outputs.py](../backend/app/services/agent_outputs.py)|由 Orchestrator 调用的输出落库适配器；Agent 本身不调用 Guardrail。|
|[backend/app/services/ai_actions.py](../backend/app/services/ai_actions.py)|AI Action 的独立提交、审批和幂等执行入口（D47）。 当前只开放 ADJUST_AD_BUDGET；动作目录按显式白名单扩展，不能接受 Agent 自报的风险等级、权限或执行模式。业务写入只在 execute() 中发生。|
|[backend/app/services/alerting.py](../backend/app/services/alerting.py)|主动巡检服务（M3）：系统定时发现经营风险并告警。 设计红线（方案 §4.4-1）：**只告警不执行** —— 巡检只写 AlertEvent， 绝不自动改价/下架/补货，决策权始终在人。 九条规则（覆盖库存/广告/售后/内容/供应链/定价/政策/汇率/物流）： stockout_risk / ads_burning / refund_spike / listing_stale / supplier_delay / price_below_floor / policy_changed / fx_volatility|
|[backend/app/services/asset_rights.py](../backend/app/services/asset_rights.py)|发布素材权利门禁：只用适用范围内的当前版本，UNKNOWN/RESTRICTED 不放行。|
|[backend/app/services/asset_schema.py](../backend/app/services/asset_schema.py)|素材登记契约：URI 是来源引用，不触发网络下载，核验状态由服务端决定。|
|[backend/app/services/commercial_analytics.py](../backend/app/services/commercial_analytics.py)|统一经营指标与数据质量门禁。所有金额当前统一为订单记账币种 USD。|
|[backend/app/services/compliance_analysis.py](../backend/app/services/compliance_analysis.py)|合规纯分析：规则底线、有限值校验和不可变输入；不保存任何数据。|
|[backend/app/services/compliance_facts.py](../backend/app/services/compliance_facts.py)|可信合规依据读取：当前租户目标、关联商品及只读知识规则。|
|[backend/app/services/compliance_outputs.py](../backend/app/services/compliance_outputs.py)|可信合规产物保存：整批报告、来源摘要与受限风险 Action 原子提交。|
|[backend/app/services/compliance_registry.py](../backend/app/services/compliance_registry.py)|目的国合规档案服务：目的国 × 类目 × 认证要求 → 准入检查（P1-4）。 补齐「只审平台规则、不审目的国法规」的缺口。原合规 Agent 是四维扣分（商标侵权 / 违禁宣称 / 图片风险 / 平台规则），而封店、下架、罚没九成死在**目的国产品准入**上： - 产品准入认证：CE（欧盟）、UKCA（英国）、FCC（美国电子）、FDA（美国食品/化妆品/ 医疗）、CPC（美国儿童）、PSE（日本）、KC（韩国）； - 环保与注册：EPR（德国包装法/法国 EPR）、REACH / RoHS； - 特殊运输资质：|
|[backend/app/services/compliance_risk.py](../backend/app/services/compliance_risk.py)|受限风险副本业务执行器：只投影可信最新报告，绝不修改内容或发布。|
|[backend/app/services/costing.py](../backend/app/services/costing.py)|成本与利润计算（Agent 共享的领域计算，不依赖任何 Agent）。 为什么必须独立成 service（而不是留在 ``agents/pricing.py``）： ``FactoryOpportunityAgent`` 需要真实利润率做门禁，原实现直接 ``from .pricing import PricingAgent`` 再 ``PricingAgent(...).calc_profit()`` ——这是 **Agent 之间 P2P 调用**，违反 Agent OS 架构冻结文档 §3 与规范 L-3 （|
|[backend/app/services/discovery_outputs.py](../backend/app/services/discovery_outputs.py)|不可变选品分析产物：既有评分和依据链原子保存，无经营 Action。|
|[backend/app/services/duty.py](../backend/app/services/duty.py)|关税与进口税引擎：目的国 × HS × 申报货值 → 关税 / 进口 VAT / 清关费（P0-1）。 为什么必须独立成服务：2026 年低值包裹免税全球退坡后，关税与进口税从「可忽略」 变成跨境直邮的第一成本项—— - 美国 $800 de minimis 全球暂停：E.O. 14324（2025-07-30 签署，2025-08-29 生效） 暂停 de minimis 免税；E.O. 14388（2026-02-20）继续暂停，并对国际邮政 路径按 Proclamation 2026-02-20「临时进口附加|
|[backend/app/services/inventory_service.py](../backend/app/services/inventory_service.py)|海外仓持有成本引擎：库龄 × 日费率 → 持有成本 + 超期附加（D59）。 把海外仓费用从「路由计费」（按出库件数平摊）升级为「库存模型」 （按库龄累计）。库存模型回答的是：「这批货在海外仓囤了多久， 该扣多少仓储费，超期要不要叠加」——这才是真实利润杀手。 分层与边界： - 纯领域计算，不写库；金额口径统一为人民币。 - 库龄 = (now - received_at).days，下限 0（刚到货不算负成本）。 - 持有成本 = 库龄 × daily_fee × qty；超期部分 × (1 + surcharg|
|[backend/app/services/knowledge_learning.py](../backend/app/services/knowledge_learning.py)|客服知识自进化服务（M4）：未命中问题沉淀 → 人工验证答案 → 可选自动固化。 安全红线（方案 §3-修正1）：**只沉淀人工验证过的答案，AI 不自行编答案**。 answer_source = "operator" → 客服人工回复过，可信，可参与自动学习 answer_source = "none" → 无答案，永不可入库（人工也只能先补答案） 时序设计（方案 §8-修正8）：auto_reply 与 reply 是两个独立触发端点， 候选先记录问题，operator 后续回复时通过 backfill_an|
|[backend/app/services/logistics.py](../backend/app/services/logistics.py)|物流计费服务：计费重 × 费率 + 首重 + 附加（P0-2）。 替换原先「一条线性公式」的物流成本口径： logistics_cny = logistics_base + logistics_per_kg * weight # 旧口径 真实跨境物流成本至少包含头程/尾程分离、体积重（泡货按体积重计费）、 分区费率、海外仓/FBA 费用与燃油/旺季附加。本模块把物流升级为 「可配置费率表 + 报价核算」： - 计费重 = max(实重, 体积重)，体积重 = 长×宽×高 / 体积系数（默认 6000，空运口径）； |
|[backend/app/services/membership_service.py](../backend/app/services/membership_service.py)|Workspace Membership 写入侧（Phase 1.8 收口）。 为什么需要本模块（三个同源缺陷）： Phase 1.1~1.7 只实现了**读取侧**（`resolve_workspace_context` 双读）， 写入侧一直缺失，导致： 1. `POST /api/admin/tenants` 不建 `workspace_profiles` → 新租户永远拿不到 MEMBERSHIP Context（实测 `source=LEGACY_FALLBACK`）； 2. `POST /api/auth|
|[backend/app/services/mock_market.py](../backend/app/services/mock_market.py)|模拟市场数据服务：模拟 1688 采集 / 订单生成（真实部署时替换为平台 OpenAPI/爬虫适配器）。|
|[backend/app/services/open_1688.py](../backend/app/services/open_1688.py)|1688 开放平台官方 API 客户端（open.1688.com）。 签名协议（param2）： path = /openapi/param2/{ns}/{version}/{api}/{app_key} 签名串 = path + 按key排序的 key1value1key2value2... sign = HMAC-SHA1(app_secret, 签名串).hex().upper() 配置存 Setting 表 key="1688_api"：{"app_key", "app_secret", "access_|
|[backend/app/services/outcome_attribution.py](../backend/app/services/outcome_attribution.py)|预测结果与私域工厂机会的到期归因服务。|
|[backend/app/services/pii_redact.py](../backend/app/services/pii_redact.py)|审计落库前的 PII 脱敏（Agent OS §19 验收项 8「无 PII 泄漏」）。 为什么必须在**写入前**脱敏 `ai_logs` 是长期保留的审计表（§16 Trace 的落地表）。PII 一旦落库，回收要靠 数据清理 + 冷备，代价高且容易漏。实测主库已有 2 行 `support.auto_reply` 的 prompt 含买家消息原文（第二十七轮交接记录）——那正是「先落库、再想办法」的 结果。因此脱敏挂在两个唯一写入落点上：`BaseAgent._log` 与 `tools.audit`， 而不|
|[backend/app/services/platform_adapters.py](../backend/app/services/platform_adapters.py)|平台适配器层（兼容门面）——把每个电商平台的一切差异封装在各自的 Adapter 里。 **本模块是唯一对外入口**。原 1303 行单文件已按 DEBT-05 拆为 `adapters/` 包， 本文件只做「重新导出 + 可打补丁点转发」，因此： - `from app.services.platform_adapters import X` 全部照旧； - 测试里的 `monkeypatch.setattr("app.services.platform_adapters.<name>", ...)` **必须继|
|[backend/app/services/platform_fees.py](../backend/app/services/platform_fees.py)|平台费率服务：平台 × 类目 × 站点 × 生效期（P1-6）。 原先平台佣金是硬编码在代码里的一个数字（``DEFAULT_FEES = {"shopee": 0.06, ...}``）， 平台一改费率就得改代码发版，而且**用一个数字代表一个平台的费率结构**必然偏： 真实费率为「佣金 + 交易手续费 + 服务费」，且随类目 / 站点 / 卖家等级分层。 本模块把费率升级为可维护的数据表解析，同时保留代码兜底以保证「主库未灌费率」 时口径不变（默认值与旧 ``DEFAULT_FEES`` 完全一致）。|
|[backend/app/services/platform_rules.py](../backend/app/services/platform_rules.py)|平台规则引擎：发布前强制校验，违规拒绝（底线：避免用户店铺被封）。 规则包来源： 1. 内置 DEFAULT_RULE_PACKS（基于各平台公开的卖家规则整理，带版本日期与出处）； 2. 数据库 PlatformRulePack（版本更新时写入，覆盖内置）； 3. 预留远程更新：环境变量 ERP_RULES_URL 指向规则 JSON 源，check_updates 可拉取。 各平台不一致性全部体现在各自的规则包里（标题长度/违禁词/禁售类目/图片要求/限流）。|
|[backend/app/services/platforms.py](../backend/app/services/platforms.py)|平台服务层（薄壳）：统一入口分发到各平台适配器。 业务代码只 import 本模块，不直接接触各平台差异。|
|[backend/app/services/pricing_outputs.py](../backend/app/services/pricing_outputs.py)|定价分析产物持久化：不创建 Action，不修改商品售价。|
|[backend/app/services/product_assets.py](../backend/app/services/product_assets.py)|商品素材版本服务；权利声明不等于核验，审批人与提交人必须不同。|
|[backend/app/services/product_outputs.py](../backend/app/services/product_outputs.py)|商品提案提交、范围恢复和业务结果组装；由 Orchestrator 调用。|
|[backend/app/services/product_performance.py](../backend/app/services/product_performance.py)|商品真实经营表现聚合（M1 选品数据飞轮）。 设计红线（方案 §4.4-3）：只统计真实来源订单（api/import/manual）， 演示数据（seed/demo）不得进入飞轮——否则 AI 学的是假数据。|
|[backend/app/services/product_standardization.py](../backend/app/services/product_standardization.py)|商品安全标准化规则与 Action 执行业务边界。|
|[backend/app/services/publish_gate.py](../backend/app/services/publish_gate.py)|上架合规闸门：发布前回答「这个商品能不能发布到这个平台」（只读）。 为什么需要独立成服务：`compliance_registry` 只回答「某目的国要求什么、证据齐不齐」， 但**发布链路真正要回答的是另一个问题**——这件商品、这个平台，现在能不能发。缺的那一环是 「目的国从哪来」：商品没写 `destination_country`、店铺没配站点时，系统要么默认放行 （等于把合规风险转嫁给运营），要么一刀切阻断（等于把合规债务变成可用性事故）。 本模块的立场（2026-10 确立）： 1. **只读**，绝不|
|[backend/app/services/regions.py](../backend/app/services/regions.py)|地区归一化：国家/地区代码的唯一口径（关税、物流、合规共用一份）。 为什么单独成模块：目的国在系统里出现多次（商品、订单、关税税率、物流路由、 合规档案），而同一目的地在不同业务口径下的"判定单元"不同——例如德国 (DE) 在 关税与合规上按**欧盟**规则判定（(EU) 2026/382 的 €3/件是欧盟口径），但在物流 路由上也可能需要按成员国单独维护。把所有归一化规则收在一处，避免每个服务 各写一份别名表，最终互相漂移。|
|[backend/app/services/review_analysis.py](../backend/app/services/review_analysis.py)|复核纯评估：Agent 与可信保存服务共用，零数据库副作用。|
|[backend/app/services/review_outputs.py](../backend/app/services/review_outputs.py)|可信复核分析保存与人工裁决；不创建发布 Action，不执行业务发布。|
|[backend/app/services/schedule_identity.py](../backend/app/services/schedule_identity.py)|调度身份只由服务器认证Context绑定，每次执行重新核验。|
|[backend/app/services/scheduler.py](../backend/app/services/scheduler.py)|自主经营调度器（AI 运营中心）：按分钟级间隔自动执行工作流/趋势扫描。 - 单后台守护线程，每 30s 检查一次到期任务；到点后在独立线程执行，互不阻塞。 - 任务配置持久化在 schedules 表，可经 /api/schedules 在线增删启停。 - last_run_at + interval 决定下一次执行时间；无锁竞争用 per-run 独立会话。|
|[backend/app/services/scraper.py](../backend/app/services/scraper.py)|真实网页采集器：多级抓取管线，输入商品页 URL 拿到商品要素。 Level 1 静态 HTTP：Open Graph / JSON-LD / 各平台内嵌 JSON（1688/京东/淘宝），快、零依赖； Level 2 无头浏览器（Playwright）：执行 JS 过反爬挑战、等待渲染后取完整 DOM， 需 `pip install playwright && playwright install chromium`，未安装自动跳过； Level 3 用户粘贴网页源码（/api/products/collect_|
|[backend/app/services/settings_service.py](../backend/app/services/settings_service.py)|配置作用域服务（P1-10）：租户级配置的唯一读写入口。 三级读取回退（租户覆盖优先，其次平台默认，最后代码默认）： tenant_settings(tenant_id, key) ↓ 不存在 settings(key) ← 平台默认值，由平台服务商维护 ↓ 不存在 代码内 _DEFAULTS 写入按 key 分流： PLATFORM_KEYS（llm / 1688_api）→ settings 表，仅平台服务商可写 TENANT_KEYS （platform_fees / fx / rules）→ tenant_|
|[backend/app/services/shop_scope.py](../backend/app/services/shop_scope.py)|店铺可见性守卫：归档（软删除）店铺对所有业务入口一律视为不存在。 背景：DELETE /api/shops/{id} 已改为归档式软删除（见 routers/shops.py）。 店铺行仍在库中（订单/采购单/结算单需要保留引用），因此每个直接读取店铺的 业务入口都必须显式排除 archived_at 非空的行，否则被删除的店铺仍能被拉单、 发布或代发，形成「已删除但可用」的越权路径。 用法： shop = active_shop(db, tenant_id, shop_id) # 返回 None 表示不存在/不可|
|[backend/app/services/store_scope.py](../backend/app/services/store_scope.py)|读取既有 Membership 数据范围；不新建身份模型或信任请求中的店铺列表。|
|[backend/app/services/supply_outputs.py](../backend/app/services/supply_outputs.py)|供应链域可信产物服务：供应商评分 / 销量预测 / 私域工厂机会匹配的原子保存。 §18.3 第 3 步（Agent OS）：Agent 只产出只读提案（经 Tool 层读取 + 规则计算）， 写入由本服务在服务端校验后原子提交。所有写入都在同一事务内，失败整批回滚、 错误显式上抛，不吞批量异常。 人工报价保护策略（见 ``finalize_scan_private_supply_batch``）：选择「整行拒绝覆盖」 而非「保护字段」。理由：``supplier_offers`` 表没有来源标记列（约束禁止改表结|
|[backend/app/services/tenant_data_purge.py](../backend/app/services/tenant_data_purge.py)|租户演示数据清理：按外键依赖顺序删除，保证 FK 约束下也能成功。 为什么需要本模块： 开启 SQLite 外键强制（app/db.py）后，原先「Order → Conversation → AdCampaign → Listing → Product」的删除顺序会被外键拦截： conversations.order_id / refund_orders.order_id / order_fees.order_id / order_lines.order_id 引用 orders；messages.convers|
|[backend/app/services/trend_candidates.py](../backend/app/services/trend_candidates.py)|内置趋势日种子纯算法：标记估算来源，不访问数据库或平台。|
|[backend/app/services/trend_refresh.py](../backend/app/services/trend_refresh.py)|内置趋势受限业务服务：原子刷新、真实来源保护及依据复核。|
|[backend/app/services/trend_source.py](../backend/app/services/trend_source.py)|趋势数据源（M5）：真实数据接入 + 如实标记来源。 设计红线（方案 §4.4）：`source` 字段如实标记数据出处，**不伪装数据来源**。 api —— 1688 开放平台行业关键词接口（有 AppKey 时真实可用） csv —— 从平台后台/第三方工具导出的真实趋势数据（无 API 时的可行路径） builtin —— 内置演示词池（降级兜底，前端可识别并提示）|
|[backend/app/services/workbench.py](../backend/app/services/workbench.py)|首页经营工作台只读聚合（BFF 服务层）。 只读红线：**仅 SELECT**，不写库、不新增表/迁移、不新增写端点。 单一实现：聚合只组合既有 `services/`、`workflows/` 函数 （`launch_list.list_launches` / `commercial_analytics.metric_summary`、`quality_report` / `alerting.list_alerts` / `action_queue` / `review_outputs.review_queue_|
|[backend/app/services/workspace_context.py](../backend/app/services/workspace_context.py)|Workspace Context Service（Phase 1.1 Identity Compatibility Layer）。 目标：在数据库尚未新增 WorkspaceMembership 表之前，先冻结"身份从哪里读"的唯一入口。 业务代码禁止直接读 `User.tenant_id` / `User.role`，必须通过本模块取 Context。 当前阶段实现为 **legacy-only**： - 只包装现有 `User` + `Tenant` + `SupplierPortalMember`； - 不|
|[backend/app/tools/__init__.py](../backend/app/tools/__init__.py)|Agent Tool Layer（Agent OS §10）—— Agent 访问业务能力的**唯一入口**。 对外只需要四个符号： ``legacy_context`` / ``ToolContext`` —— 构造调用上下文（身份 + 追踪） ``open_tool(name, context, db)`` —— 取一个 Tool 实例 ``ToolResult`` —— 读结果（ok / data / evidence / degraded / error） 为什么 Agent 只能经这里碰数据 架构红线 3|
|[backend/app/tools/audit.py](../backend/app/tools/audit.py)|Tool 调用审计：Agent OS §10.2「必须记录 Audit」的唯一落点。 为什么审计用独立短会话，而不是调用方持有的业务会话 审计与业务事务是两件事。若把审计写进调用方的会话，业务回滚会把审计一起 回滚——事后无法区分「操作没发生」与「操作发生了但审计丢了」，审计随即失去 证明力。因此审计走独立短会话，业务成败与审计留存互不牵连。代价是每次调用 多开一次连接；Tool 调用以只读为主，本地 SQLite 完全承受得住。 为什么审计失败不抛异常 与 ``BaseAgent.record_decision`|
|[backend/app/tools/base.py](../backend/app/tools/base.py)|Tool 基类：所有 Tool 的唯一调用入口与调用管线（Agent OS §10）。 管线（顺序不可调换，每一步都对应一条冻结条款）： 1. 方法在册？ —— 不在冻结清单里的方法一律拒绝，禁止 Tool 私自长接口 2. 是否写操作？ —— §10.5：写操作必须经 Action System，本层一律拒绝 3. 权限是否满足？ —— §10.2：由 Tool 自身 ToolSpec 判定，调用方无权传权限 4. 委派子类只读实现 —— 子类只提供 ``_<method>()``，返回值必须是 Reading |
|[backend/app/tools/compliance.py](../backend/app/tools/compliance.py)|Compliance Tool：合规视图读取（§10.4 冻结清单）。 为什么 `check_product` / `check_listing` 是**读**而不是「发起一次检测」 §10.4 把这两个方法冻结为读操作（权限 `compliance:read`，读写列标「读」）。 因此它们返回**已持久化的最近一次**报告，不重新跑检测、不落库。 检测分析报告由可信 Orchestrator/产物服务保存；Listing 风险副本经受限 compliance:check Action 执行。本层不提供写入口，防止|
|[backend/app/tools/contract.py](../backend/app/tools/contract.py)|Tool Layer 契约（Agent OS §10.3 冻结签名）与调用上下文。 **本模块只放契约与词汇表：零业务逻辑、零 I/O、零数据库访问。** 为什么必须有 Tool Layer 架构红线 3 禁止 Agent 直接操作数据库；§10.1 把 Tool Layer 定义为 Agent 访问业务能力的**唯一入口**。入口唯一，§10.2 的三项强制要求（绑定 Workspace / 检查 Permission / 记录 Audit）才有唯一落点。若各 Agent 继续 自建查询，这三项要求没有任何一处能|
|[backend/app/tools/conversation.py](../backend/app/tools/conversation.py)|Conversation Tool：客服会话读取（Agent OS §10.4.1 第二批冻结清单）。 为什么字段口径里**没有 buyer_name** 会话表带 `buyer_name`（买家姓名），而 Tool 的返回值会被审计落库 （`tools/audit.py` 记录结果载荷）。§15.4 明确禁止买家 PII 进入审计——因此 字段口径在这里就把它排除，而不是等审计层去猜哪个字段是 PII。与 `order_dict` 排除 `buyer_name` 同款纪律：**PII 不进 Tool 返回体**。|
|[backend/app/tools/finance.py](../backend/app/tools/finance.py)|Finance Tool：利润、单位经济与汇率（§10.4 冻结清单）。 为什么一律转调 `services/costing.py` 而不在本层算 成本/利润口径必须**唯一**：定价页显示的利润率、工厂机会门禁用的利润率、 Agent 建议降价时引用的利润率，只要有一处算法不同，三个数就对不上，而且 没人能判断哪个是对的。`services/costing.py` 已是该口径的唯一实现 （D-? 见其模块 docstring），本 Tool 只做「加闸门 + 记审计 + 转格式」。 为什么汇率缺失要报 NOT_F|
|[backend/app/tools/knowledge.py](../backend/app/tools/knowledge.py)|Knowledge Tool：把 RAG 检索收进 Tool 层（§10.4 冻结清单）。 为什么不直接让 Agent 调 ``ai.knowledge.retrieve`` 检索结果会进入 Agent 的推理依据，属于「读了什么数据」的一部分。若不收进 Tool 层，Trace 里就查不到这次运行到底依据了哪几篇知识文档，§19 验收项 5 （全部可追溯）随之落空。收进来的代价只是一次转发，收益是这条读取可审计。|
|[backend/app/tools/listing.py](../backend/app/tools/listing.py)|Listing Tool：上架内容读取（Agent OS §10.4.1 第二批冻结清单）。 为什么第二批才补 Listing §10.4 的第一批清单聚焦「机会 → 供应 → 商品 → 渠道」这条主干，Listing 作为 主干末端的内容对象没有进榜。但它是四个 Agent（compliance / listing / listing_review / orchestrator）的共同读取目标，缺它则这些 Agent 的读取点 无法迁移（DEBT-36）。补批走的是「清单扩展」而不是「改冻结项」——原 22 条 |
|[backend/app/tools/market.py](../backend/app/tools/market.py)|Market Tool：市场趋势与机会评分（§10.4 冻结清单）。 为什么机会分不在本 Tool 里「重算」而是读 `ProductScore` 评分口径属于业务算法，唯一实现在 `DiscoveryAgent` 侧（评分依据、权重、 LLM/规则双模都在那里）。Tool 层重算一遍必然与之漂移，而且会造出第二份 真相：页面上显示 78 分、Agent 拿到 81 分，没人说得清哪个对（T-53）。 本 Tool 只负责「把已落库的评分读出来」，算法归位留待后续批次。|
|[backend/app/tools/memory.py](../backend/app/tools/memory.py)|Memory Tool：§10.4 冻结清单里的 Memory 入口（本阶段只冻结接口）。 为什么现在只声明不实现 §18.2 把五层 Memory 排在 Phase 6，§18.3 又要求「禁止跳步」。此处把 ``recall`` / ``remember`` 登记进清单，是为了让 §10.4 的清单完整性可校验 （清单缺项会被 tests/test_tool_layer.py 直接打回）；实现留到 Phase 6。 为什么返回 NOT_IMPLEMENTED 而不是空结果 「没有相关记忆」与「记忆系统还不存在」|
|[backend/app/tools/order.py](../backend/app/tools/order.py)|Order Tool：订单与销售分析（§10.4 冻结清单）。 为什么 `get_orders` 不返回 `buyer_name` §19 验收项 8「无 PII 泄漏」要求 Trace / Memory / AiLog 中不得出现买家 PII。 Tool 的返回体会被写进审计与 Agent 上下文，一旦带上买家姓名，PII 就顺着 审计链路扩散到所有下游。买家身份的合法用途在客服场景，那条链路有自己的 读取口径，不从这里走。 为什么 `analyze_sales` 要显式报告币种混合 把 USD 与 CNY 的 |
|[backend/app/tools/product.py](../backend/app/tools/product.py)|Product Tool：商品读取（§10.4 冻结清单）。 为什么返回 dict 而不是 ORM 对象 Tool 层是 Agent 与数据库之间的边界。返回 ORM 对象等于把边界开成门洞： Agent 可以继续顺着关系属性做懒加载、继续 `obj.status = x` 改数据， 红线 3「禁止 Agent 直接操作数据库」就只剩一句口号。dict 强制 Agent 只拿 到显式声明的字段。|
|[backend/app/tools/registry.py](../backend/app/tools/registry.py)|Tool 注册表：名称 -> Tool 类，以及清单完整性自检（Agent OS §10.4）。 为什么必须有注册表 Guardrail 要按名字找 Tool、Trace 要按名字记调用、测试要按名字比对清单。 若各调用点直接 ``from ..tools.product import ProductTool``，「有哪些 Tool」 就散落在各处的 import 语句里，改名或增删必然漏改（T-53）。注册表让这件事 变成一份可遍历的数据。 为什么自检放在 import 期 清单写错的代价必须是「进程起不来」，而|
|[backend/app/tools/store.py](../backend/app/tools/store.py)|Store Tool：店铺列表与店铺级经营指标（§10.4 冻结清单）。 为什么店铺列表必须显式排除归档行 `DELETE /api/shops/{id}` 是**归档式软删除**（行仍在库中，订单/采购单/结算 仍引用它）。因此「能列出」等于「可用」——归档店铺一旦出现在列表里，上层就 可能对它发起拉单或发布，形成「已删除但可用」的越权路径。可见性判定统一由 `services/shop_scope.py` 承担，本 Tool 只调用它，不自己重写一遍（T-53）。 为什么 `get_store_metrics`|
|[backend/app/tools/supply.py](../backend/app/tools/supply.py)|Supply Tool：供应商与报价读取（§10.4 冻结清单）。 为什么报价要按租户过滤两遍（Supplier 与 SupplierOffer 各一次） `SupplierOffer` 自带 `tenant_id`，理论上只过滤它就够；但供应商的可见性 还受 `Supplier` 的租户归属与未来可能的档案状态约束。两处都过滤，才能保证 「拿到的报价，其供应商一定也在本租户可见范围内」——只过滤一层时，一旦 出现脏数据（跨租户 offer 指向本租户 supplier），泄漏不会被挡住。|
|[backend/app/workflows/__init__.py](../backend/app/workflows/__init__.py)|未声明模块说明；按函数/类定义进一步定位。|
|[backend/app/workflows/conditions.py](../backend/app/workflows/conditions.py)|受限条件 DSL：三值逻辑，未知事实不当作通过；不执行表达式代码。|
|[backend/app/workflows/contract_profiles.py](../backend/app/workflows/contract_profiles.py)|本地验收用 Profile；不注册生产能力，不代表任何平台官方完整流程。|
|[backend/app/workflows/engine.py](../backend/app/workflows/engine.py)|AI 工作流引擎（对应规划第十六章）： 模板步骤 -> 运行实例 -> 按序调度 Agent 动作，context_patch 在步骤间传递数据。 同步模式（settings.sync_workflow，测试用）或后台线程执行。|
|[backend/app/workflows/kinds.py](../backend/app/workflows/kinds.py)|持久化流程种类；旧自动化与平台生命周期分别领取和恢复。|
|[backend/app/workflows/launch_access.py](../backend/app/workflows/launch_access.py)|Launch 服务统一身份与店铺范围；工厂投影另走既有供应门户。|
|[backend/app/workflows/launch_action_catalog.py](../backend/app/workflows/launch_action_catalog.py)|Launch 动作元数据目录与载荷契约：未接通即禁用，完成标记绝不接受客户端勾选。 目录是纯数据（不碰 DB、不读时钟）：执行框架、NBA 与 DTO 角色投影共用同一份事实， 新增业务动作只改本文件与 handlers，框架不动（设计 D1）。本轮接通的动作见 ``BUSINESS_ACTION_META`` 的 ``connected`` 标记，其余领域动作（B03-B09）保持禁用并 指向责任领域与后续批次。动作幂等键、载荷指纹与证据指纹（设计 D2/R10）同属动作契约， 随本文件一起冻结。|
|[backend/app/workflows/launch_actions.py](../backend/app/workflows/launch_actions.py)|Launch 动作执行框架：校验链、幂等重放、revision CAS、状态机守卫与事件编排。 框架不认识任何具体业务动作（设计 D1）：新增动作只改 launch_action_catalog 与 handlers/submit。handler 返回 StepEffect 断言，由本模块统一收敛落库并记事件—— 一次事务一条动作事件（设计 D10）；高危动作失败绝不自动重发（AC-4.10）。|
|[backend/app/workflows/launch_dto.py](../backend/app/workflows/launch_dto.py)|Launch 读模型 DTO：列表/详情/步骤/事件/上下文/渠道聚合 + COMPLIANCE 角色投影（设计 D8）。 所有 DTO 结构性不含价格/成本/利润率/备货数字段（AC-3.2，契约测试递归断言）。 读详情/步骤（launch:manage）触发确定性刷新（无变化不增版，AC-2.2）；只读方仅计算不落库。|
|[backend/app/workflows/launch_facts.py](../backend/app/workflows/launch_facts.py)|Launch 服务端事实读取；未接入的领域事实保持 UNKNOWN，不能用请求载荷补齐。|
|[backend/app/workflows/launch_handlers.py](../backend/app/workflows/launch_handlers.py)|Launch 业务处理器（B01 接通集）：资料完成、重试、取消；注册表供执行框架查找。 handler 只做领域前置校验并返回 StepEffect 断言（设计 D10），不自行提交事务、 不直接写库；落库、收敛与事件由 launch_actions 统一编排。触碰 AiAction/Attempt 的 提交/核验 handler 按设计 D1 二分集中在 launch_submit。|
|[backend/app/workflows/launch_list.py](../backend/app/workflows/launch_list.py)|Launch 列表查询：先 Scope 后分页、SQL 侧筛选、批预取、逐行就绪度 + 单行降级（设计 D7）。 行**重算就绪度与 NBA**（保证下一动作/阻断摘要权威），但用四层控制查询量： Scope 过滤 → 分页 → 批预取（product/shop/listing/steps/attempt）→ 逐行仅剩 1 次权利查询。 单行事实异常不使整页失败（AC-10.6）：该行以降级阻断摘要展示。|
|[backend/app/workflows/launch_nba.py](../backend/app/workflows/launch_nba.py)|确定性 Next Best Action（B02）：纯函数，输入仅服务端事实，同输入双算一致（设计 D6）。 不读时钟、不随机、不访问 DB；排序键完全确定： ``(外部确认者, 是否解除阻断, 到期时间, sequence, step_code)``。 AI 层只能在 ``allowed_actions`` 内解释或重排（子集），不得新增动作（PRD §5.3）。|
|[backend/app/workflows/launch_plan.py](../backend/app/workflows/launch_plan.py)|Launch 只读计算段：定义/步骤完整性校验 + 服务端事实 + 确定性就绪度（零写库）。 执行框架（launch_actions）与刷新（launch_runtime）共用本模块，保证「同一实例 -> 同一计划」只有一份计算实现（设计 D10）。本函数不写库、不改 revision、不产生事件； 所有拒绝均为前置 LaunchError。|
|[backend/app/workflows/launch_records.py](../backend/app/workflows/launch_records.py)|Launch 创建事务：复用商品与草稿，固定定义，实例/步骤/事件一起提交。|
|[backend/app/workflows/launch_recovery.py](../backend/app/workflows/launch_recovery.py)|Launch 进程级恢复（AC-8.5 / 设计 D12）：重启时以系统身份回收未结束流程的 RUNNING 步骤。 与 ``launch_runtime.refresh_launch`` 的差异：本模块**无用户 ctx**、按确定性冻结规则回收 状态、**不调用任何外部适配器**、不做平台 read-back。零迁移：只写既有列 （``WorkflowStep.step_status``/``result``、``WorkflowRun.revision``、``WorkflowEvent``）。 事件与快照复|
|[backend/app/workflows/launch_rules.py](../backend/app/workflows/launch_rules.py)|确定性 DAG 就绪度；只计算状态，不执行动作、不接收客户端完成指令。|
|[backend/app/workflows/launch_runtime.py](../backend/app/workflows/launch_runtime.py)|Launch 就绪度持久化：固定定义、CAS、步骤和事件同一事务；不调用旧 Worker。|
|[backend/app/workflows/launch_state.py](../backend/app/workflows/launch_state.py)|Launch 共享状态内核：快照、纯函数 diff、事件、序号、AiAction 投影与回执落地。 执行框架（launch_actions）、刷新（launch_runtime）与读模型（launch_dto）共用本模块， 保证「同一事实 -> 同一状态迁移 -> 同一事件」只有一份实现（设计 D10）。|
|[backend/app/workflows/launch_submit.py](../backend/app/workflows/launch_submit.py)|Launch 提交与在售核验 handler（B01 接通集）：复用 action_system 审批队列与 Attempt 回执。 按设计 D1 二分，所有触碰 AiAction/PlatformPublishAttempt 的领域逻辑集中在本文件： 预检失败零状态变更、不建 Action（AC-6.1）；scope_key 带提交序号后缀，终态提案不被 复用而死锁（设计 R4）；核验双权限与核验人独立性在本处强制（AC-7.1）。|
|[backend/app/workflows/profile_schema.py](../backend/app/workflows/profile_schema.py)|平台流程定义契约：有界声明式 DAG，不携带任意 Agent 或 Python 调用。|
|[backend/app/workflows/profiles.py](../backend/app/workflows/profiles.py)|Profile 持久化、发布与确定性选择；调用方负责事务提交。|
|[backend/app/workflows/transactions.py](../backend/app/workflows/transactions.py)|局部工作流事务辅助；不改全站 SQLite 连接与旧事务语义。|
|[backend/scripts/audit_shop_roles.py](../backend/scripts/audit_shop_roles.py)|店铺角色（Supply/Sales）只读盘点：找出 role 与平台默认推导不一致的店铺。 用法（在 backend 目录执行）： python scripts/audit_shop_roles.py # 人类可读表格 python scripts/audit_shop_roles.py --json # JSON 输出（便于流水线消费） 只读保证： 1. 数据库地址默认取 ERP_DB_URL，未设置时取 app.config.settings.db_url； 2. SQLite 一律以 `mode=ro` UR|
|[backend/scripts/backup_restore_drill.py](../backend/scripts/backup_restore_drill.py)|SQLite 一致性备份与恢复演练工具（Phase 1 P1-04 迁移门禁）。 设计约束： * 源库始终以只读 URI（mode=ro + query_only）打开，绝不修改主库； * 备份一律通过 SQLite 官方备份 API（sqlite3.Connection.backup）生成， 禁止使用文件复制 —— WAL 状态下复制文件可能得到不一致副本； * 绝不覆盖已有备份文件，同名时自动追加序号； * 输出只包含表名、计数与哈希，不输出 username / password_hash / token /|
|[backend/scripts/check_docs_consistency.py](../backend/scripts/check_docs_consistency.py)|文档一致性校验器：拦住「文档与代码脱节」（规范 Doc-5）。 为什么需要本脚本 规范 Doc-5 要求「文档中引用的路径、字段名、状态值必须可被检索验证」， 但此前**没有任何工具执行它**，只能靠人工记忆。实测后果： 1. **基线数字同时过期且互不一致**——同一时点 6 个文档里并存 199 / 257 / 264 / 179 / 165 五个不同的「当前基线」，真实值是 291。 2. **已完成的事项仍标「未完成」**——`WORKSPACE_MIGRATION_PROGRESS.md` 的 R-03 |
|[backend/scripts/cleanup_probe_data.py](../backend/scripts/cleanup_probe_data.py)|probe 残留数据清理器：默认只读演练，``--apply`` 才真正删除。 为什么需要本脚本 R-06 只清理了 5 个 ``probe tenant`` 及其 25 行关联数据；``users`` / ``products`` / ``suppliers`` / ``ad_campaigns`` / ``conversations`` / ``knowledge_docs`` 中仍留有 probe 命名的静态脏数据。``app/db.py`` 在连接级 强制 ``PRAGMA foreign_keys=ON`|
|[backend/scripts/docker_feasibility.py](../backend/scripts/docker_feasibility.py)|Docker 生产镜像可行性验证：真构建 + 真运行 + 真登录 + 真业务调用。 用法（在 backend 目录执行）： python scripts/docker_feasibility.py # 完整验证（构建+运行） python scripts/docker_feasibility.py --skip-build # 复用已有镜像，只跑运行部分 python scripts/docker_feasibility.py --keep # 保留镜像与容器便于排查 为什么需要这个脚本（D21 教训）： `e2e|
|[backend/scripts/e2e_feasibility.py](../backend/scripts/e2e_feasibility.py)|端到端可行性验证：真启动服务 + 真实 HTTP + 静态前端，全程不碰业务主库。 用法（在 backend 目录执行）： python scripts/e2e_feasibility.py # 默认端口 8123 python scripts/e2e_feasibility.py --port 8125 # 自定义端口 python scripts/e2e_feasibility.py --keep # 保留副本库与日志便于排查 为什么需要这个脚本（D17 教训）： 后端全量测试全部使用进程内 `fastapi.|
|[backend/scripts/git_bundle_backup.py](../backend/scripts/git_bundle_backup.py)|Git 单文件归档备份（P0-4）：把整个仓库打成一个可离线恢复的 bundle。 为什么需要它（背景）：本仓库曾发生过一次 ``.git`` 对象库被清空的真实事故—— ``refs/heads/`` 丢失、对象只剩 8 个松散对象、无 pack、无远端，最后靠**回收站 + reflog** 才把 1297 个对象救回来。能救回来属于运气；正确做法是让历史在**仓库之外** 也有一份可验证的副本。 ``git bundle`` 把全部引用与对象打包成**单个文件**，可在任意机器上 ``git clone <b|
|[backend/scripts/launch_e2e.py](../backend/scripts/launch_e2e.py)|Launch 真机闭环端到端验收（AC-18.3）：真实后端 + 隔离副本库 + API/数据库断言。 用法（在 backend 目录执行）： python scripts/launch_e2e.py # 默认端口 8125 python scripts/launch_e2e.py --port 8126 # 自定义端口 python scripts/launch_e2e.py --keep # 保留副本库与日志（供人工/Playwright 复核） 为什么需要这个脚本（AC-18.3）： 既有 `live_acc|
|[backend/scripts/live_acceptance.py](../backend/scripts/live_acceptance.py)|全链路验收脚本：对运行中的后端执行 4 条业务闭环（读取为主 + 少量演示数据写入）。 用法：python scripts/live_acceptance.py [base_url] # base_url 默认 http://127.0.0.1:8000 输出：每步 PASS/FAIL（附关键字段），最后汇总；任一 FAIL 时退出码为 1。 **脚本自身必须可靠**（2026-09-24 修正两处"验收自己失灵"的缺陷）： 1. 采购闭环原先取 `GET /products` 的**第一个**商品建单，一旦该商品|
|[backend/scripts/migrate.py](../backend/scripts/migrate.py)|安全迁移入口：备份 SQLite 后执行兼容迁移并升级 Alembic 版本。|
|[backend/scripts/migration_preflight.py](../backend/scripts/migration_preflight.py)|P1-01 只读 Migration Preflight 检查器。 用法（在 backend 目录下执行）： python scripts/migration_preflight.py [--db <path\|sqlite-url>] [--json] [--out <report.json>] 退出码： 0 = 无 P0 失败（允许存在 P1 警告） 2 = 存在 P0 失败 3 = 用法错误 / 数据库文件不可读 只读保证： 1) SQLite 一律以 ``file:<abs>?mode=ro`` URI 打开|
|[backend/scripts/platform_contract_sandbox.py](../backend/scripts/platform_contract_sandbox.py)|本地平台契约沙箱。 仅供开发/CI。启动：uvicorn scripts.platform_contract_sandbox:app --port 8877 适配器通过 ERP_<PLATFORM>_BASE_URL=http://127.0.0.1:8877 指向这里。 请求头 ``X-Contract-Error`` 可模拟 unauthorized/rate_limit/validation 错误。|
|[backend/scripts/project_goal_acceptance.py](../backend/scripts/project_goal_acceptance.py)|项目目标验收：在独立数据库上模拟跨境 ERP 的主要业务闭环。 用法：python scripts/project_goal_acceptance.py [base_url] 说明：脚本只应指向验收实例；会写入商品、广告、客服等演示记录。|
|[backend/scripts/refresh_test_baseline.py](../backend/scripts/refresh_test_baseline.py)|刷新测试基线（单一事实源）：采集后端/前端用例数，写入 ``docs/baseline.json``。 为什么需要本脚本 测试基线数字此前**手工维护在 6 个文档里**（`AGENTS.md` 2 处、 `CONTRIBUTING.md` 2 处、规范 §8 与 §9.4、`CONTRACT.md`、 `WORKSPACE_MIGRATION_PROGRESS.md`、`项目介绍与功能地图.md`）。实测结果是 它们**同时过期且互不一致**：同一时点文档里并存 199 / 257 / 264 / 179 / 1|
|[backend/scripts/security_data_audit.py](../backend/scripts/security_data_audit.py)|权限与数据专项排查：全角色 × 全端点权限矩阵 + 跨表数据一致性审计。 用法：cd backend && python scripts/security_data_audit.py [base_url] 输出：越权访问（应拦未拦）、误拦（应放被拦）、数据不一致清单。 !! 危险提示 !! 本脚本的 ENDPOINTS 里含大量 POST/PUT 写操作（创建商品、供应商、广告、 知识库、定时任务等），会**真实写入**目标服务所连接的数据库。它曾在 主库（erp.db）留下 37 行 tenant_id=0 孤儿|
|[backend/scripts/tls_feasibility.py](../backend/scripts/tls_feasibility.py)|HTTPS 端到端验证：真 Caddy + 真应用容器，验证 TLS 链路真的通（DEBT-23）。 用法（在 backend 目录执行）： python scripts/tls_feasibility.py # 完整验证 python scripts/tls_feasibility.py --keep # 保留容器便于排查 python scripts/tls_feasibility.py --self-signed # 用自签证书（默认） ## 为什么需要这个脚本 `docker_feasibility.py`|

## HTTP 接口声明索引

以下仅提取路由装饰器，子路径还需结合各模块 APIRouter prefix 与 main.py 的 /api 前缀；不代表鉴权要求或完整契约。

### actions

```text
GET "")
GET "/{action_id}")
GET "/{action_id}/result")
POST "/{action_id}/approve")
POST "/{action_id}/reject")
POST "/{action_id}/execute")
```

### admin

```text
GET "/tenants")
POST "/tenants")
PUT "/tenants/{tenant_id}")
POST "/tenants/{tenant_id}/enter")
GET "/access_logs")
GET "/ai_logs")
GET "/overview")
```

### ads

```text
GET "/campaigns")
POST "/campaigns")
POST "/campaigns/{campaign_id}/optimize")
POST "/suggest")
```

### ai

```text
GET "/capabilities")
GET "/settings")
PUT "/settings")
POST "/chat")
GET "/decisions")
GET "/logs")
```

### alerts

```text
GET "")
PUT "/{alert_id}/ack")
GET "/rules")
PUT "/rules/{rule_id}")
POST "/scan")
```

### auth

```text
POST "/login")
GET "/me")
GET "/users")
POST "/users")
PUT "/users/{user_id}")
DELETE "/users/{user_id}")
```

### bi

```text
GET "/metrics")
GET "/data-quality")
GET "/forecast-monitoring")
GET "/forecast-outcomes")
GET "/dashboard")
GET "/profit")
GET "/report")
```

### business_profiles

```text
GET "")
PUT "")
```

### compliance

```text
GET "/reports")
GET "/reports/{report_id}")
POST "/check")
```

### cross_border

```text
GET "/duty-rates")
POST "/duty-rates")
PUT "/duty-rates/{row_id}")
DELETE "/duty-rates/{row_id}")
GET "/logistics-routes")
POST "/logistics-routes")
PUT "/logistics-routes/{row_id}")
DELETE "/logistics-routes/{row_id}")
GET "/platform-fees")
POST "/platform-fees")
PUT "/platform-fees/{row_id}")
DELETE "/platform-fees/{row_id}")
GET "/compliance-rules")
POST "/compliance-rules")
PUT "/compliance-rules/{row_id}")
DELETE "/compliance-rules/{row_id}")
GET "/products/{product_id}/compliance")
POST "/products/{product_id}/compliance")
POST "/landed-cost")
```

### discovery

```text
GET "/trends")
POST "/trends/scan")
POST "/expand")
POST "/score/{product_id}")
POST "/pick")
GET "/performance/{product_id}")
POST "/trends/import")
GET "/trends/source")
GET "/scores")
```

### factory_network

```text
POST "/suppliers/{supplier_id}/portal-account")
PUT "/suppliers/{supplier_id}/verification")
GET "/portal/me")
GET "/portal/products")
POST "/portal/products")
PUT "/portal/products/{catalog_id}")
POST "/opportunities/match")
GET "/opportunities")
POST "/matches/{match_id}/promote")
GET "/opportunity-attribution")
```

### finance

```text
GET "/fx")
POST "/fx")
GET "/orders/{order_id}/detail")
POST "/orders/{order_id}/lines")
POST "/orders/{order_id}/fees")
GET "/settlement-reconciliation")
POST "/platform-settlements")
```

### knowledge

```text
GET "/docs")
POST "/docs")
PUT "/docs/{doc_id}")
DELETE "/docs/{doc_id}")
GET "/search")
GET "/candidates")
POST "/candidates/{candidate_id}/answer")
POST "/candidates/{candidate_id}/approve")
POST "/candidates/{candidate_id}/reject")
POST "/candidates/{candidate_id}/revoke")
GET "/learning/settings")
PUT "/learning/settings")
```

### launch

```text
GET "/context")
POST "")
GET "")
GET "/{run_id}")
GET "/{run_id}/steps")
POST "/{run_id}/actions/{action}")
POST "/{run_id}/sync")
GET "/{run_id}/events")
```

### listings

```text
GET "")
GET "/{listing_id}/publication-attempts")
POST "/generate")
PUT "/{listing_id}")
POST "/{listing_id}/optimize")
POST "/{listing_id}/review")
GET "/review-queue")
GET "/{listing_id}/reviews")
POST "/{listing_id}/review/approve")
POST "/{listing_id}/publish")
DELETE "/{listing_id}")
```

### me

```text
GET "/workspaces")
GET "/workspace-context")
POST "/workspaces/{workspace_id}/switch")
```

### orders

```text
GET "")
POST "/sync")
POST "/import")
GET "/export")
GET "/{order_id}")
POST "/{order_id}/ship")
PUT "/{order_id}/status")
```

### pricing

```text
GET "")
POST "/calc")
POST "/suggest")
```

### product_assets

```text
GET "/{product_id}/assets")
POST "/{product_id}/assets")
POST "/{product_id}/assets/{asset_id}/verify")
```

### product_channels

```text
GET "/{product_id}/channels")
```

### products

```text
GET "")
POST "")
POST "/collect_url")
POST "/collect_html")
GET "/export")
GET "/{product_id}")
PUT "/{product_id}")
DELETE "/{product_id}")
POST "/collect")
POST "/{product_id}/standardize")
PUT "/{product_id}/selected-offer")
GET "/{product_id}/overview")
```

### purchases

```text
POST "/from_forecast")
POST "")
POST "/dropship")
GET "")
PUT "/{po_id}")
POST "/{po_id}/receive")
DELETE "/{po_id}")
```

### refunds

```text
POST "")
GET "")
GET "/{refund_id}")
PUT "/{refund_id}/status")
POST "/{refund_id}/return_receive")
POST "/{refund_id}/refund")
```

### schedules

```text
GET "")
POST "")
PUT "/{schedule_id}")
DELETE "/{schedule_id}")
POST "/{schedule_id}/run")
```

### settlements

```text
POST "/generate")
GET "")
GET "/summary")
PUT "/{settle_id}")
```

### shops

```text
GET "")
POST "")
PUT "/{shop_id}")
DELETE "/{shop_id}")
GET "/{shop_id}/authorize_url")
GET "/callback/{platform}/{shop_id}")
POST "/{shop_id}/exchange_code")
POST "/{shop_id}/refresh")
POST "/{shop_id}/sync_orders")
GET "/{shop_id}/listing_readiness/{listing_id}")
GET "/{shop_id}/submissions/{submission_id}")
GET "/platforms")
GET "/platform_rules")
POST "/platform_rules/{platform}/check_updates")
GET "/category-mappings")
POST "/category-mappings")
DELETE "/category-mappings/{mapping_id}")
POST "/purge_demo_data")
```

### suppliers

```text
GET "")
POST "")
PUT "/{supplier_id}")
POST "/match")
GET "/forecast")
POST "/offers")
GET "/offers")
GET "/{supplier_id}")
POST "/{supplier_id}/score")
```

### support

```text
GET "/conversations")
POST "/conversations")
GET "/conversations/{conversation_id}")
POST "/conversations/{conversation_id}/reply")
POST "/conversations/{conversation_id}/auto_reply")
POST "/conversations/{conversation_id}/close")
```

### workbench

```text
GET "/todo")
GET "/overview")
```

### workflows

```text
POST "/runs/{run_id}/resume")
GET "/templates")
POST "/run")
GET "/runs")
GET "/runs/{run_id}")
```

## 文档介绍索引

根目录活文档按首个标题列出；方案不等于已实施。历史证据路径见完整文件目录。

|文档|标题/介绍|
|---|---|
|[AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md](../docs/AI_AGENT_OPERATING_SYSTEM_ARCHITECTURE.md)|AI Agent Operating System 架构冻结 V1.0|
|[AI原生能力升级方案.md](../docs/AI原生能力升级方案.md)|AI 原生跨境电商能力升级方案 V1.0（待论证稿）|
|[CODE_AND_DIRECTORY_STANDARD.md](../docs/CODE_AND_DIRECTORY_STANDARD.md)|代码与目录规范 V1.0|
|[CONTRACT.md](../docs/CONTRACT.md)|工程接口契约（CONTRACT）V1.0|
|[DECISIONS.md](../docs/DECISIONS.md)|技术选型与决策记录（ADR）|
|[DOCUMENT_MAP.md](../docs/DOCUMENT_MAP.md)|文档地图（DOCUMENT_MAP）|
|[FRONTEND_API_ALIGNMENT.md](../docs/FRONTEND_API_ALIGNMENT.md)|前端 API 契约对齐（FRONTEND_API_ALIGNMENT）|
|[FRONTEND_DESIGN_SYSTEM.md](../docs/FRONTEND_DESIGN_SYSTEM.md)|前端设计系统（FRONTEND_DESIGN_SYSTEM）|
|[FRONTEND_IMPLEMENTATION_PLAN.md](../docs/FRONTEND_IMPLEMENTATION_PLAN.md)|前端实施计划（FRONTEND_IMPLEMENTATION_PLAN）|
|[FRONTEND_INFORMATION_ARCHITECTURE.md](../docs/FRONTEND_INFORMATION_ARCHITECTURE.md)|前端信息架构（FRONTEND_INFORMATION_ARCHITECTURE）|
|[FRONTEND_PAGE_MATRIX.md](../docs/FRONTEND_PAGE_MATRIX.md)|前端页面矩阵（UX-00）|
|[FRONTEND_R3_APP_SHELL_DESIGN_BASELINE.md](../docs/FRONTEND_R3_APP_SHELL_DESIGN_BASELINE.md)|前端 R3 统一 AppShell 设计基线（FRONTEND_R3_APP_SHELL_DESIGN_BASELINE）|
|[FRONTEND_R3_BACKEND_CAPABILITY_MAP.md](../docs/FRONTEND_R3_BACKEND_CAPABILITY_MAP.md)|前端 R3 后端能力映射（FRONTEND_R3_BACKEND_CAPABILITY_MAP）|
|[FRONTEND_R3_PAGE_OWNERSHIP_MATRIX.md](../docs/FRONTEND_R3_PAGE_OWNERSHIP_MATRIX.md)|前端 R3 页面所有权矩阵（FRONTEND_R3_PAGE_OWNERSHIP_MATRIX）|
|[FRONTEND_R3_TASK_CONTRACT.md](../docs/FRONTEND_R3_TASK_CONTRACT.md)|前端 R3 任务契约（FRONTEND_R3_TASK_CONTRACT）|
|[FRONTEND_USER_JOURNEYS.md](../docs/FRONTEND_USER_JOURNEYS.md)|前端用户旅程与画像（UX-00）|
|[FRONTEND_UX_ACCEPTANCE.md](../docs/FRONTEND_UX_ACCEPTANCE.md)|前端体验统一优化 — 全旅程验收报告|
|[FRONTEND_UX_AUDIT.md](../docs/FRONTEND_UX_AUDIT.md)|前端 UX 审计报告（UX-00）|
|[FRONTEND_UX_PROGRESS.md](../docs/FRONTEND_UX_PROGRESS.md)|全平台前端信息架构与用户体验统一优化 — 进度追踪|
|[FRONTEND_V9_ACCEPTANCE.md](../docs/FRONTEND_V9_ACCEPTANCE.md)|FRONTEND V9 · 验收报告 v2（UX-F 全量终验）|
|[FRONTEND_V9_API_MAPPING.md](../docs/FRONTEND_V9_API_MAPPING.md)|FRONTEND V9 · API 映射（UX-A 架构冻结）|
|[FRONTEND_V9_BLUEPRINT_R1_GAP_ANALYSIS.md](../docs/FRONTEND_V9_BLUEPRINT_R1_GAP_ANALYSIS.md)|FRONTEND V9 · 蓝图 R1 增量设计规约（Gap Analysis）|
|[FRONTEND_V9_BLUEPRINT_R1_TASK_BREAKDOWN.md](../docs/FRONTEND_V9_BLUEPRINT_R1_TASK_BREAKDOWN.md)|FRONTEND V9 · 蓝图 R1 文件级实施任务分解|
|[FRONTEND_V9_CONTRACTS.md](../docs/FRONTEND_V9_CONTRACTS.md)|FRONTEND V9 · 冻结契约（UX-B 编码直接输入）|
|[FRONTEND_V9_DESIGN_SYSTEM.md](../docs/FRONTEND_V9_DESIGN_SYSTEM.md)|FRONTEND V9 · 设计系统（UX-A 架构冻结）|
|[FRONTEND_V9_IMPLEMENTATION_PLAN.md](../docs/FRONTEND_V9_IMPLEMENTATION_PLAN.md)|FRONTEND V9 · 实施计划（UX-A 架构冻结）|
|[FRONTEND_V9_MASTER_DESIGN.md](../docs/FRONTEND_V9_MASTER_DESIGN.md)|FRONTEND V9 · 总设计（UX-A 架构冻结）|
|[FRONTEND_V9_NAVIGATION.md](../docs/FRONTEND_V9_NAVIGATION.md)|FRONTEND V9 · 导航冻结（UX-A 架构冻结）|
|[FRONTEND_V9_PAGE_MATRIX.md](../docs/FRONTEND_V9_PAGE_MATRIX.md)|FRONTEND V9 · 全站页面矩阵（UX-A 产品冻结）|
|[FRONTEND_V9_PROGRESS.md](../docs/FRONTEND_V9_PROGRESS.md)|FRONTEND V9 · 全站前端重设计进度（事实源）|
|[FRONTEND_V9_RUNTIME_VERIFICATION.md](../docs/FRONTEND_V9_RUNTIME_VERIFICATION.md)|FRONTEND_V9_RUNTIME_VERIFICATION.md|
|[FRONTEND_V9_USER_JOURNEYS.md](../docs/FRONTEND_V9_USER_JOURNEYS.md)|FRONTEND V9 · 三空间用户旅程（UX-A 产品冻结）|
|[FRONTEND_V9_VISUAL_ACCEPTANCE.md](../docs/FRONTEND_V9_VISUAL_ACCEPTANCE.md)|FRONTEND_V9_VISUAL_ACCEPTANCE.md|
|[INCREMENT_DESIGN_LAUNCH_P0_CLOSURE.md](../docs/INCREMENT_DESIGN_LAUNCH_P0_CLOSURE.md)|增量设计：Launch Center P0 闭环（B01 动作执行 / B02 NBA / B10 Launch API / F01-F03 前端）|
|[INCREMENT_PRD_LAUNCH_P0_CLOSURE.md](../docs/INCREMENT_PRD_LAUNCH_P0_CLOSURE.md)|增量 PRD：Launch Center P0 闭环（B01/B02/B10 + F01/F02/F03）|
|[LAUNCH_CENTER_PRODUCT_DESIGN.md](../docs/LAUNCH_CENTER_PRODUCT_DESIGN.md)|Launch Center 产品设计 V2|
|[M4客服知识自进化方案与论证.md](../docs/M4客服知识自进化方案与论证.md)|M4 客服知识自进化 方案与论证（P2）|
|[PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md](../docs/PLATFORM_COMMERCE_WORKFLOW_ARCHITECTURE.md)|Platform Commerce Workflow 架构 V2|
|[PLATFORM_COMMERCE_WORKFLOW_GAP_ANALYSIS.md](../docs/PLATFORM_COMMERCE_WORKFLOW_GAP_ANALYSIS.md)|Platform Commerce Workflow 与 Launch Center 差距审计|
|[PLATFORM_WORKFLOW_E2E_MATRIX.md](../docs/PLATFORM_WORKFLOW_E2E_MATRIX.md)|Platform Workflow 验收矩阵 V2|
|[PLATFORM_WORKFLOW_MIGRATION_PLAN.md](../docs/PLATFORM_WORKFLOW_MIGRATION_PLAN.md)|Platform Workflow 迁移与安全计划 V2|
|[PLATFORM_WORKFLOW_PROGRESS.md](../docs/PLATFORM_WORKFLOW_PROGRESS.md)|Platform Workflow / Launch Center 进度|
|[PLATFORM_WORKFLOW_STATE_MODEL.md](../docs/PLATFORM_WORKFLOW_STATE_MODEL.md)|Platform Workflow 状态与迁移 V2|
|[PROJECT_MASTER_PLAN.md](../docs/PROJECT_MASTER_PLAN.md)|AI 跨境电商经营平台详细策划书|
|[UI_REFACTOR_BLUEPRINT.md](../docs/UI_REFACTOR_BLUEPRINT.md)|前端业务体验整改计划 R2|
|[UI_REFACTOR_BLUEPRINT_R3.md](../docs/UI_REFACTOR_BLUEPRINT_R3.md)|AI 跨境经营平台 V9.1 — R3 目标驱动式前端重构总蓝图|
|[V9_1_DIRECTORY_AND_FILE_PLAN.md](../docs/V9_1_DIRECTORY_AND_FILE_PLAN.md)|V9.1 前后端目录与文件落位清单|
|[V9_1_NEXT_EXECUTION_PLAN.md](../docs/V9_1_NEXT_EXECUTION_PLAN.md)|V9.1 下一步实施计划：B3 收尾与 AI 经营闭环|
|[WORKSPACE_MIGRATION_PROGRESS.md](../docs/WORKSPACE_MIGRATION_PROGRESS.md)|Workspace Migration Progress|
|[backup_restore_runbook.md](../docs/backup_restore_runbook.md)|SQLite 备份与恢复演练运维手册|
|[phase1_interfaces.md](../docs/phase1_interfaces.md)|Phase 1 接口契约（Workspace Identity）|
|[phase1_setting_scope_design.md](../docs/phase1_setting_scope_design.md)|P1-10 Setting 作用域隔离设计|
|[子代理实施索引-20260923.md](../docs/子代理实施索引-20260923.md)|并行实施追溯索引（2026-09-23）|
|[子代理实施索引-20260930.md](../docs/子代理实施索引-20260930.md)|子代理实施索引（2026-09-30）|
|[权限体系问题排查与专家探讨.md](../docs/权限体系问题排查与专家探讨.md)|权限体系问题排查与专家探讨|
|[角色权限体系梳理方案.md](../docs/角色权限体系梳理方案.md)|角色与权限体系梳理：方案与多轮论证|
|[角色界面差异化设计方案.md](../docs/角色界面差异化设计方案.md)|角色界面差异化设计方案（待论证）|
|[需求分析与详细设计说明书V8.0.md](../docs/需求分析与详细设计说明书V8.0.md)|AI原生跨境电商运营平台需求分析与详细设计说明书 V8.0（完整工程版）|
|[页面操作权限对照表.md](../docs/页面操作权限对照表.md)|页面-操作-权限 key 对照表（实施依据）|
|[项目介绍与功能地图.md](../docs/项目介绍与功能地图.md)|项目介绍与功能实现地图|
