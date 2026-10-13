import { createProduct } from '../api/domains/products'

/**
 * 选品一键转入商品池（UX-C J1 断链归零）：把 discovery 候选/评分行转成
 * POST /products 的创建载荷。纯函数集中在文件前半段，vitest 直测。
 *
 * 红线：不伪造候选缺失的字段——候选没有的 attrs 键不进载荷；
 * 来源平台原样透传（source_platform），便于商品池区分演示/真实来源。
 */

/** 候选 → 商品创建载荷；返回 null 表示候选缺少最小可建字段（title）。 */
export function candidateToProductPayload(candidate = {}) {
  const title = typeof candidate.title === 'string' ? candidate.title.trim() : ''
  if (!title) return null
  const attrs = {}
  if (candidate.supplier_price != null) attrs.supplier_price = candidate.supplier_price
  if (candidate.sale_price != null) attrs.sale_price = candidate.sale_price
  if (candidate.price != null && attrs.sale_price == null) attrs.sale_price = candidate.price
  const payload = {
    title,
    category: candidate.category || '',
    attrs,
  }
  if (candidate.source_platform) payload.source_platform = candidate.source_platform
  if (candidate.source_url) payload.source_url = candidate.source_url
  return payload
}

/** 批量转池：逐条构造并创建；返回 {created[], failed:[{index, reason}]}。 */
export async function transferCandidates(candidates = []) {
  const created = []
  const failed = []
  for (let i = 0; i < candidates.length; i += 1) {
    const payload = candidateToProductPayload(candidates[i])
    if (!payload) {
      failed.push({ index: i, reason: '候选缺少标题，无法转入商品池' })
      continue
    }
    try {
      // eslint-disable-next-line no-await-in-loop
      const product = await createProduct(payload)
      created.push(product)
    } catch (err) {
      failed.push({
        index: i,
        reason: err?.response?.data?.detail?.message || err?.message || '创建失败',
      })
    }
  }
  return { created, failed }
}
