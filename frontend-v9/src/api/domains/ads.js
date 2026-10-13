import api from '../../shared/api/client'

/**
 * ads 域（契约 §4.2）：对应 backend/app/routers/ads.py（前缀 /ads）。
 * 预算优化的审批-执行-结果三态经独立 /actions 域（ApprovalPanel 统一消费）。
 */

/** 广告 ROI 报告：GET /ads/campaigns → {campaigns[], summary}。 */
export async function fetchCampaigns() {
  return (await api.get('/ads/campaigns')).data
}

/** 创建广告活动：POST /ads/campaigns → 活动 DTO（草稿态）。 */
export async function createCampaign(data = {}) {
  return (await api.post('/ads/campaigns', data)).data
}

/** 预算优化：POST /ads/campaigns/{id}/optimize → 提案（status/action_id/approval_required）。 */
export async function optimizeCampaign(campaignId) {
  return (await api.post(`/ads/campaigns/${campaignId}/optimize`)).data
}

/** AI 选词：POST /ads/suggest {product_id, platform} → {keywords[], reason, ...}。 */
export async function suggestKeywords({ productId, platform = 'facebook' } = {}) {
  return (await api.post('/ads/suggest', { product_id: productId, platform })).data
}
