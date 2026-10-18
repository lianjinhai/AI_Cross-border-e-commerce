/**
 * Workspace 空间菜单树（R3-2A：4+1 入口收敛，替换蓝图 R1 的 8 域 26 项）。
 *
 * 结构：**4 个高频经营入口 + 1 个专业工具柜**（`tools` 可折叠，用 el-sub-menu 渲染）：
 *   mybiz   我的生意 → 经营首页 / 我的待办
 *   goods   我的商品 → 商品库 / 上线中心 / 合规报告 / 合规工作台
 *   orders  我的订单 → 订单工作台 / 发货备货 / 售后退款 / 客户消息 / 结算对账
 *   revenue 我的收益 → BI 总览 / 财务台账 / 到岸成本 / 预测 / 定价试算
 *   tools   全部工具 → 其余全部既有页面（货源/市场/渠道/内容/增长/AI/设置）
 *
 * **铁律（R3-2A）**：
 * 1. path 全部保持不变（302 查表、深链、legacy-redirects 30 条零影响）；
 * 2. **不隐藏任何既有页面**——8 域时期的 34 条叶子 + 5 条 settings 叶子全部保留，
 *    仅改变其在树中的归位（收敛为入口，不是删功能）；
 * 3. 角色可见性**不在本树内自带过滤**，统一走 filter.js（buildDomains/whitelistForRole），
 *    禁止双事实源；本文件仅描述「结构」。
 *
 * 旧域 key 变更（蓝图 R1 → R3-2A）：workbench→mybiz、discovery→goods、
 * channel/supply/optimize/ai/settings→tools。orders/revenue(finance) 语义延续。
 */
export const WORKSPACE_DOMAINS = [
  {
    key: 'mybiz',
    label: '我的生意',
    icon: 'Odometer',
    children: [
      { path: '/app', label: '经营首页', icon: 'Odometer' },
      { path: '/app/tasks', label: '我的待办', icon: 'List', badge: 'tasks' },
    ],
  },
  {
    key: 'goods',
    label: '我的商品',
    icon: 'Goods',
    children: [
      { path: '/app/products', label: '商品库', icon: 'Goods' },
      { path: '/app/launch', label: '上线中心', icon: 'Position' },
      { path: '/app/compliance', label: '合规报告', icon: 'CircleCheck' },
      { path: '/app/compliance/approvals', label: '合规工作台', icon: 'Finished', badge: 'approvals' },
    ],
  },
  {
    key: 'orders',
    label: '我的订单',
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
    key: 'revenue',
    label: '我的收益',
    icon: 'TrendCharts',
    children: [
      { path: '/app/analytics/bi', label: '经营总览与 BI', icon: 'TrendCharts' },
      { path: '/app/analytics/finance', label: '财务台账', icon: 'Money' },
      { path: '/app/analytics/landed-cost', label: '到岸成本', icon: 'Ship' },
      { path: '/app/analytics/forecast', label: '预测与数据质量', icon: 'DataLine' },
      { path: '/app/pricing', label: '定价与利润试算', icon: 'Coin' },
    ],
  },
  {
    // collapsible=true：侧栏用 el-sub-menu 折叠渲染（旧 8 域低频功能的统一归宿）。
    key: 'tools',
    label: '全部工具',
    icon: 'Tools',
    collapsible: true,
    children: [
      // 货源与采购
      { path: '/app/supply/sourcing', label: '货源发现', icon: 'Compass' },
      { path: '/app/supply/suppliers', label: '供应商库', icon: 'OfficeBuilding' },
      { path: '/app/supply/matching', label: '货源匹配', icon: 'Connection' },
      { path: '/app/supply/purchases', label: '采购单', icon: 'ShoppingCartFull' },
      // 市场与渠道
      { path: '/app/market/discovery', label: '市场机会', icon: 'Search' },
      { path: '/app/market/candidates', label: '商品候选池', icon: 'Star' },
      { path: '/app/channels', label: '渠道推荐', icon: 'Promotion' },
      { path: '/app/channels/shops', label: '店铺管理', icon: 'Shop' },
      // 商品内容
      { path: '/app/listings', label: 'Listing 工作台', icon: 'Document' },
      { path: '/app/products/assets', label: '素材中心', icon: 'Picture' },
      // 增长与风险
      { path: '/app/ads', label: '广告与转化', icon: 'Promotion' },
      { path: '/app/risk/alerts', label: '商品与店铺诊断', icon: 'Warning' },
      { path: '/app/optimization/experiments', label: '策略实验', icon: 'DataAnalysis' },
      // AI 与自动化
      { path: '/app/ai/actions', label: 'AI 行动中心', icon: 'MagicStick', badge: 'approvals' },
      { path: '/app/ai/workflows', label: '工作流', icon: 'Connection' },
      { path: '/app/ai/agent-runs', label: 'Agent 运行', icon: 'Timer' },
      { path: '/app/ai/knowledge', label: '知识库', icon: 'Reading' },
      { path: '/app/ai/decisions', label: '决策依据', icon: 'DocumentChecked' },
      // 设置（R3-2A 由账户菜单回归工具柜，路由守卫 requiresOwner 不变）
      { path: '/app/settings/workspace', label: '空间信息', icon: 'Setting' },
      { path: '/app/settings/ai', label: 'AI 与集成', icon: 'Cpu' },
      { path: '/app/settings/team', label: '用户与角色', icon: 'UserFilled' },
      { path: '/app/settings/credentials', label: '凭据管理', icon: 'Key' },
      { path: '/app/settings/plan', label: '套餐管理', icon: 'CreditCard' },
    ],
  },
]
