/**
 * 货源匹配（SU-04）纯函数模块。
 *
 * 布局：左商品要求 / 中央供应候选对比 / 右总成本·毛利假设·风险·缺项。
 * 红线（§5.13/§B.2）：缺物流费/税费禁当真利润——总利润只能标"假设"，
 * 不同币种必须显汇率日（缺=汇率未知）。
 */

/**
 * 对比两个供应商候选（纯函数）。
 * 按字段逐项比较，产出每行的"优劣"判定：
 * - price：低价优先（缺值不判优）；
 * - moq：低量优先；
 * - ship_days：短交期优先；
 * - 字段缺失记入 gaps（不伪造 0）。
 *
 * @param {object} a 候选 A。
 * @param {object} b 候选 B。
 * @returns {Array<{field:string, winner:'a'|'b'|'tie'|'unknown', detail:string}>}
 */
export function compareCandidates(a = {}, b = {}) {
  const rules = [
    { field: 'price', better: (x, y) => (x < y ? 'a' : y < x ? 'b' : 'tie') },
    { field: 'moq', better: (x, y) => (x < y ? 'a' : y < x ? 'b' : 'tie') },
    { field: 'ship_days', better: (x, y) => (x < y ? 'a' : y < x ? 'b' : 'tie') },
  ]
  return rules.map(({ field, better }) => {
    const av = a?.[field]
    const bv = b?.[field]
    if (av == null && bv == null) return { field, winner: 'unknown', detail: '双方均缺该字段' }
    if (av == null) return { field, winner: 'b', detail: 'A 缺该字段' }
    if (bv == null) return { field, winner: 'a', detail: 'B 缺该字段' }
    // 金额行：币种不同且没有可用的换算依据时禁止直接比数字（§5.13 口径）。
    // 后端 costing 是唯一换算权威；前端比选不做隐式汇率假设。
    if (field === 'price') {
      const ac = (a.currency || '').toUpperCase()
      const bc = (b.currency || '').toUpperCase()
      if (ac && bc && ac !== bc) {
        return {
          field, winner: 'unknown',
          detail: `币种不同（${ac} vs ${bc}），需报价折算后再比较，不可直接比金额`,
        }
      }
    }
    return { field, winner: better(Number(av), Number(bv)), detail: `${av} vs ${bv}` }
  })
}

/**
 * 判定候选缺项（物流费/税费/汇率日/成本币种）——缺项不得算真利润。
 *
 * @param {object} p
 * @param {number|null} [p.logisticsCost] 物流费。
 * @param {number|null} [p.taxCost] 税费。
 * @param {string} [p.currency] 成本币种。
 * @param {string} [p.analysisCurrency] 分析币种。
 * @param {string} [p.fxDate] 汇率日。
 * @returns {string[]} 缺项清单（空=可进入下一步）。
 */
export function missingForGrossProfit({ logisticsCost = null, taxCost = null, currency = '', analysisCurrency = '', fxDate = '' } = {}) {
  const gaps = []
  if (logisticsCost == null) gaps.push('缺物流费')
  if (taxCost == null) gaps.push('缺税费')
  if (currency && analysisCurrency && currency !== analysisCurrency && !fxDate) gaps.push('缺汇率日')
  return gaps
}

/**
 * 总成本 + 毛利假设（纯函数）。
 * 缺物流费/税费 → profit 为 null（禁当真利润），isAssumption=true。
 * 不同币种且缺 fxDate → 汇率未知标记。
 *
 * @param {object} p
 * @param {number|null} p.unitPrice 单价（成本币种）。
 * @param {number} [p.qty] 数量（默认 1）。
 * @param {number|null} [p.logisticsCost] 物流费（同币种）。
 * @param {number|null} [p.taxCost] 税费（同币种）。
 * @param {number|null} [p.sellPrice] 售价（目标市场币种）。
 * @param {string} [p.currency] 成本币种。
 * @param {string} [p.analysisCurrency] 分析币种。
 * @param {string} [p.fxDate] 汇率日。
 * @returns {{totalCost:number|null, profit:number|null, isAssumption:boolean, fxUnknown:boolean, gaps:string[]}}
 */
export function costAndGrossAssumption({
  unitPrice = null, qty = 1, logisticsCost = null, taxCost = null,
  sellPrice = null, currency = '', analysisCurrency = '', fxDate = '',
} = {}) {
  const gaps = missingForGrossProfit({ logisticsCost, taxCost, currency, analysisCurrency, fxDate })
  const fxUnknown = Boolean(currency && analysisCurrency && currency !== analysisCurrency && !fxDate)
  const known = unitPrice != null && logisticsCost != null && taxCost != null
  const totalCost = known ? Number(unitPrice) * Number(qty) + Number(logisticsCost) + Number(taxCost) : null
  const profit = (totalCost != null && sellPrice != null) ? Number(sellPrice) - totalCost : null
  // 缺任一成本项或汇率未知 → 只能当假设，不是真利润
  const isAssumption = totalCost == null || profit == null || fxUnknown
  return { totalCost, profit, isAssumption, fxUnknown, gaps }
}

/**
 * 展示串（供 MoneyValue 之外的角落使用；主展示走 MoneyValue 组件）。
 * @returns {string}
 */
export function profitLabel(view) {
  if (view.profit == null) return '—'
  const num = Number(view.profit).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return view.isAssumption ? `${num}（假设，非真利润）` : `${num}`
}

/**
 * 报价身份（选定/清除 PUT 用的 offer_id）。
 * 后端契约报价对象未单列 id，依赖 offer.id / offer.offer_id；缺失则回 null（无法选定）。
 *
 * @param {object} offer
 * @returns {number|null}
 */
export function offerId(offer = {}) {
  const id = offer.id ?? offer.offer_id ?? offer.offerId
  if (id == null || id === '') return null
  const n = Number(id)
  return Number.isFinite(n) ? n : null
}

/**
 * 库存文案（B3 展示修正）：把布尔的 in_stock 渲染成业务语言。
 * 原样输出 `true/false` 让用户看不懂，且容易被当成「有库存」误读。
 * 只做事实翻译，不做推断——null / 未知一律「—」。
 *
 * @param {boolean|null|undefined} value
 * @returns {'在库'|'缺货'|'—'}
 */
export function stockLabel(value) {
  if (value === true) return '在库'
  if (value === false) return '缺货'
  return '—'
}

/**
 * 归一化报价（防御式：兼容新契约嵌套 supplier 与旧扁平字段）。
 * 新契约：{price, currency, moq, ship_days, in_stock, created_at, valid_until,
 *   source_kind, verification_status, supplier:{...}, is_selected}。
 * 旧扁平：{supplier_name, price, currency, moq, ship_days, fx_date, logistics_cost, tax_cost}。
 * 不臆造任何字段——缺即留空/ null。
 *
 * @param {object} offer
 * @returns {object} 归一化形状（与视图列一一对应）。
 */
export function normalizeOffer(offer = {}) {
  const sup = offer.supplier || {}
  return {
    id: offerId(offer),
    price: offer.price ?? null,
    currency: offer.currency || '',
    moq: offer.moq ?? null,
    ship_days: offer.ship_days ?? null,
    in_stock: offer.in_stock ?? null,
    valid_until: offer.valid_until || '',
    source_kind: offer.source_kind || '',
    verification_status: offer.verification_status || '',
    created_at: offer.created_at || '',
    is_selected: Boolean(offer.is_selected),
    // 成本试算相关（新契约未列，旧扁平字段兼容携带；缺则留 null，由 costing 标"假设"）
    logistics_cost: offer.logistics_cost ?? null,
    tax_cost: offer.tax_cost ?? null,
    fx_date: offer.fx_date || '',
    supplier: {
      id: sup.id ?? null,
      name: sup.name ?? offer.supplier_name ?? '',
      region: sup.region ?? offer.region ?? '',
      supplier_type: sup.supplier_type ?? offer.supplier_type ?? offer.type ?? '',
      verification_status: sup.verification_status ?? '',
      rating: sup.rating ?? offer.rating ?? null,
      certifications: Array.isArray(sup.certifications) ? sup.certifications : [],
      capabilities: Array.isArray(sup.capabilities) ? sup.capabilities : [],
    },
  }
}

/**
 * 来源 / 核验 标签（诚实边界：未核验/爬取 → 「待核实」琥珀色，绝不假装已确认）。
 *
 * @param {string} [sourceKind] 来源类型（official/api/manual/scraped/...）。
 * @param {string} [verificationStatus] 核验状态（verified/unverified/scraped/pending/...）。
 * @returns {{source:{label:string,tone:string}, verification:{label:string,tone:string}}}
 */
export function sourceVerificationTags(sourceKind = '', verificationStatus = '') {
  const v = String(verificationStatus).toLowerCase()
  const verification = (() => {
    if (v === 'verified') return { label: '已核验', tone: 'success' }
    if (v === 'scraped' || v === 'unverified' || v === 'pending' || v === '') {
      // 未核验或爬取 → 待核实（琥珀）
      return { label: '待核实', tone: 'warning' }
    }
    return { label: '待核实', tone: 'warning' }
  })()

  const s = String(sourceKind).toLowerCase()
  const sourceMap = {
    official: { label: '官方', tone: 'success' },
    api: { label: 'API', tone: 'info' },
    manual: { label: '人工', tone: 'warning' },
    scraped: { label: '爬取', tone: 'warning' },
  }
  const source = sourceMap[s] || (s ? { label: s, tone: 'neutral' } : { label: '未知', tone: 'neutral' })
  return { source, verification }
}

/**
 * 询价内容文案（复制用，非发送）。
 * 汇总 商品 + 会话经营条件 + 采购要求 + 意向报价；无任何"已发送"话术。
 * 缺项如实写「待补」，不臆造。
 *
 * @param {object} p
 * @param {object} [p.product] 选中商品（{id, title}）。
 * @param {object} [p.profile] 会话画像（{targetMarket, budget, risk}）。
 * @param {object} [p.requirements] 采购要求（{targetSellPrice, marketCurrency}）。
 * @param {object|null} [p.offer] 归一化后的意向报价（null=未选定）。
 * @returns {string}
 */
export function buildInquiryCopy({ product = {}, profile = {}, requirements = {}, offer = null } = {}) {
  const name = product.title
    || (product.id != null ? `商品 #${product.id}` : '未选择商品')
  const lines = ['【询价内容（仅供向供应商参考，本系统不代发送）】', '']

  lines.push(`商品：${name}${product.id != null ? `（ID ${product.id}）` : ''}`)

  const market = []
  if (profile?.targetMarket) market.push(`目标市场=${profile.targetMarket}`)
  if (profile?.budget) market.push(`预算=${profile.budget}`)
  if (profile?.risk) market.push(`风险偏好=${profile.risk}`)
  lines.push(`经营条件（会话内参考，仅本页）：${market.length ? market.join('，') : '待补'}`)

  const reqs = []
  if (requirements?.targetSellPrice != null) {
    reqs.push(`目标售价=${requirements.targetSellPrice}${requirements.marketCurrency ? ' ' + requirements.marketCurrency : ''}`)
  }
  if (requirements?.marketCurrency) reqs.push(`市场币种=${requirements.marketCurrency}`)
  lines.push(`采购要求：${reqs.length ? reqs.join('，') : '待补'}`)

  if (offer) {
    const s = offer.supplier?.name || '（未具名供应商）'
    lines.push(`意向报价：${s}｜${offer.price ?? '—'} ${offer.currency || ''}`.trim()
      + `｜MOQ ${offer.moq ?? '—'}｜交期 ${offer.ship_days ?? '—'} 天｜有效期 ${offer.valid_until || '未填写'}`)
  } else {
    lines.push('意向报价：未选定（成本试算将自动取最低在库报价）')
  }

  lines.push('')
  lines.push('（说明：以上内容由本页汇总，复制后请自行通过供应商渠道询价；系统不提供发送能力。）')
  return lines.join('\n')
}

/**
 * 最低在库报价（成本引擎"未选定报价时自动取最低在库报价"指代对象，供诚实说明展示）。
 * 无在库报价返回 null。
 *
 * @param {Array} offers 归一化报价数组。
 * @returns {object|null}
 */
export function lowestInStockOffer(offers = []) {
  const inStock = (offers || []).filter((o) => Number(o.in_stock) > 0 && o.price != null)
  if (!inStock.length) return null
  return inStock.reduce((best, o) => {
    if (best == null) return o
    return Number(o.price) < Number(best.price) ? o : best
  }, null)
}

/**
 * 后端 costing（POST /api/pricing/calc）结果 → 诚实视图。
 *
 * 铁律：成本与毛利只消费后端返回值，前端绝不用本地公式替代财务核算；
 * 「成本依据报价」必须来自响应的 offer_id（引擎实际采用者），与用户选定
 * 不一致时显式标注回退——不允许无提示回退仍显示为「用户选定」。
 *
 * @param {object|null} [calc] calc_profit 响应。
 * @param {number|null} [selectedOfferId] 用户当前选定报价 id（供一致性对照）。
 * @returns {object|null} null = 无结果（调用方渲染「待核算」）。
 */
export function costingResultView(calc, selectedOfferId = null) {
  if (!calc || typeof calc !== 'object' || calc.offer_id == null) return null
  const gaps = []
  if (calc.landed_cost_applied === false) {
    gaps.push('目的国未提供：关税 / 进口 VAT / 清关费未计入')
  }
  if (!calc.hs_code) {
    gaps.push('无 HS 编码：关税按兜底税率估算')
  }
  if (calc.warehouse_id == null) {
    gaps.push('未绑定海外仓：未计库存持有成本')
  }
  const isUserSelected = selectedOfferId != null && Number(calc.offer_id) === Number(selectedOfferId)
  const selectedIgnored = selectedOfferId != null && !isUserSelected
  // 后端 offer_state 是唯一权威（MISSING/EXPIRED/OUT_OF_STOCK/UNVERIFIED/OK）。
  // 前端不自行推断；仅把状态翻译成展示文案与阻断提示。
  const offerState = calc.offer_state || null
  const offerLimits = Array.isArray(calc.offer_limits) ? calc.offer_limits : []
  const stateNote = {
    MISSING: '选定报价已失效，成本改按最低在库价',
    EXPIRED: '选定报价已过期（保留偏好，仅供试算）',
    OUT_OF_STOCK: '选定报价缺货（保留偏好，仅供试算）',
    UNVERIFIED: '选定报价来源待核实（仅供试算）',
  }[offerState] || ''
  const basisNote = isUserSelected
    ? (stateNote || '用户选定（成本按该报价）')
    : (selectedIgnored ? '自动最低在库价（已选定报价未被采用）' : '自动最低在库价')
  return {
    offerId: calc.offer_id,
    offerState,
    offerLimits,
    isUserSelected,
    selectedIgnored,
    basisNote,
    // 店铺口径回显：shop_id 为空 = 通用试算，不得展示为某店铺确认利润。
    shopId: calc.shop_id ?? null,
    // 市场口径：后端已按「显式目的国 > 店铺市场」归一，前端只展示不回推。
    market: calc.market || '',
    isGenericEstimate: calc.is_generic_estimate !== false && calc.shop_id == null,
    purchaseCny: calc.purchase_cost ?? null,
    logisticsCny: calc.logistics_cost ?? null,
    totalCostCny: calc.cost_total_cny ?? null,
    costBreakdown: calc.cost_breakdown || {},
    price: calc.price ?? null,
    profit: calc.profit ?? null,
    margin: calc.margin ?? null,
    currency: calc.currency || 'USD',
    fx: calc.fx ?? null,
    gaps,
    isAssumption: gaps.length > 0,
  }
}
