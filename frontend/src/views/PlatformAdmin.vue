<template>
  <div class="page">
    <div class="page-header">
      <h3 class="page-title">平台控制台</h3>
      <div v-if="isSuper">
        <el-button type="primary" @click="openCreate">开通租户</el-button>
      </div>
    </div>

    <el-alert v-if="!isSuper" type="warning" show-icon :closable="false"
      title="仅平台服务商账号可访问"
      description="当前账号不是平台服务商（superadmin），无权使用平台管理功能。" />

    <template v-else>
      <el-tabs v-model="activeTab">
        <!-- 1. 总览 -->
        <el-tab-pane label="总览" name="overview">
          <el-row :gutter="16" class="mb16">
            <el-col v-for="c in statCards" :key="c.label" :xs="12" :sm="8" :lg="4">
              <el-card shadow="never" class="stat-card">
                <div class="stat-num">{{ c.value }}</div>
                <div class="stat-label">{{ c.label }}</div>
              </el-card>
            </el-col>
          </el-row>
        </el-tab-pane>

        <!-- 2. 租户管理 -->
        <el-tab-pane label="租户管理" name="tenants">
          <el-card shadow="never">
            <template #header><span>租户列表</span></template>
            <el-table :data="tenants" v-loading="loading" size="small">
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column prop="name" label="公司名称" min-width="150" show-overflow-tooltip />
              <el-table-column label="套餐" width="90">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" :type="planTag(row.plan).type">{{ planTag(row.plan).text }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusTag(row.status).type">{{ statusTag(row.status).text }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="授权到期" width="160">
                <template #default="{ row }">
                  <span :style="isExpired(row) ? 'color:#f56c6c;font-weight:600' : ''">
                    {{ row.license_until || '—' }}<template v-if="isExpired(row)">（已过期）</template>
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="授权备注" min-width="130" show-overflow-tooltip>
                <template #default="{ row }">{{ row.license_note || '—' }}</template>
              </el-table-column>
              <el-table-column label="用量统计" min-width="270">
                <template #default="{ row }">
                  <span class="stat-item">用户 {{ n(row.stats?.users) }}</span>
                  <span class="stat-item">商品 {{ n(row.stats?.products) }}</span>
                  <span class="stat-item">订单 {{ n(row.stats?.orders) }}</span>
                  <span class="stat-item">Listing {{ n(row.stats?.listings) }}</span>
                  <span class="stat-item">广告 {{ n(row.stats?.ads) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="240" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="renew(row)">续期</el-button>
                  <el-button size="small" :type="row.status === 'active' ? 'danger' : 'success'" plain @click="toggleStatus(row)">
                    {{ row.status === 'active' ? '停用' : '恢复' }}
                  </el-button>
                  <el-button size="small" type="primary" :loading="entering === row.id" @click="enter(row)">进入租户</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
              :page-size="pageSize" v-model:current-page="page" @current-change="load" />
          </el-card>
        </el-tab-pane>

        <!-- 3. 访问审计 -->
        <el-tab-pane label="系统日志" name="audit">
          <el-card shadow="never">
            <template #header>
              <div class="card-head">
                <span>代客访问审计</span>
                <el-button size="small" @click="loadLogs">刷新</el-button>
              </div>
            </template>
            <el-table :data="logs" v-loading="logsLoading" size="small">
              <el-table-column prop="operator_name" label="操作人" min-width="120" />
              <el-table-column prop="tenant_id" label="租户 ID" width="100" />
              <el-table-column prop="action" label="操作" min-width="180" />
              <el-table-column prop="created_at" label="时间" min-width="170" />
            </el-table>
          </el-card>

          <el-card shadow="never" style="margin-top:16px">
            <template #header>
              <div class="card-head">
                <span>AI 调用日志（全平台）</span>
                <el-button size="small" @click="loadAiLogs">刷新</el-button>
              </div>
            </template>
            <el-table :data="aiLogs" v-loading="aiLogsLoading" size="small" max-height="420">
              <el-table-column prop="created_at" label="时间" width="160" />
              <el-table-column prop="tenant_id" label="租户" width="70" />
              <el-table-column prop="agent" label="Agent" width="110" />
              <el-table-column prop="action" label="动作" width="140" />
              <el-table-column label="模式" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.mode === 'llm' ? 'success' : 'info'">{{ row.mode }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="70">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.ok ? 'success' : 'danger'">{{ row.ok ? 'OK' : 'FAIL' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="latency_ms" label="耗时ms" width="90" />
              <el-table-column prop="response" label="响应摘要" show-overflow-tooltip />
            </el-table>
          </el-card>
        </el-tab-pane>

        <!-- 4. 系统维护 -->
        <el-tab-pane label="系统维护" name="maintenance">
          <el-card shadow="never">
            <template #header><span>清空演示数据</span></template>
            <el-alert type="warning" show-icon :closable="false"
              title="将删除所有演示商品/订单/会话/广告数据，操作不可恢复，请谨慎执行" />
            <div style="margin-top:12px">
              <el-button type="danger" :loading="purging" @click="purgeDemo">清空演示数据</el-button>
            </div>
            <el-alert v-if="purgeResultText" type="success" show-icon :closable="false" style="margin-top:12px"
              :title="`演示数据已清空：${purgeResultText}`" />
          </el-card>

          <el-card shadow="never" style="margin-top:16px">
            <template #header>
              <div class="card-head">
                <span>平台规则包更新</span>
                <el-button size="small" type="primary" plain :loading="checkingRules"
                  @click="checkRuleUpdates">检查更新</el-button>
              </div>
            </template>
            <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
              title="规则为官方文档整理快照，可配置 ERP_RULES_URL 远程规则源自动同步"
              description="发布前系统按当前规则强制校验，违规拒绝发布以保护店铺。" />
            <el-table :data="platformRules" v-loading="rulesLoading" size="small" empty-text="暂无平台规则数据">
              <el-table-column label="平台" width="160">
                <template #default="{ row }">{{ platformLabel(row.platform) }}</template>
              </el-table-column>
              <el-table-column label="规则版本" width="110">
                <template #default="{ row }">{{ row.version || '—' }}</template>
              </el-table-column>
              <el-table-column label="规则来源" min-width="180" show-overflow-tooltip>
                <template #default="{ row }">{{ row.origin || '官方文档整理快照' }}</template>
              </el-table-column>
              <el-table-column label="标题上限" width="90" align="center">
                <template #default="{ row }">{{ row.summary?.title_max ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="违禁词数" width="90" align="center">
                <template #default="{ row }">{{ row.summary?.banned_words_count ?? '—' }}</template>
              </el-table-column>
            </el-table>
          </el-card>

          <el-card shadow="never" style="margin-top:16px">
            <template #header><span>系统信息</span></template>
            <el-descriptions :column="3" border>
              <el-descriptions-item label="租户总数">{{ fmt(overview?.tenants) }}</el-descriptions-item>
              <el-descriptions-item label="用户总数">{{ fmt(overview?.users) }}</el-descriptions-item>
              <el-descriptions-item label="订单总数">{{ fmt(overview?.orders_total) }}</el-descriptions-item>
            </el-descriptions>
            <div class="muted-line">数据库：SQLite（ERP_DB_URL 可切 MySQL） / 部署：Docker compose 支持</div>
          </el-card>
        </el-tab-pane>
      </el-tabs>
    </template>

    <!-- 开通租户 -->
    <el-dialog v-model="createDialog" title="开通租户" width="520px">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="110px">
        <el-form-item label="公司名称" prop="name">
          <el-input v-model="createForm.name" placeholder="租户公司名称" />
        </el-form-item>
        <el-form-item label="套餐" prop="plan">
          <el-select v-model="createForm.plan" style="width:100%">
            <el-option v-for="p in plans" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="授权天数" prop="license_days">
          <el-input-number v-model="createForm.license_days" :min="1" :max="3650" />
        </el-form-item>
        <el-form-item label="管理员用户名" prop="admin_username">
          <el-input v-model="createForm.admin_username" placeholder="初始管理员登录名" />
        </el-form-item>
        <el-form-item label="管理员密码">
          <el-input v-model="createForm.admin_password" placeholder="留空自动生成" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createTenant">开通</el-button>
      </template>
    </el-dialog>

    <!-- 初始管理员账号（仅显示一次） -->
    <el-dialog v-model="credDialog" title="初始管理员账号" width="460px" :close-on-click-modal="false">
      <el-alert type="warning" show-icon :closable="false" title="账号密码仅显示一次，请立即复制保存" />
      <el-descriptions :column="1" border style="margin-top:12px">
        <el-descriptions-item label="租户">{{ credTenant || '—' }}</el-descriptions-item>
        <el-descriptions-item label="管理员账号">{{ credUsername || '—' }}</el-descriptions-item>
        <el-descriptions-item label="初始密码">{{ credPassword || '—' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="credDialog = false">关闭</el-button>
        <el-button type="primary" @click="copyCred">复制账号密码</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from '../ui'
import api from '../api'
import { clearWorkspaceContext } from '../workspace'
import { roleKey } from '../permissions'

const route = useRoute()
const router = useRouter()

// Phase 1.8：平台身份以 Workspace Context 为准（`roleKey()` 返回大写新枚举）。
// 用 computed 而非 setup 期常量：Context 可能在组件挂载后才就绪。
// legacy `erp_user.role` 不再参与任何权限判断，仅作展示（见 Layout.vue）。
const isSuper = computed(() => roleKey() === 'PLATFORM_ADMIN')

// 页签：支持侧边栏通过 query 定位（/platform-admin?tab=tenants / audit / maintenance）
const VALID_TABS = ['overview', 'tenants', 'audit', 'maintenance']
const normalizeTab = (t) => (VALID_TABS.includes(t) ? t : 'overview')
const activeTab = ref(normalizeTab(route.query.tab))

const overview = ref(null)
const tenants = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const entering = ref('')

const logs = ref([])
const logsLoading = ref(false)

const platformRules = ref([])
const rulesLoading = ref(false)
const checkingRules = ref(false)

const purging = ref(false)
const purgeResult = ref(null)
const purgeResultText = computed(() => {
  const d = purgeResult.value
  if (d && typeof d === 'object') return Object.entries(d).map(([k, v]) => `${k} ${v}`).join('，')
  if (d != null) return String(d)
  return ''
})

const createDialog = ref(false)
const creating = ref(false)
const createFormRef = ref()
const createForm = reactive({ name: '', plan: 'trial', license_days: 365, admin_username: '', admin_password: '' })
const createRules = {
  name: [{ required: true, message: '请输入公司名称', trigger: 'blur' }],
  admin_username: [{ required: true, message: '请输入管理员用户名', trigger: 'blur' }],
}
const plans = [
  { value: 'trial', label: '试用版' },
  { value: 'pro', label: '专业版' },
  { value: 'enterprise', label: '企业版' },
]

const credDialog = ref(false)
const credTenant = ref('')
const credUsername = ref('')
const credPassword = ref('')

const PLANS = {
  trial: { text: '试用版', type: 'info' },
  pro: { text: '专业版', type: 'primary' },
  enterprise: { text: '企业版', type: 'warning' },
}
const planTag = (p) => PLANS[p] || { text: p || '—', type: 'info' }
const STATUSES = {
  active: { text: '正常', type: 'success' },
  suspended: { text: '停用', type: 'danger' },
}
const statusTag = (s) => STATUSES[s] || { text: s || '未知', type: 'info' }
const PLATFORM_LABELS = {
  '1688': '1688（阿里巴巴）',
  shopee: 'Shopee',
  tiktok: 'TikTok Shop',
  amazon: 'Amazon SP-API',
}
const platformLabel = (v) => PLATFORM_LABELS[v] || v || '—'
const n = (v) => (v == null ? 0 : v)
const fmt = (v) => (v == null ? '—' : Number(v).toLocaleString())

function isExpired(row) {
  if (!row.license_until) return false
  const t = new Date(row.license_until).getTime()
  return !Number.isNaN(t) && t < Date.now()
}

const statCards = computed(() => {
  const o = overview.value || {}
  return [
    { label: '租户总数', value: fmt(o.tenants) },
    { label: '正常租户', value: fmt(o.active) },
    { label: '停用租户', value: fmt(o.suspended) },
    { label: '30 天内到期', value: fmt(o.expiring_in_30d) },
    { label: '用户总数', value: fmt(o.users) },
    { label: '订单总数', value: fmt(o.orders_total) },
  ]
})

function normalizeList(data) {
  if (Array.isArray(data)) return { items: data, total: data.length }
  const items = data.items || data.tenants || data.logs || []
  return { items, total: data.total ?? items.length }
}

async function loadOverview() {
  const { data } = await api.get('/admin/overview')
  overview.value = data
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/admin/tenants', { params: { page_num: page.value, page_size: pageSize } })
    const norm = normalizeList(data)
    tenants.value = norm.items
    total.value = norm.total
  } finally { loading.value = false }
}

async function loadLogs() {
  logsLoading.value = true
  try {
    const { data } = await api.get('/admin/access_logs')
    logs.value = normalizeList(data).items
  } finally { logsLoading.value = false }
}

const aiLogs = ref([])
const aiLogsLoading = ref(false)

async function loadAiLogs() {
  aiLogsLoading.value = true
  try {
    const { data } = await api.get('/admin/ai_logs', { params: { limit: 100 } })
    aiLogs.value = normalizeList(data).items
  } finally { aiLogsLoading.value = false }
}

async function loadRules() {
  rulesLoading.value = true
  try {
    const { data } = await api.get('/shops/platform_rules')
    platformRules.value = data.items || []
  } finally { rulesLoading.value = false }
}

// 进入审计/维护页签时按需加载
function lazyLoadTab(name) {
  if (name === 'audit') { loadLogs().catch(() => {}); loadAiLogs().catch(() => {}) }
  else if (name === 'maintenance') loadRules().catch(() => {})
}

// 页签切换同步到地址栏 query，保持侧边栏高亮一致；query 变化（如侧边栏跳转）反向驱动页签
watch(activeTab, (name) => {
  const q = { ...route.query }
  if (name === 'overview') delete q.tab
  else q.tab = name
  router.replace({ path: '/platform-admin', query: q }).catch(() => {})
  lazyLoadTab(name)
})

watch(() => route.query.tab, (t) => {
  if (route.path !== '/platform-admin') return
  const name = normalizeTab(t)
  if (name !== activeTab.value) activeTab.value = name
})

async function checkRuleUpdates() {
  const targets = platformRules.value.map((r) => r.platform)
  if (!targets.length) { ElMessage.warning('暂无平台规则可检查'); return }
  checkingRules.value = true
  const done = []
  try {
    for (const p of targets) {
      try {
        const { data } = await api.post(`/shops/platform_rules/${p}/check_updates`)
        done.push(`${platformLabel(p)}：${data?.hint || (data?.updated ? '发现更新，已同步' : '已是最新')}`)
      } catch { /* 失败已由全局拦截器提示 */ }
    }
  } finally { checkingRules.value = false }
  if (done.length) {
    ElMessage({ type: 'success', message: done.join('；'), duration: 5000, showClose: true })
  }
  loadRules()
}

async function purgeDemo() {
  try {
    await ElMessageBox.prompt(
      '此操作将删除所有演示商品/订单/会话/广告数据，且不可恢复！请输入「清空」确认执行。',
      '强警告：清空演示数据',
      {
        type: 'warning',
        confirmButtonText: '确认清空',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
        inputPlaceholder: '请输入：清空',
        inputPattern: /^清空$/,
        inputErrorMessage: '请输入「清空」以确认执行',
      },
    )
  } catch { return }
  purging.value = true
  try {
    const { data } = await api.post('/shops/purge_demo_data')
    purgeResult.value = data?.deleted ?? null
    ElMessage.success(purgeResultText.value ? `演示数据已清空：${purgeResultText.value}` : '演示数据已清空')
    loadOverview().catch(() => {})
  } finally { purging.value = false }
}

function openCreate() {
  Object.assign(createForm, { name: '', plan: 'trial', license_days: 365, admin_username: '', admin_password: '' })
  createDialog.value = true
}

async function createTenant() {
  const ok = await createFormRef.value.validate().catch(() => false)
  if (!ok) return
  creating.value = true
  try {
    const body = {
      name: createForm.name.trim(),
      plan: createForm.plan,
      license_days: Number(createForm.license_days),
      admin_username: createForm.admin_username.trim(),
    }
    if (createForm.admin_password) body.admin_password = createForm.admin_password
    const { data } = await api.post('/admin/tenants', body)
    createDialog.value = false
    credTenant.value = body.name
    credUsername.value = data.admin_username || data.username || ''
    credPassword.value = data.admin_password || data.password || ''
    credDialog.value = true
    page.value = 1
    load().catch(() => {})
    loadOverview().catch(() => {})
  } finally { creating.value = false }
}

async function renew(row) {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt('请输入续期天数，将在当前授权到期时间上顺延', `续期 — ${row.name}`, {
      confirmButtonText: '确认续期',
      cancelButtonText: '取消',
      inputValue: '365',
      inputPattern: /^\d+$/,
      inputErrorMessage: '请输入正整数天数',
    }))
  } catch { return }
  await api.put(`/admin/tenants/${row.id}`, { license_days: Number(value) })
  ElMessage.success('续期成功')
  load().catch(() => {})
  loadOverview().catch(() => {})
}

async function toggleStatus(row) {
  const suspend = row.status === 'active'
  const target = suspend ? 'suspended' : 'active'
  const actionText = suspend ? '停用' : '恢复'
  try {
    await ElMessageBox.confirm(
      suspend
        ? `确定停用租户「${row.name}」？停用后该租户用户将无法登录使用。`
        : `确定恢复租户「${row.name}」？`,
      `${actionText}租户`,
      { type: suspend ? 'warning' : 'info' },
    )
  } catch { return }
  await api.put(`/admin/tenants/${row.id}`, { status: target })
  ElMessage.success(`已${actionText}`)
  load().catch(() => {})
  loadOverview().catch(() => {})
}

async function enter(row) {
  entering.value = row.id
  try {
    // 保存平台身份用于退出时还原；user 快照仅作展示，不再承载权限语义。
    localStorage.setItem('erp_impersonating', JSON.stringify({
      token: localStorage.getItem('erp_token'),
      user: JSON.parse(localStorage.getItem('erp_user') || 'null'),
      tenant: row.name,
    }))
    const { data } = await api.post(`/admin/tenants/${row.id}/enter`)
    if (data.token) localStorage.setItem('erp_token', data.token)
    // Phase 1.8：不再伪造 legacy 角色。进入后身份完全由后端签发的代客 token
    // 决定的 Workspace Context 提供（`is_impersonating=true` + 真实租户角色）。
    // 清掉旧 Context 缓存，避免平台身份被带到租户工作台。
    clearWorkspaceContext()
    ElMessage.success('已进入租户工作台，操作将记录审计')
    window.location.href = '/dashboard'
  } catch (e) {
    const saved = JSON.parse(localStorage.getItem('erp_impersonating') || 'null')
    if (saved?.token && saved?.user) { localStorage.setItem('erp_token', saved.token); localStorage.setItem('erp_user', JSON.stringify(saved.user)) }
    localStorage.removeItem('erp_impersonating'); throw e
  } finally { entering.value = '' }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch { return false }
  }
}

async function copyCred() {
  const text = `租户：${credTenant.value}\n管理员账号：${credUsername.value}\n初始密码：${credPassword.value}`
  const ok = await copyText(text)
  if (ok) ElMessage.success('已复制，请妥善保存')
  else ElMessage.error('复制失败，请手动复制')
}

onMounted(() => {
  if (!isSuper.value) return
  loadOverview().catch(() => {})
  load().catch(() => {})
  lazyLoadTab(activeTab.value)
})
</script>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; }
.page-title { margin: 0; font-size: 18px; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.stat-card { text-align: center; }
.stat-num { font-size: 24px; font-weight: 700; color: #303133; }
.stat-label { color: #909399; font-size: 13px; margin-top: 4px; }
.stat-item { display: inline-block; margin-right: 12px; color: #606266; font-size: 12px; }
.stat-item:last-child { margin-right: 0; }
.muted-line { color: #909399; font-size: 12px; margin-top: 12px; }
</style>
