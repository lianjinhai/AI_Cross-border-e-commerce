import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usePublishActionQueue } from '../src/composables/publishActionQueue'

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), prompt: vi.fn(), confirm: vi.fn(), success: vi.fn(), error: vi.fn() }))
vi.mock('../src/api', () => ({ default: { get: mocks.get, post: mocks.post } }))
vi.mock('../src/ui', () => ({ ElMessageBox: { prompt: mocks.prompt, confirm: mocks.confirm },
  ElMessage: { success: mocks.success, error: mocks.error } }))

beforeEach(() => {
  vi.resetAllMocks()
  mocks.get.mockResolvedValue({ data: { items: [] } })
})
describe('发布审批队列', () => {
  it('只加载发布 Action，不产生任何写请求', async () => {
    const queue = usePublishActionQueue()
    await queue.load()
    expect(mocks.get).toHaveBeenCalledWith('/actions', { params: { action_type: 'PUBLISH_LISTING', status: 'PENDING_APPROVAL' } })
    expect(mocks.get).toHaveBeenCalledWith('/actions', { params: { action_type: 'PUBLISH_LISTING', status: 'APPROVED' } })
    expect(mocks.post).not.toHaveBeenCalled()
    expect(queue.loading.value).toBe(false)
  })
  it('批准仅提交审批意见，不自动执行', async () => {
    mocks.prompt.mockResolvedValue({ value: '  已核对内容与店铺  ' })
    mocks.post.mockResolvedValue({ data: {} })
    const queue = usePublishActionQueue()
    await queue.decide({ id: 9, status: 'PENDING_APPROVAL' }, true)
    expect(mocks.post).toHaveBeenCalledTimes(1)
    expect(mocks.post).toHaveBeenCalledWith('/actions/9/approve', { note: '已核对内容与店铺' })
  })
  it('取消审批不产生写请求', async () => {
    mocks.prompt.mockRejectedValue('cancel')
    await usePublishActionQueue().decide({ id: 9, status: 'PENDING_APPROVAL' }, false)
    expect(mocks.post).not.toHaveBeenCalled()
  })
  it('未批准不能执行，失败不能显示发布成功', async () => {
    const done = vi.fn()
    const queue = usePublishActionQueue(done)
    await queue.execute({ id: 9, status: 'PENDING_APPROVAL' })
    expect(mocks.confirm).not.toHaveBeenCalled()
    expect(mocks.post).not.toHaveBeenCalled()
    mocks.confirm.mockResolvedValue('confirm')
    mocks.post.mockResolvedValue({ data: { status: 'FAILED', outcome: { error: '审批期间内容变化' } } })
    await queue.execute({ id: 9, target_id: 8, status: 'APPROVED' })
    expect(mocks.post).toHaveBeenCalledWith('/actions/9/execute')
    expect(mocks.error).toHaveBeenCalledWith('审批期间内容变化')
    expect(mocks.success).not.toHaveBeenCalled()
    expect(done).not.toHaveBeenCalled()
    expect(queue.busy.value).toBe(false)
  })
  it('成功执行后才通知页面刷新', async () => {
    mocks.confirm.mockResolvedValue('confirm')
    mocks.post.mockResolvedValue({ data: { status: 'SUCCESS' } })
    const done = vi.fn()
    await usePublishActionQueue(done).execute({ id: 9, target_id: 8, status: 'APPROVED' })
    expect(done).toHaveBeenCalledTimes(1)
    expect(mocks.success).toHaveBeenCalledTimes(1)
  })
})
