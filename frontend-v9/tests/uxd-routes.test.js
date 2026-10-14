import { describe, expect, it } from 'vitest'
import { UXD_ROUTES } from '../src/app/router/routes-uxd'

/**
 * UX-D 路由数组契约锁定（并行期特殊约定：不改 router/index.js，由总调度合并）。
 * meta 必须与 index.js appChildren 中对应 path 的冻结 meta 逐字一致（space/domain/title）。
 * 蓝图 R1：domain 标签随 8 域同步（任务分解 §A.5），title 同步蓝图 §5 页名。
 */
const EXPECTED = {
  'supply/suppliers': { space: 'app', domain: '货源与采购', title: '供应商库' },
  'supply/purchases': { space: 'app', domain: '货源与采购', title: '采购单' },
  orders: { space: 'app', domain: '订单与服务', title: '订单工作台' },
  settlements: { space: 'app', domain: '财务与分析', title: '结算与对账' },
  refunds: { space: 'app', domain: '订单与服务', title: '售后退款' },
  support: { space: 'app', domain: '订单与服务', title: '客户消息' },
  pricing: { space: 'app', domain: '经营优化', title: '定价与利润试算' },
  ads: { space: 'app', domain: '经营优化', title: '广告与转化' },
  'risk/alerts': { space: 'app', domain: '经营优化', title: '商品与店铺诊断' },
  'analytics/bi': { space: 'app', domain: '财务与分析', title: '经营总览与 BI' },
  'analytics/finance': { space: 'app', domain: '财务与分析', title: '真实利润' },
  'analytics/landed-cost': { space: 'app', domain: '财务与分析', title: '到岸成本' },
  // ── 蓝图 R1 P0 补齐：导航叶子可点（真实页未交付，先挂 StubPage 防 404，标记待接入） ──
  'supply/sourcing': { space: 'app', domain: '货源与采购', title: '货源发现' },
  'supply/matching': { space: 'app', domain: '货源与采购', title: '货源匹配' },
  fulfillment: { space: 'app', domain: '订单与服务', title: '发货/代发/备货' },
  'optimization/experiments': { space: 'app', domain: '经营优化', title: '策略实验' },
  'analytics/forecast': { space: 'app', domain: '财务与分析', title: '预测与数据质量' },
  // R3-1A E09：channels / channels/shops/:id 两条 CH-01/CH-03 路由改由
  // src/app/router/index.js 唯一挂载（消除重复 path 展开命中风险），本数组不再声明。
}

describe('routes-uxd', () => {
  it('covers exactly the 17 UX-D pages with frozen meta', () => {
    expect(UXD_ROUTES).toHaveLength(17)
    for (const route of UXD_ROUTES) {
      expect(EXPECTED[route.path], `unknown path ${route.path}`).toBeDefined()
      expect(route.meta).toEqual(EXPECTED[route.path])
      expect(typeof route.component).toBe('function')
    }
    const paths = UXD_ROUTES.map((r) => r.path)
    expect(new Set(paths).size).toBe(17)
    expect(Object.keys(EXPECTED).every((p) => paths.includes(p))).toBe(true)
  })
})
