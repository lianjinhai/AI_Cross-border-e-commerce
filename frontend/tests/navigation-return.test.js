import { describe, expect, it } from 'vitest'
import {
  RETURN_WHITELIST, isSafeReturnTo, sanitizeReturnTo,
} from '../src/utils/navigationReturn'
import * as launchCenter from '../src/composables/launchCenter'

/**
 * UX-03：站内回跳白名单（AC-14.7 闭环）——迁入中立模块后的行为回归。
 */
describe('isSafeReturnTo', () => {
  it('放行白名单内路径（含 query / hash / 子路径）', () => {
    expect(isSafeReturnTo('/listings/3?x=1')).toBe(true)
    expect(isSafeReturnTo('/products')).toBe(true)
    expect(isSafeReturnTo('/shops')).toBe(true)
    expect(isSafeReturnTo('/launch?page_num=2')).toBe(true)
    expect(isSafeReturnTo('/launch/12')).toBe(true)
  })

  it('拒绝站外 / 协议相对 / 目录穿越 / 形近路径', () => {
    expect(isSafeReturnTo('//evil.com')).toBe(false)
    expect(isSafeReturnTo('https://x')).toBe(false)
    expect(isSafeReturnTo('/etc/../a')).toBe(false)
    expect(isSafeReturnTo('/launcha')).toBe(false)
    expect(isSafeReturnTo('/orders')).toBe(false)
    expect(isSafeReturnTo('')).toBe(false)
    expect(isSafeReturnTo(null)).toBe(false)
  })
})

describe('sanitizeReturnTo', () => {
  it('合法路径原样返回，非法路径回退 fallback', () => {
    expect(sanitizeReturnTo('/listings/3')).toBe('/listings/3')
    expect(sanitizeReturnTo('//evil.com')).toBe('/launch')
    expect(sanitizeReturnTo('//evil.com', '/launch/9')).toBe('/launch/9')
    expect(sanitizeReturnTo('/launch/9', '/launch/9')).toBe('/launch/9')
  })
})

describe('launchCenter 重新导出保持公共 API 稳定', () => {
  it('三个符号与中立模块同一引用', () => {
    expect(launchCenter.isSafeReturnTo).toBe(isSafeReturnTo)
    expect(launchCenter.sanitizeReturnTo).toBe(sanitizeReturnTo)
    expect(launchCenter.RETURN_WHITELIST).toEqual(RETURN_WHITELIST)
  })

  it('白名单已扩为 4 条上线可挂接路径', () => {
    expect([...RETURN_WHITELIST].sort()).toEqual(['/launch', '/listings', '/products', '/shops'])
  })
})
