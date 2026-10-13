<template>
  <el-alert :type="tone" :closable="false" show-icon class="data-quality-banner">
    <template #title>
      <el-tag :type="tone" size="small" effect="plain">{{ tagLabel }}</el-tag>
      <span class="data-quality-banner__text">{{ detail }}</span>
    </template>
    <div v-if="links && links.length" class="data-quality-banner__links">
      <el-button
        v-for="link in links"
        :key="link.label"
        link
        type="primary"
        size="small"
        @click="onNavigate(link)"
      >{{ link.label }}</el-button>
    </div>
    <slot name="detail" />
  </el-alert>
</template>

<script setup>
/**
 * 数据质量横幅（蓝图 §6.5，包 1 P0 全新组件）。
 *
 * 八类标签：官方平台已核验 / 平台API已返回待业务验证 / 人工录入未核验 / 外部导入 /
 * 合同测试 / 演示 / AI估算 / 数据未知。
 * 合同测试/演示环境须常显（部署层注入，非页面各自判断）。
 * 纯函数源：shared/dataLabels.js（DATA_TAGS / tagInfo / envTag）。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { tagInfo, envTag } from '../shared/dataLabels'

const props = defineProps({
  /** 八类标签码（DATA_TAGS 的 key）。 */
  tag: { type: String, default: 'UNKNOWN' },
  /** 补充说明。 */
  detail: { type: String, default: '' },
  /** 缺项明细链接 [{label, path}]。 */
  links: { type: Array, default: () => [] },
})

const emit = defineEmits(['navigate'])
const router = useRouter()

const tagInfo_ = computed(() => tagInfo(props.tag))
const tagLabel = computed(() => tagInfo_.value.label)
const tone = computed(() => tagInfo_.value.tone)

// 部署层常显标签（合同测试/演示环境）
const envTagInfo = envTag()

function onNavigate(link) {
  emit('navigate', link)
  if (link?.path) router.push(link.path)
}
</script>

<style scoped>
.data-quality-banner__text {
  margin-left: 8px;
}
.data-quality-banner__links {
  margin-top: 4px;
  display: flex;
  gap: 8px;
}
</style>
