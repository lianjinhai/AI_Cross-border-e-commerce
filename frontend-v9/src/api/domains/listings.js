import api from '../../shared/api/client'

/**
 * listings 域（契约 §4.2）：对应 backend/app/routers/listings.py（前缀 /listings）。
 *
 * 偏离说明：后端**无** GET /listings/{id} 详情端点，契约的 fetchListing(id)
 * 拆为真实存在的回执/评审端点（fetchListingReceipts / fetchListingReviews）。
 */

/** Listing 列表：GET /listings → {items[], total}。 */
export async function fetchListings({ page, status, platform, productId, pageSize } = {}) {
  return (await api.get('/listings', {
    params: { page_num: page, status, platform, product_id: productId, page_size: pageSize },
  })).data
}

/**
 * 按 id 取 Listing 详情：后端无 GET /listings/{id}，经列表端点按页检索
 * （page_size 放大 + 逐页回退，最多 5 页；未命中抛出 404 语义错误）。
 */
export async function fetchListingById(id) {
  for (let page = 1; page <= 5; page += 1) {
    const data = await fetchListings({ page, pageSize: 100 })
    const hit = (data?.items || []).find((item) => Number(item.id) === Number(id))
    if (hit) return hit
    if (!data?.items?.length) break
  }
  const err = new Error('Listing 不存在或已删除')
  err.status = 404
  throw err
}

/** 发布回执列表：GET /listings/{id}/publication-attempts（PublicationReceipts 数据源）。 */
export async function fetchListingReceipts(id) {
  return (await api.get(`/listings/${id}/publication-attempts`)).data
}

/** 评审记录：GET /listings/{id}/reviews。 */
export async function fetchListingReviews(id) {
  return (await api.get(`/listings/${id}/reviews`)).data
}

/** 生成 Listing：POST /listings/generate → 生成结果（含 AI 建议三段式数据）。 */
export async function generate(data = {}) {
  return (await api.post('/listings/generate', data)).data
}

/** 更新 Listing：PUT /listings/{id} → Listing DTO。 */
export async function updateListing(id, data = {}) {
  return (await api.put(`/listings/${id}`, data)).data
}

/** 优化 Listing：POST /listings/{id}/optimize → 优化结果（含 AI 建议三段式数据）。 */
export async function optimize(id, data = {}) {
  return (await api.post(`/listings/${id}/optimize`, data)).data
}

/** 提交合规评审：POST /listings/{id}/review。 */
export async function submitReview(id) {
  return (await api.post(`/listings/${id}/review`)).data
}

/** 评审审批（人工）：POST /listings/{id}/review/approve {note}（合规审批人专属）。 */
export async function approveReview(id, note) {
  return (await api.post(`/listings/${id}/review/approve`, { note })).data
}

/** 发布：POST /listings/{id}/publish {shop_id}（单店；缺省=本地模拟）→ 发布结果。 */
export async function publish(id, { shopId = null } = {}) {
  return (await api.post(`/listings/${id}/publish`, { shop_id: shopId })).data
}

/** 删除 Listing：DELETE /listings/{id}。 */
export async function removeListing(id) {
  return (await api.delete(`/listings/${id}`)).data
}
