/**
 * AI 行动中心的展示口径（纯函数，供 AiActions.vue 消费）。
 *
 * 规则来源：
 *  * 能力边界**只能**来自服务端 `/api/ai/capabilities`（注册表计算），前端不自行推断；
 *  * 单条能否操作以该 Action 自己的 `required_permission` 判定（fail-closed：
 *    拿不到权限就禁用，而不是乐观放开）；
 *  * 类型下拉只列**已注册**动作——历史静态清单里的 REPRICE/RESTOCK 在后端
 *    `POLICIES/HANDLERS` 里并不存在，选中只会 400，属假入口。
 */

/** 已注册动作的中文名（后端返回类型码，不返回 label；未知类型回显原值，不臆造）。 */
export const ACTION_LABELS = {
  REFRESH_BUILTIN_TRENDS: '刷新内置趋势',
  UPDATE_LISTING_COMPLIANCE_RISK: '更新合规风险',
  UPDATE_PRODUCT_CONTENT: '商品内容标准化',
  CREATE_AD_CAMPAIGN_DRAFT: '创建广告草稿',
  ADJUST_AD_BUDGET: '预算调整',
  CREATE_LISTING_DRAFT: '创建 Listing 草稿',
  UPDATE_LISTING_CONTENT: '更新 Listing 内容',
  PUBLISH_LISTING: '发布 Listing',
}

/**
 * 类型下拉选项：优先用服务端能力矩阵的已注册类型；不可执行时在名称上标注。
 *
 * @param {{actions?: Array<{action_type: string, enabled: boolean}>}|null} caps
 * @returns {Array<{value: string, label: string}>}
 */
export function actionTypeOptions(caps) {
  const actions = Array.isArray(caps?.actions) ? caps.actions : []
  const types = actions.length ? actions.map((a) => a.action_type) : Object.keys(ACTION_LABELS)
  const blocked = new Set(actions.filter((a) => !a.enabled).map((a) => a.action_type))
  return types.map((value) => ({
    value,
    label: `${ACTION_LABELS[value] || value}${blocked.has(value) ? '（不可执行）' : ''}`,
  }))
}

/**
 * 单条是否可操作（fail-closed）。
 *
 * @param {{required_permission?: string}|null} row
 * @param {(perm: string) => boolean} can 权限判定函数（Context 缺失时应返回 false）
 * @param {boolean} [fallback] 行上没有 required_permission 时的兜底值
 */
export function canOperateAction(row, can, fallback = false) {
  const perm = row?.required_permission
  if (!perm) return Boolean(fallback)
  try {
    return Boolean(can(perm))
  } catch {
    return false
  }
}

/**
 * 「下一操作」提示：不可操作时优先展示服务端阻断原因，其次说明缺哪个权限。
 *
 * @param {{status?: string, action_type?: string, required_permission?: string}} row
 * @param {{operable: boolean, blockedReasons?: string[]}} state
 * @returns {string}
 */
export function nextActionHint(row, { operable = false, blockedReasons = [] } = {}) {
  if (!operable) {
    if (blockedReasons.length) return blockedReasons.join('；')
    return row?.required_permission ? `缺少权限 ${row.required_permission}` : '无权操作'
  }
  switch (row?.status) {
    case 'PENDING_APPROVAL': return '待审批'
    case 'APPROVED': return '待执行'
    case 'SUCCESS': return '已完成'
    case 'FAILED': return '失败可重试或查看决策依据'
    case 'REJECTED': return '已拒绝，无需操作'
    default: return '—'
  }
}
