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
