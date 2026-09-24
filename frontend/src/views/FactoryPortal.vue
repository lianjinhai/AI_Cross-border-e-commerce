<template>
  <div class="page">
    <el-alert type="info" :closable="false" show-icon class="mb16"
      title="您只能维护本厂产品、价格、产能和交期；这些数据不会自动触发上架。"
      description="ERP 运营方完成机会分析、工厂尽调、Listing Agent 复核和人工审批后，才会进入销售平台。" />
    <el-card class="mb16">
      <template #header>
        <div class="header-row"><span>{{ supplier.name || '工厂资料' }}</span>
          <el-tag :type="supplier.verification_status === 'verified' ? 'success' : 'warning'">
            {{ statusText[supplier.verification_status] || supplier.verification_status }}
          </el-tag>
        </div>
      </template>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="地区">{{ supplier.region || '—' }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ supplier.supplier_type || 'factory' }}</el-descriptions-item>
        <el-descriptions-item label="能力">{{ (supplier.capabilities || []).join('、') || '待完善' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
    <el-card>
      <template #header><div class="header-row"><span>本厂供给目录</span>
        <el-button v-if="canWrite" type="primary" size="small" @click="openCreate">新增产品</el-button></div></template>
      <el-table :data="items" v-loading="loading" size="small">
        <el-table-column prop="factory_sku" label="工厂 SKU" width="140" />
        <el-table-column prop="title" label="产品" min-width="200" />
        <el-table-column prop="category" label="类目" width="120" />
        <el-table-column label="出厂价" width="110"><template #default="{ row }">{{ row.currency }} {{ row.unit_price }}</template></el-table-column>
        <el-table-column prop="moq" label="MOQ" width="70" />
        <el-table-column prop="lead_days" label="交期/天" width="80" />
        <el-table-column prop="monthly_capacity" label="月产能" width="90" />
        <el-table-column prop="available_qty" label="可售库存" width="90" />
        <el-table-column prop="status" label="状态" width="80" />
        <el-table-column label="操作" width="80"><template #default="{ row }">
          <el-button v-if="canWrite" link type="primary" @click="edit(row)">更新</el-button>
        </template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialog" :title="form.id ? '更新产品与产能' : '新增工厂产品'" width="620px">
      <el-form label-width="100px">
        <el-form-item label="工厂 SKU"><el-input v-model="form.factory_sku" /></el-form-item>
        <el-form-item label="产品名称"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="类目"><el-input v-model="form.category" /></el-form-item>
        <el-form-item label="能力标签"><el-input v-model="form.capabilityText" placeholder="针织,小单快反,印花" /></el-form-item>
        <el-form-item label="出厂价 / 币种"><el-input-number v-model="form.unit_price" :min="0.01" :precision="2" /> <el-input v-model="form.currency" style="width:90px;margin-left:8px" /></el-form-item>
        <el-form-item label="MOQ / 交期"><el-input-number v-model="form.moq" :min="1" /> <el-input-number v-model="form.lead_days" :min="1" style="margin-left:8px" /></el-form-item>
        <el-form-item label="月产能 / 库存"><el-input-number v-model="form.monthly_capacity" :min="0" /> <el-input-number v-model="form.available_qty" :min="0" style="margin-left:8px" /></el-form-item>
        <el-form-item label="图片链接"><el-input v-model="form.imageText" placeholder="多个链接用逗号分隔" /></el-form-item>
        <el-form-item label="状态"><el-select v-model="form.status"><el-option label="有效" value="active" /><el-option label="草稿" value="draft" /><el-option label="暂停" value="paused" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :disabled="!canWrite" @click="save">确认并更新时间</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
const canWrite = can('supply:write')
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
// 工厂伙伴的写权限是 supply:write（不是通用的 order:write）——
// 后端 ROLE_PERMISSIONS[FACTORY_COLLABORATOR] 只授予 supply:read/supply:write
import { can } from '../permissions'

const supplier = ref({})
const items = ref([])
const loading = ref(false)
const dialog = ref(false)
const statusText = { candidate: '候选', contacting: '接洽中', verified: '已尽调', rejected: '未通过', suspended: '已暂停' }
const empty = () => ({ id: null, factory_sku: '', title: '', category: '', capabilityText: '',
  unit_price: 1, currency: 'CNY', moq: 1, lead_days: 7, monthly_capacity: 0,
  available_qty: 0, imageText: '', status: 'active', attrs: {} })
const form = reactive(empty())

async function load() {
  loading.value = true
  try {
    const [me, products] = await Promise.all([api.get('/factory-network/portal/me'), api.get('/factory-network/portal/products')])
    supplier.value = me.data.supplier
    items.value = products.data.items
  } finally { loading.value = false }
}
function openCreate() { Object.assign(form, empty()); dialog.value = true }
function edit(row) { Object.assign(form, row, { capabilityText: (row.capabilities || []).join(','), imageText: (row.images || []).join(',') }); dialog.value = true }
async function save() {
  const body = { factory_sku: form.factory_sku, title: form.title, category: form.category,
    capabilities: form.capabilityText.split(/[,，]/).map(x => x.trim()).filter(Boolean), attrs: form.attrs || {},
    images: form.imageText.split(/[,，]/).map(x => x.trim()).filter(Boolean), unit_price: form.unit_price,
    currency: form.currency, moq: form.moq, lead_days: form.lead_days,
    monthly_capacity: form.monthly_capacity, available_qty: form.available_qty, status: form.status }
  if (form.id) await api.put(`/factory-network/portal/products/${form.id}`, body)
  else await api.post('/factory-network/portal/products', body)
  ElMessage.success('供给数据已更新并记录确认时间')
  dialog.value = false
  load()
}
onMounted(load)
</script>

<style scoped>
.header-row { display:flex; justify-content:space-between; align-items:center; }
</style>
