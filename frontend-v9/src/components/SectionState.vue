<template>
  <div class="section-state">
    <!-- 11 态码（code 或旧 state 映射而来；非空且非内容态时走 pageStates 字典渲染） -->
    <template v-if="showStateView">
      <LoadingState v-if="renderCode === 'LOADING'" :type="loadingType" />

      <EmptyState
        v-else-if="renderCode === 'EMPTY_NEW' || renderCode === 'EMPTY_FILTER'"
        :reason="renderCode === 'EMPTY_NEW' ? 'NO_DATA' : 'NO_MATCH'"
        :hint="copy.title || emptyHint"
      />

      <EmptyState v-else-if="renderCode === 'NOT_CONFIGURED'" reason="NOT_CONFIGURED" :hint="copy.title" />

      <EmptyState v-else-if="renderCode === 'NO_PERMISSION'" reason="NO_PERMISSION" :hint="copy.title" />

      <EmptyState
        v-else-if="renderCode === 'WAITING_EXTERNAL'"
        reason="WAITING_EXTERNAL"
        :hint="copy.title"
      />

      <EmptyState
        v-else-if="renderCode === 'UNCERTAIN'"
        reason="NO_DATA"
        :hint="copy.title"
      />

      <div v-else-if="renderCode === 'PARTIAL_DATA' || renderCode === 'WAITING_USER' || renderCode === 'BLOCKED'" class="section-state__alert">
        <el-alert
          :type="alertType"
          :title="copy.title"
          :description="copy.actionText"
          :closable="false"
          show-icon
        />
      </div>

      <ErrorState
        v-else-if="renderCode === 'ERROR'"
        :message="error || copy.title"
        :trace-id="traceId"
        @retry="$emit('retry')"
      />
    </template>

    <!-- 内容渲染（ready-state 或旧 state=ready：默认插槽 / 具名插槽） -->
    <template v-else>
      <slot v-if="legacyState === 'empty'" name="empty">
        <EmptyState :reason="emptyReason || 'NO_DATA'" :hint="emptyHint" />
      </slot>
      <EmptyState v-else-if="legacyState === 'nopermission'" reason="NO_PERMISSION" />
      <slot v-else-if="legacyState === 'error'" name="error">
        <ErrorState :message="error" :trace-id="traceId" @retry="$emit('retry')" />
      </slot>
      <slot v-else />
    </template>

    <!-- 主行动按钮（11 态且有 actionText 时显示） -->
    <div v-if="showStateView && copy.actionText" class="section-state__action">
      <el-button size="small" type="primary" @click="onAction">
        {{ copy.actionText }}
      </el-button>
    </div>
  </div>
</template>

<script setup>
/**
 * 区块状态包装（UX-C 内部件 → 蓝图 R1 11 态扩展）。
 *
 * 两种用法：
 * 1. 11 态（code prop 透传，非空）：经 shared/pageStates.js 字典渲染文案，
 *    杜绝页面自写空态；外部等待（WAITING_EXTERNAL/UNCERTAIN）中性色，不用红色误报。
 *    内容态传 code='ready'（特殊保留值：渲染默认插槽）。
 * 2. 旧 5 态（state prop）：保持完全兼容，行为不变。
 *
 * `code` 传入时优先于 `state`。
 */
import { computed } from 'vue'
import EmptyState from './EmptyState.vue'
import ErrorState from './ErrorState.vue'
import LoadingState from './LoadingState.vue'
import { stateCopy, stateToCode } from '../shared/pageStates'

/** 内容态保留值（11 态下表示"有数据，渲染默认插槽"）。 */
const READY_CODE = 'ready'

const props = defineProps({
  /** 旧 5 态：loading/empty/error/nopermission/ready/partial。 */
  state: { type: String, default: 'ready' },
  /** 11 态码（优先于 state）；'ready'=内容态（渲染默认插槽）。 */
  code: { type: String, default: '' },
  /** 主行动文案（覆盖字典默认）。 */
  actionText: { type: String, default: '' },
  /** 主行动回调（传函数则直接调用，否则 emit('action', code)）。 */
  onAction: { type: Function, default: null },
  error: { type: String, default: '' },
  traceId: { type: String, default: '' },
  emptyReason: { type: String, default: '' },
  emptyHint: { type: String, default: '' },
  loadingType: { type: String, default: 'table' },
})

const emit = defineEmits(['retry', 'action'])

const legacyState = computed(() => props.code ? 'ready' : props.state)

/** 生效态码：code 优先；code='ready' 为内容态；旧 state 经 stateToCode 映射。 */
const renderCode = computed(() => {
  if (props.code) return props.code
  const mapped = stateToCode(props.state)
  return mapped
})

/** 是否走 11 态状态视图（非内容态）。 */
const showStateView = computed(() => Boolean(renderCode.value) && renderCode.value !== READY_CODE)

/** 当前态文案（pageStates 字典 + actionText 覆盖）。 */
const copy = computed(() => {
  if (!showStateView.value) return { title: '', actionText: '', tone: 'info' }
  return stateCopy(renderCode.value, props.actionText ? { actionText: props.actionText } : {})
})

/** el-alert type 映射（tone → alert type）。 */
const alertType = computed(() => {
  const tone = copy.value.tone
  if (tone === 'danger') return 'error'
  if (tone === 'warning') return 'warning'
  return 'info'
})

function onAction() {
  if (typeof props.onAction === 'function') {
    props.onAction(renderCode.value)
    return
  }
  emit('action', renderCode.value)
}
</script>

<style scoped>
.section-state__alert {
  margin-bottom: 8px;
}
.section-state__action {
  margin-top: 8px;
}
</style>
