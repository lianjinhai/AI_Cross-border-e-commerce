<template>
  <el-card v-if="active" class="j0-bar" shadow="never">
    <div class="j0-bar__head">
      <span class="j0-bar__title">
        零基础经营准备 · 第 {{ index + 1 }}/{{ total }} 步 · {{ current.title }}
      </span>
      <el-tag size="small" type="info" effect="plain">{{ objectLabel }}</el-tag>
    </div>

    <div class="j0-bar__goal">
      <span class="j0-bar__goal-label">本步目标</span>
      <span>{{ current.goal }}</span>
    </div>

    <div class="j0-bar__nav">
      <el-button v-if="prev" size="small" @click="goPrev">← 返回：{{ prev.title }}</el-button>
      <el-button v-if="next" type="primary" size="small" @click="goNext">
        下一步：{{ next.title }} →
      </el-button>
      <el-button v-else type="success" size="small" @click="finish">
        完成准备，回到工作台
      </el-button>
    </div>
  </el-card>
</template>

<script setup>
/**
 * J0 旅程进度导航条（仅在 query.journey==='j0' 时渲染）。
 *
 * 职责：跨页贯通同一对象上下文（productId 透传）、展示当前步/目标、提供
 * 上一步 / 下一步（末步为"完成"）。纯推导走 shared/journeyJ0View。
 * 不替代页面自身的"唯一主动作"，只负责链路连续性，避免死端。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  J0_STEPS, stepFromPath, deriveNextStep, derivePrevStep,
  isJourneyActive, buildJourneyQuery,
} from '../shared/journeyJ0View'

const route = useRoute()
const router = useRouter()

const active = computed(() => isJourneyActive(route.query))
const current = computed(() => stepFromPath(route.path) || J0_STEPS[0])
const index = computed(() => J0_STEPS.findIndex((s) => s.key === current.value.key))
const total = J0_STEPS.length

const productId = computed(() => route.query.productId || '')
const objectLabel = computed(() =>
  productId.value ? `商品 #${productId.value}` : '对象未选定（选品转入商品池后自动带入）')

const prev = computed(() => derivePrevStep(current.value.key, { productId: productId.value }))
const next = computed(() => deriveNextStep(current.value.key, { productId: productId.value }))

function goNext() {
  if (!next.value) return
  router.push({ path: next.value.route, query: next.value.query })
}
function goPrev() {
  if (!prev.value) return
  router.push({ path: prev.value.route, query: prev.value.query })
}
function finish() {
  router.push({ path: '/app', query: buildJourneyQuery({ productId: productId.value }) })
}
</script>

<style scoped>
.j0-bar { margin-bottom: 16px; border: 1px solid var(--color-primary, #409eff); }
.j0-bar__head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.j0-bar__title { font-weight: 600; font-size: 14px; }
.j0-bar__goal { margin: 8px 0 12px; font-size: 13px; color: var(--color-text-regular); }
.j0-bar__goal-label {
  display: inline-block;
  margin-right: 8px;
  padding: 1px 8px;
  border-radius: 4px;
  background: var(--color-fill-light, #f0f2f5);
  color: var(--color-text-secondary);
  font-size: 12px;
}
.j0-bar__nav { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
