import { describe, expect, it } from 'vitest'
import {
  resolveStatusTag,
  STATUS_LABEL_MAP,
  STATUS_TAG_MAP,
} from '../src/shared/statusDict'

/**
 * UX-01：RunStatus.vue 的字典迁移为纯函数后的行为锁定。
 * 项目未装 @vue/test-utils，故以纯函数方式断言（沿用 publish-actions.test.js 风格）。
 */
describe('resolveStatusTag', () => {
  it('maps known statuses to the same el-tag types as before', () => {
    expect(resolveStatusTag('published').type).toBe('success')
    expect(resolveStatusTag('running').type).toBe('primary')
    expect(resolveStatusTag('partial').type).toBe('warning')
  })

  it('keeps the original label text (no wording change)', () => {
    expect(resolveStatusTag('published')).toEqual({ type: 'success', label: '已发布' })
    expect(resolveStatusTag('blocked')).toEqual({ type: 'warning', label: '等待人工' })
    expect(resolveStatusTag('mid')).toEqual({ type: 'warning', label: '中' })
  })

  it('falls back to info + raw status for unknown values', () => {
    expect(resolveStatusTag('weird')).toEqual({ type: 'info', label: 'weird' })
    expect(resolveStatusTag(undefined)).toEqual({ type: 'info', label: undefined })
  })

  it('accepts a table argument without changing behaviour', () => {
    expect(resolveStatusTag('failed', 'launch')).toEqual({ type: 'danger', label: '失败' })
    expect(resolveStatusTag('high', 'risk')).toEqual({ type: 'danger', label: '高' })
  })

  it('exposes the frozen dictionaries', () => {
    expect(STATUS_TAG_MAP.published).toBe('success')
    expect(STATUS_LABEL_MAP.running).toBe('运行中')
  })
})
