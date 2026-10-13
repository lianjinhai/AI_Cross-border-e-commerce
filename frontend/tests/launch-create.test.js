import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * UX-03：创建上线流程数据层回归。
 * `launchCenter.js` 用 `api` 发送请求，这里 mock 掉 `../src/api`。
 */
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../src/api', () => ({ default: { get: mocks.get, post: mocks.post } }))

const { createLaunch, errorEnvelope } = await import('../src/composables/launchCenter')

beforeEach(() => vi.resetAllMocks())

describe('createLaunch', () => {
  it('POST /launch 携带 snake_case body 与 Idempotency-Key 头，返回后端 run', async () => {
    mocks.post.mockResolvedValueOnce({ data: { id: 77, product: { title: 'A' } } })

    const run = await createLaunch({ productId: 12, shopId: 3 })

    expect(mocks.post).toHaveBeenCalledTimes(1)
    const [url, body, config] = mocks.post.mock.calls[0]
    expect(url).toBe('/launch')
    expect(body).toEqual({ product_id: 12, shop_id: 3 })
    expect(String(config.headers['Idempotency-Key'])).toMatch(/^launch-/)
    expect(run).toEqual({ id: 77, product: { title: 'A' } })
  })

  it('请求失败时抛出原始 error，绝不伪造成功', async () => {
    const err = new Error('conflict')
    err.response = { status: 409, data: { detail: { code: 'CONFLICT', message: '存在未完成的上线流程' } } }
    mocks.post.mockRejectedValueOnce(err)

    await expect(createLaunch({ productId: 1, shopId: 2 })).rejects.toBe(err)
    // 错误仍可被调用方用 errorEnvelope 归一后如实提示
    expect(errorEnvelope(err).message).toBe('存在未完成的上线流程')
  })

  it('每次调用生成不同的 Idempotency-Key', async () => {
    mocks.post.mockResolvedValue({ data: { id: 1 } })
    await createLaunch({ productId: 1, shopId: 1 })
    await createLaunch({ productId: 1, shopId: 1 })

    const keys = mocks.post.mock.calls.map((call) => call[2].headers['Idempotency-Key'])
    expect(keys[0]).not.toBe(keys[1])
  })
})
