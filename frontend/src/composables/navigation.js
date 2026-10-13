/**
 * 前端信息架构（UX-02）：把侧栏菜单定义与角色过滤从 Layout.vue 抽出为纯模块，
 * 便于单元测试与复用（项目未装 @vue/test-utils，菜单逻辑必须是纯函数）。
 *
 * 冻结口径见 docs/FRONTEND_INFORMATION_ARCHITECTURE.md §2：一级 11 域。
 * 抽出的仅为「导航结构 + 可见性过滤」，不改变任何页面本体或路由语义。
 */

/**
 * 业务侧 11 个一级域。结构 {key,label,icon,children:[{path,label,icon}]}。
 * icon 一律沿用现网已用的 @element-plus/icons-vue 名称（全局注册于 main.js）。
 */
export const BUSINESS_DOMAINS = [
  {
    key: 'home',
    label: '首页',
    icon: 'Odometer',
    children: [
      { path: '/dashboard', label: '经营工作台', icon: 'Odometer' },
    ],
  },
  {
    key: 'market',
    label: '市场机会',
    icon: 'Search',
    children: [
      { path: '/discovery', label: '商品发现', icon: 'Search' },
    ],
  },
  {
    key: 'product',
    label: '商品经营',
    icon: 'Goods',
    children: [
      { path: '/products', label: '商品池', icon: 'Goods' },
      { path: '/listings', label: 'Listing 工作台', icon: 'Document' },
      { path: '/launch', label: '上线中心', icon: 'Position' },
      { path: '/compliance-workbench', label: '合规工作台', icon: 'Finished' },
      { path: '/compliance', label: '合规检测', icon: 'CircleCheck' },
    ],
  },
  {
    key: 'supply',
    label: '货源中心',
    icon: 'OfficeBuilding',
    children: [
      { path: '/suppliers', label: '供应商', icon: 'OfficeBuilding' },
    ],
  },
  {
    key: 'channel',
    label: '销售渠道',
    icon: 'Link',
    children: [
      { path: '/shops', label: '店铺授权', icon: 'Link' },
    ],
  },
  {
    key: 'fulfill',
    label: '订单履约',
    icon: 'List',
    children: [
      { path: '/orders', label: '订单管理', icon: 'List' },
      { path: '/settlements', label: '账期结算', icon: 'Wallet' },
    ],
  },
  {
    key: 'aftersale',
    label: '客户售后',
    icon: 'ChatDotRound',
    children: [
      { path: '/refunds', label: '售后管理', icon: 'RefreshLeft' },
      { path: '/support', label: '智能客服', icon: 'ChatDotRound' },
    ],
  },
  {
    key: 'optimize',
    label: '经营优化',
    icon: 'Promotion',
    children: [
      { path: '/pricing', label: '动态定价', icon: 'Coin' },
      { path: '/ads', label: '广告增长', icon: 'Promotion' },
      { path: '/alerts', label: '风险巡检', icon: 'Warning' },
    ],
  },
  {
    key: 'analytics',
    label: '数据分析',
    icon: 'TrendCharts',
    children: [
      { path: '/bi', label: 'BI 经营分析', icon: 'TrendCharts' },
      { path: '/finance', label: '财务工作台', icon: 'Money' },
    ],
  },
  {
    key: 'aiops',
    label: 'AI 运营',
    icon: 'MagicStick',
    children: [
      { path: '/knowledge', label: '知识库', icon: 'Reading' },
      { path: '/ai-decisions', label: 'AI 决策依据', icon: 'DocumentChecked' },
      { path: '/workflows', label: 'AI 工作流', icon: 'MagicStick' },
    ],
  },
  {
    key: 'admin',
    label: '设置与管理',
    icon: 'Setting',
    children: [
      { path: '/settings', label: 'AI 设置', icon: 'Setting' },
      { path: '/users', label: '用户与角色', icon: 'UserFilled' },
    ],
  },
]

/** PLATFORM_ADMIN 专属域（原样保留，不并入 11 域）。 */
export const PLATFORM_DOMAINS = [
  {
    key: 'platform',
    label: '平台管理',
    icon: 'Platform',
    children: [
      { path: '/platform-admin', label: '平台控制台', icon: 'Platform' },
      { path: '/platform-admin?tab=audit', label: '访问审计', icon: 'Document' },
    ],
  },
]

/** FACTORY_COLLABORATOR 专属域（原样保留）。 */
export const FACTORY_DOMAINS = [
  {
    key: 'factory',
    label: '工厂门户',
    icon: 'OfficeBuilding',
    children: [
      { path: '/factory-portal', label: '产品与产能', icon: 'OfficeBuilding' },
    ],
  },
]

/** 合规员可见路径白名单（与 permissions.js 的 APPROVER_PATHS 语义一致）。 */
export const COMPLIANCE_ALLOWED_PATHS = new Set([
  '/compliance-workbench', '/dashboard', '/bi', '/listings', '/compliance', '/launch',
])

/** 非 OWNER（OPERATOR/READ_ONLY）隐藏路径（与旧 Layout 语义一致）。 */
export const NON_OWNER_HIDDEN_PATHS = new Set([
  '/settings', '/users', '/compliance-workbench',
])

/** 展平所有域的叶子路径（用于构造白名单）。 */
function allChildPaths(domains) {
  return domains.flatMap((domain) => domain.children.map((child) => child.path))
}

/**
 * 按路径白名单过滤域：仅保留 `allowedPaths` 内的子项；空域丢弃。
 * 纯函数——不修改入参，返回新的域/子项对象。
 *
 * @param {Array} domains 域数组。
 * @param {Set<string>|string[]} allowedPaths 允许保留的 path 集合。
 * @returns {Array} 过滤后的新数组。
 */
export function filterDomainsByPaths(domains, allowedPaths) {
  const allowed = allowedPaths instanceof Set ? allowedPaths : new Set(allowedPaths)
  return domains
    .map((domain) => ({
      ...domain,
      children: domain.children.filter((child) => allowed.has(child.path)),
    }))
    .filter((domain) => domain.children.length > 0)
}

/**
 * 按角色构造可见域数组，规则与旧 Layout.vue 的 `menus` computed 语义等价。
 *
 * @param {object} p
 * @param {string} [p.roleKey=''] 新角色枚举（大写，Context 优先；见 permissions.roleKey）。
 * @param {boolean} [p.canManageMembers=false] 是否可见「用户与角色」（canAdmin）。
 * @returns {Array} 该角色应见的域数组。
 */
export function buildDomains({ roleKey = '', canManageMembers = false } = {}) {
  if (roleKey === 'PLATFORM_ADMIN') return PLATFORM_DOMAINS
  if (roleKey === 'FACTORY_COLLABORATOR') return FACTORY_DOMAINS

  // 合规员：仅白名单路径，空域丢弃。
  if (roleKey === 'COMPLIANCE') {
    return filterDomainsByPaths(BUSINESS_DOMAINS, COMPLIANCE_ALLOWED_PATHS)
  }

  // 非 OWNER（OPERATOR/READ_ONLY/未知）：隐藏管理入口与合规工作台。
  if (roleKey !== 'OWNER') {
    const allowed = allChildPaths(BUSINESS_DOMAINS).filter((p) => !NON_OWNER_HIDDEN_PATHS.has(p))
    return filterDomainsByPaths(BUSINESS_DOMAINS, new Set(allowed))
  }

  // OWNER：全量；「用户与角色」仅在具备成员管理权限时保留。
  if (!canManageMembers) {
    const allowed = allChildPaths(BUSINESS_DOMAINS).filter((p) => p !== '/users')
    return filterDomainsByPaths(BUSINESS_DOMAINS, new Set(allowed))
  }
  return BUSINESS_DOMAINS
}
