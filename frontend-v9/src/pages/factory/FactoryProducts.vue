<template>
  <div class="page">
    <PageHeader :title="supplier.name || '工厂资料'" subtitle="本厂产品 / 价格 / 产能 / 交期维护">
      <template #actions>
        <el-tag :type="verificationTag.type" size="small">{{ verificationTag.text }}</el-tag>
      </template>
    </PageHeader>

    <el-alert type="info" :closable="false" show-icon class="mb16"
      title="您只能维护本厂产品、价格、产能和交期；这些数据不会自动触发上架。"
      description="ERP 运营方完成机会分析、工厂尽调、Listing Agent 复核和人工审批后，才会进入销售平台。" />

    <el-card class="mb16" shadow="never">
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="地区">{{ supplier.region || '—' }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ supplier.supplier_type || 'factory' }}</el-descriptions-item>
        <el-descriptions-item label="能力">{{ (supplier.capabilities || []).join('、') || '待完善' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card>
      <template #header>
        <div class="between">
          <span class="card-title">本厂供给目录</span>
          <el-button v-if="canWrite()" type="primary" size="small" @click="openCreate">新增产品</el-button>
        </div>
      </template>
      <el-table :data="items" v-loading="loading" size="small">
        <el-table-column prop="factory_sku" label="工厂 SKU" width="140" />
        <el-table-column prop="title" label="产品" min-width="200" show-overflow-tooltip />
        <el-table-column prop="category" label="类目" width="120" />
        <el-table-column label="出厂价" width="110">
          <template #default="{ row }">{{ row.currency }} {{ row.unit_price }}</template>
        </el-table-column>
        <el-table-column prop="moq" label="MOQ" width="70" />
        <el-table-column prop="lead_days" label="交期/天" width="80" />
        <el-table-column prop="monthly_capacity" label="月产能" width="90" />
        <el-table-column prop="available_qty" label="可售库存" width="90" />
        <el-table-column prop="status" label="状态" width="80" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button v-if="canWrite()" link type="primary" @click="edit(row)">更新</el-button>
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="还没有供给产品，点击「新增产品」开始维护" /></template>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" :title="form.id ? '更新产品与产能' : '新增工厂产品'" width="620px">
      <el-form label-width="100px">
        <el-form-item label="工厂 SKU"><el-input v-model="form.factory_sku" /></el-form-item>
        <el-form-item label="产品名称"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="类目"><el-input v-model="form.category" /></el-form-item>
        <el-form-item label="能力标签"><el-input v-model="form.capabilityText" placeholder="针织,小单快反,印花" /></el-form-item>
        <el-form-item label="出厂价 / 币种">
          <el-input-number v-model="form.unit_price" :min="0.01" :precision="2" />
          <el-input v-model="form.currency" style="width:90px;margin-left:8px" />
        </el-form-item>
        <el-form-item label="MOQ / 交期">
          <el-input-number v-model="form.moq" :min="1" />
          <el-input-number v-model="form.lead_days" :min="1" style="margin-left:8px" />
        </el-form-item>
        <el-form-item label="月产能 / 库存">
          <el-input-number v-model="form.monthly_capacity" :min="0" />
          <el-input-number v-model="form.available_qty" :min="0" style="margin-left:8px" />
        </el-form-item>
        <el-form-item label="图片链接"><el-input v-model="form.imageText" placeholder="多个链接用逗号分隔" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status">
            <el-option label="有效" value="active" /><el-option label="草稿" value="draft" />
            <el-option label="暂停" value="paused" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :disabled="!canWrite()" @click="save">确认并更新时间</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 工厂门户（UX-E，旧 FactoryPortal.vue 平移 /factory/products）：
 * 供给目录 CRUD 走 factoryNetwork 域 portal 端点；写权限是 supply:write
 * （FACTORY_COLLABORATOR 专属，非 order:write）。表单↔载荷转换见 catalogForm 纯函数。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import EmptyState from '../../components/EmptyState.vue'
import { can } from '../../permissions/permissions'
import {
  createPortalProduct, fetchPortalMe, fetchPortalProducts, updatePortalProduct,
} from '../../api/domains/factoryNetwork'
import { catalogFormToPayload, catalogRowToForm, emptyCatalogForm, VERIFICATION_TAGS } from '../../composables/factoryCatalog'

const supplier = ref({})
const items = ref([])
const loading = ref(false)
const dialog = ref(false)
const form = reactive(emptyCatalogForm())

const canWrite = () => can('supply:write')
const verificationTag = computed(() => VERIFICATION_TAGS[supplier.value.verification_status]
  || { text: supplier.value.verification_status || '未知', type: 'info' })

async function load() {
  loading.value = true
  try {
    const [me, products] = await Promise.all([fetchPortalMe(), fetchPortalProducts()])
    supplier.value = me.supplier || {}
    items.value = products.items || []
  } finally { loading.value = false }
}

function openCreate() {
  Object.assign(form, emptyCatalogForm())
  dialog.value = true
}

function edit(row) {
  Object.assign(form, catalogRowToForm(row))
  dialog.value = true
}

async function save() {
  const payload = catalogFormToPayload(form)
  if (form.id) await updatePortalProduct(form.id, payload)
  else await createPortalProduct(payload)
  ElMessage.success('供给数据已更新并记录确认时间')
  dialog.value = false
  await load()
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.between { display: flex; justify-content: space-between; align-items: center; }
.card-title { font-weight: 600; }
</style>
