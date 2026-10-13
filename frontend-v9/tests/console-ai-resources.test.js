import { describe, expect, it } from 'vitest'
import {
  AI_RESOURCE_SECTIONS,
  hasAiQuotaSource,
  aiSectionState,
  aiResourcesPendingCopy,
  aiNumberOrDash,
} from '../src/shared/consoleAiResources'

/**
 * 控制台 AI 资源与成本纯函数回归（蓝图 R1 包 3 · PC-05，§B.3 / §5.19 / §F#8）。
 *
 * 红线：ai 配额读端点未核 → 无真实数据不渲染图表、不编造 Token 成本，
 * 缺项显"未接入"。
 */
describe('AI_RESOURCE_SECTIONS 字典', () => {
  it('五类展示区：模型路由/Token成本/限流/失败/配额', () => {
    expect(AI_RESOURCE_SECTIONS.map((s) => s.code)).toEqual(
      ['model_route', 'token_cost', 'throttle', 'failure', 'quota'],
    )
  })
})

describe('hasAiQuotaSource — 配额数据源判定', () => {
  it('未核（null/undefined）→ false', () => {
    expect(hasAiQuotaSource(null)).toBe(false)
    expect(hasAiQuotaSource(undefined)).toBe(false)
    expect(hasAiQuotaSource({})).toBe(false)
  })

  it('显式含 used+limit → true；缺其一无 true', () => {
    expect(hasAiQuotaSource({ used: 10, limit: 100 })).toBe(true)
    expect(hasAiQuotaSource({ used: 10 })).toBe(false)
    expect(hasAiQuotaSource({ limit: 100 })).toBe(false)
  })

  it('非对象 → false', () => {
    expect(hasAiQuotaSource('x')).toBe(false)
    expect(hasAiQuotaSource(42)).toBe(false)
  })
})

describe('aiSectionState — 区块主态（11 态码）', () => {
  it('无真实数据 → NOT_CONFIGURED + "未接入"（不渲染图表）', () => {
    const s = aiSectionState(false)
    expect(s.code).toBe('NOT_CONFIGURED')
    expect(s.title).toBe('未接入')
    expect(s.tone).toBe('neutral')
  })

  it('有真实数据 → ready + 空标题', () => {
    const s = aiSectionState(true)
    expect(s.code).toBe('ready')
    expect(s.title).toBe('')
  })
})

describe('aiResourcesPendingCopy — 待接入文案', () => {
  it('集中产出"AI 资源配额未接入"提示（不编造 Token 成本）', () => {
    const copy = aiResourcesPendingCopy()
    expect(copy.title).toBe('AI 资源配额未接入')
    expect(copy.detail).toContain('不渲染图表')
  })
})

describe('aiNumberOrDash — 缺值不渲染 0', () => {
  it('null/undefined → "—"（避免假数字）', () => {
    expect(aiNumberOrDash(null)).toBe('—')
    expect(aiNumberOrDash(undefined)).toBe('—')
  })

  it('有值 → 原样返回', () => {
    expect(aiNumberOrDash(42)).toBe(42)
    expect(aiNumberOrDash('12 tokens')).toBe('12 tokens')
  })
})
