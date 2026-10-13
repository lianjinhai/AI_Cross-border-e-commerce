/**
 * 证据面板纯函数（蓝图 §6.4，包 1 P0 共享组件 EvidencePanel 扩展纯函数下沉）。
 *
 * 未核验默认中性样式（非绿色），verified=true 才显绿色"官方已核验"。
 */

/**
 * 证据语气判定。
 * verified=true → 'success'（绿色"官方已核验"）
 * 未核验（默认）→ 'neutral'（中性灰）
 *
 * @param {object} p
 * @param {boolean} [p.verified] 官方已核验。
 * @param {string} [p.source] 数据来源。
 * @returns {string} el-tag tone：'success'|'neutral'|'info'。
 */
export function evidenceTone({ verified = false, source = '' } = {}) {
  if (verified) return 'success'
  if (source) return 'info'
  return 'neutral'
}

/**
 * 过期/时效标签。
 * expiresAt 缺失 → ''（不显标签）。
 * 已过期 → "已过期"。
 * 未过期 → "有效至 {date}"。
 *
 * @param {string} [expiresAt] ISO 日期字符串（如 2025-06-01T00:00:00Z）。
 * @returns {string} 标签文案（空串=不显）。
 */
export function expiryLabel(expiresAt) {
  if (!expiresAt) return ''
  const exp = new Date(expiresAt)
  if (Number.isNaN(exp.getTime())) return ''
  if (exp.getTime() < Date.now()) return '已过期'
  return `有效至 ${expiresAt.slice(0, 10)}`
}
