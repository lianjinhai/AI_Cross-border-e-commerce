/**
 * 订单详情展示口径（S5，纯函数）。
 *
 * 铁律：订单金额/成本是**订单币种快照**；采购单是供应商 CNY 应付，两者不可相加。
 * 这里只做分组与提示，不做任何汇率换算（换算只能走服务端 costing/finance）。
 */
import { formatOrderMoney } from './orderView'

const FEE_LABELS = {
  commission: '平台佣金',
  payment: '支付费',
  tax: '税费',
  shipping: '物流费',
  storage: '仓储费',
  adjustment: '其他调整',
}

export function feeLabel(type) {
  return FEE_LABELS[type] || type || '未分类费用'
}

/** 费用按币种汇总成一行文本；空 → '—'。 */
export function feeTotalsText(detail) {
  const totals = detail?.fees?.total_by_currency || {}
  const parts = Object.entries(totals).map(([cur, amount]) => formatOrderMoney({ currency: cur, amount }))
  return parts.length ? parts.join(' · ') : '—'
}

/** 采购单汇总（CNY 应付），空 → '—'。 */
export function purchaseTotalsText(detail) {
  const totals = detail?.purchases?.total_by_currency || {}
  const parts = Object.entries(totals).map(([cur, amount]) => formatOrderMoney({ currency: cur, amount }))
  return parts.length ? parts.join(' · ') : '—'
}

/**
 * 风险/口径提示：只列真实存在的限制，不编造。
 * @returns {Array<{level: string, text: string}>}
 */
export function detailWarnings(detail) {
  const out = []
  if (!detail) return out
  const totals = detail.totals || {}
  if (totals.mixed_currency) {
    out.push({
      level: 'warning',
      text: `订单金额为 ${totals.currency || '未知币种'} 原值；关联采购单是 CNY 应付，两者不可相加，也不在本页换算。`,
    })
  }
  if (detail.fulfillment && detail.fulfillment.tracking_available === false) {
    out.push({
      level: 'info',
      text: detail.fulfillment.note || '物流轨迹未接入：仅展示单号。',
    })
  }
  if (detail.order && !detail.order.shop_id) {
    out.push({ level: 'warning', text: '该订单未绑定店铺：无法判断销售渠道归属。' })
  }
  if (detail.order && !detail.order.product_id) {
    out.push({ level: 'warning', text: '该订单未绑定商品：成本与采购联动不可用。' })
  }
  if (!(detail.purchases?.items || []).length) {
    out.push({ level: 'info', text: '没有通过 sales_order_id 关联的采购单（不代表未采购）。' })
  }
  return out
}

/** 退款合计（按退款单币种假定与订单一致，仅展示原始金额）。 */
export function refundTotalText(detail) {
  const rows = detail?.refunds || []
  if (!rows.length) return '—'
  const currency = detail?.order?.currency
  const sum = rows.reduce((acc, row) => acc + Number(row.amount || 0), 0)
  return formatOrderMoney({ currency, amount: sum })
}
