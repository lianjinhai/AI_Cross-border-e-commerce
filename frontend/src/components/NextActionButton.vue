<template>
  <span class="next-action">
    <el-button
      size="small"
      :type="executable ? 'primary' : 'info'"
      :disabled="!executable"
      :loading="loading"
      @click="$emit('run')"
    >{{ action }}</el-button>
    <span v-if="!executable && reason" class="next-action__reason">{{ reason }}</span>
  </span>
</template>

<script setup>
/**
 * 下一动作按钮（UX-03）。
 *
 * 铁律：不可执行的动作一律 `disabled`，并在旁侧展示原因——绝不允许「能点但点了吃 409」。
 * 只负责呈现与转发 `run` 事件，权限判定由调用方（canManage / available_actions）决定。
 */
defineProps({
  action: { type: String, default: '' },
  executable: { type: Boolean, default: false },
  reason: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})
defineEmits(['run'])
</script>

<style scoped>
.next-action { display: inline-flex; align-items: center; gap: 8px; }
.next-action__reason { color: #e6a23c; font-size: 12px; }
</style>
