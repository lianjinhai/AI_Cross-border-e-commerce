import { describe, it, expect } from 'vitest'
import {
  ACTION_LABELS,
  actionTypeOptions,
  canOperateAction,
  nextActionHint,
} from '../../src/shared/actionView'

describe('actionTypeOptions', () => {
  it('优先使用服务端能力矩阵的已注册类型', () => {
    const options = actionTypeOptions({
      actions: [
        { action_type: 'CREATE_AD_CAMPAIGN_DRAFT', enabled: true },
        { action_type: 'PUBLISH_LISTING', enabled: false },
      ],
    })
    expect(options.map((o) => o.value)).toEqual([
      'CREATE_AD_CAMPAIGN_DRAFT',
      'PUBLISH_LISTING',
    ])
    expect(options[0].label).toBe('创建广告草稿')
    expect(options[1].label).toBe('发布 Listing（不可执行）')
  })

  it('能力矩阵缺失时退回本地已知清单（不出现未注册的 REPRICE/RESTOCK）', () => {
    const values = actionTypeOptions(null).map((o) => o.value)
    expect(values).toContain('UPDATE_PRODUCT_CONTENT')
    expect(values).not.toContain('REPRICE')
    expect(values).not.toContain('RESTOCK')
    expect(values.length).toBe(Object.keys(ACTION_LABELS).length)
  })

  it('未知类型回显原值，不臆造中文名', () => {
    const options = actionTypeOptions({ actions: [{ action_type: 'FUTURE_TYPE', enabled: true }] })
    expect(options[0].label).toBe('FUTURE_TYPE')
  })

  it('无 actions 字段时不抛错', () => {
    expect(() => actionTypeOptions({})).not.toThrow()
    expect(actionTypeOptions({}).length).toBeGreaterThan(0)
  })
})

describe('canOperateAction', () => {
  it('按行上的 required_permission 判定', () => {
    const row = { required_permission: 'approve_action' }
    expect(canOperateAction(row, (p) => p === 'approve_action')).toBe(true)
    expect(canOperateAction(row, () => false)).toBe(false)
  })

  it('无 required_permission 时使用兜底值（默认 fail-closed）', () => {
    expect(canOperateAction({}, () => true)).toBe(false)
    expect(canOperateAction({}, () => false, true)).toBe(true)
  })

  it('权限函数抛错视为不可操作', () => {
    const row = { required_permission: 'execute_action' }
    expect(
      canOperateAction(row, () => {
        throw new Error('context missing')
      }),
    ).toBe(false)
  })
})

describe('nextActionHint', () => {
  it('不可操作时优先展示服务端阻断原因', () => {
    expect(
      nextActionHint(
        { status: 'PENDING_APPROVAL', required_permission: 'approve_action' },
        { operable: false, blockedReasons: ['角色无权审批', '店铺范围受限'] },
      ),
    ).toBe('角色无权审批；店铺范围受限')
  })

  it('不可操作且无阻断原因时说明缺哪个权限', () => {
    expect(
      nextActionHint({ required_permission: 'approve_action' }, { operable: false }),
    ).toBe('缺少权限 approve_action')
  })

  it('可操作时按状态给出下一动作', () => {
    expect(nextActionHint({ status: 'PENDING_APPROVAL' }, { operable: true })).toBe('待审批')
    expect(nextActionHint({ status: 'APPROVED' }, { operable: true })).toBe('待执行')
    expect(nextActionHint({ status: 'SUCCESS' }, { operable: true })).toBe('已完成')
    expect(nextActionHint({ status: 'UNKNOWN' }, { operable: true })).toBe('—')
  })
})
