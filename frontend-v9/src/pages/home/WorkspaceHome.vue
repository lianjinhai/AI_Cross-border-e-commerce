<template>
  <div class="page">
    <PageHeader title="经营工作台" subtitle="今天需要你处理 · 唯一主任务优先">
      <template #actions>
        <el-tag size="small" type="info">{{ entry.label }}</el-tag>
      </template>
    </PageHeader>

    <!-- 只读 BFF 降级：部分源不可用 → 明示，不整页报错 -->
    <PartialBanner v-if="overview.partial" class="mb16" :missing="missingSourceNames" />
    <ErrorState v-if="error" class="mb16" :message="error" :trace-id="overview.trace_id" @retry="fetchAll" />

    <!-- 顶部小型计数条：待我处理 / 等待外部 / 被阻断（缺失显示 — 不显示 0） -->
    <el-card class="mb16" shadow="never">
      <div class="counters">
        <div class="counter">
          <div class="counter__num">{{ counters.mine }}</div>
          <div class="counter__label">待我处理</div>
        </div>
        <div class="counter">
          <div class="counter__num">{{ counters.waitingExternal }}</div>
          <div class="counter__label">等待外部</div>
        </div>
        <div class="counter">
          <div class="counter__num counter__num--warn">{{ counters.blocked }}</div>
          <div class="counter__label">被阻断</div>
        </div>
      </div>
    </el-card>

    <!-- 顶部问候 + 当前目标行（原型01：一眼看到阶段与下一步） -->
    <div class="home-hero mb16">
      <div class="home-hero__greeting">{{ greetingWord }}</div>
      <div class="home-hero__goal">
        <el-tag size="small" type="primary">{{ stage.label }}</el-tag>
        <span class="home-hero__hint">{{ stage.hint }}</span>
      </div>
    </div>

    <!--
      DESIGN-DIFF（master prompt）：本双栏 2:1 布局（当前任务卡 / 经营条件卡）刻意偏离
      早期「全宽单列任务列」蓝图。取舍：零经验用户首屏只需「一件事 + 诚实经营条件」，
      双栏把「下一步动作」与「会话内经营画像（预算/目标市场/风险偏好）」并置首屏，
      而非把画像藏进折叠区。四层优先级语义完整保留：
        ① 当前任务卡（唯一主任务） ② 优先处理任务（≤3 高优待办）
        ③ 经营阶段→顶部目标行 + 阻断/摘要（左列下方） ④ AI历史+BI明细（折叠）
    -->
    <el-row :gutter="16">
      <!-- 左列（更宽）：第一层唯一主任务 + 第三层阻断/摘要 -->
      <el-col :xs="24" :sm="24" :md="16">
        <!-- 第一层：唯一主任务 -->
        <el-card class="mb16 main-task-card" shadow="never">
          <template #header>
            <div class="between"><span class="card-title">今天最值得完成的一件事</span>
              <span class="scope">按 时限 · 风险 · 责任 排序</span></div>
          </template>
          <SectionState :state="todoState" @retry="fetchAll" empty-hint="当前没有待你处理的任务">
            <template v-if="primaryTask">
              <div class="main-task">
                <el-tag size="small" :type="severityTag(primaryTask.severity)">{{ severityLabel(primaryTask.severity) }}</el-tag>
                <span class="main-task__title">{{ primaryTask.title }}</span>
                <el-badge v-if="primaryTask.count" :value="primaryTask.count" type="primary" />
                <el-button v-if="primaryTask.link" type="primary" @click="go(primaryTask.link)">去处理</el-button>
              </div>
            </template>
            <template v-else>
              <div class="main-task main-task--empty">
                <span class="hint">{{ entry.hint }}</span>
                <el-button type="primary" @click="go(entry.recommended.path)">{{ entry.recommended.text }}</el-button>
              </div>
            </template>
          </SectionState>
        </el-card>

        <!-- 第三层：经营阶段（已上移顶部目标行）+ 阻断 + 真实经营摘要 -->
        <el-card class="mb16" shadow="never">
          <template #header><span class="card-title">当前经营状况</span></template>
          <div v-if="blockers.available && blockers.items.length" class="blocker-list">
            <el-alert v-for="(b, i) in blockers.items" :key="i" type="warning" :closable="false" show-icon
              :title="`${b.product || '商品'} · ${b.store || '店铺'}：${b.message}`" />
          </div>
          <el-alert v-else-if="!blockers.available" type="info" :closable="false" show-icon
            :title="`阻断信息：${blockers.reason}（未知，不作为“无阻断”处理）`" />
          <div class="summary">
            <div v-for="s in summary" :key="s.label" class="summary__cell">
              <div class="summary__label">{{ s.label }}</div>
              <div class="summary__value" :class="{ 'summary__value--missing': s.missing }">{{ s.value }}</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右列（更窄）：经营条件卡（画像服务端持久化 D63，会话层仅兜底） -->
      <el-col :xs="24" :sm="24" :md="8">
        <el-card class="mb16 condition-card" shadow="never">
          <template #header><span class="card-title">经营条件</span></template>
          <div class="condition-rows">
            <div v-for="row in conditionRows" :key="row.key" class="condition-row" :class="{ 'condition-row--missing': row.missing }">
              <span class="condition-row__label">{{ row.label }}</span>
              <template v-if="row.missing">
                <el-link type="primary" :underline="false" @click="go(row.link)">待补 · 去补充</el-link>
              </template>
              <span v-else class="condition-row__value">{{ row.value }}</span>
            </div>
          </div>
          <p class="condition-caption" :class="{ 'condition-caption--draft': !isProfilePersisted }">
            {{ profileCaption }}
          </p>
        </el-card>
      </el-col>
    </el-row>

    <!-- 第二层：最多 3 项高优先级待办（首屏下方，不抢主位） -->
    <el-card class="mb16" shadow="never">
      <template #header>
        <div class="between"><span class="card-title">还需要处理（最多 3 项）</span>
          <el-button link type="primary" size="small" @click="go('/app/tasks')">全部待办 →</el-button></div>
      </template>
      <SectionState :state="todoState" @retry="fetchAll" empty-hint="没有其他高优先级待办">
        <div v-if="highPriority.length" class="task-list">
          <TaskCard v-for="item in highPriority" :key="item.key" :todo="item.raw" />
        </div>
        <EmptyState v-else reason="NO_DATA" hint="没有其他高优先级待办" />
      </SectionState>
    </el-card>

    <!-- 第四层：可展开的 AI 执行历史 + BI 明细（不与待办抢首屏） -->
    <el-collapse class="mb16">
      <el-collapse-item :title="`AI 执行历史（近 24 小时 · ${ai.count ?? '—'}）`">
        <SectionState :state="aiState" @retry="fetchAll" empty-hint="近 24 小时没有已完成的 AI 运行">
          <el-table :data="ai.items" size="small">
            <el-table-column prop="title" label="运行" show-overflow-tooltip />
            <el-table-column prop="finished_at" label="完成时间" width="180" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }"><StatusBadge :status="row.status" /></template>
            </el-table-column>
          </el-table>
        </SectionState>
      </el-collapse-item>
      <el-collapse-item title="完整经营数据（BI 明细 · 近 30 天）">
        <template v-if="biDetail">
          <el-row :gutter="16" class="mb16">
            <el-col :span="16"><div ref="trendRef" class="chart-box" /></el-col>
            <el-col :span="8"><div ref="pieRef" class="chart-box" /></el-col>
          </el-row>
          <el-table :data="biDetail.top_products || []" size="small">
            <el-table-column type="index" width="50" />
            <el-table-column prop="title" label="热销商品" show-overflow-tooltip />
            <el-table-column prop="units" label="销量" width="90" />
            <el-table-column label="销售额" width="150">
              <template #default="{ row }">
                <span>{{ revenueCell(row).display }}</span>
                <span v-if="revenueCell(row).currencyNote" class="currency-note">（{{ revenueCell(row).currencyNote }}）</span>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <EmptyState v-else reason="NO_DATA" hint="经营明细需财务读权限，或暂无数据（缺失不显示为 0）" />
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
/**
 * 经营工作台（R3-2B §1 四层优先级，B2 对齐原型01「我的生意」）：
 *   第一层 唯一主任务 → 第二层 ≤3 高优待办 → 第三层 阶段/阻断/经营摘要 → 第四层 可展开 AI 历史 + BI 明细。
 * B2 重排：顶部问候+目标行；双栏 2:1（当前任务卡 / 经营条件卡）；优先待办下移；AI+BI 折叠。
 * 顶部小型计数条（待我处理/等待外部/被阻断）。画像不同入口不同（确定性规则）。
 * 只读红线：本页只发 GET；partial/源失败用横幅与「—」明示，绝不把错误当空或 0。
 * 经营画像（预算/目标市场/风险偏好）：服务端 GET /business-profile 为权威事实
 * （D63），会话缓存仅作服务端不可用时的草稿兜底；保存状态文案按真实来源渲染。
 * 排序/计数/入口/阶段/条件卡/货币渲染全部在 shared/workspaceHomeView.js 纯函数中，组件只消费。
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import echarts from '../../charts'
import PageHeader from '../../components/PageHeader.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import ErrorState from '../../components/ErrorState.vue'
import TaskCard from '../../components/TaskCard.vue'
import PartialBanner from '../../features/home/PartialDataBanner.vue'
import { fetchOverview, fetchTodo } from '../../api/domains/workbench'
import { fetchTrends as fetchBiTrends } from '../../api/domains/bi'
import { isEmptySection, missingSources, sectionState } from '../../composables/workbenchTodo'
import {
  aiActivity, blockerSummary, businessStage, businessSummary, conditionCardViewModel, entryPlan, formatBiRevenue,
  greeting, pickHighPriority, pickPrimaryTask,
  resolveEntryProfile, taskCounters, taskLink,
} from '../../shared/workspaceHomeView'
import { loadSessionProfile, profileFromServer } from '../../shared/onboardingProfile'
import { fetchBusinessProfile } from '../../api/domains/businessProfile'

const router = useRouter()

const overview = ref({})
const todo = ref({})
const loading = ref(false)
const error = ref('')
const biDetail = ref(null)
const trendRef = ref(null)
const pieRef = ref(null)
const charts = []
const profile = ref(loadSessionProfile())

/** 画像数据来源（诚实文案的唯一事实）：true=服务端已持久化；false=会话草稿。 */
const isProfilePersisted = ref(false)
const profileCaption = computed(() => (isProfilePersisted.value
  ? '已保存到服务器：重新登录或换设备仍可读回'
  : '未保存到服务器：仅在当前浏览器会话内有效，可在「新手引导」补充'))

/** 画像刷新：会话缓存即时上屏 → 服务端读回覆盖（权威事实）；失败保持草稿。 */
async function refreshProfile() {
  profile.value = loadSessionProfile()
  try {
    const serverProfile = profileFromServer(await fetchBusinessProfile())
    if (serverProfile) {
      profile.value = serverProfile
      isProfilePersisted.value = true
      return
    }
  } catch { /* 服务端不可用：保持会话草稿，文案如实标注 */ }
  isProfilePersisted.value = false
}

async function fetchAll() {
  loading.value = true
  error.value = ''
  try {
    const [ov, td] = await Promise.all([fetchOverview(), fetchTodo()])
    overview.value = ov || {}
    todo.value = td || {}
    refreshProfile()
    if (overview.value.sources?.bi === 'ok') await loadBiDetail()
  } catch (e) {
    const detail = e?.response?.data?.detail
    error.value = (detail && typeof detail === 'object' ? detail.message : detail)
      || e?.message || '加载失败，请重试'
  } finally {
    loading.value = false
  }
}

async function loadBiDetail() {
  try {
    const data = await fetchBiTrends()
    biDetail.value = data || {}
    await nextTick()
    renderTrend(data?.sales_trend || [])
    renderPie(data?.category_dist || [])
  } catch {
    biDetail.value = null
  }
}

// ── 派生（全部经 shared/workspaceHomeView 纯函数） ──────────────────────
const missingSourceNames = computed(() => missingSources(overview.value.sources))
const counters = computed(() => taskCounters(todo.value, overview.value))

const entry = computed(() => entryPlan(resolveEntryProfile(overview.value.signals)))
const stage = computed(() => businessStage(overview.value.signals, overview.value))
const blockers = computed(() => blockerSummary(overview.value))
const summary = computed(() => businessSummary(overview.value))
const ai = computed(() => aiActivity(overview.value))
const greetingWord = greeting(new Date().getHours())
const conditionRows = computed(() => conditionCardViewModel(profile.value))

/** 待办条目（附加稳定 key 与深链 return_to）。 */
const taskEntries = computed(() => {
  const items = Array.isArray(todo.value.items) ? todo.value.items : []
  return items.map((item, index) => ({
    ...item,
    key: `${item.type || 'x'}:${item.route?.path || ''}:${index}`,
    link: taskLink(item.route, '/app/tasks'),
    raw: item,
  }))
})
const primaryTask = computed(() => pickPrimaryTask(taskEntries.value))
const highPriority = computed(() => pickHighPriority(taskEntries.value, 3))

const todoState = computed(() => {
  const hasTodoSource = todo.value && Object.keys(todo.value).length > 0
  if (loading.value && !hasTodoSource) return 'loading'
  if (error.value) return 'error'
  return 'ready'
})
const aiState = computed(() => {
  if (loading.value && !ai.value.items?.length) return 'loading'
  // 源失败 → 部分可用；确实无数据 → ready（渲染空态文案，缺失不当 0）
  return (overview.value.sources || {}).workflow === 'failed' ? 'partial' : 'ready'
})

function severityLabel(sev) {
  return { high: '高', mid: '中', low: '低' }[sev] || '低'
}
function severityTag(sev) {
  return { high: 'danger', mid: 'warning', low: 'info' }[sev] || 'info'
}
function go(path) {
  if (path) router.push(path)
}
/** BI 销售额单元格（诚实货币：币种来自 DTO 顶层 currency，缺失标「币种未知」）。 */
function revenueCell(row) {
  return formatBiRevenue(row?.revenue, biDetail.value?.currency)
}
/** 运行时读取 CSS 令牌色（ECharts 不能直接读 CSS 变量）；无样式环境回退令牌值。 */
function tokenColor(name, fallback) {
  if (typeof document === 'undefined' || !document.documentElement) return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

// ── BI 次级图表 ────────────────────────────────────────────────────────
function renderTrend(rows) {
  if (!trendRef.value) return
  const chart = echarts.init(trendRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['GMV', '订单数'] },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: rows.map((r) => String(r.date).slice(5)) },
    yAxis: [{ type: 'value', name: 'GMV' }, { type: 'value', name: '订单' }],
    series: [
      { name: 'GMV', type: 'line', smooth: true, data: rows.map((r) => r.gmv), showSymbol: false,
        areaStyle: { opacity: 0.15 }, itemStyle: { color: tokenColor('--chart-series-1', '#236BBD') } },
      { name: '订单数', type: 'line', yAxisIndex: 1, smooth: true, data: rows.map((r) => r.orders),
        showSymbol: false, itemStyle: { color: tokenColor('--chart-series-2', '#67C23A') } },
    ],
  })
  charts.push(chart)
}

function renderPie(rows) {
  if (!pieRef.value) return
  const chart = echarts.init(pieRef.value)
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{ type: 'pie', radius: ['38%', '68%'],
      data: rows.map((r) => ({ name: r.category, value: Math.round((r.revenue || 0) * 100) / 100 })) }],
  })
  charts.push(chart)
}

onMounted(fetchAll)
onUnmounted(() => charts.forEach((c) => c.dispose()))
</script>

<style scoped>
.page { min-width: 0; }
.between { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.card-title { font-size: 16px; font-weight: 600; }
.scope { color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.hint { margin: 0 0 8px; color: var(--color-text-secondary); font-size: var(--font-size-sm); }

/* 顶部问候 + 目标行 */
.home-hero { background: var(--v91-surface); border: 1px solid var(--v91-border); border-radius: var(--radius-md); padding: 16px 20px; }
.home-hero__greeting { font-size: var(--font-size-display); font-weight: 700; color: var(--v91-text-strong); line-height: 1.2; }
.home-hero__goal { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.home-hero__hint { color: var(--v91-text-muted); font-size: var(--font-size-sm); }

.counters { display: flex; flex-wrap: wrap; gap: 40px; }
.counter { text-align: center; }
.counter__num { font-size: 24px; font-weight: 600; }
.counter__num--warn { color: var(--color-warning); }
.counter__label { color: var(--color-text-secondary); font-size: var(--font-size-xs); margin-top: 2px; }

/* 当前任务卡：高亮主任务 */
.main-task-card { background: var(--v91-tint-blue); }
.main-task { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.main-task__title { flex: 1 1 200px; min-width: 0; font-size: 16px; font-weight: 600; color: var(--v91-text-strong); }
.main-task--empty { justify-content: space-between; }

/* 第三层：阻断/摘要 */
.blocker-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.summary { display: flex; flex-wrap: wrap; gap: 24px; margin-top: 8px; }
.summary__label { color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.summary__value { font-size: 18px; font-weight: 600; color: var(--v91-text-strong); }
.summary__value--missing { color: var(--color-text-disabled); font-weight: 400; }

/* 经营条件卡：会话画像（诚实非服务端） */
.condition-card { border-color: var(--v91-border); }
.condition-rows { display: flex; flex-direction: column; }
.condition-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--v91-border); }
.condition-row:last-child { border-bottom: none; }
.condition-row__label { color: var(--v91-text-secondary); font-size: var(--font-size-sm); }
.condition-row__value { color: var(--v91-text-strong); font-weight: 600; font-size: var(--font-size-sm); text-align: right; }
.condition-row--missing { background: var(--v91-amber-surface); border-radius: var(--radius-sm); padding-left: 10px; padding-right: 10px; }
.condition-caption { margin: 12px 0 0; color: var(--v91-text-muted); font-size: var(--font-size-xs); }
/* 草稿态（未保存到服务器）用琥珀底提示；已保存态保持平静 */
.condition-caption--draft {
  padding: 4px 8px;
  border-radius: 4px;
  background: var(--v91-amber-surface);
}

.task-list { display: flex; flex-direction: column; }
.chart-box { height: 280px; }

.currency-note { color: var(--v91-text-muted); font-size: var(--font-size-xs); margin-left: 4px; }

.mb16 { margin-bottom: 16px; }

/* 窄屏（≤768）：卡片内元素换行，避免挤压；容器不横向溢出 */
@media (max-width: 768px) {
  .counters { gap: 24px; }
  .summary { gap: 16px; }
  .home-hero__greeting { font-size: var(--font-size-xl); }
  .chart-box { height: 200px; }
}
</style>
