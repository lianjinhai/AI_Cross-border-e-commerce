/**
 * Workspace 空间菜单树（契约 §2.2：11 业务域，/app/*）。
 *
 * 结构沿用 UX-02 冻结的 11 域语义（frontend/src/composables/navigation.js 平移），
 * 仅按 FRONTEND_V9_NAVIGATION.md §1 将路径映射为 /app 前缀；域 key 以 V9 导航
 * 冻结文档为准（optimize→optimization、admin→settings）。
 * 参数详情路由（/app/products/:id、/app/listings/:id、/app/launch/:id）路由化但
 * 不入侧栏（hidden 语义见 types.js），由列表行进入。
 */
export const WORKSPACE_DOMAINS = [
  {
    key: 'home',
    label: '首页',
    icon: 'Odometer',
    children: [
      { path: '/app', label: '经营工作台', icon: 'Odometer' },
    ],
  },
  {
    key: 'market',
    label: '市场机会',
    icon: 'Search',
    children: [
      { path: '/app/market/discovery', label: '商品发现', icon: 'Search' },
    ],
  },
  {
    key: 'product',
    label: '商品经营',
    icon: 'Goods',
    children: [
      { path: '/app/products', label: '商品池', icon: 'Goods' },
      { path: '/app/listings', label: 'Listing 工作台', icon: 'Document' },
      { path: '/app/launch', label: '上线中心', icon: 'Position' },
      { path: '/app/compliance', label: '合规报告中心', icon: 'CircleCheck' },
      { path: '/app/compliance/approvals', label: '合规工作台', icon: 'Finished' },
    ],
  },
  {
    key: 'supply',
    label: '货源中心',
    icon: 'OfficeBuilding',
    children: [
      { path: '/app/supply/suppliers', label: '供应商库', icon: 'OfficeBuilding' },
      { path: '/app/supply/purchases', label: '采购单', icon: 'ShoppingCartFull' },
    ],
  },
  {
    key: 'channel',
    label: '销售渠道',
    icon: 'Link',
    children: [
      { path: '/app/channels/shops', label: '店铺授权', icon: 'Link' },
    ],
  },
  {
    key: 'fulfill',
    label: '订单履约',
    icon: 'List',
    children: [
      { path: '/app/orders', label: '订单管理', icon: 'List' },
      { path: '/app/settlements', label: '账期结算', icon: 'Wallet' },
    ],
  },
  {
    key: 'aftersale',
    label: '客户售后',
    icon: 'ChatDotRound',
    children: [
      { path: '/app/refunds', label: '售后管理', icon: 'RefreshLeft' },
      { path: '/app/support', label: '智能客服', icon: 'ChatDotRound' },
    ],
  },
  {
    key: 'optimization',
    label: '经营优化',
    icon: 'Promotion',
    children: [
      { path: '/app/pricing', label: '动态定价', icon: 'Coin' },
      { path: '/app/ads', label: '广告增长', icon: 'Promotion' },
      { path: '/app/risk/alerts', label: '风险巡检', icon: 'Warning' },
    ],
  },
  {
    key: 'analytics',
    label: '数据分析',
    icon: 'TrendCharts',
    children: [
      { path: '/app/analytics/bi', label: 'BI 经营分析', icon: 'TrendCharts' },
      { path: '/app/analytics/finance', label: '财务工作台', icon: 'Money' },
      { path: '/app/analytics/landed-cost', label: '到岸成本配置', icon: 'Ship' },
    ],
  },
  {
    key: 'aiops',
    label: 'AI 运营',
    icon: 'MagicStick',
    children: [
      { path: '/app/ai/knowledge', label: '知识库', icon: 'Reading' },
      { path: '/app/ai/decisions', label: 'AI 决策依据', icon: 'DocumentChecked' },
      { path: '/app/ai/workflows', label: 'AI 工作流', icon: 'MagicStick' },
    ],
  },
  {
    key: 'settings',
    label: '设置与管理',
    icon: 'Setting',
    children: [
      { path: '/app/settings/ai', label: 'AI 与集成设置', icon: 'Setting' },
      { path: '/app/settings/team', label: '用户与角色', icon: 'UserFilled' },
    ],
  },
]
