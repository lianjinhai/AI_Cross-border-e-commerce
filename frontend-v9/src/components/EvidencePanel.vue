<template>
  <div class="evidence-panel">
    <div v-if="items.length" class="evidence-panel__section">
      <div class="evidence-panel__label">决策依据</div>
      <ul class="evidence-panel__list">
        <li v-for="(item, i) in items" :key="i">{{ item }}</li>
      </ul>
    </div>
    <div v-if="risks.length" class="evidence-panel__section">
      <div class="evidence-panel__label evidence-panel__label--risk">风险提示</div>
      <ul class="evidence-panel__list">
        <li v-for="(risk, i) in risks" :key="i" class="evidence-panel__risk">{{ risk }}</li>
      </ul>
    </div>
    <el-button
      v-if="decisionId" link type="primary" size="small"
      @click="$router.push(`/app/ai/decisions?decision_id=${decisionId}`)"
    >查看完整决策链</el-button>
  </div>
</template>

<script setup>
/**
 * 证据面板（V9 第 2 批，设计系统 §2）：决策依据链展示；有 decisionId 时
 * 提供跳转 /app/ai/decisions 的深链（AI 可解释性通用件）。
 */
defineProps({
  items: { type: Array, default: () => [] },
  risks: { type: Array, default: () => [] },
  decisionId: { type: [String, Number], default: '' },
})
</script>

<style scoped>
.evidence-panel__section {
  margin-bottom: 6px;
}
.evidence-panel__label {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  margin-bottom: 2px;
}
.evidence-panel__label--risk {
  color: var(--color-warning);
}
.evidence-panel__list {
  margin: 0;
  padding-left: 18px;
  color: var(--color-text-regular);
  font-size: var(--font-size-sm);
}
.evidence-panel__list li {
  margin: 2px 0;
}
.evidence-panel__risk {
  color: var(--color-warning);
}
</style>
