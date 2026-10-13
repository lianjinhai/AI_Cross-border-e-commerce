/**
 * BI 指标口径字典（UX-D #22）：每张指标卡可展开的口径说明。
 *
 * 后端 metric_summary 不下发口径字段，口径文案由本字典统一维护（唯一事实源），
 * 并明确区分五个易混口径：GMV / 净收入 / 贡献利润 / 结算到账 / 估算利润。
 * 「结算到账」不在 metric_summary 里（以平台实际打款为准，入口在财务工作台），
 * 仅作口径区分说明呈现，绝不伪造数值。
 */

export const BI_METRIC_CALIBERS = [
  {
    key: 'gmv',
    label: 'GMV',
    money: true,
    caliber: '统计周期内全部订单的账面金额合计（含待支付与已退款订单），反映经营规模。',
    distinction: 'GMV 口径最宽；净收入需扣除退款；两者都不等于实际到账。',
  },
  {
    key: 'net_revenue',
    label: '净收入',
    money: true,
    caliber: 'GMV 扣除退款金额后的确认收入，进入贡献利润计算的入账基数。',
    distinction: '净收入 ≠ 结算到账：平台实际打款还需扣除平台费/支付费，见财务工作台对账。',
  },
  {
    key: 'contribution_profit',
    label: '贡献利润',
    money: true,
    caliber: '净收入 − 订单成本 − 订单费用 − 广告花费（统一口径，与定价/到岸成本页同源 costing 实现）。',
    distinction: '贡献利润是统一财务口径；订单列表「利润」列是估算口径（售价−采购成本，未含平台费与广告）。',
  },
  {
    key: 'contribution_margin',
    label: '贡献利润率',
    money: false,
    caliber: '贡献利润 ÷ 净收入。',
    distinction: '与定价页「利润率」同口径；广告 ROI 不计入分母以外的口径换算。',
  },
  {
    key: 'order_cost',
    label: '订单成本',
    money: true,
    caliber: '统计周期内订单对应的采购+物流成本合计。',
    distinction: '成本口径不含平台费与广告费（单列于订单费用/广告花费）。',
  },
  {
    key: 'order_fees',
    label: '订单费用',
    money: true,
    caliber: '平台佣金、支付通道费等订单级费用合计。',
    distinction: '在财务工作台按订单行维护，缺汇率的费用会被排除而非静默混入。',
  },
  {
    key: 'ad_spend',
    label: '广告花费',
    money: true,
    caliber: '统计周期内广告活动花费合计。',
    distinction: '与广告增长页「总花费」同源。',
  },
  {
    key: 'roi',
    label: '广告 ROI',
    money: false,
    caliber: '广告带来的收入 ÷ 广告花费。',
    distinction: '广告增长页活动明细 ROI 与本页汇总同源。',
  },
  {
    key: 'refund_rate',
    label: '退款率',
    money: false,
    caliber: '退款订单金额 ÷ GMV。',
    distinction: '风险巡检「退款率异常」规则使用同一比率。',
  },
]

/** 结算到账口径说明（无数值卡，仅口径区分 + 财务入口互链）。 */
export const SETTLED_CALIBER_NOTE =
  '结算到账：以平台结算单实际打款金额为准（应结/实结/差异见财务工作台「平台结算对账」）。' +
  '结算到账 ≠ 净收入 ≠ GMV：三者口径依次变窄，禁止混用。'

/** 估算利润口径说明（订单列表「利润」列）。 */
export const ESTIMATED_PROFIT_NOTE =
  '估算利润：订单口径的「售价 − 采购成本」快速估算，未含平台费、支付费、广告与退货成本，' +
  '仅供运营排序参考；经营决策以「贡献利润」统一口径为准。'

const MONEY_KEYS = new Set(BI_METRIC_CALIBERS.filter((m) => m.money).map((m) => m.key))

/** 金额格式化（与旧 Bi.vue 一致：$ 前缀，原值直出）。 */
export function formatMetricValue(key, value) {
  if (value === null || value === undefined || value === '') return '—'
  return MONEY_KEYS.has(key) ? `$${value}` : String(value)
}

/**
 * 生成指标卡视图模型：仅输出后端实际返回的键（缺失键不渲染，绝不伪造 0）。
 * @returns {Array<{key,label,value,display,caliber,distinction}>}
 */
export function metricCardList(metrics = {}) {
  return BI_METRIC_CALIBERS
    .filter((m) => metrics[m.key] !== undefined && metrics[m.key] !== null)
    .map((m) => ({
      key: m.key,
      label: m.label,
      caliber: m.caliber,
      distinction: m.distinction,
      value: metrics[m.key],
      display: formatMetricValue(m.key, metrics[m.key]),
    }))
}
