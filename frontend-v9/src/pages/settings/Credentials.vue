<template>
  <div class="page">
    <PageHeader
      title="凭据管理"
      subtitle="店铺 OAuth / AI 凭据 · 仅显尾部与状态 · 区分平台级 / Workspace 级作用域"
    >
      <template #actions>
        <el-button size="small" @click="loadAll">刷新</el-button>
        <el-button size="small" @click="router.push('/app/channels/shops')">店铺授权</el-button>
      </template>
    </PageHeader>

    <SectionState :code="code" :error="error" @retry="loadAll">
      <!-- 平台级：店铺 OAuth 凭据（shops.js） -->
      <FormSection
        title="店铺 OAuth 凭据（Workspace 级）"
        description="每个店铺一条 OAuth 凭据；仅显示状态与 token 到期时间，不回显明文。"
      >
        <el-table :data="oauthRows" size="small" v-loading="oauthLoading">
          <el-table-column prop="shopName" label="店铺" min-width="160" show-overflow-tooltip />
          <el-table-column prop="platform" label="平台" width="100" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.statusTag.type" effect="plain">{{ row.statusTag.label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Token 尾部" width="130">
            <template #default="{ row }">{{ row.tokenTail || '—' }}</template>
          </el-table-column>
          <el-table-column prop="expiresAt" label="Token 到期" width="160">
            <template #default="{ row }">{{ row.expiresAt || '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-tooltip v-if="row.status === 'authorized'" content="刷新将生成新的 token；旧 token 立即失效" placement="top">
                <el-button
                  size="small" :loading="refreshing === row.id"
                  @click="doRefresh(row)"
                >刷新</el-button>
              </el-tooltip>
              <el-button v-else size="small" type="primary" @click="router.push('/app/channels/shops')">
                重新授权
              </el-button>
            </template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="尚无店铺凭据（到店铺管理页添加）" /></template>
        </el-table>
      </FormSection>

      <!-- 平台级 / Workspace 级：AI 凭据（ai.js） -->
      <FormSection
        title="AI 集成凭据（平台级 + Workspace 级）"
        description="密钥仅显示尾部/是否已配置，明文不回显。平台级 key 仅平台服务商可写——租户 OWNER 只读提示。"
      >
        <el-table :data="aiRows" size="small" v-loading="aiLoading">
          <el-table-column prop="name" label="凭据" width="180" />
          <el-table-column label="作用域" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.scope === '平台级' ? 'warning' : 'info'" effect="plain">
                {{ row.scope }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="160">
            <template #default="{ row }">
              <el-tag size="small" :type="row.configured ? 'success' : 'info'" effect="plain">
                {{ row.configured ? '已配置' : '未配置' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="尾部" width="130">
            <template #default="{ row }">{{ row.tail || '—' }}</template>
          </el-table-column>
          <el-table-column label="说明" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.note }}</template>
          </el-table-column>
          <template #empty><EmptyState reason="NO_DATA" hint="尚未配置 AI 集成凭据" /></template>
        </el-table>
        <el-alert
          v-if="platformKeysReadOnly"
          type="info" :closable="false" class="mt12"
          title="平台级密钥（LLM / 1688）仅平台服务商可修改"
          description="租户 OWNER 保存会被后端 403 拒绝——本页只读呈现，不做假授权。修改请到 AI 与集成设置页（平台管理员身份）。"
        />
      </FormSection>
    </SectionState>

    <!-- 吊销/刷新走 AsyncActionDialog（不可逆影响说明 + 409/超时不盲重试） -->
    <AsyncActionDialog
      v-model="revokeDialog"
      action="刷新店铺凭据"
      :context="revokeContext"
      :idempotency-key="revokeKey"
      done-message="凭据已刷新"
      @submit="onRefreshSubmit"
      @requery="loadOauth"
    />
  </div>
</template>

<script setup>
/**
 * 凭据管理（蓝图 R1 SET-03，包 2）：/app/settings/credentials（requiresOwner）。
 *
 * 数据源：shops.js(OAuth 授权/刷新) + ai.js（AI 凭据 has_key 聚合）；
 * 仅显尾部/状态，不回文明文；区分平台级/Workspace 级作用域。
 * 红线：明文不回显——token 尾部由本页从已有字段截取（后端未提供明文尾段时显"—"）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import SectionState from '../../components/SectionState.vue'
import AsyncActionDialog from '../../components/AsyncActionDialog.vue'
import { ElMessage } from '../../shared/ui'
import { fetchShops, refresh } from '../../api/domains/shops'
import { fetchAiSettings } from '../../api/domains/ai'

const router = useRouter()

const oauthRows = ref([])
const oauthLoading = ref(false)
const aiRows = ref([])
const aiLoading = ref(false)
const error = ref('')
const refreshing = ref(null)

/** 11 态：加载/错误/内容。 */
const code = computed(() => {
  if (error.value) return 'ERROR'
  if (oauthLoading.value || aiLoading.value) return 'LOADING'
  return 'ready'
})

const STATUS_TAG_MAP = {
  authorized: { type: 'success', label: '已授权' },
  expired: { type: 'warning', label: '已过期' },
  failed: { type: 'danger', label: '失败' },
  pending: { type: 'info', label: '授权中' },
}

/** token 尾 4 位（后端未提供明文尾段时不伪造——显 null）。 */
function tokenTail(shop) {
  // shops DTO 不回显 token 明文（PII 红线）；仅当后端显式给出 tail 字段才显示
  return typeof shop?.token_tail === 'string' ? shop.token_tail : null
}

async function loadOauth() {
  oauthLoading.value = true
  try {
    const data = await fetchShops()
    oauthRows.value = (data.items || []).map((s) => ({
      id: s.id,
      shopName: s.shop_name || `#${s.id}`,
      platform: s.platform || '—',
      status: s.status || '',
      statusTag: STATUS_TAG_MAP[s.status] || { type: 'info', label: s.status || '未知' },
      tokenTail: tokenTail(s),
      expiresAt: s.token_expires_at || s.expires_at || null,
    }))
  } catch (e) {
    error.value = e?.response?.data?.detail || e?.message || '加载店铺凭据失败'
  } finally {
    oauthLoading.value = false
  }
}

async function loadAi() {
  aiLoading.value = true
  try {
    const data = await fetchAiSettings()
    // 密钥回空串 + has_key（既有契约）：本页只显 has_key/尾部，不渲染任何明文输入框
    const llmKey = data?.llm?.api_key || ''
    const secret1688 = data?.open_1688?.app_secret || ''
    aiRows.value = [
      {
        name: 'LLM API Key',
        scope: '平台级',
        configured: Boolean(data?.llm?.has_key),
        tail: llmKey ? `${llmKey.slice(0, 3)}…${llmKey.slice(-4)}` : null,
        note: data?.llm?.model ? `模型：${data.llm.model}` : '未配置模型（离线规则模式）',
      },
      {
        name: '1688 App Secret',
        scope: '平台级',
        configured: Boolean(data?.open_1688?.has_key),
        tail: secret1688 ? `${secret1688.slice(0, 3)}…${secret1688.slice(-4)}` : null,
        note: data?.open_1688?.has_key ? '已配置：采集优先走官方 API' : '未配置：走浏览器抓取兜底',
      },
      {
        name: '1688 Access Token',
        scope: '平台级',
        configured: Boolean(data?.open_1688?.access_token),
        tail: null,
        note: 'OAuth 授权获得（商品详情接口需要）；明文不回显',
      },
    ]
  } catch {
    // AI 凭据加载失败不阻断 OAuth 区：保持空列表 + 状态码不 ERROR
    aiRows.value = []
  } finally {
    aiLoading.value = false
  }
}

/** 平台级 key 对租户 OWNER 只读（后端 403 语义前置提示，不做假授权）。 */
const platformKeysReadOnly = computed(() =>
  aiRows.value.some((r) => r.scope === '平台级'))

async function loadAll() {
  error.value = ''
  await Promise.all([loadOauth(), loadAi()])
}

// ── 刷新店铺凭据（AsyncActionDialog） ──
const revokeDialog = ref(false)
const revokeTarget = ref(null)
const revokeKey = computed(() =>
  revokeTarget.value ? `shop:${revokeTarget.value.id}:refresh:${Date.now()}` : '')
const revokeContext = computed(() => {
  const row = revokeTarget.value
  if (!row) return ''
  return `店铺 ${row.shopName}（${row.platform}）：刷新将生成新 token，旧 token 立即失效`
})

function doRefresh(row) {
  revokeTarget.value = row
  refreshing.value = row.id
  revokeDialog.value = true
}

async function onRefreshSubmit() {
  const row = revokeTarget.value
  try {
    await refresh(row.id)
    ElMessage.success('凭据已刷新')
    revokeDialog.value = false
    await loadOauth()
  } catch (e) {
    if (e?.response?.status === 409) {
      ElMessage.warning('凭据状态已变更，请刷新查看')
      revokeDialog.value = false
      await loadOauth()
    }
    throw e
  } finally {
    refreshing.value = null
  }
}

onMounted(loadAll)
</script>

<style scoped>
.mt12 { margin-top: 12px; }
</style>
