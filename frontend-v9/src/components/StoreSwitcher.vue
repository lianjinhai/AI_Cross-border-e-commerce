<template>
  <el-select
    :model-value="modelValue"
    size="small"
    class="store-switcher__select"
    clearable
    placeholder="全部店铺"
    @change="onChange"
  >
    <el-option
      v-for="shop in salesShops"
      :key="shop.id"
      :label="shop.name"
      :value="shop.id"
    />
    <el-option
      v-for="item in unconnected"
      :key="`unconnected-${item.id}`"
      :label="`${item.name}（待连接）`"
      :value="item.id"
      disabled
    />
  </el-select>
</template>

<script setup>
/**
 * 店铺切换器（契约 §2.4 → 蓝图 R1 P1 扩展）。
 *
 * 新增：
 * - unconnected prop：未接店铺引导项
 * - guideConnect 事件：跳 CH-01 /app/channels
 * - 仅销售店铺（filterSalesShops 剔除 source 类型）
 * 纯函数源：shared/storeScope.js（filterSalesShops / resolveScopeKey / isAllShops / unconnectedShops）。
 */
import { computed, watch } from 'vue'
import { filterSalesShops } from '../shared/storeScope'

const props = defineProps({
  shops: { type: Array, default: () => [] },
  modelValue: { type: [String, Number], default: '' },
  /** 未接店铺引导项 [{id, name, hint}]。 */
  unconnected: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'guideConnect'])

const salesShops = computed(() => filterSalesShops(props.shops))

function onChange(shopId) {
  emit('update:modelValue', shopId ?? '')
}

// 选中即落盘：页面侧直接读 localStorage 取默认筛选（单一持久化事实源）。
watch(() => props.modelValue, (value) => {
  if (value === '' || value === null || value === undefined) localStorage.removeItem('v9_selected_shop')
  else localStorage.setItem('v9_selected_shop', String(value))
})
</script>

<style scoped>
.store-switcher__select {
  width: 180px;
}
@media (max-width: 560px) {
  .store-switcher__select { width: 128px; }
}
</style>
