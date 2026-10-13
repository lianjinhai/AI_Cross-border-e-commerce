/**
 * 运行状态字典（UX-01）。
 *
 * 逐字迁移自 `frontend/src/views/RunStatus.vue` 的既有映射，**文案一字未改**，
 * 以保证抽成组件后 6 个引用页（Dashboard/Listings/Compliance/Suppliers/Alerts/
 * Workflows）零行为变化。
 *
 * 抽成纯函数的原因：项目未安装 @vue/test-utils，组件逻辑无法 mount 测试；
 * 把映射下沉为纯函数后可用 vitest 直接断言。
 *
 * Element Plus el-tag 的 `type` 取值：primary / success / warning / danger / info。
 */

/** 状态 → el-tag type。 */
export const STATUS_TAG_MAP = {
  success: 'success',
  running: 'primary',
  failed: 'danger',
  partial: 'warning',
  blocked: 'warning',
  skipped: 'info',
  queued: 'info',
  published: 'success',
  draft: 'info',
  pending: 'info',
  low: 'success',
  mid: 'warning',
  high: 'danger',
}

/** 状态 → 展示文案。 */
export const STATUS_LABEL_MAP = {
  success: '成功',
  running: '运行中',
  failed: '失败',
  published: '已发布',
  partial: '部分成功',
  blocked: '等待人工',
  skipped: '已跳过',
  queued: '排队中',
  draft: '草稿',
  pending: '待处理',
  low: '低',
  mid: '中',
  high: '高',
}

/**
 * 解析状态标签。
 *
 * @param {string} status 状态码（如 'published'）。
 * @param {string} [table='run'] 所属表；本批所有取值都走同一套既有映射（零行为变化），
 *   该参数为后续按表细分保留。
 * @returns {{ type: string, label: string }} `type` 供 el-tag，`label` 为文本。
 *   未知 status 返回 `{ type: 'info', label: status }`（保留原文案）。
 */
export function resolveStatusTag(status, table = 'run') {
  void table // 本批不区分表；保留参数以冻结接口。
  const type = STATUS_TAG_MAP[status] || 'info'
  const label = STATUS_LABEL_MAP[status] || status
  return { type, label }
}
