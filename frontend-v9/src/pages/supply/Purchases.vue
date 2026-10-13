<template>
  <div class="page">
    <PageHeader title="采购单" subtitle="旧供应商页 4-tab 拆分独立页 · 支持按预测一键生成">
      <template #actions>
        <el-button v-if="writable" type="primary" :loading="pfLoading" @click="genFromForecast">
          从补货预警一键生成
        </el-button>
        <el-button v-if="writable" type="primary" plain @click="openPoDialog">新建采购单</el-button>
      </template>
      <template #filters>
        <el-select v-model="status" placeholder="全部状态" clearable style="width: 140px">
          <el-option v-for="(v, s) in PO_STATUS" :key="s" :label="v.text" :value="s" />
        </el-select>
      </template>
    </PageHeader>

    <FormSection title="采购单列表" description="状态机：草稿 → 已提交 → 已入库（草稿/已提交可取消；提交需供应商已尽调）">
      <DataTable :columns="columns" :loader="load" :reload-key="reloadKey" :empty-reason="'NO_DATA'" empty-hint="暂无采购单">
        <template #cell-status="{ row }">
          <el-tag size="small" :type="poStatusTag(row.status).type">{{ poStatusTag(row.status).label }}</el-tag>
        </template>
        <template #cell-unit_price="{ row }">¥{{ row.unit_price }}</template>
        <template #cell-total="{ row }">¥{{ row.total }}</template>
        <template #cell-actions="{ row }">
          <el-button
            v-for="act in poActions(row.status)"
            :key="act.action"
            :type="act.type" link size="small"
            @click="onAction(row, act.action)"
          >
            {{ act.label }}
          </el-button>
        </template>
      </DataTable>
    </FormSection>

    <!-- 新建采购单 -->
    <el-dialog v-model="poDialog" title="新建采购单" width="480px">
      <el-form label-width="90px">
        <el-form-item label="商品ID" required>
          <el-input-number v-model="poForm.product_id" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="供应商">
          <el-select v-model="poForm.supplier_id" filterable clearable placeholder="缺省自动选最优货源" style="width: 100%">
            <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量" required>
          <el-input-number v-model="poForm.qty" :min="1" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="poForm.note" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="poDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createPo">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import DataTable from '../../components/DataTable.vue'
import { can } from '../../permissions/permissions'
import {
  fetchPurchases, createPurchase, generateFromForecast, updatePurchase, receivePurchase, removePurchase,
} from '../../api/domains/purchases'
import { fetchSuppliers } from '../../api/domains/suppliers'
import { PO_STATUS, poStatusTag, poActions } from '../../features/supply/purchaseStateMachine'

const writable = can('purchase:write') || can('supply:write')

const columns = [
  { prop: 'po_no', label: '采购单号', minWidth: 150 },
  { prop: 'supplier_name', label: '供应商', minWidth: 120 },
  { prop: 'product_title', label: '商品', minWidth: 140 },
  { prop: 'qty', label: '数量', width: 70 },
  { prop: 'unit_price', label: '单价', width: 90 },
  { prop: 'total', label: '总额', width: 100 },
  { prop: 'expected_date', label: '期望到货', width: 110 },
  { prop: 'status', label: '状态', width: 90 },
  { prop: 'note', label: '备注', minWidth: 120 },
  { prop: 'actions', label: '操作', width: 170, fixed: 'right' },
]

const status = ref('')
const reloadKey = ref(0)
const suppliers = ref([])
const poDialog = ref(false)
const saving = ref(false)
const pfLoading = ref(false)
const poForm = reactive({ product_id: undefined, supplier_id: undefined, qty: 1, note: '' })

async function load({ page }) {
  return fetchPurchases({ page, status: status.value })
}

function touch() {
  reloadKey.value += 1
}

async function genFromForecast() {
  pfLoading.value = true
  try {
    const data = await generateFromForecast({})
    const created = data.created || []
    const skipped = data.skipped || []
    if (!created.length) {
      ElMessage.warning(
        `未生成采购单：${skipped[0]?.reason || '无缺货风险或预测商用门禁未通过'}`)
      return
    }
    ElMessage.success(`已生成 ${created.length} 张采购单（跳过 ${skipped.length} 项）`)
    touch()
  } finally {
    pfLoading.value = false
  }
}

function openPoDialog() {
  Object.assign(poForm, { product_id: undefined, supplier_id: undefined, qty: 1, note: '' })
  poDialog.value = true
}

async function createPo() {
  if (!poForm.product_id || !poForm.qty) return ElMessage.warning('请填写商品ID和数量')
  saving.value = true
  try {
    await createPurchase({
      product_id: poForm.product_id,
      supplier_id: poForm.supplier_id || null,
      qty: poForm.qty,
      note: poForm.note,
    })
    ElMessage.success('采购单已创建')
    poDialog.value = false
    touch()
  } finally {
    saving.value = false
  }
}

async function onAction(row, action) {
  if (action === 'submit') {
    await updatePurchase(row.id, { status: 'submitted' })
    ElMessage.success(`采购单 ${row.po_no} 已提交`)
  } else if (action === 'receive') {
    const data = await receivePurchase(row.id, {})
    ElMessage.success(`入库 ${data.in_stock_added} 件，当前库存 ${data.onhand_now}`)
  } else if (action === 'cancel') {
    try {
      await ElMessageBox.confirm(`确定取消采购单 ${row.po_no}？`, '提示', { type: 'warning' })
    } catch { return }
    await removePurchase(row.id)
    ElMessage.success('采购单已取消')
  }
  touch()
}

onMounted(async () => {
  try {
    suppliers.value = (await fetchSuppliers()).items || []
  } catch { suppliers.value = [] }
})
</script>
