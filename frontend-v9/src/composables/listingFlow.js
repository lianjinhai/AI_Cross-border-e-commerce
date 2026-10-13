/**
 * Listing 单页分步流纯函数（UX-C J2：生成→编辑预览→合规→发布→回执，无断点）。
 *
 * 步骤推进是**纯推导**：由 Listing DTO 的字段（model/needs_review/risk_level/
 * status 等）推导当前应停留的步骤与各步可用性；组件只消费，不重复实现判定。
 */

/** 分步流步骤定义（顺序冻结）。 */
export const FLOW_STEPS = [
  { key: 'generate', label: '生成', hint: '选商品与目标平台，AI 生成 Listing' },
  { key: 'edit', label: '编辑预览', hint: '核对与编辑标题/卖点/关键词' },
  { key: 'review', label: '合规复核', hint: '规则自检 + 人工审批（如需）' },
  { key: 'publish', label: '发布', hint: '选择已授权销售店铺或本地模拟' },
  { key: 'receipts', label: '回执', hint: '店铺发布回执与提交核验' },
]

/** 编辑表单初值（bullets 补齐 5 槽，keywords 文本化）。 */
export function editFormFromListing(listing = {}) {
  const bullets = Array.isArray(listing.bullets)
    ? listing.bullets.slice(0, 5).map((b) => (b == null ? '' : String(b)))
    : []
  while (bullets.length < 5) bullets.push('')
  const keywords = Array.isArray(listing.keywords) ? listing.keywords : []
  return {
    title: listing.title || '',
    description: listing.description || '',
    bullets,
    keywordsText: keywords.join(', '),
  }
}

/** 表单 → PUT /listings/{id} 请求体（裁剪空值）。 */
export function listingPayloadFromForm(form = {}) {
  return {
    title: String(form.title || '').trim(),
    description: form.description || '',
    bullets: (form.bullets || []).map((b) => String(b || '').trim()).filter(Boolean),
    keywords: String(form.keywordsText || '').split(/[,，\n]/).map((s) => s.trim()).filter(Boolean),
  }
}

/**
 * 由 Listing 状态推导应停留的步骤 key：
 * - 无 id（未生成）→ generate；
 * - 高风险 → review（复核门禁禁止发布）；
 * - needs_review / 人工待审 → review；
 * - 已有发布记录（published）→ receipts；
 * - 其余 → publish。
 */
export function deriveFlowStep(listing = {}) {
  if (!listing.id) return 'generate'
  if (listing.risk_level === 'high') return 'review'
  if (listing.needs_review) return 'review'
  if (listing.status === 'published') return 'receipts'
  return 'publish'
}

/** 步骤 key → 索引；未知 key 回 0。 */
export function stepIndex(key) {
  const i = FLOW_STEPS.findIndex((s) => s.key === key)
  return i === -1 ? 0 : i
}

/** 发布可行性：高风险一律禁发（复核门禁），原因直出。 */
export function publishGate(listing = {}) {
  if (listing.risk_level === 'high') {
    return { allowed: false, reason: '该 Listing 为高风险，复核门禁禁止发布；请先修改内容并重新检测' }
  }
  return { allowed: true, reason: '' }
}

/** 店铺可发布判定（与旧 Listings.vue 语义一致）。 */
export function shopSelectable(shop = {}) {
  return shop.status === 'authorized' && (
    shop.capabilities?.can_publish !== false || shop.capabilities?.can_listing_readiness === true)
}

/** 店铺状态徽标（统一 StatusBadge 语义源）。 */
export const SHOP_STATUS = {
  authorized: { text: '已授权·可选', type: 'success' },
  pending: { text: '未授权', type: 'info' },
  failed: { text: '授权失败', type: 'danger' },
  expired: { text: '已过期', type: 'warning' },
}

export function shopStatusTag(status) {
  return SHOP_STATUS[status] || { text: status || '未知', type: 'info' }
}
