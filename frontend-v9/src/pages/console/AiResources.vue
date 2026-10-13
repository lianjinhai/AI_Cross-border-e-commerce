<template>
  <div class="page">
    <PageHeader title="AI 资源与成本" subtitle="模型路由 / Token / 限流 / 配额（仅真实数据可用时显示）" />

    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />
    <DataQualityBanner :tag="pendingCopy.tag" :detail="pendingCopy.detail" />

    <!-- §F#8：ai 配额读端点未核 → 各区块无真实数据 → 不渲染图表，显"未接入" -->
    <el-row :gutter="16">
      <el-col v-for="sec in sections" :key="sec.code" :xs="12" :sm="8" :lg="4" class="mb16">
        <el-card shadow="never">
          <div class="section-title">{{ sec.label }}</div>
          <SectionState :code="sec.state.code" :action-text="sec.state.title" />
        </el-card>
      </el-col>
    </el-row>

    <el-alert
      type="info" :closable="false" show-icon
      title="AI 资源与成本数据未接入"
      description="Token / 成本、限流、失败与配额仅在真实数据可用时渲染；当前不编造数字、不渲染假图表。"
    />
  </div>
</template>

<script setup>
/**
 * AI 资源与成本（蓝图 R1 包 3 · PC-05，§B.3 / §5.19 / §F#8）：/console/ai-resources。
 *
 * 蓝图 §5.19：记录模型路由、Token/成本、限流、失败、策略与配额，但**只在真实数据
 * 可用时显示**。ai 配额读端点未核（§F#8）→ 无真实数据不渲染图表，缺项显"未接入"。
 * 区块目录与缺项判定集中在 shared/consoleAiResources.js（hasAiQuotaSource 当前恒 false）。
 * 红线：不编造 Token 成本。
 */
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import {
  AI_RESOURCE_SECTIONS, hasAiQuotaSource, aiSectionState, aiResourcesPendingCopy,
} from '../../shared/consoleAiResources'
import { envTag } from '../../shared/dataLabels'

const envBanner = envTag()

/** ai 配额读端点未核 → 传 null，hasAiQuotaSource 恒 false。 */
const quotaSource = null
const available = hasAiQuotaSource(quotaSource)

const sections = AI_RESOURCE_SECTIONS.map((sec) => ({
  ...sec,
  state: aiSectionState(available && sec.code === 'quota'),
}))
const pendingCopy = { tag: 'UNKNOWN', ...aiResourcesPendingCopy() }
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.section-title { font-weight: 600; margin-bottom: 8px; }
</style>
