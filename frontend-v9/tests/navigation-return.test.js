import { describe, expect, it } from 'vitest'
import {
  RETURN_WHITELIST, isSafeReturnTo, sanitizeReturnTo,
} from '../src/shared/navigationReturn'
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

  it('R3-3：放行 AppShell 站内 /app 前缀路由（含带筛选 query）', () => {
    expect(isSafeReturnTo('/app')).toBe(true)
    expect(isSafeReturnTo('/app/tasks')).toBe(true)
    expect(isSafeReturnTo('/app/tasks?view=blocked&store=%E7%BE%8E%E5%9B%BD%E7%AB%99')).toBe(true)
    expect(isSafeReturnTo('/app/products/7')).toBe(true)
    expect(isSafeReturnTo('/app/launch/4?return_to=/app/tasks')).toBe(true)
    // 形近不越界：/application 不是 /app 前缀路径
    expect(isSafeReturnTo('/application')).toBe(false)
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

  it('白名单为上线可挂接路径 + /app 站内前缀（R3-3）', () => {
    expect([...RETURN_WHITELIST].sort()).toEqual(['/app', '/launch', '/listings', '/products', '/shops'])
  })
})
