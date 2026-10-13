<template>
  <div class="page">
    <PageHeader title="我的待办" subtitle="跨域待办中心 · 按来源域分组">
      <template #filters>
        <el-radio-group v-model="typeFilter" size="small">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="launch">上线流程</el-radio-button>
          <el-radio-button value="action">AI 建议</el-radio-button>
          <el-radio-button value="alert">风险告警</el-radio-button>
          <el-radio-button value="review">人工复核</el-radio-button>
        </el-radio-group>
      </template>
    </PageHeader>

    <SectionState
      :code="activeCode"
      @action="onStateAction"
      @retry="fetchAll"
      :error="error"
    >
      <!-- 11 态：LOADING / EMPTY_NEW / EMPTY_FILTER / NO_PERMISSION / ERROR -->
      <div v-if="activeCode === 'ready'" class="task-center__body">
        <div v-if="groups.length" class="task-center__groups">
          <el-card v-for="group in groups" :key="group.type" class="mb16" shadow="never">
            <template #header>
              <div class="task-center__group-header">
                <span>{{ groupLabel(group.type) }}</span>
                <el-tag size="small" type="info">{{ group.total }}</el-tag>
              </div>
            </template>
            <TaskCard v-for="item in group.items" :key="item.title" :todo="item" />
          </el-card>
        </div>
        <EmptyState v-else reason="NO_DATA" hint="当前没有待办事项" />
      </div>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 任务中心（蓝图 R1 WK-02，P0）：/app/tasks，跨域待办聚合。
 *
 * 数据源：api/domains/workbench.js（fetchTodo → /workbench/todo，已接）。
 * 每页 11 态：LOADING / EMPTY_NEW / EMPTY_FILTER / NO_PERMISSION / PARTIAL_DATA / ERROR
 * 全区块经 SectionState 11 态渲染，文案不页面自写。
 */
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import TaskCard from '../../components/TaskCard.vue'
import EmptyState from '../../components/EmptyState.vue'
import { fetchTodo } from '../../api/domains/workbench'
import { todoGroups, SEVERITY_TAG } from '../../composables/workbenchTodo'

const todo = ref({})
const loading = ref(false)
const error = ref('')
const typeFilter = ref('')

const groups = computed(() => {
  const items = todo.value.items || []
  if (typeFilter.value) return todoGroups(items.filter((i) => i?.type === typeFilter.value))
  return todoGroups(items)
})

/** 11 态派生：SectionState code（空态细分 EMPTY_NEW vs EMPTY_FILTER；内容态='ready'）。 */
const activeCode = computed(() => {
  if (error.value) return 'ERROR'
  if (loading.value) return 'LOADING'
  const items = todo.value.items
  if (!items) return 'NO_PERMISSION'
  if (items.length === 0 && typeFilter.value) return 'EMPTY_FILTER'
  if (items.length === 0) return 'EMPTY_NEW'
  return 'ready'
})

function onStateAction(code) {
  if (code === 'EMPTY_FILTER') {
    typeFilter.value = ''
  } else if (code === 'EMPTY_NEW') {
    // 跳转动作由 SectionState 内置 action 按钮文案承载；本处仅清空筛选
    typeFilter.value = ''
  }
}

function groupLabel(type) {
  const MAP = { launch: '上线流程', action: 'AI 建议待审', alert: '风险告警', review: '人工复核' }
  return MAP[type] || type
}

async function fetchAll() {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchTodo()
    todo.value = data || { items: [] }
  } catch (e) {
    const detail = e?.response?.data?.detail
    error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(fetchAll)
</script>

<style scoped>
.task-center__group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mb16 { margin-bottom: 16px; }
</style>
