import api from '../../shared/api/client'

/**
 * workbench 域（契约 §4.2）：对应 backend/app/routers/workbench.py（前缀 /workbench）。
 *
 * 只读 BFF，字段**透传后端 build_todo/build_overview，禁改名**；
 * 只发 GET，绝不发起任何写请求。
 *
 * partial 降级红线（契约 §4.3）：`partial`/`sources` 字段必须透传到视图层
 * （TaskCard/MetricCard 必须渲染完整性提示），禁止吞掉；FACTORY 空、COMPLIANCE
 * 脱敏由后端保证，前端不特判。
 */

/** GET /workbench/todo：跨域待办（items + counts + partial + sources）。 */
export async function fetchTodo({ limit = 50, includeHistory = false } = {}) {
  return (await api.get('/workbench/todo', {
    params: { limit, include_history: includeHistory },
  })).data
}

/** GET /workbench/overview：首页 6 问聚合（sections + signals + partial + sources）。 */
export async function fetchOverview({ limit = 50 } = {}) {
  return (await api.get('/workbench/overview', { params: { limit } })).data
}
