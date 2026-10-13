import { describe, expect, it } from 'vitest'
import {
  ADAPTER_SUBCAPABILITIES,
  ADAPTER_PLATFORMS,
  VERIFY_LEVELS,
  adapterSubcapLevel,
  adapterPlatformCards,
  adapterPendingCopy,
} from '../src/shared/consoleAdapters'

/**
 * 控制台 Adapter 认证中心纯函数回归（蓝图 R1 包 3 · PC-03，§B.3 / §F#8）。
 *
 * 红线（§F#8）：Registry 读端点未核 → 各子能力验证等级一律"尚未验证"
 * （不用绿色/红色误报），证据时间必显。
 */
describe('adapterSubcapLevel — 验证等级判定', () => {
  it('Registry 未核（默认）→ 恒 UNVERIFIED"尚未验证"，不用绿/红误报', () => {
    const level = adapterSubcapLevel({ registryAvailable: false })
    expect(level.code).toBe(VERIFY_LEVELS.UNVERIFIED.code)
    expect(level.label).toBe('尚未验证')
    expect(level.tone).toBe('neutral')
    expect(level.evidenceAt).toBe('证据时间未知')
  })

  it('Registry 未核时即使 verified=true 也不得显"真实已认证"（红线：未核即未验证）', () => {
    const level = adapterSubcapLevel({ registryAvailable: false, verified: true, protocolImplemented: true })
    expect(level.code).toBe('UNVERIFIED')
    expect(level.label).toBe('尚未验证')
  })

  it('Registry 已核 + verified → VERIFIED"真实已认证"（success 色）', () => {
    const level = adapterSubcapLevel({ registryAvailable: true, verified: true, evidenceAt: '2025-01-02' })
    expect(level.code).toBe('VERIFIED')
    expect(level.label).toBe('真实已认证')
    expect(level.tone).toBe('success')
    expect(level.evidenceAt).toBe('2025-01-02')
  })

  it('Registry 已核 + 仅协议实现未联调 → PROTOCOL_PENDING"协议未验收"（warning）', () => {
    const level = adapterSubcapLevel({ registryAvailable: true, protocolImplemented: true })
    expect(level.code).toBe('PROTOCOL_PENDING')
    expect(level.label).toBe('协议未验收')
    expect(level.tone).toBe('warning')
  })

  it('Registry 已核 + 无任何实现 → UNVERIFIED', () => {
    expect(adapterSubcapLevel({ registryAvailable: true }).code).toBe('UNVERIFIED')
  })

  it('账号范围缺省 → "未知"，缺 evidenceAt → "证据时间未知"', () => {
    const level = adapterSubcapLevel({ registryAvailable: false })
    expect(level.accountScope).toBe('未知')
    expect(level.evidenceAt).toBe('证据时间未知')
  })
})

describe('adapterPlatformCards — 平台卡渲染数据', () => {
  it('静态平台目录（含受限渠道 Temu 标记）', () => {
    const cards = adapterPlatformCards()
    expect(cards).toHaveLength(ADAPTER_PLATFORMS.length)
    const temu = cards.find((c) => c.code === 'temu')
    expect(temu.restricted).toBe(true)
  })

  it('每平台含 5 个子能力，且 Registry 未核时全部 UNVERIFIED（不冒充认证）', () => {
    const cards = adapterPlatformCards()
    expect(ADAPTER_SUBCAPABILITIES.map((c) => c.code)).toEqual(
      ['auth', 'publish', 'listing_check', 'orders', 'refunds'],
    )
    for (const card of cards) {
      expect(card.subcaps).toHaveLength(5)
      for (const sub of card.subcaps) {
        expect(sub.level.code).toBe('UNVERIFIED')
        expect(sub.level.label).toBe('尚未验证')
      }
    }
  })
})

describe('adapterPendingCopy — 待接入文案', () => {
  it('集中产出"Registry 待接入"提示（不页面自写）', () => {
    const copy = adapterPendingCopy()
    expect(copy.title).toBe('Adapter Registry 待接入')
    expect(copy.detail).toContain('尚未验证')
  })
})
