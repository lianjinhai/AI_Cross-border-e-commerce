<template>
  <div class="page">
    <el-card class="mb16">
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <el-select v-model="q.platform" placeholder="平台" style="width:130px" clearable @change="load">
          <el-option v-for="p in salesPlatforms" :key="p.value" :label="p.label" :value="p.value" />
        </el-select>
        <el-select v-model="q.status" placeholder="状态" style="width:120px" clearable @change="load">
          <el-option label="草稿" value="draft" /><el-option label="已发布" value="published" />
        </el-select>
        <el-button v-if="write" type="primary" @click="openGenerate">AI 生成 Listing</el-button>
      </div>
    </el-card>

    <el-card>
      <el-table :data="items" v-loading="loading" size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="product_title" label="商品" min-width="180" show-overflow-tooltip />
        <el-table-column prop="platform" label="平台" width="90" />
        <el-table-column prop="language" label="语言" width="70" />
        <el-table-column label="模型" width="90">
          <template #default="{ row }">
            <el-tooltip v-if="row.model === 'llm'" content="AI 生成内容，上架前请人工核对" placement="top">
              <el-tag size="small" type="warning">AI生成</el-tag>
            </el-tooltip>
            <el-tag v-else-if="row.model === 'rule'" size="small" type="info">模板</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="Listing 标题" min-width="260" show-overflow-tooltip />
        <el-table-column label="状态" width="90"><template #default="{ row }"><run-status :status="row.status" /></template></el-table-column>
        <el-table-column label="风险" width="80"><template #default="{ row }"><run-status :status="row.risk_level" /></template></el-table-column>
        <el-table-column label="操作" width="255" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="preview(row)">预览</el-button>
            <el-button v-if="write" size="small" type="primary" @click="optimize(row)">AI 优化</el-button>
            <el-button v-if="write" size="small" type="warning" @click="openReview(row)">复核</el-button>
            <el-button v-if="write && row.status !== 'published'" size="small" type="success" @click="publish(row)">发布</el-button>
            <el-button v-if="row.platform === 'walmart' && row.status === 'published' && row.external_id" size="small" @click="checkSubmission(row)">Feed 状态</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" v-model:current-page="page" @current-change="load" />
    </el-card>

    <el-dialog v-model="genDialog" title="AI 生成 Listing" width="520px">
      <el-form label-width="90px">
        <el-form-item label="选择商品">
          <el-select v-model="gen.product_id" filterable style="width:100%" placeholder="搜索商品标题">
            <el-option v-for="p in productOptions" :key="p.id" :label="`#${p.id} ${p.title}`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标平台">
          <el-select v-model="gen.platform">
            <el-option v-for="p in salesPlatforms" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="gen.language">
            <el-option label="英语 en" value="en" /><el-option label="中文 zh" value="zh" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="genDialog = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="generate">生成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reviewDialog" title="上架合规复核" width="680px">
      <div v-loading="reviewLoading">
        <el-alert v-if="reviewResult.decision" show-icon :closable="false"
          :type="reviewResult.decision === 'approved' ? 'success' : reviewResult.decision === 'rejected' ? 'error' : 'warning'"
          :title="{ approved: '复核通过', rejected: '明确违规，禁止上架', manual_required: '需要合规人员人工审批' }[reviewResult.decision]" />
        <el-descriptions v-if="reviewResult.decision" :column="2" border size="small" style="margin-top:12px">
          <el-descriptions-item label="规则版本">{{ reviewResult.rule_version }}</el-descriptions-item>
          <el-descriptions-item label="规则来源">{{ reviewResult.evidence?.rule_origin }}</el-descriptions-item>
          <el-descriptions-item label="规则时效">{{ reviewResult.evidence?.rule_age_days }} 天</el-descriptions-item>
          <el-descriptions-item label="内容指纹">{{ reviewResult.evidence?.content_fingerprint }}</el-descriptions-item>
        </el-descriptions>
        <el-card v-if="reviewResult.reasons?.length" shadow="never" style="margin-top:12px">
          <div v-for="reason in reviewResult.reasons" :key="reason" style="margin:5px 0">• {{ reason }}</div>
        </el-card>
        <el-input v-if="reviewResult.decision === 'manual_required'" v-model="approvalNote"
          type="textarea" :rows="3" style="margin-top:12px" placeholder="必须填写人工核验依据；只有合规审批员或管理员可以批准" />
      </div>
      <template #footer>
        <el-button @click="reviewDialog = false">关闭</el-button>
        <el-button v-if="reviewResult.decision === 'manual_required' && approve" type="primary"
          :loading="approving" :disabled="!approvalNote.trim()" @click="approveReview">批准当前内容与规则版本</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="submissionDialog" title="平台异步提交状态" width="680px"><div v-loading="submissionLoading"><el-alert type="info" :closable="false" title="平台接受 Feed 不等于商品已上架，请以商品级处理结果为准。" class="mb16"/><pre style="white-space:pre-wrap;max-height:440px;overflow:auto">{{ JSON.stringify(submissionResult, null, 2) }}</pre></div></el-dialog>

    <el-dialog v-model="previewDialog" title="Listing 预览 / 编辑" width="640px">
      <div style="margin-bottom:12px">
        <el-radio-group v-model="previewMode" @change="onModeChange">
          <el-radio-button value="preview">预览</el-radio-button>
          <el-radio-button value="edit">编辑</el-radio-button>
        </el-radio-group>
      </div>
      <template v-if="previewRow.id">
        <template v-if="previewMode === 'preview'">
          <h4 style="margin:0 0 8px">{{ previewRow.title }}</h4>
          <p style="white-space:pre-wrap;color:#606266">{{ previewRow.description }}</p>
          <ul style="color:#606266"><li v-for="(b, i) in previewRow.bullets" :key="i">{{ b }}</li></ul>
          <el-tag v-for="k in previewRow.keywords" :key="k" size="small" type="info" style="margin:0 6px 6px 0">{{ k }}</el-tag>
        </template>
        <el-form v-else ref="editFormRef" :model="editForm" label-width="90px">
          <el-form-item label="标题" prop="title" :rules="[{ required: true, message: '标题不能为空', trigger: 'blur' }]">
            <el-input v-model="editForm.title" maxlength="200" show-word-limit placeholder="Listing 标题" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="editForm.description" type="textarea" :rows="4" placeholder="Listing 描述" />
          </el-form-item>
          <el-form-item v-for="(b, i) in editForm.bullets" :key="i" :label="i === 0 ? '卖点' : ''">
            <el-input v-model="editForm.bullets[i]" :placeholder="`卖点 ${i + 1}`" />
          </el-form-item>
          <el-form-item label="关键词">
            <el-input v-model="editForm.keywordsText" type="textarea" :rows="2" placeholder="多个关键词用逗号或换行分隔" />
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <el-button @click="previewDialog = false">关闭</el-button>
        <el-button v-if="previewMode === 'edit'" type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pubDialog" title="选择上架店铺" width="520px">
      <el-alert type="info" show-icon :closable="false" style="margin-bottom:12px"
        :title="`发布 Listing #${pubRow?.id ?? ''}：请选择一个已授权的销售店铺，或本地模拟发布`" />
      <div v-loading="pubLoading">
        <el-radio-group v-model="pubTarget" class="pub-options">
          <el-radio v-for="s in pubShops" :key="s.id" :value="s.id" :disabled="!shopSelectable(s)" border class="pub-option">
            <span class="pub-shop">{{ s.shop_name || `店铺 #${s.id}` }}</span>
            <el-tag size="small" type="info" effect="plain" style="margin-left:6px">{{ s.platform }}</el-tag>
            <el-tag size="small" :type="shopStatusTag(s.status).type" style="margin-left:6px">{{ shopStatusTag(s.status).text }}</el-tag>
          </el-radio>
          <el-radio value="demo" border class="pub-option">
            <span class="pub-shop">不选店铺（本地模拟发布）</span>
            <el-tag size="small" type="info" style="margin-left:6px">demo</el-tag>
          </el-radio>
        </el-radio-group>
        <el-button v-if="selectedRealShop?.platform === 'tiktok'" type="primary" plain
          :loading="checkingReadiness" style="margin-top:12px" @click="checkReadiness">
          检查 TikTok 美国站上架条件
        </el-button>
        <el-alert v-if="readiness" :type="readiness.ready ? 'success' : 'warning'" show-icon
          :closable="false" style="margin-top:12px" :title="readiness.next_action">
          <template #default>
            <div v-for="item in readiness.blockers || []" :key="item">阻断：{{ item }}</div>
            <div v-for="item in readiness.warnings || []" :key="item">提示：{{ item }}</div>
          </template>
        </el-alert>
        <el-empty v-if="!pubLoading && !pubShops.length" description="暂无可用的真实销售店铺，可选择本地模拟发布" :image-size="70" />
      </div>
      <template #footer>
        <el-button @click="pubDialog = false">取消</el-button>
        <el-button type="primary" :loading="publishing" :disabled="publishDisabled" @click="confirmPublish">
          {{ publishDisabled ? '真实发布尚未开放' : '确认发布' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
import { canApprove, canWrite, can } from '../permissions'
import RunStatus from './RunStatus.vue'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const q = reactive({ platform: '', status: '' })
const genDialog = ref(false)
const generating = ref(false)
const previewDialog = ref(false)
const previewRow = ref({})
const previewMode = ref('preview')
const editFormRef = ref()
const editForm = ref({ title: '', description: '', bullets: ['', '', '', '', ''], keywordsText: '' })
const saving = ref(false)
const productOptions = ref([])
const salesPlatforms = [
  { value: 'tiktok', label: 'TikTok Shop 美国站' },
  { value: 'shopee', label: 'Shopee 新加坡站' },
  { value: 'amazon', label: 'Amazon 美国站（待接入）' },
  { value: 'ebay', label: 'eBay 美国站' },
  { value: 'walmart', label: 'Walmart 美国站' },
  { value: 'lazada', label: 'Lazada 东南亚' },
]
const gen = reactive({ product_id: null, platform: 'tiktok', language: 'en' })
const reviewDialog = ref(false)
const reviewLoading = ref(false)
const reviewRow = ref(null)
const reviewResult = ref({})
const approvalNote = ref('')
const approving = ref(false)

const pubDialog = ref(false)
const pubRow = ref(null)
const pubShops = ref([])
const pubLoading = ref(false)
const pubTarget = ref('demo')
const publishing = ref(false)
const checkingReadiness = ref(false)
const readiness = ref(null)
const write = can('listing:write'), approve = canApprove()
const submissionDialog = ref(false), submissionLoading = ref(false), submissionResult = ref({})
const selectedRealShop = computed(() => pubShops.value.find(s => s.id === pubTarget.value))
const publishDisabled = computed(() => Boolean(
  selectedRealShop.value && selectedRealShop.value.capabilities?.can_publish === false))
watch(pubTarget, () => { readiness.value = null })

const SHOP_STATUS = {
  authorized: { text: '已授权·可选', type: 'success' },
  pending: { text: '未授权', type: 'info' },
  failed: { text: '授权失败', type: 'danger' },
  expired: { text: '已过期', type: 'warning' },
}
const shopStatusTag = (s) => SHOP_STATUS[s] || { text: s || '未知', type: 'info' }
const shopSelectable = (s) => s.status === 'authorized' && (
  s.capabilities?.can_publish !== false || s.capabilities?.can_listing_readiness === true)

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/listings', { params: { ...q, page_num: page.value, page_size: pageSize } })
    items.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

async function openGenerate() {
  genDialog.value = true
  const { data } = await api.get('/products', { params: { page_num: 1, page_size: 50 } })
  productOptions.value = data.items
}

async function generate() {
  if (!gen.product_id) return ElMessage.warning('请选择商品')
  generating.value = true
  try {
    const { data } = await api.post('/listings/generate', gen)
    // M2：展示生成时引用的知识与规则版本（可追溯）
    const refs = (data.knowledge_refs || []).length
    ElMessage.success(`Listing 已生成（规则版本 ${data.rule_version || '-'}，引用 ${refs} 篇知识）`)
    if (data.needs_review) {
      ElMessage.warning('该文案未通过规则自检，请人工复核后再发布')
    }
    genDialog.value = false
    load()
  } finally { generating.value = false }
}

function preview(row) {
  previewRow.value = row
  previewMode.value = 'preview'
  previewDialog.value = true
}

function onModeChange(val) {
  if (val === 'edit') initEditForm()
}

function initEditForm() {
  const r = previewRow.value || {}
  const bullets = Array.isArray(r.bullets) ? r.bullets.slice(0, 5).map(b => (b == null ? '' : String(b))) : []
  while (bullets.length < 5) bullets.push('')
  const keywords = Array.isArray(r.keywords) ? r.keywords : []
  editForm.value = {
    title: r.title || '',
    description: r.description || '',
    bullets,
    keywordsText: keywords.join(', ')
  }
}

async function saveEdit() {
  const valid = await editFormRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    await api.put(`/listings/${previewRow.value.id}`, {
      title: editForm.value.title.trim(),
      description: editForm.value.description,
      bullets: editForm.value.bullets.map(b => b.trim()).filter(Boolean),
      keywords: editForm.value.keywordsText.split(/[,，\n]/).map(s => s.trim()).filter(Boolean)
    })
    ElMessage.success('已保存')
    previewDialog.value = false
    load()
  } finally { saving.value = false }
}

async function optimize(row) {
  await api.post(`/listings/${row.id}/optimize`)
  ElMessage.success('已按最新关键词优化标题')
  load()
}

async function openReview(row) {
  reviewRow.value = row
  reviewResult.value = {}
  approvalNote.value = ''
  reviewDialog.value = true
  reviewLoading.value = true
  try {
    const { data } = await api.post(`/listings/${row.id}/review`)
    reviewResult.value = data
  } finally { reviewLoading.value = false }
}

async function approveReview() {
  if (!reviewRow.value || !approvalNote.value.trim()) return
  approving.value = true
  try {
    await api.post(`/listings/${reviewRow.value.id}/review/approve`, { note: approvalNote.value.trim() })
    ElMessage.success('审批已记录；内容或规则版本变化后需要重新审批')
    reviewDialog.value = false
  } finally { approving.value = false }
}

async function publish(row) {
  if (row.risk_level === 'high') {
    ElMessage.error('该 Listing 为高风险，复核门禁禁止发布；请先修改内容并重新检测')
    return
  }
  pubRow.value = row
  pubTarget.value = 'demo'
  pubShops.value = []
  pubDialog.value = true
  pubLoading.value = true
  try {
    const { data } = await api.get('/shops')
    pubShops.value = (data.items || []).filter((s) => s.role === 'sales' && !s.is_demo)
  } finally { pubLoading.value = false }
}

async function confirmPublish() {
  if (!pubRow.value) return
  publishing.value = true
  try {
    const body = pubTarget.value === 'demo' ? {} : { shop_id: pubTarget.value }
    const { data } = await api.post(`/listings/${pubRow.value.id}/publish`, body)
    const srcLabel = { api: '平台真实上架', demo: '演示店铺', local: '本地模拟' }[data.source] || data.source
    ElMessage.success(`发布成功（${srcLabel}）单号 ${data.external_id}`)
    pubDialog.value = false
    load()
  } finally { publishing.value = false }
}

async function checkReadiness() {
  if (!selectedRealShop.value || !pubRow.value) return
  checkingReadiness.value = true
  try {
    const { data } = await api.get(`/shops/${selectedRealShop.value.id}/listing_readiness/${pubRow.value.id}`)
    readiness.value = data
    if (data.ready) ElMessage.success('实时上架条件预检通过')
  } finally { checkingReadiness.value = false }
}

async function checkSubmission(row) {
  submissionDialog.value = true; submissionLoading.value = true; submissionResult.value = {}
  try {
    const { data } = await api.get('/shops')
    const shop = (data.items || []).find(s => s.platform === row.platform && s.status === 'authorized' && !s.is_demo)
    if (!shop) throw new Error('没有可查询该提交状态的已授权 Walmart 店铺')
    submissionResult.value = (await api.get(`/shops/${shop.id}/submissions/${row.external_id}`)).data
  } catch (e) { submissionResult.value = { error: e.response?.data?.detail || e.message } }
  finally { submissionLoading.value = false }
}

onMounted(load)
</script>

<style scoped>
.pub-options { display: flex; flex-direction: column; gap: 8px; align-items: stretch; }
.pub-option { margin-right: 0; height: auto; padding: 10px 12px; }
.pub-shop { font-weight: 500; }
</style>
