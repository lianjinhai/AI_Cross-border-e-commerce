<template>
  <div class="page">
    <PageHeader
      title="预测与数据质量"
      subtitle="预测区待接入 · 数据质量缺项统计先行（缺汇率/缺费用/缺成本/来源混合）"
    >
      <template #filters>
        <el-select v-model="days" size="small" @change="load">
          <el-option :value="7" label="近 7 天" />
          <el-option :value="30" label="近 30 天" />
          <el-option :value="90" label="近 90 天" />
        </el-select>
      </template>
      <template #actions>
        <el-button @click="router.push('/app/analytics/bi')">经营总览</el-button>
        <el-button @click="router.push('/app/analytics/finance')">财务台账</el-button>
      </template>
    </PageHeader>

    <!-- 数据质量区：基于 finance/orders 真实缺项统计先行 -->
    <SectionState :code="dqCode" :error="dqError" @retry="loadDq">
      <el-card v-if="dqCode === 'ready' || dqCode === 'PARTIAL_DATA'" shadow="never" class="mb16">
        <div class="card-head">
          <span>数据质量缺项（可先行修复）</span>
          <el-tag :type="hasGaps ? 'warning' : 'success'" size="small" effect="plain">
            {{ hasGaps ? '存在缺项' : '无缺项' }}
          </el-tag>
        </div>
        <DataQualityBanner
          v-if="hasGaps"
          tag="MANUAL_UNVERIFIED"
          :detail="`近 ${days} 天订单共发现 ${totalGaps} 处数据缺项`"
          :links="dqLinks"
        />
        <el-table :data="dqRows" size="small">
          <el-table-column prop="label" label="缺项类别" width="120" />
          <el-table-column prop="count" label="数量" width="80" />
          <el-table-column prop="hint" label="说明" min-width="220" />
          <el-table-column label="修复入口" width="140">
            <template #default="{ row }">
              <el-button
                link type="primary" size="small"
                :disabled="row.count === 0"
                @click="router.push(row.link)"
              >跳明细修复</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </SectionState>

    <!-- 预测区：端点未核（§7#10）→ 只读"待接入"骨架 + 未达商用门槛显"仅参考" -->
    <el-card shadow="never" class="mb16">
      <div class="card-head">
        <span>销量预测</span>
        <el-tag type="info" size="small" effect="plain">{{ gate.label }}</el-tag>
      </div>
      <div class="forecast-body">
        <el-alert
          type="info" :closable="false"
          title="预测数据待接入，以下数据质量可先行修复"
          description="预测模型端点未核（§7#10）：训练样本/连续性/真实数据比例/窗口/模型版本/WAPE 未接入前，本区只读，不出预测数字，不触发自动采购。数据质量缺项修复后预测才可商用。"
        />
        <div class="forecast-grid">
          <div v-for="item in forecastPlaceholders" :key="item.key" class="forecast-grid__cell">
            <div class="forecast-grid__label">{{ item.label }}</div>
            <div class="forecast-grid__value">—</div>
            <div class="forecast-grid__hint">待接入</div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
/**
 * 预测与数据质量（蓝图 R1 BI-02，包 2）：/app/analytics/forecast。
 *
 * 数据源：预测端点未核（§7#10）→ 预测区"待接入"；数据质量区基于
 * finance.js/orders.js 缺项统计先行（缺汇率/缺费用/缺成本/来源混合），
 * 未达商用门槛显"仅参考"，禁自动采购。
 * 纯函数源：shared/forecastView.js（缺项统计 + 商用门槛 + 11 态映射）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { ElMessage } from '../../shared/ui'
import { fetchOrders } from '../../api/domains/orders'
import {
  DQ_GAPS, dataQualityRows, forecastCommercialGate,
} from '../../shared/forecastView'

const router = useRouter()
const days = ref(30)

const orders = ref([])
const dqCode = ref('LOADING')
const dqError = ref('')

/** 缺项行（含跳明细修复深链）。 */
const dqRows = computed(() => {
  const rows = dataQualityRows(orders.value)
  const LINK = {
    fx_missing: '/app/analytics/finance',
    fee_missing: '/app/analytics/finance',
    cost_missing: '/app/supply/purchases',
    source_mixed: '/app/orders',
  }
  return rows.map((r) => ({ ...r, link: LINK[r.key] || '/app/orders' }))
})
const hasGaps = computed(() => dqRows.value.some((r) => r.count > 0))
const totalGaps = computed(() => dqRows.value.reduce((sum, r) => sum + r.count, 0))
const dqLinks = computed(() => dqRows.value
  .filter((r) => r.count > 0)
  .map((r) => ({ label: `查看${r.label}明细`, path: r.link })))

/** 预测区（端点未核 → 只读"待接入"骨架，未达商用门槛显"仅参考"）。 */
const gate = computed(() => forecastCommercialGate({}))

/** 预测占位字段（全部"—"，禁假数字）。 */
const forecastPlaceholders = [
  { key: 'samples', label: '训练样本', value: '' },
  { key: 'continuity', label: '数据连续性', value: '' },
  { key: 'real_ratio', label: '真实数据比例', value: '' },
  { key: 'window', label: '预测窗口', value: '' },
  { key: 'model', label: '模型版本', value: '' },
  { key: 'wape', label: 'WAPE', value: '' },
]
void DQ_GAPS

async function loadDq() {
  dqCode.value = 'LOADING'
  dqError.value = ''
  try {
    const data = await fetchOrders({ page: 1 })
    orders.value = data.items || []
    dqCode.value = hasGaps.value ? 'PARTIAL_DATA' : 'ready'
  } catch (e) {
    dqError.value = e?.response?.data?.detail || e?.message || '加载失败'
    dqCode.value = 'ERROR'
  }
}

onMounted(loadDq)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-weight: 600;
}
.forecast-body { margin-top: 8px; }
.forecast-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 12px;
}
.forecast-grid__cell {
  border: 1px dashed var(--el-border-color, #dcdfe6);
  border-radius: 6px;
  padding: 10px;
}
.forecast-grid__label { font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.forecast-grid__value { font-size: 16px; font-weight: 600; margin: 4px 0; }
.forecast-grid__hint { font-size: var(--font-size-xs); color: var(--color-text-secondary); }
</style>
