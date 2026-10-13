<template>
  <el-select
    :model-value="activeId"
    size="small"
    class="workspace-switcher__select"
    placeholder="切换工作区"
    @change="onChange"
  >
    <el-option
      v-for="item in workspaces"
      :key="item.id"
      :label="item.name"
      :value="item.id"
    />
  </el-select>
</template>

<script setup>
/**
 * 工作区切换器（契约 §2.4）：props 驱动（workspaces / activeId），emit switch。
 * 壳内调用 shared/workspace.js 的 switchWorkspace(id)，成功后由
 * subscribeWorkspaceChange 通知刷新；组件内不做任何权限判断。
 */
const props = defineProps({
  workspaces: { type: Array, default: () => [] },
  activeId: { type: [String, Number], default: '' },
})

const emit = defineEmits(['switch'])

function onChange(workspaceId) {
  if (workspaceId === props.activeId) return
  emit('switch', workspaceId)
}
</script>

<style scoped>
.workspace-switcher__select {
  width: 180px;
}
</style>
