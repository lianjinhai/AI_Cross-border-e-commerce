<template>
  <div class="page">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="供应商" name="suppliers">
        <el-row :gutter="16">
          <el-col :span="14">
            <el-card class="mb16">
              <template #header>
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <span>私域供应链伙伴</span>
                  <div><el-button size="small" @click="matchDialog=true">匹配市场机会</el-button>
                  <el-button v-if="can('supply:write')" type="primary" size="small" @click="dialog = true">新增源头工厂</el-button></div>
                </div>
              </template>
              <el-table :data="items" v-loading="loading" size="small">
                <el-table-column prop="id" label="ID" width="55" />
                <el-table-column prop="name" label="供应商" min-width="180" show-overflow-tooltip />
                <el-table-column prop="region" label="地区" width="80" />
                <el-table-column label="核验" width="90"><template #default="{ row }">
                  <el-tag :type="row.verification_status === 'verified' ? 'success' : 'warning'" size="small">{{ row.verification_status || 'candidate' }}</el-tag>
                </template></el-table-column>
                <el-table-column prop="rating" label="评分" width="70" />
                <el-table-column prop="ship_days" label="发货天" width="75" />
                <el-table-column label="综合分" width="150">
                  <template #default="{ row }">
                    <el-progress v-if="row.score_total != null" :percentage="row.score_total"
                      :color="row.score_total > 75 ? '#67C23A' : '#E6A23C'" />
                    <el-button v-else-if="can('supply:write')" size="small" type="primary" link @click="score(row)">AI 评分</el-button>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="90" fixed="right">
                  <template #default="{ row }"><el-button size="small" @click="detail(row)">详情</el-button></template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
          <el-col :span="10">
            <el-card>
              <template #header>
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <span>补货预警（AI 销量预测）</span>
                  <el-button type="primary" size="small" :loading="fcLoading" @click="forecast">刷新预测</el-button>
                </div>
              </template>
              <el-table :data="shortages" size="small" v-loading="fcLoading">
                <el-table-column prop="title" label="商品" show-overflow-tooltip />
                <el-table-column prop="weekly_demand" label="周需求" width="80" />
                <el-table-column prop="onhand" label="在手" width="70" />
                <el-table-column label="风险" width="80">
                  <template #default="{ row }"><run-status :status="row.shortage_risk" /></template>
                </el-table-column>
                <el-table-column prop="suggest_restock_qty" label="建议补货" width="90" />
              </el-table>
              <el-empty v-if="!shortages.length && !fcLoading" description="暂无缺货风险" :image-size="60" />
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="机会历史" name="opportunities"><el-card><template #header><div style="display:flex;justify-content:space-between"><span>市场机会 × 私域工厂</span><el-button @click="loadOpportunityHistory">刷新</el-button></div></template><el-table :data="opportunityHistory" v-loading="opportunityLoading"><el-table-column prop="product.title" label="市场商品" min-width="180"/><el-table-column prop="supplier.name" label="工厂"/><el-table-column prop="catalog_product.title" label="工厂商品" min-width="180"/><el-table-column prop="total_score" label="机会分"/><el-table-column prop="decision" label="决策"/><el-table-column label="操作"><template #default="{row}"><el-button v-if="write" link type="primary" :disabled="!row.can_promote" @click="promoteMatch(row)">转为报价</el-button></template></el-table-column></el-table></el-card></el-tab-pane>
      <el-tab-pane label="采购单" name="purchases">
        <el-card class="mb16">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>采购单列表</span>
              <div>
                <el-button v-if="can('purchase:write')" type="primary" size="small" :loading="pfLoading" @click="genFromForecast">从补货预警生成采购单</el-button>
                <el-button v-if="can('purchase:write')" size="small" type="primary" plain @click="openPoDialog">新建采购单</el-button>
              </div>
            </div>
          </template>
          <el-table :data="poItems" v-loading="poLoading" size="small">
            <el-table-column prop="po_no" label="采购单号" min-width="150" show-overflow-tooltip />
            <el-table-column prop="supplier_name" label="供应商" min-width="130" show-overflow-tooltip />
            <el-table-column prop="product_title" label="商品" min-width="150" show-overflow-tooltip />
            <el-table-column prop="qty" label="数量" width="70" />
            <el-table-column label="单价" width="90">
              <template #default="{ row }">¥{{ row.unit_price }}</template>
            </el-table-column>
            <el-table-column label="总额" width="100">
              <template #default="{ row }">¥{{ row.total }}</template>
            </el-table-column>
            <el-table-column prop="expected_date" label="期望到货" width="110" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="poStatusTag(row.status)">{{ poStatusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <template v-if="row.status === 'draft'">
                  <el-button v-if="can('supply:write')" type="primary" link size="small" @click="submitPo(row)">提交</el-button>
                  <el-button type="success" link size="small" @click="receivePo(row)">收货入库</el-button>
                  <el-button type="danger" link size="small" @click="cancelPo(row)">取消</el-button>
                </template>
                <template v-else-if="row.status === 'submitted'">
                  <el-button type="success" link size="small" @click="receivePo(row)">收货入库</el-button>
                  <el-button type="danger" link size="small" @click="cancelPo(row)">取消</el-button>
                </template>
              </template>
            </el-table-column>
          </el-table>
          <div style="display:flex;justify-content:flex-end;margin-top:12px">
            <el-pagination v-model:current-page="poPage" v-model:page-size="poPageSize" :total="poTotal"
              :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next"
              @current-change="loadPurchases" @size-change="onPoSizeChange" />
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="应付账龄" name="aging">
        <el-card>
          <template #header><span>应付账龄总览（按供应商）</span></template>
          <el-table :data="agingItems" v-loading="agingLoading" size="small" :row-class-name="agingRowClass">
            <el-table-column prop="supplier_name" label="供应商" min-width="140" show-overflow-tooltip />
            <el-table-column prop="settlement_days" label="账期天数" width="90" />
            <el-table-column prop="unsettled_count" label="未结算笔数" width="100" />
            <el-table-column label="未结算金额" width="120">
              <template #default="{ row }">¥{{ Number(row.unsettled_amount || 0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="overdue_count" label="逾期笔数" width="90" />
            <el-table-column label="逾期金额" width="120">
              <template #default="{ row }">¥{{ Number(row.overdue_amount || 0).toFixed(2) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!agingItems.length && !agingLoading" description="暂无应付账龄数据" :image-size="60" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="drawer" :title="current.name || '供应商详情'" size="520px">
      <template v-if="current.id">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="地区">{{ current.region }}</el-descriptions-item>
          <el-descriptions-item label="平台评分">{{ current.rating }}</el-descriptions-item>
          <el-descriptions-item label="发货天数">{{ current.ship_days }}</el-descriptions-item>
          <el-descriptions-item label="稳定性">{{ current.stability }}</el-descriptions-item>
          <el-descriptions-item label="工厂类型">{{ current.supplier_type }}</el-descriptions-item>
          <el-descriptions-item label="核验状态">{{ current.verification_status }}</el-descriptions-item>
        </el-descriptions>
        <div style="margin-top:12px">
          <el-button v-if="current.verification_status !== 'verified'" type="success" size="small" @click="verifyCurrent">尽调通过</el-button>
          <el-button v-if="can('supply:write')" size="small" @click="openPortalAccount">创建工厂门户账号</el-button>
        </div>
        <template v-if="current.score">
          <h4>AI 综合评分（{{ current.score.total }}）</h4>
          <el-alert v-for="(r, i) in current.score.reasons" :key="i" :title="r" type="info" :closable="false" style="margin-bottom:6px" />
        </template>
        <h4>货源报价（{{ (current.offers || []).length }}）</h4>
        <el-table :data="current.offers || []" size="small">
          <el-table-column prop="product_id" label="商品ID" width="80" />
          <el-table-column prop="price" label="采购价¥" width="100" />
          <el-table-column prop="ship_days" label="发货天" width="80" />
          <el-table-column prop="moq" label="起订" width="70" />
        </el-table>
      </template>
    </el-drawer>

    <el-dialog v-model="dialog" title="新增供应商" width="480px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="地区"><el-input v-model="form.region" /></el-form-item>
        <el-form-item label="平台评分"><el-input-number v-model="form.rating" :min="0" :max="5" :step="0.1" /></el-form-item>
        <el-form-item label="发货天数"><el-input-number v-model="form.ship_days" :min="1" :max="30" /></el-form-item>
        <el-form-item label="能力标签"><el-input v-model="form.capabilityText" placeholder="针织,小单快反,印花" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="create">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="accountDialog" title="创建工厂门户账号" width="460px">
      <el-alert type="warning" :closable="false" title="账号只能维护当前工厂的资料和供给目录，不能访问订单、店铺或财务数据。" class="mb16" />
      <el-form label-width="90px"><el-form-item label="用户名"><el-input v-model="accountForm.username" /></el-form-item>
        <el-form-item label="初始密码"><el-input v-model="accountForm.password" type="password" show-password /></el-form-item></el-form>
      <template #footer><el-button @click="accountDialog=false">取消</el-button><el-button type="primary" @click="createPortalAccount">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="matchDialog" title="市场机会 × 私域工厂匹配" width="850px">
      <div style="display:flex;gap:10px;margin-bottom:12px"><el-select v-model="matchProductId" filterable placeholder="选择市场商品" style="width:360px"><el-option v-for="p in productOptions" :key="p.id" :label="`#${p.id} ${p.title}`" :value="p.id"/></el-select>
        <el-button type="primary" :loading="matchLoading" @click="matchOpportunity">分析匹配</el-button></div>
      <el-table :data="matchItems" size="small">
        <el-table-column prop="supplier.name" label="工厂" min-width="140" />
        <el-table-column prop="catalog_product.title" label="工厂商品" min-width="180" />
        <el-table-column prop="total_score" label="机会分" width="80" />
        <el-table-column label="预计售价" width="90"><template #default="{ row }">${{ Number(row.expected_price || 0).toFixed(2) }}</template></el-table-column>
        <el-table-column label="单件利润" width="90"><template #default="{ row }">${{ Number(row.expected_unit_profit || 0).toFixed(2) }}</template></el-table-column>
        <el-table-column label="利润率" width="85"><template #default="{ row }">{{ (Number(row.expected_margin || 0) * 100).toFixed(1) }}%</template></el-table-column>
        <el-table-column label="预计月营收" width="110"><template #default="{ row }">${{ Number(row.expected_monthly_revenue || 0).toFixed(2) }}</template></el-table-column>
        <el-table-column label="缺口" min-width="180"><template #default="{ row }">{{ (row.gaps || []).join('；') || '无' }}</template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="{ row }"><el-button link type="primary" :disabled="!row.can_promote" @click="promoteMatch(row)">转为报价</el-button></template></el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="poDialog" title="新建采购单" width="480px">
      <el-form label-width="90px">
        <el-form-item label="商品ID"><el-input-number v-model="poForm.product_id" :min="1" /></el-form-item>
        <el-form-item label="供应商">
          <el-select v-model="poForm.supplier_id" filterable placeholder="请选择供应商" style="width:100%">
            <el-option v-for="s in items" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量"><el-input-number v-model="poForm.qty" :min="1" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="poForm.note" type="textarea" :rows="2" placeholder="选填" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="poDialog = false">取消</el-button>
        <el-button type="primary" @click="createPo">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'
import RunStatus from './RunStatus.vue'
import { canWrite, can } from '../permissions'

const activeTab = ref('suppliers')

const items = ref([])
const loading = ref(false)
const shortages = ref([])
const fcLoading = ref(false)
const drawer = ref(false)
const current = ref({})
const dialog = ref(false)
const form = reactive({ name: '', region: '', rating: 4.5, ship_days: 7, capabilityText: '' })
const accountDialog = ref(false)
const accountForm = reactive({ username: '', password: '' })
const matchDialog = ref(false)
const matchProductId = ref()
const matchItems = ref([])
const matchLoading = ref(false)
const write = can('supply:write'), productOptions = ref([]), opportunityHistory = ref([]), opportunityLoading = ref(false)

const poItems = ref([])
const poLoading = ref(false)
const poPage = ref(1)
const poPageSize = ref(10)
const poTotal = ref(0)
const poDialog = ref(false)
const pfLoading = ref(false)
const poForm = reactive({ product_id: undefined, supplier_id: undefined, qty: 1, note: '' })

const agingItems = ref([])
const agingLoading = ref(false)

const PO_STATUS = {
  draft: { text: '草稿', tag: 'info' },
  submitted: { text: '已提交', tag: 'warning' },
  received: { text: '已入库', tag: 'success' },
  cancelled: { text: '已取消', tag: 'danger' }
}
const poStatusText = (s) => (PO_STATUS[s] || { text: s }).text
const poStatusTag = (s) => (PO_STATUS[s] || { tag: 'info' }).tag

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/suppliers')
    items.value = data.items
  } finally { loading.value = false }
}

async function score(row) {
  const { data } = await api.post(`/suppliers/${row.id}/score`)
  ElMessage.success(`${row.name} 综合评分 ${data.total}`)
  load()
}

async function detail(row) {
  const { data } = await api.get(`/suppliers/${row.id}`)
  current.value = data
  drawer.value = true
}

async function forecast() {
  fcLoading.value = true
  try {
    const { data } = await api.get('/suppliers/forecast')
    shortages.value = (data.context_patch || data).shortages || data.shortages || []
  } finally { fcLoading.value = false }
}

async function create() {
  await api.post('/suppliers', { ...form, capabilities: form.capabilityText.split(/[,，]/).map(x => x.trim()).filter(Boolean) })
  ElMessage.success('已创建')
  dialog.value = false
  load()
}

async function verifyCurrent() {
  await api.put(`/factory-network/suppliers/${current.value.id}/verification`, { status: 'verified', note: 'ERP 管理员确认尽调通过' })
  ElMessage.success('已标记为尽调通过')
  await detail(current.value); load()
}

function openPortalAccount() {
  accountForm.username = ''; accountForm.password = ''; accountDialog.value = true
}

async function createPortalAccount() {
  await api.post(`/factory-network/suppliers/${current.value.id}/portal-account`, accountForm)
  ElMessage.success('工厂门户账号已创建，请通过安全渠道交付初始密码')
  accountDialog.value = false
}

async function matchOpportunity() {
  if (!matchProductId.value) return ElMessage.warning('请输入市场商品 ID')
  matchLoading.value = true
  try { matchItems.value = (await api.post('/factory-network/opportunities/match', { product_id: matchProductId.value })).data.items || [] }
  finally { matchLoading.value = false }
}
async function loadOpportunityHistory(){opportunityLoading.value=true;try{opportunityHistory.value=(await api.get('/factory-network/opportunities')).data.items||[]}finally{opportunityLoading.value=false}}
async function loadProductOptions(){productOptions.value=(await api.get('/products',{params:{page_num:1,page_size:100}})).data.items||[]}

async function promoteMatch(row) {
  await api.post(`/factory-network/matches/${row.id}/promote`)
  ElMessage.success('已转为有效货源报价；下一步生成 Listing 并进入复核审批')
}

async function loadPurchases() {
  poLoading.value = true
  try {
    const { data } = await api.get('/purchases', { params: { page_num: poPage.value, page_size: poPageSize.value } })
    poItems.value = data.items || []
    poTotal.value = data.total ?? poItems.value.length
  } finally { poLoading.value = false }
}

function onPoSizeChange() {
  poPage.value = 1
  loadPurchases()
}

async function refreshPurchaseData() {
  await Promise.all([loadPurchases(), forecast()])
}

async function genFromForecast() {
  pfLoading.value = true
  try {
    const { data } = await api.post('/purchases/from_forecast', { product_ids: [], qty_multiplier: 1.0 })
    ElMessage.success(`已生成 ${(data.created || []).length} 张采购单`)
    await refreshPurchaseData()
  } finally { pfLoading.value = false }
}

function openPoDialog() {
  poForm.product_id = undefined
  poForm.supplier_id = undefined
  poForm.qty = 1
  poForm.note = ''
  poDialog.value = true
}

async function createPo() {
  if (!poForm.product_id || !poForm.supplier_id || !poForm.qty) {
    ElMessage.warning('请填写商品ID、供应商和数量')
    return
  }
  await api.post('/purchases', {
    product_id: poForm.product_id,
    supplier_id: poForm.supplier_id,
    qty: poForm.qty,
    note: poForm.note
  })
  ElMessage.success('采购单已创建')
  poDialog.value = false
  await refreshPurchaseData()
}

async function submitPo(row) {
  await api.put(`/purchases/${row.id}`, { status: 'submitted' })
  ElMessage.success(`采购单 ${row.po_no} 已提交`)
  await refreshPurchaseData()
}

async function receivePo(row) {
  const { data } = await api.post(`/purchases/${row.id}/receive`, {})
  ElMessage.success(`入库 ${data.in_stock_added} 件，当前库存 ${data.onhand_now}`)
  await refreshPurchaseData()
}

async function cancelPo(row) {
  try {
    await ElMessageBox.confirm(`确定取消采购单 ${row.po_no}？`, '提示', { type: 'warning' })
  } catch { return }
  await api.delete(`/purchases/${row.id}`)
  ElMessage.success('采购单已取消')
  await refreshPurchaseData()
}

function agingRowClass({ row }) {
  return row.overdue_amount > 0 ? 'aging-overdue' : ''
}

async function loadAging() {
  agingLoading.value = true
  try {
    const { data } = await api.get('/settlements/summary')
    agingItems.value = data.items || []
  } finally { agingLoading.value = false }
}

onMounted(() => { load(); forecast(); loadPurchases(); loadAging(); loadOpportunityHistory(); loadProductOptions() })
</script>

<style scoped>
:deep(.el-table .aging-overdue td.el-table__cell) { color: #F56C6C; }
</style>
