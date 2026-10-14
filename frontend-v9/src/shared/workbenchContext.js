/**
 * 顶栏任务计数条纯函数（R3-2A，baseline §3.2）。
 *
 * 从 `GET /workbench/overview` 的 `sections` 派生三个**小型计数**：
 *   待我处理（todo）   ← `sections.need_human.count`（待人工处理，后端已按权限聚合）
 *   等待外部（waiting）← `sections.in_progress` 中处于「等平台/等外部」的在途 Launch 数
 *   被阻断（blocked）  ← `sections.in_progress` 中执行态为 BLOCKED/FAILED 的在途 Launch 数
 *
 * **数据诚实红线（baseline §5「请求失败不得清空/不当零」）**：
 * 计数三态 = 数字 | null；**null 表示「不可得」**（源被 skipped/failed，或结构不匹配），
 * 由视图渲染为「—」，**绝不当 0**。仅当源确实返回、且聚合后为 0 时才显示 0。
 *
 * 口径依据：`INCREMENT_PRD_LAUNCH_P0_CLOSURE.md` AC-1.5 —— 「等待平台」按
 * `platform_status ∈ {SUBMITTED, UNDER_REVIEW}` 或存在 WAITING_EXTERNAL 步骤；
 * 「被阻断」按执行态 `BLOCKED/FAILED`；与 `BusinessStatus.vue` 状态文案同源。
 *
 * 纯函数、无副作用、可独立单测（不依赖 axios / Vue）。
 */

/** 执行态「被阻断」枚举（与 BusinessStatus / 后端 execution_status 对齐）。 */
export const BLOCKED_EXECUTION_STATES = ['BLOCKED', 'FAILED']

/** 执行态「等待外部」枚举。 */
export const WAITING_EXECUTION_STATES = ['WAITING_EXTERNAL']

/** 平台状态「等待外部」枚举（外部平台已受理但未在售）。 */
export const WAITING_PLATFORM_STATUSES = ['SUBMITTED', 'UNDER_REVIEW']

/** 计数不可得时的展示占位（不当 0）。 */
export const COUNT_PLACEHOLDER = '—'

/**
 * 从 section 对象取标量计数（`{count:int}`）；非对象或无 count → null（不可得）。
 * @param {*} section
 * @returns {number|null}
 */
function countFromSection(section) {
  if (!section || typeof section !== 'object') return null
  const value = section.count
  return Number.isInteger(value) ? value : null
}

/**
 * 从列表型 section 按谓词计数；非数组 → null（源不可得，不当 0）。
 * @param {*} section
 * @param {(item:object)=>boolean} predicate
 * @returns {number|null}
 */
function countByPredicate(section, predicate) {
  if (!Array.isArray(section)) return null
  return section.filter((item) => item && predicate(item)).length
}

/** 是否「被阻断」在途项。 */
export function isBlockedItem(item) {
  return BLOCKED_EXECUTION_STATES.includes(item?.execution_status)
}

/** 是否「等待外部」在途项（执行态或平台状态任一命中）。 */
export function isWaitingExternalItem(item) {
  if (WAITING_EXECUTION_STATES.includes(item?.execution_status)) return true
  return WAITING_PLATFORM_STATUSES.includes(item?.platform_status)
}

/**
 * 派生顶栏三计数。
 * @param {object|null} overview `/workbench/overview` 响应（或任意非空对象）。
 * @returns {{todo:number|null, waiting:number|null, blocked:number|null}}
 */
export function deriveWorkbenchCounts(overview) {
  const sections = overview && typeof overview === 'object' ? overview.sections : null
  if (!sections || typeof sections !== 'object') {
    return { todo: null, waiting: null, blocked: null }
  }
  return {
    todo: countFromSection(sections.need_human),
    waiting: countByPredicate(sections.in_progress, isWaitingExternalItem),
    blocked: countByPredicate(sections.in_progress, isBlockedItem),
  }
}

/**
 * 计数展示格式化：null/undefined/非法 → 「—」，否则字符串化（0 正常显示为 "0"）。
 * @param {*} value
 * @returns {string}
 */
export function formatCount(value) {
  if (value === null || value === undefined) return COUNT_PLACEHOLDER
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return COUNT_PLACEHOLDER
}

/** 三计数是否全部不可得（用于视图降级判定，如整体隐藏或灰显）。 */
export function isCountsUnavailable(counts) {
  if (!counts) return true
  return ['todo', 'waiting', 'blocked'].every((key) => counts[key] === null || counts[key] === undefined)
}
