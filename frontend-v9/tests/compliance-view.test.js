/**
 * M2-E 目的国合规依据 × 标签包的展示逻辑。
 *
 * 这些用例盯着最容易「骗人」的三种渲染：
 * ① 该国要求未收录被渲染成「无需认证」；② 缺证据被渲染成绿勾；
 * ③ 依据查不到（接口挂了）时还留着上一轮的「已具备」。
 */
import { describe, expect, it } from 'vitest'

import {
  NO_COUNTRY_HINT, complianceBasisView, evidenceFormGaps, evidencePayload, labelHistoryView,
} from '../src/shared/complianceView'

const basis = (overrides = {}) => ({
  country: 'EU',
  covered: true,
  complete: false,
  requirements: [
    { requirement: 'CE', mandatory: true, note: '欧盟 CE 标志' },
    { requirement: 'EPR', mandatory: true, note: '生产者责任延伸' },
  ],
  satisfied: [{ requirement: 'CE', evidence_ref: 'CE-2026-001', valid_until: '2030-01-01' }],
  expired: [],
  missing: [{ requirement: 'EPR', mandatory: true, note: '生产者责任延伸' }],
  blocking: [{ requirement: 'EPR', mandatory: true }],
  reasons: ['缺 EPR 证据：生产者责任延伸'],
  ...overrides,
})

describe('complianceBasisView', () => {
  it('未给依据时返回 null（「还没查」不能被画成「通过」）', () => {
    expect(complianceBasisView(null)).toBeNull()
    expect(complianceBasisView(undefined)).toBeNull()
    expect(complianceBasisView('')).toBeNull()
  })

  it('没有目的国时明确说「不做默认猜测」', () => {
    const view = complianceBasisView({ country: '' })
    expect(view.covered).toBe(false)
    expect(view.complete).toBe(false)
    expect(view.reasons).toEqual([NO_COUNTRY_HINT])
    expect(view.canGenerate).toBe(false)
  })

  it('该国要求未收录：判为「未知」而不是「无需认证」', () => {
    const view = complianceBasisView({
      country: 'SG', covered: false, complete: false,
      requirements: [], satisfied: [], missing: [], expired: [],
      reasons: ['目的国准入要求未收录：系统里 SG 一条适用要求都没有。这是「未知」而不是「无需认证」'],
    })
    expect(view.covered).toBe(false)
    expect(view.complete).toBe(false)
    expect(view.headline).toContain('不是「无需认证」')
    expect(view.reasons[0]).toContain('未收录')
    // 未收录时连「补证据」都不该放：缺的是要求本身，不是某条证据。
    expect(view.canRegisterEvidence).toBe(false)
    expect(view.canGenerate).toBe(false)
  })

  it('缺一条证据：逐条给出缺口，且不允许生成标签', () => {
    const view = complianceBasisView(basis())
    expect(view.covered).toBe(true)
    expect(view.complete).toBe(false)
    expect(view.canGenerate).toBe(false)
    expect(view.gaps.map((row) => row.requirement)).toEqual(['EPR'])
    expect(view.rows.find((row) => row.requirement === 'CE').state).toBe('SATISFIED')
    expect(view.rows.find((row) => row.requirement === 'CE').evidenceRef).toBe('CE-2026-001')
    expect(view.rows.find((row) => row.requirement === 'EPR').tone).toBe('danger')
    expect(view.headline).toContain('缺 1 项')
    expect(view.canRegisterEvidence).toBe(true)
  })

  it('证据过期算缺口（不是「有过就算具备」）', () => {
    const view = complianceBasisView(basis({
      satisfied: [{ requirement: 'EPR', evidence_ref: 'EPR-1' }],
      missing: [],
      expired: [{ requirement: 'CE', evidence_ref: '', valid_until: '2026-01-01' }],
      reasons: ['CE 证据已过期（有效期至 2026-01-01）'],
    }))
    const ce = view.rows.find((row) => row.requirement === 'CE')
    expect(ce.state).toBe('EXPIRED')
    expect(ce.stateText).toBe('已过期')
    expect(view.gaps.map((row) => row.requirement)).toEqual(['CE'])
    expect(view.complete).toBe(false)
  })

  it('非强制要求缺失不算缺口，但仍如实显示状态', () => {
    const view = complianceBasisView(basis({
      requirements: [{ requirement: 'CE', mandatory: false, note: '' }],
      satisfied: [], missing: [{ requirement: 'CE', mandatory: false }], expired: [],
      reasons: [],
    }))
    expect(view.gaps).toEqual([])
    expect(view.complete).toBe(true)
    expect(view.rows[0].state).toBe('MISSING')
    expect(view.rows[0].mandatory).toBe(false)
  })

  it('依据齐备才允许生成标签', () => {
    const view = complianceBasisView(basis({
      satisfied: [
        { requirement: 'CE', evidence_ref: 'CE-2026-001' },
        { requirement: 'EPR', evidence_ref: 'EPR-DE-9' },
      ],
      missing: [], expired: [], reasons: [],
    }))
    expect(view.complete).toBe(true)
    expect(view.canGenerate).toBe(true)
    expect(view.tone).toBe('success')
    expect(view.rows.every((row) => row.state === 'SATISFIED')).toBe(true)
  })
})

describe('evidenceFormGaps / evidencePayload', () => {
  it('缺证据引用一律拦住（空引用等于没有证据）', () => {
    const gaps = evidenceFormGaps({ destination_country: 'DE', requirement: 'CE', evidence_ref: '  ' })
    expect(gaps.join('；')).toContain('证据引用不能为空')
  })

  it('有效期格式不合法时报错', () => {
    const gaps = evidenceFormGaps({
      destination_country: 'DE', requirement: 'CE', evidence_ref: 'CE-1', valid_until: '2030/01/01',
    })
    expect(gaps.join('；')).toContain('YYYY-MM-DD')
  })

  it('提交体不发送空有效期，国家码归一为大写', () => {
    const payload = evidencePayload({
      destination_country: 'de', requirement: ' CE ', evidence_ref: ' CE-1 ', note: '', valid_until: '',
    })
    expect(payload.destination_country).toBe('DE')
    expect(payload.requirement).toBe('CE')
    expect(payload.evidence_ref).toBe('CE-1')
    expect('valid_until' in payload).toBe(false)
  })
})

describe('labelHistoryView', () => {
  it('按版本倒序，并统计印刷前待补项', () => {
    const rows = labelHistoryView([
      { id: 1, version: 1, action: 'GENERATE', destination_country: 'EU',
        content: { marks: [{ requirement: 'CE' }] }, content_digest: 'abcdef1234567890',
        created_at: '2026-11-07T10:00:00', open_items: ['印刷信息需人工补全'] },
      { id: 2, version: 2, action: 'REGENERATE', destination_country: 'EU',
        content: { marks: [] }, content_digest: 'ffffffff00000000',
        created_at: '2026-11-08T10:00:00', open_items: [] },
    ])
    expect(rows.map((row) => row.version)).toEqual([2, 1])
    expect(rows[1].marks).toEqual(['CE'])
    expect(rows[1].shortDigest).toBe('abcdef123456')
    expect(rows[1].openItemCount).toBe(1)
    expect(rows[0].openItemCount).toBe(0)
  })

  it('脏数据不炸：非数组、缺版本号的一律丢弃', () => {
    expect(labelHistoryView(null)).toEqual([])
    expect(labelHistoryView([{ id: 1 }, { id: 2, version: 0 }])).toEqual([])
  })
})
