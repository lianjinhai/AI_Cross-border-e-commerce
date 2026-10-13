/**
 * Factory 空间菜单树（契约 §2.2：1 项 + 2 待接入注释占位，/factory/*）。
 *
 * 待接入（factory_network 其余端点未核，**不放入口**，接入前禁止出现可点击项）：
 * - 平台订单 /factory/orders —— backend factory_network 端点未核实
 * - 结算查看 /factory/settlements —— backend factory_network 端点未核实
 * 来源：FRONTEND_V9_NAVIGATION.md §3。
 */
export const FACTORY_DOMAINS = [
  {
    key: 'factory',
    label: '工厂门户',
    icon: 'OfficeBuilding',
    children: [
      { path: '/factory/products', label: '产品与产能', icon: 'OfficeBuilding' },
    ],
  },
]
