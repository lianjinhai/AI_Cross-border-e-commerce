<template>
  <el-tag :type="map[status] || 'info'" size="small">{{ label[status] || status }}</el-tag>
</template>

<script setup>
const props = defineProps({ status: String })
const map = { success: 'success', running: 'primary', failed: 'danger',
  partial: 'warning', blocked: 'warning', skipped: 'info', queued: 'info',
  published: 'success', draft: 'info', pending: 'info', low: 'success', mid: 'warning', high: 'danger' }
const label = { success: '成功', running: '运行中', failed: '失败', published: '已发布',
  partial: '部分成功', blocked: '等待人工', skipped: '已跳过', queued: '排队中',
  draft: '草稿', pending: '待处理', low: '低', mid: '中', high: '高' }
</script>
