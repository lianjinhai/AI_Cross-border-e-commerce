<template>
  <el-tag :type="resolved.type" :size="size">{{ resolved.label }}</el-tag>
</template>

<script setup>
/**
 * 状态标签（UX-01）：统一以「文字 + 颜色」表达状态，禁止仅靠颜色区分。
 * 数据来自纯函数 `resolveStatusTag`，行为与原 `RunStatus.vue` 完全一致。
 */
import { computed } from 'vue'
import { resolveStatusTag } from '../composables/statusDict'

const props = defineProps({
  status: { type: String, default: '' },
  table: { type: String, default: 'run' },
  size: { type: String, default: 'small' },
})

const resolved = computed(() => resolveStatusTag(props.status, props.table))
</script>
