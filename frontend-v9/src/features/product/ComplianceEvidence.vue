<template>
  <el-card shadow="never" class="ce">
    <template #header>
      <div class="ce__head">
        <div>
          <span class="ce__title">目的国合规要求与证据</span>
          <span class="ce__sub">标签与上线都靠这里的证据说话：要求来自合规档案，证据是本商品实际取得的认证</span>
        </div>
        <div class="ce__tools">
          <el-select v-model="country" size="small" style="width:110px" placeholder="目的国" @change="load">
            <el-option v-for="item in MARKETS" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-if="shops.length" v-model="shopId" size="small" style="width:180px"
            placeholder="店铺（看标签版本）" @change="load">
            <el-option label="全部店铺" :value="0" />
            <el-option v-for="item in shops" :key="item.id" :label="item.label" :value="item.id" />
          </el-select>
          <el-button size="small" link @click="load">刷新</el-button>
        </div>
      </div>
    </template>

    <div v-if="!country" class="ce__hint">{{ NO_COUNTRY_HINT }}</div>

    <el-alert v-if="error" type="error" :closable="false" show-icon class="mb12" :title="`合规依据加载失败：${error}`"
      description="下方不显示任何「已具备」结论——查不到依据时按未通过处理，不做乐观假设。" />

    <template v-if="view">
      <el-alert v-if="view.complete" type="success" :closable="false" show-icon class="mb12"
        :title="view.headline" description="依据齐备只代表可以生成标签包；认证是否真实由证据引用本身负责。" />
      <el-alert v-else-if="!view.covered" type="warning" :closable="false" show-icon class="mb12"
        :title="view.headline" :description="view.reasons.join('；')" />
      <el-alert v-else type="error" :closable="false" show-icon class="mb12"
        :title="view.headline" :description="view.reasons.join('；')" />

      <el-table v-if="view.rows.length" :data="view.rows" size="small">
        <el-table-column prop="requirement" label="准入要求" min-width="110" />
        <el-table-column label="强制" width="70">
          <template #default="{ row }">{{ row.mandatory ? '强制' : '非强制' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.tone" effect="light">{{ row.stateText }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="证据引用" min-width="170">
          <template #default="{ row }">
            <span :class="{ 'ce__gap': !row.evidenceRef }">{{ row.evidenceRef || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="有效期至" width="110">
          <template #default="{ row }">
            <span :class="{ 'ce__gap': row.state === 'EXPIRED' }">{{ row.validUntil || '长期' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="说明" min-width="200" show-overflow-tooltip />
      </el-table>
      <el-empty v-else :image-size="60"
        :description="view.covered ? '该国没有适用于本商品类目的要求' : `${view.country} 暂无收录的准入要求`" />

      <div class="ce__actions">
        <el-button v-if="canWrite() && view.canRegisterEvidence" size="small" type="primary" plain
          @click="openDialog">补录 / 更新证据</el-button>
        <span class="ce__note">
          这里补的是<strong>目的国准入证据</strong>。标签包本身不能在这里生成——它必须走上线流程里的
          GENERATE_LABEL（依据门禁 + 版本 CAS），避免出现绕过门禁的第二个写入口。
        </span>
      </div>
    </template>

    <SectionState v-else :state="state" :error="error" empty-hint="" />

    <!-- 标签包版本（只读）：说清「印出去过哪几版、当时依据是什么」 -->
    <div v-if="country" class="ce__label">
      <div class="ce__label-head">
        <span>标签包版本（只增不改）</span>
        <span v-if="packageCurrent === true" class="ce__ok">依据仍当前</span>
        <span v-else-if="packageCurrent === false" class="ce__gap">依据已失效，需在流程内重新生成</span>
      </div>
      <el-table v-if="labelRows.length" :data="labelRows" size="small">
        <el-table-column label="版本" width="70">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column prop="action" label="来源动作" width="120" />
        <el-table-column prop="country" label="目的国" width="80" />
        <el-table-column label="认证声明" min-width="140">
          <template #default="{ row }">{{ row.marks.length ? row.marks.join('、') : '（无认证声明）' }}</template>
        </el-table-column>
        <el-table-column label="内容摘要" width="130">
          <template #default="{ row }"><code>{{ row.shortDigest }}</code></template>
        </el-table-column>
        <el-table-column label="印刷前待补" min-width="200">
          <template #default="{ row }">
            <el-tag v-if="row.openItemCount" size="small" type="warning" effect="plain">
              {{ row.openItemCount }} 项需人工补全
            </el-tag>
            <el-tag v-else size="small" type="success" effect="plain">无</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="createdAt" label="生成时间" width="170" />
      </el-table>
      <el-empty v-else :image-size="50"
        description="还没有标签包：在上线流程的「标签准备」步骤执行生成标签" />
      <div v-if="labelRows.length && labelRows[0].openItems.length" class="ce__open-items">
        最新一版的印刷待补项：{{ labelRows[0].openItems.join('；') }}
      </div>
    </div>
  </el-card>

  <el-dialog v-model="dialog" title="登记目的国合规证据" width="540px">
    <el-form label-width="96px" @submit.prevent>
      <el-form-item label="目的国">
        <el-input :model-value="form.destination_country" readonly />
      </el-form-item>
      <el-form-item label="准入要求" required>
        <el-select v-model="form.requirement" filterable allow-create default-first-option
          placeholder="选择缺项，或填写该国实际要求的认证项" style="width:100%">
          <el-option v-for="row in candidateRequirements" :key="row.requirement"
            :label="`${row.requirement}（${row.stateText}）`" :value="row.requirement" />
        </el-select>
      </el-form-item>
      <el-form-item label="证据引用" required>
        <el-input v-model="form.evidence_ref" placeholder="证书编号 / 合规文件链接（不能留空，空引用等于没有证据）" />
      </el-form-item>
      <el-form-item label="有效期至">
        <el-date-picker v-model="form.valid_until" type="date" value-format="YYYY-MM-DD"
          placeholder="不填表示长期有效" style="width:100%" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.note" type="textarea" :rows="2" placeholder="发证机构 / 覆盖型号等" />
      </el-form-item>
    </el-form>
    <el-alert v-if="formGaps.length" type="warning" :closable="false" show-icon
      :title="formGaps.join('；')" />
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="formGaps.length > 0" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'

import SectionState from '../../components/SectionState.vue'
import { labelPackages, saveComplianceEvidence } from '../../api/domains/crossBorder'
import { canWrite } from '../../permissions/permissions'
import { ElMessage } from '../../shared/ui'
import {
  NO_COUNTRY_HINT, complianceBasisView, evidenceFormGaps, evidencePayload, labelHistoryView,
} from '../../shared/complianceView'

/**
 * 目的国合规要求与证据（M2-E）。
 *
 * 为什么要有这一块：标签依据不足时，阻断码 `LABEL_BASIS_MISSING` 指向「商品详情」。
 * 如果商品详情页没有能补证据的地方，这个入口就又是一次「指路指错」——
 * 所以补齐入口与补齐页面必须同时存在，否则不如不给入口。
 *
 * 红线：
 * - 只说后端给的事实。`covered=false`（该国要求未收录）显式写成「未知 ≠ 无需认证」；
 * - 加载失败时不显示任何「已具备」结论（fail-closed），不做乐观假设；
 * - 不回显虚假的认证：认证声明只来自证据引用的 `evidence_ref`。
 */
const props = defineProps({
  productId: { type: [Number, String], required: true },
  shops: { type: Array, default: () => [] },        // [{id, label}]
  defaultCountry: { type: String, default: '' },
})

/** 常用目的国（仅作输入便利，不改变「未收录即未知」的判定）。 */
const MARKETS = [
  { label: '德国 DE', value: 'DE' }, { label: '法国 FR', value: 'FR' },
  { label: '英国 GB', value: 'GB' }, { label: '美国 US', value: 'US' },
  { label: '日本 JP', value: 'JP' }, { label: '韩国 KR', value: 'KR' },
  { label: '新加坡 SG', value: 'SG' }, { label: '马来西亚 MY', value: 'MY' },
]

const country = ref(String(props.defaultCountry || '').toUpperCase())
const shopId = ref(0)
const basis = ref(null)
const items = ref([])
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const form = reactive({ destination_country: '', requirement: '', evidence_ref: '', valid_until: '', note: '' })

const view = computed(() => complianceBasisView(basis.value))
const labelRows = computed(() => labelHistoryView(items.value))
const packageCurrent = computed(() => (basis.value ? basis.value.package_current : undefined))
const state = computed(() => (loading.value ? 'LOADING' : (error.value ? 'ERROR' : 'EMPTY')))
const formGaps = computed(() => evidenceFormGaps(form))
const candidateRequirements = computed(() => (view.value ? view.value.rows : []))

watch(() => props.defaultCountry, (value) => {
  const next = String(value || '').toUpperCase()
  if (next && next !== country.value) { country.value = next; load() }
})

async function load() {
  if (!country.value) { basis.value = null; items.value = []; return }
  loading.value = true
  error.value = ''
  try {
    const data = await labelPackages(props.productId, { country: country.value, shopId: shopId.value })
    basis.value = data.basis || null
    items.value = data.items || []
  } catch (err) {
    // fail-closed：清空依据，宁可什么都不显示，也不留上一轮的绿勾误导人。
    basis.value = null
    items.value = []
    error.value = err?.response?.data?.detail?.message || err?.message || '未知错误'
  } finally {
    loading.value = false
  }
}

function openDialog() {
  form.destination_country = view.value?.country || country.value
  const first = candidateRequirements.value.find((row) => row.state !== 'SATISFIED')
  form.requirement = first ? first.requirement : ''
  form.evidence_ref = ''
  form.valid_until = ''
  form.note = ''
  dialog.value = true
}

async function save() {
  if (formGaps.value.length) return
  saving.value = true
  try {
    await saveComplianceEvidence(props.productId, evidencePayload({ ...form, destination_country: country.value }))
    ElMessage.success('证据已登记')
    dialog.value = false
    await load()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail?.message || '登记失败')
  } finally {
    saving.value = false
  }
}

load()
</script>

<style scoped>
.ce { margin-bottom: 16px; }
.ce__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.ce__title { font-weight: 600; font-size: 14px; }
.ce__sub { display: block; font-size: 12px; color: var(--color-text-secondary); margin-top: 2px; }
.ce__tools { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.ce__hint { font-size: 12px; color: var(--color-text-secondary); }
.ce__actions { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.ce__note { font-size: 12px; color: var(--color-text-secondary); line-height: 1.5; }
.ce__gap { color: var(--color-danger); }
.ce__ok { color: var(--color-success); font-size: 12px; }
.ce__label { margin-top: 16px; border-top: 1px solid var(--color-border-light); padding-top: 12px; }
.ce__label-head { display: flex; align-items: baseline; gap: 10px; font-weight: 600; font-size: 13px; margin-bottom: 8px; }
.ce__open-items { margin-top: 8px; font-size: 12px; color: var(--color-warning); line-height: 1.5; }
.mb12 { margin-bottom: 12px; }
</style>
