import { describe, expect, it } from 'vitest'
import { UXD_ROUTES } from '../src/app/router/routes-uxd'

/**
 * UX-D 路由数组契约锁定（并行期特殊约定：不改 router/index.js，由总调度合并）。
 * meta 必须与 index.js appChildren 中对应 path 的冻结 meta 逐字一致（space/domain/title）。
 */
const EXPECTED = {
  'supply/suppliers': { space: 'app', domain: '货源中心', title: '供应商库' },
  'supply/purchases': { space: 'app', domain: '货源中心', title: '采购单' },
  orders: { space: 'app', domain: '订单履约', title: '订单管理' },
  settlements: { space: 'app', domain: '订单履约', title: '账期结算' },
  refunds: { space: 'app', domain: '客户售后', title: '售后管理' },
  support: { space: 'app', domain: '客户售后', title: '智能客服' },
  pricing: { space: 'app', domain: '经营优化', title: '动态定价' },
  ads: { space: 'app', domain: '经营优化', title: '广告增长' },
  'risk/alerts': { space: 'app', domain: '经营优化', title: '风险巡检' },
  'analytics/bi': { space: 'app', domain: '数据分析', title: 'BI 经营分析' },
  'analytics/finance': { space: 'app', domain: '数据分析', title: '财务工作台' },
  'analytics/landed-cost': { space: 'app', domain: '数据分析', title: '到岸成本配置' },
}

describe('routes-uxd', () => {
  it('covers exactly the 12 UX-D pages with frozen meta', () => {
    expect(UXD_ROUTES).toHaveLength(12)
    for (const route of UXD_ROUTES) {
      expect(EXPECTED[route.path], `unknown path ${route.path}`).toBeDefined()
      expect(route.meta).toEqual(EXPECTED[route.path])
      expect(typeof route.component).toBe('function')
    }
    const paths = UXD_ROUTES.map((r) => r.path)
    expect(new Set(paths).size).toBe(12)
    expect(Object.keys(EXPECTED).every((p) => paths.includes(p))).toBe(true)
  })
})
