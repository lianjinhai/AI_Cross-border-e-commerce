<template>
  <div class="page">
    <PageHeader title="我的待办" subtitle="统一任务列表 · 一条业务事项只出现一次">
      <template #filters>
        <div class="filters">
          <el-radio-group :model-value="filters.view" size="small" @change="onViewChange">
            <el-radio-button v-for="v in views" :key="v.key" :value="v.key">
              {{ v.label }}<span v-if="counts[v.key] != null">（{{ counts[v.key] }}）</span>
            </el-radio-button>
          </el-radio-group>
          <el-input :model-value="filters.product" size="small" placeholder="商品" clearable style="width:130px"
            @change="(val) => onFilter('product', val)" />
          <el-input :model-value="filters.store" size="small" placeholder="店铺" clearable style="width:130px"
            @change="(val) => onFilter('store', val)" />
          <el-select :model-value="filters.type" size="small" placeholder="类型" clearable style="width:130px"
            @change="(val) => onFilter('type', val)">
            <el-option label="上线流程" value="launch" />
            <el-option label="待审批动作" value="action" />
            <el-option label="风险告警" value="alert" />
            <el-option label="人工复核" value="review" />
            <el-option label="AI 运行" value="ai_run" />
          </el-select>
          <el-select :model-value="filters.due" size="small" placeholder="期限" clearable style="width:120px"
            @change="(val) => onFilter('due', val)">
            <el-option label="已逾期" value="overdue" />
            <el-option label="7 天内" value="soon" />
            <el-option label="无截止" value="none" />
          </el-select>
        </div>
      </template>
    </PageHeader>

    <PartialBanner v-if="unavailable.length" class="mb16" :missing="unavailable" />
    <ErrorState v-if="error" class="mb16" :message="error" @retry="fetchAll" />

    <SectionState :code="activeCode" @action="onStateAction" @retry="fetchAll" :error="error">
      <div v-if="activeCode === 'ready'" class="task-center__body">
        <el-table :data="visibleTasks" size="small" row-key="id">
          <el-table-column label="任务" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tag size="small" :type="severityTag(row.severity)">{{ severityLabel(row.severity) }}</el-tag>
              <span class="task-title">{{ row.title }}</span>
              <el-badge v-if="row.count" :value="row.count" type="primary" class="ml8" />
              <el-badge v-else-if="row.mergedCount > 1" :value="`x${row.mergedCount}`" type="info" class="ml8" />
            </template>
          </el-table-column>
          <el-table-column label="商品 / 对象" min-width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ row.object }}</template>
          </el-table-column>
          <el-table-column label="店铺" width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.store }}</template>
          </el-table-column>
          <el-table-column label="原因" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.reason }}</template>
          </el-table-column>
          <el-table-column label="责任人" width="100">
            <template #default="{ row }">{{ row.owner }}</template>
          </el-table-column>
          <el-table-column label="时间" width="160">
            <template #default="{ row }">{{ row.time }}</template>
          </el-table-column>
          <el-table-column label="来源" width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ row.sources.join('、') }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.link" link type="primary" size="small" @click="openTask(row)">处理</el-button>
              <span v-else class="muted">无入口</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="gapNotes.length" class="gap-note">
          缺口说明：{{ gapNotes.join('；') }}
        </div>
      </div>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 待办中心（R3-2B §2/§3）：统一任务列表 + 视图切换 + URL 筛选 + 去重（含 store 维度）。
 * 消费 GET /workbench/todo（分组摘要）+ GET /workbench/overview（进行中/已完成明细）。
 * 红线：不捏造明细实例；来源失败显示部分可用/未知；缺失显示「—」不当 0。
 * 处理入口保留 return_to（回跳原筛选位置，§3 闭环）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import ErrorState from '../../components/ErrorState.vue'
import PartialBanner from '../../features/home/PartialDataBanner.vue'
import { fetchOverview, fetchTodo } from '../../api/domains/workbench'
import {
  TASK_VIEWS, filterTasks, filtersFromQuery, normalizeTasks, queryFromFilters, viewCounts,
} from '../../shared/taskCenterView'

const route = useRoute()
const router = useRouter()

const todo = ref({})
const overview = ref({})
const loading = ref(false)
const error = ref('')
const views = TASK_VIEWS

/** 筛选/视图的单一事实源 = URL query（浏览器返回可恢复，§3）。 */
const filters = computed(() => filtersFromQuery(route.query))
const counts = computed(() => viewCounts(normalized.value.tasks))
const normalized = computed(() => normalizeTasks({ todo: todo.value, overview: overview.value }))
const unavailable = computed(() => normalized.value.unavailable)
const visibleTasks = computed(() => filterTasks(normalized.value.tasks, filters.value))
const gapNotes = computed(() => {
  const notes = new Set()
  for (const t of visibleTasks.value) for (const g of t.gaps || []) notes.add(g)
  return [...notes]
})

const activeCode = computed(() => {
  if (error.value) return 'ERROR'
  if (loading.value && normalized.value.tasks.length === 0) return 'LOADING'
  if (visibleTasks.value.length === 0 && hasActiveFilter.value) return 'EMPTY_FILTER'
  if (visibleTasks.value.length === 0) return 'EMPTY_NEW'
  return 'ready'
})
const hasActiveFilter = computed(() => {
  const f = filters.value
  return Boolean(f.product || f.store || f.type || f.due) || f.view !== 'todo'
})

/** 写 URL：push（保留历史，浏览器返回可恢复上一筛选态，§3）。 */
function pushFilters(patch) {
  const merged = { ...filters.value, ...patch }
  router.push({ path: route.path, query: queryFromFilters(merged) })
}

function onViewChange(view) {
  pushFilters({ view })
}
function onFilter(key, value) {
  pushFilters({ [key]: value || '' })
}
function onStateAction(code) {
  if (code === 'EMPTY_FILTER') router.push({ path: route.path, query: {} })
}

function severityLabel(sev) {
  return { high: '高', mid: '中', low: '低' }[sev] || '低'
}
function severityTag(sev) {
  return { high: 'danger', mid: 'warning', low: 'info' }[sev] || 'info'
}

/** 处理任务：跳目标页并带 return_to（保留当前筛选，§3 返回原位置）。 */
function openTask(task) {
  if (!task.link) return
  const returnTo = `${route.path}${Object.keys(route.query).length ? '?' + new URLSearchParams(route.query).toString() : ''}`
  const sep = task.link.includes('?') ? '&' : '?'
  router.push(`${task.link}${sep}return_to=${encodeURIComponent(returnTo)}`)
}

async function fetchAll() {
  loading.value = true
  error.value = ''
  try {
    const [td, ov] = await Promise.all([fetchTodo(), fetchOverview()])
    todo.value = td || {}
    overview.value = ov || {}
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
.filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.task-title { margin-left: 8px; }
.ml8 { margin-left: 8px; }
.muted { color: var(--color-text-disabled); font-size: var(--font-size-xs); }
.gap-note { margin-top: 8px; color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.mb16 { margin-bottom: 16px; }
</style>
