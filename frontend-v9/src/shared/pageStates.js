/**
 * 11 态字典（蓝图 §6.4，包 1 P0 横切）。
 *
 * 所有列表/详情区块**统一经 SectionState 消费本字典**，文案不允许页面自写。
 * tone 语义：neutral（外部等待/不确定）显中性灰；warning 橙；danger 仅 ERROR/失败；info 蓝。
 * 外部等待=WAITING_EXTERNAL 中性（不用红色误报）。
 *
 * 兼容映射：旧 SectionState state → 11 态码（既有 5~6 态页面逐步迁移）。
 */

/** 11 态常量 + 默认文案 + 主行动 + tone。 */
export const PAGE_STATES = {
  LOADING:          { code: 'LOADING',          title: '正在加载…',                actionText: '',                  tone: 'info' },
  EMPTY_NEW:        { code: 'EMPTY_NEW',        title: '你还没有添加商品/店铺/任务', actionText: '创建/接入',       tone: 'info' },
  EMPTY_FILTER:     { code: 'EMPTY_FILTER',     title: '当前筛选无结果',           actionText: '重置筛选',          tone: 'info' },
  NOT_CONFIGURED:   { code: 'NOT_CONFIGURED',   title: '未连接Store/未配置规则',  actionText: '进入设置',          tone: 'warning' },
  NO_PERMISSION:    { code: 'NO_PERMISSION',    title: '当前角色无权查看或操作',  actionText: '返回/申请权限',     tone: 'info' },
  PARTIAL_DATA:     { code: 'PARTIAL_DATA',     title: '部分数据未同步，结果可能不完整', actionText: '查看缺项/重试', tone: 'warning' },
  WAITING_EXTERNAL: { code: 'WAITING_EXTERNAL', title: '等待平台反馈，当前无需操作', actionText: '查看同步记录',     tone: 'neutral' },
  WAITING_USER:     { code: 'WAITING_USER',     title: '需要你补充/审批',         actionText: '对应当前合法动作',   tone: 'warning' },
  BLOCKED:          { code: 'BLOCKED',          title: '被具体规则阻断',          actionText: '解释阻断+可修复入口', tone: 'warning' },
  UNCERTAIN:        { code: 'UNCERTAIN',        title: '操作是否在外部成功尚待核实', actionText: '重新查询状态',     tone: 'neutral' },
  ERROR:            { code: 'ERROR',            title: '本次操作未完成：原因…',   actionText: '修复/可安全重试',    tone: 'danger' },
}

/**
 * 兼容映射：旧 SectionState state（5 态）→ 11 态码。
 * 'ready' 映射为 null（表示无特定态码，正常渲染内容）。
 * 未知/缺省返回 null。
 *
 * @param {string} state 旧 5 态之一：loading/empty/error/nopermission/partial/ready。
 * @returns {string|null} 11 态码或 null。
 */
export function stateToCode(state) {
  const map = {
    loading: 'LOADING',
    empty: 'EMPTY_NEW',
    nopermission: 'NO_PERMISSION',
    error: 'ERROR',
    partial: 'PARTIAL_DATA',
    ready: null,
  }
  return map[state] ?? null
}

/**
 * 取某态文案（可被页面 override title/actionText，但默认文案不页面自写）。
 * 未知 code 回落为 { code, title: code, actionText: '', tone: 'info' }。
 *
 * @param {string} code 11 态码之一。
 * @param {object} [overrides] 可选 override（title / actionText / tone）。
 * @returns {{code:string, title:string, actionText:string, tone:string}}
 */
export function stateCopy(code, overrides = {}) {
  const base = PAGE_STATES[code] || { code, title: code, actionText: '', tone: 'info' }
  return { ...base, ...overrides, code }
}

/**
 * 校验是否合法 11 态码（供测试/断言使用）。
 * @param {string} code
 * @returns {boolean}
 */
export function isValidStateCode(code) {
  return Object.prototype.hasOwnProperty.call(PAGE_STATES, code)
}

/** 11 态码集合（便于遍历/断言数量）。 */
export const STATE_CODES = Object.keys(PAGE_STATES)
