import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * F01 上线中心数据层契约（T04）。
 *
 * 数据层被 api 拦截器与组件共同依赖，两处最易回归的点单独固化：
 *   1. 写路径必须带 `Idempotency-Key` 头与 body `expected_revision`（缺一后端 409/422）。
 *   2. 列表请求字段名是服务端契约的 `page_num`（前端曾误用 `page`）。
 * 纯函数（状态文案/空态分因/return_to/错误 envelope）与组件解耦，直接测。
 */
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../src/api', () => ({ default: { get: mocks.get, post: mocks.post } }))

const {
  PLATFORM_STATUS, blockerText, buildReturnTo, detailPath, emptyStateReason, errorEnvelope,
  executeAction, executionStatusMeta, guidedSummary, isSafeReturnTo, listLaunches, listQuery,
  loadContext, newIdempotencyKey, nextActionText, ownerText, parseReturnTo, platformStatusMeta,
  progressText, revisionConflict, sanitizeReturnTo, statusMeta, syncLaunch,
} = await import('../src/composables/launchCenter')

beforeEach(() => vi.resetAllMocks())

describe('数据层写路径契约（Idempotency-Key + expected_revision）', () => {
  it('executeAction 必带幂等头、步骤码与预期版本', async () => {
    mocks.post.mockResolvedValue({ data: { status: 'EXECUTED' } })
    await executeAction(7, 'COMPLETE_DATA', { note: 'x' },
      { expectedRevision: 3, stepCode: 'INFORMATION', idempotencyKey: 'fixed-key' })
    expect(mocks.post).toHaveBeenCalledWith('/launch/7/actions/COMPLETE_DATA',
      { step_code: 'INFORMATION', expected_revision: 3, payload: { note: 'x' } },
      { headers: { 'Idempotency-Key': 'fixed-key' } })
  })

  it('executeAction 未传幂等键时自动生成非空键', async () => {
    mocks.post.mockResolvedValue({ data: {} })
    await executeAction(7, 'COMPLETE_DATA', {}, { expectedRevision: 1 })
    const header = mocks.post.mock.calls[0][2].headers['Idempotency-Key']
    expect(typeof header).toBe('string')
    expect(header.length).toBeGreaterThan(0)
  })

  it('syncLaunch 发送 refresh 模式与 expected_revision', async () => {
    mocks.post.mockResolvedValue({ data: { refreshed: true } })
    await syncLaunch(9, 4)
    expect(mocks.post).toHaveBeenCalledWith('/launch/9/sync', { mode: 'refresh', expected_revision: 4 })
  })

  it('listLaunches 用服务端字段名 page_num 并透传筛选', async () => {
    mocks.get.mockResolvedValue({ data: { items: [], total: 0, page_num: 2, page_size: 20 } })
    await listLaunches({ page_num: 2, page_size: 20, mine: true })
    expect(mocks.get).toHaveBeenCalledWith('/launch', { params: { page_num: 2, page_size: 20, mine: true } })
  })

  it('loadContext 命中 /launch/context', async () => {
    mocks.get.mockResolvedValue({ data: { shops: [] } })
    expect(await loadContext()).toEqual({ shops: [] })
    expect(mocks.get).toHaveBeenCalledWith('/launch/context')
  })
})

describe('状态文案（AC-14.2）', () => {
  it('「等待平台」用中性文案，不是失败红', () => {
    expect(executionStatusMeta('WAITING_EXTERNAL')).toEqual({ text: '等待平台反馈', tag: 'info' })
    expect(executionStatusMeta('FAILED').tag).toBe('danger')
  })

  it('UNKNOWN 不显示为绿色完成', () => {
    expect(platformStatusMeta('UNKNOWN')).toEqual({ text: '未知', tag: 'info' })
    expect(platformStatusMeta('ACTIVE').tag).toBe('success')
  })

  it('未知枚举退化为 info 而非 success', () => {
    expect(statusMeta(PLATFORM_STATUS, 'WHAT').tag).toBe('info')
    expect(statusMeta(PLATFORM_STATUS, '').text).toBe('未知')
  })
})

describe('筛选与空态分因（AC-14.5）', () => {
  it('listQuery 仅发送非空筛选且用服务端字段名', () => {
    expect(listQuery({ platform: '', mine: false, shop_id: 5 }, { pageNum: 1, pageSize: 20 }))
      .toEqual({ page_num: 1, page_size: 20, shop_id: 5 })
    expect(listQuery({ mine: true, blocked_only: true }, { pageNum: 3, pageSize: 50 }))
      .toEqual({ page_num: 3, page_size: 50, mine: true, blocked_only: true })
  })

  it.each([
    ['REQUEST_FAILED', 'retry', { error: new Error('boom') }],
    ['NO_PERMISSION', 'none', { context: { shops: [], blocked_reason: { code: 'PERMISSION_DENIED' } } }],
    ['NO_SHOP', 'add_shop', { context: { shops: [], blocked_reason: { code: 'NO_USABLE_SHOP' } } }],
    ['NO_PROFILE', 'none', { context: { shops: [{ usable: false }] } }],
    ['NO_MATCH', 'clear_filters', { context: { shops: [{ usable: true }] }, filters: { mine: true } }],
    ['NO_PRODUCT', 'none', { context: { shops: [{ usable: true }] } }],
  ])('空态分因 %s → 动作 %s', (code, action, extra) => {
    const reason = emptyStateReason({ total: 0, ...extra })
    expect(reason.code).toBe(code)
    expect(reason.action).toBe(action)
    expect(reason.text).toBeTruthy()
  })
})

describe('return_to 站内白名单（AC-14.7）', () => {
  it('放行 /launch 与 /launch/:id，拒绝站外与相对路径', () => {
    expect(isSafeReturnTo('/launch')).toBe(true)
    expect(isSafeReturnTo('/launch/12?mine=true')).toBe(true)
    expect(isSafeReturnTo('//evil.com')).toBe(false)
    expect(isSafeReturnTo('https://evil.com')).toBe(false)
    expect(isSafeReturnTo('/launching')).toBe(false)
    expect(isSafeReturnTo('/orders')).toBe(false)
    expect(isSafeReturnTo('/launch/../secret')).toBe(false)
  })

  it('sanitizeReturnTo 非法回退默认', () => {
    expect(sanitizeReturnTo('//evil.com')).toBe('/launch')
    expect(sanitizeReturnTo('/launch/3')).toBe('/launch/3')
  })

  it('buildReturnTo ↔ parseReturnTo 往返一致', () => {
    const path = buildReturnTo({ product_id: 5, mine: true, platform: 'shopee', execution_status: '' })
    expect(path).toBe('/launch?product_id=5&mine=true&platform=shopee')
    expect(parseReturnTo(path)).toEqual({ product_id: 5, mine: true, platform: 'shopee' })
    expect(parseReturnTo('https://evil.com')).toBeNull()
  })

  it('detailPath 仅带白名单 return_to', () => {
    expect(detailPath(3, '/launch?mine=true')).toEqual({ path: '/launch/3', query: { return_to: '/launch?mine=true' } })
    expect(detailPath(3, '//evil.com')).toEqual({ path: '/launch/3', query: {} })
  })
})

describe('错误 envelope（409 保留用户输入）', () => {
  it('对象 detail 提取 code/message/blockers', () => {
    const env = errorEnvelope({
      response: { data: { detail: { code: 'ACTION_PRECONDITION_FAILED', message: '缺条件', blockers: [{ code: 'X' }] } } },
    })
    expect(env.code).toBe('ACTION_PRECONDITION_FAILED')
    expect(env.message).toBe('缺条件')
    expect(env.blockers).toHaveLength(1)
  })

  it('REVISION_CONFLICT 回填 current_revision，其它错误不回填', () => {
    const conflict = { response: { data: { detail: { code: 'REVISION_CONFLICT', message: '流程已更新', current_revision: 7 } } } }
    expect(revisionConflict(conflict)).toBe(7)
    expect(revisionConflict({ response: { data: { detail: { code: 'OTHER' } } } })).toBeNull()
  })

  it('字符串 detail 与缺失 detail 不崩', () => {
    expect(errorEnvelope({ response: { data: { detail: 'plain' } } }).message).toBe('plain')
    expect(errorEnvelope(undefined).code).toBe('REQUEST_FAILED')
  })
})

describe('展示纯函数', () => {
  it('progressText', () => {
    expect(progressText({ completed: 4, total: 9 })).toBe('4/9')
    expect(progressText()).toBe('0/0')
  })

  it('blockerText 折叠多余阻断', () => {
    expect(blockerText([{ message: 'A' }, { message: 'B' }])).toBe('A（+1）')
    expect(blockerText([])).toBe('—')
  })

  it('nextActionText 不可执行时带原因（引导刷新）', () => {
    expect(nextActionText({ action: 'SUBMIT_PLATFORM', step_code: 'SUBMISSION', executable: true }))
      .toBe('SUBMIT_PLATFORM · SUBMISSION')
    expect(nextActionText({ action: 'SUBMIT_PLATFORM', executable: false, reason: '缺少权限' }))
      .toBe('SUBMIT_PLATFORM（缺少权限）')
    expect(nextActionText({})).toBe('暂无待办动作')
  })

  it('ownerText 优先角色提示', () => {
    expect(ownerText({ actor: 'USER', role_hint: '运营' })).toBe('运营')
    expect(ownerText({})).toBe('—')
  })

  it('guidedSummary 数值与状态来自 DTO（AC-16.2）', () => {
    expect(guidedSummary({ progress: { completed: 4, total: 9 }, execution_status: 'WAITING_EXTERNAL' }))
      .toBe('你的商品已完成 4/9；等待平台反馈')
  })

  it('newIdempotencyKey 结构稳定且两次不同', () => {
    const a = newIdempotencyKey('launch-1-X')
    const b = newIdempotencyKey('launch-1-X')
    expect(a.startsWith('launch-1-X-')).toBe(true)
    expect(a).not.toBe(b)
  })
})
