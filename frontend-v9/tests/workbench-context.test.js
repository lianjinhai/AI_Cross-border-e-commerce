import { describe, expect, it } from 'vitest'
import {
  BLOCKED_EXECUTION_STATES,
  COUNT_PLACEHOLDER,
  WAITING_PLATFORM_STATUSES,
  deriveWorkbenchCounts,
  formatCount,
  isBlockedItem,
  isCountsUnavailable,
  isWaitingExternalItem,
} from '../src/shared/workbenchContext'

/**
 * 顶栏任务计数条纯函数回归（R3-2A，baseline §3.2 + §5 数据诚实红线）。
 *
 * 核心红线：**不可得当 null（渲染「—」），绝不当 0**；
 * 仅当源确实返回且聚合为 0 时才显示 0。
 */
describe('deriveWorkbenchCounts — 从 overview.sections 派生三计数', () => {
  it('returns all-null when the overview is missing / not an object', () => {
    expect(deriveWorkbenchCounts(null)).toEqual({ todo: null, waiting: null, blocked: null })
    expect(deriveWorkbenchCounts(undefined)).toEqual({ todo: null, waiting: null, blocked: null })
    expect(deriveWorkbenchCounts('nope')).toEqual({ todo: null, waiting: null, blocked: null })
    expect(deriveWorkbenchCounts({})).toEqual({ todo: null, waiting: null, blocked: null })
  })

  it('reads 待我处理 from sections.need_human.count', () => {
    expect(deriveWorkbenchCounts({ sections: { need_human: { count: 4 } } }).todo).toBe(4)
  })

  it('treats a missing / skipped need_human section as null (not 0)', () => {
    expect(deriveWorkbenchCounts({ sections: { need_human: null } }).todo).toBeNull()
    expect(deriveWorkbenchCounts({ sections: {} }).todo).toBeNull()
    // 结构不匹配（非 {count:int}）→ null
    expect(deriveWorkbenchCounts({ sections: { need_human: { count: 'x' } } }).todo).toBeNull()
  })

  it('derives 等待外部 / 被阻断 from sections.in_progress', () => {
    const overview = {
      sections: {
        need_human: { count: 2 },
        in_progress: [
          { execution_status: 'RUNNING' },                    // 既非等待外部也非阻断
          { execution_status: 'WAITING_EXTERNAL' },           // 等待外部（执行态）
          { platform_status: 'SUBMITTED' },                   // 等待外部（平台状态）
          { platform_status: 'UNDER_REVIEW' },                // 等待外部（平台状态）
          { execution_status: 'BLOCKED' },                    // 被阻断
          { execution_status: 'FAILED' },                     // 被阻断
        ],
      },
    }
    expect(deriveWorkbenchCounts(overview)).toEqual({ todo: 2, waiting: 3, blocked: 2 })
  })

  it('returns null (not 0) when in_progress source is unavailable', () => {
    expect(deriveWorkbenchCounts({ sections: { need_human: { count: 0 }, in_progress: null } }))
      .toEqual({ todo: 0, waiting: null, blocked: null })
    expect(deriveWorkbenchCounts({ sections: {} })).toEqual({ todo: null, waiting: null, blocked: null })
  })

  it('returns a genuine 0 when the source returned an empty list', () => {
    const counts = deriveWorkbenchCounts({ sections: { need_human: { count: 0 }, in_progress: [] } })
    expect(counts).toEqual({ todo: 0, waiting: 0, blocked: 0 })
  })
})

describe('isBlockedItem / isWaitingExternalItem 口径（AC-1.5）', () => {
  it('blocked = BLOCKED or FAILED execution state', () => {
    expect(BLOCKED_EXECUTION_STATES).toEqual(['BLOCKED', 'FAILED'])
    expect(isBlockedItem({ execution_status: 'BLOCKED' })).toBe(true)
    expect(isBlockedItem({ execution_status: 'FAILED' })).toBe(true)
    expect(isBlockedItem({ execution_status: 'RUNNING' })).toBe(false)
    expect(isBlockedItem(null)).toBe(false)
  })

  it('waiting-external = WAITING_EXTERNAL state or SUBMITTED/UNDER_REVIEW platform status', () => {
    expect(WAITING_PLATFORM_STATUSES).toEqual(['SUBMITTED', 'UNDER_REVIEW'])
    expect(isWaitingExternalItem({ execution_status: 'WAITING_EXTERNAL' })).toBe(true)
    expect(isWaitingExternalItem({ platform_status: 'SUBMITTED' })).toBe(true)
    expect(isWaitingExternalItem({ platform_status: 'UNDER_REVIEW' })).toBe(true)
    expect(isWaitingExternalItem({ platform_status: 'PUBLISHED' })).toBe(false)
    expect(isWaitingExternalItem(undefined)).toBe(false)
  })
})

describe('formatCount — 不可得渲染「—」，0 正常显示', () => {
  it('renders the placeholder for null / undefined / invalid', () => {
    expect(formatCount(null)).toBe(COUNT_PLACEHOLDER)
    expect(formatCount(undefined)).toBe(COUNT_PLACEHOLDER)
    expect(formatCount(Number.NaN)).toBe(COUNT_PLACEHOLDER)
    expect(formatCount('x')).toBe(COUNT_PLACEHOLDER)
  })

  it('renders numbers verbatim, including a real 0', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(7)).toBe('7')
  })
})

describe('isCountsUnavailable', () => {
  it('true only when all three counts are unavailable', () => {
    expect(isCountsUnavailable(null)).toBe(true)
    expect(isCountsUnavailable({ todo: null, waiting: null, blocked: null })).toBe(true)
    expect(isCountsUnavailable({ todo: 0, waiting: null, blocked: null })).toBe(false)
    expect(isCountsUnavailable({ todo: null, waiting: 1, blocked: null })).toBe(false)
  })
})
