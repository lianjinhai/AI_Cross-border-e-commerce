<template>
  <div class="page">
    <PageHeader
      title="到岸成本配置"
      subtitle="关税 / 物流路由 / 平台费率 / 目的国合规 四组配置 · 试算口径与定价页一致"
    >
      <template #actions>
        <router-link to="/app/pricing"><el-button plain>前往动态定价</el-button></router-link>
      </template>
    </PageHeader>

    <!-- 到岸成本试算（与 /pricing/calc 同一套 costing 实现） -->
    <FormSection title="到岸成本试算" description="给出目的国即计入关税/进口 VAT/清关费与路由物流费；口径与利润页同源（T-53）">
      <div class="calc-bar">
        <el-select v-model="calc.product_id" filterable placeholder="选择商品" style="width: 280px">
          <el-option v-for="p in products" :key="p.id" :label="`#${p.id} ${p.title}`" :value="p.id" />
        </el-select>
        <el-input v-model="calc.destination_country" placeholder="目的国（如 US）" style="width: 140px" clearable />
        <el-input v-model="calc.channel_type" placeholder="物流渠道（可选）" style="width: 150px" clearable />
        <el-input v-model="calc.site" placeholder="站点（可选）" style="width: 120px" clearable />
        <el-input-number v-model="calc.qty" :min="1" placeholder="数量" />
        <el-button type="primary" :loading="calcLoading" :disabled="!calc.product_id" @click="doCalc">
          试算
        </el-button>
      </div>
      <el-descriptions v-if="calcResult" :column="4" border size="small" class="mt8">
        <el-descriptions-item v-for="item in calcFields" :key="item.label" :label="item.label">
          {{ item.value }}
        </el-descriptions-item>
      </el-descriptions>
    </FormSection>

    <!-- 四组配置 CRUD（配置驱动；tenant_id 为空的行是平台内置口径，只读） -->
    <el-tabs v-model="activeGroup">
      <el-tab-pane v-for="group in GROUPS" :key="group.key" :label="group.title" :name="group.key" />
    </el-tabs>

    <FormSection :title="currentGroup.title" :description="currentGroup.desc">
      <div class="toolbar">
        <el-button v-if="writable" type="primary" size="small" @click="openCreate">新增{{ currentGroup.title }}</el-button>
      </div>
      <el-table v-loading="loading" :data="rows" size="small">
        <el-table-column
          v-for="field in tableFields" :key="field.prop"
          :prop="field.prop" :label="field.label" :width="field.width" show-overflow-tooltip
        />
        <el-table-column label="归属" width="100">
          <template #default="{ row }">
            <el-tag v-if="isBuiltIn(row)" size="small" type="warning">平台内置</el-tag>
            <el-tag v-else size="small" type="info">本租户</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="writable" label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <template v-if="!isBuiltIn(row)">
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
            <span v-else class="builtin-tip">只读</span>
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="暂无配置行" /></template>
      </el-table>
    </FormSection>

    <!-- 通用新增/编辑弹窗（字段由 group.fields 驱动） -->
    <el-dialog v-model="dialog" :title="`${editing ? '编辑' : '新增'}${currentGroup.title}`" width="560px">
      <el-form label-width="110px">
        <el-form-item
          v-for="field in currentGroup.fields" :key="field.prop"
          :label="field.label" :required="field.required"
        >
          <el-select v-if="field.type === 'select'" v-model="form[field.prop]" style="width: 100%">
            <el-option v-for="opt in field.options" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <el-switch v-else-if="field.type === 'switch'" v-model="form[field.prop]" />
          <el-input-number
            v-else-if="field.type === 'number'" v-model="form[field.prop]"
            :min="field.min ?? 0" :precision="field.precision" style="width: 100%"
          />
          <el-date-picker
            v-else-if="field.type === 'date'" v-model="form[field.prop]"
            type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%"
          />
          <el-input v-else v-model="form[field.prop]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import { can } from '../../permissions/permissions'
import { dutyRates, logisticsRoutes, platformFees, complianceRules, calcLandedCost } from '../../api/domains/crossBorder'
import { fetchProducts } from '../../api/domains/products'

const writable = can('finance:write')

/** 四组配置描述符（列/表单字段单一事实源，新增组只需加配置）。 */
const GROUPS = [
  {
    key: 'dutyRates', title: '关税税率', api: dutyRates,
    desc: '欧盟成员国按 EU 判定关税口径（€3/件）；计税方式支持从价/按件',
    fields: [
      { prop: 'destination_country', label: '目的国', required: true },
      { prop: 'hs_prefix', label: 'HS 前缀' },
      { prop: 'rate_type', label: '计税方式', type: 'select', options: [
        { value: 'ad_valorem', label: '从价（ad_valorem）' },
        { value: 'fixed_per_item', label: '按件（fixed_per_item）' },
      ] },
      { prop: 'rate', label: '税率/税额', type: 'number', precision: 4 },
      { prop: 'currency', label: '币种' },
      { prop: 'de_minimis', label: '免税额度', type: 'number', precision: 2 },
      { prop: 'effective_from', label: '生效起始', type: 'date' },
      { prop: 'note', label: '备注' },
    ],
  },
  {
    key: 'logisticsRoutes', title: '物流路由', api: logisticsRoutes,
    desc: '计费方式支持按重/按体积/按件；含燃油与旺季附加费',
    fields: [
      { prop: 'name', label: '名称', required: true },
      { prop: 'destination_country', label: '目的国' },
      { prop: 'channel_type', label: '渠道类型' },
      { prop: 'billing_method', label: '计费方式', type: 'select', options: [
        { value: 'per_kg', label: '按重（per_kg）' },
        { value: 'per_cbm', label: '按体积（per_cbm）' },
        { value: 'per_item', label: '按件（per_item）' },
      ] },
      { prop: 'first_weight_kg', label: '首重(kg)', type: 'number', precision: 2 },
      { prop: 'first_weight_fee', label: '首重费', type: 'number', precision: 2 },
      { prop: 'additional_per_kg', label: '续重/kg', type: 'number', precision: 2 },
      { prop: 'per_cbm', label: '每立方费', type: 'number', precision: 2 },
      { prop: 'per_item', label: '每件费', type: 'number', precision: 2 },
      { prop: 'min_charge', label: '最低收费', type: 'number', precision: 2 },
      { prop: 'fuel_surcharge_rate', label: '燃油附加率', type: 'number', precision: 4 },
      { prop: 'peak_surcharge_rate', label: '旺季附加率', type: 'number', precision: 4 },
      { prop: 'active', label: '启用', type: 'switch' },
      { prop: 'note', label: '备注' },
    ],
  },
  {
    key: 'platformFees', title: '平台费率', api: platformFees,
    desc: '佣金/交易/服务三费率，按平台+类目+站点生效',
    fields: [
      { prop: 'platform', label: '平台', required: true },
      { prop: 'category', label: '类目' },
      { prop: 'site', label: '站点' },
      { prop: 'commission_rate', label: '佣金率', type: 'number', precision: 4 },
      { prop: 'transaction_rate', label: '交易费率', type: 'number', precision: 4 },
      { prop: 'service_rate', label: '服务费率', type: 'number', precision: 4 },
      { prop: 'effective_from', label: '生效起始', type: 'date' },
      { prop: 'note', label: '备注' },
    ],
  },
  {
    key: 'complianceRules', title: '目的国合规', api: complianceRules,
    desc: '目的国准入要求（认证/标签等），mandatory 为强制项',
    fields: [
      { prop: 'destination_country', label: '目的国', required: true },
      { prop: 'category', label: '类目' },
      { prop: 'requirement', label: '要求', required: true },
      { prop: 'mandatory', label: '强制', type: 'switch' },
      { prop: 'source_url', label: '来源链接' },
      { prop: 'note', label: '备注' },
    ],
  },
]

const activeGroup = ref('dutyRates')
const currentGroup = computed(() => GROUPS.find((g) => g.key === activeGroup.value) || GROUPS[0])
/** 表格列 = 表单字段（备注列收窄；全部展示保持透明）。 */
const tableFields = computed(() => currentGroup.value.fields.map((f) => ({
  prop: f.prop, label: f.label, width: f.type === 'switch' ? 80 : undefined,
})))

const rows = ref([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const form = reactive({})

const products = ref([])
const calc = reactive({ product_id: null, destination_country: '', channel_type: '', site: '', qty: 1 })
const calcLoading = ref(false)
const calcResult = ref(null)

/** 平台内置口径（tenant_id 为空）：租户只读，防止改掉共享税率。 */
function isBuiltIn(row) {
  return row.tenant_id == null
}

function blankForm() {
  const next = {}
  for (const field of currentGroup.value.fields) {
    if (field.type === 'switch') next[field.prop] = field.prop === 'active' || field.prop === 'mandatory'
    else if (field.type === 'number') next[field.prop] = 0
    else if (field.type === 'select') next[field.prop] = field.options[0]?.value ?? ''
    else next[field.prop] = ''
  }
  return next
}

async function load() {
  loading.value = true
  try {
    rows.value = (await currentGroup.value.api.list()).items || []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, blankForm())
  dialog.value = true
}

function openEdit(row) {
  editing.value = row
  Object.assign(form, blankForm(), row)
  dialog.value = true
}

async function save() {
  for (const field of currentGroup.value.fields) {
    if (field.required && (form[field.prop] === '' || form[field.prop] == null)) {
      return ElMessage.warning(`请填写「${field.label}」`)
    }
  }
  saving.value = true
  try {
    if (editing.value) await currentGroup.value.api.update(editing.value.id, { ...form })
    else await currentGroup.value.api.create({ ...form })
    ElMessage.success('已保存')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除该${currentGroup.value.title}配置行？`, '提示', { type: 'warning' })
  } catch { return }
  await currentGroup.value.api.remove(row.id)
  ElMessage.success('已删除')
  load()
}

const CALC_FIELDS = [
  { key: 'price', label: '售价($)', money: true },
  { key: 'purchase_cost', label: '采购成本¥', money: true },
  { key: 'logistics_cost', label: '物流¥', money: true },
  { key: 'duty_cny', label: '关税¥', money: true },
  { key: 'import_vat_cny', label: '进口VAT¥', money: true },
  { key: 'clearance_cny', label: '清关费¥', money: true },
  { key: 'platform_fee', label: '平台费¥', money: true },
  { key: 'payment_fee', label: '支付费¥', money: true },
  { key: 'refund_cost', label: '退货成本¥', money: true },
  { key: 'profit', label: '单件利润$', money: true },
  { key: 'margin', label: '利润率', percent: true },
  { key: 'fx', label: '汇率' },
]

const calcFields = computed(() => (calcResult.value
  ? CALC_FIELDS.filter((f) => calcResult.value[f.key] !== undefined && calcResult.value[f.key] !== null)
    .map((f) => ({
      label: f.label,
      value: f.percent
        ? `${(Number(calcResult.value[f.key]) * 100).toFixed(1)}%`
        : String(calcResult.value[f.key]),
    }))
  : []))

async function doCalc() {
  calcLoading.value = true
  try {
    calcResult.value = await calcLandedCost({ ...calc })
  } finally {
    calcLoading.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    products.value = (await fetchProducts({ page: 1 })).items || []
  } catch { products.value = [] }
})
</script>

<style scoped>
.calc-bar {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-wrap: wrap;
}
.toolbar {
  margin-bottom: var(--space-2);
  display: flex;
  justify-content: flex-end;
}
.builtin-tip {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}
.mt8 {
  margin-top: var(--space-2);
}
</style>
