<template>
  <el-dialog
    :model-value="modelValue"
    :title="action"
    width="480px"
    :close-on-click-modal="false"
    @update:model-value="(v) => $emit('update:modelValue', v)"
    @close="onReset"
  >
    <div v-if="state === ASYNC_STATES.SUBMITTING" class="async-action__loading">
      <el-skeleton :rows="3" animated />
    </div>

    <div v-else-if="state === ASYNC_STATES.SUCCESS" class="async-action__success">
      <el-alert type="success" :title="doneMessage || '操作成功'" :closable="false" />
    </div>

    <div v-else-if="state === ASYNC_STATES.FAILED" class="async-action__failed">
      <el-alert type="error" :title="failReason || '操作失败'" :closable="false">
        <div v-if="context" class="async-action__context">
          <slot name="context" />
        </div>
      </el-alert>
      <el-button size="small" type="primary" @click="onRetry">重新提交</el-button>
    </div>

    <div v-else-if="state === ASYNC_STATES.CONFLICT" class="async-action__conflict">
      <el-alert type="warning" title="状态已变更，请刷新后重试" :closable="false">
        <div class="async-action__hint">已保留你的输入，刷新页面即可看到最新状态。</div>
      </el-alert>
      <el-button size="small" type="primary" @click="onRequery">刷新状态</el-button>
    </div>

    <div v-else-if="state === ASYNC_STATES.UNCERTAIN" class="async-action__uncertain">
      <el-alert type="info" title="结果待核查" :closable="false">
        <div class="async-action__hint">操作是否成功尚不确定，请重新查询状态（不做盲重试）。</div>
      </el-alert>
      <el-button size="small" type="primary" @click="onRequery">重新查询状态</el-button>
    </div>

    <div v-else class="async-action__idle">
      <slot name="context">
        <div v-if="context" class="async-action__context-desc">{{ context }}</div>
      </slot>
    </div>

    <template #footer>
      <el-button @click="onReset">关闭</el-button>
      <el-button v-if="state === ASYNC_STATES.IDLE" type="primary" :disabled="submitting" @click="onSubmit">
        确认执行
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
/**
 * 异步操作对话框（蓝图 §6.4，包 1 P0 全新组件）。
 *
 * 状态机：提交中→成功/失败/409(状态已变→刷新,不丢输入)/超时(UNCERTAIN:"结果待核查")。
 * 超时后只允许"重新查询状态"，禁盲重试副作用。
 * 纯函数源：shared/asyncAction.js（classifyResult / nextState / buildIdempotencyKey）。
 */
import { ref } from 'vue'
import {
  ASYNC_STATES, ASYNC_EVENTS,
  classifyResult, nextState, buildIdempotencyKey,
} from '../shared/asyncAction'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 动作名称（标题展示）。 */
  action: { type: String, default: '' },
  /** 上下文描述（影响对象/Store/金额币种/前置条件/审批人展示）。 */
  context: { type: [String, Object], default: '' },
  /** 幂等键。 */
  idempotencyKey: { type: String, default: '' },
  /** CAS revision。 */
  revision: { type: String, default: '' },
  /** 成功消息。 */
  doneMessage: { type: String, default: '' },
  /** 失败原因。 */
  failReason: { type: String, default: '' },
})

const emit = defineEmits([
  'update:modelValue', 'submit', 'done', 'uncertain', 'retry', 'requery', 'reset',
])

const state = ref(ASYNC_STATES.IDLE)
const submitting = ref(false)

function onSubmit() {
  const key = props.idempotencyKey
    || buildIdempotencyKey({
      objectType: props.context?.type || '',
      objectId: props.context?.id || '',
      action: props.action,
    })
  emit('submit', {
    key,
    revision: props.revision,
    action: props.action,
    context: typeof props.context === 'object' ? props.context : {},
  })
  state.value = nextState(state.value, ASYNC_EVENTS.SUBMIT)
  submitting.value = true
}

function onSuccess(response) {
  submitting.value = false
  const result = classifyResult(response)
  state.value = nextState(state.value, ASYNC_EVENTS.RESOLVED, { result })
  if (result === ASYNC_STATES.SUCCESS) emit('done', response?.data)
  else if (result === ASYNC_STATES.UNCERTAIN) emit('uncertain', response)
}

function onRetry() {
  state.value = nextState(state.value, ASYNC_EVENTS.RESET)
  emit('retry')
}

function onRequery() {
  state.value = nextState(state.value, ASYNC_EVENTS.REQUERY)
  emit('requery')
}

function onReset() {
  state.value = ASYNC_STATES.IDLE
  submitting.value = false
  emit('reset')
  emit('update:modelValue', false)
}
</script>

<style scoped>
.async-action__hint {
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
.async-action__context-desc {
  white-space: pre-wrap;
  color: var(--color-text-regular);
  font-size: var(--font-size-sm);
}
</style>
