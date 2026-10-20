<template>
  <div class="page">
    <PageHeader title="订单管理" subtitle="CSV 导入（逐行校验报告） · 状态机流转 · 履约链跟踪">
      <template #filters>
        <el-input v-model="keyword" placeholder="订单号/买家搜索" clearable style="width: 180px" @change="touch" />
        <el-select v-model="platform" placeholder="平台" clearable style="width: 120px" @change="touch">
          <el-option v-for="p in PLATFORMS" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select v-model="status" placeholder="状态" clearable style="width: 120px" @change="touch">
          <el-option v-for="(l, s) in ORDER_STATUS_LABELS" :key="s" :label="l" :value="s" />
        </el-select>
        <el-select v-model="shopFilter" placeholder="店铺" clearable style="width: 160px" @change="touch">
          <el-option v-for="s in shopOptions" :key="s.id" :label="`${s.platform} · ${s.shop_name}`" :value="s.id" />
        </el-select>
      </template>
      <template #actions>
        <el-select v-model="syncShopId" placeholder="已授权销售店铺" clearable style="width: 200px">
          <el-option
            v-for="s in syncShops" :key="s.id"
            :label="`${s.platform_label || s.platform} · ${s.shop_name}`" :value="s.id"
          />
        </el-select>
        <el-button v-if="writable" type="primary" :loading="syncing" :disabled="!syncShopId" @click="syncShop">
          从真实店铺同步
        </el-button>
        <el-button v-if="writable" type="success" @click="importDialog = true">导入 CSV</el-button>
        <el-button plain @click="exportCsv">导出 CSV</el-button>
      </template>
    </PageHeader>

    <!-- 状态机图示 -->
    <FormSection title="订单状态机" description="非法流转由后端 409 拒绝；列表内仅提供合法的下一个状态">
      <div class="flow">
        <template v-for="(s, i) in ORDER_MAIN_FLOW" :key="s">
          <el-tag v-if="i > 0" type="info" effect="plain">→</el-tag>
          <el-tag :type="status === s ? 'primary' : 'info'">{{ ORDER_STATUS_LABELS[s] }}</el-tag>
        </template>
        <el-tag type="info" effect="plain">→（任一状态）</el-tag>
        <el-tag :type="status === 'refunded' ? 'danger' : 'info'">{{ ORDER_STATUS_LABELS.refunded }}</el-tag>
      </div>
    </FormSection>

    <FormSection title="订单列表" description="展开行查看状态时间线与履约链">
      <div class="scope-line">
        当前范围：<template v-if="shopFilter">店铺 #{{ shopFilter }} · {{ shopLabel(shopFilter) }}</template>
        <template v-else>全部店铺</template>
      </div>
      <el-table v-loading="loading" :data="items" size="small">
        <el-table-column type="expand">
          <template #default="{ row }">
            <AuditTimeline :steps="orderTimeline(row)" />
            <el-alert
              v-if="row.status === 'shipped'" type="info" :closable="false" class="mt8"
              title="物流轨迹跟踪能力待接入，当前仅展示物流单号"
            />
          </template>
        </el-table-column>
        <el-table-column prop="external_no" label="订单号" width="130" />
        <el-table-column prop="platform" label="平台" width="90" />
        <el-table-column prop="buyer_name" label="买家" width="100" />
        <el-table-column prop="country" label="国家" width="70" />
        <el-table-column prop="qty" label="件数" width="70" />
        <el-table-column label="店铺" width="140">
          <template #default="{ row }">{{ orderShopLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="金额" width="120">
          <template #default="{ row }">{{ formatOrderMoney(row) }}</template>
        </el-table-column>
        <el-table-column :label="ESTIMATED_PROFIT_LABEL" width="130">
          <template #default="{ row }">
            <span :style="{ color: row.profit > 0 ? 'var(--color-success)' : 'var(--color-danger)' }">
              {{ formatOrderMoney({ currency: row.currency, amount: row.profit }) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-select
              :model-value="row.status" size="small" :disabled="!writable"
              @change="(v) => changeStatus(row, v)"
            >
              <el-option :label="ORDER_STATUS_LABELS[row.status] || row.status" :value="row.status" />
              <el-option
                v-for="s in nextStatusOptions(row.status)" :key="s"
                :label="ORDER_STATUS_LABELS[s]" :value="s"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="writable && row.status === 'paid'"
              size="small" type="success" @click="ship(row)"
            >
              发货
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="物流单号" width="150">
          <template #default="{ row }">{{ row.tracking_no || '-' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="下单时间" width="160" />
        <template #empty><EmptyState reason="NO_DATA" hint="暂无订单" /></template>
      </el-table>
      <el-pagination
        class="pager" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" :current-page="page"
        @current-change="onPageChange"
      />
    </FormSection>

    <!-- CSV 导入向导 -->
    <el-dialog v-model="importDialog" title="导入订单 CSV" width="640px" @closed="resetImport">
      <el-alert type="info" :closable="false" class="mb8" :title="CSV_IMPORT_HINT" />
      <el-input
        v-model="csvText" type="textarea" :rows="8" :disabled="importDone"
        placeholder="external_no,platform,qty,amount,status,country,buyer_name,created_at&#10;SO1001,shopee,1,23.99,paid,US,Emma88,2026-09-01 10:00:00"
      />
      <div class="mt8">
        <input type="file" accept=".csv,text/csv" :disabled="importDone" @change="onFile" />
      </div>
      <template v-if="importDone">
        <el-divider>逐行校验报告</el-divider>
        <el-alert
          :type="(importResult.errors || []).length ? 'warning' : 'success'" :closable="false"
          :title="`成功导入 ${importResult.imported ?? 0} 条，跳过重复 ${importResult.skipped ?? 0} 条，错误 ${(importResult.errors || []).length} 条`"
        />
        <el-table v-if="(importResult.errors || []).length" :data="parsedErrors" size="small" class="mt8">
          <el-table-column label="行号" width="70">
            <template #default="{ row }">{{ row.row ?? '—' }}</template>
          </el-table-column>
          <el-table-column prop="orderNo" label="订单号" width="140" />
          <el-table-column prop="reason" label="失败原因" min-width="220" />
        </el-table>
      </template>
      <template #footer>
        <el-button @click="importDialog = false">{{ importDone ? '关闭' : '取消' }}</el-button>
        <el-button v-if="!importDone" type="primary" :loading="importing" @click="doImport">
          开始导入
        </el-button>
      </template>
    </el-dialog>
    <!-- 订单详情：行/费用/采购/退款/履约，口径分开展示（S5） -->
    <el-drawer v-model="detailOpen" :title="detailTitle" size="640px">
      <div v-loading="detailLoading">
        <template v-if="detail">
          <el-alert
            v-for="(w, i) in detailWarnings(detail)" :key="i"
            :type="w.level" :title="w.text" :closable="false" class="mb8"
          />
          <el-descriptions :column="2" border size="small" class="mb12">
            <el-descriptions-item label="订单号">{{ detail.order.external_no }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ ORDER_STATUS_LABELS[detail.order.status] || detail.order.status }}</el-descriptions-item>
            <el-descriptions-item label="平台">{{ detail.order.platform }}</el-descriptions-item>
            <el-descriptions-item label="店铺">{{ detail.order.shop_name || '—（未绑定）' }}</el-descriptions-item>
            <el-descriptions-item label="商品">{{ detail.order.product_title || '—（未绑定）' }}</el-descriptions-item>
            <el-descriptions-item label="来源">{{ detail.order.source }}</el-descriptions-item>
            <el-descriptions-item label="下单时间">{{ detail.order.created_at }}</el-descriptions-item>
            <el-descriptions-item label="物流单号">
              {{ detail.fulfillment.tracking_no || '—' }}
              <span v-if="!detail.fulfillment.tracking_available" class="hint">（轨迹未接入）</span>
            </el-descriptions-item>
          </el-descriptions>

          <div class="money-grid">
            <div class="money-cell">
              <span class="money-label">订单金额</span>
              <span class="money-value">{{ formatOrderMoney({ currency: detail.order.currency, amount: detail.order.amount }) }}</span>
            </div>
            <div class="money-cell">
              <span class="money-label">{{ ESTIMATED_PROFIT_LABEL }}</span>
              <span class="money-value">{{ formatOrderMoney({ currency: detail.order.currency, amount: detail.order.profit }) }}</span>
            </div>
            <div class="money-cell">
              <span class="money-label">平台/物流等费用</span>
              <span class="money-value">{{ feeTotalsText(detail) }}</span>
            </div>
            <div class="money-cell">
              <span class="money-label">关联采购应付</span>
              <span class="money-value">{{ purchaseTotalsText(detail) }}</span>
            </div>
            <div class="money-cell">
              <span class="money-label">退款合计</span>
              <span class="money-value">{{ refundTotalText(detail) }}</span>
            </div>
          </div>

          <el-divider content-position="left">订单行</el-divider>
          <el-table :data="detail.lines" size="small">
            <el-table-column prop="sku" label="SKU" width="140" />
            <el-table-column prop="title" label="商品" min-width="180" show-overflow-tooltip />
            <el-table-column prop="qty" label="数量" width="70" />
            <el-table-column label="成交价" width="110">
              <template #default="{ row }">{{ formatOrderMoney({ currency: row.currency, amount: row.unit_price }) }}</template>
            </el-table-column>
            <el-table-column label="成本快照" width="110">
              <template #default="{ row }">{{ formatOrderMoney({ currency: row.currency, amount: row.product_cost }) }}</template>
            </el-table-column>
            <template #empty><span class="hint">该订单没有行明细（旧数据只存订单头）</span></template>
          </el-table>

          <el-divider content-position="left">费用事实</el-divider>
          <el-table :data="detail.fees.items" size="small">
            <el-table-column label="类型" width="120">
              <template #default="{ row }">{{ feeLabel(row.fee_type) }}</template>
            </el-table-column>
            <el-table-column label="金额" width="120">
              <template #default="{ row }">{{ formatOrderMoney({ currency: row.currency, amount: row.amount }) }}</template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="100" />
            <el-table-column prop="occurred_at" label="发生时间" min-width="150" />
            <template #empty><span class="hint">没有登记费用</span></template>
          </el-table>

          <el-divider content-position="left">关联采购（sales_order_id，CNY 应付）</el-divider>
          <el-table :data="detail.purchases.items" size="small">
            <el-table-column prop="po_no" label="采购单" width="150" />
            <el-table-column prop="status" label="状态" width="90" />
            <el-table-column prop="qty" label="数量" width="70" />
            <el-table-column label="单价" width="110">
              <template #default="{ row }">{{ formatOrderMoney({ currency: 'CNY', amount: row.unit_price }) }}</template>
            </el-table-column>
            <el-table-column label="合计" width="110">
              <template #default="{ row }">{{ formatOrderMoney({ currency: 'CNY', amount: row.total }) }}</template>
            </el-table-column>
            <template #empty><span class="hint">没有直接关联的采购单</span></template>
          </el-table>

          <el-divider content-position="left">退款</el-divider>
          <el-table :data="detail.refunds" size="small">
            <el-table-column prop="refund_no" label="退款单" width="150" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="reason" label="原因" min-width="160" show-overflow-tooltip />
            <el-table-column label="金额" width="110">
              <template #default="{ row }">{{ formatOrderMoney({ currency: detail.order.currency, amount: row.amount }) }}</template>
            </el-table-column>
            <template #empty><span class="hint">没有退款单</span></template>
          </el-table>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import AuditTimeline from '../../components/AuditTimeline.vue'
import { can } from '../../permissions/permissions'
import {
  fetchOrders, fetchOrder, importCsv, exportOrders, updateStatus, ship as shipOrder,
} from '../../api/domains/orders'
import { fetchShops, syncOrders as syncShopOrdersReal } from '../../api/domains/shops'
import { formatOrderMoney, orderShopLabel } from '../../shared/orderView'
import {
  detailWarnings, feeLabel, feeTotalsText, purchaseTotalsText, refundTotalText,
} from '../../shared/orderDetailView'
import {
  ORDER_STATUS_LABELS, ORDER_MAIN_FLOW, nextStatusOptions, orderTimeline,
  parseImportErrors, CSV_IMPORT_HINT,
} from '../../features/fulfillment/orderStateMachine'
import { ESTIMATED_PROFIT_LABEL } from '../../shared/biCaliber'

const PLATFORMS = ['tiktok', 'shopee', 'amazon', 'ebay', 'walmart', 'lazada', 'aliexpress', 'temu', 'shopify', 'mercadolibre', 'shein']

const writable = can('order:write')

const keyword = ref('')
const platform = ref('')
const status = ref('')
const shopFilter = ref(null)
const shopOptions = ref([])
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const syncShops = ref([])
const syncShopId = ref(null)
const syncing = ref(false)

const importDialog = ref(false)
const importing = ref(false)
const importDone = ref(false)
const csvText = ref('')
const importResult = ref({})
const parsedErrors = ref([])

// 订单详情抽屉（按 id 拉取，列表行只作为入口，不复用行数据当详情）
const detailOpen = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const detailTitle = computed(() =>
  detail.value?.order?.external_no ? `订单 ${detail.value.order.external_no}` : '订单详情')

function touch() {
  page.value = 1
  load()
}

/** 按店铺 id 查展示名（用于范围行）。找不到时回退到 "#id"，避免空白。 */
function shopLabel(id) {
  const s = shopOptions.value.find((x) => x.id === id)
  return s ? (s.shop_name || `#${id}`) : `#${id}`
}

async function load() {
  loading.value = true
  try {
    const data = await fetchOrders({
      page: page.value, status: status.value, platform: platform.value,
      keyword: keyword.value, shopId: shopFilter.value,
    })
    items.value = data.items || []
    total.value = Number(data.total ?? items.value.length)
  } finally {
    loading.value = false
  }
}

function onPageChange(next) {
  page.value = next
  load()
}

/** 发货：状态即时更新；物流轨迹待接入（展开行有标注，不放可点击入口）。 */
async function ship(row) {
  const data = await shipOrder(row.id)
  ElMessage.success(`已发货，物流单号 ${data.tracking_no}（轨迹跟踪待接入）`)
  load()
}

async function changeStatus(row, next) {
  if (!next || next === row.status) return
  const prev = row.status
  try {
    await updateStatus(row.id, next)
    row.status = next
    ElMessage.success(`订单 ${row.external_no} 状态已更新为「${ORDER_STATUS_LABELS[next]}」`)
  } catch {
    row.status = prev // 后端拒绝（非法流转）时恢复原状态显示
  }
}

function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => { csvText.value = String(reader.result || '') }
  reader.readAsText(file, 'utf-8')
}

async function doImport() {
  if (!csvText.value.trim()) return ElMessage.warning('请粘贴 CSV 内容或选择文件')
  importing.value = true
  try {
    importResult.value = await importCsv({ csvText: csvText.value })
    parsedErrors.value = parseImportErrors(importResult.value.errors || [])
    importDone.value = true
    load()
  } finally {
    importing.value = false
  }
}

function resetImport() {
  importDone.value = false
  importResult.value = {}
  parsedErrors.value = []
  csvText.value = ''
}

async function exportCsv() {
  const res = await exportOrders()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(res.data)
  a.download = 'orders.csv'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function syncShop() {
  if (!syncShopId.value) return ElMessage.warning('请选择已授权且支持拉单的销售店铺')
  syncing.value = true
  try {
    const data = await syncShopOrdersReal(syncShopId.value)
    ElMessage.success(`已从真实店铺同步 ${data.synced} 条订单`)
    load()
  } finally {
    syncing.value = false
  }
}

async function openDetail(row) {
  detailOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await fetchOrder(row.id)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '订单详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    const data = await fetchShops()
    shopOptions.value = data.items || []
    syncShops.value = (data.items || []).filter(
      (s) => s.role === 'sales' && !s.is_demo && s.status === 'authorized'
        && s.capabilities?.can_order_sync !== false)
  } catch { syncShops.value = [] }
})
</script>

<style scoped>
.flow {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.scope-line {
  margin-bottom: var(--space-2);
  color: var(--color-text-secondary, #6b7280);
  font-size: 13px;
}
.pager {
  margin-top: var(--space-3);
  justify-content: flex-end;
}
.mt8 {
  margin-top: var(--space-2);
}
.mb8 {
  margin-bottom: var(--space-2);
}
.mb12 {
  margin-bottom: var(--space-3);
}
.hint {
  color: var(--color-text-secondary, #6b7280);
  font-size: 12px;
}
.money-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.money-cell {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.money-label {
  color: var(--color-text-secondary, #6b7280);
  font-size: 12px;
}
.money-value {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>
