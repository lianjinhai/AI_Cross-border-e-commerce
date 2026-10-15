/**
 * 商品详情（E01/E02/E05/E06）View Model：渠道与素材分区只消费稳定字段。
 *
 * 契约来源（现场核对后端源码，非文档臆测）：
 * - 渠道：backend/app/workflows/launch_dto.py channels_dto →
 *   {product, total, channels:[{shop:{id,name,platform,market},
 *   active_launch: launch_list_item|null, history:[launch_list_item]}]}；
 *   launch_list_item 含 execution_status/platform_status/progress/next_action/
 *   blocked_summary/revision/created_at/id。
 * - 素材：backend/app/routers/product_assets.py + models.ProductAsset：
 *   asset_key/asset_type/uri/content_hash/rights_status/source/
 *   verification_status/version/market/platform（列表为 {items,total,page,page_size}）。
 *
 * 原则（契约 R3 §5）：组件不猜 items/data；错误不当空；UNKNOWN/RESTRICTED 权利
 * 不渲染为可发布；素材存在 ≠ 拥有发布权（rights_status 与 verification_status 分离）。
 */

/** 素材类型码 → 中文标签（asset_schema.py Literal 域，未知名值原样回显）。 */
const ASSET_TYPE_LABELS = {
  ORIGINAL_IMAGE: '原图',
  MAIN_IMAGE: '主图',
  DETAIL_IMAGE: '详情图',
  SIZE_IMAGE: '尺码图',
  PHYSICAL_PHOTO: '实物照',
  RIGHTS_EVIDENCE: '权利证据',
  VIDEO: '视频',
  LABEL: '标签',
  BARCODE: '条码',
  COMPLIANCE_ATTACHMENT: '合规附件',
}

/** 权利状态 → 标签（UNKNOWN/RESTRICTED 视为不拥有发布权）。 */
const RIGHTS_LABELS = {
  OWNED: '自有权利',
  SUPPLIER_AUTHORIZED: '供应商授权',
  LICENSED: '已许可',
  UNKNOWN: '权利未知',
  RESTRICTED: '权利受限',
}

/** 核验状态 → 标签（VERIFIED/REJECTED/MANUAL_REPORTED/UNVERIFIED 之外原样回显）。 */
const VERIFICATION_LABELS = {
  VERIFIED: '已核验',
  REJECTED: '已驳回',
  MANUAL_REPORTED: '人工申报（未核验）',
  UNVERIFIED: '未核验',
}

/** 执行状态 → 标签（与 launchCenter EXECUTION_STATUS 语义对齐，独立兜底映射）。 */
const EXECUTION_LABELS = {
  DRAFT: '草稿',
  RUNNING: '进行中',
  WAITING_PLATFORM: '等待平台',
  BLOCKED: '受阻',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
}

/**
 * 把渠道聚合响应规整为按店铺分组的数据（E01：读 channels，不读 items）。
 * 同一商品多店各自独立状态，按 shop.id 升序固定展示顺序。
 * @param {object} [response] 后端 channels_dto 原始响应。
 * @returns {{ product: object|null, total: number, channels: Array<object> }}
 */
export function normalizeChannels(response = {}) {
  const channels = Array.isArray(response?.channels)
    ? response.channels
    : (Array.isArray(response?.items) ? response.items : [])
  return {
    product: response?.product || null,
    total: Number.isFinite(response?.total) ? response.total : channels.length,
    channels: channels
      .filter((c) => c && c.shop)
      .map((c) => ({
        shop: c.shop,
        active: c.active_launch || null,
        history: Array.isArray(c.history) ? c.history : [],
      }))
      .sort((a, b) => (a.shop.id || 0) - (b.shop.id || 0)),
  }
}

/** 单条 launch item 的稳定视图（launch_list_item 字段白名单，缺省给 — 值）。 */
export function launchItemView(item = {}) {
  return {
    id: item.id ?? null,
    executionStatus: item.execution_status || 'UNKNOWN',
    executionLabel: EXECUTION_LABELS[item.execution_status] || item.execution_status || '未知',
    platformStatus: item.platform_status || 'UNKNOWN',
    progress: progressLabel(item.progress),
    nextAction: nextActionLabel(item.next_action),
    blocked: (item.blocked_summary || []).length > 0,
    revision: item.revision ?? null,
    createdAt: item.created_at || '—',
    isHistory: Boolean(item.is_history),
  }
}

/** progress {completed,total} → "3/8 步"；缺失时「尚未获得」。 */
export function progressLabel(progress = {}) {
  if (!progress || !Number.isFinite(progress.completed)) return '尚未获得'
  return `${progress.completed}/${progress.total ?? '未知'} 步`
}

/** next_action {action,step_code,executable,reason} → 可读文案。 */
export function nextActionLabel(next = {}) {
  if (!next || !next.action) return '—'
  const action = String(next.action)
  if (next.executable === false) {
    return next.reason ? `${action}（不可执行：${next.reason}）` : `${action}（暂不可执行）`
  }
  return action
}

/**
 * 素材行 View Model（E05）：只消费 ProductAsset 真实列，权利与核验分离。
 * @param {object} asset 后端 to_dict(ProductAsset) 行。
 */
export function assetRowView(asset = {}) {
  const rights = asset.rights_status || 'UNKNOWN'
  const verification = asset.verification_status || 'MANUAL_REPORTED'
  return {
    id: asset.id ?? null,
    assetKey: asset.asset_key || '—',
    version: asset.version ?? 1,
    typeLabel: ASSET_TYPE_LABELS[asset.asset_type] || asset.asset_type || '—',
    uri: asset.uri || '',
    rightsLabel: RIGHTS_LABELS[rights] || rights,
    rightsStatus: rights,
    // 发布权判定：只认 OWNED/SUPPLIER_AUTHORIZED/LICENSED；UNKNOWN/RESTRICTED 一律「不可发布」
    publishable: ['OWNED', 'SUPPLIER_AUTHORIZED', 'LICENSED'].includes(rights) && verification === 'VERIFIED',
    verificationLabel: VERIFICATION_LABELS[verification] || verification,
    verificationStatus: verification,
    market: asset.market || '—',
    platform: asset.platform || '—',
    source: asset.source || '—',
    validUntil: asset.valid_until || null,
  }
}

/**
 * 素材分页响应 → 稳定数组（后端 page() → {items,total,page,page_size}）。
 * 缺 items 时返回空数组（数据空≠加载失败，调用方须区分 error 态单独处理）。
 */
export function assetPageItems(response = {}) {
  return Array.isArray(response?.items) ? response.items : []
}

/** 店铺选项（渠道 shop 列表优先，否则 shops API items）→ {id,label}。 */
export function buildShopOptions(channelsShops = [], extraShops = []) {
  const seen = new Set()
  const options = []
  for (const raw of [...channelsShops, ...extraShops]) {
    const id = raw?.id
    if (id == null || seen.has(id)) continue
    seen.add(id)
    const market = raw.market ? `（${raw.market}）` : ''
    options.push({ id, label: `${raw.name || raw.shop_name || `店铺#${id}`}${raw.platform ? ' · ' + raw.platform : ''}${market}` })
  }
  return options
}

/**
 * 由目标 shop_id 反查其 market/platform（E03 登记必填字段来源）。
 * 渠道 shop 优先，其次 shops API；均未命中返回 null（禁止猜测，前端不得代填）。
 * @returns {{market:string,platform:string}|null}
 */
export function shopContext(channelsShops = [], extraShops = [], shopId) {
  for (const raw of [...channelsShops, ...extraShops]) {
    if (raw?.id === shopId && (raw.market || raw.platform)) {
      return { market: raw.market || '', platform: raw.platform || '' }
    }
  }
  return null
}

/** 错误体归一：后端 detail 对象 {code,message} / axios error → 可读原因（E06 用）。 */
export function sectionErrorText(error, fallback) {
  const detail = error?.response?.data?.detail
  if (detail && typeof detail === 'object') {
    return detail.message || detail.code || fallback
  }
  return error?.message || fallback
}

/**
 * E04 核验错误分类：区分 无权限(403 ASSET_PERMISSION_DENIED/需合规审批)、自审限制(403 ASSET_SELF_REVIEW)、
 * 版本冲突(409 ASSET_VERSION_CONFLICT，须保留输入提示刷新)、其余(如 404/422)。
 * @returns {{kind:'no_permission'|'self_review'|'version_conflict'|'other', message:string}}
 */
export function verifyErrorKind(error, fallback = '核验提交失败') {
  const status = error?.response?.status
  const detail = error?.response?.data?.detail
  const code = typeof detail === 'object' ? detail.code : ''
  // 先判具体 403 子码（自审限制），再落到泛化无权限
  if (code === 'ASSET_SELF_REVIEW') {
    return { kind: 'self_review', message: '提交人不能核验自己的权利证据（自审限制）：需由他人复核' }
  }
  if (status === 403 || code === 'ASSET_PERMISSION_DENIED') {
    return { kind: 'no_permission', message: '缺少合规审批权（compliance:approve）：无权限时核验入口应不可用，请向拥有审批权的成员申请' }
  }
  if (status === 409 || code === 'ASSET_VERSION_CONFLICT') {
    return { kind: 'version_conflict', message: '素材版本已变化（仅可核验当前版本）：请刷新素材列表后重新确认，已填内容已保留' }
  }
  return { kind: 'other', message: sectionErrorText(error, fallback) }
}

/**
 * J1 深链：从商品详情跳到「上线中心」创建向导，携带商品/目标店铺上下文，避免重新搜索。
 * 仅组装 path + query，不触碰路由实例（组件负责 push）；字段只带后端 LaunchCreateIn
 * 认的 product_id / shop_id，外加 `from` 作为回跳来源（白名单由调用方 isSafeReturnTo 校验）。
 * @returns {{path:string, query:object}}
 */
export function buildLaunchDeepLink(productId, { shopId = null, from = '' } = {}) {
  const query = {}
  if (productId != null && productId !== '') query.product_id = String(productId)
  if (shopId != null && shopId !== '') query.shop_id = String(shopId)
  if (from) query.from = String(from)
  return { path: '/app/launch', query }
}

/**
 * J1 向导起点：已携带 product_id 时跳过「选商品」步，直接进「选店铺/确认」，上下文不丢。
 * @returns {0|1} 0=从未带商品（正常从上线中心进入）；1=已带商品（从商品详情深链进入）。
 */
export function launchWizardStartStep(productId) {
  return (productId != null && productId !== '') ? 1 : 0
}
