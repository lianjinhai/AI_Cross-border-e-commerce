import api from '../../shared/api/client'

/**
 * schedules 域（契约 §4.2）：对应 backend/app/routers/schedules.py（前缀 /schedules）。
 * 入参键名与后端 ScheduleIn/ScheduleUpdate 逐字一致（kind: workflow/trend_scan/alert_scan；
 * interval_minutes 后端校验 5 分钟 ~ 30 天）。
 */

/** 调度列表：GET /schedules → {items[]}（含 last_run_at/last_status/run_count）。 */
export async function fetchSchedules() {
  return (await api.get('/schedules')).data
}

/** 新建调度：POST /schedules {name, kind, workflow_key, interval_minutes, enabled} → 调度 DTO。 */
export async function createSchedule(data = {}) {
  return (await api.post('/schedules', {
    name: data.name || '',
    kind: data.kind || 'workflow',
    workflow_key: data.workflow_key || '',
    interval_minutes: data.interval_minutes ?? 1440,
    enabled: data.enabled ?? true,
  })).data
}

/** 更新调度：PUT /schedules/{id}（仅传显式字段；enabled=true 且正在执行时后端 409）。 */
export async function updateSchedule(scheduleId, data = {}) {
  return (await api.put(`/schedules/${scheduleId}`, data)).data
}

/** 删除调度：DELETE /schedules/{id} → {ok}。 */
export async function deleteSchedule(scheduleId) {
  return (await api.delete(`/schedules/${scheduleId}`)).data
}

/** 立即执行一次：POST /schedules/{id}/run → {ok, detail, schedule}。 */
export async function triggerSchedule(scheduleId) {
  return (await api.post(`/schedules/${scheduleId}/run`)).data
}
