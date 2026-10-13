<template>
  <el-alert type="warning" :closable="false" show-icon class="waiting-external" :title="title">
    <span v-if="detail" class="waiting-external__detail">{{ detail }}</span>
  </el-alert>
</template>

<script setup>
import { computed } from 'vue'

/**
 * 等待外部（平台）核验态（UX-03）。
 *
 * 只表达「等待核验」，**绝不含「已上线 / 已完成」字样**——避免把待核验流程谎报为已完成。
 */
const props = defineProps({
  owner: { type: String, default: '平台' },
  since: { type: String, default: '' },
  hint: { type: String, default: '' },
})

const title = computed(() => `等待${props.owner}核验`)
const detail = computed(() => {
  const parts = []
  if (props.since) parts.push(`自 ${props.since}`)
  if (props.hint) parts.push(props.hint)
  return parts.join(' · ')
})
</script>

<style scoped>
.waiting-external { margin: 0; }
.waiting-external__detail { font-size: 12px; }
</style>
