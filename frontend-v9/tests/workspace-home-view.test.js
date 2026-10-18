import { describe, expect, it } from 'vitest'
import {
  UNKNOWN, aiActivity, blockerSummary, businessStage, businessSummary, conditionCardViewModel, displayName, entryPlan,
  formatBiRevenue, greeting, pickHighPriority, pickPrimaryTask, rankTasks, resolveEntryProfile, safeInternalPath, taskCounters,
  taskLink, taskPriorityKey,
} from '../src/shared/workspaceHomeView'
import { deriveWorkbenchCounts } from '../src/shared/workbenchContext'

/**
 * R3-2B §1 四层工作台视图模型单测：排序/计数/入口/阶段/摘要/活动流。
 * 样本形状逐字来自 backend/app/services/workbench.py（build_todo/build_overview）。
 */

const SAMPLE_TODO = {
  items: [
    { type: 'alert', title: '待处理风险告警', count: 3, severity: 'mid', due_at: null, route: { path: '/alerts', return_to: null }, ref: null },
    { type: 'launch', title: '待你处理的上线流程', count: 5, severity: 'high', due_at: '2026-01-01 10:00:00', route: { path: '/launch', return_to: '/launch?mine=true' }, ref: null },
    { type: 'review', title: '待人工复核的 Listing', count: 1, severity: 'high', due_at: null, route: { path: '/compliance-workbench', return_to: null }, ref: null },
  ],
  counts: { launch: 5, action: 0, alert: 3, review: 1 },
  generated_at: '2026-01-01T00:00:00Z',
  partial: false,
  sources: { launch: 'ok', action: 'ok', alert: 'ok', review: 'ok' },
}

describe('rankTasks / pickPrimaryTask / pickHighPriority（时限·风险·责任确定性排序）', () => {
  it('高风险优先，其次到期时间近的优先', () => {
    const ranked = rankTasks(SAMPLE_TODO.items)
    expect(ranked[0].severity).toBe('high')
    // 同为 high：launch 有 due_at（近）先于 review（无 due）
    expect(ranked[0].type).toBe('launch')
    expect(ranked[1].type).toBe('review')
    expect(ranked[2].type).toBe('alert')
  })

  it('pickPrimaryTask 取排序首条（第一层唯一主任务）', () => {
    expect(pickPrimaryTask(SAMPLE_TODO.items).type).toBe('launch')
    expect(pickPrimaryTask([])).toBeNull()
    expect(pickPrimaryTask(null)).toBeNull()
  })

  it('pickHighPriority 排除主任务、最多 3 项（第二层）', () => {
    const rest = pickHighPriority(SAMPLE_TODO.items, 3)
    expect(rest.map((i) => i.type)).toEqual(['review', 'alert'])
    // 超过 3 项时截断
    const many = Array.from({ length: 6 }, (_, i) => ({ type: 'launch', title: `t${i}`, severity: 'mid', count: 6 - i }))
    expect(pickHighPriority(many, 3)).toHaveLength(3)
  })

  it('taskPriorityKey 确定性且同键稳定', () => {
    expect(taskPriorityKey({ severity: 'high', due_at: null, type: 'review', count: 1 }))
      .toEqual([0, Number.POSITIVE_INFINITY, 0, -1])
  })
})

describe('taskCounters（首屏计数条：缺失/失败不当 0；口径与顶栏统一）', () => {
  const overviewOk = {
    sources: { launch: 'ok', need_human: 'ok' },
    sections: {
      need_human: { count: 2 }, // 待我处理 = need_human 口径
      in_progress: [
        { id: 1, execution_status: 'WAITING_EXTERNAL' },
        { id: 2, execution_status: 'BLOCKED' },
        { id: 3, execution_status: 'FAILED' },
        { id: 4, execution_status: 'RUNNING' }, // mine 状态：不计入等待外部/阻断
      ],
    },
  }

  it('正常：待我处理=need_human.count；等待外部/阻断按状态计数（RUNNING 不计入）', () => {
    const c = taskCounters(SAMPLE_TODO, overviewOk)
    expect(c.mine).toBe(2)
    expect(c.waitingExternal).toBe(1)
    expect(c.blocked).toBe(2)
  })

  it('上线源不可得 → 等待外部/阻断为「—」而非 0', () => {
    const c = taskCounters(SAMPLE_TODO, { sources: { launch: 'failed' }, sections: {} })
    expect(c.waitingExternal).toBe(UNKNOWN)
    expect(c.blocked).toBe(UNKNOWN)
  })

  it('need_human 不可得 → 待我处理为「—」而非 0', () => {
    const c = taskCounters(SAMPLE_TODO, { sources: { need_human: 'failed' }, sections: { in_progress: [] } })
    expect(c.mine).toBe(UNKNOWN)
  })

  it('确实为空 → 0（≠缺数据）', () => {
    const c = taskCounters(
      { counts: { launch: 0, action: 0, review: 0 }, sources: { launch: 'ok', action: 'ok', review: 'ok' } },
      { sources: { need_human: 'ok' }, sections: { need_human: { count: 0 }, in_progress: [] } })
    expect(c.mine).toBe(0)
    expect(c.blocked).toBe(0)
    expect(c.waitingExternal).toBe(0)
  })

  it('三方口径一致：工作台 taskCounters ≡ 顶栏 deriveWorkbenchCounts（顶栏/工作台/待办中心同源）', () => {
    const ov = {
      sources: { need_human: 'ok' },
      sections: {
        need_human: { count: 3 },
        in_progress: [
          { execution_status: 'WAITING_EXTERNAL' }, // 等待外部（执行态）
          { platform_status: 'SUBMITTED' },         // 等待外部（平台状态）
          { execution_status: 'FAILED' },           // 被阻断
          { execution_status: 'READY' },            // 不计入任何计数
        ],
      },
    }
    const home = taskCounters({}, ov)
    const bar = deriveWorkbenchCounts(ov)
    expect(home.mine).toBe(bar.todo)
    expect(home.waitingExternal).toBe(bar.waiting)
    expect(home.blocked).toBe(bar.blocked)
    expect(home.mine).toBe(3)
    expect(home.waitingExternal).toBe(2) // WAITING_EXTERNAL + SUBMITTED；READY 不混入
    expect(home.blocked).toBe(1)
  })
})

describe('resolveEntryProfile / entryPlan（画像不同入口不同）', () => {
  it('有店 → STORE_OWNER（上线/订单/利润入口）', () => {
    expect(resolveEntryProfile({ has_sales_shop: true, has_factory: false })).toBe('STORE_OWNER')
    expect(entryPlan('STORE_OWNER').recommended.path).toBe('/app/launch')
  })

  it('无店无厂单人 → NEW_USER（准备/选品/连店入口）', () => {
    expect(resolveEntryProfile({ has_sales_shop: false, has_factory: false, member_count: 1 })).toBe('NEW_USER')
    const plan = entryPlan('NEW_USER')
    expect(plan.steps.map((s) => s.path)).toContain('/app/channels/shops')
    expect(plan.recommended.path).toBe('/app/market/discovery')
  })

  it('关键事实缺失 → UNKNOWN（不猜）', () => {
    expect(resolveEntryProfile({})).toBe('UNKNOWN')
    expect(resolveEntryProfile(null)).toBe('UNKNOWN')
    expect(entryPlan('UNKNOWN').label).toBe('通用工作台')
  })

  it('仅工厂 → FACTORY；无店多人 → TEAM', () => {
    expect(resolveEntryProfile({ has_sales_shop: false, has_factory: true })).toBe('FACTORY')
    expect(resolveEntryProfile({ has_sales_shop: false, has_factory: false, member_count: 3 })).toBe('TEAM')
  })
})

describe('businessStage / blockerSummary / businessSummary（第三层）', () => {
  it('NEW_USER → 起步阶段', () => {
    expect(businessStage({ has_sales_shop: false, has_factory: false }, {}).stage).toBe('STARTING')
  })

  it('有店且有进行中上线 → 上线阶段', () => {
    const st = businessStage({ has_sales_shop: true, has_factory: false },
      { sections: { in_progress: [{ id: 1 }] } })
    expect(st.stage).toBe('LAUNCHING')
  })

  it('阻断摘要：源失败 → available=false（未知非“无阻断”）；对象字段人类可读（bug3）', () => {
    expect(blockerSummary({ sources: { launch: 'failed' } }).available).toBe(false)
    const ok = blockerSummary({
      sources: { launch: 'ok' },
      sections: {
        in_progress: [{
          id: 1, execution_status: 'BLOCKED',
          product: { id: 5, title: '哑铃', sku: 'D-1' },
          store: { id: 9, name: '美国站', platform: 'amazon' },
          blocked_summary: [{ message: '缺资料' }],
        }],
      },
    })
    expect(ok.available).toBe(true)
    expect(ok.items[0].message).toBe('缺资料')
    expect(ok.items[0].product).toBe('哑铃')
    expect(ok.items[0].store).toBe('美国站')
    expect(JSON.stringify(ok.items[0])).not.toContain('[object Object]')
  })

  it('经营摘要：指标缺失/无权限 → —（缺失不当 0）', () => {
    expect(businessSummary({ sources: { bi: 'failed' } })[0].value).toBe(UNKNOWN)
    const partial = businessSummary({ sources: { bi: 'ok' }, sections: { metrics: { gmv: null, orders: 0, contribution_profit: 12.5, currency: 'USD' } } })
    expect(partial[0].value).toBe(UNKNOWN) // gmv null → —
    expect(partial[0].missing).toBe(true)
    expect(partial[1].value).toBe('0') // 真实 0 显示 0，不是 —
  })

  it('AI 活动流：源失败 → available=false', () => {
    expect(aiActivity({ sources: { workflow: 'failed' } }).available).toBe(false)
    const ok = aiActivity({ sources: { workflow: 'ok' }, sections: { ai_done: { count: 1, items: [{ id: 9, title: 'X', status: 'success' }] } } })
    expect(ok.available).toBe(true)
    expect(ok.items[0].id).toBe(9)
  })
})

describe('safeInternalPath / taskLink（站内回跳白名单）', () => {
  it('拒绝站外与穿越路径', () => {
    expect(safeInternalPath('//evil.com')).toBeNull()
    expect(safeInternalPath('https://evil.com')).toBeNull()
    expect(safeInternalPath('/launch/../secret')).toBeNull()
    expect(safeInternalPath('/launch')).toBe('/launch')
  })

  it('taskLink 附加 return_to（保留待办位置）', () => {
    const link = taskLink({ path: '/launch' }, '/app/tasks?view=waiting')
    expect(link).toBe('/launch?return_to=%2Fapp%2Ftasks%3Fview%3Dwaiting')
    expect(taskLink({ path: '/launch' }, '//evil.com')).toBe('/launch')
  })
})

describe('displayName（bug1/bug3：后端 product/store 对象 → 人类可读字符串）', () => {
  it('product 取 title→sku→id；store 取 name→id；字符串原样；空 → —', () => {
    expect(displayName({ id: 1, title: '弹力带', sku: 'B1' }, 'product')).toBe('弹力带')
    expect(displayName({ id: 1, sku: 'B1' }, 'product')).toBe('B1') // 无 title 退 sku
    expect(displayName({ id: 7 }, 'product')).toBe('7')            // 退 id
    expect(displayName({ id: 2, name: '美国站', platform: 'amazon' }, 'store')).toBe('美国站')
    expect(displayName({ id: 2 }, 'store')).toBe('2')
    expect(displayName('美国站', 'store')).toBe('美国站')
    expect(displayName(0, 'product')).toBe('0')
    expect(displayName(null, 'store')).toBe(UNKNOWN)
    expect(displayName(undefined, 'product')).toBe(UNKNOWN)
    expect(displayName({}, 'product')).toBe(UNKNOWN)
  })
})

describe('greeting（B2 顶部问候行：按本地小时分桶，纯函数）', () => {
  it('05–11 早上好 / 12–17 下午好 / 18–04 晚上好', () => {
    expect(greeting(5)).toBe('早上好')
    expect(greeting(11)).toBe('早上好')
    expect(greeting(12)).toBe('下午好')
    expect(greeting(17)).toBe('下午好')
    expect(greeting(18)).toBe('晚上好')
    expect(greeting(23)).toBe('晚上好')
    expect(greeting(0)).toBe('晚上好')
    expect(greeting(4)).toBe('晚上好')
  })

  it('非法/越界小时 → 「你好」（不抛错）', () => {
    expect(greeting(NaN)).toBe('你好')
    expect(greeting(-1)).toBe('你好')
    expect(greeting(24)).toBe('你好')
    expect(greeting('x')).toBe('你好')
  })
})

describe('conditionCardViewModel（B2 经营条件卡：会话画像三行，缺项待补+入口）', () => {
  it('null 画像 → 三行全缺，值「待补」，链接 /onboarding?step=1', () => {
    const rows = conditionCardViewModel(null)
    expect(rows.map((r) => r.key)).toEqual(['budget', 'targetMarket', 'risk'])
    expect(rows.every((r) => r.missing && r.value === '待补' && r.link === '/onboarding?step=1')).toBe(true)
  })

  it('部分画像 → 仅缺项标记待补并给链接，已填行显真实值且无链接', () => {
    const rows = conditionCardViewModel({ budget: '2 万', targetMarket: '', risk: '保守' })
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]))
    expect(byKey.budget).toMatchObject({ value: '2 万', missing: false, link: '' })
    expect(byKey.targetMarket).toMatchObject({ value: '待补', missing: true, link: '/onboarding?step=1' })
    expect(byKey.risk).toMatchObject({ value: '保守', missing: false, link: '' })
  })

  it('零值/空格不误判为已填', () => {
    const rows = conditionCardViewModel({ budget: '   ', targetMarket: null, risk: 0 })
    // 0 是合法值（风险偏好=0 档），视为已填；空格与 null 视为缺
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]))
    expect(byKey.budget.missing).toBe(true)
    expect(byKey.targetMarket.missing).toBe(true)
    expect(byKey.risk.missing).toBe(false)
    expect(byKey.risk.value).toBe('0')
  })
})

describe('formatBiRevenue（B2 task3：BI 销售额诚实货币渲染）', () => {
  it('缺失/null → —（不当 0）', () => {
    expect(formatBiRevenue(null, 'USD')).toEqual({ display: UNKNOWN, currencyNote: '' })
    expect(formatBiRevenue(undefined, 'USD')).toEqual({ display: UNKNOWN, currencyNote: '' })
    expect(formatBiRevenue('', 'USD')).toEqual({ display: UNKNOWN, currencyNote: '' })
    expect(formatBiRevenue('abc', 'USD')).toEqual({ display: UNKNOWN, currencyNote: '' })
  })

  it('有币种 → 真实币种 + 金额（来自 BI DTO 顶层 currency）', () => {
    expect(formatBiRevenue(123.4, 'USD')).toEqual({ display: 'USD 123.40', currencyNote: '' })
    expect(formatBiRevenue(0, 'CNY')).toEqual({ display: 'CNY 0.00', currencyNote: '' })
  })

  it('无币种 → 裸数字 + 「币种未知」标注（不臆造符号）', () => {
    expect(formatBiRevenue(123.4, '')).toEqual({ display: '123.40', currencyNote: '币种未知' })
    expect(formatBiRevenue(123.4, undefined)).toEqual({ display: '123.40', currencyNote: '币种未知' })
  })
})

