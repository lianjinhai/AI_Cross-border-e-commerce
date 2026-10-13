/**
 * 下一步动作面板纯函数（蓝图 §6.4，包 1 P0）。
 *
 * 规则：恰一个 primary；无权限=不渲染并显只读解释；业务不可执行=reason+补救入口；
 * 技术未接通=灰化+"暂不支持"；confirm=true 走 AsyncActionDialog。
 */

/**
 * 从动作列表中选取 primary 动作。
 * 恰一个 primary（kind='primary'）；多个 primary → 取第一个（告警日志由组件层处理）。
 * 无 primary 返回 null。
 *
 * @param {Array<{code:string,label:string,kind?:string}>} actions 可用动作列表。
 * @returns {object|null} primary 动作或 null。
 */
export function pickPrimaryAction(actions) {
  if (!Array.isArray(actions) || actions.length === 0) return null
  const primaries = actions.filter((a) => a?.kind === 'primary')
  if (primaries.length === 0) return null
  return primaries[0]
}

/**
 * 渲染策略三态判定（NextActionPanel 消费）。
 *
 * 返回 { mode, reason }：
 * - 'enabled'      — 有权限且业务可执行（正常渲染按钮）
 * - 'readOnly'     — 无权限（不渲染按钮，显只读解释）
 * - 'unavailable'  — 技术未接通（灰化+"暂不支持"）
 *
 * @param {object} action 单个动作 { code, label, kind, reason?, confirm?, apiGap? }
 * @param {boolean} permission 是否具备该动作权限。
 * @returns {{mode:string, reason?:string}}
 */
export function renderPolicy(action, permission) {
  if (!action || !action.code) return { mode: 'unavailable', reason: '未知动作' }
  // 技术未接通（后端 API 缺失）→ 灰化
  if (action.apiGap) return { mode: 'unavailable', reason: '暂不支持，后端未接入' }
  // 无权限 → 只读
  if (!permission) return { mode: 'readOnly', reason: action.reason || '当前角色无权执行' }
  // 业务不可执行（有明确 reason）
  if (action.reason) return { mode: 'unavailable', reason: action.reason }
  return { mode: 'enabled' }
}

/**
 * 动作列表分组：primary / secondary（便于组件渲染）。
 *
 * @param {Array} actions 可用动作列表。
 * @returns {{primary: object|null, secondary: Array}}
 */
export function splitActions(actions) {
  if (!Array.isArray(actions)) return { primary: null, secondary: [] }
  const primary = pickPrimaryAction(actions)
  const secondary = actions.filter((a) => a && a.kind === 'secondary')
  return { primary, secondary }
}
