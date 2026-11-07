/**
 * 阻断补齐入口的视图模型（P0-4）。
 *
 * 后端每个 blocker 必须带三要素：阻断码 + 原因 + 补齐动作（`repair_action`）。
 * 但历史数据里仍有 `repair_action: null` 的旧记录，前端不能因此渲染空白或死按钮，
 * 所以这里统一成「有入口 / 暂无入口 / 未接入」三种确定形态。
 *
 * 红线：`connected === false` 表示补齐动作背后的领域服务还没接入，
 * 页面可以看去核对，但**不能**把按钮画成可完成的样子。
 */

const KINDS = ['ROUTE', 'ACTION', 'UNAVAILABLE']

/** 把 repair_action 规范成视图模型；null/异常一律降级为「暂无入口」。 */
export function repairView(repair) {
  if (!repair || typeof repair !== 'object') {
    return {
      kind: 'UNAVAILABLE',
      label: '暂无补齐入口',
      path: '',
      action: '',
      connected: false,
      reason: '',
      note: '该阻断尚未登记补齐入口，请在待办中心跟进',
      canNavigate: false,
    }
  }
  const kind = KINDS.includes(repair.kind) ? repair.kind : 'UNAVAILABLE'
  const path = typeof repair.path === 'string' && repair.path.startsWith('/app') ? repair.path : ''
  const connected = repair.connected === true
  return {
    kind,
    label: typeof repair.label === 'string' && repair.label ? repair.label : '去补齐',
    path,
    action: typeof repair.action === 'string' ? repair.action : '',
    connected,
    reason: typeof repair.reason === 'string' ? repair.reason : '',
    // `UNAVAILABLE` 没有值得去的页面，不给跳转；`ROUTE`/`ACTION` 即使是
    // 「未接入」也保留入口——页面本身有效（如定价页能算利润），只是补不完，
    // 所以按钮照给、但必须同时显示未接入原因。
    canNavigate: Boolean(path) && kind !== 'UNAVAILABLE',
    note: connected ? '' : (repair.reason || '该能力尚未接入，无法在此完成补齐'),
  }
}

/** 单个阻断项的视图模型。 */
export function blockerView(blocker) {
  const item = blocker && typeof blocker === 'object' ? blocker : {}
  return {
    code: typeof item.code === 'string' && item.code ? item.code : 'MISSING_DATA',
    message: typeof item.message === 'string' && item.message ? item.message : '未提供阻断原因',
    stepCode: typeof item.step_code === 'string' ? item.step_code : '',
    ownerActor: typeof item.owner_actor === 'string' ? item.owner_actor : '',
    repair: repairView(item.repair_action),
  }
}

/** 阻断列表 → 视图列表；脏数据丢弃而不是抛错。 */
export function blockerViews(blockers) {
  const rows = Array.isArray(blockers) ? blockers : []
  return rows.filter((item) => item && typeof item === 'object').map(blockerView)
}

/** 一句概括，用于状态汇总的横幅标题。 */
export function blockerHeadline(blockers) {
  const list = blockerViews(blockers)
  if (!list.length) return ''
  return `阻断 ${list.length} 项：${list[0].message}`
}

/** 有几项是「点了也补不完」的，页面需要单独提示，避免用户反复点。 */
export function unrepairableCount(blockers) {
  return blockerViews(blockers).filter((item) => item.repair.connected !== true).length
}
