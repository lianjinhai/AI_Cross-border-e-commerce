<template>
  <div class="page">
    <PageHeader title="工厂履约与历史" subtitle="本厂订单任务与历史">
      <template #actions>
        <el-tag type="warning" size="small">待接入</el-tag>
      </template>
    </PageHeader>

    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />

    <!-- §F#3：/factory/orders、/factory/settlements 未核 → 整页占位"待接入"，禁复用卖家 Launch 详情 JSON -->
    <SectionState code="NOT_CONFIGURED" :action-text="'暂无数据'" :on-action="onAction">
      <el-card shadow="never">
        <template #header><span class="card-title">本厂履约历史</span></template>
        <el-empty description="履约历史数据待接入">
          <p class="pending-detail">{{ pendingCopy.detail }}</p>
          <el-alert
            type="info" :closable="false" show-icon class="muted-note"
            title="本页仅承接工厂身份绑定的履约数据；不复用卖家 Launch 流程详情。"
          />
        </el-empty>
      </el-card>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 工厂履约与历史（蓝图 R1 包 3 · FP-05，§B.3 / §F#3）：/factory/fulfillment。
 *
 * /factory/orders、/factory/settlements 端点未核 → 整页占位"暂无数据/履约历史数据待接入"。
 * 安全约束（蓝图 §5.18）：禁止复用卖家 Launch 详情 JSON；只收工厂身份绑定 DTO。
 * 主态经 SectionState NOT_CONFIGURED（"未连接/未配置"语境，字典渲染不页面自写）。
 */
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { envTag } from '../../shared/dataLabels'

const envBanner = envTag()

const pendingCopy = {
  detail: '本厂订单任务与履约历史端点（/factory/orders、/factory/settlements）尚未接入，接入后这里将展示历史履约与反馈记录。',
}

function onAction() {
  /* NOT_CONFIGURED 主行动：数据源待接入，无可执行的设置入口，仅提示。 */
}
</script>

<style scoped>
.pending-detail { margin: 0 0 8px; color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.muted-note { max-width: 420px; }
.card-title { font-weight: 600; }
</style>
