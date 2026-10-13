<template>
  <div class="page">
    <PageHeader title="合规工作台" subtitle="发现与商品 · 合规审批与复核">
      <template #actions>
        <el-tag v-if="!isOwner" size="small" type="warning">当前角色无审批权限</el-tag>
        <el-tag v-else size="small" type="info">待接入</el-tag>
      </template>
    </PageHeader>

    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />

    <!-- 非 OWNER：合规工作台需审批权限（requiresOwner），只读提示 -->
    <SectionState :code="code" @retry="fetchAll" @action="onAction" :error="error">
      <!-- 审批队列：compliance 域 API_GAP → 只读骨架 + 明示"待接入"，禁假按钮/假数据 -->
      <el-card class="mb16" shadow="never">
        <template #header>
          <div class="between"><span class="card-title">审批队列</span><span class="scope">API_GAP · 后端未接入</span></div>
        </template>
        <el-alert
          v-if="code === 'NOT_CONFIGURED' || code === 'ready'"
          type="info" :closable="false" show-icon
          title="合规审批端点待接入"
          description="审批写操作（approve/reject）依赖后端合规端点，当前不可用。本页为只读占位，不显示虚假审批结果。"
        />
      </el-card>

      <!-- 知识复核区：knowledge 域已接（candidates 候选），只读展示，标注"待接入"写端点 -->
      <el-card shadow="never">
        <template #header>
          <div class="between"><span class="card-title">知识候选复核</span><span class="scope">来源：knowledge/candidates（只读）</span></div>
        </template>
        <SectionState :code="candidateCode" @retry="loadCandidates">
          <el-table v-if="candidateCode === 'ready'" :data="candidates" size="small">
            <el-table-column prop="question" label="问题" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }"><StatusBadge :status="row.status" /></template>
            </el-table-column>
            <el-table-column label="数据来源" width="130">
              <template #default="{ row }">
                <el-tag size="small" type="info" effect="plain">{{ row.answer_source || '未标注' }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </SectionState>
      </el-card>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 合规工作台（蓝图 R1 CO-02，P0，替换 StubPage）：/app/compliance/approvals。
 *
 * requiresOwner（路由守卫 + 菜单过滤）：非 OWNER 隐藏/403。
 * API_GAP：compliance 域审批写端点未核（§7）→ 只读骨架 + 明示"待接入"，禁止假按钮/假成功态。
 * 已接的 knowledge/candidates 区只读展示候选复核（写端点标注待接入）。每页 11 态全区块
 * 经 SectionState 渲染。
 */
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchCandidates } from '../../api/domains/knowledge'
import { envTag } from '../../shared/dataLabels'
import { hasPermission } from '../../shared/workspace'

const envBanner = envTag()

const isOwner = computed(() => hasPermission('compliance:approve') ?? false)

const code = ref('LOADING')
const error = ref('')
const candidates = ref([])
const candidateLoading = ref(false)

const candidateCode = computed(() => {
  if (candidateLoading.value) return 'LOADING'
  if (!candidates.value.length) return 'EMPTY_NEW'
  return 'ready'
})

function onAction() { /* NOT_CONFIGURED：进入设置（本无设置项） */ }

async function loadCandidates() {
  candidateLoading.value = true
  try {
    const data = await fetchCandidates({ status: 'pending' })
    candidates.value = (data?.items || []).slice(0, 20)
  } catch {
    candidates.value = [] // 次级区独立降级，不阻断主流程
  } finally {
    candidateLoading.value = false
  }
}

async function fetchAll() {
  code.value = 'LOADING'
  error.value = ''
  try {
    // 合规审批域 API_GAP：无真实端点 → NOT_CONFIGURED（不造假数据）
    await loadCandidates()
    code.value = 'NOT_CONFIGURED'
  } catch (e) {
    const detail = e?.response?.data?.detail
    error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
    code.value = 'ERROR'
  }
}

onMounted(fetchAll)
</script>

<style scoped>
.between { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.card-title { font-size: 15px; font-weight: 600; }
.scope { color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.mb16 { margin-bottom: 16px; }
</style>
