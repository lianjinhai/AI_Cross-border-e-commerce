/**
 * B3（V9.1 原型 04/06）概览 / 货源 / 表现 纯函数：概览聚合、报价行、表现视图、阶段色调。
 * 全部防御式——任何缺失键都回落为「待补」，页面永不因 overview 接口缺失/缺字段而崩溃。
 * 报价行复用 matchingView 的 normalizeOffer / sourceVerificationTags，避免重复契约映射。
 */
import { renderMoney, isMissing } from './money'
import { normalizeOffer, sourceVerificationTags } from './matchingView'

/**
 * 阶段 key → 设计令牌色调（原型 04/06）。
 * NO_SUPPLY / CHANNEL_PENDING → amber（准备缺口/风险，待补 accent）；
 * SUPPLY_READY / LAUNCHING → blue（tint）；OPERATING → success（正向）。
 * 未知 key 回 neutral，绝不臆造"完成"态。
 * @param {string} [key]
 * @returns {'amber'|'blue'|'success'|'neutral'}
 */
export function stageTone(key) {
  const map = {
    NO_SUPPLY: 'amber',
    CHANNEL_PENDING: 'amber',
    SUPPLY_READY: 'blue',
    LAUNCHING: 'blue',
    OPERATING: 'success',
  }
  return map[key] || 'neutral'
}

/**
 * 概览响应 → 稳定视图（B3；防御式映射 product_overview 顶层键）。
 * 后端顶层：product / supply / channels / performance / stage / generated_at。
 * 任何缺失键都回落为「待补」/ null，页面消费时无需再判空。
 * @param {object} [overview]
 * @returns {object} 概览视图
 */
export function overviewViewModel(overview = {}) {
  const o = overview || {}
  const supply = o.supply || {}
  const stage = o.stage || {}
  const costMissing = Array.isArray(supply.cost_missing) ? supply.cost_missing.slice() : []
  return {
    product: o.product || null,
    supply: {
      offersCount: supply.offers_count ?? null,
      selectedOfferId: supply.selected_offer_id ?? null,
      selectedOfferPriceCny: supply.selected_offer_price_cny ?? null,
      minOfferPriceCny: supply.min_offer_price_cny ?? null,
      costMissing,
      costComplete: Boolean(supply.cost_complete),
      costGapChips: costMissing,
      // 选定报价诚实信号：selected_offer_id 悬空（行不存在/跨租户）时为 true，
      // 成本已回退最低在库价（costOfferId）——页面必须显式标注回退，不得显示「用户选定」。
      selectedOfferMissing: Boolean(supply.selected_offer_missing),
      costOfferId: supply.cost_offer_id ?? null,
      // 三档状态（后端 costing.offer_state 唯一权威）：EXPIRED / OUT_OF_STOCK /
      // UNVERIFIED 保留偏好但阻断对外承诺；limits 为可直接展示的中文原因。
      selectedOfferState: supply.selected_offer_state ?? null,
      selectedOfferLimits: Array.isArray(supply.selected_offer_limits)
        ? supply.selected_offer_limits : [],
    },
    channels: o.channels || null,
    stage: {
      key: stage.key || null,
      label: stage.label || '待补',
      reasons: Array.isArray(stage.reasons) ? stage.reasons.slice() : [],
      tone: stageTone(stage.key),
    },
    performance: o.performance != null ? o.performance : null,
    generatedAt: o.generated_at || null,
  }
}

/**
 * 供应商核验状态中文（诚实边界：verified 仅平台核验，非工商尽调，必须显式标注）。
 * @param {string} [status]
 * @returns {{label:string, honestNote:string}}
 */
export function supplierVerificationLabel(status = '') {
  const s = String(status || '').toLowerCase()
  const LABELS = { verified: '已核验', candidate: '候选', contacting: '接洽中', unverified: '未核验' }
  const label = LABELS[s] || (s ? s : '未核验')
  const honestNote = s === 'verified' ? '平台核验，非工商尽调' : ''
  return { label, honestNote }
}

/**
 * 货源报价行视图（B3 原型 04；复用 matchingView 的归一化与来源/核验标签）。
 * 金额诚实：有币种走 renderMoney；无币种→裸数字+"币种未知"标注，绝不默认 $。
 * valid_until 缺失→"未填写"；供应商认证/能力折叠为 chips；当前选中行高亮标记。
 * @param {Array} [items] 后端 offers 列表（normalizeOffer 兼容新契约嵌套 supplier 与旧扁平）。
 * @param {number|null} [selectedOfferId] 当前选中报价 id（与 overview.supply.selected_offer_id 同源）。
 * @returns {Array<object>}
 */
export function offersViewModel(items = [], selectedOfferId = null) {
  const list = Array.isArray(items) ? items : []
  const selId = selectedOfferId ?? null
  return list.map((offer) => {
    const o = normalizeOffer(offer)
    const tags = sourceVerificationTags(o.source_kind, o.verification_status)
    let priceText = '—'
    let priceNote = ''
    if (!isMissing(o.price)) {
      if (o.currency) {
        priceText = renderMoney({ value: o.price, currency: o.currency })
      } else {
        const num = Number(o.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        priceText = num
        priceNote = '币种未知' // 后端未带币种，绝不当真币值、不默认 $
      }
    }
    const validityText = o.valid_until ? String(o.valid_until) : '未填写'
    const sup = o.supplier || {}
    const supVer = supplierVerificationLabel(sup.verification_status)
    return {
      id: o.id,
      priceText,
      priceNote,
      moq: o.moq ?? '—',
      shipDays: o.ship_days ?? '—',
      inStock: o.in_stock ?? '—',
      validityText,
      sourceLabel: tags.source.label,
      sourceTone: tags.source.tone,
      verificationLabel: tags.verification.label,
      verificationTone: tags.verification.tone,
      isSelected: o.id != null && selId != null && o.id === selId,
      supplier: {
        id: sup.id ?? null,
        name: sup.name || '未具名',
        region: sup.region || '—',
        supplierType: sup.supplier_type || '—',
        rating: sup.rating ?? null,
        verificationLabel: supVer.label,
        verificationHonestNote: supVer.honestNote,
        chips: [
          ...(Array.isArray(sup.certifications) ? sup.certifications : []).map((c) => ({ label: String(c), kind: 'cert' })),
          ...(Array.isArray(sup.capabilities) ? sup.capabilities : []).map((c) => ({ label: String(c), kind: 'cap' })),
        ],
      },
    }
  })
}

/**
 * 经营表现视图（B3 原型 06；诚实边界：null → 未取得可靠数据）。
 * 有值才渲染；金额字段（revenue/profit）无币种→裸数字+"币种未知"；
 * 比率字段(0-1)→百分比；均不臆造 0（缺失即「—」）。
 * @param {object|null} [performance] 后端 read_performance 结果或 null。
 * @returns {{available:boolean, hasData:boolean, windowDays:*, metrics:Array}}
 */
export function performanceViewModel(performance = null) {
  if (!performance || typeof performance !== 'object') {
    return { available: false, hasData: false, windowDays: null, metrics: [] }
  }
  const hasData = performance.has_data !== false
  const defs = [
    { key: 'units_sold', label: '销量', kind: 'count' },
    { key: 'revenue', label: '营收', kind: 'money' },
    { key: 'profit', label: '利润', kind: 'money' },
    { key: 'margin', label: '毛利率', kind: 'percent' },
    { key: 'refund_rate', label: '退款率', kind: 'percent' },
    { key: 'sell_through', label: '动销率', kind: 'percent' },
    { key: 'performance_score', label: '表现分', kind: 'score' },
  ]
  const metrics = defs.map((d) => {
    const v = performance[d.key]
    const missing = v == null
    let text = '—'
    let note = ''
    if (!missing) {
      if (d.kind === 'money') {
        text = Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        note = '币种未知' // 表现 DTO 不带币种，绝不当真币值
      } else if (d.kind === 'percent') {
        text = `${(Number(v) * 100).toFixed(1)}%`
      } else if (d.kind === 'score') {
        text = Number(v).toFixed(1)
      } else {
        text = String(v)
      }
    }
    return { key: d.key, label: d.label, kind: d.kind, value: v ?? null, text, note, missing }
  })
  return { available: true, hasData, windowDays: performance.window_days ?? null, metrics }
}

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
 * 深链 id 归一：只接受正整数或纯数字字符串。
 *
 * 真实浏览器验证发现的根因守卫：`@click="goCreateLaunch"`（漏括号）会把 PointerEvent
 * 传成 shopId，旧实现 `String(shopId)` 直接产出 `shop_id=[object PointerEvent]`，
 * 上线中心 `Number()` 得 NaN → 向导店铺为空、创建按钮永久禁用。事件对象必须在这里被丢掉。
 */
function toPositiveInt(value) {
  if (typeof value === 'number') return Number.isInteger(value) && value > 0 ? value : null
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) {
    const n = Number(value.trim())
    return n > 0 ? n : null
  }
  return null
}

/**
 * J1 深链：从商品详情跳到「上线中心」创建向导，携带商品/目标店铺上下文，避免重新搜索。
 * 仅组装 path + query，不触碰路由实例（组件负责 push）；字段只带后端 LaunchCreateIn
 * 认的 product_id / shop_id，外加 `from` 作为回跳来源（白名单由调用方 isSafeReturnTo 校验）。
 * 非 id 值（事件对象 / 带单位的字符串 / NaN）一律丢弃，绝不把 `[object …]` 写进 URL。
 * @returns {{path:string, query:object}}
 */
export function buildLaunchDeepLink(productId, { shopId = null, from = '' } = {}) {
  const query = {}
  const pid = toPositiveInt(productId)
  const sid = toPositiveInt(shopId)
  if (pid != null) query.product_id = String(pid)
  if (sid != null) query.shop_id = String(sid)
  if (from) query.from = String(from)
  return { path: '/app/launch', query }
}

/**
 * J1 向导起点：已携带 product_id 时跳过「选商品」步，直接进「选店铺/确认」，上下文不丢。
 * @returns {0|1} 0=从未带商品（正常从上线中心进入）；1=已带商品（从商品详情深链进入）。
 */
export function launchWizardStartStep(productId) {
  return toPositiveInt(productId) != null ? 1 : 0
}
