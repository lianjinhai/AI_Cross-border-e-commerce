import { describe, expect, it } from 'vitest'

import { buildRoundChain, roundChainHint } from '../src/shared/launchRounds'

/** 造一条流程列表项。 */
function row(id, createdAt, isHistory) {
  return {
    id,
    created_at: createdAt,
    is_history: isHistory,
    execution_status: isHistory ? 'COMPLETED' : 'WAITING_EXTERNAL',
    platform_status: isHistory ? 'OFFLINE' : 'UNDER_REVIEW',
  }
}

describe('buildRoundChain', () => {
  it('按创建时间升序编号，最早的是第 1 轮', () => {
    const { rounds } = buildRoundChain([
      row(30, '2026-11-03T10:00:00', false),
      row(10, '2026-11-01T10:00:00', true),
      row(20, '2026-11-02T10:00:00', true),
    ])
    expect(rounds.map((item) => item.id)).toEqual([10, 20, 30])
    expect(rounds.map((item) => item.round)).toEqual([1, 2, 3])
  })

  it('时间相同时按 id 升序，结果稳定', () => {
    const same = '2026-11-01T10:00:00'
    const { rounds } = buildRoundChain([row(12, same, true), row(11, same, true)])
    expect(rounds.map((item) => item.id)).toEqual([11, 12])
  })

  it('标记当前查看的轮次，且只有一个', () => {
    const { rounds } = buildRoundChain([
      row(10, '2026-11-01T10:00:00', true),
      row(20, '2026-11-02T10:00:00', false),
    ], 20)
    expect(rounds.filter((item) => item.is_current).map((item) => item.id)).toEqual([20])
  })

  it('未传 currentId 时不标记任何轮次为当前', () => {
    const { rounds } = buildRoundChain([row(10, '2026-11-01T10:00:00', true)])
    expect(rounds.some((item) => item.is_current)).toBe(false)
  })

  it('活跃槽只有一个时不报异常', () => {
    const { activeCount, anomalies } = buildRoundChain([
      row(10, '2026-11-01T10:00:00', true),
      row(20, '2026-11-02T10:00:00', false),
    ])
    expect(activeCount).toBe(1)
    expect(anomalies).toEqual([])
  })

  it('出现多个活跃槽时显式报异常，不静默吞掉', () => {
    const { activeCount, anomalies } = buildRoundChain([
      row(10, '2026-11-01T10:00:00', false),
      row(20, '2026-11-02T10:00:00', false),
    ])
    expect(activeCount).toBe(2)
    expect(anomalies).toHaveLength(1)
    expect(anomalies[0]).toContain('仅一个活跃槽')
  })

  it('全部是历史轮次时活跃槽为 0', () => {
    const { activeCount, anomalies } = buildRoundChain([
      row(10, '2026-11-01T10:00:00', true),
    ])
    expect(activeCount).toBe(0)
    expect(anomalies).toEqual([])
  })

  it('丢弃缺少数字 id 的脏数据，不让它打乱编号', () => {
    const { rounds } = buildRoundChain([
      row(10, '2026-11-01T10:00:00', true),
      { id: null, created_at: '2026-11-02T10:00:00', is_history: true },
      null,
    ])
    expect(rounds.map((item) => item.id)).toEqual([10])
  })

  it('空输入返回空链而不是抛错', () => {
    expect(buildRoundChain().rounds).toEqual([])
    expect(buildRoundChain(null).rounds).toEqual([])
  })

  it('槽位标签区分历史与活跃，避免「活跃 = 成功」误读', () => {
    const { rounds } = buildRoundChain([
      row(10, '2026-11-01T10:00:00', true),
      row(20, '2026-11-02T10:00:00', false),
    ])
    expect(rounds[0].slot_label).toBe('历史')
    expect(rounds[1].slot_label).toBe('活跃槽')
  })

  it('服务端总数大于本次条数时报分页截断，不让编号静默失真', () => {
    const { anomalies } = buildRoundChain([
      row(10, '2026-11-01T10:00:00', true),
      row(20, '2026-11-02T10:00:00', false),
    ], 20, 25)
    expect(anomalies).toHaveLength(1)
    expect(anomalies[0]).toContain('25')
    expect(anomalies[0]).toContain('轮次编号可能不完整')
  })

  it('总数与条数一致时不报截断', () => {
    const { anomalies } = buildRoundChain([
      row(10, '2026-11-01T10:00:00', true),
      row(20, '2026-11-02T10:00:00', false),
    ], 20, 2)
    expect(anomalies).toEqual([])
  })
})

describe('roundChainHint', () => {
  it('历史轮次提示只读回看', () => {
    expect(roundChainHint({ currentIsHistory: true, activeCount: 1 })).toContain('历史轮次')
  })

  it('没有活跃槽时提示可发起新一轮', () => {
    expect(roundChainHint({ activeCount: 0 })).toContain('可发起新一轮')
  })

  it('存在活跃槽时说明在售/暂停都不释放槽位', () => {
    expect(roundChainHint({ activeCount: 1 })).toContain('不会释放')
  })

  it('多个活跃槽优先报异常', () => {
    expect(roundChainHint({ activeCount: 2 })).toContain('数据异常')
  })
})
