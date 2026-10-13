/**
 * 调度任务视图模型（UX-E #20，纯函数）。
 * 矩阵 #20「调度列表含下次执行时间」：后端 Schedule 不下发 next_run_at，
 * 由「上次执行时间 + 频率」估算，列头与单元格均明示「估算」，绝不冒充实排期。
 */

/** 频率选项（interval_minutes 取值域 5 ~ 43200，与后端校验一致）。 */
export const FREQ_OPTIONS = [
  { label: '每 30 分钟', value: 30 },
  { label: '每 1 小时', value: 60 },
  { label: '每 6 小时', value: 360 },
  { label: '每天一次', value: 1440 },
  { label: '每周一次', value: 10080 },
]

/** 调度类型选项（后端只接受三种 kind）。 */
export const SCHEDULE_KIND_OPTIONS = [
  { label: '工作流', value: 'workflow' },
  { label: '趋势扫描', value: 'trend_scan' },
  { label: '主动巡检', value: 'alert_scan' },
]

/** 上次结果文案（含手动触发可能产生的 dispatched）。 */
export const SCHEDULE_LAST_STATUS_LABELS = {
  success: '成功',
  partial: '部分成功',
  blocked: '等待人工',
  failed: '失败',
  running: '运行中',
  queued: '排队中',
  dispatched: '已派发',
}

export function lastStatusLabel(status) {
  return SCHEDULE_LAST_STATUS_LABELS[status] || status
}

/** 频率人读文案（逐字迁移旧 freqLabel）。 */
export function freqLabel(minutes) {
  if (minutes % 10080 === 0 && minutes >= 10080) return `每 ${minutes / 10080} 周`
  if (minutes % 1440 === 0 && minutes >= 1440) return `每 ${minutes / 1440} 天`
  if (minutes % 60 === 0) return `每 ${minutes / 60} 小时`
  return `每 ${minutes} 分钟`
}

/** 任务类型文案（逐字迁移旧 kindLabel：三种 kind 各自可读）。 */
export function kindLabel(schedule) {
  if (schedule?.kind === 'workflow') return `工作流·${schedule.workflow_key}`
  if (schedule?.kind === 'alert_scan') return '主动巡检'
  if (schedule?.kind === 'trend_scan') return '趋势扫描'
  return schedule?.kind || ''
}

function pad(n) {
  return String(n).padStart(2, '0')
}

/** 本地时间格式化（YYYY-MM-DD HH:mm；无效输入返回空串）。 */
export function formatDateTime(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * 下次执行时间（估算）：enabled 且有上次执行时间时 = last_run_at + interval_minutes。
 * 返回 {text, estimated}：不可估算时 text 为 '—' 且 estimated=false。
 */
export function nextRunAt(schedule, now = new Date()) {
  if (!schedule?.enabled || !schedule?.last_run_at) return { text: '—', estimated: false }
  const last = new Date(schedule.last_run_at)
  if (Number.isNaN(last.getTime())) return { text: '—', estimated: false }
  const next = new Date(last.getTime() + (schedule.interval_minutes || 0) * 60000)
  const overdue = next.getTime() <= now.getTime()
  return {
    text: overdue ? '待调度器拾取（已到期）' : formatDateTime(next),
    estimated: true,
  }
}
