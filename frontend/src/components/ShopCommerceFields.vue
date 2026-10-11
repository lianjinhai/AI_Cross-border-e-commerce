<template>
  <el-form-item label="目标国家">
    <el-input v-model="model.market" placeholder="填写具体国家码，如 US、DE、TR；真实发布前必填" maxlength="8" />
  </el-form-item>
  <el-form-item label="履约方式">
    <el-select v-model="model.fulfillment_mode" clearable placeholder="选择实际履约方式" style="width:100%">
      <el-option value="DROPSHIP" label="订单后采购与代发" />
      <el-option value="PLATFORM_STOCK" label="平台预先备货" />
      <el-option value="SELF_STOCK" label="自有库存履约" />
      <el-option value="FACTORY_DIRECT" label="工厂直供" />
    </el-select>
  </el-form-item>
  <el-form-item label="店铺类型"><el-input v-model="model.store_type" placeholder="按平台实际账户填写" maxlength="64" /></el-form-item>
  <el-form-item label="账户类型"><el-input v-model="model.account_type" maxlength="64" /></el-form-item>
  <el-form-item label="经营模式"><el-input v-model="model.business_mode" placeholder="如普通卖家、全托管；不能替代履约方式" maxlength="64" /></el-form-item>
</template>

<script setup>
defineProps({ model: { type: Object, required: true } })
</script>
