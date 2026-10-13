<template>
  <div class="advanced-filter">
    <div class="advanced-filter__fields">
      <slot />
    </div>
    <div v-if="savedViewsKey" class="advanced-filter__views">
      <el-select
        v-model="selectedView" size="small" clearable placeholder="保存的视图"
        style="width: 160px" @change="onPickView"
      >
        <el-option v-for="v in views" :key="v.name" :label="v.name" :value="v.name" />
      </el-select>
      <el-button size="small" :disabled="!selectedView" @click="onSaveView">更新视图</el-button>
      <el-button size="small" :disabled="!selectedView" type="danger" plain @click="onDeleteView">删除视图</el-button>
      <el-button size="small" @click="onNewView">存为视图</el-button>
    </div>
  </div>
</template>

<script setup>
/**
 * 筛选区（V9 第 2 批，设计系统 §2）：字段组（默认插槽）+ 保存视图（localStorage）。
 * savedViewsKey 为视图命名空间；视图 CRUD 经 composables/launchViews.js 纯函数。
 */
import { onMounted, ref } from 'vue'
import { ElMessageBox } from '../shared/ui'
import {
  applyView, deleteView, loadViews, saveView,
} from '../composables/launchViews'

const props = defineProps({
  savedViewsKey: { type: String, default: '' },
  // 当前筛选快照（存为视图用）。
  filters: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['apply-filters'])

const views = ref([])
const selectedView = ref('')

onMounted(() => { views.value = loadViews() })

function onPickView(name) {
  const view = views.value.find((v) => v.name === name)
  if (view) emit('apply-filters', applyView(view))
}

async function onNewView() {
  try {
    const { value } = await ElMessageBox.prompt('给这套筛选起个名字', '保存视图', {
      inputValidator: (v) => !!v?.trim() || '视图名不能为空',
    })
    views.value = saveView(value.trim(), props.filters)
    selectedView.value = value.trim()
  } catch { /* 取消 */ }
}

function onSaveView() {
  const view = views.value.find((v) => v.name === selectedView.value)
  if (!view) return
  views.value = saveView(view.name, props.filters)
}

async function onDeleteView() {
  try {
    await ElMessageBox.confirm(`删除视图「${selectedView.value}」？`, '提示', { type: 'warning' })
  } catch { return }
  views.value = deleteView(selectedView.value)
  selectedView.value = ''
}
</script>

<style scoped>
.advanced-filter {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.advanced-filter__fields {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
  flex: 1;
}
.advanced-filter__views {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}
</style>
