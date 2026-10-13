<template>
  <div class="page">
    <PageHeader title="系统维护" subtitle="演示数据 · 平台规则包 · 系统信息" />

    <!-- 清空演示数据（强确认） -->
    <el-card class="mb16" shadow="never">
      <template #header><span class="card-title">清空演示数据</span></template>
      <el-alert type="warning" show-icon :closable="false"
        title="将删除所有演示商品/订单/会话/广告数据，操作不可恢复，请谨慎执行" />
      <div class="mt12">
        <el-button type="danger" :loading="purging" @click="doPurge">清空演示数据</el-button>
      </div>
      <el-alert v-if="purgeText" type="success" show-icon :closable="false" class="mt12"
        :title="`演示数据已清空：${purgeText}`" />
    </el-card>

    <!-- 平台规则包 -->
    <el-card class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">平台规则包更新</span>
          <el-button size="small" type="primary" plain :loading="checkingRules" @click="doCheckUpdates">检查更新</el-button>
        </div>
      </template>
      <el-alert type="info" :closable="false" show-icon class="mb12"
        title="规则为官方文档整理快照，可配置 ERP_RULES_URL 远程规则源自动同步"
        description="发布前系统按当前规则强制校验，违规拒绝发布以保护店铺。" />
      <el-table :data="rules" v-loading="rulesLoading" size="small">
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
        <template #empty><EmptyState reason="NO_DATA" hint="暂无平台规则数据" /></template>
      </el-table>
    </el-card>

    <!-- 系统信息 -->
    <el-card shadow="never">
      <template #header><span class="card-title">系统信息</span></template>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="租户总数">{{ fmt(overview?.tenants) }}</el-descriptions-item>
        <el-descriptions-item label="用户总数">{{ fmt(overview?.users) }}</el-descriptions-item>
        <el-descriptions-item label="订单总数">{{ fmt(overview?.orders_total) }}</el-descriptions-item>
      </el-descriptions>
      <div class="muted-line">数据库：SQLite（ERP_DB_URL 可切 MySQL） / 部署：Docker compose 支持</div>
    </el-card>
  </div>
</template>

<script setup>
/**
 * 系统维护（UX-E，旧 /platform-admin tab=maintenance 拆分）：
 * 清空演示数据（输入「清空」强确认）+ 平台规则包检查更新 + 系统信息。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import EmptyState from '../../components/EmptyState.vue'
import { fetchOverview } from '../../api/domains/admin'
import { checkPlatformRuleUpdates, fetchPlatformRules, purgeDemoData } from '../../api/domains/shops'
import { fmt, platformLabel, purgeResultText } from '../../composables/tenantAdmin'

const overview = ref(null)
const rules = ref([])
const rulesLoading = ref(false)
const checkingRules = ref(false)
const purging = ref(false)
const purgeText = ref('')

async function loadRules() {
  rulesLoading.value = true
  try { rules.value = (await fetchPlatformRules()).items || [] }
  finally { rulesLoading.value = false }
}

async function loadOverview() {
  try { overview.value = await fetchOverview() } catch { overview.value = null }
}

async function doPurge() {
  try {
    await ElMessageBox.prompt(
      '此操作将删除所有演示商品/订单/会话/广告数据，且不可恢复！请输入「清空」确认执行。',
      '强警告：清空演示数据',
      {
        type: 'warning', confirmButtonText: '确认清空', cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger', inputPlaceholder: '请输入：清空',
        inputPattern: /^清空$/, inputErrorMessage: '请输入「清空」以确认执行',
      },
    )
  } catch { return }
  purging.value = true
  try {
    const data = await purgeDemoData()
    purgeText.value = purgeResultText(data?.deleted ?? null)
    ElMessage.success(purgeText.value ? `演示数据已清空：${purgeText.value}` : '演示数据已清空')
    loadOverview()
  } finally { purging.value = false }
}

async function doCheckUpdates() {
  const targets = rules.value.map((r) => r.platform)
  if (!targets.length) { ElMessage.warning('暂无平台规则可检查'); return }
  checkingRules.value = true
  const done = []
  try {
    for (const p of targets) {
      try {
        const data = await checkPlatformRuleUpdates(p)
        done.push(`${platformLabel(p)}：${data?.hint || (data?.updated ? '发现更新，已同步' : '已是最新')}`)
      } catch { /* 失败已由全局拦截器提示 */ }
    }
  } finally { checkingRules.value = false }
  if (done.length) ElMessage({ type: 'success', message: done.join('；'), duration: 5000, showClose: true })
  loadRules()
}

onMounted(() => { loadRules(); loadOverview() })
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.mt12 { margin-top: 12px; }
.mb12 { margin-bottom: 12px; }
.card-title { font-weight: 600; }
.between { display: flex; justify-content: space-between; align-items: center; }
.muted-line { color: var(--color-text-secondary); font-size: 12px; margin-top: 12px; }
</style>
