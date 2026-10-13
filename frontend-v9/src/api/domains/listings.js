import api from '../../shared/api/client'

/**
 * listings 域（契约 §4.2）：对应 backend/app/routers/listings.py（前缀 /listings）。
 *
 * 偏离说明：后端**无** GET /listings/{id} 详情端点，契约的 fetchListing(id)
 * 拆为真实存在的回执/评审端点（fetchListingReceipts / fetchListingReviews）。
 */

/** Listing 列表：GET /listings → {items[], total}。 */
export async function fetchListings({ page, status } = {}) {
  return (await api.get('/listings', { params: { page_num: page, status } })).data
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

/** 评审裁定：POST /listings/{id}/review/approve。 */
export async function approveReview(id, verdict) {
  return (await api.post(`/listings/${id}/review/approve`, { verdict })).data
}

/** 发布：POST /listings/{id}/publish {shop_ids} → 发布回执 DTO。 */
export async function publish(id, { shopIds = [] } = {}) {
  return (await api.post(`/listings/${id}/publish`, { shop_ids: shopIds })).data
}
