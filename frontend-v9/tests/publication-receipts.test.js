import { beforeEach, expect, it, vi } from 'vitest'
import { queryPublicationReceipt } from '../src/composables/publicationReceipts'

const mocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../src/shared/api/client', () => ({ default: { get: mocks.get } }))
beforeEach(() => vi.resetAllMocks())

it('只查询所选回执所属店铺，不按平台猜第一家店', async () => {
  mocks.get.mockResolvedValue({ data: { status: 'processing' } })
  expect(await queryPublicationReceipt({ shop_id: 102, external_id: 'feed/B', can_query_submission: true }))
    .toEqual({ status: 'processing' })
  expect(mocks.get).toHaveBeenCalledTimes(1)
  expect(mocks.get).toHaveBeenCalledWith('/shops/102/submissions/feed%2FB')
})

it('缺店铺或未开放查询时不发送请求', async () => {
  await expect(queryPublicationReceipt({ external_id: 'feed', can_query_submission: true })).rejects.toThrow()
  await expect(queryPublicationReceipt({ shop_id: 1, external_id: 'feed', can_query_submission: false })).rejects.toThrow()
  expect(mocks.get).not.toHaveBeenCalled()
})
