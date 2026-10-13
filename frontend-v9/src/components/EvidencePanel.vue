<template>
  <div class="evidence-panel">
    <!-- 数据真实性标签（P0 扩展） -->
    <div v-if="source || verified" class="evidence-panel__meta">
      <el-tag :type="tone" size="small" effect="plain">{{ verified ? '官方已核验' : (source || '未核验') }}</el-tag>
      <el-tag v-if="expiryTag" type="info" size="small" effect="plain">{{ expiryTag }}</el-tag>
      <span v-if="scope" class="evidence-panel__scope">适用范围：{{ scope }}</span>
      <span v-if="version" class="evidence-panel__version">v{{ version }}</span>
    </div>

    <div v-if="items.length" class="evidence-panel__section">
      <div class="evidence-panel__label">决策依据</div>
      <slot name="body">
        <ul class="evidence-panel__list">
          <li v-for="(item, i) in items" :key="i">{{ item }}</li>
        </ul>
      </slot>
    </div>
    <div v-if="risks.length" class="evidence-panel__section">
      <div class="evidence-panel__label evidence-panel__label--risk">风险提示</div>
      <ul class="evidence-panel__list">
        <li v-for="(risk, i) in risks" :key="i" class="evidence-panel__risk">{{ risk }}</li>
      </ul>
    </div>
    <el-button
      v-if="decisionId" link type="primary" size="small"
      @click="$emit('viewDecision', decisionId)"
    >查看完整决策链</el-button>
  </div>
</template>

<script setup>
/**
 * 证据面板（V9 第 2 批 → 蓝图 R1 P0 扩展）：
 * 决策依据链展示 + 数据真实性标签（source/verified/scope/version/expiresAt）。
 * 未核验默认中性样式（非绿色），verified=true 才显绿色"官方已核验"。
 * 纯函数源：shared/evidence.js（evidenceTone / expiryLabel）。
 */
import { computed } from 'vue'
import { evidenceTone, expiryLabel } from '../shared/evidence'

const props = defineProps({
  items: { type: Array, default: () => [] },
  risks: { type: Array, default: () => [] },
  decisionId: { type: [String, Number], default: '' },
  /** 数据来源（如"1688 API"/"人工录入"）。 */
  source: { type: String, default: '' },
  /** 官方已核验布尔（默认 false → 中性样式）。 */
  verified: { type: Boolean, default: false },
  /** 适用范围。 */
  scope: { type: String, default: '' },
  /** 版本号。 */
  version: { type: String, default: '' },
  /** 过期时间（ISO 字符串）。 */
  expiresAt: { type: String, default: '' },
  /** 关联对象（refObject）。 */
  refObject: { type: Object, default: () => ({}) },
})

defineEmits(['viewDecision'])

const tone = computed(() => evidenceTone({ verified: props.verified, source: props.source }))
const expiryTag = computed(() => expiryLabel(props.expiresAt))
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
.evidence-panel__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.evidence-panel__scope,
.evidence-panel__version {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}
</style>
