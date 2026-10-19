<template>
  <div class="page">
    <!-- 只读 BFF 降级：部分源不可用 → 明示，不整页报错 -->
    <PartialDataBanner v-if="overview.partial" class="mb16" :missing="missingSourceNames" />

    <ErrorState v-if="error" class="mb16" :message="error"
                :trace-id="overview.trace_id" :on-retry="fetchAll" />

    <!-- 画像引导（derived，非准入依据；信号不足回落通用） -->
    <el-card class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">经营工作台</span>
          <el-tag size="small" type="info">{{ personaLabel }}</el-tag>
        </div>
      </template>
      <p class="hint">{{ personaHint }}</p>
      <ol class="guide-steps">
        <li v-for="(step, i) in personaSteps" :key="i">
          <span>{{ step.text }}</span>
          <el-button v-if="step.path" link type="primary" size="small"
                     @click="go(step.path)">前往</el-button>
        </li>
      </ol>
    </el-card>

    <!-- ① 在做什么 -->
    <el-card class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">① 在做什么</span>
          <span class="scope">口径：我参与的上线流程（mine）</span>
        </div>
      </template>
      <StateWrapper :state="stateOf(overview.sections.in_progress, 'launch')"
                    :on-retry="fetchAll" empty-hint="还没有进行中的上线流程">
        <el-table :data="overview.sections.in_progress || []" size="small">
          <el-table-column prop="product" label="商品" show-overflow-tooltip />
          <el-table-column prop="store" label="店铺" width="150" show-overflow-tooltip />
          <el-table-column label="进度" width="100">
            <template #default="{ row }">
              {{ row.progress?.completed ?? 0 }}/{{ row.progress?.total ?? 0 }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }"><StatusTag :status="row.execution_status" /></template>
          </el-table-column>
        </el-table>
      </StateWrapper>
    </el-card>

    <!-- ② 进展如何（BI 指标降级为次级信息，销售/广告口径分列不混算） -->
    <el-card class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">② 进展如何</span>
          <span class="scope">口径：近 30 天销售/广告指标（次级信息）</span>
        </div>
      </template>
      <StateWrapper :state="stateOf(overview.sections.metrics, 'bi')"
                    :on-retry="fetchAll" empty-hint="暂无经营指标（需财务读权限）">
        <el-row :gutter="12">
          <el-col :span="6" v-for="m in metrics" :key="m.label" class="mb12">
            <MetricCard :label="m.label" :value="m.value" :color="m.color" />
          </el-col>
        </el-row>
        <div class="scope-note">
          销售口径：GMV / 订单数 / 贡献利润 / 净收入 / 退款率；
          广告口径：广告花费 / ROI。两类口径**不做混算**。
        </div>
      </StateWrapper>
    </el-card>

    <!-- ③ 今天最重要 -->
    <el-card class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">③ 今天最重要</span>
          <span class="scope">口径：跨域待办（launch / action / alert / review）</span>
        </div>
      </template>
      <StateWrapper :state="stateOf(topToday, 'todo')"
                    :on-retry="fetchAll" empty-hint="今天没有待办">
        <div v-for="item in topToday" :key="item.type" class="todo-row">
          <el-tag size="small" :type="SEVERITY_TAG[item.severity]">
            {{ severityLabel(item.severity) }}
          </el-tag>
          <span class="todo-title">{{ item.title }}</span>
          <el-badge :value="item.count" type="primary" />
          <el-button link type="primary" size="small"
                     @click="go(item.route && item.route.path)">处理</el-button>
        </div>
      </StateWrapper>
    </el-card>

    <!-- ④ 哪些要人工 -->
    <el-card class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">④ 哪些要人工</span>
          <span class="scope">口径：待审批动作 + 待人工复核（按 items.type 派生）</span>
        </div>
      </template>
      <StateWrapper :state="stateOf(overview.sections.need_human, 'review')"
                    :on-retry="fetchAll" empty-hint="当前无需人工介入">
        <div class="metric-inline">待人工处理：<b>{{ overview.sections.need_human?.count ?? 0 }}</b></div>
        <div v-for="item in humanItems" :key="item.type" class="todo-row">
          <el-tag size="small" :type="SEVERITY_TAG[item.severity]">
            {{ severityLabel(item.severity) }}
          </el-tag>
          <span class="todo-title">{{ item.title }}</span>
          <el-button link type="primary" size="small"
                     @click="go(item.route && item.route.path)">去处理</el-button>
        </div>
      </StateWrapper>
    </el-card>

    <!-- ⑤ AI 完成了什么 -->
    <el-card class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">⑤ AI 完成了什么</span>
          <span class="scope">口径：近 24 小时成功的自动化运行</span>
        </div>
      </template>
      <StateWrapper :state="stateOf(overview.sections.ai_done, 'workflow')"
                    :on-retry="fetchAll" empty-hint="近 24 小时没有已完成的 AI 运行">
        <el-table :data="overview.sections.ai_done?.items || []" size="small">
          <el-table-column prop="title" label="运行" show-overflow-tooltip />
          <el-table-column prop="finished_at" label="完成时间" width="180" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }"><StatusTag :status="row.status" /></template>
          </el-table-column>
        </el-table>
      </StateWrapper>
    </el-card>

    <!-- ⑥ 哪些异常 -->
    <el-card class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">⑥ 哪些异常</span>
          <span class="scope">口径：未关闭的风险告警</span>
        </div>
      </template>
      <StateWrapper :state="stateOf(overview.sections.exceptions, 'alert')"
                    :on-retry="fetchAll" empty-hint="没有未处理的风险告警">
        <el-table :data="overview.sections.exceptions?.items || []" size="small">
          <el-table-column prop="title" label="告警" show-overflow-tooltip />
          <el-table-column prop="level" label="级别" width="90" />
          <el-table-column prop="created_at" label="时间" width="180" />
        </el-table>
      </StateWrapper>
    </el-card>

    <!-- 下一步 -->
    <el-card class="mb16" shadow="never">
      <template #header><span class="card-title">下一步</span></template>
      <div v-if="nextActions.length" class="next-actions">
        <el-button v-for="item in nextActions" :key="item.type" type="primary" plain
                   @click="go(item.route && item.route.path)">
          {{ item.title }}（{{ item.count }}）
        </el-button>
      </div>
      <EmptyState v-else reason="NO_DATA" hint="暂无下一步动作" />
    </el-card>

    <!-- 次级：BI 明细（保留既有能力，权限由 BFF 的 bi 源自检决定是否加载） -->
    <el-card v-if="biDetail" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">BI 明细</span>
          <span class="scope">次级信息 · 近 30 天</span>
        </div>
      </template>
      <el-row :gutter="16" class="mb16">
        <el-col :span="16"><div ref="trendRef" class="chart-box" /></el-col>
        <el-col :span="8"><div ref="pieRef" class="chart-box" /></el-col>
      </el-row>
      <el-table :data="biDetail.top_products || []" size="small">
        <el-table-column type="index" width="50" />
        <el-table-column prop="title" label="热销商品" show-overflow-tooltip />
        <el-table-column prop="units" label="销量" width="90" />
        <el-table-column label="销售额" width="120">
          <template #default="{ row }">${{ Number(row.revenue || 0).toFixed(2) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
/**
 * 首页「经营工作台」（UX-04a）：消费只读 BFF `/workbench/*`，按顺序回答 6 问。
 *
 * 只读红线：本页只发 GET；任何变更都必须在业务页经权限与审批流程完成。
 * 不伪造数据：无数据即空态；`partial=true` 时用 `PartialDataBanner` 明示缺失源。
 * 口径边界：广告花费 / 采购 / 销售分列展示，**不做混算**（见各卡 `口径` 注脚）。
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import echarts from '../charts'
import api from '../api'
import StatusTag from '../components/StatusTag.vue'
import StateWrapper from '../components/StateWrapper.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import MetricCard from '../components/MetricCard.vue'
import PartialDataBanner from '../components/PartialDataBanner.vue'
import {
  SEVERITY_TAG,
  isEmptySection,
  loadOverview,
  loadTodo,
  missingSources,
  resolvePersona,
  sectionState,
} from '../composables/workbenchTodo'

const router = useRouter()

const overview = ref({})
const todo = ref({})
const loading = ref(false)
const error = ref('')
const biDetail = ref(null)
const trendRef = ref(null)
const pieRef = ref(null)
const charts = []

// ── 数据加载（仅 GET）────────────────────────────────────────────────────

async function fetchAll() {
  loading.value = true
  error.value = ''
  try {
    const [ov, td] = await Promise.all([loadOverview(), loadTodo()])
    overview.value = ov || {}
    todo.value = td || {}
    // 次级 BI 明细：仅当 BFF 判定具备 bi 读权限时加载（避免越权 403 噪声）
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
    const { data } = await api.get('/bi/dashboard')
    biDetail.value = data || {}
    await nextTick()
    renderTrend(data?.sales_trend || [])
    renderPie(data?.category_dist || [])
  } catch {
    // 次级信息：加载失败不阻断主流程（主流程已用 BFF 的 bi 源状态表达）
    biDetail.value = null
  }
}

// ── 纯函数派生（无需组件即可理解的映射）─────────────────────────────────

const missingSourceNames = computed(() => missingSources(overview.value.sources))

const persona = computed(() => resolvePersona(overview.value.signals))

const PERSONA_LABELS = {
  A: '新手起步 · 选品 → 连店 → 上线',
  B: '货源经营 · 选品与上架',
  C: '工厂协同 · 数据与匹配',
  D: '成长期店铺 · 规模经营',
  F: '团队协作 · 权限治理',
  GENERIC: '通用工作台',
}
const personaLabel = computed(() => PERSONA_LABELS[persona.value] || PERSONA_LABELS.GENERIC)

const PERSONA_HINTS = {
  A: '先完成一次「选品 → 连店 → 上线」，再看经营指标。',
  B: '聚焦货源机会与采集/标准化进度。',
  C: '聚焦工厂数据完整度与需求匹配结果。',
  D: '聚焦店铺同步、订单履约与店铺表现。',
  F: '聚焦成员权限、授权到期与审计。',
  GENERIC: '信号不足，先按通用路径了解系统。',
}
const personaHint = computed(() => PERSONA_HINTS[persona.value] || PERSONA_HINTS.GENERIC)

const PERSONA_STEPS = {
  A: [
    { text: '第 1 步：选品（商品发现）', path: '/discovery' },
    { text: '第 2 步：连接销售店铺', path: '/shops' },
    { text: '第 3 步：创建上线流程', path: '/launch' },
  ],
  B: [
    { text: '查看货源机会与选品', path: '/discovery' },
    { text: '处理采集 / 标准化待办', path: '/products' },
    { text: '核对供应商匹配', path: '/suppliers' },
  ],
  C: [
    { text: '补全工厂供给数据', path: '/suppliers' },
    { text: '查看需求匹配结果', path: '/suppliers' },
  ],
  D: [
    { text: '同步销售店铺', path: '/shops' },
    { text: '处理待履约订单', path: '/orders' },
    { text: '查看店铺表现', path: '/bi' },
  ],
  F: [
    { text: '管理成员与权限', path: '/users' },
    { text: '检查授权与到期', path: '/settings' },
  ],
  GENERIC: [
    { text: '浏览商品池', path: '/products' },
    { text: '绑定销售店铺', path: '/shops' },
    { text: '创建工作流 / 上线流程', path: '/launch' },
  ],
}
const personaSteps = computed(() => PERSONA_STEPS[persona.value] || PERSONA_STEPS.GENERIC)

const metrics = computed(() => {
  const m = overview.value.sections?.metrics
  if (!m) return []
  const money = (v) => `$${Number(v || 0).toFixed(2)}`
  const rate = (v) => `${Number(v || 0).toFixed(1)}%`
  return [
    { label: 'GMV（销售口径）', value: money(m.gmv), color: 'var(--color-primary)' },
    { label: '订单数（销售口径）', value: m.orders ?? '—', color: 'var(--color-text)' },
    { label: '贡献利润（销售口径）', value: money(m.contribution_profit), color: 'var(--color-success)' },
    { label: '净收入（销售口径）', value: money(m.net_revenue), color: 'var(--color-text)' },
    { label: '退款率（销售口径）', value: rate(m.refund_rate), color: 'var(--color-warning)' },
    { label: '广告花费（广告口径）', value: money(m.ad_spend), color: 'var(--color-warning)' },
    { label: 'ROI（广告口径）', value: m.roi ?? '—', color: 'var(--color-danger)' },
    { label: '币种', value: m.currency || '—', color: 'var(--color-text-secondary)' },
  ]
})

const topToday = computed(() => overview.value.sections?.top_today || [])

const humanItems = computed(() =>
  topToday.value.filter((item) => item.type === 'action' || item.type === 'review'))

const nextActions = computed(() => overview.value.next_actions || [])

// ── 段状态（loading / empty / nopermission / error / ready）───────────────

function stateOf(section, sourceKey) {
  const src = overview.value.sources || {}
  const empty = isEmptySection(section)
  if (loading.value && empty) return 'loading'
  if (empty && src[sourceKey] === 'skipped') return 'nopermission'
  const st = sectionState(section, overview.value.partial, { [sourceKey]: src[sourceKey] })
  // StateWrapper 无 'partial' 态：整体部分可用时照常渲染，缺失由顶部横幅表达
  return st === 'partial' ? 'ready' : st
}

function severityLabel(severity) {
  return { high: '高', mid: '中', low: '低' }[severity] || '低'
}

function go(path) {
  if (path) router.push(path)
}

// ── 次级 BI 明细图表 ────────────────────────────────────────────────────

function renderTrend(rows) {
  if (!trendRef.value) return
  const chart = echarts.init(trendRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['GMV', '订单数'] },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: rows.map((r) => String(r.date).slice(5)) },
    yAxis: [{ type: 'value', name: 'GMV($)' }, { type: 'value', name: '订单' }],
    series: [
      { name: 'GMV', type: 'line', smooth: true, data: rows.map((r) => r.gmv), showSymbol: false,
        areaStyle: { opacity: 0.15 }, itemStyle: { color: '#409EFF' } },
      { name: '订单数', type: 'line', yAxisIndex: 1, smooth: true, data: rows.map((r) => r.orders),
        showSymbol: false, itemStyle: { color: '#67C23A' } },
    ],
  })
  charts.push(chart)
}

function renderPie(rows) {
  if (!pieRef.value) return
  const chart = echarts.init(pieRef.value)
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: ${c} ({d}%)' },
    series: [{ type: 'pie', radius: ['38%', '68%'],
      data: rows.map((r) => ({ name: r.category, value: Math.round((r.revenue || 0) * 100) / 100 })) }],
  })
  charts.push(chart)
}

onMounted(fetchAll)
onUnmounted(() => charts.forEach((c) => c.dispose()))
</script>

<style scoped>
.between {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.card-title { font-size: 16px; font-weight: 600; }
.scope { color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.scope-note {
  margin-top: 8px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}
.hint { margin: 0 0 8px; color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.guide-steps { margin: 0; padding-left: 20px; }
.guide-steps li { margin: 4px 0; }
.todo-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--color-border);
}
.todo-title { flex: 1; }
.metric-inline { margin-bottom: 8px; }
.metric-inline b { font-size: 18px; color: var(--color-primary); }
.next-actions { display: flex; flex-wrap: wrap; gap: 12px; }
.chart-box { height: 280px; }
.mb12 { margin-bottom: 12px; }
</style>
