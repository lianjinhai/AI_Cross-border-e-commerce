<template>
  <div class="page">
    <el-tabs v-model="activeTab">
      <!-- ============ 知识文档（原有内容） ============ -->
      <el-tab-pane label="知识文档" name="docs">
        <el-card class="mb16">
          <div style="display:flex;gap:12px">
            <el-input v-model="q" placeholder="搜索知识库（如：违禁词 / 佣金 / 退货）" style="width:320px"
              clearable @keyup.enter="search" />
            <el-button v-if="can('ai:write')" type="primary" @click="search">语义检索</el-button>
            <el-button v-if="can('ai:write')" type="success" plain @click="openEdit()">新增文档</el-button>
          </div>
          <el-alert v-if="searchResults.length" type="success" :closable="false" style="margin-top:12px"
            :title="`检索到 ${searchResults.length} 篇相关文档（RAG 检索结果）`" />
          <div v-if="searchResults.length" style="margin-top:8px">
            <el-card v-for="d in searchResults" :key="d.id" shadow="never" style="margin-bottom:8px">
              <b>{{ d.title }}</b>
              <el-tag size="small" type="info" style="margin-left:8px">相关度 {{ d.score }}</el-tag>
              <p style="color:#606266;font-size:13px;margin:6px 0 0">{{ d.content }}…</p>
            </el-card>
          </div>
        </el-card>

        <el-card>
          <el-table :data="items" v-loading="loading" size="small">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
            <el-table-column label="来源" width="140">
              <template #default="{ row }">
                <el-tag v-if="row.source === 'auto_learned'" size="small" type="success">AI 自动固化</el-tag>
                <el-tag v-else-if="row.source === 'support_candidate'" size="small" type="primary">客服沉淀</el-tag>
                <span v-else-if="row.source">{{ row.source }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="标签" width="180">
              <template #default="{ row }">
                <el-tag v-for="t in row.tags" :key="t" size="small" style="margin-right:4px">{{ t }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="enabled" label="启用" width="70">
              <template #default="{ row }"><el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '是' : '否' }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button v-if="can('ai:write')" size="small" type="danger" @click="remove(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
            :page-size="pageSize" v-model:current-page="page" @current-change="load" />
        </el-card>
      </el-tab-pane>

      <!-- ============ 知识候选（M4 客服知识自进化） ============ -->
      <el-tab-pane label="知识候选（AI 学习）" name="candidates">
        <el-card class="mb16">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>客服未命中问题沉淀</span>
              <el-button size="small" @click="loadCandidates">刷新</el-button>
            </div>
          </template>
          <el-alert :title="learning.hint" :closable="false" style="margin-bottom:12px"
            :type="learning.auto_learn_enabled ? 'success' : 'info'" />
          <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
            <div>
              <span style="margin-right:8px">自动学习</span>
              <el-switch v-model="learning.auto_learn_enabled" @change="saveLearning" />
            </div>
            <div>
              <span style="margin-right:8px">触发阈值（出现次数）</span>
              <el-input-number v-model="learning.auto_learn_threshold" :min="2" :max="100"
                size="small" @change="saveLearning" />
            </div>
            <el-tag size="small" type="warning">仅对「人工已验证答案」的问题生效——AI 不自行编造答案</el-tag>
          </div>
        </el-card>

        <el-card>
          <template #header>
            <div style="display:flex;gap:12px;align-items:center">
              <el-select v-model="candidateFilter" placeholder="全部状态" clearable style="width:150px"
                size="small" @change="loadCandidates">
                <el-option label="待处理" value="pending" />
                <el-option label="已采纳" value="approved" />
                <el-option label="AI已固化" value="auto_learned" />
                <el-option label="已拒绝" value="rejected" />
              </el-select>
            </div>
          </template>
          <el-table :data="candidates" v-loading="candidatesLoading" size="small">
            <el-table-column prop="question_text" label="买家问题" min-width="240" show-overflow-tooltip />
            <el-table-column prop="intent" label="意图" width="110" />
            <el-table-column label="出现次数" width="100" sortable prop="hit_count">
              <template #default="{ row }">
                <el-tag size="small" :type="row.hit_count >= 5 ? 'danger' : 'info'">{{ row.hit_count }} 次</el-tag>
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
                <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="last_seen_at" label="最近出现" width="160" />
            <el-table-column label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <el-button v-if="row.answer_source === 'none' && can('ai:write')" size="small" type="warning"
                  @click="openAnswer(row)">补答案</el-button>
                <el-button v-if="row.answer_source === 'operator' && row.status === 'pending' && can('ai:write')"
                  size="small" type="primary" @click="approve(row)">采纳入库</el-button>
                <el-button v-if="row.doc_id && can('ai:write')" size="small" type="danger" plain
                  @click="revoke(row)">撤销入库</el-button>
                <el-button v-if="row.status !== 'rejected' && can('ai:write')" size="small"
                  @click="reject(row)">拒绝</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!candidates.length && !candidatesLoading" :image-size="60"
            description="暂无候选——买家提问未命中知识库时会自动沉淀到这里" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

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
      <el-alert type="info" :closable="false" style="margin-bottom:10px"
        :title="`问题：${answerRow.question_text || ''}`" />
      <el-input v-model="answerText" type="textarea" :rows="5"
        placeholder="请输入经过验证的标准答案（补写后该问题可被采纳为知识，并参与自动学习）" />
      <template #footer>
        <el-button @click="answerDialog = false">取消</el-button>
        <el-button type="primary" @click="saveAnswer">保存答案</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'
import { can } from '../permissions'

const activeTab = ref('docs')

// ---- 知识文档 ----
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const q = ref('')
const searchResults = ref([])
const dialog = ref(false)
const form = reactive({ id: null, title: '', content: '', source: '' })

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/knowledge/docs', { params: { page_num: page.value, page_size: pageSize } })
    items.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

async function search() {
  if (!q.value.trim()) { searchResults.value = []; return }
  const { data } = await api.get('/knowledge/search', { params: { q: q.value, top_k: 4 } })
  searchResults.value = data.items
}

function openEdit(row) {
  form.id = row?.id || null
  form.title = row?.title || ''
  form.content = row?.content || ''
  form.source = row?.source || ''
  dialog.value = true
}

async function save() {
  // 只提交表单管理的字段；tags/enabled 未在表单中编辑，PUT 不携带以保留后端原值
  const body = { title: form.title, content: form.content, source: form.source }
  if (form.id) await api.put(`/knowledge/docs/${form.id}`, body)
  else await api.post('/knowledge/docs', body)
  ElMessage.success('已保存')
  dialog.value = false
  load()
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除文档「${row.title}」？`, '确认', { type: 'warning' })
  await api.delete(`/knowledge/docs/${row.id}`)
  ElMessage.success('已删除')
  load()
}

// ---- M4 知识候选 ----
const candidates = ref([])
const candidatesLoading = ref(false)
const candidateFilter = ref('')
const learning = reactive({ auto_learn_enabled: false, auto_learn_threshold: 5, hint: '' })
const answerDialog = ref(false)
const answerRow = ref({})
const answerText = ref('')

const statusLabel = (s) => ({ pending: '待处理', approved: '已采纳', auto_learned: 'AI已固化', rejected: '已拒绝' }[s] || s)
const statusType = (s) => ({ pending: 'info', approved: 'primary', auto_learned: 'success', rejected: 'danger' }[s] || 'info')

async function loadCandidates() {
  candidatesLoading.value = true
  try {
    const params = { limit: 200 }
    if (candidateFilter.value) params.status = candidateFilter.value
    const { data } = await api.get('/knowledge/candidates', { params })
    candidates.value = data.items
  } finally { candidatesLoading.value = false }
}

async function loadLearning() {
  const { data } = await api.get('/knowledge/learning/settings')
  Object.assign(learning, data)
}

async function saveLearning() {
  await api.put('/knowledge/learning/settings', {
    auto_learn_enabled: learning.auto_learn_enabled,
    auto_learn_threshold: learning.auto_learn_threshold,
  })
  ElMessage.success(learning.auto_learn_enabled ? '自动学习已开启（仅对人工验证过答案的问题生效）' : '自动学习已关闭')
  loadLearning()
}

function openAnswer(row) {
  answerRow.value = row
  answerText.value = row.answer_draft || ''
  answerDialog.value = true
}

async function saveAnswer() {
  if (!answerText.value.trim()) return ElMessage.warning('答案不能为空')
  await api.post(`/knowledge/candidates/${answerRow.value.id}/answer`, { answer: answerText.value })
  ElMessage.success('答案已保存，现在可以采纳为知识')
  answerDialog.value = false
  loadCandidates()
}

async function approve(row) {
  await ElMessageBox.confirm(`确定把「${row.question_text}」采纳为知识文档？`, '确认', { type: 'info' })
  const { data } = await api.post(`/knowledge/candidates/${row.id}/approve`, { answer: '' })
  ElMessage.success(`已采纳为知识文档（doc #${data.doc_id}）`)
  loadCandidates()
  load()
}

async function reject(row) {
  await api.post(`/knowledge/candidates/${row.id}/reject`)
  ElMessage.success('已拒绝该候选')
  loadCandidates()
}

async function revoke(row) {
  await ElMessageBox.confirm('撤销将删除已生成的知识文档，确定继续？', '撤销自动入库', { type: 'warning' })
  const { data } = await api.post(`/knowledge/candidates/${row.id}/revoke`)
  ElMessage.success(data.doc_removed ? '已撤销并删除知识文档' : '已撤销')
  loadCandidates()
  load()
}

onMounted(() => { load(); loadCandidates(); loadLearning() })
</script>
