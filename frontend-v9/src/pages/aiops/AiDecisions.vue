<template>
  <div class="page">
    <PageHeader title="AI 决策依据" subtitle="决策链只读审计（只增不删） · 用了哪些数据 · 规则还是大模型 · 判定结果">
      <template #filters>
        <el-select v-model="filters.agent" style="width: 150px" @change="touch">
          <el-option v-for="o in AGENT_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-select v-model="filters.subjectType" style="width: 150px" @change="touch">
          <el-option v-for="o in SUBJECT_TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-input-number
          v-model="filters.subjectId" :min="1" placeholder="对象 ID" style="width: 130px"
          :controls="false" @change="touch"
        />
      </template>
    </PageHeader>

    <SectionState :state="listState" :error="error" :trace-id="traceId" @retry="load">
      <FormSection title="决策记录" description="每条决策记录：数据引用（而非快照）、模型模式、判定结果；点击行查看依据详情">
        <el-table :data="items" v-loading="loading" size="small" @row-click="open">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="agent" label="Agent" width="120" />
          <el-table-column prop="action" label="动作" width="150" />
          <el-table-column label="对象" width="150">
            <template #default="{ row }">{{ row.subject_type }} #{{ row.subject_id }}</template>
          </el-table-column>
          <el-table-column label="判定结果" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ briefDecision(row.decision) }}</template>
          </el-table-column>
          <el-table-column label="模型" width="90">
            <template #default="{ row }">
              <el-tag :type="row.model === 'llm' ? 'success' : 'info'" size="small">
                {{ row.model === 'llm' ? '大模型' : '规则' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="时间" width="160" />
          <template #empty><EmptyState reason="NO_DATA" hint="暂无决策记录（调整过滤条件或先运行相关 AI 功能）" /></template>
        </el-table>
      </FormSection>
    </SectionState>

    <el-drawer v-model="drawer" title="决策依据详情" size="560px">
      <template v-if="current.id">
        <el-descriptions :column="2" border size="small" class="mb12">
          <el-descriptions-item label="Agent">{{ current.agent }}</el-descriptions-item>
          <el-descriptions-item label="动作">{{ current.action }}</el-descriptions-item>
          <el-descriptions-item label="对象">{{ current.subject_type }} #{{ current.subject_id }}</el-descriptions-item>
          <el-descriptions-item label="模型">{{ current.model }}</el-descriptions-item>
        </el-descriptions>
        <h4 class="drawer-h">判定结果</h4>
        <pre class="json-box">{{ prettyJson(current.decision) }}</pre>
        <h4 class="drawer-h">依据链（数据引用）</h4>
        <pre class="json-box">{{ prettyJson(current.evidence) }}</pre>
        <el-alert v-if="reasons.length" type="success" :closable="false" title="判定理由">
          <ul class="reason-list">
            <li v-for="(r, i) in reasons" :key="i">{{ r }}</li>
          </ul>
        </el-alert>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import SectionState from '../../components/SectionState.vue'
import { normalizeError } from '../../shared/api/errors'
import { fetchAiDecisions } from '../../api/domains/ai'
import {
  AGENT_OPTIONS, SUBJECT_TYPE_OPTIONS, briefDecision, decisionReasons,
  filtersFromQuery, prettyJson,
} from '../../features/aiops/decisionsView'

const route = useRoute()
const items = ref([])
const loading = ref(false)
const error = ref('')
const traceId = ref('')
const drawer = ref(false)
const current = ref({})
const filters = reactive({ agent: '', subjectType: '', subjectId: null })

const reasons = computed(() => decisionReasons(current.value.evidence))

const listState = computed(() => {
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  if (!items.value.length) return 'empty'
  return 'ready'
})

async function load() {
  loading.value = true
  error.value = ''
  traceId.value = ''
  try {
    const data = await fetchAiDecisions({
      agent: filters.agent,
      subjectType: filters.subjectType,
      subjectId: filters.subjectId,
      limit: 100,
    })
    items.value = data.items || []
  } catch (e) {
    const norm = normalizeError(e)
    error.value = norm.message
    traceId.value = norm.traceId || ''
  } finally {
    loading.value = false
  }
}

function touch() {
  load()
}

/** 深链入口（矩阵 #25）：/app/ai/decisions?agent=&subject_type=&subject_id= 预填过滤。 */
function applyQuery() {
  Object.assign(filters, filtersFromQuery(route.query || {}))
}

function open(row) {
  current.value = row
  drawer.value = true
}

onMounted(() => {
  applyQuery()
  load()
})

// 其他 AI 页通过 router.push 带新 query 深链时重新过滤（app 子路由无 name，按 path 判定）。
watch(() => route.query, () => {
  if (route.path.endsWith('/ai/decisions')) {
    applyQuery()
    load()
  }
})
</script>

<style scoped>
.json-box {
  background: var(--color-fill-light, #f5f7fa);
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  line-height: 1.6;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.drawer-h { margin: 12px 0 6px; }
.reason-list { margin: 6px 0 0; padding-left: 18px; }
.mb12 { margin-bottom: var(--space-3); }
</style>
