/**
 * 平台能力静态目录（CH-01 / PC-03 共用标记层，差距分析 §7#8）。
 *
 * Platform Adapter Registry 读端点**未核** → 本模块为静态目录 + 能力字段
 * 一律标"协议未验收"，仅 shops 端点证实的授权状态可显示。
 * 红线：禁止"已连接官方实时数据"误导；未接入标"协议未验收"。
 */

/**
 * 静态平台目录。每项字段：
 * - platform / label：平台标识与名称；
 * - markets：目标市场（文案数组）；
 * - capabilities：真实能力位（授权/发布/订单/售后/广告），每项 { code, label, verified }，
 *   verified=false 一律"协议未验证"（Adapter Registry 未核 §7#8）；
 * - level：验证等级码：AUTHENTICATED（真实已认证）/ UNVERIFIED（协议未验证）/
 *   PLANNED（计划中）/ RESTRICTED（受限）；
 * - prerequisites：接入前提（文案数组，受限渠道明示材料要求）。
 */
export const PLATFORM_CATALOG = [
  {
    platform: 'shopee',
    label: 'Shopee',
    markets: ['东南亚', '拉美'],
    level: 'UNVERIFIED',
    capabilities: [
      { code: 'auth', label: 'OAuth 授权', verified: true },
      { code: 'publish', label: '商品发布', verified: false },
      { code: 'orders', label: '订单同步', verified: false },
      { code: 'aftersale', label: '售后退款', verified: false },
      { code: 'ads', label: '广告投放', verified: false },
    ],
    prerequisites: ['完成 OAuth 授权', '店铺类目映射配置'],
  },
  {
    platform: 'tiktok',
    label: 'TikTok Shop',
    markets: ['东南亚', '美国'],
    level: 'UNVERIFIED',
    capabilities: [
      { code: 'auth', label: 'OAuth 授权', verified: true },
      { code: 'publish', label: '商品发布', verified: false },
      { code: 'orders', label: '订单同步', verified: false },
      { code: 'aftersale', label: '售后退款', verified: false },
      { code: 'ads', label: '广告投放', verified: false },
    ],
    prerequisites: ['完成 OAuth 授权', '上架条件预检（listing_readiness）'],
  },
  {
    platform: 'lazada',
    label: 'Lazada',
    markets: ['东南亚'],
    level: 'UNVERIFIED',
    capabilities: [
      { code: 'auth', label: 'OAuth 授权', verified: true },
      { code: 'publish', label: '商品发布', verified: false },
      { code: 'orders', label: '订单同步', verified: false },
      { code: 'aftersale', label: '售后退款', verified: false },
      { code: 'ads', label: '广告投放', verified: false },
    ],
    prerequisites: ['完成 OAuth 授权'],
  },
  {
    platform: 'temu',
    label: 'Temu',
    markets: ['美国', '欧洲'],
    level: 'RESTRICTED',
    capabilities: [
      { code: 'auth', label: 'OAuth 授权', verified: false },
      { code: 'publish', label: '商品发布（半托管）', verified: false },
      { code: 'orders', label: '订单同步', verified: false },
      { code: 'aftersale', label: '售后退款', verified: false },
      { code: 'ads', label: '广告投放', verified: false },
    ],
    prerequisites: ['平台邀约制：需 Temu 定向邀约与入驻材料', '半托管备货合规材料', '受限渠道：先查看接入前提与材料，不出现"连接"按钮'],
  },
  {
    platform: 'amazon',
    label: 'Amazon',
    markets: ['美国', '欧洲', '日本'],
    level: 'PLANNED',
    capabilities: [
      { code: 'auth', label: 'SP-API 授权', verified: false },
      { code: 'publish', label: '商品发布', verified: false },
      { code: 'orders', label: '订单同步', verified: false },
      { code: 'aftersale', label: '售后退款', verified: false },
      { code: 'ads', label: '广告投放', verified: false },
    ],
    prerequisites: ['Amazon 开发者账号（SP-API 审核）', '计划中：协议未验收，接入排期未定'],
  },
]

/** 验证等级码 → 展示文案（协议未验证/计划中/受限/真实已认证）。 */
export const PLATFORM_LEVEL_LABEL = {
  AUTHENTICATED: '真实已认证',
  UNVERIFIED: '协议未验证',
  PLANNED: '计划中',
  RESTRICTED: '受限',
}

/**
 * 取某平台卡片渲染数据（纯函数，便于测试）。
 * 缺失 platform 返回空卡（不伪造）。
 *
 * @param {string} platform 平台码。
 * @returns {{platform:string, label:string, markets:string[], level:string, levelLabel:string, capabilities:Array, prerequisites:string[], restricted:boolean}|null}
 */
export function platformCard(platform) {
  const item = PLATFORM_CATALOG.find((p) => p.platform === platform)
  if (!item) return null
  return {
    ...item,
    levelLabel: PLATFORM_LEVEL_LABEL[item.level] || '协议未验证',
    restricted: item.level === 'RESTRICTED',
  }
}

/**
 * 全目录卡片（未接入 → 全部"协议未验收"语义由 levelLabel 承载）。
 * @returns {Array}
 */
export function allPlatformCards() {
  return PLATFORM_CATALOG
    .map((p) => platformCard(p.platform))
    .filter(Boolean)
}
