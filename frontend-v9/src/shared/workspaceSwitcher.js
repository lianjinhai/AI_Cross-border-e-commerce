/**
 * WorkspaceSwitcher 纯函数（蓝图 §6.4，包 1 P0 共享组件扩展纯函数下沉）。
 *
 * 切换时同步清 localStorage v9_selected_shop + 旧 Context；
 * "新建空间"项 → create()（跳 ONB-01 /onboarding?step=1）。
 */

/**
 * 构建切换器选项列表。
 * - workspaces 原样透传
 * - creating=true 时末尾追加 { id: '__create__', name: '新建空间', isCreate: true }
 *
 * @param {Array<{id:string|number, name:string}>} workspaces 空间列表。
 * @param {boolean} [creating] 是否显示"新建空间"项。
 * @returns {Array<{id:string|number, name:string, isCreate?:boolean}>}
 */
export function buildSwitcherOptions(workspaces, creating = false) {
  const options = Array.isArray(workspaces)
    ? workspaces.map((ws) => ({ id: ws.id, name: ws.name }))
    : []
  if (creating) {
    options.push({ id: '__create__', name: '新建空间', isCreate: true })
  }
  return options
}

/**
 * 切换成功后需要清理的 localStorage 键 + Context 约定。
 * 返回应删除的键列表（组件层执行 delete）。
 *
 * @returns {string[]} 需清除的 localStorage 键。
 */
export function clearOnSwitch() {
  return ['v9_selected_shop']
}

/**
 * 判定选项是否为"新建空间"（isCreate 标记）。
 *
 * @param {object} option 选项对象。
 * @returns {boolean}
 */
export function isCreateOption(option) {
  return Boolean(option?.isCreate) || option?.id === '__create__'
}
