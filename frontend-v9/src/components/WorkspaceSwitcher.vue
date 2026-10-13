<template>
  <el-select
    :model-value="activeId"
    size="small"
    class="workspace-switcher__select"
    placeholder="切换工作区"
    @change="onChange"
  >
    <el-option
      v-for="item in options"
      :key="item.id"
      :label="item.name"
      :value="item.id"
    />
  </el-select>
</template>

<script setup>
/**
 * 工作区切换器（契约 §2.4 → 蓝图 R1 P0 扩展）。
 *
 * 新增：
 * - creating prop：是否有"新建空间"项
 * - create 事件：跳 ONB-01 /onboarding?step=1
 * - 切换时同步清 localStorage v9_selected_shop + 旧 Context（复用 shared/workspace.js clearWorkspaceContext）
 * 纯函数源：shared/workspaceSwitcher.js（buildSwitcherOptions / clearOnSwitch / isCreateOption）。
 */
import { computed } from 'vue'
import { buildSwitcherOptions, clearOnSwitch, isCreateOption } from '../shared/workspaceSwitcher'
import { clearWorkspaceContext } from '../shared/workspace'

const props = defineProps({
  workspaces: { type: Array, default: () => [] },
  activeId: { type: [String, Number], default: '' },
  /** 是否显示"新建空间"项。 */
  creating: { type: Boolean, default: false },
})

const emit = defineEmits(['switch', 'create'])

const options = computed(() => buildSwitcherOptions(props.workspaces, props.creating))

function onChange(workspaceId) {
  if (workspaceId === props.activeId) return
  if (workspaceId === '__create__' || isCreateOption({ id: workspaceId })) {
    emit('create')
    return
  }
  // 切换时清 localStorage 旧选中店铺 + 旧 Context（epoch 比对由 workspace.js 内部处理）
  const keys = clearOnSwitch()
  keys.forEach((key) => {
    try { localStorage.removeItem(key) } catch { /* noop */ }
  })
  clearWorkspaceContext()
  emit('switch', workspaceId)
}
</script>

<style scoped>
.workspace-switcher__select {
  width: 180px;
}
</style>
