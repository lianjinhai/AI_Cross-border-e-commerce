/**
 * AI 副驾驶动作与上下文模型（UX-E #29，纯函数）。
 *
 * 后端 orchestrator.chat 返回 actions 为「动作 key 字符串数组」（如
 * ['pick_candidates']，见 backend/app/agents/orchestrator.py）。本模块是
 * key → 可执行导航 的唯一映射源：可执行项带确认对话框跳转；
 * 不可执行项分两态——WaitingExternal（后端新增 key，前端导航待接入）与
 * NotConfigured（当前身份无对应权限，fail-closed 不造假入口）。
 */

/** 基础建议问题（orchestrator._route 关键词域内，保证能路由到真实能力）。 */
export const COPILOT_SUGGESTIONS = ['帮我选品', '看看市场趋势', '有什么风险', '重新定价', '经营情况']

/** 会话持久化说明（后端无会话存储端点，只标注不造假入口）。 */
export const AI_SESSION_PERSIST_NOTE =
  'AI 会话历史持久化待接入：当前对话仅保留在本次页面会话中，刷新后不保留。'

/** 动作 key → 导航元数据（route 为 /app 下真实冻结路由）。 */
export const ACTION_META = {
  pick_candidates: { label: '查看选品结果', route: '/app/market/discovery', permission: '' },
  scan_trends: { label: '查看市场趋势', route: '/app/market/discovery', permission: '' },
  reprice_batch: { label: '查看动态定价明细', route: '/app/pricing', permission: '' },
}

/**
 * 解析动作视图模型。
 * @param {string[]} actionKeys 后端 actions 数组。
 * @param {{can: (key: string) => boolean}} ctx 权限判定（注入 permissions.can，便于测试）。
 * @returns {Array<{key,label,route?,status:'ready'|'waiting'|'notconfigured',reason}>}
 */
export function resolveCopilotActions(actionKeys = [], ctx) {
  return (actionKeys || []).map((key) => {
    const meta = ACTION_META[key]
    if (!meta) {
      return {
        key,
        label: key,
        status: 'waiting',
        reason: '该动作由后端返回，前端导航待接入（WaitingExternal）',
      }
    }
    if (meta.permission && !(ctx?.can?.(meta.permission) ?? false)) {
      return {
        key,
        label: meta.label,
        status: 'notconfigured',
        reason: `需要 ${meta.permission} 权限，当前身份不可执行（NotConfigured）`,
      }
    }
    return { key, label: meta.label, route: meta.route, status: 'ready', reason: '' }
  })
}

/** 动作确认对话框文案（可执行项点击后先确认再跳转）。 */
export function buildActionConfirm(vm) {
  return `AI 建议前往「${vm.label}」查看/执行该动作（${vm.key}）。确定前往？`
}

/** 页面域 → 上下文建议问题（当前页可用的意图优先，全部落在 orchestrator 路由域内）。 */
const DOMAIN_SUGGESTIONS = {
  首页: COPILOT_SUGGESTIONS,
  市场机会: ['帮我选品', '看看市场趋势'],
  商品经营: ['帮我铺货上架', '有什么风险'],
  订单履约: ['经营情况', '有什么风险'],
  客户售后: ['客服会话情况', '有什么风险'],
  经营优化: ['重新定价', '有什么风险'],
  数据分析: ['经营情况', '看看市场趋势'],
  'AI 运营': ['经营情况', '有什么风险'],
}

/**
 * 上下文感知建议：按当前路由 meta.domain 返回建议问题；未登记域回退基础集。
 * @param {{domain?: string, title?: string}} routeMeta
 */
export function contextualSuggestions(routeMeta = {}) {
  return DOMAIN_SUGGESTIONS[routeMeta.domain] || COPILOT_SUGGESTIONS
}

/** 上下文标注（输入框上方灰字，让用户知道 AI「看得见」当前页面）。 */
export function contextLabel(routeMeta = {}) {
  return routeMeta.title ? `当前页面：${routeMeta.title}` : ''
}
