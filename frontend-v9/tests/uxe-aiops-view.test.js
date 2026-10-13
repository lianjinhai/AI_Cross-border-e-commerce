import { describe, expect, it } from 'vitest'
import {
  agentLabel, isRecoverableRun, paramsHint, runActiveStep, runWizardSteps,
  sortRunsForRecovery, stepDesc, stepFlowStatus,
} from '../src/features/aiops/workflowView'
import {
  FREQ_OPTIONS, SCHEDULE_KIND_OPTIONS, formatDateTime, freqLabel, kindLabel,
  lastStatusLabel, nextRunAt,
} from '../src/features/aiops/scheduleView'
import {
  candidateActions, candidateStatusLabel, candidateStatusType, canAnswer,
  canApprove, canReject, canRevoke, docSourceLabel, hitTagType,
} from '../src/features/aiops/knowledgeView'
import {
  AGENT_OPTIONS, SUBJECT_TYPE_OPTIONS, briefDecision, decisionReasons,
  filtersFromQuery, prettyJson,
} from '../src/features/aiops/decisionsView'

/**
 * UX-E aiops 视图模型纯函数测试（对照 backend routers/models 逐字核对）。
 */

describe('workflowView', () => {
  const tpl = {
    key: 'auto_listing',
    name: '自动铺货',
    description: '全链路自动铺货',
    steps: [
      { agent: 'discovery', action: 'pick_candidates', params: { limit: 3, offset: 0 } },
      { agent: 'listing', action: 'generate_batch', params: {} },
    ],
  }

  it('runWizardSteps puts intro, per-step param hints and confirm', () => {
    const steps = runWizardSteps(tpl)
    expect(steps).toHaveLength(4)
    expect(steps[0]).toMatchObject({ key: 'intro', hint: '全链路自动铺货' })
    expect(steps[1].label).toBe('市场发现·pick_candidates')
    expect(steps[1].hint).toBe('limit=3；offset=0')
    expect(steps[2].hint).toBe('该步骤无参数，自动执行')
    expect(steps[3].key).toBe('confirm')
  })

  it('maps agent labels and unknown agents fall through', () => {
    expect(agentLabel('discovery')).toBe('市场发现')
    expect(agentLabel('pricing')).toBe('定价')
    expect(agentLabel('unknown_agent')).toBe('unknown_agent')
  })

  it('sorts recoverable runs first keeping created_at desc within groups', () => {
    const runs = [
      { id: 1, status: 'success', created_at: '2026-01-01T10:00:00' },
      { id: 2, status: 'failed', created_at: '2026-01-02T10:00:00' },
      { id: 3, status: 'blocked', created_at: '2026-01-01T09:00:00' },
      { id: 4, status: 'running', created_at: '2026-01-03T10:00:00' },
    ]
    const sorted = sortRunsForRecovery(runs)
    expect(sorted.map((r) => r.id)).toEqual([2, 3, 4, 1])
    expect(isRecoverableRun(runs[1])).toBe(true)
    expect(isRecoverableRun(runs[0])).toBe(false)
    // 不修改原数组
    expect(runs.map((r) => r.id)).toEqual([1, 2, 3, 4])
  })

  it('step status map and descriptions follow the legacy mapping', () => {
    expect(stepFlowStatus('success')).toBe('success')
    expect(stepFlowStatus('running')).toBe('process')
    expect(stepFlowStatus('blocked')).toBe('error')
    expect(stepFlowStatus('pending')).toBe('wait')
    expect(stepFlowStatus('whatever')).toBe('wait')
    expect(stepDesc({ status: 'pending', error: 'x', output: {} })).toBe('错误：x')
    expect(stepDesc({ status: 'success', output: { repriced: [1, 2, 3] } })).toBe('repriced: 3 条')
    expect(stepDesc({ status: 'success', output: { margin: 0.3 } })).toBe('margin: 0.3')
    expect(runActiveStep([{ status: 'success' }, { status: 'failed' }])).toBe(1)
    expect(runActiveStep([{ status: 'success' }])).toBe(1)
  })
})

describe('scheduleView', () => {
  it('exposes only backend-accepted kinds and frequency bounds', () => {
    expect(SCHEDULE_KIND_OPTIONS.map((o) => o.value))
      .toEqual(['workflow', 'trend_scan', 'alert_scan'])
    expect(FREQ_OPTIONS.every((o) => o.value >= 5 && o.value <= 43200)).toBe(true)
  })

  it('labels frequencies and kinds like the legacy page', () => {
    expect(freqLabel(30)).toBe('每 30 分钟')
    expect(freqLabel(60)).toBe('每 1 小时')
    expect(freqLabel(1440)).toBe('每 1 天')
    expect(freqLabel(10080)).toBe('每 1 周')
    expect(freqLabel(45)).toBe('每 45 分钟')
    expect(kindLabel({ kind: 'workflow', workflow_key: 'auto_listing' })).toBe('工作流·auto_listing')
    expect(kindLabel({ kind: 'alert_scan' })).toBe('主动巡检')
    expect(kindLabel({ kind: 'trend_scan' })).toBe('趋势扫描')
    expect(lastStatusLabel('dispatched')).toBe('已派发')
    expect(lastStatusLabel('whatever')).toBe('whatever')
  })

  it('estimates next run only when enabled and last_run_at exists', () => {
    const now = new Date('2026-03-01T12:00:00')
    expect(nextRunAt({ enabled: false, last_run_at: '2026-03-01T10:00:00', interval_minutes: 60 }, now).text).toBe('—')
    expect(nextRunAt({ enabled: true, last_run_at: null, interval_minutes: 60 }, now).text).toBe('—')
    const vm = nextRunAt(
      { enabled: true, last_run_at: '2026-03-01T11:30:00', interval_minutes: 60 }, now,
    )
    expect(vm.estimated).toBe(true)
    expect(vm.text).toBe('2026-03-01 12:30')
    const overdue = nextRunAt(
      { enabled: true, last_run_at: '2026-02-28T10:00:00', interval_minutes: 60 }, now,
    )
    expect(overdue.text).toBe('待调度器拾取（已到期）')
    const boundary = nextRunAt(
      { enabled: true, last_run_at: '2026-03-01T11:00:00', interval_minutes: 60 }, now,
    )
    expect(boundary.text).toBe('待调度器拾取（已到期）') // 恰好到期也归调度器拾取
    expect(formatDateTime('bad')).toBe('')
  })
})

describe('knowledgeView', () => {
  it('enforces the no-answer-never-approved red line', () => {
    const none = { answer_source: 'none', status: 'pending', doc_id: null }
    const operator = { answer_source: 'operator', status: 'pending', doc_id: null }
    const approved = { answer_source: 'operator', status: 'approved', doc_id: 3 }
    expect(canAnswer(none)).toBe(true)
    expect(canApprove(none)).toBe(false) // 红线：无验证答案不可采纳
    expect(canApprove(operator)).toBe(true)
    expect(canApprove(approved)).toBe(false)
    expect(canRevoke(approved)).toBe(true)
    expect(canRevoke(operator)).toBe(false)
    expect(canReject(approved)).toBe(true)
    expect(candidateActions(none)).toEqual({ answer: true, approve: false, revoke: false, reject: true })
  })

  it('maps candidate statuses, doc sources and hit thresholds', () => {
    expect(candidateStatusLabel('auto_learned')).toBe('AI 已固化')
    expect(candidateStatusType('rejected')).toBe('danger')
    expect(candidateStatusType('nope')).toBe('info')
    expect(docSourceLabel('auto_learned')).toBe('AI 自动固化')
    expect(docSourceLabel('support_candidate')).toBe('客服沉淀')
    expect(docSourceLabel('')).toBe('')
    expect(docSourceLabel(undefined)).toBe('')
    expect(hitTagType(5)).toBe('danger')
    expect(hitTagType(4)).toBe('info')
  })
})

describe('decisionsView', () => {
  it('briefs decisions and extracts evidence reasons', () => {
    expect(briefDecision({})).toBe('—')
    expect(briefDecision(undefined)).toBe('—')
    expect(briefDecision({ margin: 0.3, action: 'raise' })).toBe('margin=0.3，action=raise')
    expect(decisionReasons({ reasons: ['a', 'b'] })).toEqual(['a', 'b'])
    expect(decisionReasons({})).toEqual([])
    expect(decisionReasons(undefined)).toEqual([])
    expect(prettyJson({ a: 1 })).toBe('{\n  "a": 1\n}')
  })

  it('prefills filters from deep-link queries, dropping invalid values', () => {
    expect(filtersFromQuery({ agent: 'pricing', subject_type: 'product', subject_id: '12' }))
      .toEqual({ agent: 'pricing', subjectType: 'product', subjectId: 12 })
    expect(filtersFromQuery({ agent: 'hacker', subject_type: 'nope', subject_id: '-1' }))
      .toEqual({ agent: '', subjectType: '', subjectId: null })
    expect(filtersFromQuery({})).toEqual({ agent: '', subjectType: '', subjectId: null })
    expect(AGENT_OPTIONS.some((o) => o.value === '')).toBe(true)
    expect(SUBJECT_TYPE_OPTIONS.map((o) => o.value)).toContain('product')
  })
})
