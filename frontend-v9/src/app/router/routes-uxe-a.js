/**
 * UX-E 前半（管理侧）路由数组（契约 §3 meta 约定，并行期约定：不改 index.js，
 * 由总调度统一合并）。meta 逐字沿用 index.js 冻结值，仅 component 不同。
 *
 * 合并对照表：
 *   UXE_A_ROOT（顶层路由，替换 /console/login 的 StubPage）
 *   UXE_A_CONSOLE_CHILDREN（替换 consoleChildren 中 overview/tenants/audit/maintenance）
 *   UXE_A_FACTORY_CHILDREN（替换 factoryChildren 中 products）
 *
 * 302 确认：/login → /console/login（legacy-redirects #1）、
 * /factory-portal → /factory/products（#13）、/platform-admin → /console/overview
 * （#28，?tab=audit → /console/audit）目标均已指向本批真实页面，无需改查表。
 */

/** 顶层：全空间共用登录页。 */
export const UXE_A_ROOT = [
  {
    path: '/console/login',
    component: () => import('../../pages/auth/Login.vue'),
    meta: { space: 'console', title: '登录' },
  },
]

/** Console 子路由（4 页：旧 /platform-admin 572 行巨页拆分）。 */
export const UXE_A_CONSOLE_CHILDREN = [
  {
    path: 'overview',
    component: () => import('../../pages/console/Overview.vue'),
    meta: { space: 'console', domain: '平台管理', title: '平台总览' },
  },
  {
    path: 'tenants',
    component: () => import('../../pages/console/Tenants.vue'),
    meta: { space: 'console', domain: '平台管理', title: '租户管理' },
  },
  {
    path: 'audit',
    component: () => import('../../pages/console/Audit.vue'),
    meta: { space: 'console', domain: '平台管理', title: '访问审计' },
  },
  {
    path: 'maintenance',
    component: () => import('../../pages/console/Maintenance.vue'),
    meta: { space: 'console', domain: '平台管理', title: '维护' },
  },
  // ── 蓝图 R1 包 3 追加（PC-03/04/05，P2 骨架；现有 4 条不动） ──
  {
    path: 'adapters',
    component: () => import('../../pages/console/Adapters.vue'),
    meta: { space: 'console', domain: '平台管理', title: 'Adapter 认证中心' },
  },
  {
    path: 'rules',
    component: () => import('../../pages/console/Rules.vue'),
    meta: { space: 'console', domain: '平台管理', title: '数据源与规则' },
  },
  {
    path: 'ai-resources',
    component: () => import('../../pages/console/AiResources.vue'),
    meta: { space: 'console', domain: '平台管理', title: 'AI 资源与成本' },
  },
]

/** Factory 子路由（工厂门户主页）。 */
export const UXE_A_FACTORY_CHILDREN = [
  // ── 蓝图 R1 包 3 追加（FP-01/03/04/05，P2 骨架；现有 products 主入口保留） ──
  {
    path: '',
    component: () => import('../../pages/factory/FactoryHome.vue'),
    meta: { space: 'factory', domain: '工厂门户', title: '工厂首页' },
  },
  {
    path: 'products',
    component: () => import('../../pages/factory/FactoryProducts.vue'),
    meta: { space: 'factory', domain: '工厂门户', title: '产品与产能' },
  },
  {
    path: 'stocking',
    component: () => import('../../pages/factory/StockingTasks.vue'),
    meta: { space: 'factory', domain: '工厂门户', title: '备货/贴标任务' },
  },
  {
    path: 'fulfillment',
    component: () => import('../../pages/factory/FulfillmentHistory.vue'),
    meta: { space: 'factory', domain: '工厂门户', title: '工厂履约与历史' },
  },
  {
    path: 'capability',
    component: () => import('../../pages/factory/Capability.vue'),
    meta: { space: 'factory', domain: '工厂门户', title: '报价与供货能力' },
  },
]
