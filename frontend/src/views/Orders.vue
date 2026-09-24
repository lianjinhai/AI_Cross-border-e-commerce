<template>
  <div class="page">
    <el-card class="mb16">
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <el-input v-model="q.keyword" placeholder="订单号/买家搜索" style="width:200px" clearable @change="load" />
        <el-select v-model="q.platform" placeholder="平台" style="width:120px" clearable @change="load">
          <el-option v-for="p in platforms" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select v-model="q.status" placeholder="状态" style="width:120px" clearable @change="load">
          <el-option v-for="(l, s) in statusLabel" :key="s" :label="l" :value="s" />
        </el-select>
        <el-select v-model="syncShopId" placeholder="选择已授权店铺" style="width:210px" clearable>
          <el-option v-for="s in syncShops" :key="s.id" :label="`${s.platform_label || s.platform} · ${s.shop_name}`" :value="s.id" />
        </el-select>
        <el-button v-if="write" type="primary" @click="sync" :loading="syncing" :disabled="!syncShopId">从真实店铺同步</el-button>
        <el-button v-if="write" type="success" @click="importDialog = true">导入 CSV</el-button>
        <el-button plain @click="exportCsv">导出 CSV</el-button>
      </div>
    </el-card>

    <el-card>
      <el-table :data="items" v-loading="loading" size="small">
        <el-table-column prop="external_no" label="订单号" width="130" />
        <el-table-column prop="platform" label="平台" width="90" />
        <el-table-column prop="product_id" label="商品ID" width="80" />
        <el-table-column prop="buyer_name" label="买家" width="100" />
        <el-table-column prop="country" label="国家" width="70" />
        <el-table-column prop="qty" label="件数" width="70" />
        <el-table-column label="金额" width="100">
          <template #default="{ row }">${{ row.amount.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="利润" width="100">
          <template #default="{ row }">
            <span :style="{ color: row.profit > 0 ? '#67C23A' : '#F56C6C' }">${{ row.profit.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-select :model-value="row.status" size="small" :disabled="!write" @change="(v) => changeStatus(row, v)">
              <el-option v-for="(l, s) in statusLabel" :key="s" :label="l" :value="s" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button v-if="write && row.status === 'paid'" size="small" type="success" @click="ship(row)">发货</el-button>
          </template>
        </el-table-column>
        <el-table-column label="物流单号" width="150">
          <template #default="{ row }">{{ row.tracking_no || '-' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="下单时间" width="160" />
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" v-model:current-page="page" @current-change="load" />
    </el-card>
    <!-- CSV 导入 -->
    <el-dialog v-model="importDialog" title="导入订单 CSV" width="600px">
      <el-alert type="info" :closable="false" style="margin-bottom:10px"
        title="表头需含：订单号(external_no)、金额(amount)；可选 platform/status/qty/sku/country/buyer_name/created_at。按订单号去重。" />
      <el-input v-model="csvText" type="textarea" :rows="8"
        placeholder="external_no,platform,qty,amount,status,country,buyer_name,created_at&#10;SO1001,shopee,1,23.99,paid,US,Emma88,2026-09-01 10:00:00&#10;SO1002,amazon,2,45.00,已发货,DE,Liam12,2026-09-02 12:30:00" />
      <div style="margin-top:8px">
        <input type="file" accept=".csv,text/csv" @change="onFile" />
      </div>
      <el-alert v-if="importResult.imported != null" style="margin-top:10px"
        :type="importResult.errors?.length ? 'warning' : 'success'" :closable="false"
        :title="`导入 ${importResult.imported} 条，跳过重复 ${importResult.skipped} 条` + (importResult.errors?.length ? `，${importResult.errors.length} 条错误：${importResult.errors[0]}` : '')" />
      <template #footer>
        <el-button v-if="can('order:write')" @click="importDialog = false">关闭</el-button>
        <el-button v-if="can('order:write')" type="primary" :loading="importing" @click="doImport">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
import { canWrite, can } from '../permissions'

const platforms = ['tiktok', 'shopee', 'amazon', 'ebay', 'walmart', 'lazada', 'aliexpress', 'temu', 'shopify', 'mercadolibre', 'shein']
const statusLabel = { pending: '待支付', paid: '已付款', shipped: '已发货', delivered: '已签收', refunded: '已退款' }
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const syncing = ref(false)
const q = reactive({ keyword: '', platform: '', status: '' })
const importDialog = ref(false)
const importing = ref(false)
const csvText = ref('')
const importResult = ref({})
const write = can('order:write')
const syncShops = ref([])
const syncShopId = ref()

async function doImport() {
  if (!csvText.value.trim()) return ElMessage.warning('请粘贴 CSV 内容或选择文件')
  importing.value = true
  try {
    const { data } = await api.post('/orders/import', { csv_text: csvText.value })
    importResult.value = data
    ElMessage.success(`导入 ${data.imported} 条，跳过 ${data.skipped} 条`)
    load()
  } finally { importing.value = false }
}

function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => { csvText.value = String(reader.result || '') }
  reader.readAsText(file, 'utf-8')
}

async function exportCsv() {
  const res = await api.get('/orders/export', { responseType: 'blob' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(res.data)
  a.download = 'orders.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/orders', { params: { ...q, page_num: page.value, page_size: pageSize } })
    items.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

async function sync() {
  if (!syncShopId.value) return ElMessage.warning('请选择已授权且支持拉单的销售店铺')
  syncing.value = true
  try {
    const { data } = await api.post(`/shops/${syncShopId.value}/sync_orders`)
    ElMessage.success(`已从真实店铺同步 ${data.synced} 条订单`)
    load()
  } finally { syncing.value = false }
}

async function changeStatus(row, v) {
  const prev = row.status
  try {
    await api.put(`/orders/${row.id}/status`, { status: v })
    row.status = v
    ElMessage.success(`订单 ${row.external_no} 状态已更新为「${statusLabel[v]}」`)
  } catch {
    row.status = prev  // 后端拒绝（如非法流转）时恢复原状态显示
  }
}

async function loadSyncShops() {
  const { data } = await api.get('/shops')
  syncShops.value = (data.items || []).filter(s => s.role === 'sales' && !s.is_demo && s.status === 'authorized' && s.capabilities?.can_order_sync !== false)
}

async function ship(row) {
  const { data } = await api.post(`/orders/${row.id}/ship`)
  ElMessage.success(`已发货，物流单号 ${data.tracking_no}`)
  load()
}

onMounted(() => { load(); loadSyncShops() })
</script>
