import { computed, onMounted, onUnmounted, ref } from 'vue'
import { loadOverview } from './workbenchTodo'
import { getWorkspaceEpoch, subscribeWorkspaceChange } from '../shared/workspace'
import { deriveWorkbenchCounts, isCountsUnavailable } from '../shared/workbenchContext'

/**
 * 顶栏任务计数条数据装配（R3-2A，baseline §3.2）。
 *
 * 复用既有只读 BFF `loadOverview`（workbenchTodo.js，**不新造第二个 overview 调用**），
 * 用 `deriveWorkbenchCounts`（shared/workbenchContext.js）派生三计数。
 *
 * 陈旧响应防护（baseline §3.1「切换 Workspace 取消旧请求、迟到响应不覆盖新空间」）：
 * 每次请求记录发起时的 `getWorkspaceEpoch()`，回写前比对；epoch 已变（切换/登出/401）
 * 则丢弃。卸载后再回写亦丢弃（cancelled 标记）。
 *
 * 降级红线：请求失败或源不可得 → 三计数置 `null`（渲染为「—」），**绝不当 0**；
 * 订阅 Context 变更后在切空间完成时自动重取。
 *
 * @returns {{counts: import('vue').Ref<{todo:*,waiting:*,blocked:*}>, unavailable: import('vue').ComputedRef<boolean>, reload: () => Promise<void>}}
 */
export function useWorkbenchCounts() {
  const counts = ref({ todo: null, waiting: null, blocked: null })
  let cancelled = false

  const unavailable = computed(() => isCountsUnavailable(counts.value))

  async function reload() {
    const myEpoch = getWorkspaceEpoch()
    try {
      const data = await loadOverview({ limit: 1 })
      if (cancelled || myEpoch !== getWorkspaceEpoch()) return
      counts.value = deriveWorkbenchCounts(data)
    } catch {
      if (cancelled || myEpoch !== getWorkspaceEpoch()) return
      // 失败不得当 0：置 null → 视图渲染「—」。
      counts.value = { todo: null, waiting: null, blocked: null }
    }
  }

  let unsubscribe = () => {}
  onMounted(() => {
    reload()
    // Context 变更（切空间/登出）后重取，保持顶栏与当前空间一致。
    unsubscribe = subscribeWorkspaceChange(() => { reload() })
  })
  onUnmounted(() => {
    cancelled = true
    unsubscribe()
  })

  return { counts, unavailable, reload }
}
