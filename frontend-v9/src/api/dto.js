/**
 * DTO 转换纯函数（契约 §4.3）：snake_case（后端）→ 视图模型（前端）。
 *
 * 全部为纯函数、可 vitest 直测；页面禁止直接 import axios，也禁止在组件里
 * 手写字段映射。仅转换键名风格与空值兜底，**不伪造缺失字段**（未接入字段保持
 * 缺省，由视图按「未接入」呈占位，对应 B03–B09 口径）。
 */

/** snake_case → camelCase 键名。 */
export function toCamelCase(key) {
  return String(key).replace(/_([a-z0-9])/g, (_, ch) => ch.toUpperCase())
}

/** 深度转换对象/数组的键名；原始类型原样返回；null/undefined 原样返回。 */
export function camelize(value) {
  if (Array.isArray(value)) return value.map((item) => camelize(item))
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, val]) => [toCamelCase(key), camelize(val)]),
    )
  }
  return value
}

/** 列表形态便捷封装：items 逐项 camelize，其余字段（total 等）一并转换。 */
export function camelizePage(page) {
  return camelize(page)
}
