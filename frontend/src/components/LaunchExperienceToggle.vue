<template>
  <div class="toggle">
    <el-radio-group :model-value="modelValue" size="small" @change="onChange">
      <el-radio-button value="GUIDED">业务视图</el-radio-button>
      <el-radio-button value="PROFESSIONAL">专业视图</el-radio-button>
    </el-radio-group>
    <span class="hint">临时切换，不代表授权变更；刷新后回到默认「{{ effectiveLabel }}」</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: 'GUIDED' },
  effective: { type: String, default: 'GUIDED' },
})
const emit = defineEmits(['update:modelValue'])

const LABELS = { GUIDED: '业务视图', PROFESSIONAL: '专业视图' }
const effectiveLabel = computed(() => LABELS[props.effective] || props.effective)

function onChange(value) {
  emit('update:modelValue', value)
}
</script>

<style scoped>
.toggle { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.hint { color: #909399; font-size: 12px; }
</style>
