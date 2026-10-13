/**
 * 控制台 Adapter 认证中心纯函数（蓝图 R1 包 3 · PC-03，§B.3 / §F#8）。
 *
 * 蓝图 §5.19：Adapter 认证中心将能力拆到**子能力**（授权/商品发布/在售核验/订单/退款），
 * 每项显示协议实现与真实联调状态、证据时间、账号范围。
 *
 * Platform Adapter Registry 读端点**未核**（§F#8）→ 所有子能力的验证等级一律显
 * "尚未验证"（不用绿色/红色误报），证据时间必显。本模块集中定义子能力目录与
 * 验证等级判定，组件（Adapters.vue）只消费。
 */

/** 子能力目录（蓝图 §5.19：授权/商品发布/在售核验/订单/退款）。 */
export const ADAPTER_SUBCAPABILITIES = [
  { code: 'auth', label: '授权' },
  { code: 'publish', label: '商品发布' },
  { code: 'listing_check', label: '在售核验' },
  { code: 'orders', label: '订单' },
  { code: 'refunds', label: '退款' },
]

/** 平台目录（静态，Registry 未核前以协议目录呈现；不冒充真实认证）。 */
export const ADAPTER_PLATFORMS = [
  { code: 'shopee', label: 'Shopee', markets: ['东南亚', '台湾'] },
  { code: 'tiktok', label: 'TikTok Shop', markets: ['东南亚', '美国'] },
  { code: 'amazon', label: 'Amazon', markets: ['北美', '欧洲'] },
  { code: 'temu', label: 'Temu', markets: ['全球'], restricted: true },
]

/** 验证等级（缺 Registry 端点 → 统一 UNVERIFIED，禁绿/红误报）。 */
export const VERIFY_LEVELS = {
  UNVERIFIED: { code: 'UNVERIFIED', label: '尚未验证', tone: 'neutral' },
  PROTOCOL_PENDING: { code: 'PROTOCOL_PENDING', label: '协议未验收', tone: 'warning' },
  VERIFIED: { code: 'VERIFIED', label: '真实已认证', tone: 'success' },
}

/**
 * 单项子能力验证等级判定。
 *
 * 红线（§F#8）：Registry 读端点未核 → 无论传入什么，缺 protocolImplemented 即 UNVERIFIED；
 * 只有明确给出 verified=true 才能显"真实已认证"。evidenceAt 缺省时显"证据时间未知"。
 *
 * @param {object} cap
 * @param {boolean} [cap.registryAvailable] Registry 读端点是否已核（当前恒为 false）。
 * @param {boolean} [cap.protocolImplemented] 协议层是否实现。
 * @param {boolean} [cap.verified] 是否真实联调验证。
 * @param {string} [cap.evidenceAt] 证据时间（ISO）。
 * @param {string} [cap.accountScope] 账号范围（如"全部"/"指定账号"）。
 * @returns {{code:string, label:string, tone:string, evidenceAt:string, accountScope:string}}
 */
export function adapterSubcapLevel(cap = {}) {
  const { registryAvailable = false, protocolImplemented = false, verified = false, evidenceAt = '', accountScope = '未知' } = cap
  // Registry 未核：只能显"尚未验证"，不用绿/红误报。
  if (!registryAvailable) {
    return { ...VERIFY_LEVELS.UNVERIFIED, evidenceAt: evidenceAt || '证据时间未知', accountScope }
  }
  if (verified) {
    return { ...VERIFY_LEVELS.VERIFIED, evidenceAt: evidenceAt || '证据时间未知', accountScope }
  }
  if (protocolImplemented) {
    return { ...VERIFY_LEVELS.PROTOCOL_PENDING, evidenceAt: evidenceAt || '证据时间未知', accountScope }
  }
  return { ...VERIFY_LEVELS.UNVERIFIED, evidenceAt: evidenceAt || '证据时间未知', accountScope }
}

/**
 * 平台卡渲染数据：静态目录 + 全部子能力降级为 UNVERIFIED（Registry 未核）。
 * @returns {Array<{code,label,markets,restricted, subcaps:object[]}>}
 */
export function adapterPlatformCards() {
  return ADAPTER_PLATFORMS.map((p) => ({
    ...p,
    subcaps: ADAPTER_SUBCAPABILITIES.map((c) => ({
      ...c,
      level: adapterSubcapLevel({ registryAvailable: false }),
    })),
  }))
}

/** Registry 待接入标记文案（§F#8 用户可见文案）。 */
export function adapterPendingCopy() {
  return {
    title: 'Adapter Registry 待接入',
    detail: '渠道 Adapter 认证中心读端点尚未核；以下各子能力验证等级一律为"尚未验证"，不作为真实认证结论。',
  }
}
