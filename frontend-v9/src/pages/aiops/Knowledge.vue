<template>
  <div class="page">
    <PageHeader title="知识库" subtitle="文档管理与语义检索 · 客服知识候选审批（与智能客服互跳）">
      <template #actions>
        <el-button plain @click="goSupport">去智能客服处理会话</el-button>
        <el-button v-if="writable" type="success" plain @click="openEdit()">新增文档</el-button>
      </template>
    </PageHeader>

    <SectionState :state="docState" :error="error" :trace-id="traceId" @retry="loadAll">
      <!-- 搜索置顶（矩阵 #21：文档搜索置顶，RAG 命中置顶展示） -->
      <FormSection title="语义检索" description="基于向量检索（RAG），命中结果按相关度置顶展示">
        <div class="search-bar">
          <el-input
            v-model="q" placeholder="搜索知识库（如：违禁词 / 佣金 / 退货）"
            style="width: 340px" clearable @keyup.enter="search"
          />
          <el-button type="primary" :loading="searching" @click="search">检索</el-button>
        </div>
        <el-alert
          v-if="searchResults.length" type="success" :closable="false" class="mt8"
          :title="`检索到 ${searchResults.length} 篇相关文档（RAG 检索结果，按相关度排序）`"
        />
        <el-card
          v-for="d in searchResults" :key="d.id" shadow="never" class="hit-card"
        >
          <b>{{ d.title }}</b>
          <el-tag size="small" type="info" class="hit-score">相关度 {{ d.score }}</el-tag>
          <p class="hit-content">{{ d.content }}</p>
        </el-card>
      </FormSection>

      <!-- 知识文档 -->
      <FormSection title="知识文档" description="RAG 检索语料；删除被候选引用的文档时后端会自动解除引用">
        <el-table :data="items" v-loading="docsLoading" size="small">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
          <el-table-column label="来源" width="130">
            <template #default="{ row }">
              <el-tag v-if="docSourceLabel(row.source)" size="small" :type="row.source === 'auto_learned' ? 'success' : 'primary'">
                {{ docSourceLabel(row.source) }}
              </el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="标签" width="180">
            <template #default="{ row }">
              <el-tag v-for="t in row.tags" :key="t" size="small" class="tag-gap">{{ t }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '是' : '否' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button v-if="writable" size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="暂无知识文档" /></template>
        </el-table>
        <el-pagination
          class="pager" layout="total, prev, pager, next" :total="total"
          :page-size="pageSize" :current-page="page" @current-change="onPageChange"
        />
      </FormSection>
    </SectionState>

    <!-- 知识候选（客服未命中问题沉淀；自动学习设置按矩阵并入本域） -->
    <FormSection title="知识候选（AI 学习）" description="买家提问未命中知识库时自动沉淀；只沉淀人工验证过的答案（AI 不自行编造）">
      <SectionState :state="candState" :error="candError" @retry="loadCandidates">
        <el-alert
          :title="learning.hint || '自动学习已关闭：候选仅累积，需人工采纳'" :closable="false"
          class="mb8" :type="learning.auto_learn_enabled ? 'success' : 'info'"
        />
        <div class="learning-bar">
          <span>自动学习</span>
          <el-switch
            v-model="learning.auto_learn_enabled" :disabled="!writable"
            @change="saveLearning"
          />
          <span class="ml8">触发阈值（出现次数）</span>
          <el-input-number
            v-model="learning.auto_learn_threshold" :min="2" :max="100"
            size="small" :disabled="!writable" @change="saveLearning"
          />
          <el-tag size="small" type="warning">仅对「人工已验证答案」的问题生效</el-tag>
        </div>
        <div class="filter-bar">
          <el-select v-model="candidateFilter" placeholder="全部状态" clearable style="width: 150px" @change="loadCandidates">
            <el-option label="待处理" value="pending" />
            <el-option label="已采纳" value="approved" />
            <el-option label="AI 已固化" value="auto_learned" />
            <el-option label="已拒绝" value="rejected" />
          </el-select>
        </div>
        <el-table :data="candidates" v-loading="candLoading" size="small">
          <el-table-column prop="question_text" label="买家问题" min-width="240" show-overflow-tooltip />
          <el-table-column prop="intent" label="意图" width="110" />
          <el-table-column label="出现次数" width="100" sortable prop="hit_count">
            <template #default="{ row }">
              <el-tag size="small" :type="hitTagType(row.hit_count)">{{ row.hit_count }} 次</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="答案来源" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="row.answer_source === 'operator' ? 'success' : 'warning'">
                {{ row.answer_source === 'operator' ? '人工已验证' : '待补答案' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="candidateStatusType(row.status)">{{ candidateStatusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="last_seen_at" label="最近出现" width="160" />
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button v-if="writable && acts(row).answer" size="small" type="warning" @click="openAnswer(row)">补答案</el-button>
              <el-button v-if="writable && acts(row).approve" size="small" type="primary" @click="approve(row)">采纳入库</el-button>
              <el-button v-if="writable && acts(row).revoke" size="small" type="danger" plain @click="revoke(row)">撤销入库</el-button>
              <el-button v-if="writable && acts(row).reject" size="small" @click="reject(row)">拒绝</el-button>
            </template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="暂无候选——买家提问未命中知识库时会自动沉淀到这里" /></template>
        </el-table>
      </SectionState>
    </FormSection>

    <!-- 文档编辑 -->
    <el-dialog v-model="dialog" :title="form.id ? '编辑文档' : '新增文档'" width="640px">
      <el-form label-width="80px">
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="来源"><el-input v-model="form.source" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="form.content" type="textarea" :rows="8" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 补写答案 -->
    <el-dialog v-model="answerDialog" title="补写标准答案" width="560px">
      <el-alert type="info" :closable="false" class="mb8" :title="`问题：${answerRow.question_text || ''}`" />
      <el-input
        v-model="answerText" type="textarea" :rows="5"
        placeholder="请输入经过验证的标准答案（补写后该问题可被采纳为知识，并参与自动学习）"
      />
      <template #footer>
        <el-button @click="answerDialog = false">取消</el-button>
        <el-button type="primary" @click="saveAnswer">保存答案</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import SectionState from '../../components/SectionState.vue'
import { can } from '../../permissions/permissions'
import { normalizeError } from '../../shared/api/errors'
import {
  fetchDocs, createDoc, updateDoc, deleteDoc, searchDocs,
  fetchCandidates, answerCandidate, approveCandidate, rejectCandidate, revokeCandidate,
  fetchLearningSettings, updateLearningSettings,
} from '../../api/domains/knowledge'
import {
  candidateActions, candidateStatusLabel, candidateStatusType,
  docSourceLabel, hitTagType,
} from '../../features/aiops/knowledgeView'

const writable = can('ai:write')
const router = useRouter()

// ---- 知识文档 ----
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const docsLoading = ref(false)
const error = ref('')
const traceId = ref('')
const q = ref('')
const searching = ref(false)
const searchResults = ref([])

const docState = computed(() => {
  if (docsLoading.value) return 'loading'
  if (error.value) return 'error'
  if (!items.value.length) return 'empty'
  return 'ready'
})

async function load() {
  docsLoading.value = true
  error.value = ''
  try {
    const data = await fetchDocs({ page: page.value, pageSize })
    items.value = data.items || []
    total.value = Number(data.total ?? items.value.length)
  } catch (e) {
    const norm = normalizeError(e)
    error.value = norm.message
    traceId.value = norm.traceId || ''
  } finally {
    docsLoading.value = false
  }
}

function onPageChange(next) {
  page.value = next
  load()
}

async function search() {
  if (!q.value.trim()) {
    searchResults.value = []
    return
  }
  searching.value = true
  try {
    const data = await searchDocs(q.value.trim(), 4)
    searchResults.value = data.items || []
  } finally {
    searching.value = false
  }
}

// ---- 候选 ----
const candidates = ref([])
const candLoading = ref(false)
const candError = ref('')
const candidateFilter = ref('')
const learning = reactive({ auto_learn_enabled: false, auto_learn_threshold: 5, hint: '' })

const candState = computed(() => {
  if (candLoading.value) return 'loading'
  if (candError.value) return 'error'
  if (!candidates.value.length) return 'empty'
  return 'ready'
})

const acts = (row) => candidateActions(row)

async function loadCandidates() {
  candLoading.value = true
  candError.value = ''
  try {
    const data = await fetchCandidates({ status: candidateFilter.value, limit: 200 })
    candidates.value = data.items || []
  } catch (e) {
    candError.value = normalizeError(e).message
  } finally {
    candLoading.value = false
  }
}

async function loadLearning() {
  try {
    Object.assign(learning, await fetchLearningSettings())
  } catch { /* 学习设置加载失败不阻塞候选列表 */ }
}

async function saveLearning() {
  await updateLearningSettings({
    auto_learn_enabled: learning.auto_learn_enabled,
    auto_learn_threshold: learning.auto_learn_threshold,
  })
  ElMessage.success(learning.auto_learn_enabled ? '自动学习已开启（仅对人工验证过答案的问题生效）' : '自动学习已关闭')
  loadLearning()
}

// ---- 文档编辑 ----
const dialog = ref(false)
const form = reactive({ id: null, title: '', content: '', source: '' })

function openEdit(row) {
  form.id = row?.id || null
  form.title = row?.title || ''
  form.content = row?.content || ''
  form.source = row?.source || ''
  dialog.value = true
}

async function save() {
  // 只提交表单字段：tags/enabled 未编辑，PUT 不携带以保留后端原值
  const body = { title: form.title, content: form.content, source: form.source }
  if (form.id) await updateDoc(form.id, body)
  else await createDoc(body)
  ElMessage.success('已保存')
  dialog.value = false
  load()
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除文档「${row.title}」？关联候选将退回未入库态。`, '确认', { type: 'warning' })
  } catch {
    return
  }
  await deleteDoc(row.id)
  ElMessage.success('已删除')
  load()
}

// ---- 补写 / 审批 ----
const answerDialog = ref(false)
const answerRow = ref({})
const answerText = ref('')

function openAnswer(row) {
  answerRow.value = row
  answerText.value = row.answer_draft || ''
  answerDialog.value = true
}

async function saveAnswer() {
  if (!answerText.value.trim()) return ElMessage.warning('答案不能为空')
  await answerCandidate(answerRow.value.id, answerText.value)
  ElMessage.success('答案已保存，现在可以采纳为知识')
  answerDialog.value = false
  loadCandidates()
}

async function approve(row) {
  try {
    await ElMessageBox.confirm(`确定把「${row.question_text}」采纳为知识文档？`, '确认', { type: 'info' })
  } catch {
    return
  }
  const data = await approveCandidate(row.id, '')
  ElMessage.success(`已采纳为知识文档（doc #${data.doc_id}）`)
  loadCandidates()
  load()
}

async function reject(row) {
  await rejectCandidate(row.id)
  ElMessage.success('已拒绝该候选')
  loadCandidates()
}

async function revoke(row) {
  try {
    await ElMessageBox.confirm('撤销将删除已生成的知识文档，确定继续？', '撤销自动入库', { type: 'warning' })
  } catch {
    return
  }
  const data = await revokeCandidate(row.id)
  ElMessage.success(data.doc_removed ? '已撤销并删除知识文档' : '已撤销')
  loadCandidates()
  load()
}

function goSupport() {
  router.push('/app/support')
}

function loadAll() {
  load()
  loadCandidates()
  loadLearning()
}

onMounted(loadAll)
</script>

<style scoped>
.search-bar { display: flex; gap: var(--space-2); }
.hit-card { margin-top: var(--space-2); }
.hit-score { margin-left: 8px; }
.hit-content { color: var(--color-text-regular, #606266); font-size: 13px; margin: 6px 0 0; }
.learning-bar { display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap; margin-bottom: var(--space-2); }
.filter-bar { margin-bottom: var(--space-2); }
.ml8 { margin-left: var(--space-2); }
.tag-gap { margin-right: 4px; }
.pager { margin-top: var(--space-3); justify-content: flex-end; }
.mt8 { margin-top: var(--space-2); }
.mb8 { margin-bottom: var(--space-2); }
</style>
