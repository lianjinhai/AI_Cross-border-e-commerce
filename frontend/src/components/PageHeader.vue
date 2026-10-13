<template>
  <div class="page-header">
    <div class="page-header__text">
      <div class="page-header__breadcrumb">
        <slot name="breadcrumb" />
      </div>
      <div class="page-header__title">{{ title }}</div>
    </div>
    <div class="page-header__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
/**
 * 页头（UX-02）：标题沿用现网字号（16px / 600）；`#breadcrumb`、`#actions` 具名插槽。
 */
defineProps({
  title: { type: String, default: '' },
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-header__breadcrumb:empty {
  display: none;
}
.page-header__title {
  font-size: 16px;
  font-weight: 600;
}
</style>
