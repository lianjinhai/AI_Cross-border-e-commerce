<template>
  <div class="shell-context" data-testid="shell-context-bar">
    <!-- 1) 当前 Workspace + 当前店铺范围（持续可见） -->
    <span class="shell-context__scope" :title="scopeTitle">
      <el-icon class="shell-context__scope-icon"><OfficeBuilding /></el-icon>
      <span class="shell-context__ws">{{ workspaceLabel }}</span>
      <span class="shell-context__sep">·</span>
      <el-icon class="shell-context__scope-icon"><Shop /></el-icon>
      <span class="shell-context__shop">{{ shopScope }}</span>
    </span>

    <!-- 2) 小型计数条：待我处理 / 等待外部 / 被阻断（不可得 → 「—」，不当 0） -->
    <span class="shell-context__counts" data-testid="shell-context-counts">
      <span
        v-for="chip in chips"
        :key="chip.key"
        class="shell-context__chip"
        :class="{ 'shell-context__chip--muted': chip.value === null }"
        :title="chip.title"
      >
        <el-icon class="shell-context__chip-icon"><component :is="chip.icon" /></el-icon>
        <span class="shell-context__chip-label">{{ chip.label }}</span>
        <b class="shell-context__chip-value">{{ chip.text }}</b>
      </span>
    </span>
  </div>
</template>

<script setup>
/**
 * 顶栏上下文条（AppShell 子件，baseline §3）：始终让用户知道操作作用于哪里。
 *  1. 当前 Workspace + 当前店铺范围（无 Context / 未选店 → 「全部店铺」）；
 *  2. 任务提醒三计数（待我处理 / 等待外部 / 被阻断），不可得渲染「—」；
 * 数据由调用方（WorkspaceShell）经 useWorkspaceShell 装配，本组件纯展示、无副作用。
 */
import { computed } from 'vue'
import { formatCount } from '../shared/workbenchContext'

const props = defineProps({
  /** 当前 Workspace 名称；空 → 展示占位。 */
  workspaceName: { type: String, default: '' },
  /** 当前店铺范围（如「全部店铺」或具体店铺名）。 */
  shopScope: { type: String, default: '全部店铺' },
  /** 三计数：{ todo, waiting, blocked }，值可为 null（不可得）。 */
  counts: { type: Object, default: () => ({ todo: null, waiting: null, blocked: null }) },
})

const workspaceLabel = computed(() => props.workspaceName || '当前空间')
const scopeTitle = computed(() => `${workspaceLabel.value} · ${props.shopScope}`)

const chips = computed(() => [
  { key: 'todo', label: '待我处理', icon: 'List', value: normalize(props.counts?.todo), title: '待人工处理的行动与复核' },
  { key: 'waiting', label: '等待外部', icon: 'Clock', value: normalize(props.counts?.waiting), title: '等待外部平台回执的在途流程' },
  { key: 'blocked', label: '被阻断', icon: 'Warning', value: normalize(props.counts?.blocked), title: '被阻断或失败、需人工介入的在途流程' },
].map((chip) => ({ ...chip, text: formatCount(chip.value) })))

/** 归一化计数：仅接受有限数字，其余（含 undefined/NaN）→ null（渲染「—」）。 */
function normalize(value) {
  return (typeof value === 'number' && Number.isFinite(value)) ? value : null
}
</script>

<style scoped>
.shell-context {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.shell-context__scope {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-regular);
  font-size: var(--font-size-sm);
  white-space: nowrap;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.shell-context__scope-icon { font-size: 12px; color: var(--color-text-secondary); }
.shell-context__ws { font-weight: var(--font-weight-medium); }
.shell-context__sep { color: var(--color-text-secondary); }
.shell-context__counts {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.shell-context__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: var(--radius-round);
  background: var(--color-info-bg);
  color: var(--color-text-regular);
  font-size: var(--font-size-sm);
  white-space: nowrap;
}
.shell-context__chip--muted { color: var(--color-text-secondary); }
.shell-context__chip-icon { font-size: 12px; }
.shell-context__chip-label { color: var(--color-text-secondary); }
.shell-context__chip-value { color: var(--color-text); font-weight: var(--font-weight-medium); }
</style>
