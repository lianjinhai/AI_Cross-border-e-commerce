/**
 * Factory 空间菜单树（契约 §2.2 → 蓝图 R1 包 3 扩展，/factory/*）。
 *
 * 蓝图 R1 包 3（FP-01/04/05，§B.3 / §2.3）新增子项：
 * - /factory            工厂首页（FP-01，/factory 重定向目标；待办未接→"暂无任务"空态）
 * - /factory/products   产品与产能（FP-02 主入口，保留；catalog+capability 合并展示）
 * - /factory/stocking   备货/贴标任务（FP-04，task projection 待接入→只读队列）
 * - /factory/fulfillment 履约与历史（FP-05，/factory/orders 待接入→占位）
 * - /factory/capability 报价与供货能力（FP-03，由 products 拆出的只读能力视图）
 *
 * 待接入（§F#3/#5）——**只读骨架，不放可点击写入口**：
 * - 平台订单 /factory/orders —— backend factory_network 端点未核实（FP-05 占位）
 * - 结算查看 /factory/settlements —— backend factory_network 端点未核实（FP-05 占位）
 * 来源：FRONTEND_V9_NAVIGATION.md §3 + 蓝图 R1 §5.18。
 * 安全约束（蓝图 §9）：不展示卖家平台核价/安全底价/GMV/真实贡献利润。
 */
export const FACTORY_DOMAINS = [
  {
    key: 'factory',
    label: '工厂门户',
    icon: 'OfficeBuilding',
    children: [
      { path: '/factory', label: '工厂首页', icon: 'Odometer' },
      { path: '/factory/products', label: '产品与产能', icon: 'OfficeBuilding' },
      { path: '/factory/stocking', label: '备货/贴标', icon: 'List' },
      { path: '/factory/fulfillment', label: '履约与历史', icon: 'Document' },
      { path: '/factory/capability', label: '报价与供货能力', icon: 'TrendCharts' },
    ],
  },
]
