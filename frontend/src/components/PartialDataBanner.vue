<template>
  <el-alert type="warning" :closable="false" show-icon :title="title">
    <div class="partial-data__note">{{ note }}</div>
  </el-alert>
</template>

<script setup>
/**
 * 部分数据不可用横幅（UX-04a）：`partial=true` 时明示哪些数据源不可用，
 * 让用户看到「已知范围内」的结果，而不是整页报错或伪造数据。
 */
import { computed } from 'vue'

const props = defineProps({
  missing: { type: Array, default: () => [] },
  note: { type: String, default: '' },
})

const title = computed(() => (props.missing.length
  ? `部分数据不可用：${props.missing.join('、')}`
  : '部分数据暂不可用'))

const note = computed(() => props.note || '以下内容基于当前可用数据源展示，缺失部分不会以默认值替代。')
</script>

<style scoped>
.partial-data__note {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>
