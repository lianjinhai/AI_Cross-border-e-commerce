<template>
  <el-card class="form-section" shadow="never">
    <template #header>
      <div class="form-section__header">
        <span class="form-section__title">{{ title }}</span>
        <span v-if="description" class="form-section__description">{{ description }}</span>
      </div>
    </template>
    <slot />
  </el-card>
</template>

<script setup>
/**
 * 表单分组（V9 第 1 批，设计系统 §2 新增）：设置子页/向导步的分组容器，
 * 承接 /app/settings/ai 四分组（AI 模型/经营参数/集成密钥/日志）等场景。
 */
defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
})
</script>

<style scoped>
.form-section__header {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}
.form-section__title {
  font-weight: var(--font-weight-medium);
}
.form-section__description {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>
