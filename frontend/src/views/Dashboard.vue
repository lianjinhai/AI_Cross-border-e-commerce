<template>
  <div class="page" v-loading="loading">
    <el-row :gutter="16" class="mb16">
      <el-col :span="4" v-for="k in kpis" :key="k.label">
        <el-card class="kpi-card" shadow="hover">
          <div class="kpi-label">{{ k.label }}</div>
          <div class="kpi-value" :style="{ color: k.color }">{{ k.value }}</div>
        </el-card>
      </el-col>
    </el-row>
    <el-row :gutter="16" class="mb16">
      <el-col :span="16">
        <el-card>
          <template #header>近 30 天 GMV 与订单趋势</template>
          <div ref="trendRef" class="chart-box"></div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>类目销售分布</template>
          <div ref="pieRef" class="chart-box"></div>
        </el-card>
      </el-col>
    </el-row>
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card>
          <template #header>热销 Top5 商品</template>
          <el-table :data="data.top_products || []" size="small">
            <el-table-column type="index" width="50" />
            <el-table-column prop="title" label="商品" show-overflow-tooltip />
            <el-table-column prop="units" label="销量" width="80" />
            <el-table-column label="销售额" width="110">
              <template #default="{ row }">${{ row.revenue.toFixed(2) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>最近 AI 工作流运行</span>
              <el-button size="small" type="primary" @click="$router.push('/workflows')">去运行工作流</el-button>
            </div>
          </template>
          <el-table :data="data.recent_runs || []" size="small">
            <el-table-column prop="name" label="工作流" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }"><run-status :status="row.status" /></template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="160" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import echarts from '../charts'
import api from '../api'
import RunStatus from './RunStatus.vue'

const data = ref({})
const loading = ref(false)
const trendRef = ref(null)
const pieRef = ref(null)
let charts = []

const kpis = computed(() => {
  const d = data.value
  return [
    { label: 'GMV（总销售额）', value: `$${(d.gmv || 0).toFixed(2)}`, color: '#409EFF' },
    { label: '订单数', value: d.orders ?? '-', color: '#303133' },
    { label: '真实利润', value: `$${(d.profit || 0).toFixed(2)}`, color: '#67C23A' },
    { label: '广告 ROI', value: d.roi ?? '-', color: '#E6A23C' },
    { label: '在售 Listing', value: d.active_listings ?? '-', color: '#303133' },
    { label: '待处理会话', value: d.open_conversations ?? '-', color: '#F56C6C' },
  ]
})

onMounted(async () => {
  loading.value = true
  try {
    const { data: d } = await api.get('/bi/dashboard')
    data.value = d
    renderTrend(d.sales_trend || [])
    renderPie(d.category_dist || [])
  } finally {
    loading.value = false
  }
})

function renderTrend(rows) {
  const chart = echarts.init(trendRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['GMV', '订单数'] },
    grid: { left: 50, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: rows.map((r) => r.date.slice(5)) },
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
  const chart = echarts.init(pieRef.value)
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: ${c} ({d}%)' },
    series: [{ type: 'pie', radius: ['38%', '68%'],
      data: rows.map((r) => ({ name: r.category, value: Math.round(r.revenue * 100) / 100 })) }],
  })
  charts.push(chart)
}

onUnmounted(() => charts.forEach((c) => c.dispose()))
</script>
