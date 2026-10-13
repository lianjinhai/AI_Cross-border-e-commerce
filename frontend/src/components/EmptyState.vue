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
 * 空态（UX-01）：按 `reason` 给出统一标题，可附 `hint` 说明与 `#action` 按钮插槽。
 * 标题映射见 docs/FRONTEND_DESIGN_SYSTEM.md §3（EmptyState）。
 */
import { computed } from 'vue'

const REASON_TITLE_MAP = {
  NO_DATA: '暂无数据',
  NO_PERMISSION: '无访问权限',
  NOT_CONFIGURED: '尚未配置',
  NO_MATCH: '没有匹配结果',
  REQUEST_FAILED: '加载失败',
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
