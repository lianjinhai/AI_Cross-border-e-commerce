<template>
  <div class="page">
    <PageHeader title="Adapter 认证中心" subtitle="渠道能力拆分 · 协议实现与真实联调状态">
      <template #actions>
        <el-tag type="warning" size="small">Registry 未核</el-tag>
      </template>
    </PageHeader>

    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />
    <DataQualityBanner :tag="pendingCopy.tag" :detail="pendingCopy.detail" />

    <el-card v-for="p in platforms" :key="p.code" class="mb16" shadow="never">
      <template #header>
        <div class="between">
          <span class="card-title">
            {{ p.label }}
            <el-tag v-if="p.restricted" type="danger" size="small" effect="plain" class="restricted">受限渠道</el-tag>
          </span>
          <span class="markets">{{ p.markets.join(' · ') }}</span>
        </div>
      </template>
      <el-table :data="p.subcaps" size="small">
        <el-table-column prop="label" label="子能力" width="140" />
        <el-table-column label="验证等级" width="140">
          <template #default="{ row }">
            <el-tag :type="row.level.tone" size="small" effect="plain">{{ row.level.label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="证据时间" min-width="160">
          <template #default="{ row }">{{ row.level.evidenceAt }}</template>
        </el-table-column>
        <el-table-column label="账号范围" width="140">
          <template #default="{ row }">{{ row.level.accountScope }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
/**
 * Adapter 认证中心（蓝图 R1 包 3 · PC-03，§B.3 / §5.19 / §F#8）：/console/adapters。
 *
 * 能力拆到授权/商品发布/在售核验/订单/退款子能力，每项显示协议实现与真实联调状态、
 * 证据时间、账号范围。Registry 读端点未核 → 各子能力验证等级一律显"尚未验证"
 * （不用绿色/红色误报），证据时间必显。判定与平台目录集中在 shared/consoleAdapters.js。
 * 红线（§F#8）：不冒充真实认证；Registry 接入后切真实数据。
 */
import PageHeader from '../../components/PageHeader.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import {
  adapterPlatformCards, adapterPendingCopy,
} from '../../shared/consoleAdapters'
import { envTag } from '../../shared/dataLabels'

const envBanner = envTag()
const platforms = adapterPlatformCards()
const pendingCopy = { tag: 'API_UNVERIFIED', ...adapterPendingCopy() }
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.card-title { font-weight: 600; }
.between { display: flex; justify-content: space-between; align-items: center; }
.markets { color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.restricted { margin-left: 8px; }
</style>
