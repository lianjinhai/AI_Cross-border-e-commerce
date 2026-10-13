import { describe, expect, it } from 'vitest'
import {
  FACTORY_TASK_KINDS,
  TASK_QUEUE_STATE,
  queueStateCode,
  writeActionPolicy,
  pendingIntegrationCopy,
  labelingScopeNote,
} from '../src/shared/factoryTasks'

/**
 * 工厂任务投影纯函数回归（蓝图 R1 包 3 · FP-04 备货/贴标，§B.3 / §F#5）。
 *
 * 红线：task projection 未接入 → 写动作全部不可执行（灰化 + 原因），
 * 队列无数据源 → 落空态（EMPTY_NEW），不编造任务、不触发假 API。
 */
describe('writeActionPolicy — 写操作可用性（§F#5 三按钮灰化）', () => {
  it.each(['accept', 'submit_proof', 'cannot_complete'])(
    '%s 在 projection 未接入时不可执行且附原因',
    (actionCode) => {
      const p = writeActionPolicy(actionCode, { projectionAvailable: false })
      expect(p.executable).toBe(false)
      expect(p.reason).toBe('任务同步待接入，写操作暂缺')
      expect(p.code).toBe(actionCode)
    },
  )

  it('projection 已接入 + 能力匹配时才可执行', () => {
    const p = writeActionPolicy('accept', { projectionAvailable: true, capability: 'accept' })
    expect(p.executable).toBe(true)
    expect(p.reason).toBe('')
  })

  it('projection 已接入但能力不匹配时仍不可执行', () => {
    const p = writeActionPolicy('accept', { projectionAvailable: true, capability: 'submit_proof' })
    expect(p.executable).toBe(false)
    expect(p.reason).toBe('该任务未开放此操作')
  })

  it('未知动作码 → 不可执行 + 未知操作原因', () => {
    const p = writeActionPolicy('unknown_action', { projectionAvailable: true })
    expect(p.executable).toBe(false)
    expect(p.reason).toBe('未知操作')
  })
})

describe('queueStateCode — 队列主态推导', () => {
  it('loading 优先 → LOADING', () => {
    expect(queueStateCode(true, false, 5)).toBe(TASK_QUEUE_STATE.LOADING)
  })

  it('error → ERROR', () => {
    expect(queueStateCode(false, true, 3)).toBe(TASK_QUEUE_STATE.ERROR)
  })

  it('空队列（无数据源）→ EMPTY_NEW（待接入语境"暂无任务"）', () => {
    expect(queueStateCode(false, false, 0)).toBe(TASK_QUEUE_STATE.EMPTY)
    expect(TASK_QUEUE_STATE.EMPTY).toBe('EMPTY_NEW')
  })

  it('有数据 → ready', () => {
    expect(queueStateCode(false, false, 4)).toBe(TASK_QUEUE_STATE.READY)
  })
})

describe('factoryTasks — 文案与字典', () => {
  it('任务类型字典含备货/贴标两类', () => {
    expect(FACTORY_TASK_KINDS.stocking.label).toBe('备货')
    expect(FACTORY_TASK_KINDS.labeling.label).toBe('贴标')
  })

  it('待接入文案集中产出（不页面自写）', () => {
    const copy = pendingIntegrationCopy()
    expect(copy.title).toBe('任务同步待接入')
    expect(copy.detail).toContain('暂不可用')
  })

  it('贴标授权边界说明：贴标 ≠ 批准整条 Launch', () => {
    expect(labelingScopeNote()).toContain('不代表其能批准整条 Launch')
  })
})
