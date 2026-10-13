import { describe, expect, it } from 'vitest'

import {
  applyView, applyViewToFilters, deleteView, loadViews, sanitizeViewFilters, saveView,
} from '../src/composables/launchViews'

/** 内存 storage（隔离 localStorage，vitest 直测纯函数）。 */
function memStorage(initial = {}) {
  const store = new Map(Object.entries(initial))
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  }
}

describe('sanitizeViewFilters（只挑可保存键、剔除空值）', () => {
  it('丢弃不可保存键（分页/未知键）与空值', () => {
    const clean = sanitizeViewFilters({
      platform: 'amazon', market: 'US', page_num: 3, junk: 'x',
      mine: false, execution_status: '', shop_id: null,
    })
    expect(clean).toEqual({ platform: 'amazon', market: 'US' })
  })

  it('布尔 true 与数值 0 均为有效筛选值', () => {
    const clean = sanitizeViewFilters({ mine: true, blocked_only: true, product_id: 0 })
    expect(clean).toEqual({ mine: true, blocked_only: true, product_id: 0 })
  })

  it('空输入得到空对象', () => {
    expect(sanitizeViewFilters()).toEqual({})
  })
})

describe('保存视图 CRUD（storage 注入）', () => {
  it('saveView 新增并置顶，同名覆盖不重复', () => {
    const storage = memStorage()
    saveView('a', { platform: 'amazon' }, storage)
    saveView('b', { market: 'US' }, storage)
    saveView('a', { platform: 'tiktok' }, storage)
    const views = loadViews(storage)
    expect(views.map((v) => v.name)).toEqual(['a', 'b'])
    expect(views[0].filters).toEqual({ platform: 'tiktok' })
  })

  it('空名 saveView 抛错且不写入', () => {
    const storage = memStorage()
    expect(() => saveView('  ', {}, storage)).toThrow('视图名不能为空')
    expect(loadViews(storage)).toEqual([])
  })

  it('最多保留 10 个视图（旧的先淘汰）', () => {
    const storage = memStorage()
    for (let i = 0; i < 12; i += 1) saveView(`v${i}`, {}, storage)
    const views = loadViews(storage)
    expect(views).toHaveLength(10)
    expect(views[0].name).toBe('v11')
    expect(views[9].name).toBe('v2')
  })

  it('loadViews 容错：存储损坏/非数组/坏元素一律 fail-safe', () => {
    expect(loadViews(memStorage({ v9_launch_views: '{broken' }))).toEqual([])
    expect(loadViews(memStorage({ v9_launch_views: '{"x":1}' }))).toEqual([])
    expect(loadViews(memStorage({
      v9_launch_views: JSON.stringify([null, { name: 1 }, { name: 'ok', filters: {} }]),
    }))).toEqual([{ name: 'ok', filters: {} }])
  })

  it('deleteView 删除指定视图，未命中原样返回', () => {
    const storage = memStorage()
    saveView('a', {}, storage)
    saveView('b', {}, storage)
    expect(deleteView('a', storage).map((v) => v.name)).toEqual(['b'])
    expect(deleteView('ghost', storage)).toHaveLength(1)
  })

  it('applyView 返回干净副本；视图载荷被 sanitize', () => {
    const applied = applyView({ filters: { platform: 'amazon', page_num: 5, evil: 1 } })
    expect(applied).toEqual({ platform: 'amazon' })
    expect(applyView({})).toEqual({})
  })

  it('applyViewToFilters（P2-1）：视图键覆盖现值，未覆盖键保留', () => {
    const current = { platform: 'shopee', market: 'US', mine: true, execution_status: 'BLOCKED' }
    const merged = applyViewToFilters(current, { filters: { platform: 'amazon' } })
    expect(merged).toEqual({ platform: 'amazon', market: 'US', mine: true, execution_status: 'BLOCKED' })
    // 不可变：合并不污染当前筛选对象
    expect(current.platform).toBe('shopee')
  })
})
