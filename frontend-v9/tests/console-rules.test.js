import { describe, expect, it } from 'vitest'
import {
  RULES_COLUMNS,
  RULES_ACTIONS,
  ruleMissingCopy,
  ruleCellText,
  rulesWritePolicy,
} from '../src/shared/consoleRules'

/**
 * 控制台数据源与规则纯函数回归（蓝图 R1 包 3 · PC-04，§B.3 / §5.19）。
 *
 * 红线：缺项（有效期/最近拉取/回滚）显"—"或"未接入"，不编造；
 * 规则写端点未接入 → 写动作灰化，不触发 API。
 */
describe('RULES_COLUMNS / RULES_ACTIONS 字典', () => {
  it('规则列含版本/有效期/最近拉取/错误/回滚', () => {
    const keys = RULES_COLUMNS.map((c) => c.key)
    for (const k of ['version', 'valid_until', 'last_fetched', 'last_error', 'rollback']) {
      expect(keys).toContain(k)
    }
  })

  it('写动作 = 启用/停用', () => {
    expect(RULES_ACTIONS.map((a) => a.code)).toEqual(['enable', 'disable'])
  })
})

describe('ruleMissingCopy — 缺项文案', () => {
  it.each([
    ['valid_until', '有效期未接入'],
    ['last_fetched', '最近拉取未接入'],
    ['rollback', '回滚未接入'],
    ['version', '版本未知'],
  ])('%s → 对应未接入文案', (field, expected) => {
    expect(ruleMissingCopy(field)).toBe(expected)
  })

  it('未知字段回落"未接入"', () => {
    expect(ruleMissingCopy('unknown_field')).toBe('未接入')
  })
})

describe('ruleCellText — 缺值不渲染 0/假数据', () => {
  it('值存在 → 原样字符串', () => {
    expect(ruleCellText({ version: 'v2.1' }, 'version')).toBe('v2.1')
  })

  it('值缺失 → 对应缺项文案（last_error 显"—"）', () => {
    expect(ruleCellText({ last_error: null }, 'last_error')).toBe('—')
    expect(ruleCellText({ valid_until: null }, 'valid_until')).toBe('有效期未接入')
    expect(ruleCellText({}, 'rollback')).toBe('回滚未接入')
  })

  it('空串视同缺失', () => {
    expect(ruleCellText({ version: '' }, 'version')).toBe('版本未知')
  })
})

describe('rulesWritePolicy — 写动作可用性', () => {
  it('写端点未接入（默认）→ 全部不可执行 + 原因', () => {
    expect(rulesWritePolicy('enable', { rulesWriteAvailable: false }).executable).toBe(false)
    expect(rulesWritePolicy('disable', { rulesWriteAvailable: false }).reason).toBe('规则写端点待接入，暂不可用')
  })

  it('写端点已接入 + 合法动作 → 可执行', () => {
    const p = rulesWritePolicy('enable', { rulesWriteAvailable: true })
    expect(p.executable).toBe(true)
    expect(p.reason).toBe('')
  })

  it('未知动作 → 不可执行 + 未知操作', () => {
    const p = rulesWritePolicy('reboot', { rulesWriteAvailable: true })
    expect(p.executable).toBe(false)
    expect(p.reason).toBe('未知操作')
  })
})
