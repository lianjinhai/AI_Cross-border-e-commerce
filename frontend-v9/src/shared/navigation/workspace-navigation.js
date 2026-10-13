/**
 * Workspace 空间菜单树（蓝图 R1：8 业务域 + settings 下沉，/app/*）。
 *
 * 域 key 变更（旧→新）：home→workbench、market+product→discovery、
 * fulfill+aftersale→orders、analytics→finance、optimization→optimize、aiops→ai。
 * settings 下沉到账户菜单（主导航不占 8 域名额）；路由与 requiresOwner 守卫保留。
 * path 全部不变（302 查表、深链、295 测试零影响）。
 */
export const WORKSPACE_DOMAINS = [
  {
    key: 'workbench',
    label: '工作台',
    icon: 'Odometer',
    children: [
      { path: '/app', label: '经营首页', icon: 'Odometer' },
      { path: '/app/tasks', label: '我的待办', icon: 'List', badge: 'tasks' },
    ],
  },
  {
    key: 'discovery',
    label: '发现与商品',
    icon: 'Goods',
    children: [
      { path: '/app/market/discovery', label: '市场机会', icon: 'Search' },
      { path: '/app/market/candidates', label: '商品候选池', icon: 'Star' },
      { path: '/app/products', label: '商品库', icon: 'Goods' },
      { path: '/app/listings', label: 'Listing 工作台', icon: 'Document' },
      { path: '/app/launch', label: '上线中心', icon: 'Position' },
      { path: '/app/compliance', label: '合规报告', icon: 'CircleCheck' },
      { path: '/app/compliance/approvals', label: '合规工作台', icon: 'Finished' },
      { path: '/app/products/assets', label: '素材中心', icon: 'Picture' },
    ],
  },
  {
    key: 'supply',
    label: '货源与采购',
    icon: 'OfficeBuilding',
    children: [
      { path: '/app/supply/sourcing', label: '货源发现', icon: 'Compass' },
      { path: '/app/supply/suppliers', label: '供应商库', icon: 'OfficeBuilding' },
      { path: '/app/supply/matching', label: '货源匹配', icon: 'Connection' },
      { path: '/app/supply/purchases', label: '采购单', icon: 'ShoppingCartFull' },
    ],
  },
  {
    key: 'channel',
    label: '渠道与店铺',
    icon: 'Link',
    children: [
      { path: '/app/channels', label: '渠道推荐', icon: 'Promotion' },
      { path: '/app/channels/shops', label: '店铺管理', icon: 'Shop' },
    ],
  },
  {
    key: 'orders',
    label: '订单与服务',
    icon: 'List',
    children: [
      { path: '/app/orders', label: '订单工作台', icon: 'List' },
      { path: '/app/fulfillment', label: '发货/代发/备货', icon: 'Van' },
      { path: '/app/refunds', label: '售后退款', icon: 'RefreshLeft' },
      { path: '/app/support', label: '客户消息', icon: 'ChatDotRound' },
      { path: '/app/settlements', label: '结算与对账', icon: 'Wallet' },
    ],
  },
  {
    key: 'optimize',
    label: '经营优化',
    icon: 'Promotion',
    children: [
      { path: '/app/pricing', label: '定价与利润试算', icon: 'Coin' },
      { path: '/app/ads', label: '广告与转化', icon: 'Promotion' },
      { path: '/app/risk/alerts', label: '商品与店铺诊断', icon: 'Warning' },
      { path: '/app/optimization/experiments', label: '策略实验', icon: 'DataAnalysis' },
    ],
  },
  {
    key: 'finance',
    label: '财务与分析',
    icon: 'TrendCharts',
    children: [
      { path: '/app/analytics/bi', label: '经营总览与 BI', icon: 'TrendCharts' },
      { path: '/app/analytics/finance', label: '真实利润', icon: 'Money' },
      { path: '/app/analytics/landed-cost', label: '到岸成本', icon: 'Ship' },
      { path: '/app/analytics/forecast', label: '预测与数据质量', icon: 'DataLine' },
    ],
  },
  {
    key: 'ai',
    label: 'AI 与自动化',
    icon: 'MagicStick',
    children: [
      { path: '/app/ai/actions', label: 'AI 行动中心', icon: 'MagicStick', badge: 'approvals' },
      { path: '/app/ai/workflows', label: '工作流', icon: 'Connection' },
      { path: '/app/ai/agent-runs', label: 'Agent 运行', icon: 'Timer' },
      { path: '/app/ai/knowledge', label: '知识库', icon: 'Reading' },
      { path: '/app/ai/decisions', label: '决策依据', icon: 'DocumentChecked' },
    ],
  },
]
