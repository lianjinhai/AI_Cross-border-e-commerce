/**
 * 业务状态映射（蓝图 §6.4/§6.5，包 1 P0 共享组件纯函数下沉）。
 *
 * 外部等待=WAITING_EXTERNAL 中性色（禁红色误报）；PRO 模式才显 raw；未知码回落 info。
 */

/** 标准态码 → el-tag tone 映射。 */
const TONE_MAP = {
  SUCCESS: 'success',
  RUNNING: 'primary',
  FAILED: 'danger',
  PARTIAL: 'warning',
  BLOCKED: 'warning',
  SKIPPED: 'info',
  QUEUED: 'info',
  WAITING_EXTERNAL: 'neutral',
  WAITING_USER: 'warning',
  UNCERTAIN: 'neutral',
  PUBLISHED: 'success',
  DRAFT: 'info',
  PENDING: 'info',
}

/**
 * 标准态码 → el-tag tone（未知码回落 'info'）。
 * WAITING_EXTERNAL / UNCERTAIN → neutral（中性灰，不用红色误报）。
 *
 * @param {string} code 标准态码（大写枚举）。
 * @returns {string} el-tag type（primary/success/warning/danger/info/neutral）。
 */
export function statusTone(code) {
  return TONE_MAP[code] || 'info'
}

/**
 * PRO 模式才显 raw（原始状态文本）。
 *
 * @param {string} mode 当前模式：'PRO' | 'GUIDED' | ''。
 * @param {string} code 原始状态码。
 * @returns {boolean} 是否展示 raw。
 */
export function shouldShowRaw(mode, code) {
  return mode === 'PRO' && Boolean(code)
}

/**
 * 原始状态 → 标准态码映射。
 * 后端可能返回小写/自定义码；本函数归一化为大写标准码。
 * 未知值返回 'UNKNOWN'。
 *
 * @param {string} raw 原始状态字符串。
 * @returns {string} 标准态码。
 */
export function mapBusinessStatus(raw) {
  if (!raw || typeof raw !== 'string') return 'UNKNOWN'
  const upper = raw.toUpperCase()
  const DIRECT = new Set([
    'SUCCESS', 'RUNNING', 'FAILED', 'PARTIAL', 'BLOCKED',
    'SKIPPED', 'QUEUED', 'WAITING_EXTERNAL', 'WAITING_USER', 'UNCERTAIN',
    'PUBLISHED', 'DRAFT', 'PENDING',
  ])
  if (DIRECT.has(upper)) return upper
  // 别名映射
  const ALIAS = {
    'WAITING': 'WAITING_EXTERNAL',
    'EXTERNAL': 'WAITING_EXTERNAL',
    'APPROVAL_PENDING': 'WAITING_USER',
    'REVIEW': 'WAITING_USER',
    'TIMEOUT': 'UNCERTAIN',
  }
  if (ALIAS[upper]) return ALIAS[upper]
  return 'UNKNOWN'
}
