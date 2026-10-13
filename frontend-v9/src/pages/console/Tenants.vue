<template>
  <div class="page">
    <PageHeader title="租户管理" subtitle="开通 · 续期 · 停启用 · 代客进入">
      <template #actions>
        <el-button type="primary" size="small" @click="openCreate">开通租户</el-button>
      </template>
    </PageHeader>

    <el-card>
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
        <el-table-column label="授权到期" width="150">
          <template #default="{ row }">
            <span :class="{ expired: isExpired(row.license_until) }">
              {{ row.license_until || '—' }}<template v-if="isExpired(row.license_until)">（已过期）</template>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="用量" min-width="220">
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
            <el-button size="small" type="primary" :loading="entering === row.id"
              :disabled="row.status !== 'active'" @click="enter(row)">进入租户</el-button>
          </template>
        </el-table-column>
        <template #empty><EmptyState reason="NO_DATA" hint="还没有租户，点击右上角「开通租户」" /></template>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" v-model:current-page="page" @current-change="load" />
    </el-card>

    <!-- 开通租户向导 -->
    <el-dialog v-model="createDialog" title="开通租户" width="520px">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="110px">
        <el-form-item label="公司名称" prop="name"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="套餐" prop="plan">
          <el-select v-model="createForm.plan" style="width:100%">
            <el-option label="试用版" value="trial" /><el-option label="专业版" value="pro" />
            <el-option label="企业版" value="enterprise" />
          </el-select>
        </el-form-item>
        <el-form-item label="授权天数" prop="license_days">
          <el-input-number v-model="createForm.license_days" :min="1" :max="3650" />
        </el-form-item>
        <el-form-item label="管理员用户名" prop="admin_username"><el-input v-model="createForm.admin_username" /></el-form-item>
        <el-form-item label="管理员密码">
          <el-input v-model="createForm.admin_password" placeholder="留空自动生成" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">开通</el-button>
      </template>
    </el-dialog>

    <!-- 初始凭据一次性展示（后端仅返回一次） -->
    <el-dialog v-model="credDialog" title="初始管理员账号" width="460px" :close-on-click-modal="false">
      <el-alert type="warning" show-icon :closable="false" title="账号密码仅显示一次，请立即复制保存" />
      <el-descriptions :column="1" border class="mt12">
        <el-descriptions-item label="租户">{{ cred.tenant }}</el-descriptions-item>
        <el-descriptions-item label="管理员账号">{{ cred.username }}</el-descriptions-item>
        <el-descriptions-item label="初始密码">{{ cred.password }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="credDialog = false">关闭</el-button>
        <el-button type="primary" @click="copyCred">复制账号密码</el-button>
      </template>
    </el-dialog>

    <!-- PC-02（蓝图 §5.19）：代客操作挂审计字段（原因/时间/操作者），最近代客记录可回看 -->
    <el-card v-if="recentAudits.length" shadow="never" class="mt16">
      <template #header><span class="card-title">最近代客操作（本地审计）</span></template>
      <el-table :data="recentAudits" size="small">
        <el-table-column prop="tenant" label="租户" width="140" show-overflow-tooltip />
        <el-table-column prop="operator" label="操作者" width="140" show-overflow-tooltip />
        <el-table-column prop="reason" label="原因" min-width="180" show-overflow-tooltip />
        <el-table-column prop="at" label="时间" width="180" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
/**
 * 租户管理（UX-E，旧 /platform-admin tab=tenants 拆分）：
 * 开通向导（凭据一次性展示+复制）→ 续期/停启用 → **显式确认后代客进入**；
 * 代客快照/还原统一走 composables/impersonation.js，横幅由目标空间壳常显。
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import EmptyState from '../../components/EmptyState.vue'
import { currentUser, roleKey } from '../../permissions/permissions'
import { clearWorkspaceContext } from '../../shared/workspace'
import { createTenant, enterTenant, fetchTenants, updateTenant } from '../../api/domains/admin'
import { isImpersonating, saveImpersonationSnapshot } from '../../composables/impersonation'
import { fmt, isExpired, n, planTag, statusTag } from '../../composables/tenantAdmin'

const tenants = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const loading = ref(false)
const entering = ref('')

/** PC-02 代客审计（本地留痕）：{tenant, operator, reason, at}[]。读自 localStorage，跨会话可回看。 */
const AUDIT_KEY = 'v9_impersonation_audits'
const recentAudits = ref(loadRecentAudits())

function loadRecentAudits() {
  try {
    const list = JSON.parse(localStorage.getItem(AUDIT_KEY) || '[]')
    return Array.isArray(list) ? list.slice(0, 20) : []
  } catch { return [] }
}

function recordAudit(entry) {
  const list = loadRecentAudits()
  list.unshift(entry)
  localStorage.setItem(AUDIT_KEY, JSON.stringify(list.slice(0, 50)))
  recentAudits.value = list.slice(0, 20)
}

const createDialog = ref(false)
const creating = ref(false)
const createFormRef = ref()
const createForm = reactive({ name: '', plan: 'trial', license_days: 365, admin_username: '', admin_password: '' })
const createRules = {
  name: [{ required: true, message: '请输入公司名称', trigger: 'blur' }],
  admin_username: [{ required: true, message: '请输入管理员用户名', trigger: 'blur' }],
}

const credDialog = ref(false)
const cred = reactive({ tenant: '', username: '', password: '' })

async function load() {
  loading.value = true
  try {
    const data = await fetchTenants({ page: page.value, pageSize })
    tenants.value = data.items || []
    total.value = data.total || 0
  } finally { loading.value = false }
}

function openCreate() {
  Object.assign(createForm, { name: '', plan: 'trial', license_days: 365, admin_username: '', admin_password: '' })
  createDialog.value = true
}

async function submitCreate() {
  const ok = await createFormRef.value.validate().catch(() => false)
  if (!ok) return
  creating.value = true
  try {
    const body = {
      name: createForm.name.trim(), plan: createForm.plan,
      license_days: Number(createForm.license_days), admin_username: createForm.admin_username.trim(),
    }
    if (createForm.admin_password) body.admin_password = createForm.admin_password
    const data = await createTenant(body)
    createDialog.value = false
    cred.tenant = body.name
    cred.username = data.admin_username || data.username || ''
    cred.password = data.admin_password || data.password || ''
    credDialog.value = true
    await load()
  } finally { creating.value = false }
}

async function copyCred() {
  const text = `租户：${cred.tenant}\n管理员账号：${cred.username}\n初始密码：${cred.password}`
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制，请妥善保存')
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

async function renew(row) {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt('请输入续期天数，将在当前授权到期时间上顺延', `续期 — ${row.name}`, {
      inputValue: '365', inputPattern: /^\d+$/, inputErrorMessage: '请输入正整数天数',
    }))
  } catch { return }
  await updateTenant(row.id, { license_days: Number(value) })
  ElMessage.success('续期成功')
  await load()
}

async function toggleStatus(row) {
  const suspend = row.status === 'active'
  try {
    await ElMessageBox.confirm(
      suspend ? `确定停用租户「${row.name}」？停用后该租户用户将无法登录使用。` : `确定恢复租户「${row.name}」？`,
      suspend ? '停用租户' : '恢复租户',
      { type: suspend ? 'warning' : 'info' },
    )
  } catch { return }
  await updateTenant(row.id, { status: suspend ? 'suspended' : 'active' })
  ElMessage.success(suspend ? '已停用' : '已恢复')
  await load()
}

/** 代客进入（PC-02）：填原因 → 显式确认 → 保存平台身份快照 + 挂审计字段（原因/时间/操作者）→ 换租户 token → 进 /app。 */
async function enter(row) {
  if (isImpersonating()) {
    ElMessage.warning('已在代客会话中，请先退出当前租户')
    return
  }
  // PC-02：代客须填原因（审计字段之一），缺失即阻断，避免无因代客。
  let reason = ''
  try {
    ;({ value: reason } = await ElMessageBox.prompt(
      '请填写代客进入原因（将连同操作者、时间一并记录审计）',
      `代客进入租户「${row.name}」`,
      {
        inputValue: '', confirmButtonText: '确认进入',
        inputPlaceholder: '必填，例如：协助排查租户订单同步问题',
        inputValidator: (v) => (v && v.trim().length > 0 ? true : '代客进入必须填写原因'),
        inputErrorMessage: '代客进入必须填写原因',
      },
    ))
  } catch { return }
  reason = String(reason || '').trim()
  if (!reason) {
    ElMessage.warning('代客进入必须填写原因')
    return
  }
  entering.value = row.id
  try {
    const data = await enterTenant(row.id)
    if (!data.token) throw new Error('服务端未返回租户 token')
    saveImpersonationSnapshot({
      token: localStorage.getItem('erp_token'), user: currentUser(), tenantName: row.name,
    }, data.token)
    // PC-02：挂审计字段（原因/时间/操作者）——本地留痕，服务端 enterTenant 已记审计，前端补充可读记录。
    recordAudit({
      tenant: row.name,
      operator: currentUser()?.username || currentUser()?.name || '平台管理员',
      reason,
      at: new Date().toISOString(),
    })
    clearWorkspaceContext()
    ElMessage.success('已进入租户工作台，代客原因已记录审计')
    window.location.assign('/app')
  } finally { entering.value = '' }
}

onMounted(() => { if (roleKey() === 'PLATFORM_ADMIN' || roleKey()) load() })
</script>

<style scoped>
.mt12 { margin-top: 12px; }
.mt16 { margin-top: 16px; }
.card-title { font-weight: 600; }
.expired { color: var(--color-danger); font-weight: 600; }
.stat-item { display: inline-block; margin-right: 12px; font-size: 12px; color: var(--color-text-regular); }
.stat-item:last-child { margin-right: 0; }
</style>
