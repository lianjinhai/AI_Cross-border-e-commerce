<template>
  <div class="page">
    <!-- 应付账龄总览 -->
    <el-card class="mb16">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>应付账龄总览</span>
          <el-button v-if="can('settlement:write')" type="primary" size="small" @click="openGen">按供应商生成对账单</el-button>
        </div>
      </template>
      <el-table :data="summary" v-loading="sumLoading" size="small" :row-class-name="agingRowClass">
        <el-table-column prop="supplier_name" label="供应商" min-width="140" show-overflow-tooltip />
        <el-table-column prop="settlement_days" label="账期(天)" width="90" />
        <el-table-column prop="unsettled_count" label="未结算笔数" width="100" />
        <el-table-column label="未结算金额" width="120">
          <template #default="{ row }">¥{{ Number(row.unsettled_amount || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="overdue_count" label="逾期笔数" width="90" />
        <el-table-column label="逾期金额" width="120">
          <template #default="{ row }">¥{{ Number(row.overdue_amount || 0).toFixed(2) }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!summary.length && !sumLoading" description="暂无应付数据" :image-size="60" />
    </el-card>

    <!-- 结算单列表 -->
    <el-card>
      <template #header><span>结算单列表</span></template>
      <el-table :data="items" v-loading="loading" size="small">
        <el-table-column prop="settle_no" label="结算单号" width="170" show-overflow-tooltip />
        <el-table-column prop="supplier_name" label="供应商" min-width="130" show-overflow-tooltip />
        <el-table-column label="账期区间" width="200">
          <template #default="{ row }">
            {{ (row.period_start || '').slice(0, 10) }} ~ {{ (row.period_end || '').slice(0, 10) }}
          </template>
        </el-table-column>
        <el-table-column prop="po_count" label="采购单数" width="90" />
        <el-table-column label="应付总额" width="120">
          <template #default="{ row }">¥{{ Number(row.total_amount || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="stTag(row.status)">{{ stText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="付款时间" width="160">
          <template #default="{ row }">{{ row.paid_at || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending' && can('settlement:write')" type="primary" link size="small"
              @click="confirmSettle(row)">确认对账</el-button>
            <el-button v-if="row.status === 'confirmed' && can('settlement:write')" type="success" link size="small"
              @click="markPaid(row)">标记已付款</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" v-model:current-page="page" @current-change="load" />
    </el-card>

    <!-- 按供应商生成对账单 -->
    <el-dialog v-model="genDialog" title="按供应商生成对账单" width="480px">
      <el-form label-width="90px">
        <el-form-item label="供应商" required>
          <el-select v-model="genSupplierId" filterable placeholder="请选择供应商" style="width:100%">
            <el-option v-for="s in genableSuppliers" :key="s.supplier_id"
              :label="`${s.supplier_name}（未结算 ${s.unsettled_count} 笔 / ¥${Number(s.unsettled_amount || 0).toFixed(2)}）`"
              :value="s.supplier_id" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false"
        title="将汇总该供应商所有「已收货且未结算」的采购单，生成一张对账单。" />
      <template #footer>
        <el-button @click="genDialog = false">取消</el-button>
        <el-button type="primary" :loading="genLoading" @click="generate">生成对账单</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'
import { can } from '../permissions'

const ST_STATUS = {
  pending: { text: '对账中', tag: 'warning' },
  confirmed: { text: '已确认', tag: 'primary' },
  paid: { text: '已付款', tag: 'success' },
}
const stText = (s) => (ST_STATUS[s] || { text: s }).text
const stTag = (s) => (ST_STATUS[s] || { tag: 'info' }).tag

const summary = ref([])
const sumLoading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const genDialog = ref(false)
const genLoading = ref(false)
const genSupplierId = ref(null)
const genableSuppliers = computed(() => summary.value.filter((s) => s.unsettled_count > 0))

function agingRowClass({ row }) {
  return row.overdue_amount > 0 ? 'aging-overdue' : ''
}

async function loadSummary() {
  sumLoading.value = true
  try {
    const { data } = await api.get('/settlements/summary')
    summary.value = data.items || []
  } finally { sumLoading.value = false }
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/settlements', { params: { page_num: page.value, page_size: pageSize } })
    items.value = data.items || []
    total.value = data.total ?? items.value.length
  } finally { loading.value = false }
}

function refresh() {
  loadSummary()
  load()
}

function openGen() {
  if (!genableSuppliers.value.length) {
    ElMessage.info('当前没有待结算的已收货采购单')
    return
  }
  genSupplierId.value = null
  genDialog.value = true
}

async function generate() {
  if (!genSupplierId.value) {
    ElMessage.warning('请选择供应商')
    return
  }
  genLoading.value = true
  try {
    const { data } = await api.post('/settlements/generate', { supplier_id: genSupplierId.value })
    ElMessage.success(`对账单 ${data.settle_no} 已生成`)
    genDialog.value = false
    refresh()
  } finally { genLoading.value = false }
}

async function confirmSettle(row) {
  try {
    await ElMessageBox.confirm(`确认完成结算单 ${row.settle_no} 的对账？`, '确认对账', { type: 'warning' })
  } catch { return }
  await api.put(`/settlements/${row.id}`, { status: 'confirmed' })
  ElMessage.success(`结算单 ${row.settle_no} 已确认对账`)
  load()
}

async function markPaid(row) {
  try {
    await ElMessageBox.confirm(
      `确认将结算单 ${row.settle_no}（¥${Number(row.total_amount || 0).toFixed(2)}）标记为已付款？真实打款请在银行/支付宝完成后记录。`,
      '标记已付款', { type: 'warning' })
  } catch { return }
  await api.put(`/settlements/${row.id}`, { status: 'paid' })
  ElMessage.success('已记录付款，请确保真实打款已在银行/支付宝完成')
  load()
}

onMounted(refresh)
</script>

<style scoped>
:deep(.el-table .aging-overdue td.el-table__cell) { color: #F56C6C; }
</style>
