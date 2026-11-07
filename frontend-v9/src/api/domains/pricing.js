import api from '../../shared/api/client'

/**
 * pricing 域（契约 §4.2）：对应 backend/app/routers/pricing.py（前缀 /pricing）。
 * 利润口径与 BI / 到岸成本同源（services/costing.calc_profit）。
 * 「采纳建议价」经 products.updateProduct 写入 attrs.sale_price（costing 取价口径）。
 */

/** 定价记录列表：GET /pricing → {items[], total}（最新在前）。 */
export async function fetchPricingRecords({ productId, page } = {}) {
  return (await api.get('/pricing', {
    params: { product_id: productId, page_num: page },
  })).data
}

/** 利润试算：POST /pricing/calc {product_id, price?, destination_country?, ...} → 成本明细。 */
export async function calcProfit(data = {}) {
  return (await api.post('/pricing/calc', data)).data
}

/** AI 定价建议：POST /pricing/suggest {product_id} → 建议结果（新定价记录）。 */
export async function suggestPrice(productId) {
  return (await api.post('/pricing/suggest', { product_id: productId })).data
}

/**
 * 核价报价轮次（M2-A）：GET /pricing/rounds {product_id, limit} → {items[], total}（新→旧）。
 * 只读：写入入口在 Launch 动作（REPORT_PRICE / ACCEPT_PRICE / COUNTER_PRICE），
 * 定价页不允许绕过流程写轮次，否则「谁批的、依据哪份成本」就断了。
 */
export async function fetchPriceRounds({ productId, limit } = {}) {
  return (await api.get('/pricing/rounds', {
    params: { product_id: productId, limit },
  })).data
}
