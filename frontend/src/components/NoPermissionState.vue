<template>
  <el-empty description="无访问权限">
    <p class="no-permission__required">需要权限：{{ required }}</p>
    <p v-if="scope" class="no-permission__scope">范围：{{ scope }}</p>
  </el-empty>
</template>

<script setup>
/**
 * 无权限态（UX-02）：让「看不到功能」变成「看得见原因」。
 * `required` 为所需权限 key；`scope`（可选）标明生效范围。
 */
defineProps({
  required: { type: String, default: '' },
  scope: { type: String, default: '' },
})
</script>

<style scoped>
.no-permission__required,
.no-permission__scope {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>
