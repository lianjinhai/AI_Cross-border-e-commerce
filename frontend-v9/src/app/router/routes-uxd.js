/**
 * UX-D 经营闭环页路由数组（契约 §3 meta 约定 → 蓝图 R1 域标签同步）。
 *
 * 特殊约定（并行期）：**不修改 src/app/router/index.js**（该文件由总调度合并），
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
 * meta.space/title 逐字沿用 index.js 冻结值（保证面包屑叶与守卫行为不变）；
 * meta.domain 随蓝图 R1 8 域同步（任务分解 §A.5，仅文本）：
 * 货源中心→货源与采购、订单履约→订单与服务、客户售后→订单与服务、
 * 经营优化→经营优化（不变）、数据分析→财务与分析。
 * FN-02：settlements 域归属改 finance（财务与分析）。
 */

export const UXD_ROUTES = [
  {
    path: 'supply/suppliers',
    component: () => import('../../pages/supply/Suppliers.vue'),
    meta: { space: 'app', domain: '货源与采购', title: '供应商库' },
  },
  {
    path: 'supply/purchases',
    component: () => import('../../pages/supply/Purchases.vue'),
    meta: { space: 'app', domain: '货源与采购', title: '采购单' },
  },
  {
    path: 'orders',
    component: () => import('../../pages/fulfillment/Orders.vue'),
    meta: { space: 'app', domain: '订单与服务', title: '订单工作台' },
  },
  {
    path: 'settlements',
    component: () => import('../../pages/fulfillment/Settlements.vue'),
    meta: { space: 'app', domain: '财务与分析', title: '结算与对账' },
  },
  {
    path: 'refunds',
    component: () => import('../../pages/aftersale/Refunds.vue'),
    meta: { space: 'app', domain: '订单与服务', title: '售后退款' },
  },
  {
    path: 'support',
    component: () => import('../../pages/aftersale/Support.vue'),
    meta: { space: 'app', domain: '订单与服务', title: '客户消息' },
  },
  {
    path: 'pricing',
    component: () => import('../../pages/optimization/Pricing.vue'),
    meta: { space: 'app', domain: '经营优化', title: '定价与利润试算' },
  },
  {
    path: 'ads',
    component: () => import('../../pages/optimization/Ads.vue'),
    meta: { space: 'app', domain: '经营优化', title: '广告与转化' },
  },
  {
    path: 'risk/alerts',
    component: () => import('../../pages/optimization/RiskAlerts.vue'),
    meta: { space: 'app', domain: '经营优化', title: '商品与店铺诊断' },
  },
  {
    path: 'analytics/bi',
    component: () => import('../../pages/analytics/Bi.vue'),
    meta: { space: 'app', domain: '财务与分析', title: '经营总览与 BI' },
  },
  {
    path: 'analytics/finance',
    component: () => import('../../pages/analytics/Finance.vue'),
    meta: { space: 'app', domain: '财务与分析', title: '财务台账' },
  },
  {
    path: 'analytics/landed-cost',
    component: () => import('../../pages/analytics/LandedCost.vue'),
    meta: { space: 'app', domain: '财务与分析', title: '到岸成本' },
  },
  // ── 蓝图 R1 P0 补齐：导航叶子可点（真实页未交付，先挂 StubPage 防 404，标记待接入） ──
  // P1 真实页已由包 2 交付（sourcing/matching/fulfillment/forecast 替换 StubPage）；
  // optimization/experiments 仍为 P2 待接入，保持 StubPage。
  {
    path: 'supply/sourcing',
    component: () => import('../../pages/supply/Sourcing.vue'),
    meta: { space: 'app', domain: '货源与采购', title: '货源发现' },
  },
  {
    path: 'supply/matching',
    component: () => import('../../pages/supply/Matching.vue'),
    meta: { space: 'app', domain: '货源与采购', title: '货源匹配' },
  },
  {
    path: 'fulfillment',
    component: () => import('../../pages/fulfillment/Fulfillment.vue'),
    meta: { space: 'app', domain: '订单与服务', title: '发货/代发/备货' },
  },
  {
    path: 'optimization/experiments',
    component: () => import('../../app/pages/StubPage.vue'),
    meta: { space: 'app', domain: '经营优化', title: '策略实验' },
  },
  {
    path: 'analytics/forecast',
    component: () => import('../../pages/analytics/Forecast.vue'),
    meta: { space: 'app', domain: '财务与分析', title: '预测与数据质量' },
  },
  // ── 蓝图 R1 CH-01/CH-03：渠道推荐 + 店铺详情（R3-1A E09 起改由 index.js 唯一挂载；
  //    原两条同 path 声明已移除，消除展开顺序导致的占位页命中风险）──
]
