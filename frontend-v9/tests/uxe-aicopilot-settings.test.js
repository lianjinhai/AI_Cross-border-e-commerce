import { describe, expect, it } from 'vitest'
import {
  AI_SESSION_PERSIST_NOTE, COPILOT_SUGGESTIONS,
  buildActionConfirm, contextLabel, contextualSuggestions, resolveCopilotActions,
} from '../src/features/aicopilot/actions'
import { ROLE_CHANGE_NOTE, ROLE_GUIDES, ROLE_OPTIONS, roleEnumLabel } from '../src/features/settings/roleGuides'

/**
 * UX-E aicopilot 动作模型 + settings 角色说明卡纯函数测试。
 */

const allowAll = { can: () => true }
const denyAll = { can: () => false }

describe('aicopilot actions', () => {
  it('maps known action keys to ready navigation', () => {
    const vms = resolveCopilotActions(['pick_candidates', 'scan_trends', 'reprice_batch'], allowAll)
    expect(vms.every((v) => v.status === 'ready')).toBe(true)
    expect(vms[0].route).toBe('/app/market/discovery')
    expect(vms[2].route).toBe('/app/pricing')
  })

  it('unknown backend keys become WaitingExternal (no fake entries)', () => {
    const vms = resolveCopilotActions(['future_action'], allowAll)
    expect(vms[0].status).toBe('waiting')
    expect(vms[0].reason).toContain('待接入')
    expect(vms[0].route).toBeUndefined()
  })

  it('navigation actions without permission requirements are always ready', () => {
    // 现有 ACTION_META 均为只读导航（无 permission 要求）；denyAll 下仍可跳转，
    // 写权限由目标页与后端把关——前端不造假入口，也不虚拦只读导航。
    const vms = resolveCopilotActions(['pick_candidates'], denyAll)
    expect(vms[0].status).toBe('ready')
  })

  it('builds confirm dialog text from the view model', () => {
    const [vm] = resolveCopilotActions(['reprice_batch'], allowAll)
    expect(buildActionConfirm(vm)).toContain('查看动态定价明细')
    expect(buildActionConfirm(vm)).toContain('reprice_batch')
  })

  it('gives context-aware suggestions per route domain with fallback', () => {
    expect(contextualSuggestions({ domain: '市场机会' })).toEqual(['帮我选品', '看看市场趋势'])
    expect(contextualSuggestions({ domain: '经营优化' })).toEqual(['重新定价', '有什么风险'])
    expect(contextualSuggestions({ domain: '不存在的域' })).toEqual(COPILOT_SUGGESTIONS)
    expect(contextualSuggestions({})).toEqual(COPILOT_SUGGESTIONS)
    expect(contextLabel({ title: '动态定价' })).toBe('当前页面：动态定价')
    expect(contextLabel({})).toBe('')
  })

  it('persists the session note but never a history entry', () => {
    expect(AI_SESSION_PERSIST_NOTE).toContain('待接入')
    expect(AI_SESSION_PERSIST_NOTE).toContain('不保留')
  })
})

describe('settings roleGuides', () => {
  it('maps legacy submit values to context-authoritative enums', () => {
    expect(roleEnumLabel('admin')).toBe('OWNER')
    expect(roleEnumLabel('compliance_approver')).toBe('COMPLIANCE')
    expect(roleEnumLabel('operator')).toBe('OPERATOR')
    expect(roleEnumLabel('viewer')).toBe('READ_ONLY')
    expect(roleEnumLabel('unknown')).toBe('unknown')
  })

  it('option values are the only backend-accepted legacy roles', () => {
    expect(ROLE_OPTIONS.map((o) => o.value))
      .toEqual(['admin', 'compliance_approver', 'operator', 'viewer'])
    expect(ROLE_OPTIONS.every((o) => o.label.includes(roleEnumLabel(o.value)))).toBe(true)
  })

  it('has one guide card per enum with non-empty points', () => {
    expect(ROLE_GUIDES.map((g) => g.key)).toEqual(['OWNER', 'OPERATOR', 'COMPLIANCE', 'READ_ONLY'])
    for (const g of ROLE_GUIDES) {
      expect(g.points.length).toBeGreaterThan(0)
      expect(g.title).toContain(g.key)
    }
    expect(ROLE_CHANGE_NOTE).toContain('fail-closed')
  })
})
