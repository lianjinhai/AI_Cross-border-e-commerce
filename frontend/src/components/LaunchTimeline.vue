<template>
  <el-card shadow="never" class="timeline">
    <div class="title">流程时间线</div>
    <div v-for="group in groups" :key="group.sequence" class="group">
      <div class="seq">阶段 {{ group.sequence + 1 }}<span v-if="group.items.length > 1" class="parallel-badge">并行 {{ group.items.length }}</span></div>
      <div class="nodes">
        <div v-for="step in group.items" :key="step.step_code" class="node"
          :class="[statusClass(step.step_status), { active: step.step_code === activeCode }]"
          @click="$emit('select', step)">
          <div class="node-head">
            <span class="node-name">{{ step.step_name || step.step_code }}</span>
            <el-tag size="small" :type="executionStatusMeta(step.step_status).tag">
              {{ executionStatusMeta(step.step_status).text }}
            </el-tag>
          </div>
          <div class="node-meta">依赖：{{ evidenceText(step.dependencies) }}</div>
          <div class="node-meta">执行者：{{ step.actor || '—' }}</div>
          <div v-if="step.blocking_reason?.message" class="node-block">阻断：{{ step.blocking_reason.message }}</div>
        </div>
      </div>
    </div>

    <div class="parallel">
      <div class="parallel-head">可并行处理（{{ ready.length }} 项）</div>
      <div class="parallel-items">
        <el-tag v-for="step in ready" :key="step.step_code" size="small" type="primary" effect="plain"
          class="parallel-tag" @click="$emit('select', step)">
          {{ step.step_name || step.step_code }}
        </el-tag>
        <span v-if="!ready.length" class="muted">当前没有可并行处理的节点</span>
      </div>
    </div>
  </el-card>
</template>

<script setup>
import { computed } from 'vue'
import { evidenceText, executionStatusMeta, groupStepsBySequence, parallelReadySteps } from '../composables/launchCenter'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  activeCode: { type: String, default: '' },
})
defineEmits(['select'])

const CLASS = { COMPLETED: 'done', READY: 'ready', RUNNING: 'running', FAILED: 'failed',
  BLOCKED: 'blocked', WAITING_USER: 'waiting', WAITING_APPROVAL: 'waiting', WAITING_EXTERNAL: 'waiting' }

const groups = computed(() => groupStepsBySequence(props.steps))
const ready = computed(() => parallelReadySteps(props.steps))
const statusClass = (status) => CLASS[status] || 'idle'
</script>

<style scoped>
.title { font-weight: 600; margin-bottom: 12px; }
.group { margin-bottom: 12px; }
.seq { color: #909399; font-size: 12px; margin-bottom: 6px; }
.parallel-badge { margin-left: 8px; color: #409eff; }
.nodes { display: flex; flex-direction: column; gap: 8px; }
.node { border: 1px solid #e4e7ed; border-left: 4px solid #dcdfe6; border-radius: 4px;
  padding: 8px 10px; cursor: pointer; transition: box-shadow .15s; }
.node:hover { box-shadow: 0 0 6px rgba(64, 158, 255, .3); }
.node.active { box-shadow: 0 0 6px rgba(64, 158, 255, .5); }
.node.done { border-left-color: #67c23a; }
.node.ready { border-left-color: #409eff; }
.node.running { border-left-color: #e6a23c; }
.node.failed { border-left-color: #f56c6c; }
.node.blocked, .node.waiting { border-left-color: #e6a23c; }
.node-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.node-name { font-weight: 500; }
.node-meta { color: #909399; font-size: 12px; margin-top: 2px; }
.node-block { color: #e6a23c; font-size: 12px; margin-top: 2px; }
.parallel { margin-top: 12px; border-top: 1px dashed #e4e7ed; padding-top: 12px; }
.parallel-head { color: #909399; font-size: 12px; margin-bottom: 6px; }
.parallel-items { display: flex; flex-wrap: wrap; gap: 8px; }
.parallel-tag { cursor: pointer; }
.muted { color: #a8abb2; font-size: 12px; }
</style>
