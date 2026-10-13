<template>
  <div class="task-card" :class="{ clickable: !!deepLink }" @click="go">
    <el-tag size="small" :type="severityTag.type">{{ severityTag.label }}</el-tag>
    <span class="task-card__title">{{ todo.title }}</span>
    <el-badge v-if="todo.count" :value="todo.count" type="primary" />
    <el-button v-if="deepLink" link type="primary" size="small">处理</el-button>
  </div>
</template>

<script setup>
/**
 * 待办卡（V9 第 2 批，设计系统 §2）：工作台/任务中心统一待办条目。
 * 数据来自 /workbench/todo items（type: launch|action|alert|review）；
 * 深链由后端 route.path 提供（待办直达，J2 断链归零）。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { resolveStatusTag } from '../shared/statusDict'

const props = defineProps({
  todo: { type: Object, required: true }, // { title, count, severity, route?: {path} }
})

const router = useRouter()

const severityTag = computed(() => {
  const { type } = resolveStatusTag(props.todo.severity === 'high' ? 'high'
    : props.todo.severity === 'mid' ? 'mid' : 'low')
  const label = { high: '高', mid: '中', low: '低' }[props.todo.severity] || '低'
  return { type, label }
})

const deepLink = computed(() => props.todo.route?.path || '')

function go() {
  if (deepLink.value) router.push(deepLink.value)
}
</script>

<style scoped>
.task-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--color-border);
}
.task-card.clickable {
  cursor: pointer;
}
.task-card__title {
  flex: 1;
}
</style>
