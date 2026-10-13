import { computed, onMounted, onUnmounted, ref } from 'vue'
import { buildDomains } from '../shared/navigation/filter'
import { defaultLanding } from '../permissions/permissions'
import {
  getContext,
  getWorkspaceEpoch,
  loadWorkspaces,
  subscribeWorkspaceChange,
  switchWorkspace,
  workspaceId,
} from '../shared/workspace'
import { fetchShops } from '../api/domains/shops'

/**
 * Workspace 薄壳数据装配（契约 §2.1 的壳外下沉，保持薄壳 ≤60 行）。
 * 导航与 Context 响应式联动（getContext 读取即建立依赖）；禁止新写 Context
 * 获取逻辑或第二份 axios 实例（一律 shared/workspace.js + api/domains 平移件）。
 */
export function useWorkspaceShell() {
  const workspaces = ref([])
  const shops = ref([])
  const selectedShopId = ref('')

  const impersonating = computed(() =>
    Boolean(getContext()?.is_impersonating) || Boolean(localStorage.getItem('erp_impersonating')))
  const readOnly = computed(() => getContext()?.role === 'READ_ONLY' || !getContext())
  const activeWorkspaceId = computed(() => workspaceId())

  const navigation = computed(() => buildDomains({
    roleKey: getContext()?.role || '',
    canManageMembers: (getContext()?.permissions || []).includes('workspace:member:admin'),
    isImpersonating: impersonating.value,
  }))

  // 丢弃过期快照：在途响应回来时 epoch 已变则不写回（getWorkspaceEpoch 约定）。
  async function loadShops() {
    const myEpoch = getWorkspaceEpoch()
    try {
      const data = await fetchShops()
      if (myEpoch === getWorkspaceEpoch()) shops.value = Array.isArray(data?.items) ? data.items : []
    } catch { shops.value = [] }
  }

  async function onSwitchWorkspace(id) {
    const ok = await switchWorkspace(id)
    if (ok) window.location.assign(defaultLanding())
  }

  function exitImpersonate() {
    localStorage.removeItem('erp_impersonating')
    window.location.assign('/console/overview')
  }

  // selectedShopId 初值来自 localStorage 记忆（StoreSwitcher 负责回写）。
  selectedShopId.value = localStorage.getItem('v9_selected_shop') || ''

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
  }
}
