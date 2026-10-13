<template>
  <div class="listing-flow">
    <!-- 分步导航（顺序冻结于 FLOW_STEPS；由 Listing 状态推导当前步，无断点） -->
    <el-steps :active="current" align-center finish-status="success" class="flow-steps">
      <el-step v-for="step in FLOW_STEPS" :key="step.key" :title="step.label" :description="step.hint" />
    </el-steps>

    <!-- ① 生成 -->
    <div v-if="activeKey === 'generate'" class="flow-body">
      <el-form label-width="90px">
        <el-form-item label="选择商品">
          <el-select v-model="gen.productId" filterable style="width:100%" placeholder="搜索商品标题">
            <el-option v-for="p in products" :key="p.id" :label="`#${p.id} ${p.title}`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标平台">
          <el-select v-model="gen.platform" style="width:100%">
            <el-option v-for="p in PLATFORMS" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="gen.language" style="width:100%">
            <el-option label="英语 en" value="en" /><el-option label="中文 zh" value="zh" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="flow-nav">
        <el-button @click="$emit('exit')">关闭</el-button>
        <el-button type="primary" :loading="generating" :disabled="!canManage" @click="doGenerate">AI 生成</el-button>
      </div>
    </div>

    <!-- ② 编辑预览 -->
    <div v-else-if="activeKey === 'edit'" class="flow-body">
      <el-radio-group v-model="editMode" size="small" class="mb12">
        <el-radio-button value="preview">预览</el-radio-button>
        <el-radio-button value="edit">编辑</el-radio-button>
      </el-radio-group>
      <template v-if="editMode === 'preview'">
        <h4 class="preview-title">{{ listing.title }}</h4>
        <p class="preview-desc">{{ listing.description }}</p>
        <ul class="preview-bullets"><li v-for="(b, i) in listing.bullets" :key="i">{{ b }}</li></ul>
        <el-tag v-for="k in listing.keywords" :key="k" size="small" type="info" class="kw">{{ k }}</el-tag>
      </template>
      <el-form v-else label-width="90px">
        <el-form-item label="标题"><el-input v-model="form.title" maxlength="200" show-word-limit /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="4" /></el-form-item>
        <el-form-item v-for="(b, i) in form.bullets" :key="i" :label="i === 0 ? '卖点' : ''">
          <el-input v-model="form.bullets[i]" :placeholder="`卖点 ${i + 1}`" />
        </el-form-item>
        <el-form-item label="关键词"><el-input v-model="form.keywordsText" placeholder="逗号分隔" /></el-form-item>
      </el-form>
      <div class="flow-nav">
        <el-button @click="go('generate')">上一步</el-button>
        <el-button :loading="optimizing" :disabled="!canManage" @click="doOptimize">AI 优化</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canManage" @click="doSave">保存并进入复核</el-button>
      </div>
    </div>

    <!-- ③ 合规复核 -->
    <div v-else-if="activeKey === 'review'" class="flow-body">
      <div v-loading="reviewing">
        <el-alert v-if="review.decision" :closable="false" show-icon
          :type="review.decision === 'approved' ? 'success' : review.decision === 'rejected' ? 'error' : 'warning'"
          :title="{ approved: '复核通过', rejected: '明确违规，禁止上架', manual_required: '需要合规人员人工审批' }[review.decision]" />
        <el-descriptions v-if="review.decision" :column="2" border size="small" class="mt12">
          <el-descriptions-item label="规则版本">{{ review.rule_version }}</el-descriptions-item>
          <el-descriptions-item label="规则来源">{{ review.evidence?.rule_origin }}</el-descriptions-item>
          <el-descriptions-item label="规则时效">{{ review.evidence?.rule_age_days }} 天</el-descriptions-item>
          <el-descriptions-item label="内容指纹">{{ review.evidence?.content_fingerprint }}</el-descriptions-item>
        </el-descriptions>
        <el-card v-if="review.reasons?.length" shadow="never" class="mt12">
          <div v-for="reason in review.reasons" :key="reason" class="reason-line">• {{ reason }}</div>
        </el-card>
        <el-input v-if="review.decision === 'manual_required' && canApprove()" v-model="approvalNote"
          type="textarea" :rows="3" class="mt12" placeholder="必须填写人工核验依据（审批留痕）" />
        <el-alert v-else-if="review.decision === 'manual_required'" type="info" :closable="false" class="mt12"
          title="等待合规审批人处理；审批通过后才能发布" />
      </div>
      <div class="flow-nav">
        <el-button @click="go('edit')">上一步</el-button>
        <el-button :loading="reviewing" :disabled="!canManage" @click="doReview">执行合规复核</el-button>
        <el-button v-if="review.decision === 'manual_required' && canApprove()" type="primary"
          :loading="approving" :disabled="!approvalNote.trim()" @click="doApprove">批准当前内容</el-button>
        <el-button v-if="review.decision === 'approved'" type="primary" @click="go('publish')">下一步：发布</el-button>
      </div>
    </div>

    <!-- ④ 发布 -->
    <div v-else-if="activeKey === 'publish'" class="flow-body">
      <el-alert v-if="!gate.allowed" type="error" :closable="false" show-icon :title="gate.reason" />
      <el-alert type="info" :closable="false" class="mb12"
        title="提交成功不等于已在售：发布后请到「回执」步骤核验店铺提交结果。" />
      <el-form label-width="90px">
        <el-form-item label="发布目标">
          <el-radio-group v-model="pubTarget">
            <el-radio value="demo">本地模拟（不触达平台）</el-radio>
            <el-radio v-for="s in selectableShops" :key="s.id" :value="s.id">
              {{ s.shop_name }}（{{ shopStatusTag(s.status).text }}）
            </el-radio>
          </el-radio-group>
          <div v-if="!selectableShops.length" class="muted">暂无可用的已授权销售店铺，可先本地模拟</div>
        </el-form-item>
      </el-form>
      <div class="flow-nav">
        <el-button @click="go('review')">上一步</el-button>
        <el-button type="primary" :loading="publishing" :disabled="!canManage || !gate.allowed" @click="doPublish">
          发布
        </el-button>
      </div>
    </div>

    <!-- ⑤ 回执（PublicationReceipts 常驻面板） -->
    <div v-else class="flow-body">
      <PublicationReceipts v-if="listing.id" :listing-id="listing.id" />
      <div class="flow-nav">
        <el-button @click="go('publish')">上一步</el-button>
        <el-button type="primary" @click="$emit('exit')">完成</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * Listing 单页分步流（UX-C J2：生成→编辑预览→合规→发布→回执，无断点）。
 * 步骤推进全部由 listingFlow.js 纯函数推导（deriveFlowStep/publishGate），
 * 组件只消费；动作失败原因经 detail/表单校验直出。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from '../../shared/ui'
import PublicationReceipts from './PublicationReceipts.vue'
import { canApprove, canWrite } from '../../permissions/permissions'
import {
  approveReview as apiApproveReview, generate as apiGenerate, optimize as apiOptimize,
  publish as apiPublish, submitReview, updateListing,
} from '../../api/domains/listings'
import { fetchProducts } from '../../api/domains/products'
import { fetchShops } from '../../api/domains/shops'
import {
  FLOW_STEPS, deriveFlowStep, editFormFromListing, listingPayloadFromForm,
  publishGate, shopSelectable, stepIndex,
} from '../../composables/listingFlow'

const props = defineProps({
  // 外部带入的既有 Listing（列表点「继续分步流」），null=从生成开始。
  listing: { type: Object, default: null },
})
const emit = defineEmits(['exit', 'updated'])

const PLATFORMS = [
  { value: 'tiktok', label: 'TikTok Shop' },
  { value: 'amazon', label: 'Amazon' },
  { value: 'shopee', label: 'Shopee' },
]

const canManage = computed(() => canWrite())
const activeKey = ref('generate')
const current = computed(() => stepIndex(activeKey.value))
const editMode = ref('preview')

const products = ref([])
const shops = ref([])
const listing = ref({})
const gen = ref({ productId: null, platform: 'tiktok', language: 'en' })
const form = ref(editFormFromListing())
const review = ref({})
const approvalNote = ref('')
const pubTarget = ref('demo')
const generating = ref(false)
const saving = ref(false)
const optimizing = ref(false)
const reviewing = ref(false)
const approving = ref(false)
const publishing = ref(false)

const gate = computed(() => publishGate(listing.value))
const selectableShops = computed(() => shops.value.filter(shopSelectable))

function go(key) { activeKey.value = key }

function applyListing(data) {
  listing.value = data || {}
  form.value = editFormFromListing(listing.value)
  emit('updated', listing.value)
}

async function doGenerate() {
  if (!gen.value.productId) return ElMessage.warning('请选择商品')
  generating.value = true
  try {
    const data = await apiGenerate({
      product_id: gen.value.productId, platform: gen.value.platform, language: gen.value.language,
    })
    applyListing(data)
    editMode.value = 'preview'
    activeKey.value = 'edit'
    ElMessage.success('已生成，请在下一步核对与编辑')
  } finally { generating.value = false }
}

async function doSave() {
  if (!String(form.value.title || '').trim()) return ElMessage.warning('标题不能为空')
  saving.value = true
  try {
    const data = await updateListing(listing.value.id, listingPayloadFromForm(form.value))
    applyListing(data)
    activeKey.value = 'review'
  } finally { saving.value = false }
}

async function doOptimize() {
  optimizing.value = true
  try {
    const data = await apiOptimize(listing.value.id)
    applyListing({ ...listing.value, ...data })
    ElMessage.success('AI 优化已应用，请核对预览')
  } finally { optimizing.value = false }
}

async function doReview() {
  reviewing.value = true
  review.value = {}
  try {
    review.value = await submitReview(listing.value.id)
    // 复核结果即时改写门禁（高风险禁发由 publishGate 兜底）
    if (review.value.decision === 'approved' && listing.value.risk_level !== 'high') {
      ElMessage.success('复核通过，可进入发布')
    }
  } finally { reviewing.value = false }
}

async function doApprove() {
  approving.value = true
  try {
    await apiApproveReview(listing.value.id, approvalNote.value.trim())
    ElMessage.success('已批准')
    review.value = { ...review.value, decision: 'approved' }
  } finally { approving.value = false }
}

async function doPublish() {
  publishing.value = true
  try {
    const shopId = pubTarget.value === 'demo' ? null : Number(pubTarget.value)
    const data = await apiPublish(listing.value.id, { shopId })
    applyListing({ ...listing.value, status: data.status || listing.value.status })
    activeKey.value = 'receipts'
    ElMessage.success(shopId ? '已提交到店铺，实际在售请以回执核验为准' : '本地模拟发布完成')
  } finally { publishing.value = false }
}

// 外部切换 Listing（如列表换行）时重放状态推导。
watch(() => props.listing, (val) => {
  if (val && val.id) {
    applyListing(val)
    activeKey.value = deriveFlowStep(val)
    review.value = {}
  }
}, { immediate: true })

onMounted(async () => {
  // 选项数据：失败不阻断分步流（用户仍可查看既有步骤）
  try { products.value = (await fetchProducts({ page: 1 })).items || [] } catch { products.value = [] }
  try { shops.value = (await fetchShops()).items || [] } catch { shops.value = [] }
})
</script>

<style scoped>
.flow-steps { margin-bottom: 16px; }
.flow-body { min-height: 220px; }
.flow-nav { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.preview-title { margin: 0 0 8px; }
.preview-desc { white-space: pre-wrap; color: var(--color-text-regular); }
.preview-bullets { color: var(--color-text-regular); }
.kw { margin: 0 6px 6px 0; }
.reason-line { margin: 5px 0; }
.mt12 { margin-top: 12px; }
.mb12 { margin-bottom: 12px; }
.muted { color: var(--color-text-secondary); font-size: 12px; margin-top: 4px; }
</style>
