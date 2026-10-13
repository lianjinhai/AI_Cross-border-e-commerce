/**
 * 站内回跳（return_to）白名单校验（UX-03）。
 *
 * 从 `composables/launchCenter.js` 迁入的中立模块：原先白名单仅 `['/launch']`，
 * 导致从上线任务点入商品 / Listing / 店铺专业页后**无法回到原步骤**（AC-14.7 闭环缺口）。
 * 现扩为上线流程可挂接的专业页集合；`launchCenter.js` 通过「重新导出」保持其公共 API 不变
 * （既有签名 / 行为 / 测试零改动）。
 *
 * 纯模块、零依赖，供数据层 composable 与通用组件（如 PageHeader）共用。
 */

export const RETURN_WHITELIST = ['/launch', '/listings', '/products', '/shops']

/** 站内白名单校验：仅放行白名单前缀路径；拒绝站外 / 协议相对 / 目录穿越 / 反斜杠。 */
export function isSafeReturnTo(path) {
  if (typeof path !== 'string' || !path.startsWith('/')) return false
  if (path.startsWith('//') || path.includes('\\') || path.includes('..')) return false
  const base = path.split('?')[0].split('#')[0]
  return RETURN_WHITELIST.some((p) => base === p || base.startsWith(`${p}/`))
}

/** 非法路径回退 fallback（默认 `/launch`）。 */
export function sanitizeReturnTo(path, fallback = '/launch') {
  return isSafeReturnTo(path) ? path : fallback
}
