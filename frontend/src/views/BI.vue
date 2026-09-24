<template>
  <div class="page">
    <el-card class="mb16">
      <div style="display:flex;gap:12px;align-items:center">
        <span>统计周期：</span>
        <el-radio-group v-model="days" @change="loadProfit">
          <el-radio-button :value="7">7 天</el-radio-button>
          <el-radio-button :value="30">30 天</el-radio-button>
          <el-radio-button :value="90">90 天</el-radio-button>
        </el-radio-group>
        <el-button v-if="can('ai:write')" type="primary" :loading="reportLoading" @click="genReport">生成 AI 经营报告</el-button>
      </div>
      <el-alert v-if="quality.grade" :type="quality.grade === 'low' ? 'warning' : 'success'"
        :closable="false" show-icon style="margin-top:12px"
        :title="`数据可信度：${quality.grade.toUpperCase()} · 真实订单 ${quality.real_order_count} · 新鲜度 ${quality.freshness_hours ?? '—'} 小时`"
        :description="quality.commercial_ready ? '当前数据通过基础商用门禁' : '当前数据不足以宣称商用预测准确，自动采购保持受限'" />
      <el-descriptions v-if="metrics.as_of" :column="4" border size="small" style="margin-top:12px">
        <el-descriptions-item label="GMV">${{ metrics.gmv }}</el-descriptions-item>
        <el-descriptions-item label="净收入">${{ metrics.net_revenue }}</el-descriptions-item>
        <el-descriptions-item label="贡献利润">${{ metrics.contribution_profit }}</el-descriptions-item>
        <el-descriptions-item label="贡献利润率">{{ percent(metrics.contribution_margin) }}</el-descriptions-item>
        <el-descriptions-item label="订单成本">${{ metrics.order_cost }}</el-descriptions-item>
        <el-descriptions-item label="订单费用">${{ metrics.order_fees }}</el-descriptions-item>
        <el-descriptions-item label="广告 ROAS / ROI">{{ metrics.roas ?? '—' }} / {{ metrics.roi ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="退款率">{{ percent(metrics.refund_rate) }}</el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="metrics.as_of && (metrics.excluded_orders_missing_fx?.length || metrics.excluded_fees_missing_fx?.length)"
        type="error" :closable="false" show-icon style="margin-top:12px"
        :title="`财务口径不完整：${metrics.excluded_orders_missing_fx.length} 个订单、${metrics.excluded_fees_missing_fx.length} 笔费用因缺少汇率被排除`"
        description="请补齐交易发生日之前有效的兑 USD 汇率；在此之前，这些金额不会被静默混入统一指标。" />
      <el-descriptions v-if="metrics.as_of" :column="3" border size="small" style="margin-top:12px">
        <el-descriptions-item label="可信订单">{{ metrics.trusted_orders }} / {{ metrics.orders }}</el-descriptions-item>
        <el-descriptions-item label="数据截止">{{ metrics.as_of }}</el-descriptions-item>
        <el-descriptions-item label="费用拆分">{{ feeBreakdown }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-row :gutter="16" class="mb16">
      <el-col :span="16">
        <el-card><template #header>订单账面趋势（仅作运营趋势，不替代统一财务口径）</template><div ref="profitRef" class="chart-box"></div></el-card>
      </el-col>
      <el-col :span="8">
        <el-card><template #header>类目利润贡献</template><div ref="catRef" class="chart-box"></div></el-card>
      </el-col>
    </el-row>

    <el-card v-if="report">
      <template #header>🤖 AI 经营报告</template>
      <div style="white-space:pre-wrap;line-height:1.9;font-size:14px" v-html="mdRender(report)"></div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import echarts from '../charts'
import api from '../api'
import { can } from '../permissions'

const days = ref(30)
const summary = ref({})
const report = ref('')
const reportLoading = ref(false)
const metrics = ref({})
const quality = ref({})
const profitRef = ref(null)
const catRef = ref(null)
let charts = []

const feeBreakdown = computed(() => {
  const entries = Object.entries(metrics.value.fee_breakdown || {})
  return entries.length ? entries.map(([name, amount]) => `${name}: $${amount}`).join('；') : '暂无费用明细'
})

function percent(value) {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`
}

function mdRender(text) {
  return (text || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/^### (.*)$/gm, '<h4>$1</h4>')
    .replace(/^## (.*)$/gm, '<h3>$1</h3>')
    .replace(/^# (.*)$/gm, '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/^[-·] (.*)$/gm, '<div>• $1</div>')
}

async function loadProfit() {
  charts.forEach((c) => c.dispose())
  charts = []
  const [metricRes, qualityRes] = await Promise.all([
    api.get('/bi/metrics', { params: { days: days.value } }),
    api.get('/bi/data-quality'),
  ])
  metrics.value = metricRes.data
  quality.value = qualityRes.data
  const { data } = await api.get('/bi/profit', { params: { days: days.value } })
  summary.value = data.summary
  const chart = echarts.init(profitRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['收入', '成本', '利润'] },
    grid: { left: 60, right: 30, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: data.series.map((s) => s.date.slice(5)) },
    yAxis: { type: 'value', name: 'USD' },
    series: [
      { name: '收入', type: 'line', smooth: true, showSymbol: false, data: data.series.map((s) => s.revenue), itemStyle: { color: '#409EFF' } },
      { name: '成本', type: 'line', smooth: true, showSymbol: false, data: data.series.map((s) => s.cost), itemStyle: { color: '#E6A23C' } },
      { name: '利润', type: 'line', smooth: true, showSymbol: false, areaStyle: { opacity: 0.12 }, data: data.series.map((s) => s.profit), itemStyle: { color: '#67C23A' } },
    ],
  })
  charts.push(chart)
  const cat = echarts.init(catRef.value)
  cat.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 90, right: 30, top: 20, bottom: 30 },
    xAxis: { type: 'value', name: 'USD' },
    yAxis: { type: 'category', data: data.by_category.map((c) => c.category).reverse() },
    series: [{ type: 'bar', data: data.by_category.map((c) => Math.round(c.profit * 100) / 100).reverse(),
      itemStyle: { color: '#67C23A' }, label: { show: true, position: 'right' } }],
  })
  charts.push(cat)
}

async function genReport() {
  reportLoading.value = true
  try {
    const { data } = await api.get('/bi/report')
    report.value = data.report
  } finally { reportLoading.value = false }
}

onMounted(() => { loadProfit(); genReport() })
onUnmounted(() => charts.forEach((c) => c.dispose()))
</script>
