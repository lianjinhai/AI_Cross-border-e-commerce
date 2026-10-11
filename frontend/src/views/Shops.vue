<template>
  <div class="page">
    <div class="page-header">
      <h3 class="page-title">店铺授权</h3>
      <el-button v-if="can('workspace:write')" type="primary" @click="openAdd">添加店铺</el-button>
    </div>
    <el-alert type="info" :closable="false" show-icon style="margin-bottom:16px"
      title="真实拉单需要平台开放平台 AppKey"
      description="流程：添加店铺 → 填 AppKey/Secret → 打开授权链接登录授权 → 粘贴授权码 → 同步订单。" />

    <!-- 货源店铺（1688 搜品 / 一件代发下单） -->
    <el-card shadow="never" class="mb16">
      <template #header>
        <div class="card-head">
          <span>📦 货源店铺（1688 搜品 / 一件代发下单）</span>
          <el-tag size="small" type="info">{{ sourceShops.length }} 家</el-tag>
        </div>
      </template>
      <el-row :gutter="16" v-loading="loading">
        <el-col v-for="s in sourceShops" :key="s.id" :xs="24" :sm="12" :lg="8" style="margin-bottom:16px">
          <el-card shadow="hover" class="shop-card">
            <template #header>
              <div class="card-head">
                <span class="shop-name">{{ s.shop_name || `店铺 #${s.id}` }}</span>
                <span>
                  <el-tag size="small" type="info" effect="plain">{{ s.platform_label || s.platform }}</el-tag>
                  <el-tag size="small" type="warning" effect="plain" style="margin-left:6px">货源</el-tag>
                  <el-tag v-if="s.is_demo" size="small" type="info" effect="plain" style="margin-left:6px">演示</el-tag>
                </span>
              </div>
            </template>
            <div class="status-row">
              <el-tag size="small" :type="statusTag(s.status).type">{{ statusTag(s.status).text }}</el-tag>
              <span v-if="s.token_expire_at" class="muted">Token 至 {{ s.token_expire_at }}</span>
            </div>
            <div class="kv"><span class="k">店铺 ID</span><span>{{ s.shop_id || '—' }}</span></div>
            <div class="kv"><span class="k">AppKey</span><span>{{ s.app_key || '—' }}</span></div>
            <el-alert v-if="s.auth_message" :title="s.auth_message"
              :type="s.status === 'authorized' ? 'success' : 'warning'" :closable="false" style="margin:8px 0" />
            <div class="btns">
              <el-button size="small" @click="openConfig(s)">配置</el-button>
              <el-button v-if="can('workspace:write')" size="small" type="primary" plain :loading="acting === `auth-${s.id}`" @click="authorize(s)">发起授权</el-button>
              <el-button v-if="can('workspace:write')" size="small" type="success" plain @click="openCode(s)">粘贴授权码</el-button>
              <el-tooltip v-if="s.status === 'authorized' && s.token_valid === false"
                content="该平台不支持自动刷新 Token" placement="top" :disabled="canRefresh(s)">
                <span>
                  <el-button size="small" type="primary" link :disabled="!canRefresh(s)"
                    :loading="acting === `refresh-${s.id}`" @click="refreshToken(s)">刷新Token</el-button>
                </span>
              </el-tooltip>
              <el-button v-if="can('workspace:write')" size="small" type="danger" plain @click="removeShop(s)">删除</el-button>
            </div>
            <div class="muted" style="margin-top:4px">用于采集与一件代发下单，不用于销售上架</div>
          </el-card>
        </el-col>
      </el-row>
      <el-empty v-if="!loading && !sourceShops.length" description="暂无货源店铺（添加店铺时选「货源」角色，或选 1688 平台自动归入）" :image-size="60" />
    </el-card>

    <!-- 销售店铺（上架 / 拉单） -->
    <el-card shadow="never" class="mb16">
      <template #header>
        <div class="card-head">
          <span>🛒 销售店铺（上架 / 拉单）</span>
          <el-tag size="small" type="info">{{ salesShops.length }} 家</el-tag>
        </div>
      </template>
      <el-row :gutter="16" v-loading="loading">
        <el-col v-for="s in salesShops" :key="s.id" :xs="24" :sm="12" :lg="8" style="margin-bottom:16px">
          <el-card shadow="hover" class="shop-card">
            <template #header>
              <div class="card-head">
                <span class="shop-name">{{ s.shop_name || `店铺 #${s.id}` }}</span>
                <span>
                  <el-tag size="small" type="info" effect="plain">{{ s.platform_label || s.platform }}</el-tag>
                  <el-tag size="small" type="primary" effect="plain" style="margin-left:6px">销售</el-tag>
                  <el-tag size="small" :type="integrationTag(s.platform).type" effect="plain" style="margin-left:6px">
                    {{ integrationTag(s.platform).text }}
                  </el-tag>
                  <el-tag v-if="s.is_demo" size="small" type="info" effect="plain" style="margin-left:6px">演示</el-tag>
                </span>
              </div>
            </template>
            <div class="status-row">
              <el-tag size="small" :type="statusTag(s.status).type">{{ statusTag(s.status).text }}</el-tag>
              <span v-if="s.token_expire_at" class="muted">Token 至 {{ s.token_expire_at }}</span>
            </div>
            <div class="kv"><span class="k">店铺 ID</span><span>{{ s.shop_id || '—' }}</span></div>
            <div class="kv"><span class="k">AppKey</span><span>{{ s.app_key || '—' }}</span></div>
            <el-alert v-if="s.auth_message" :title="s.auth_message"
              :type="s.status === 'authorized' ? 'success' : 'warning'" :closable="false" style="margin:8px 0" />
            <div class="btns">
              <el-button size="small" @click="openConfig(s)">配置</el-button>
              <el-button size="small" type="primary" plain :loading="acting === `auth-${s.id}`" @click="authorize(s)">发起授权</el-button>
              <el-button size="small" type="success" plain @click="openCode(s)">粘贴授权码</el-button>
              <el-tooltip content="该平台拉单协议待接入" placement="top" :disabled="canOrderSync(s)">
                <span>
                  <el-button v-if="can('workspace:write')" size="small" type="warning" plain :disabled="!canOrderSync(s)"
                    :loading="acting === `sync-${s.id}`" @click="syncOrders(s)">同步订单</el-button>
                </span>
              </el-tooltip>
              <el-tooltip v-if="s.status === 'authorized' && s.token_valid === false"
                content="该平台不支持自动刷新 Token" placement="top" :disabled="canRefresh(s)">
                <span>
                  <el-button size="small" type="primary" link :disabled="!canRefresh(s)"
                    :loading="acting === `refresh-${s.id}`" @click="refreshToken(s)">刷新Token</el-button>
                </span>
              </el-tooltip>
              <el-button v-if="can('workspace:write')" size="small" type="danger" plain @click="removeShop(s)">删除</el-button>
            </div>
            <div v-if="metaFor(s.platform)?.markets?.length" class="muted" style="margin-top:4px">
              目标市场：{{ metaFor(s.platform).markets.join(' / ') }} · {{ metaFor(s.platform).auth_model }}
            </div>
            <div v-for="item in metaFor(s.platform)?.limitations || []" :key="item" class="muted" style="margin-top:4px">
              {{ item }}
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-empty v-if="!loading && !salesShops.length" description="暂无销售店铺（用于上架与订单同步）" :image-size="60" />
    </el-card>

    <el-card shadow="never" style="margin-top:16px">
      <template #header>
        <div class="card-head">
          <span class="block-title">类目映射</span>
          <el-button v-if="can('workspace:write')" size="small" type="primary" @click="openMapAdd">新增映射</el-button>
        </div>
      </template>
      <el-table :data="mappings" v-loading="mappingsLoading" size="small"
        empty-text="暂无类目映射，点击右上角「新增映射」添加">
        <el-table-column label="平台" width="160">
          <template #default="{ row }">{{ platformLabel(row.platform) }}</template>
        </el-table-column>
        <el-table-column label="系统类目" prop="system_category" min-width="120" />
        <el-table-column label="平台类目ID" prop="platform_category_id" min-width="140" />
        <el-table-column label="备注" min-width="160">
          <template #default="{ row }">{{ row.note || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button v-if="can('workspace:write')" size="small" type="danger" link @click="removeMapping(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="addDialog" title="添加店铺" width="480px">
      <el-form ref="addFormRef" :model="addForm" :rules="rules" label-width="110px">
        <el-form-item label="平台" prop="platform">
          <el-select v-model="addForm.platform" placeholder="请选择平台" style="width:100%"
            @change="onPlatformChange">
            <el-option v-for="p in platforms" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="店铺角色" prop="role">
          <el-radio-group v-model="addForm.role">
            <el-radio-button value="source">货源（搜品/一件代发）</el-radio-button>
            <el-radio-button value="sales">销售（上架/拉单）</el-radio-button>
          </el-radio-group>
          <div class="muted" style="font-size:12px;margin-top:4px">
            货源店铺用于 1688 采集与代发下单；销售店铺用于商品上架与订单同步，两类不可混用
          </div>
        </el-form-item>
        <el-form-item label="店铺名">
          <el-input v-model="addForm.shop_name" placeholder="如：我的 Shopee 店" />
        </el-form-item>
        <shop-commerce-fields :model="addForm" />
        <el-form-item label="店铺ID/登录ID">
          <el-input v-model="addForm.shop_id" placeholder="平台店铺 ID 或登录账号" />
        </el-form-item>
        <el-form-item label="AppKey" prop="app_key">
          <el-input v-model="addForm.app_key" placeholder="平台开放平台 AppKey" />
        </el-form-item>
        <el-form-item label="AppSecret">
          <el-input v-model="addForm.app_secret" type="password" show-password placeholder="平台开放平台 AppSecret" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createShop">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="configDialog" :title="`配置店铺 #${configForm.id || ''}`" width="480px">
      <el-form ref="configFormRef" :model="configForm" :rules="rules" label-width="110px">
        <el-form-item label="平台">
          <el-input :model-value="platformLabel(configForm.platform)" disabled />
        </el-form-item>
        <el-form-item label="店铺名">
          <el-input v-model="configForm.shop_name" />
        </el-form-item>
        <shop-commerce-fields :model="configForm" />
        <el-form-item label="店铺ID/登录ID">
          <el-input v-model="configForm.shop_id" />
        </el-form-item>
        <el-form-item label="AppKey" prop="app_key">
          <el-input v-model="configForm.app_key" />
        </el-form-item>
        <el-form-item label="AppSecret">
          <el-input v-model="configForm.app_secret" type="password" show-password placeholder="留空则不修改" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="codeDialog" :title="`粘贴授权码 — ${codeShop?.shop_name || ''}`" width="480px">
      <el-input v-model="authCode" type="textarea" :rows="4"
        placeholder="粘贴授权完成后平台返回的授权码" />
      <template #footer>
        <el-button @click="codeDialog = false">取消</el-button>
        <el-button v-if="can('workspace:write')" type="primary" :loading="saving" @click="submitCode">提交授权码</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mapDialog" title="新增类目映射" width="480px">
      <el-form ref="mapFormRef" :model="mapForm" :rules="mapRules" label-width="110px">
        <el-form-item label="平台" prop="platform">
          <el-select v-model="mapForm.platform" placeholder="请选择平台" style="width:100%">
            <el-option v-for="p in mappingPlatformOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="系统类目" prop="system_category">
          <el-select v-model="mapForm.system_category" placeholder="请选择系统八大类目" style="width:100%">
            <el-option v-for="c in SYSTEM_CATEGORIES" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="平台类目ID" prop="platform_category_id">
          <el-input v-model="mapForm.platform_category_id" :placeholder="catIdPlaceholder(mapForm.platform)" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="mapForm.note" placeholder="选填，如：厨房小工具的对应关系" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mapDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitMapping">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'
import { can } from '../permissions'
import ShopCommerceFields from '../components/ShopCommerceFields.vue'
import { shopCommerceFields } from '../composables/shopCommerce'

const shops = ref([])
const loading = ref(false)
const saving = ref(false)
const acting = ref('')

const platforms = [
  { value: '1688', label: '1688（阿里巴巴）' },
  { value: 'tiktok', label: 'TikTok Shop 美国站' },
  { value: 'shopee', label: 'Shopee 新加坡站' },
  { value: 'amazon', label: 'Amazon 美国站 SP-API（待接入）' },
  { value: 'ebay', label: 'eBay 美国站' },
  { value: 'walmart', label: 'Walmart 美国站（规划）' },
  { value: 'lazada', label: 'Lazada 东南亚（规划）' },
  { value: 'aliexpress', label: 'AliExpress（规划）' },
  { value: 'temu', label: 'Temu 跨境店（受限）' },
  { value: 'shopify', label: 'Shopify Markets 独立站（规划）' },
  { value: 'mercadolibre', label: 'Mercado Libre 拉美（规划）' },
  { value: 'shein', label: 'SHEIN Marketplace（受限）' },
]
const platformMeta = ref([])
const metaFor = (platform) => platformMeta.value.find((m) => m.platform === platform) || null
const platformLabel = (v) => {
  const meta = metaFor(v)
  if (meta?.label) return meta.label
  return (platforms.find((p) => p.value === v) || { label: v || '—' }).label
}
const roleOf = (s) => s.role || metaFor(s.platform)?.role || (s.platform === '1688' ? 'source' : 'sales')
const sourceShops = computed(() => shops.value.filter((s) => roleOf(s) === 'source'))
const salesShops = computed(() => shops.value.filter((s) => roleOf(s) !== 'source'))
const canOrderSync = (s) => metaFor(s.platform)?.can_order_sync !== false
const canPublish = (s) => metaFor(s.platform)?.can_publish !== false
const canRefresh = (s) => metaFor(s.platform)?.can_refresh !== false
const integrationTag = (platform) => {
  const status = metaFor(platform)?.integration_status
  return {
    ready: { text: '已接通', type: 'success' },
    partial: { text: '部分接通', type: 'warning' },
    protocol_ready_unverified: { text: '协议已实现·待实店验收', type: 'warning' },
    restricted: { text: '准入受限', type: 'danger' },
    planned: { text: '已规划', type: 'info' },
  }[status] || { text: '待确认', type: 'info' }
}

async function loadPlatformMeta() {
  try {
    const { data } = await api.get('/shops/platforms')
    platformMeta.value = data.items || []
  } catch { /* 元数据加载失败不阻塞页面，按钮默认可用 */ }
}

const STATUS = {
  authorized: { text: '已授权', type: 'success' },
  pending: { text: '未授权', type: 'info' },
  failed: { text: '授权失败', type: 'danger' },
  expired: { text: '已过期', type: 'warning' },
}
const statusTag = (s) => STATUS[s] || { text: s || '未知', type: 'info' }

const rules = {
  platform: [{ required: true, message: '请选择平台', trigger: 'change' }],
  app_key: [{ required: true, message: '请填写 AppKey', trigger: 'blur' }],
}

const addDialog = ref(false)
const addFormRef = ref()
const addForm = reactive({ platform: '', role: '', shop_name: '', shop_id: '', app_key: '', app_secret: '' })

function onPlatformChange(platform) {
  // 按平台推导默认角色：1688=货源，其余=销售（用户可手动改）
  addForm.role = platform === '1688' ? 'source' : 'sales'
}

const configDialog = ref(false)
const configFormRef = ref()
const configForm = reactive({ id: null, platform: '', shop_name: '', shop_id: '', app_key: '', app_secret: '' })

const codeDialog = ref(false)
const codeShop = ref(null)
const authCode = ref('')

const SYSTEM_CATEGORIES = ['家居', '3C配件', '宠物用品', '户外运动', '美妆工具', '母婴用品', '厨房用品', '服饰配件']

const mappings = ref([])
const mappingsLoading = ref(false)

async function loadMappings() {
  mappingsLoading.value = true
  try {
    const { data } = await api.get('/shops/category-mappings')
    mappings.value = data.items || []
  } finally { mappingsLoading.value = false }
}

const mappingPlatformOptions = computed(() => platformMeta.value.length
  ? platformMeta.value.map((m) => ({ value: m.platform, label: m.label || m.platform }))
  : platforms.map((p) => ({ value: p.value, label: p.label })))

const catIdPlaceholder = (platform) => {
  const meta = metaFor(platform)
  return meta?.category_mapping_hint || '平台类目ID，见平台文档'
}

const mapDialog = ref(false)
const mapFormRef = ref()
const mapForm = reactive({ platform: '', system_category: '', platform_category_id: '', note: '' })
const mapRules = {
  platform: [{ required: true, message: '请选择平台', trigger: 'change' }],
  system_category: [{ required: true, message: '请选择系统类目', trigger: 'change' }],
  platform_category_id: [{ required: true, message: '请填写平台类目ID', trigger: 'blur' }],
}

function openMapAdd() {
  Object.assign(mapForm, { platform: '', system_category: '', platform_category_id: '', note: '' })
  mapDialog.value = true
}

async function submitMapping() {
  const ok = await mapFormRef.value.validate().catch(() => false)
  if (!ok) return
  saving.value = true
  try {
    await api.post('/shops/category-mappings', { ...mapForm })
    ElMessage.success('类目映射已保存')
    mapDialog.value = false
    loadMappings()
  } finally { saving.value = false }
}

async function removeMapping(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${platformLabel(row.platform)} - ${row.system_category}」的类目映射？`,
      '提示', { type: 'warning' })
  } catch { return }
  await api.delete(`/shops/category-mappings/${row.id}`)
  ElMessage.success('已删除')
  loadMappings()
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/shops')
    shops.value = data.items || []
  } finally { loading.value = false }
}

function openAdd() {
  Object.assign(addForm, { ...shopCommerceFields(), platform: '', role: '', shop_name: '', shop_id: '', app_key: '', app_secret: '' })
  addDialog.value = true
}

async function createShop() {
  const ok = await addFormRef.value.validate().catch(() => false)
  if (!ok) return
  if (!addForm.role) {
    ElMessage.warning('请选择店铺角色（货源/销售）')
    return
  }
  saving.value = true
  try {
    await api.post('/shops', { ...addForm })
    ElMessage.success('店铺已添加')
    addDialog.value = false
    load()
  } finally { saving.value = false }
}

function openConfig(s) {
  Object.assign(configForm, {
    id: s.id, platform: s.platform, shop_name: s.shop_name,
    shop_id: s.shop_id, app_key: s.app_key, app_secret: '', ...shopCommerceFields(s),
  })
  configDialog.value = true
}

async function saveConfig() {
  const ok = await configFormRef.value.validate().catch(() => false)
  if (!ok) return
  const body = { ...shopCommerceFields(configForm), shop_name: configForm.shop_name, shop_id: configForm.shop_id, app_key: configForm.app_key }
  if (configForm.app_secret) body.app_secret = configForm.app_secret
  saving.value = true
  try {
    await api.put(`/shops/${configForm.id}`, body)
    ElMessage.success('配置已保存')
    configDialog.value = false
    load()
  } finally { saving.value = false }
}

async function authorize(s) {
  acting.value = `auth-${s.id}`
  try {
    const { data } = await api.get(`/shops/${s.id}/authorize_url`)
    if (data.authorize_url) window.open(data.authorize_url, '_blank')
    ElMessage.info(data.manual_hint || '已打开授权页面，请登录并完成授权')
  } finally { acting.value = '' }
}

function openCode(s) {
  codeShop.value = s
  authCode.value = ''
  codeDialog.value = true
}

async function submitCode() {
  const code = authCode.value.trim()
  if (!code) { ElMessage.warning('请粘贴授权码'); return }
  saving.value = true
  try {
    const { data } = await api.post(`/shops/${codeShop.value.id}/exchange_code`, { code })
    ElMessage.success(`授权成功：${data.message}`)
    codeDialog.value = false
    load()
  } finally { saving.value = false }
}

async function syncOrders(s) {
  acting.value = `sync-${s.id}`
  try {
    const { data } = await api.post(`/shops/${s.id}/sync_orders`)
    ElMessage.success(`同步 ${data.synced} 条订单（来源:${data.source}）`)
    load()
  } finally { acting.value = '' }
}

async function refreshToken(s) {
  acting.value = `refresh-${s.id}`
  try {
    await api.post(`/shops/${s.id}/refresh`)
    ElMessage.success('Token 已刷新')
    load()
  } finally { acting.value = '' }
}

async function removeShop(s) {
  try {
    await ElMessageBox.confirm(`确定删除店铺「${s.shop_name || s.shop_id || s.id}」？删除后需重新添加。`, '提示', { type: 'warning' })
  } catch { return }
  await api.delete(`/shops/${s.id}`)
  ElMessage.success('已删除')
  load()
}

onMounted(() => {
  load()
  loadPlatformMeta()
  loadMappings()
})
</script>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; }
.page-title { margin: 0; font-size: 18px; }
.shop-card { height: 100%; }
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.shop-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.muted { color: #909399; font-size: 12px; }
.kv { display: flex; font-size: 13px; line-height: 22px; }
.kv .k { color: #909399; width: 70px; flex: none; }
.btns { display: flex; flex-wrap: wrap; gap: 0; margin-top: 4px; }
.block-title { font-weight: 600; }
</style>
