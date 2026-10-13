<template>
  <div class="page">
    <PageHeader title="平台总览" subtitle="租户 · 用户 · 授权到期" />

    <SectionState :state="state" :error="error" @retry="load" empty-hint="暂无平台数据">
      <el-row :gutter="16">
        <el-col v-for="c in cards" :key="c.label" :xs="12" :sm="8" :lg="4" class="mb16">
          <MetricCard :label="c.label" :value="c.value" />
        </el-col>
      </el-row>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 平台总览（UX-E，旧 /platform-admin tab=overview 拆分）：
 * 6 统计卡（租户/正常/停用/30 天到期/用户/订单），数据走 admin.fetchOverview。
 */
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../../components/PageHeader.vue'
import MetricCard from '../../components/MetricCard.vue'
import SectionState from '../../components/SectionState.vue'
import { fetchOverview } from '../../api/domains/admin'
import { statCardsFromOverview } from '../../composables/tenantAdmin'

const overview = ref(null)
const error = ref('')
const loading = ref(false)

const cards = computed(() => statCardsFromOverview(overview.value || {}))
const state = computed(() => {
  if (loading.value && !overview.value) return 'loading'
  if (error.value) return 'error'
  return overview.value ? 'ready' : 'loading'
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    overview.value = await fetchOverview()
  } catch (e) {
    error.value = e?.response?.data?.detail?.message || e?.message || '加载失败，请重试'
  } finally { loading.value = false }
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
</style>
