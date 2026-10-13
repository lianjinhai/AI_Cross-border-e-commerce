<template>
  <div class="page">
    <PageHeader title="AI 与集成设置" subtitle="AI 模型 · 经营参数 · 集成密钥 · 调用日志（OWNER 专属）">
      <template #actions>
        <el-button v-if="writable" type="primary" :loading="saving" @click="save">保存设置</el-button>
      </template>
    </PageHeader>

    <SectionState :state="listState" :error="error" :trace-id="traceId" @retry="load">
      <!-- 分组一：AI 模型（平台级，仅平台服务商可写——按后端 403 语义只读呈现） -->
      <FormSection title="AI 模型接入" description="Model Router：支持任意 OpenAI 兼容接口；未配置时全系统以规则引擎离线运行">
        <div class="key-bar">
          <el-tag :type="llm.has_key ? 'success' : 'warning'" size="small">
            {{ llm.has_key ? `已配置：${llm.model || '模型未命名'}` : '未配置 API Key（离线规则模式）' }}
          </el-tag>
          <el-tag v-if="!isPlatformAdmin" size="small" type="info">平台级配置，仅平台服务商可修改</el-tag>
        </div>
        <el-form label-width="110px" :disabled="!writable || !isPlatformAdmin">
          <el-form-item label="启用 LLM"><el-switch v-model="llm.enabled" /></el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="llm.api_key" type="password" show-password
              :placeholder="llm.has_key ? '已保存（留空表示不修改）' : '粘贴兼容 OpenAI 协议的 Key'"
            />
          </el-form-item>
          <el-form-item label="Base URL"><el-input v-model="llm.base_url" placeholder="https://open.bigmodel.cn/api/paas/v4" /></el-form-item>
          <el-form-item label="主模型"><el-input v-model="llm.model" placeholder="glm-4-flash / glm-4-plus / deepseek-chat" /></el-form-item>
          <el-form-item label="轻量模型"><el-input v-model="llm.model_small" placeholder="简单任务（分类/翻译）使用" /></el-form-item>
          <el-form-item label="向量模型"><el-input v-model="llm.embedding_model" placeholder="embedding-3（知识库语义检索）" /></el-form-item>
        </el-form>
      </FormSection>

      <!-- 分组二：经营参数（租户级） -->
      <FormSection title="经营参数" description="定价规则与费率（租户级覆盖；平台服务商保存的是平台默认值）">
        <el-form label-width="130px" :disabled="!writable">
          <el-form-item label="目标利润率"><el-input-number v-model="rules.target_margin" :step="0.05" :min="0.05" :max="2" /></el-form-item>
          <el-form-item label="最低利润率"><el-input-number v-model="rules.min_margin" :step="0.05" :min="0" :max="1" /></el-form-item>
          <el-form-item label="基础物流费¥"><el-input-number v-model="rules.logistics_base" :min="0" /></el-form-item>
          <el-form-item label="每kg物流¥"><el-input-number v-model="rules.logistics_per_kg" :min="0" /></el-form-item>
          <el-form-item label="单件广告费¥"><el-input-number v-model="rules.ads_default" :min="0" :step="0.5" /></el-form-item>
          <el-form-item label="USD 汇率"><el-input-number v-model="fx.USD" :step="0.01" :min="1" /></el-form-item>
        </el-form>
        <el-divider content-position="left">平台佣金费率</el-divider>
        <el-form inline size="small" :disabled="!writable">
          <el-form-item v-for="(v, k) in platformFees" :key="k" :label="k">
            <el-input-number v-model="platformFees[k]" :step="0.01" :min="0" :max="0.5" style="width: 110px" />
          </el-form-item>
        </el-form>
      </FormSection>

      <!-- 分组三：集成密钥 -->
      <FormSection title="集成密钥（1688 开放平台）" description="配置后采集优先走官方 API；未配置自动降级：静态抓取 → 无头浏览器 → 粘贴源码">
        <div class="key-bar">
          <el-tag :type="api1688.has_key ? 'success' : 'info'" size="small">
            {{ api1688.has_key ? '已配置：采集优先走官方 API' : '未配置：走浏览器抓取兜底' }}
          </el-tag>
          <el-tag v-if="!isPlatformAdmin" size="small" type="info">平台级配置，仅平台服务商可修改</el-tag>
        </div>
        <el-form label-width="110px" :disabled="!writable || !isPlatformAdmin">
          <el-form-item label="App Key"><el-input v-model="api1688.app_key" placeholder="open.1688.com 创建应用获得" /></el-form-item>
          <el-form-item label="App Secret">
            <el-input
              v-model="api1688.app_secret" type="password" show-password
              :placeholder="api1688.has_key ? '已保存（留空不改）' : ''"
            />
          </el-form-item>
          <el-form-item label="Access Token"><el-input v-model="api1688.access_token" placeholder="OAuth 授权获得（商品详情接口需要）" /></el-form-item>
        </el-form>
      </FormSection>

      <!-- 分组四：调用日志 -->
      <FormSection title="AI 调用日志" description="每次 Agent/LLM 调用一条（不含 prompt 明文，审计口径）">
        <el-table :data="logs" v-loading="logsLoading" size="small" max-height="420">
          <el-table-column prop="created_at" label="时间" width="150" />
          <el-table-column prop="agent" label="Agent" width="110" />
          <el-table-column prop="action" label="动作" width="140" />
          <el-table-column prop="mode" label="模式" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.mode === 'llm' ? 'success' : 'info'">{{ row.mode }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.ok ? 'success' : 'danger'">{{ row.ok ? 'OK' : 'FAIL' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="response" label="响应摘要" show-overflow-tooltip />
          <template #empty><EmptyState reason="NO_DATA" hint="暂无调用日志" /></template>
        </el-table>
      </FormSection>
    </SectionState>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import SectionState from '../../components/SectionState.vue'
import { can, roleKey, ROLES } from '../../permissions/permissions'
import { normalizeError } from '../../shared/api/errors'
import { fetchAiSettings, saveAiSettings, fetchAiLogs } from '../../api/domains/ai'

const writable = can('workspace:member:admin')
const isPlatformAdmin = roleKey() === ROLES.PLATFORM_ADMIN

const llm = reactive({ enabled: true, api_key: '', base_url: '', model: '', model_small: '', embedding_model: '', has_key: false })
const rules = reactive({ target_margin: 0.35, min_margin: 0.15, logistics_base: 18, logistics_per_kg: 8, ads_default: 1.5 })
const fx = reactive({ USD: 7.12 })
const platformFees = reactive({})
const api1688 = reactive({ app_key: '', app_secret: '', access_token: '', has_key: false })
const logs = ref([])
const loading = ref(false)
const logsLoading = ref(false)
const error = ref('')
const traceId = ref('')
const saving = ref(false)

const listState = computed(() => {
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  return 'ready'
})

async function load() {
  loading.value = true
  error.value = ''
  traceId.value = ''
  try {
    const data = await fetchAiSettings()
    Object.assign(llm, data.llm || {})
    Object.assign(rules, data.rules || {})
    Object.assign(fx, data.fx || {})
    Object.keys(platformFees).forEach((k) => delete platformFees[k])
    Object.assign(platformFees, data.platform_fees || {})
    Object.assign(api1688, data.open_1688 || {})
  } catch (e) {
    const norm = normalizeError(e)
    error.value = norm.message
    traceId.value = norm.traceId || ''
  } finally {
    loading.value = false
  }
  logsLoading.value = true
  try {
    const lg = await fetchAiLogs(50)
    logs.value = lg.items || []
  } catch { logs.value = [] } finally {
    logsLoading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await saveAiSettings({
      // 平台级 key（llm/open_1688）租户 OWNER 保存会被后端 403——
      // 仍随表单提交会让整次保存失败，故仅平台管理员携带（租户级 key 正常提交）。
      ...(isPlatformAdmin
        ? {
            llm: {
              enabled: llm.enabled, api_key: llm.api_key, base_url: llm.base_url,
              model: llm.model, model_small: llm.model_small, embedding_model: llm.embedding_model,
            },
            open_1688: {
              app_key: api1688.app_key, app_secret: api1688.app_secret,
              access_token: api1688.access_token,
            },
          }
        : {}),
      rules: { ...rules },
      fx: { ...fx },
      platform_fees: { ...platformFees },
    })
    ElMessage.success('设置已保存')
    load()
  } catch (e) {
    ElMessage.error(normalizeError(e).message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.key-bar { display: flex; gap: var(--space-2); margin-bottom: var(--space-3); flex-wrap: wrap; }
</style>
