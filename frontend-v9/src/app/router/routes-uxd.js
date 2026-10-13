/**
 * UX-D 经营闭环页路由数组（契约 §3 meta 约定）。
 *
 * 特殊约定（并行期）：**不修改 src/app/router/index.js**（该文件由 UX-C 工程师持有），
 * 本数组由总调度后续合并——用下列条目替换 index.js appChildren 中对应 path 的
 * StubPage 挂载（path/meta 与 index.js 现有条目逐一对应，仅 component 不同）：
 *
 *   supply/suppliers  → ../../pages/supply/Suppliers.vue
 *   supply/purchases  → ../../pages/supply/Purchases.vue
 *   orders            → ../../pages/fulfillment/Orders.vue
 *   settlements       → ../../pages/fulfillment/Settlements.vue
 *   refunds           → ../../pages/aftersale/Refunds.vue
 *   support           → ../../pages/aftersale/Support.vue
 *   pricing           → ../../pages/optimization/Pricing.vue
 *   ads               → ../../pages/optimization/Ads.vue
 *   risk/alerts       → ../../pages/optimization/RiskAlerts.vue
 *   analytics/bi      → ../../pages/analytics/Bi.vue
 *   analytics/finance → ../../pages/analytics/Finance.vue
 *   analytics/landed-cost → ../../pages/analytics/LandedCost.vue
 *
 * meta 逐字沿用 index.js 冻结值（space/domain/title），保证面包屑与守卫行为不变。
 */

export const UXD_ROUTES = [
  {
    path: 'supply/suppliers',
    component: () => import('../../pages/supply/Suppliers.vue'),
    meta: { space: 'app', domain: '货源中心', title: '供应商库' },
  },
  {
    path: 'supply/purchases',
    component: () => import('../../pages/supply/Purchases.vue'),
    meta: { space: 'app', domain: '货源中心', title: '采购单' },
  },
  {
    path: 'orders',
    component: () => import('../../pages/fulfillment/Orders.vue'),
    meta: { space: 'app', domain: '订单履约', title: '订单管理' },
  },
  {
    path: 'settlements',
    component: () => import('../../pages/fulfillment/Settlements.vue'),
    meta: { space: 'app', domain: '订单履约', title: '账期结算' },
  },
  {
    path: 'refunds',
    component: () => import('../../pages/aftersale/Refunds.vue'),
    meta: { space: 'app', domain: '客户售后', title: '售后管理' },
  },
  {
    path: 'support',
    component: () => import('../../pages/aftersale/Support.vue'),
    meta: { space: 'app', domain: '客户售后', title: '智能客服' },
  },
  {
    path: 'pricing',
    component: () => import('../../pages/optimization/Pricing.vue'),
    meta: { space: 'app', domain: '经营优化', title: '动态定价' },
  },
  {
    path: 'ads',
    component: () => import('../../pages/optimization/Ads.vue'),
    meta: { space: 'app', domain: '经营优化', title: '广告增长' },
  },
  {
    path: 'risk/alerts',
    component: () => import('../../pages/optimization/RiskAlerts.vue'),
    meta: { space: 'app', domain: '经营优化', title: '风险巡检' },
  },
  {
    path: 'analytics/bi',
    component: () => import('../../pages/analytics/Bi.vue'),
    meta: { space: 'app', domain: '数据分析', title: 'BI 经营分析' },
  },
  {
    path: 'analytics/finance',
    component: () => import('../../pages/analytics/Finance.vue'),
    meta: { space: 'app', domain: '数据分析', title: '财务工作台' },
  },
  {
    path: 'analytics/landed-cost',
    component: () => import('../../pages/analytics/LandedCost.vue'),
    meta: { space: 'app', domain: '数据分析', title: '到岸成本配置' },
  },
]
