<template>
  <div class="page">
    <PageHeader title="我的待办" subtitle="统一任务列表 · 一条业务事项只出现一次">
      <template #filters>
        <div class="filters">
          <el-radio-group :model-value="filters.view" size="small" @change="onViewChange">
            <el-radio-button v-for="v in views" :key="v.key" :value="v.key">
              {{ v.label }}（{{ fmtCount(tabCounts[v.key]) }}）
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

    <!-- 任务三计数（与顶栏上下文条、工作台卡同口径，单一事实源 deriveWorkbenchCounts） -->
    <div class="counter-strip" data-testid="task-center-counters">
      <span class="counter-strip__item">
        <b class="counter-strip__num">{{ fmtCount(canonical.todo) }}</b><span>待我处理</span>
      </span>
      <span class="counter-strip__item">
        <b class="counter-strip__num">{{ fmtCount(canonical.waiting) }}</b><span>等待外部</span>
      </span>
      <span class="counter-strip__item">
        <b class="counter-strip__num counter-strip__num--warn">{{ fmtCount(canonical.blocked) }}</b><span>被阻断</span>
      </span>
      <span class="counter-strip__hint">（与顶栏、工作台同口径 · 缺失显示「—」不当 0）</span>
    </div>

    <PartialBanner v-if="unavailable.length" class="mb16" :missing="unavailable" />
    <ErrorState v-if="error" class="mb16" :message="error" @retry="fetchAll" />

    <SectionState :code="activeCode" @action="onStateAction" @retry="fetchAll" :error="error">
      <div v-if="activeCode === 'ready'" class="task-center__body">
        <div class="task-center__scroll">
          <el-table :data="visibleTasks" size="small" row-key="id" class="task-center__table">
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
        </div>
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
import { deriveWorkbenchCounts } from '../../shared/workbenchContext'
import {
  TASK_VIEWS, buildTaskHref, filterTasks, filtersFromQuery, normalizeTasks, queryFromFilters, viewCounts,
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
const normalized = computed(() => normalizeTasks({ todo: todo.value, overview: overview.value }))
const unavailable = computed(() => normalized.value.unavailable)
const visibleTasks = computed(() => filterTasks(normalized.value.tasks, filters.value))
/**
 * 计数口径（R3-2B 语义统一）：等待外部 / 被阻断 直接复用**与顶栏、工作台同一**的
 * `deriveWorkbenchCounts`（值可为 null → 渲染「—」）；「全部待办」/「已完成」按列表
 * 实际行数。三方「待我处理/等待外部/被阻断」由此保证一致。
 */
const canonical = computed(() => deriveWorkbenchCounts(overview.value))
const tabCounts = computed(() => {
  const vc = viewCounts(normalized.value.tasks)
  return {
    todo: vc.todo,
    waiting: canonical.value.waiting,
    blocked: canonical.value.blocked,
    done: vc.done,
  }
})
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
/** 计数展示：null/undefined（不可得）→ 「—」，0 正常显示（不当 0 掩盖）。 */
function fmtCount(value) {
  return value === null || value === undefined ? '—' : String(value)
}

/** 处理任务：跳目标页并带 return_to（bug4 修复：URL 感知合并，不重复追加；保留当前筛选）。 */
function openTask(task) {
  if (!task.link) return
  // 用**逻辑（未编码）**的当前待办位置作为 return_to，由 buildTaskHref 统一编码，
  // 避免「已编码再编码」的双重转义；已存在的 return_to 会被覆盖为唯一值。
  const parts = Object.entries(route.query)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${String(v)}`)
  const returnTo = route.path + (parts.length ? `?${parts.join('&')}` : '')
  const href = buildTaskHref(task.link, returnTo)
  if (href) router.push(href)
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
.page { min-width: 0; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.counter-strip {
  display: flex; flex-wrap: wrap; align-items: center; gap: 20px;
  margin-bottom: 16px; padding: 8px 12px;
  background: var(--color-info-bg); border-radius: var(--radius-base, 6px);
}
.counter-strip__item { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.counter-strip__num { font-size: 18px; font-weight: var(--font-weight-medium, 600); color: var(--color-text); }
.counter-strip__num--warn { color: var(--color-warning); }
.counter-strip__hint { color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.task-title { margin-left: 8px; }
.ml8 { margin-left: 8px; }
.muted { color: var(--color-text-disabled); font-size: var(--font-size-xs); }
.gap-note { margin-top: 8px; color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.mb16 { margin-bottom: 16px; }
/* 窄屏：表格横向滚动，不挤压竖排；容器不横向溢出 */
.task-center__scroll { width: 100%; overflow-x: auto; }
.task-center__table { min-width: 760px; }
@media (max-width: 768px) {
  .counter-strip { gap: 12px; }
  .filters { width: 100%; }
  .filters :deep(.el-input),
  .filters :deep(.el-select) { width: 100% !important; }
}
</style>
