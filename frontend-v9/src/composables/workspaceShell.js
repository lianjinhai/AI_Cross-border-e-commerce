import { computed, onMounted, onUnmounted, ref } from 'vue'
import { buildDomains } from '../shared/navigation/filter'
import { defaultLanding } from '../permissions/permissions'
import {
  clearWorkspaceContext,
  getContext,
  getWorkspaceEpoch,
  loadWorkspaces,
  subscribeWorkspaceChange,
  switchWorkspace,
  workspaceId,
  workspaceName as contextWorkspaceName,
} from '../shared/workspace'
import { isAllShops, toShellShop } from '../shared/storeScope'
import { restoreImpersonation } from './impersonation'
import { fetchShops } from '../api/domains/shops'
import { useWorkbenchCounts } from './workbenchCounts'

/**
 * 店铺范围是**全壳单一事实**：壳顶栏切换器写、业务页读。
 * 若每次调用 useWorkspaceShell() 都新建 ref，页面拿到的是挂载时的快照，
 * 切换店铺后页面成本口径不会重算（B3 实测缺陷）。
 * 故此处提升为模块级共享状态（持久化仍以 localStorage `v9_selected_shop` 为准）。
 */
const selectedShopId = ref(
  (typeof localStorage !== 'undefined' && localStorage.getItem('v9_selected_shop')) || '')

/**
 * Workspace 薄壳数据装配（契约 §2.1 的壳外下沉，保持薄壳 ≤60 行）。
 * 导航与 Context 响应式联动（getContext 读取即建立依赖）；禁止新写 Context
 * 获取逻辑或第二份 axios 实例（一律 shared/workspace.js + api/domains 平移件）。
 *
 * R3-2A：新增顶栏上下文条数据（Workspace 名称 / 店铺范围 / 任务三计数），
 * 供 ShellContextBar 消费；计数来自 useWorkbenchCounts（复用只读 overview）。
 */
export function useWorkspaceShell() {
  const workspaces = ref([])
  const shops = ref([])

  const impersonating = computed(() =>
    Boolean(getContext()?.is_impersonating) || Boolean(localStorage.getItem('erp_impersonating')))
  const readOnly = computed(() => getContext()?.role === 'READ_ONLY' || !getContext())
  const activeWorkspaceId = computed(() => workspaceId())

  const navigation = computed(() => buildDomains({
    roleKey: getContext()?.role || '',
    canManageMembers: (getContext()?.permissions || []).includes('workspace:member:admin'),
    isImpersonating: impersonating.value,
  }))

  // ── 顶栏上下文条（R3-2A） ──────────────────────────────────────────────
  const workspaceName = computed(() => contextWorkspaceName())
  const shopScope = computed(() => {
    if (isAllShops(selectedShopId.value)) return '全部店铺'
    const hit = (shops.value || []).find((s) => String(s?.id) === String(selectedShopId.value))
    return hit?.name || '全部店铺'
  })
  const { counts, unavailable: countsUnavailable } = useWorkbenchCounts()

  // 丢弃过期快照：在途响应回来时 epoch 已变则不写回（getWorkspaceEpoch 约定）。
  async function loadShops() {
    const myEpoch = getWorkspaceEpoch()
    try {
      const data = await fetchShops()
      if (myEpoch === getWorkspaceEpoch()) {
        const items = Array.isArray(data?.items) ? data.items : []
        // DTO 适配唯一入口：shop_name/role → name/type（否则下拉框只剩 id、货源店铺混入销售店铺）。
        shops.value = items.map(toShellShop).filter(Boolean)
      }
    } catch { shops.value = [] }
  }

  async function onSwitchWorkspace(id) {
    const ok = await switchWorkspace(id)
    if (ok) window.location.assign(defaultLanding())
  }

  function exitImpersonate() {
    // 退出代客：还原平台 token/user 快照（impersonation 模块），Context 清缓存后重拉。
    restoreImpersonation()
    clearWorkspaceContext()
    window.location.assign('/console/overview')
  }

  // selectedShopId 为模块级共享状态（见文件头）：此处不再重置，
  // 否则页面挂载会用旧的 localStorage 快照覆盖掉刚切换的店铺范围。

  let unsubscribe = () => {}
  onMounted(async () => {
    workspaces.value = await loadWorkspaces()
    await loadShops()
    unsubscribe = subscribeWorkspaceChange(() => { loadShops() })
  })
  onUnmounted(() => unsubscribe())

  return {
    workspaces, shops, selectedShopId, impersonating, readOnly,
    activeWorkspaceId, navigation, onSwitchWorkspace, exitImpersonate,
    // R3-2A 顶栏上下文条
    workspaceName, shopScope, counts, countsUnavailable,
  }
}
