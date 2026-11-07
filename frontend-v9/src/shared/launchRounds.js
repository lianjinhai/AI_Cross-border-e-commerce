/**
 * 轮次链（P0-3）：把同一销售对象的上线流程按轮次排好。
 *
 * 语义依据 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md`：
 * - 同一销售对象（product + shop）**只有一个活跃槽**（`active_slot == 1`），
 *   其余轮次都是历史（`active_slot IS NULL`，DTO 投影为 `is_history`）。
 * - ACTIVE / PAUSED 不释放槽位，所以「活跃槽」不等于「还在跑」。
 *
 * 列表 DTO 没有 `previous_run_id`（只有详情有），因此按创建时间升序编号；
 * 查询侧已按 product_id + shop_id 收窄，不会混入其它销售对象。
 */

/**
 * @typedef {Object} RoundItem
 * @property {number} id 流程 ID
 * @property {boolean} is_history 是否历史轮次
 * @property {string} created_at ISO 时间
 * @property {string} execution_status 执行状态
 * @property {string} platform_status 平台状态
 */

/**
 * 按轮次排序并编号。
 *
 * @param {RoundItem[]} items 同一销售对象的流程列表项
 * @param {number|null} currentId 当前查看的流程 ID（用于标记「当前」）
 * @param {number|null} total 服务端报告的总轮次数（用于发现分页截断）
 * @returns {{rounds: Array, activeCount: number, anomalies: string[]}}
 *   `activeCount` 正常应为 0 或 1；>1 表示数据异常（唯一索引应已阻止，
 *   这里只是把异常显式暴露出来，不静默吞掉）。
 */
export function buildRoundChain(items = [], currentId = null, total = null) {
  const rows = (Array.isArray(items) ? items : [])
    .filter((item) => item && typeof item.id === 'number')
    .slice()
    .sort((a, b) => {
      const ta = String(a.created_at || '')
      const tb = String(b.created_at || '')
      if (ta !== tb) return ta < tb ? -1 : 1
      return a.id - b.id
    })

  const rounds = rows.map((item, index) => ({
    ...item,
    round: index + 1,
    is_current: currentId !== null && item.id === currentId,
    // 历史轮次用灰色；活跃槽用状态色，避免「活跃 = 成功」的误读。
    slot_label: item.is_history ? '历史' : '活跃槽',
  }))

  const activeCount = rounds.filter((row) => !row.is_history).length
  const anomalies = []
  if (activeCount > 1) {
    anomalies.push(`检测到 ${activeCount} 个活跃槽，违反「同一销售对象仅一个活跃槽」`)
  }
  // 分页截断必须说出来：否则「第 N 轮」的编号是错的，而页面看上去完全正常。
  if (typeof total === 'number' && total > rounds.length) {
    anomalies.push(`共 ${total} 轮，本次仅取到 ${rounds.length} 轮，轮次编号可能不完整`)
  }
  return { rounds, activeCount, anomalies }
}

/**
 * 轮次切换的说明文案：活跃槽为什么还在、为什么不能新开。
 *
 * @param {Object} opts
 * @param {boolean} opts.currentIsHistory 当前查看的是否历史轮次
 * @param {number} opts.activeCount 活跃槽数量
 * @returns {string}
 */
export function roundChainHint({ currentIsHistory = false, activeCount = 0 } = {}) {
  if (activeCount > 1) return '数据异常：存在多个活跃槽，请核查唯一索引是否被绕过'
  if (currentIsHistory) return '这是历史轮次，仅可只读回看；同一销售对象的活跃槽只有一处'
  if (activeCount === 0) return '该销售对象当前没有活跃槽，可发起新一轮上线'
  return '同一销售对象仅一个活跃槽；在售或暂停都不会释放它'
}
