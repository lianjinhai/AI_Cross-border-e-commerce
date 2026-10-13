import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * UX-E 域端点契约锁定：域函数必须打到 backend/app/routers/ 的真实端点，
 * 入参键名与后端 Pydantic 模型一致（对照 routers 源码逐字核对）。
 */
vi.mock('../src/shared/api/client', () => {
  const calls = []
  const make = (method) => vi.fn(async (url, config) => {
    calls.push({ method, url, config })
    return { data: { ok: true, url, method, config } }
  })
  const api = {
    get: make('GET'), post: make('POST'), put: make('PUT'), delete: make('DELETE'),
    interceptors: { request: { use() {} }, response: { use() {} } },
  }
  api.__calls = calls
  return { default: api }
})

import api from '../src/shared/api/client'
import {
  fetchTemplates, runWorkflow, fetchRuns, fetchRun, resumeRun,
} from '../src/api/domains/workflows'
import {
  fetchSchedules, createSchedule, updateSchedule, deleteSchedule, triggerSchedule,
} from '../src/api/domains/schedules'
import {
  fetchDocs, createDoc, updateDoc, deleteDoc, searchDocs,
  fetchCandidates, answerCandidate, approveCandidate, rejectCandidate, revokeCandidate,
  fetchLearningSettings, updateLearningSettings,
} from '../src/api/domains/knowledge'
import {
  fetchAiSettings, saveAiSettings, fetchAiDecisions, fetchAiLogs, sendChat,
} from '../src/api/domains/ai'
import { fetchUsers, createUser, updateUser, deleteUser } from '../src/api/domains/users'

const calls = () => api.__calls
const last = () => calls().at(-1)

beforeEach(() => { calls().length = 0 })

describe('workflows domain endpoints', () => {
  it('hits templates/run/runs/resume with backend param names', async () => {
    await fetchTemplates()
    expect(last()).toMatchObject({ method: 'GET', url: '/workflows/templates' })

    await runWorkflow('auto_listing', { product_ids: [1] })
    expect(last()).toMatchObject({ method: 'POST', url: '/workflows/run' })
    expect(api.post.mock.calls.at(-1)[1]).toEqual({ template_key: 'auto_listing', context: { product_ids: [1] } })

    await fetchRuns(50)
    expect(last().url).toBe('/workflows/runs')
    expect(last().config.params).toEqual({ limit: 50 })

    await fetchRun(7)
    expect(last()).toMatchObject({ method: 'GET', url: '/workflows/runs/7' })

    await resumeRun(7)
    expect(last()).toMatchObject({ method: 'POST', url: '/workflows/runs/7/resume' })
  })
})

describe('schedules domain endpoints', () => {
  it('create sends ScheduleIn fields; update/trigger/delete use the id path', async () => {
    await fetchSchedules()
    expect(last()).toMatchObject({ method: 'GET', url: '/schedules' })

    await createSchedule({ name: '每日扫趋势', kind: 'workflow', workflow_key: 'auto_listing', interval_minutes: 360 })
    expect(last()).toMatchObject({ method: 'POST', url: '/schedules' })
    expect(api.post.mock.calls.at(-1)[1]).toEqual({
      name: '每日扫趋势', kind: 'workflow', workflow_key: 'auto_listing',
      interval_minutes: 360, enabled: true,
    })

    await updateSchedule(5, { enabled: false })
    expect(last()).toMatchObject({ method: 'PUT', url: '/schedules/5' })
    expect(api.put.mock.calls.at(-1)[1]).toEqual({ enabled: false })

    await triggerSchedule(5)
    expect(last()).toMatchObject({ method: 'POST', url: '/schedules/5/run' })

    await deleteSchedule(5)
    expect(last()).toMatchObject({ method: 'DELETE', url: '/schedules/5' })
  })
})

describe('knowledge domain endpoints', () => {
  it('docs CRUD uses keyword/page_num/page_size; search uses q/top_k', async () => {
    await fetchDocs({ keyword: '退货', page: 2, pageSize: 15 })
    expect(last().url).toBe('/knowledge/docs')
    expect(last().config.params).toEqual({ keyword: '退货', page_num: 2, page_size: 15 })

    await createDoc({ title: 't', content: 'c', source: 's' })
    expect(last()).toMatchObject({ method: 'POST', url: '/knowledge/docs' })

    await updateDoc(9, { title: 't2' })
    expect(last()).toMatchObject({ method: 'PUT', url: '/knowledge/docs/9' })

    await deleteDoc(9)
    expect(last()).toMatchObject({ method: 'DELETE', url: '/knowledge/docs/9' })

    await searchDocs('佣金', 4)
    expect(last().url).toBe('/knowledge/search')
    expect(last().config.params).toEqual({ q: '佣金', top_k: 4 })
  })

  it('candidate lifecycle and learning settings hit the M4 routes', async () => {
    await fetchCandidates({ status: 'pending', limit: 200 })
    expect(last().url).toBe('/knowledge/candidates')
    expect(last().config.params).toEqual({ status: 'pending', limit: 200 })

    await answerCandidate(3, '标准答案')
    expect(last()).toMatchObject({ method: 'POST', url: '/knowledge/candidates/3/answer' })
    expect(api.post.mock.calls.at(-1)[1]).toEqual({ answer: '标准答案' })

    await approveCandidate(3, '')
    expect(last()).toMatchObject({ method: 'POST', url: '/knowledge/candidates/3/approve' })

    await rejectCandidate(3)
    expect(last()).toMatchObject({ method: 'POST', url: '/knowledge/candidates/3/reject' })

    await revokeCandidate(3)
    expect(last()).toMatchObject({ method: 'POST', url: '/knowledge/candidates/3/revoke' })

    await fetchLearningSettings()
    expect(last()).toMatchObject({ method: 'GET', url: '/knowledge/learning/settings' })

    await updateLearningSettings({ auto_learn_enabled: true, auto_learn_threshold: 5 })
    expect(last()).toMatchObject({ method: 'PUT', url: '/knowledge/learning/settings' })
    expect(api.put.mock.calls.at(-1)[1]).toEqual({ auto_learn_enabled: true, auto_learn_threshold: 5 })
  })
})

describe('ai domain endpoints', () => {
  it('settings/decisions/logs/chat match the ai router', async () => {
    await fetchAiSettings()
    expect(last()).toMatchObject({ method: 'GET', url: '/ai/settings' })

    await saveAiSettings({ rules: { target_margin: 0.4 } })
    expect(last()).toMatchObject({ method: 'PUT', url: '/ai/settings' })
    expect(api.put.mock.calls.at(-1)[1]).toEqual({ rules: { target_margin: 0.4 } })

    await fetchAiDecisions({ agent: 'pricing', subjectType: 'product', subjectId: 12, limit: 100 })
    expect(last().url).toBe('/ai/decisions')
    expect(last().config.params).toEqual({ agent: 'pricing', subject_type: 'product', subject_id: 12, limit: 100 })

    await fetchAiDecisions({ agent: '', subjectType: '', subjectId: null, limit: 100 })
    expect(last().config.params).toEqual({ agent: '', subject_type: '', subject_id: null, limit: 100 })

    await fetchAiLogs(50)
    expect(last().url).toBe('/ai/logs')
    expect(last().config.params).toEqual({ limit: 50 })

    await sendChat('帮我选品')
    expect(last()).toMatchObject({ method: 'POST', url: '/ai/chat' })
    expect(api.post.mock.calls.at(-1)[1]).toEqual({ message: '帮我选品' })
  })
})

describe('users domain endpoints', () => {
  it('member CRUD hits /auth/users with legacy role values', async () => {
    await fetchUsers()
    expect(last().url).toBe('/auth/users')
    expect(last().config.params).toEqual({ page_size: 100 })

    await createUser({ username: 'op1', password: 'longpassword1', role: 'operator', display_name: '运营一号' })
    expect(last()).toMatchObject({ method: 'POST', url: '/auth/users' })
    expect(api.post.mock.calls.at(-1)[1]).toEqual({
      username: 'op1', password: 'longpassword1', role: 'operator', display_name: '运营一号',
    })

    await updateUser(6, { role: 'viewer', status: 'disabled' })
    expect(last()).toMatchObject({ method: 'PUT', url: '/auth/users/6' })
    expect(api.put.mock.calls.at(-1)[1]).toEqual({ role: 'viewer', status: 'disabled' })

    await deleteUser(6)
    expect(last()).toMatchObject({ method: 'DELETE', url: '/auth/users/6' })
  })
})
