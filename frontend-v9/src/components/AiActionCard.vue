<template>
  <el-card class="ai-action-card" shadow="never">
    <!-- ① 建议段：标题 + 一句话结论 + 置信/评分 -->
    <div class="ai-action-card__head">
      <span class="ai-action-card__title">{{ suggestion.title }}</span>
      <el-tag v-if="suggestion.score != null" size="small" type="warning">
        置信 {{ suggestion.score }}
      </el-tag>
    </div>
    <p class="ai-action-card__conclusion">{{ suggestion.conclusion }}</p>

    <!-- ② 证据段：证据链 + 风险（可解释性，不做黑盒建议） -->
    <div v-if="evidence.length || risks.length" class="ai-action-card__evidence">
      <EvidencePanel :items="evidence" :risks="risks" />
    </div>

    <!-- ③ 动作段：主/次按钮；不可执行 disabled + 原因旁展示 -->
    <div class="ai-action-card__actions">
      <template v-for="entry in actions" :key="entry.label">
        <el-tooltip v-if="!entry.executable && entry.reason" :content="entry.reason" placement="top">
          <span>
            <el-button size="small" :type="entry.primary ? 'primary' : 'default'" disabled>
              {{ entry.label }}
            </el-button>
          </span>
        </el-tooltip>
        <el-button
          v-else size="small" :type="entry.primary ? 'primary' : 'default'"
          @click="$emit('apply', entry)"
        >{{ entry.label }}</el-button>
      </template>
    </div>
  </el-card>
</template>

<script setup>
/**
 * AI 建议统一卡（V9 第 2 批，设计系统 §3 三段式）：所有 AI 建议
 * （选品机会/定价/广告选词/Listing 优化等）统一为 建议→证据→动作 三段。
 * 不可执行动作 disabled + 原因（NextActionButton 铁律：绝不「能点但吃了 409」）。
 */
import EvidencePanel from './EvidencePanel.vue'

defineProps({
  // { title, conclusion, score? }
  suggestion: { type: Object, required: true },
  evidence: { type: Array, default: () => [] },
  risks: { type: Array, default: () => [] },
  // [{ label, primary?, executable, reason?, payload? }]
  actions: { type: Array, default: () => [] },
})

defineEmits(['apply'])
</script>

<style scoped>
.ai-action-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.ai-action-card__title {
  font-weight: var(--font-weight-medium);
}
.ai-action-card__conclusion {
  margin: 6px 0;
  color: var(--color-text-regular);
  font-size: var(--font-size-md);
}
.ai-action-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: 10px;
}
</style>
