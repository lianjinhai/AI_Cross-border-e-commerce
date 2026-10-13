<template>
  <el-alert type="info" :closable="false" show-icon class="not-configured" title="该能力尚未接入">
    <span class="not-configured__detail">
      {{ capability }}<template v-if="reason"> · {{ reason }}</template>
    </span>
  </el-alert>
</template>

<script setup>
/**
 * 未接入占位（UX-03）：把缺失能力显式声明出来，绝不伪造数值或成功（对应 B03–B09 口径）。
 * 紧凑 info 提示，不抢占主操作区视觉焦点。
 */
defineProps({
  capability: { type: String, default: '' },
  reason: { type: String, default: '' },
})
</script>

<style scoped>
.not-configured { margin: 0; }
.not-configured__detail { font-size: 12px; }
</style>
