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
      v-for="shop in shops"
      :key="shop.id"
      :label="shop.name"
      :value="shop.id"
    />
  </el-select>
</template>

<script setup>
/**
 * 店铺切换器（契约 §2.4）：props {shops, modelValue}，emit update:modelValue。
 * 选中值持久化到 localStorage `v9_selected_shop`，供订单/广告/客服页作默认筛选。
 */
import { watch } from 'vue'

const props = defineProps({
  shops: { type: Array, default: () => [] },
  modelValue: { type: [String, Number], default: '' },
})

const emit = defineEmits(['update:modelValue'])

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
</style>
