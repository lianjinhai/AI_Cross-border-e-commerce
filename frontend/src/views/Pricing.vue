<template>
  <div class="page">
    <el-card class="mb16">
      <div style="display:flex;gap:12px;align-items:center">
        <span>商品 ID：</span>
        <el-input-number v-model="pid" :min="1" />
        <el-button v-if="can('finance:write')" @click="calc" :loading="calcLoading">计算真实利润</el-button>
        <el-button v-if="can('finance:write')" type="primary" @click="suggest" :loading="sugLoading">AI 动态定价</el-button>
        <el-button v-if="can('finance:write')" type="success" plain @click="repriceAll" :loading="allLoading">全店重新定价（工作流）</el-button>
      </div>
      <el-descriptions v-if="calcResult" :column="4" border size="small" style="margin-top:12px">
        <el-descriptions-item label="采购成本¥">{{ calcResult.purchase_cost }}</el-descriptions-item>
        <el-descriptions-item label="物流¥">{{ calcResult.logistics_cost }}</el-descriptions-item>
        <el-descriptions-item label="佣金率">{{ (calcResult.platform_fee_rate * 100).toFixed(1) }}%</el-descriptions-item>
        <el-descriptions-item label="广告¥/件">{{ calcResult.ads_cost }}</el-descriptions-item>
        <el-descriptions-item label="售价">${{ calcResult.price }}</el-descriptions-item>
        <el-descriptions-item label="单件利润">
          <b :style="{ color: calcResult.profit > 0 ? '#67C23A' : '#F56C6C' }">${{ calcResult.profit }}</b>
        </el-descriptions-item>
        <el-descriptions-item label="利润率">{{ (calcResult.margin * 100).toFixed(1) }}%</el-descriptions-item>
        <el-descriptions-item label="汇率">{{ calcResult.fx }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card>
      <template #header>定价记录（最新在前）</template>
      <el-table :data="items" v-loading="loading" size="small">
        <el-table-column prop="product_id" label="商品ID" width="80" />
        <el-table-column prop="product_title" label="商品" min-width="200" show-overflow-tooltip />
        <el-table-column prop="price" label="当前价$" width="90" />
        <el-table-column label="建议价$" width="110">
          <template #default="{ row }"><b style="color:#409EFF">${{ row.suggested_price }}</b></template>
        </el-table-column>
        <el-table-column label="单件利润$" width="100">
          <template #default="{ row }">
            <span :style="{ color: row.profit > 0 ? '#67C23A' : '#F56C6C' }">{{ row.profit }}</span>
          </template>
        </el-table-column>
        <el-table-column label="利润率" width="150">
          <template #default="{ row }">
            <el-progress :percentage="Math.max(0, Math.round(row.margin * 100))"
              :color="row.margin > 0.3 ? '#67C23A' : row.margin > 0.15 ? '#E6A23C' : '#F56C6C'" />
          </template>
        </el-table-column>
        <el-table-column prop="model" label="模型" width="90" />
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column label="调价依据" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.reason?.strategy }}{{ row.reason?.adjustments?.length ? '；' + row.reason.adjustments.join('；') : '' }}
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" v-model:current-page="page" @current-change="load" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
import { can } from '../permissions'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const pid = ref(1)
const calcLoading = ref(false)
const sugLoading = ref(false)
const allLoading = ref(false)
const calcResult = ref(null)

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/pricing', { params: { page_num: page.value, page_size: pageSize } })
    items.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

async function calc() {
  calcLoading.value = true
  try {
    const { data } = await api.post('/pricing/calc', { product_id: pid.value })
    calcResult.value = data
  } finally { calcLoading.value = false }
}

async function suggest() {
  sugLoading.value = true
  try {
    const { data } = await api.post('/pricing/suggest', { product_id: pid.value })
    ElMessage.success(`建议价 $${data.suggested_price}（利润率 ${(data.margin * 100).toFixed(1)}%）`)
    load()
  } finally { sugLoading.value = false }
}

async function repriceAll() {
  allLoading.value = true
  try {
    await api.post('/workflows/run', { template_key: 'reprice', context: {} })
    ElMessage.success('全店动态定价工作流已完成')
    load()
  } finally { allLoading.value = false }
}

onMounted(load)
</script>
