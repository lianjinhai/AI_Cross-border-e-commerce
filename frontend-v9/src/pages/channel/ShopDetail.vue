<template>
  <div class="page">
    <PageHeader
      :title="shop?.shop_name || `店铺 #${shopId}`"
      subtitle="店铺详情 / 健康 · 授权 / 同步 / 告警"
    >
      <template #actions>
        <el-button @click="router.push('/app/channels/shops')">返回店铺管理</el-button>
      </template>
    </PageHeader>

    <SectionState :code="shopCode" :error="error" :action-text="actionText" @action="onStateAction" @retry="load">
      <!-- 顶部三态（授权有效 / 商品能力 / 订单能力） -->
      <el-card v-if="shopCode === 'ready'" shadow="never" class="mb16">
        <div class="tri-states">
          <div v-for="state in triStates" :key="state.key" class="tri-states__item">
            <el-tag :type="triTagType(state.state)" effect="dark" size="default">
              {{ state.label }}：{{ triStateText(state.state) }}
            </el-tag>
            <div class="tri-states__hint">
              {{ state.key === 'auth'
                ? (shop.status === 'authorized' ? '授权凭据有效' : (shop.auth_message || '授权未生效'))
                : '验证端点未核（§7#8），仅当后端显式返回已验证才显示有效' }}
            </div>
          </div>
        </div>

        <el-descriptions :column="3" border size="small" class="mt12">
          <el-descriptions-item label="平台">{{ shop.platform || '—' }}</el-descriptions-item>
          <el-descriptions-item label="目标市场">{{ shop.market || '—' }}</el-descriptions-item>
          <el-descriptions-item label="角色">
            <el-tag size="small" :type="shop.role === 'source' ? 'warning' : 'success'">
              {{ shop.role === 'source' ? '货源' : '销售' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="最近同步">{{ shop.last_sync_at || '—' }}</el-descriptions-item>
          <el-descriptions-item label="授权时间">{{ shop.authorized_at || '—' }}</el-descriptions-item>
          <el-descriptions-item label="Token 到期">{{ shop.token_expires_at || '—' }}</el-descriptions-item>
        </el-descriptions>

        <div class="shop-detail__actions">
          <el-button
            v-if="canWrite && shop.status === 'authorized'"
            size="small" type="primary" :loading="syncing"
            @click="doSync"
          >同步订单</el-button>
          <el-tooltip content="重新授权将生成新的 OAuth 跳转；现有同步数据不受影响" placement="top">
            <el-button
              v-if="canWrite && (shop.status === 'expired' || shop.status === 'failed' || shop.status === 'authorized')"
              size="small" @click="doReauth"
            >重新授权</el-button>
          </el-tooltip>
        </div>
      </el-card>

      <!-- 四 Tab：商品 / 订单 / 同步任务 / 证书配置 -->
      <el-card v-if="shopCode === 'ready'" shadow="never">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="商品" name="product">
            <el-alert
              type="info" :closable="false" class="mb12"
              title="商品能力验证端点未核（§7#8）"
              description="本 Tab 仅展示已核实的类目映射；「商品能力」未验证前不显示 ✅。上架条件预检需先完成授权。"
            />
            <el-table :data="mappings" size="small" v-loading="mappingLoading">
              <el-table-column prop="platform" label="平台" width="100" />
              <el-table-column prop="system_category" label="系统类目" min-width="140" />
              <el-table-column prop="platform_category_id" label="平台类目 ID" min-width="140" />
              <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
              <template #empty><EmptyState reason="NO_DATA" hint="暂无类目映射（到店铺管理页配置）" /></template>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="订单" name="orders">
            <el-alert
              type="info" :closable="false" class="mb12"
              title="订单能力验证端点未核（§7#8）"
              description="「订单能力」未验证前不显示 ✅；下方仅显示同步触发结果（真实进度）。"
            />
            <el-descriptions :column="2" border size="small" v-if="lastSync">
              <el-descriptions-item label="最近同步">{{ lastSync.time || '—' }}</el-descriptions-item>
              <el-descriptions-item label="同步结果">{{ lastSync.message || '—' }}</el-descriptions-item>
            </el-descriptions>
            <EmptyState v-else reason="NO_DATA" hint="尚无同步记录。点击上方「同步订单」查看真实进度。" />
          </el-tab-pane>

          <el-tab-pane label="同步任务" name="sync">
            <SectionState code="WAITING_EXTERNAL" action-text="查看同步记录" v-if="syncing">
            </SectionState>
            <el-alert
              v-else type="info" :closable="false" class="mb12"
              title="等待平台反馈，当前无需操作"
              description="同步任务状态来自平台侧回执；超时结果只允许重新查询，不做盲重试。"
            />
            <div v-if="shop.last_sync_at" class="sync-info">
              最近同步：{{ shop.last_sync_at }}
            </div>
            <div v-if="shop.sync_alerts && shop.sync_alerts.length" class="sync-alerts">
              <el-alert
                v-for="(a, i) in shop.sync_alerts" :key="i"
                type="warning" :title="String(a)" :closable="false" class="mb8"
              />
            </div>
          </el-tab-pane>

          <el-tab-pane label="证书配置" name="cert">
            <el-alert
              type="info" :closable="false" class="mb12"
              title="证书与密钥管理走凭据管理页"
              description="本页只读展示配置状态；OAuth 凭据仅显尾部与状态，明文不回显（见 /app/settings/credentials）。"
            />
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="OAuth 授权">{{ shopStatusLabel }}</el-descriptions-item>
              <el-descriptions-item label="凭据作用域">平台级（OAuth）+ Workspace 级</el-descriptions-item>
            </el-descriptions>
            <el-button size="small" class="mt12" @click="router.push('/app/settings/credentials')">
              管理凭据
            </el-button>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </SectionState>

    <!-- 重新授权（AsyncActionDialog：二次确认 + 影响说明） -->
    <AsyncActionDialog
      v-model="reauthDialog"
      action="重新授权"
      :context="reauthContext"
      :idempotency-key="reauthKey"
      done-message="授权跳转已生成"
      @submit="onReauthSubmit"
      @requery="load"
    />
  </div>
</template>

<script setup>
/**
 * 店铺详情/健康（蓝图 R1 CH-03，包 2）：/app/channels/shops/:id（hidden）。
 *
 * 数据源：shops.js（授权/最近同步/告警）；订单/商品能力验证未核（§7#8）→
 * 三态中未核项显"未验证"而非 ✅。深链携带 store_id（= :id）与 return_to（PageHeader 回跳）。
 * 纯函数源：shared/shopDetailView.js（三态判定 + 四 Tab + 深链构造）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import AsyncActionDialog from '../../components/AsyncActionDialog.vue'
import { ElMessage } from '../../shared/ui'
import { canWrite as canWritePerm } from '../../permissions/permissions'
import {
  fetchShops, fetchCategoryMappings, refresh, syncOrders,
} from '../../api/domains/shops'
import { shopTriStates, shopTabStates, TRISTATE_LABEL } from '../../shared/shopDetailView'

const route = useRoute()
const router = useRouter()
const shopId = computed(() => route.params.id)
const writable = canWritePerm()
/** 模板侧写操作开关（canWrite 布尔值）。 */
const canWrite = writable

const shop = ref(null)
const loading = ref(false)
const error = ref('')
const activeTab = ref('product')
const mappings = ref([])
const mappingLoading = ref(false)
const syncing = ref(false)
const lastSync = ref(null)

const reauthDialog = ref(false)
const reauthKey = computed(() => `shop:${shopId.value}:reauth:${Date.now()}`)
const reauthContext = computed(() => ({
  type: 'shop',
  id: shopId.value,
  说明: '重新授权将生成新的 OAuth 跳转地址；现有同步数据与订单记录不受影响。',
}))

/** 三态（未核端点 → unverified，禁假 ✅）。 */
const triStates = computed(() => shopTriStates(shop.value || {}))

/** 四 Tab 可用性（当前全可点；证书 Tab 只读）。 */
const tabs = computed(() => shopTabStates(shop.value || {}))
void tabs

/** 11 态：内容态 'ready' / 空 'EMPTY_NEW' / 权限 'NO_PERMISSION' / 加载 / 错误。 */
const shopCode = computed(() => {
  if (error.value) return 'ERROR'
  if (loading.value) return 'LOADING'
  if (!shop.value) return 'EMPTY_NEW'
  return 'ready'
})
const actionText = computed(() => {
  if (shopCode.value === 'EMPTY_NEW') return '进入设置'
  return ''
})

const shopStatusLabel = computed(() => {
  const status = shop.value?.status
  const MAP = { authorized: '授权有效', expired: '授权已过期', failed: '授权失败', pending: '授权中' }
  return MAP[status] || status || '未知'
})

function triTagType(state) {
  return { valid: 'success', invalid: 'danger', unverified: 'info' }[state] || 'info'
}
function triStateText(state) {
  return TRISTATE_LABEL[state] || state
}

function onStateAction() {
  if (shopCode.value === 'EMPTY_NEW') router.push('/app/channels/shops')
}

async function load() {
  loading.value = true
  error.value = ''
  shop.value = null
  try {
    const data = await fetchShops()
    const items = data.items || []
    // shops 域无独立 GET /shops/{id}：按 id 从列表取（同一事实源，不伪造）
    shop.value = items.find((s) => String(s.id) === String(shopId.value)) || null
    if (!shop.value) error.value = `未找到店铺 #${shopId.value}（可能已删除或不在当前空间）`
    loadMappings()
  } catch (e) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadMappings() {
  mappingLoading.value = true
  try {
    const data = await fetchCategoryMappings()
    mappings.value = (data.items || []).filter((m) => m.platform === shop.value?.platform || !shop.value?.platform)
  } catch {
    mappings.value = []
  } finally {
    mappingLoading.value = false
  }
}

async function doSync() {
  syncing.value = true
  activeTab.value = 'orders'
  try {
    const result = await syncOrders(shop.value.id)
    lastSync.value = {
      time: new Date().toLocaleString('zh-CN'),
      message: result?.message || `同步已触发（同步 ${result?.synced ?? '未知'} 条订单）`,
    }
    ElMessage.success('订单同步已触发')
    await load()
  } catch (e) {
    lastSync.value = {
      time: new Date().toLocaleString('zh-CN'),
      message: e?.response?.data?.detail || e?.message || '同步失败',
    }
  } finally {
    syncing.value = false
  }
}

async function doReauth() {
  reauthDialog.value = true
}

/** 重新授权：走既有 authorize（生成 OAuth 跳转），经 AsyncActionDialog 二次确认。 */
async function onReauthSubmit() {
  try {
    const result = await refresh(shop.value.id)
    ElMessage.success('授权已刷新')
    await load()
  } catch (e) {
    ElMessage.warning(e?.response?.data?.detail || e?.message || '刷新失败，请走授权向导')
  }
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.mb12 { margin-bottom: 12px; }
.mb8 { margin-bottom: 8px; }
.mt12 { margin-top: 12px; }
.tri-states {
  display: flex;
  gap: 24px;
}
.tri-states__item { flex: 1; }
.tri-states__hint {
  margin-top: 4px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}
.sync-info, .sync-alerts { font-size: var(--font-size-sm); }
</style>
