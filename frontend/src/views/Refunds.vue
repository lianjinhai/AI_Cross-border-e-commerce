<template>
  <div class="page">
    <!-- 状态统计卡 -->
    <el-row :gutter="16" class="mb16">
      <el-col :span="4" v-for="k in statCards" :key="k.key">
        <el-card class="kpi-card" shadow="hover" v-loading="statLoading">
          <div class="kpi-label">{{ k.label }}</div>
          <div class="kpi-value" :style="{ color: k.color }">{{ stats[k.key] || 0 }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 筛选 + 发起退款 -->
    <el-card class="mb16">
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center">
        <el-select v-model="q.status" placeholder="状态" style="width:140px" clearable @change="onFilter">
          <el-option v-for="(v, s) in STATUS" :key="s" :label="v.text" :value="s" />
        </el-select>
        <el-button v-if="can('refund:write')" type="primary" @click="openCreate">发起退款</el-button>
      </div>
    </el-card>

    <!-- 退款单列表 -->
    <el-card>
      <el-table :data="items" v-loading="loading" size="small">
        <el-table-column prop="refund_no" label="退款单号" width="170" show-overflow-tooltip />
        <el-table-column prop="external_no" label="平台单号" width="130" show-overflow-tooltip />
        <el-table-column prop="platform" label="平台" width="90" />
        <el-table-column prop="buyer_name" label="买家" width="100" show-overflow-tooltip />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">{{ TYPE[row.type] || row.type }}</template>
        </el-table-column>
        <el-table-column prop="qty" label="数量" width="70" />
        <el-table-column label="金额" width="100">
          <template #default="{ row }">${{ Number(row.amount || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="140" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="申请时间" width="160" />
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button v-if="can('refund:write')" type="primary" link size="small" @click="approve(row)">同意</el-button>
              <el-button v-if="can('refund:write')" type="danger" link size="small" @click="reject(row)">拒绝</el-button>
            </template>
            <el-button v-if="row.status === 'approved' && row.type === 'return_refund' && can('refund:write')"
              type="warning" link size="small" @click="receiveReturn(row)">退货入库</el-button>
            <el-button v-if="(row.status === 'approved' || row.status === 'returned') && can('refund:write')"
              type="success" link size="small" @click="doRefund(row)">执行退款</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" v-model:current-page="page" @current-change="load" />
    </el-card>

    <!-- 发起退款 -->
    <el-dialog v-model="dialog" title="发起退款" width="480px">
      <el-form label-width="90px">
        <el-form-item label="订单ID" required>
          <el-input-number v-model="form.order_id" :min="1" style="width:100%" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width:100%">
            <el-option label="退款不退货" value="refund_only" />
            <el-option label="退货退款" value="return_refund" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="form.qty" :min="1" />
        </el-form-item>
        <el-form-item label="金额($)">
          <el-input-number v-model="form.amount" :min="0" :precision="2" :step="1"
            controls-position="right" style="width:100%" />
          <div class="form-tip">留空 = 按订单单价 × 数量自动计算</div>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="form.reason" type="textarea" :rows="2" placeholder="买家申请原因 / 备注" />
        </el-form-item>
        <el-form-item label="回补库存">
          <el-switch v-model="form.restock" />
          <span class="form-tip" style="margin-left:8px">退货退款且退货入库时回补虚拟库存</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="create">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'
import { can } from '../permissions'

const STATUS = {
  pending: { text: '待审核', tag: 'warning' },
  approved: { text: '已同意', tag: 'primary' },
  returned: { text: '已退货', tag: 'info' },
  refunded: { text: '已退款', tag: 'success' },
  rejected: { text: '已拒绝', tag: 'danger' },
}
const TYPE = { refund_only: '退款不退货', return_refund: '退货退款' }
const statusText = (s) => (STATUS[s] || { text: s }).text
const statusTag = (s) => (STATUS[s] || { tag: 'info' }).tag

const statCards = [
  { key: 'pending', label: '待审核', color: '#E6A23C' },
  { key: 'approved', label: '已同意', color: '#409EFF' },
  { key: 'returned', label: '已退货', color: '#909399' },
  { key: 'refunded', label: '已退款', color: '#67C23A' },
  { key: 'rejected', label: '已拒绝', color: '#F56C6C' },
]

const stats = ref({})
const statLoading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const q = reactive({ status: '' })
const dialog = ref(false)
const submitting = ref(false)
const form = reactive({ order_id: undefined, type: 'refund_only', qty: 1, amount: null, reason: '', restock: true })

async function loadStats() {
  statLoading.value = true
  try {
    const { data } = await api.get('/refunds', { params: { page_num: 1, page_size: 200 } })
    const counter = {}
    for (const r of data.items || []) counter[r.status] = (counter[r.status] || 0) + 1
    stats.value = counter
  } finally { statLoading.value = false }
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/refunds',
      { params: { status: q.status, page_num: page.value, page_size: pageSize } })
    items.value = data.items || []
    total.value = data.total ?? items.value.length
  } finally { loading.value = false }
}

function onFilter() {
  page.value = 1
  load()
}

function refresh() {
  load()
  loadStats()
}

async function approve(row) {
  try {
    await ElMessageBox.confirm(
      `确定同意退款单 ${row.refund_no}（$${Number(row.amount || 0).toFixed(2)}）？`, '同意退款', { type: 'warning' })
  } catch { return }
  await api.put(`/refunds/${row.id}/status`, { status: 'approved' })
  ElMessage.success(`退款单 ${row.refund_no} 已同意`)
  refresh()
}

async function reject(row) {
  let reason = ''
  try {
    const { value } = await ElMessageBox.prompt('请输入拒绝原因', `拒绝退款 ${row.refund_no}`, {
      type: 'warning',
      inputPlaceholder: '拒绝原因（将记录到退款单备注）',
      inputValidator: (v) => (v && v.trim() ? true : '请输入拒绝原因'),
    })
    reason = value.trim()
  } catch { return }
  await api.put(`/refunds/${row.id}/status`, { status: 'rejected', note: reason })
  ElMessage.success(`退款单 ${row.refund_no} 已拒绝`)
  refresh()
}

async function receiveReturn(row) {
  try {
    await ElMessageBox.confirm(`确认已收到 ${row.refund_no} 的退货商品并入库？`, '退货入库', { type: 'warning' })
  } catch { return }
  const { data } = await api.post(`/refunds/${row.id}/return_receive`, {})
  ElMessage.success(`已回补库存 ${data.restocked} 件`)
  refresh()
}

async function doRefund(row) {
  try {
    await ElMessageBox.confirm(
      `确认执行退款 $${Number(row.amount || 0).toFixed(2)}？订单将联动为已退款。`, '执行退款', { type: 'warning' })
  } catch { return }
  await api.post(`/refunds/${row.id}/refund`, {})
  ElMessage.success('退款执行成功，订单将联动为已退款')
  refresh()
}

function openCreate() {
  form.order_id = undefined
  form.type = 'refund_only'
  form.qty = 1
  form.amount = null
  form.reason = ''
  form.restock = true
  dialog.value = true
}

async function create() {
  if (!form.order_id) {
    ElMessage.warning('请填写订单ID')
    return
  }
  submitting.value = true
  try {
    const { data } = await api.post('/refunds', {
      order_id: form.order_id,
      type: form.type,
      qty: form.qty,
      amount: form.amount ?? null,
      reason: form.reason,
      restock: form.restock,
    })
    ElMessage.success(`退款单 ${data.refund_no} 已创建，等待审核`)
    dialog.value = false
    refresh()
  } finally { submitting.value = false }
}

onMounted(() => { loadStats(); load() })
</script>

<style scoped>
.form-tip { color: #909399; font-size: 12px; line-height: 1.6; }
</style>
