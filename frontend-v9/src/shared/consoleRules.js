/**
 * 控制台数据源与规则纯函数（蓝图 R1 包 3 · PC-04，§B.3 / §5.19）。
 *
 * 蓝图 §5.19：平台规则/市场数据源设置展示来源、适用范围、版本、有效期、最近拉取、错误、回滚。
 * admin 规则端点（Maintenance 现有"平台规则包"能力并入）：来源=平台目录 + version/origin。
 *
 * Registry/规则版本端点部分未核 → 缺项（有效期/最近拉取/回滚）一律显"—"或"未接入"，
 * 禁止编造。本模块定义列目录与缺项判定，组件（Rules.vue）只消费。
 */

/** 规则/数据源展示列（版本、有效期、最近拉取、错误、回滚）。 */
export const RULES_COLUMNS = [
  { key: 'platform', label: '平台' },
  { key: 'origin', label: '来源' },
  { key: 'version', label: '版本' },
  { key: 'valid_until', label: '有效期' },
  { key: 'last_fetched', label: '最近拉取' },
  { key: 'last_error', label: '最近错误' },
  { key: 'rollback', label: '回滚' },
]

/** 可写规则动作（现有 admin 写端点：启用/停用）；未接入时禁用。 */
export const RULES_ACTIONS = [
  { code: 'enable', label: '启用' },
  { code: 'disable', label: '停用' },
]

/** 未接入标记文案（§5.19 缺项明示）。 */
export function ruleMissingCopy(field) {
  const map = {
    valid_until: '有效期未接入',
    last_fetched: '最近拉取未接入',
    last_error: '无错误记录',
    rollback: '回滚未接入',
    version: '版本未知',
  }
  return map[field] || '未接入'
}

/** 某单元格缺项判定：值为空 → 显占位文案（不渲染 0/假数据）。 */
export function ruleCellText(row = {}, key) {
  const v = row[key]
  if (v == null || v === '') {
    if (key === 'last_error') return '—'
    return ruleMissingCopy(key)
  }
  return String(v)
}

/**
 * 写动作可用判定：规则写端点未接入时禁用（灰化 + 暂不支持），不触发 API。
 * @param {string} actionCode
 * @param {object} [ctx]
 * @param {boolean} [ctx.rulesWriteAvailable] 规则写端点是否已接入。
 * @returns {{code:string, executable:boolean, reason:string}}
 */
export function rulesWritePolicy(actionCode, { rulesWriteAvailable = false } = {}) {
  if (!RULES_ACTIONS.some((a) => a.code === actionCode)) {
    return { code: actionCode, executable: false, reason: '未知操作' }
  }
  if (!rulesWriteAvailable) {
    return { code: actionCode, executable: false, reason: '规则写端点待接入，暂不可用' }
  }
  return { code: actionCode, executable: true, reason: '' }
}
