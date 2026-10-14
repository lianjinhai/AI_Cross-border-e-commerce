/**
 * 导航数据结构约定（契约 §2.2，纯数据契约，非运行时代码）。
 *
 * 域：{ key:string, label:string, icon:string, collapsible?:boolean, children:NavChild[] }
 * NavChild：{ path:string, label:string, icon:string, hidden?:boolean, badge?:'approvals'|'alerts'|'tasks' }
 * - icon 一律 @element-plus/icons-vue 组件名（main.js 全局注册的现网约定）；
 * - hidden=参数详情等不入侧栏的子路由（/app/products/:id 等，路由化但不在树内）；
 * - badge 取已接端点计数（approvals→/actions、alerts→/alerts、tasks→/workbench/todo），
 *   未接计数前不下发。
 * - collapsible（R3-2A 新增，可选，向后兼容）：true → 侧栏以 el-sub-menu 折叠渲染该入口
 *   （仅「全部工具」tools 使用）；缺省/false → 沿用「分组标题 + 平铺叶子」渲染。
 *
 * 三份菜单源：workspace-navigation.js（R3-2A 4+1 入口：mybiz/goods/orders/revenue/tools）/
 * console-navigation.js（4 项 + R1 包 3 项）/ factory-navigation.js（home + products + 3 项）。
 * 角色过滤统一走 filter.js（buildDomains / whitelistForRole），
 * 禁止各树自带过滤逻辑（禁止双事实源）。
 */

/** NavChild 允许的 badge 取值（已接端点计数语义，见 FRONTEND_V9_NAVIGATION.md §1）。 */
export const NAV_BADGES = ['approvals', 'alerts', 'tasks']

/** R3-2A 4+1 入口 key（顺序即侧栏渲染顺序：4 高频入口 + 工具柜）。 */
export const WORKSPACE_ENTRY_KEYS = ['mybiz', 'goods', 'orders', 'revenue', 'tools']

/** 可折叠（工具柜）入口 key。 */
export const WORKSPACE_COLLAPSIBLE_KEYS = ['tools']
