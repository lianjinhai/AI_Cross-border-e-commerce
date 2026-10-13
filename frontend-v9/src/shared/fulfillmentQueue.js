/**
 * 发货/代发/备货（OR-03）纯函数模块：三列分列 + 主操作推导。
 *
 * 数据源：purchases.js（采购已有）；平台备货端点未核（§7#6）→ 备货区"待接入/人工处理"。
 * 红线：备货与代发必须独立展示；可关联不等同；物流轨迹待接入（§7#1）。
 */

/** 履约模式枚举。 */
export const FULFILL_MODES = ['stocking', 'dropship', 'purchase']

/**
 * 三列分列（纯函数）：备货 / 代发 / 采购。
 * - purchase：purchases.js 真实数据（供货商/价格/下单/收货）；
 * - dropship：purchases 中 supplier_type==='dropship' 或 item.mode==='dropship' 的子集；
 * - stocking：平台备货端点未核 → 恒空 + 待接入标记（不伪造数据）。
 *
 * @param {Array} purchases 采购单列表。
 * @returns {{stocking: {items:Array, apiGap:boolean}, dropship: Array, purchase: Array}}
 */
export function splitFulfillmentQueues(purchases = []) {
  const list = Array.isArray(purchases) ? purchases : []
  const dropship = list.filter((p) => p && (p.supplier_type === 'dropship' || p.mode === 'dropship'))
  const purchase = list.filter((p) => p && !dropship.includes(p))
  // 平台备货端点未核（§7#6）：apiGap=true，items 恒空
  return {
    stocking: { items: [], apiGap: true },
    dropship,
    purchase,
  }
}

/**
 * 订单行级备货信息提取（批准量/备妥量/外部参考号/仓库/证据）。
 * 缺项一律 null（不渲染 0）；外部参考号仅在平台状态真实返回时展示。
 *
 * @param {object} item 采购/备货 DTO。
 * @returns {{approvedQty:number|null, readyQty:number|null, externalRef:string|null, warehouse:string|null, evidence:string|null}}
 */
export function stockingEvidence(item = {}) {
  return {
    approvedQty: item.approved_qty ?? null,
    readyQty: item.ready_qty ?? null,
    externalRef: item.external_ref || null,
    warehouse: item.warehouse || null,
    evidence: item.evidence || item.evidence_url || null,
  }
}

/**
 * 单一主操作推导（纯函数）：按当前履约模式给且仅给一个 primary。
 * - dropship → 委托代发（若已有采购单 → 查看发运）；
 * - stocking → 平台备货待接入，主操作=人工在平台处理（禁用，tooltip）；
 * - purchase → 创建采购（未下单）/ 登记收货（已下单未收货）。
 *
 * @param {object} p
 * @param {string} [p.mode] 履约模式。
 * @param {object} [p.item] 当前行 DTO。
 * @returns {{code:string, label:string, kind:'primary', disabled:boolean, reason:string}}
 */
export function primaryFulfillAction({ mode = 'purchase', item = {} } = {}) {
  if (mode === 'stocking') {
    return { code: 'STOCKING_MANUAL', label: '人工在平台处理', kind: 'primary', disabled: true, reason: '平台备货待接入' }
  }
  if (mode === 'dropship') {
    if (item.status === 'received' || item.status === 'shipped') {
      return { code: 'DROP_SHIP_VIEW', label: '查看发运登记', kind: 'primary', disabled: false, reason: '物流轨迹待接入，当前仅显示发运登记状态' }
    }
    return { code: 'DROP_SHIP_DELEGATE', label: '委托代发', kind: 'primary', disabled: false, reason: '' }
  }
  // purchase
  if (item.status === 'received') {
    return { code: 'PURCHASE_DONE', label: '已收货', kind: 'primary', disabled: true, reason: '无需操作' }
  }
  if (item.status === 'submitted' || item.status === 'draft') {
    return { code: 'PURCHASE_RECEIVE', label: '登记收货', kind: 'primary', disabled: false, reason: '' }
  }
  return { code: 'PURCHASE_CREATE', label: '创建采购', kind: 'primary', disabled: false, reason: '' }
}

/**
 * 采购行展示字段提取（供货商/价格/下单/收货，缺项 null）。
 * @param {object} p 采购单 DTO。
 * @returns {object}
 */
export function purchaseRow(p = {}) {
  return {
    id: p.id ?? null,
    supplier: p.supplier_name || p.supplier || null,
    price: p.price ?? p.total_price ?? null,
    currency: p.currency || '',
    status: p.status || '',
    orderedAt: p.ordered_at || p.created_at || null,
    receivedAt: p.received_at || null,
    qty: p.qty ?? p.quantity ?? null,
  }
}
