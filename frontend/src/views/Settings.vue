<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :span="10">
        <el-card class="mb16">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>🤖 大模型接入（Model Router）</span>
              <el-tag :type="llm.has_key ? 'success' : 'warning'" size="small">
                {{ llm.has_key ? `已配置：${llm.model}` : '未配置 API Key（离线规则模式）' }}
              </el-tag>
            </div>
          </template>
          <el-form label-width="110px">
            <el-form-item label="启用 LLM">
              <el-switch v-model="llm.enabled" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="llm.api_key" type="password" show-password
                :placeholder="llm.has_key ? '已保存（留空表示不修改）' : '粘贴兼容 OpenAI 协议的 Key'" />
            </el-form-item>
            <el-form-item label="Base URL">
              <el-input v-model="llm.base_url" placeholder="https://open.bigmodel.cn/api/paas/v4" />
            </el-form-item>
            <el-form-item label="主模型">
              <el-input v-model="llm.model" placeholder="glm-4-flash / glm-4-plus / deepseek-chat" />
            </el-form-item>
            <el-form-item label="轻量模型">
              <el-input v-model="llm.model_small" placeholder="简单任务（分类/翻译）使用" />
            </el-form-item>
            <el-form-item label="向量模型">
              <el-input v-model="llm.embedding_model" placeholder="embedding-3（知识库语义检索）" />
            </el-form-item>
          </el-form>
          <el-alert type="info" :closable="false" style="margin-bottom:12px"
            title="支持智谱 GLM / DeepSeek / OpenAI / Ollama 等任意 OpenAI 兼容接口；未配置时全系统以规则引擎离线运行。" />
          <el-button v-if="can('workspace:member:admin')" type="primary" style="width:100%" @click="save">保存全部设置</el-button>
        </el-card>

        <el-card>
          <template #header>经营参数</template>
          <el-form label-width="130px" size="small">
            <el-form-item label="目标利润率"><el-input-number v-model="rules.target_margin" :step="0.05" :min="0.05" :max="2" /></el-form-item>
            <el-form-item label="最低利润率"><el-input-number v-model="rules.min_margin" :step="0.05" :min="0" :max="1" /></el-form-item>
            <el-form-item label="基础物流费¥"><el-input-number v-model="rules.logistics_base" :min="0" /></el-form-item>
            <el-form-item label="每kg物流¥"><el-input-number v-model="rules.logistics_per_kg" :min="0" /></el-form-item>
            <el-form-item label="单件广告费¥"><el-input-number v-model="rules.ads_default" :min="0" :step="0.5" /></el-form-item>
            <el-form-item label="USD 汇率"><el-input-number v-model="fx.USD" :step="0.01" :min="1" /></el-form-item>
          </el-form>
        </el-card>
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>🏪 1688 开放平台 API（官方接口，推荐）</span>
              <el-tag :type="api1688.has_key ? 'success' : 'info'" size="small">
                {{ api1688.has_key ? '已配置：采集优先走官方 API' : '未配置：走浏览器抓取兜底' }}
              </el-tag>
            </div>
          </template>
          <el-form label-width="110px" size="small">
            <el-form-item label="App Key"><el-input v-model="api1688.app_key" placeholder="open.1688.com 创建应用获得" /></el-form-item>
            <el-form-item label="App Secret"><el-input v-model="api1688.app_secret" type="password" show-password :placeholder="api1688.has_key ? '已保存（留空不改）' : ''" /></el-form-item>
            <el-form-item label="Access Token"><el-input v-model="api1688.access_token" placeholder="OAuth 授权获得（商品详情接口需要）" /></el-form-item>
          </el-form>
          <el-alert type="info" :closable="false" size="small"
            title="配置后 1688 链接采集优先走官方 API（稳定合规）；未配置自动降级：静态抓取 → 无头浏览器渲染 → 粘贴源码。" />
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card class="mb16">
          <template #header>平台佣金费率</template>
          <el-form inline size="small">
            <el-form-item v-for="(v, k) in platformFees" :key="k" :label="k">
              <el-input-number v-model="platformFees[k]" :step="0.01" :min="0" :max="0.5" style="width:110px" />
            </el-form-item>
          </el-form>
        </el-card>
        <el-card>
          <template #header>AI 调用日志（最近）</template>
          <el-table :data="logs" size="small" v-loading="loadingLogs" max-height="480">
            <el-table-column prop="created_at" label="时间" width="150" />
            <el-table-column prop="agent" label="Agent" width="100" />
            <el-table-column prop="action" label="动作" width="130" />
            <el-table-column prop="mode" label="模式" width="70">
              <template #default="{ row }">
                <el-tag size="small" :type="row.mode === 'llm' ? 'success' : 'info'">{{ row.mode }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="ok" label="状态" width="70">
              <template #default="{ row }"><el-tag size="small" :type="row.ok ? 'success' : 'danger'">{{ row.ok ? 'OK' : 'FAIL' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="response" label="响应摘要" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../ui'
import api from '../api'
import { can } from '../permissions'

const llm = reactive({ enabled: true, api_key: '', base_url: '', model: '', model_small: '', has_key: false })
const rules = reactive({ target_margin: 0.35, min_margin: 0.15, logistics_base: 18, logistics_per_kg: 8, ads_default: 1.5 })
const fx = reactive({ USD: 7.12 })
const platformFees = reactive({})
const api1688 = reactive({ app_key: '', app_secret: '', access_token: '', has_key: false })
const logs = ref([])
const loadingLogs = ref(false)

async function load() {
  const { data } = await api.get('/ai/settings')
  Object.assign(llm, data.llm)
  Object.assign(rules, data.rules)
  Object.assign(fx, data.fx)
  Object.assign(platformFees, data.platform_fees)
  Object.assign(api1688, data.open_1688)
  loadingLogs.value = true
  try {
    const { data: lg } = await api.get('/ai/logs', { params: { limit: 50 } })
    logs.value = lg.items
  } finally { loadingLogs.value = false }
}

async function save() {
  await api.put('/ai/settings', {
    llm: { enabled: llm.enabled, api_key: llm.api_key, base_url: llm.base_url,
           model: llm.model, model_small: llm.model_small, embedding_model: llm.embedding_model },
    open_1688: { app_key: api1688.app_key, app_secret: api1688.app_secret,
                 access_token: api1688.access_token },
    rules, fx, platform_fees: platformFees,
  })
  ElMessage.success('设置已保存')
  load()
}

onMounted(load)
</script>
