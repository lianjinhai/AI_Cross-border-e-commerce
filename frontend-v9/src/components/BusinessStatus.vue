<template>
  <el-tag :type="tone" :size="size" effect="light">
    {{ label }}
    <span v-if="showRaw" class="business-status__raw">{{ raw }}</span>
  </el-tag>
  <el-popover v-if="note" trigger="click" :width="320" placement="top">
    <template #reference>
      <el-button link type="info" size="small" @click="$emit('expand')">详情</el-button>
    </template>
    <div class="business-status__note">{{ note }}</div>
    <slot name="note" />
  </el-popover>
</template>

<script setup>
/**
 * 业务状态标签（蓝图 §6.4，包 1 P0 全新组件）。
 *
 * 规则：外部等待=WAITING_EXTERNAL 中性色（禁红色误报）；PRO 模式才显 raw；未知码回落 info。
 * 纯函数源：shared/businessStatus.js（statusTone / shouldShowRaw / mapBusinessStatus）。
 */
import { computed } from 'vue'
import { statusTone, shouldShowRaw, mapBusinessStatus } from '../shared/businessStatus'

const props = defineProps({
  /** 标准态码（String）。 */
  standard: { type: String, default: '' },
  /** 原始状态（PRO 模式才显示）。 */
  raw: { type: String, default: '' },
  /** 数据标签码（见 §6.5）。 */
  evidenceLevel: { type: String, default: '' },
  /** 更新时间。 */
  updatedAt: { type: String, default: '' },
  /** 点击展开说明。 */
  note: { type: String, default: '' },
  /** 当前模式：'PRO'|'GUIDED'|''。 */
  mode: { type: String, default: 'GUIDED' },
  size: { type: String, default: 'small' },
})

const emit = defineEmits(['expand'])

const tone = computed(() => {
  const code = props.standard || mapBusinessStatus(props.raw)
  return statusTone(code)
})

const showRaw = computed(() => shouldShowRaw(props.mode, props.raw))

const label = computed(() => {
  const code = props.standard || mapBusinessStatus(props.raw)
  const LABEL_MAP = {
    SUCCESS: '成功', RUNNING: '运行中', FAILED: '失败', PARTIAL: '部分成功',
    BLOCKED: '被阻断', SKIPPED: '已跳过', QUEUED: '排队中',
    WAITING_EXTERNAL: '等待外部', WAITING_USER: '待审批', UNCERTAIN: '待核查',
    PUBLISHED: '已发布', DRAFT: '草稿', PENDING: '待处理', UNKNOWN: '未知',
  }
  return LABEL_MAP[code] || code || '未知'
})
</script>

<style scoped>
.business-status__raw {
  margin-left: 4px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}
.business-status__note {
  white-space: pre-wrap;
  font-size: var(--font-size-sm);
}
</style>
