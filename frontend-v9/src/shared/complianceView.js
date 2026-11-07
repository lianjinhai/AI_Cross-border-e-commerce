/**
 * 目的国合规要求 × 证据 × 标签包（M2-E）的纯展示逻辑。
 *
 * 为什么抽成纯函数：本仓没有 `@vue/test-utils`，组件里的逻辑测不到；而这一段恰好
 * 最容易悄悄骗人——「没查到要求」被渲染成「无需认证」、缺项被渲染成绿勾。
 * 因此判定与文案全部在这里，组件只做绑定。
 *
 * 口径（与后端 `services/label_packages.resolve_basis` 一致，不另立一套）：
 * - `covered=false`（该国一条要求都没收录）**不等于**「没有要求」，必须显式提示；
 * - 某条要求只有 `state === 'SATISFIED'` 才算具备，`MISSING` / `EXPIRED` 都算缺口；
 * - 非强制要求（`mandatory=false`）缺失不算缺口，但要在表里如实显示状态。
 */

/** 单条要求的状态（顺序即严重程度，用于排序）。 */
export const REQUIREMENT_STATE = { SATISFIED: 'SATISFIED', EXPIRED: 'EXPIRED', MISSING: 'MISSING' }

const STATE_META = {
  SATISFIED: { label: '已具备', tone: 'success', order: 0 },
  EXPIRED: { label: '已过期', tone: 'warning', order: 1 },
  MISSING: { label: '缺证据', tone: 'danger', order: 2 },
}

/** 没有目的国时的固定文案（不猜目的地，也不假装已检查）。 */
export const NO_COUNTRY_HINT = '未选择目的国：没有目的国就无从判断要声明哪些认证，也不做默认猜测'

/**
 * 依据 → 表行 + 缺口 + 结论。
 * @param {object|null} basis 后端 `GET /cross-border/products/{id}/labels` 的 basis 字段
 * @returns {object|null} null 表示还没查（不是「通过」）
 */
export function complianceBasisView(basis = null) {
  if (!basis || typeof basis !== 'object') return null
  const country = String(basis.country || '')
  if (!country) {
    return { country: '', covered: false, complete: false, rows: [], gaps: [],
      reasons: [NO_COUNTRY_HINT], tone: 'info', headline: NO_COUNTRY_HINT, canGenerate: false }
  }
  const state = new Map()
  const put = (items, name, extra = {}) => (Array.isArray(items) ? items : []).forEach((item) => {
    if (!item || !item.requirement) return
    state.set(item.requirement, {
      requirement: String(item.requirement),
      mandatory: item.mandatory !== false,
      note: String(item.note || ''),
      // 证据引用与有效期只出现在 satisfied/expired 行；丢了它们表格会显示「已具备」但没证据号。
      evidence_ref: String(item.evidence_ref || ''),
      valid_until: String(item.valid_until || ''),
      state: name,
      ...extra,
    })
  })
  put(basis.satisfied, REQUIREMENT_STATE.SATISFIED)
  put(basis.expired, REQUIREMENT_STATE.EXPIRED)
  put(basis.missing, REQUIREMENT_STATE.MISSING)

  const rows = (Array.isArray(basis.requirements) ? basis.requirements : [])
    .filter((item) => item && item.requirement)
    .map((item) => {
      const known = state.get(item.requirement) || {}
      const row = {
        requirement: String(item.requirement),
        mandatory: item.mandatory !== false,
        note: String(item.note || known.note || ''),
        state: known.state || REQUIREMENT_STATE.MISSING,
        evidenceRef: String(known.evidence_ref || ''),
        validUntil: String(known.valid_until || ''),
      }
      return { ...row, ...STATE_META[row.state], stateText: STATE_META[row.state].label }
    })
    .sort((a, b) => a.order - b.order || a.requirement.localeCompare(b.requirement))

  const covered = Boolean(basis.covered) && rows.length > 0
  const gaps = rows.filter((row) => row.mandatory && row.state !== REQUIREMENT_STATE.SATISFIED)
  const reasons = Array.isArray(basis.reasons) && basis.reasons.length
    ? basis.reasons.map(String)
    : (covered ? gaps.map((row) => `${row.requirement}：${row.stateText}`) : [NO_COUNTRY_HINT])
  const complete = covered && gaps.length === 0
  return {
    country,
    covered,
    complete,
    rows,
    gaps,
    reasons,
    canGenerate: complete,
    tone: complete ? 'success' : (covered ? 'danger' : 'warning'),
    headline: !covered
      ? `${country} 的准入要求尚未收录——这是「未知」，不是「无需认证」`
      : (complete ? `${country} 的准入依据已齐备（${rows.length} 项）`
        : `${country} 还缺 ${gaps.length} 项依据，不能生成标签包`),
    // 未收录时不能「补证据」了事：要先补要求本身（租户合规规则），所以写证据入口也关掉。
    canRegisterEvidence: covered,
  }
}

/** 证据登记表单的本地校验（与后端 `EvidenceIn` 的必填/长度口径一致）。 */
export function evidenceFormGaps(form = {}) {
  const gaps = []
  if (!String(form.destination_country || '').trim()) gaps.push('目的国不能为空')
  if (!String(form.requirement || '').trim()) gaps.push('要补的认证项不能为空')
  const ref = String(form.evidence_ref || '').trim()
  if (!ref) gaps.push('证据引用不能为空（证书编号或文件链接）')
  else if (ref.length > 512) gaps.push('证据引用不能超过 512 字符')
  const until = String(form.valid_until || '').trim()
  if (until && !/^\d{4}-\d{2}-\d{2}/.test(until)) gaps.push('有效期格式应为 YYYY-MM-DD')
  return gaps
}

/** 表单 → 提交体：空值不发送（后端用「空引用」表示缺证据，不能让空串冒充已填）。 */
export function evidencePayload(form = {}) {
  const payload = {
    destination_country: String(form.destination_country || '').trim().toUpperCase(),
    requirement: String(form.requirement || '').trim(),
    evidence_ref: String(form.evidence_ref || '').trim(),
    note: String(form.note || '').trim(),
  }
  const until = String(form.valid_until || '').trim()
  if (until) payload.valid_until = until
  return payload
}

/**
 * 标签包版本行（新→旧）：只展示只读信息，**不提供删除/覆盖按钮**。
 * @param {Array} items 后端 `GET /labels` 的 items
 */
export function labelHistoryView(items = []) {
  return (Array.isArray(items) ? items : [])
    .filter((item) => item && Number(item.version) > 0)
    .map((item) => ({
      id: item.id,
      version: Number(item.version),
      action: String(item.action || ''),
      country: String(item.destination_country || ''),
      marks: (item.content?.marks || []).map((mark) => String(mark.requirement || '')).filter(Boolean),
      contentDigest: String(item.content_digest || ''),
      shortDigest: String(item.content_digest || '').slice(0, 12),
      createdAt: String(item.created_at || ''),
      openItems: Array.isArray(item.open_items) ? item.open_items.map(String) : [],
      // 印刷前必须人工补全的字段数：>0 时界面要显式提示「不能直接拿去印」。
      openItemCount: Array.isArray(item.open_items) ? item.open_items.length : 0,
    }))
    .sort((a, b) => b.version - a.version)
}
