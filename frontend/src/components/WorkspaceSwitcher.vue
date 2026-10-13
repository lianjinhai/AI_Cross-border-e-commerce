<template>
  <div v-if="items.length > 1" class="workspace-switcher">
    <el-select
      :model-value="currentId"
      size="small"
      class="workspace-switcher__select"
      placeholder="切换工作区"
      @change="onChange"
    >
      <el-option
        v-for="item in items"
        :key="item.id"
        :label="item.name"
        :value="item.id"
      />
    </el-select>
  </div>
</template>

<script setup>
/**
 * 工作区切换器（UX-01）。
 *
 * 后端 `/me/workspaces` 与 `/me/workspaces/{id}/switch` 封装早已存在于 workspace.js，
 * 但此前全站无 UI 入口，导致「切换工作区」实际不可用。本组件补上入口。
 *
 * 切换成功后整页跳转到 defaultLanding()，以确保菜单/数据/筛选/待办/AI 会话全部
 * 按新工作区重建（不走局部刷新）。切换失败则提示且不改变当前选中。
 * 组件内不做任何权限判断——权限一律走 permissions.js / workspace.js。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from '../ui'
import { defaultLanding } from '../permissions'
import { loadWorkspaces, switchWorkspace, workspaceId } from '../workspace'

const items = ref([])

// 当前选中即当前 Context 的 workspaceId（workspace.js 已响应式，读取即建立依赖）。
// 只读绑定 + 手动 @change：成功切换会整页跳转，失败时不改动此处 → 选中自动回到原值。
const currentId = computed(() => workspaceId())

async function onChange(id) {
  const ok = await switchWorkspace(id)
  if (ok === true) {
    window.location.assign(defaultLanding())
  } else {
    ElMessage.error('切换工作区失败，请重试')
  }
}

onMounted(async () => {
  items.value = await loadWorkspaces()
})
</script>

<style scoped>
.workspace-switcher__select {
  width: 180px;
}
</style>
