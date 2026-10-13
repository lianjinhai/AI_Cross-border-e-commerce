<template>
  <div class="page">
    <PageHeader title="BI 经营分析" subtitle="统一指标（口径可展开） · 趋势 · 数据可信度 · AI 经营报告">
      <template #actions>
        <el-radio-group v-model="days" @change="loadAll">
          <el-radio-button :value="7">7 天</el-radio-button>
          <el-radio-button :value="30">30 天</el-radio-button>
          <el-radio-button :value="90">90 天</el-radio-button>
        </el-radio-group>
        <el-button v-if="writable" type="primary" :loading="reportLoading" @click="genReport">
          生成 AI 经营报告
        </el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="quality.grade" :type="quality.grade === 'low' ? 'warning' : 'success'"
      :closable="false" show-icon class="mb16"
      :title="`数据可信度：${String(quality.grade).toUpperCase()} · 真实订单 ${quality.real_order_count} · 新鲜度 ${quality.freshness_hours ?? '—'} 小时`"
      :description="quality.commercial_ready ? '当前数据通过基础商用门禁' : '当前数据不足以宣称商用预测准确，自动采购保持受限'"
    />

    <!-- 指标卡：每张可展开口径说明，并区分五个易混口径 -->
    <FormSection title="统一指标" description="点击「口径」展开说明；结算到账与估算利润口径见下方专项说明">
      <el-row :gutter="16">
        <el-col v-for="m in cards" :key="m.key" :span="6" class="metric-col">
          <el-card shadow="hover">
            <div class="kpi-label">
              {{ m.label }}
              <el-button link size="small" type="primary" @click="toggle(m.key)">
                {{ expanded.has(m.key) ? '收起口径' : '口径' }}
              </el-button>
            </div>
            <div class="kpi-value">{{ m.display }}</div>
            <div v-if="expanded.has(m.key)" class="caliber">
              <p><b>口径：</b>{{ m.caliber }}</p>
              <p><b>口径区分：</b>{{ m.distinction }}</p>
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-alert type="info" :closable="false" class="mt8" :title="SETTLED_CALIBER_NOTE" />
      <el-alert type="info" :closable="false" class="mt8" :title="ESTIMATED_PROFIT_NOTE" />
    </FormSection>

    <el-alert
      v-if="fxGap" type="error" :closable="false" show-icon class="mb16"
      :title="`财务口径不完整：${fxGap.orders} 个订单、${fxGap.fees} 笔费用因缺少汇率被排除`"
      description="请到财务工作台补齐交易发生日之前有效的兑 USD 汇率；在此之前，这些金额不会被静默混入统一指标。"
    />

    <el-row :gutter="16" class="mb16">
      <el-col :span="16">
        <FormSection title="订单账面趋势" description="仅作运营趋势参考，不替代统一财务口径">
          <div ref="profitRef" class="chart-box" />
        </FormSection>
      </el-col>
      <el-col :span="8">
        <FormSection title="类目利润贡献">
          <div ref="catRef" class="chart-box" />
        </FormSection>
      </el-col>
    </el-row>

    <FormSection v-if="report" title="AI 经营报告">
      <!-- report 为后端 AI 文本，经 mdRender 白名单转义渲染 -->
      <div class="report" v-html="mdRender(report)" />
    </FormSection>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import echarts from '../../charts'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import { can } from '../../permissions/permissions'
import { fetchMetrics, fetchDataQuality, fetchProfitAnalysis, generateReport } from '../../api/domains/bi'
import {
  metricCardList, SETTLED_CALIBER_NOTE, ESTIMATED_PROFIT_NOTE,
} from '../../shared/biCaliber'

const writable = can('ai:write')

const days = ref(30)
const metrics = ref({})
const quality = ref({})
const report = ref('')
const reportLoading = ref(false)
const profitRef = ref(null)
const catRef = ref(null)
const expanded = reactive(new Set())
let charts = []

const cards = computed(() => metricCardList(metrics.value))
const fxGap = computed(() => {
  const orders = (metrics.value.excluded_orders_missing_fx || []).length
  const fees = (metrics.value.excluded_fees_missing_fx || []).length
  return orders || fees ? { orders, fees } : null
})

function toggle(key) {
  if (expanded.has(key)) expanded.delete(key)
  else expanded.add(key)
}

/** AI 报告白名单 Markdown 渲染（先转义 HTML 再替换受限语法）。 */
function mdRender(text) {
  return (text || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/^### (.*)$/gm, '<h4>$1</h4>')
    .replace(/^## (.*)$/gm, '<h3>$1</h3>')
    .replace(/^# (.*)$/gm, '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/^[-·] (.*)$/gm, '<div>• $1</div>')
}

function renderCharts(data) {
  charts.forEach((c) => c.dispose())
  charts = []
  const profit = echarts.init(profitRef.value)
  profit.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['收入', '成本', '利润'] },
    grid: { left: 60, right: 30, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: (data.series || []).map((s) => s.date.slice(5)) },
    yAxis: { type: 'value', name: 'USD' },
    series: [
      { name: '收入', type: 'line', smooth: true, showSymbol: false, data: (data.series || []).map((s) => s.revenue), itemStyle: { color: '#409EFF' } },
      { name: '成本', type: 'line', smooth: true, showSymbol: false, data: (data.series || []).map((s) => s.cost), itemStyle: { color: '#E6A23C' } },
      { name: '利润', type: 'line', smooth: true, showSymbol: false, areaStyle: { opacity: 0.12 }, data: (data.series || []).map((s) => s.profit), itemStyle: { color: '#67C23A' } },
    ],
  })
  charts.push(profit)
  const cat = echarts.init(catRef.value)
  cat.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 90, right: 30, top: 20, bottom: 30 },
    xAxis: { type: 'value', name: 'USD' },
    yAxis: { type: 'category', data: (data.by_category || []).map((c) => c.category).reverse() },
    series: [{
      type: 'bar',
      data: (data.by_category || []).map((c) => Math.round(c.profit * 100) / 100).reverse(),
      itemStyle: { color: '#67C23A' },
      label: { show: true, position: 'right' },
    }],
  })
  charts.push(cat)
}

async function loadAll() {
  const [metricData, qualityData] = await Promise.all([
    fetchMetrics({ days: days.value }),
    fetchDataQuality(),
  ])
  metrics.value = metricData || {}
  quality.value = qualityData || {}
  const profit = await fetchProfitAnalysis({ days: days.value })
  renderCharts(profit || {})
}

async function genReport() {
  reportLoading.value = true
  try {
    const data = await generateReport()
    report.value = data.report || ''
  } finally {
    reportLoading.value = false
  }
}

onMounted(() => { loadAll(); genReport() })
onUnmounted(() => charts.forEach((c) => c.dispose()))
</script>

<style scoped>
.metric-col {
  margin-bottom: var(--space-3);
}
.kpi-value {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  margin-top: var(--space-1);
}
.caliber {
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px dashed var(--color-border-light);
  color: var(--color-text-regular);
  font-size: var(--font-size-xs);
  line-height: 1.7;
}
.caliber p {
  margin: 0 0 var(--space-1);
}
.chart-box {
  height: 300px;
}
.report {
  white-space: pre-wrap;
  line-height: 1.9;
  font-size: var(--font-size-sm);
}
.mb16 {
  margin-bottom: var(--space-4);
}
.mt8 {
  margin-top: var(--space-2);
}
</style>
