<template>
  <el-link type="primary" :underline="false" @click="onNavigate">
    <slot name="label">{{ defaultLabel }}</slot>
  </el-link>
</template>

<script setup>
/**
 * 实体深链（蓝图 §6.3，包 1 P0 全新组件）。
 *
 * 生成站内白名单深链；return_to 限站内白名单；无权限对象点击→/403。
 * 纯函数源：shared/entityLink.js（buildEntityLink / isWhitelistedPath）。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { buildEntityLink, isWhitelistedPath } from '../shared/entityLink'

const props = defineProps({
  /** 对象类型（product/listing/order/launch...）。 */
  objectType: { type: String, default: '' },
  /** 对象 ID。 */
  objectId: { type: [String, Number], default: '' },
  /** 店铺 ID（可选）。 */
  storeId: { type: String, default: '' },
  /** 工作流运行 ID（可选）。 */
  workflowRunId: { type: String, default: '' },
  /** 步骤码（可选）。 */
  stepCode: { type: String, default: '' },
  /** 返回路径（站内白名单）。 */
  returnTo: { type: String, default: '' },
  /** 返回时恢复筛选（JSON 字符串）。 */
  returnFilters: { type: String, default: '' },
  /** 无权限时目标。 */
  forbiddenPath: { type: String, default: '/403' },
  /** 当前是否具备访问权限。 */
  allowed: { type: Boolean, default: true },
})

const emit = defineEmits(['navigate'])

const router = useRouter()

const defaultLabel = computed(() => {
  if (props.objectType && props.objectId) {
    return `${props.objectType}#${props.objectId}`
  }
  return '查看详情'
})

const link = computed(() => buildEntityLink({
  objectType: props.objectType,
  objectId: String(props.objectId),
  storeId: props.storeId,
  workflowRunId: props.workflowRunId,
  stepCode: props.stepCode,
  returnTo: props.returnTo,
  returnFilters: props.returnFilters,
}))

function onNavigate() {
  if (!props.allowed) {
    emit('navigate', props.forbiddenPath)
    router.push(props.forbiddenPath)
    return
  }
  const target = link.value
  if (!isWhitelistedPath(target)) {
    emit('navigate', '/404')
    router.push('/404')
    return
  }
  emit('navigate', target)
  router.push(target)
}
</script>
