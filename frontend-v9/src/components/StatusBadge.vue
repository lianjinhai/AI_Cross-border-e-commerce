<template>
  <el-tag :type="resolved.type" :size="size">{{ resolved.label }}</el-tag>
</template>

<script setup>
/**
 * 状态徽标（V9 第 1 批，StatusTag 升名，设计系统 §2）：
 * 统一以「文字 + 颜色」表达状态，禁止仅靠颜色区分。
 * 字典源：shared/statusDict.js（唯一字典源，各页禁止私配颜色文案）。
 */
import { computed } from 'vue'
import { resolveStatusTag } from '../shared/statusDict'

const props = defineProps({
  status: { type: String, default: '' },
  // 字典表名（'run' 起步；后续按 'launch'|'risk'|'order'|'refund'… 扩展，接口已冻结）。
  dict: { type: String, default: 'run' },
  size: { type: String, default: 'small' },
})

const resolved = computed(() => resolveStatusTag(props.status, props.dict))
</script>
