<template>
  <div class="page">
    <PageHeader title="备货与贴标任务" subtitle="工厂任务投影 · 只读队列">
      <template #actions>
        <el-tag type="warning" size="small">待接入 · 只读</el-tag>
      </template>
    </PageHeader>

    <!-- §F#5：task projection 未接入 → 只读队列 + 写按钮灰化，禁止假 API/假成功 -->
    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试" />
    <DataQualityBanner
      :tag="pendingCopy.tag"
      :detail="pendingCopy.detail"
    />

    <el-alert
      type="info" :closable="false" show-icon class="mb16"
      :title="labelingScopeNote()"
    />

    <SectionState :code="code" @retry="load" @action="onAction" :error="error">
      <!-- 待接入 → 无真实任务数据：空队列（EMPTY_NEW）；不渲染假任务行 -->
      <el-card shadow="never">
        <template #header><span class="card-title">任务队列</span></template>
        <el-table :data="tasks" size="small">
          <el-table-column label="类型" width="90">
            <template #default="{ row }">
              <el-tag :type="row.kind === 'stocking' ? 'primary' : 'warning'" size="small">
                {{ kindLabel(row.kind) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="requirement" label="要求数量 / 交期" min-width="220" show-overflow-tooltip />
          <el-table-column prop="material" label="材料 / 参考" min-width="180" show-overflow-tooltip />
          <el-table-column label="写操作" width="320">
            <template #default="{ row }">
              <!-- §F#5：三写按钮灰化 + tooltip"任务同步待接入，写操作暂缺"，不触发 API -->
              <el-tooltip content="任务同步待接入，写操作暂缺" :disabled="writePolicy.accept.executable">
                <el-button size="small" :disabled="!writePolicy.accept.executable" @click="noop">确认受理</el-button>
              </el-tooltip>
              <el-tooltip content="任务同步待接入，写操作暂缺" :disabled="writePolicy.submit_proof.executable">
                <el-button size="small" :disabled="!writePolicy.submit_proof.executable" @click="noop">提交证明</el-button>
              </el-tooltip>
              <el-tooltip content="任务同步待接入，写操作暂缺" :disabled="!writePolicy.cannot_complete.executable">
                <el-button size="small" :disabled="!writePolicy.cannot_complete.executable" @click="noop">无法完成</el-button>
              </el-tooltip>
            </template>
          </el-table-column>
          <template #empty>
            <EmptyState reason="NO_DATA" hint="任务同步待接入，暂无只读任务队列" />
          </template>
        </el-table>
      </el-card>
    </SectionState>
  </div>
</template>

<script setup>
/**
 * 备货/贴标任务（蓝图 R1 包 3 · FP-04，§B.3 / §F#5）：/factory/stocking。
 *
 * 后端 task projection 未接入 → 只读队列 + "待接入，无法自动完成"；写操作（确认受理/
 * 提交证明/无法完成）三按钮一律灰化，禁止假 API 调用、假成功态。判定逻辑集中
 * 在 shared/factoryTasks.js（writeActionPolicy / queueStateCode / pendingIntegrationCopy）。
 * 贴标授权边界：授权某贴标步骤 ≠ 批准整条 Launch（labelingScopeNote）。
 */
import { onMounted, ref } from 'vue'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import EmptyState from '../../components/EmptyState.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import {
  FACTORY_TASK_KINDS, queueStateCode, writeActionPolicy,
  pendingIntegrationCopy, labelingScopeNote,
} from '../../shared/factoryTasks'
import { envTag } from '../../shared/dataLabels'

const envBanner = envTag()

/** §F#5：Registry/projection 未核 → 写动作能力全部不可执行。 */
const PROJECTION_AVAILABLE = false

const tasks = ref([])
const code = ref('LOADING')
const error = ref('')

const pendingCopy = { tag: 'API_UNVERIFIED', ...pendingIntegrationCopy() }

/** 三写按钮可用性（当前恒 false → 全灰化）。 */
const writePolicy = {
  accept: writeActionPolicy('accept', { projectionAvailable: PROJECTION_AVAILABLE }),
  submit_proof: writeActionPolicy('submit_proof', { projectionAvailable: PROJECTION_AVAILABLE }),
  cannot_complete: writeActionPolicy('cannot_complete', { projectionAvailable: PROJECTION_AVAILABLE }),
}

function kindLabel(kind) {
  return FACTORY_TASK_KINDS[kind]?.label || kind
}

function noop() {
  /* 写操作未接入：点击无副作用，不触发 API（灰化 + tooltip 已说明原因）。 */
}

/** 待接入 → 无真实任务源：落空态而非报错（禁编造任务）。 */
function load() {
  code.value = 'LOADING'
  error.value = ''
  tasks.value = []
  code.value = queueStateCode(false, false, tasks.value.length)
}

function onAction(c) {
  if (c === 'EMPTY_NEW') return
  if (c === 'ERROR') load()
}

onMounted(load)
</script>

<style scoped>
.mb16 { margin-bottom: 16px; }
.card-title { font-weight: 600; }
</style>
