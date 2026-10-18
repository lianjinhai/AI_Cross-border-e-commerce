/**
 * 订单视图纯函数：金额格式化与店铺标签。
 *
 * 这些函数只负责「渲染文本」，不触碰任何组件状态，便于单元测试（vitest）独立覆盖。
 * 设计底线（B1 批次 P0 正确性）：币种必须真实、店铺范围必须可信，绝不静默回退到 "$"。
 */

/** 把数值格式化为带千分位、固定两位小数的字符串（如 1280 -> "1,280.00"）。 */
function fmtNumber(amount) {
  return Number(amount).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/**
 * 订单金额渲染：前缀使用订单真实币种。
 *
 * 规则：
 *  - row.currency 为空/缺失 -> 返回 "—"（绝不静默回退到 "$"，也绝不渲染成 "$0.00"）。
 *  - row.amount 缺失（null/undefined/空串/NaN）-> 返回 "—"，不把缺失金额 coerce 成 0.00。
 *  - 真实数字 0 -> "CNY 0.00"（合法值，必须照常渲染）。
 *  - 示例：CNY 1,280.00 / USD 12.50。
 */
export function formatOrderMoney(row = {}) {
  const currency = row.currency
  if (currency === null || currency === undefined || String(currency).trim() === '') {
    return '—'
  }
  const amount = row.amount
  // 缺失金额：不去碰 0.00，避免把「无数据」伪装成「零销售额」。
  if (amount === null || amount === undefined || amount === '' || Number.isNaN(Number(amount))) {
    return '—'
  }
  const num = Number(amount)
  if (!Number.isFinite(num)) {
    return '—'
  }
  return `${String(currency).toUpperCase()} ${fmtNumber(num)}`
}

/**
 * 订单店铺标签：优先展示店铺名，其次回退到 "#店铺ID"，最后才是 "—"。
 *
 * 回退链：row.shop_name -> `#${row.shop_id}` -> "—"。
 */
export function orderShopLabel(row = {}) {
  if (row.shop_name && String(row.shop_name).trim() !== '') {
    return row.shop_name
  }
  if (row.shop_id !== null && row.shop_id !== undefined && String(row.shop_id).trim() !== '') {
    return `#${row.shop_id}`
  }
  return '—'
}
