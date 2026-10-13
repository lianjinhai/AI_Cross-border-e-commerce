import { describe, expect, it } from 'vitest'

import {
  IMPERSONATION_KEY, buildImpersonationSnapshot, isImpersonating,
  parseImpersonationSnapshot, restoreImpersonation, saveImpersonationSnapshot,
} from '../src/composables/impersonation'

function memStorage(initial = {}) {
  const store = new Map(Object.entries(initial))
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  }
}

describe('buildImpersonationSnapshot / parse', () => {
  it('构造快照：token/user/tenant 三元组', () => {
    expect(buildImpersonationSnapshot({ token: 't1', user: { id: 1 }, tenantName: 'A 公司' }))
      .toEqual({ token: 't1', user: { id: 1 }, tenant: 'A 公司' })
  })

  it('异常输入归一：非字符串 token 归空、非对象 user 归 null', () => {
    expect(buildImpersonationSnapshot({ token: 42, user: 'x', tenantName: 7 }))
      .toEqual({ token: '', user: null, tenant: '7' })
  })

  it('parse：损坏 JSON / 非对象返回 null（fail-safe）', () => {
    expect(parseImpersonationSnapshot('{broken')).toBeNull()
    expect(parseImpersonationSnapshot('42')).toBeNull()
    expect(parseImpersonationSnapshot(null)).toBeNull()
  })
})

describe('save / isImpersonating / restore（storage 注入）', () => {
  it('save：写入快照 + 替换 token；isImpersonating 判定有效快照', () => {
    const storage = memStorage({ erp_token: 'platform-token', erp_user: '{"id":9}' })
    const snapshot = saveImpersonationSnapshot(
      { token: 'platform-token', user: { id: 9 }, tenantName: 'A' }, 'tenant-token', storage)
    expect(snapshot).toEqual({ token: 'platform-token', user: { id: 9 }, tenant: 'A' })
    expect(storage.getItem('erp_token')).toBe('tenant-token')
    expect(isImpersonating(storage)).toBe(true)
  })

  it('空 token 快照不视为代客中（isImpersonating=false）', () => {
    const storage = memStorage()
    storage.setItem(IMPERSONATION_KEY, JSON.stringify({ token: '', user: null, tenant: 'x' }))
    expect(isImpersonating(storage)).toBe(false)
  })

  it('restore：还原平台 token/user、清快照，返回 true', () => {
    const storage = memStorage()
    saveImpersonationSnapshot({ token: 'p1', user: { id: 2 }, tenantName: 'B' }, 't9', storage)
    expect(restoreImpersonation(storage)).toBe(true)
    expect(storage.getItem('erp_token')).toBe('p1')
    expect(JSON.parse(storage.getItem('erp_user'))).toEqual({ id: 2 })
    expect(storage.getItem(IMPERSONATION_KEY)).toBeNull()
  })

  it('restore：无快照仅清标记并返回 false（不伪造平台身份）', () => {
    const storage = memStorage({ erp_token: 'tenant-token' })
    expect(restoreImpersonation(storage)).toBe(false)
    expect(storage.getItem('erp_token')).toBe('tenant-token')
    expect(storage.getItem(IMPERSONATION_KEY)).toBeNull()
  })

  it('restore：快照损坏（无 token）返回 false 且清除坏数据', () => {
    const storage = memStorage({ [IMPERSONATION_KEY]: '{broken' })
    expect(restoreImpersonation(storage)).toBe(false)
    expect(storage.getItem(IMPERSONATION_KEY)).toBeNull()
  })
})
