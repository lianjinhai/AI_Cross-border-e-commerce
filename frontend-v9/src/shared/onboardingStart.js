/**
 * 新手起步 · 资源起点卡（B2；纯函数，供 vitest 直测 + Onboarding.vue 消费）。
 *
 * 设计契约（不可违反）：
 * - 只做「推荐」，绝不做「保存」：本模块不碰 sessionStorage / 服务端，
 *   选择落地由 shared/onboardingProfile.js 负责（persisted 恒 false）。
 * - 推荐必须诚实：经营事实不足时回退到 A（研究商品方向）并给出「可随时更换」理由，
 *   绝不假装已判定或已保存。
 * - 推荐采用「直接映射」对齐三卡语义（与 workspaceHomeView.resolveEntryProfile 的
 *   画像语义一致：C↔STORE_OWNER / B↔FACTORY / A↔NEW_USER）；不直接透传该函数，
 *   因其对「缺失店铺事实」一律回退 UNKNOWN，会使「仅检测到商品/货源」的用户无法落到 Card B。
 *
 * 信号来源（组件侧构建，见 buildStartSignals）：
 *  - 销售店铺：fetchShops 返回 items 中 type!=='source' 的记为销售店铺。
 *  - 商品/货源：fetchProducts({page:1}).total > 0 视为已有商品/货源资源（Card B）。
 *
 * @typedef {Object} StartSignals
 * @property {boolean} [hasSalesShop]   是否有已连接销售店铺（精确布尔，优先于计数）。
 * @property {number}  [salesShopCount] 销售店铺数（替代 hasSalesShop 的计数）。
 * @property {boolean} [hasGoods]       是否有商品或工厂资源（精确布尔，优先于计数）。
 * @property {number}  [productTotal]   商品总数（替代 hasGoods 的计数）。
 */

/**
 * 推荐与 workspaceHomeView.resolveEntryProfile 的画像语义一致：
 *   C ↔ STORE_OWNER（有销售店铺） / B ↔ FACTORY（有商品或工厂资源） / A ↔ NEW_USER（其余）。
 * 但本函数采用「直接映射」而非透传 resolveEntryProfile：后者在「店铺事实缺失」时
 * 一律回退 UNKNOWN，会使「仅检测到商品/货源（无店铺）」的用户无法落到 Card B，
 * 与任务明确的「有商品或工厂资源 → Card B」冲突。直接按三卡语义判断更诚实且可用。
 */

/**
 * 三张资源起点卡：纯展示元数据（不含业务逻辑）。
 * - A 无商品、无店铺：主线 研究商品方向 → /app/market/discovery?journey=j0
 * - B 有商品或工厂资源：主线 供给研究/货源 → /app/supply/matching
 * - C 已有销售店铺：主线 推进上线 → /app/launch
 */
export const START_CARDS = {
  A: {
    id: 'A',
    title: '无商品、无店铺',
    subtitle: '从零开始，先找到方向',
    mainLine: '研究商品方向',
    primaryPath: '/app/market/discovery?journey=j0',
    primaryLabel: '研究商品方向',
    secondaryLabel: '',
    secondaryPath: '',
    secondaryNote: '沿「选品 → 货源 → 成本/风险 → 渠道 → 商品准备」用 J0 向导一步步跑通',
  },
  B: {
    id: 'B',
    title: '有商品或工厂资源',
    subtitle: '已有供给，聚焦货源与匹配',
    mainLine: '供给研究 / 货源',
    primaryPath: '/app/supply/matching',
    primaryLabel: '去供给匹配',
    secondaryLabel: '研究工厂 SKU',
    secondaryPath: '/app/products',
    secondaryNote: '可先补充工厂 SKU 研究上下文，再进入匹配',
  },
  C: {
    id: 'C',
    title: '已有销售店铺',
    subtitle: '已具备销售渠道，直接推进',
    mainLine: '推进上线',
    primaryPath: '/app/launch',
    primaryLabel: '推进上线',
    secondaryLabel: '',
    secondaryPath: '',
    secondaryNote: '',
  },
}

/** 默认清单（未知卡 / 未选时回退；对齐原 GENERIC 路径，避免死端）。 */
const DEFAULT_PATH_ITEMS = [
  { label: '浏览商品池', path: '/app/products' },
  { label: '绑定销售店铺', path: '/app/channels/shops' },
  { label: '创建工作流', path: '/app/launch' },
]

/** 各卡对应第 3 步经营路径清单；未知卡 → DEFAULT_PATH_ITEMS。 */
const PATH_ITEMS_BY_CARD = {
  A: [
    { label: '研究商品方向', path: '/app/market/discovery?journey=j0' },
    { label: '连接销售店铺', path: '/app/channels/shops' },
    { label: '创建上线流程', path: '/app/launch' },
  ],
  B: [
    { label: '供给 / 货源研究', path: '/app/supply/matching' },
    { label: '核对商品资料', path: '/app/products' },
    { label: '连接销售店铺', path: '/app/channels/shops' },
  ],
  C: [
    { label: '推进上线流程', path: '/app/launch' },
    { label: '处理订单 / 履约', path: '/app/orders' },
    { label: '查看店铺表现', path: '/app/analytics/bi' },
  ],
}

/**
 * 由真实信号推导推荐资源起点卡（只读，不保存）。
 * 直接按三卡语义判断：有销售店铺 → C；否则有商品/货源 → B；其余（含事实不足）→ A。
 * 缺事实一律回退 A 并诚实说明理由，绝不假装已判定或已保存。
 * @param {StartSignals} signals
 * @returns {{card:'A'|'B'|'C', reason:string}}
 */
export function recommendedStartCard(signals = {}) {
  const s = signals || {}
  const hasSalesShop = typeof s.hasSalesShop === 'boolean'
    ? s.hasSalesShop
    : (typeof s.salesShopCount === 'number' ? s.salesShopCount > 0 : null)
  const hasGoods = typeof s.hasGoods === 'boolean'
    ? s.hasGoods
    : (typeof s.productTotal === 'number' ? s.productTotal > 0 : null)

  if (hasSalesShop === true) {
    return { card: 'C', reason: '检测到已连接销售店铺，建议直接进入「推进上线」' }
  }
  if (hasGoods === true) {
    return { card: 'B', reason: '检测到已有商品或货源资源，建议先做供给 / 货源研究' }
  }
  // 既无店铺也无商品，或信号不足以判断 → 回退 A，并明示可随时更换（不假装已判定）
  return { card: 'A', reason: '暂未检测到商品或店铺，建议从「研究商品方向」开始（可随时更换）' }
}

/**
 * 由 API 原始数据构建推荐信号（组件侧：fetchShops + fetchProducts）。
 * 销售店铺 = items 中 type!=='source'；商品资源 = total>0。
 * @param {{shopItems?:Array, productTotal?:number}} data
 * @returns {StartSignals}
 */
export function buildStartSignals({ shopItems = [], productTotal = 0 } = {}) {
  const items = Array.isArray(shopItems) ? shopItems : []
  const salesShopCount = items.filter((s) => s && s.type !== 'source').length
  const total = Number(productTotal) || 0
  return {
    hasSalesShop: salesShopCount > 0,
    salesShopCount,
    hasGoods: total > 0,
    productTotal: total,
  }
}

/**
 * 第 3 步经营路径清单（按所选卡重排）。
 * @param {'A'|'B'|'C'|string} card 资源起点卡 id（来自 saveSessionProfile.direction）
 * @returns {Array<{label:string, path?:string}>}
 */
export function pathItemsForCard(card) {
  return PATH_ITEMS_BY_CARD[card] || DEFAULT_PATH_ITEMS
}
