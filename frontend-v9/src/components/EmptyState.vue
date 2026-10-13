<template>
  <el-empty :description="title">
    <p v-if="hint" class="empty-state__hint">{{ hint }}</p>
    <div class="empty-state__action">
      <slot name="action" />
    </div>
  </el-empty>
</template>

<script setup>
/**
 * 空态（V9 第 1 批，EmptyState 家族）：按 `reason` 给出统一标题，
 * 可附 `hint` 说明与 `#action` 按钮插槽。
 * V9 起 NoPermissionState/NotConfiguredState/WaitingExternalState 的语义并入
 * 本组件 reason 枚举（设计系统 §2），不再单设组件。
 */
import { computed } from 'vue'

const REASON_TITLE_MAP = {
  NO_DATA: '暂无数据',
  NO_PERMISSION: '无访问权限',
  NOT_CONFIGURED: '尚未配置',
  NO_MATCH: '没有匹配结果',
  REQUEST_FAILED: '加载失败',
  WAITING_EXTERNAL: '等待外部反馈',
}

const props = defineProps({
  reason: { type: String, default: 'NO_DATA' },
  hint: { type: String, default: '' },
})

const title = computed(() => REASON_TITLE_MAP[props.reason] || REASON_TITLE_MAP.NO_DATA)
</script>

<style scoped>
.empty-state__hint {
  margin: 0 0 8px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
.empty-state__action {
  margin-top: 8px;
}
</style>
