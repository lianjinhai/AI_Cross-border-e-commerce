<template>
  <div class="page">
    <el-alert type="info" show-icon :closable="false" class="mb16" title="财务事实工作台"
      description="维护交易日汇率、订单行与费用，并核对平台结算。所有数据将进入统一 GMV、净收入和贡献利润口径。" />
    <el-tabs v-model="tab">
      <el-tab-pane label="汇率" name="fx">
        <el-card class="mb16"><el-form :inline="true">
          <el-form-item label="币种"><el-input v-model="fxForm.base_currency" style="width:90px" /></el-form-item>
          <el-form-item label="兑 USD"><el-input-number v-model="fxForm.rate" :min="0.000001" :precision="6" /></el-form-item>
          <el-form-item label="生效时间"><el-date-picker v-model="fxForm.effective_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
          <el-form-item><el-button v-if="admin" type="primary" :loading="saving" @click="saveFx">新增汇率</el-button></el-form-item>
        </el-form></el-card>
        <el-table :data="fxItems" v-loading="loading"><el-table-column prop="base_currency" label="基础币种"/><el-table-column prop="quote_currency" label="报价币种"/><el-table-column prop="rate" label="汇率"/><el-table-column prop="effective_at" label="生效时间"/><el-table-column prop="source" label="来源"/></el-table>
      </el-tab-pane>
      <el-tab-pane label="订单明细与费用" name="orders">
        <el-card class="mb16"><div style="display:flex;gap:10px"><el-input-number v-model="orderId" :min="1" placeholder="订单 ID"/><el-button type="primary" @click="loadOrder">加载财务明细</el-button></div></el-card>
        <template v-if="detail.order">
          <el-descriptions :column="4" border class="mb16"><el-descriptions-item label="订单号">{{ detail.order.external_no }}</el-descriptions-item><el-descriptions-item label="平台">{{ detail.order.platform }}</el-descriptions-item><el-descriptions-item label="金额">{{ detail.order.currency }} {{ detail.order.amount }}</el-descriptions-item><el-descriptions-item label="状态">{{ detail.order.status }}</el-descriptions-item></el-descriptions>
          <el-row :gutter="16"><el-col :span="12"><el-card><template #header>订单行</template><el-table :data="detail.lines"><el-table-column prop="external_line_no" label="行号"/><el-table-column prop="sku" label="SKU"/><el-table-column prop="qty" label="数量"/><el-table-column prop="unit_price" label="单价"/><el-table-column prop="product_cost" label="成本"/></el-table><el-button v-if="write" class="mt12" @click="lineDialog=true">新增订单行</el-button></el-card></el-col>
          <el-col :span="12"><el-card><template #header>费用</template><el-table :data="detail.fees"><el-table-column prop="fee_type" label="类型"/><el-table-column prop="amount" label="金额"/><el-table-column prop="currency" label="币种"/><el-table-column prop="occurred_at" label="发生时间"/></el-table><el-button v-if="write" class="mt12" @click="feeDialog=true">新增费用</el-button></el-card></el-col></el-row>
        </template>
      </el-tab-pane>
      <el-tab-pane label="平台结算对账" name="settlements">
        <div style="display:flex;justify-content:flex-end;margin-bottom:12px"><el-button v-if="write" type="primary" @click="settleDialog=true">录入/更新结算单</el-button></div>
        <el-alert v-if="unreconciled" type="warning" :closable="false" :title="`${unreconciled} 笔结算存在差异`" class="mb16"/>
        <el-table :data="settlements" v-loading="loading"><el-table-column prop="platform" label="平台"/><el-table-column prop="external_settlement_no" label="结算单号"/><el-table-column prop="gross_amount" label="交易总额"/><el-table-column prop="fee_amount" label="费用"/><el-table-column prop="refund_amount" label="退款"/><el-table-column prop="expected_net" label="应结"/><el-table-column prop="net_amount" label="实结"/><el-table-column prop="variance" label="差异"/><el-table-column label="结果"><template #default="{row}"><el-tag :type="row.reconciled?'success':'danger'">{{ row.reconciled?'已平':'待核对' }}</el-tag></template></el-table-column></el-table>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="lineDialog" title="新增订单行"><el-form label-width="100px"><el-form-item label="外部行号"><el-input v-model="line.external_line_no"/></el-form-item><el-form-item label="SKU"><el-input v-model="line.sku"/></el-form-item><el-form-item label="标题"><el-input v-model="line.title"/></el-form-item><el-form-item label="数量"><el-input-number v-model="line.qty" :min="1"/></el-form-item><el-form-item label="单价/成本"><el-input-number v-model="line.unit_price" :min="0"/> <el-input-number v-model="line.product_cost" :min="0"/></el-form-item><el-form-item label="币种"><el-input v-model="line.currency"/></el-form-item></el-form><template #footer><el-button @click="lineDialog=false">取消</el-button><el-button type="primary" @click="saveLine">保存</el-button></template></el-dialog>
    <el-dialog v-model="feeDialog" title="新增订单费用"><el-form label-width="100px"><el-form-item label="费用类型"><el-select v-model="fee.fee_type"><el-option v-for="x in ['platform_fee','payment_fee','shipping','tax','advertising','other']" :key="x" :value="x"/></el-select></el-form-item><el-form-item label="金额"><el-input-number v-model="fee.amount" :precision="2"/></el-form-item><el-form-item label="币种"><el-input v-model="fee.currency"/></el-form-item></el-form><template #footer><el-button @click="feeDialog=false">取消</el-button><el-button type="primary" @click="saveFee">保存</el-button></template></el-dialog>
    <el-dialog v-model="settleDialog" title="录入平台结算单"><el-form label-width="110px"><el-form-item label="平台"><el-input v-model="settle.platform"/></el-form-item><el-form-item label="结算单号"><el-input v-model="settle.external_settlement_no"/></el-form-item><el-form-item label="总额/费用"><el-input-number v-model="settle.gross_amount" :min="0"/> <el-input-number v-model="settle.fee_amount" :min="0"/></el-form-item><el-form-item label="退款/实结"><el-input-number v-model="settle.refund_amount" :min="0"/> <el-input-number v-model="settle.net_amount"/></el-form-item><el-form-item label="币种"><el-input v-model="settle.currency"/></el-form-item></el-form><template #footer><el-button @click="settleDialog=false">取消</el-button><el-button type="primary" @click="saveSettlement">幂等保存</el-button></template></el-dialog>
  </div>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'; import { ElMessage } from '../ui'; import api from '../api'; import { canAdmin, canWrite, can } from '../permissions'
const admin=canAdmin(), write=can('finance:write'), tab=ref('fx'), loading=ref(false), saving=ref(false), fxItems=ref([]), settlements=ref([]), unreconciled=ref(0), orderId=ref(), detail=ref({}), lineDialog=ref(false), feeDialog=ref(false), settleDialog=ref(false)
const fxForm=reactive({base_currency:'CNY',rate:0.14,effective_at:new Date().toISOString().slice(0,19),quote_currency:'USD',source:'manual'})
const line=reactive({external_line_no:'',sku:'',title:'',qty:1,unit_price:0,product_cost:0,currency:'USD'}), fee=reactive({fee_type:'platform_fee',amount:0,currency:'USD',source:'manual'}), settle=reactive({platform:'',external_settlement_no:'',gross_amount:0,fee_amount:0,refund_amount:0,net_amount:0,currency:'USD',status:'pending'})
async function load(){loading.value=true;try{const [a,b]=await Promise.all([api.get('/finance/fx'),api.get('/finance/settlement-reconciliation')]);fxItems.value=a.data.items||[];settlements.value=b.data.items||[];unreconciled.value=b.data.unreconciled||0}finally{loading.value=false}}
async function saveFx(){if(!fxForm.base_currency||!fxForm.rate)return ElMessage.warning('请填写币种和汇率');saving.value=true;try{await api.post('/finance/fx',fxForm);ElMessage.success('汇率已保存');load()}finally{saving.value=false}}
async function loadOrder(){if(!orderId.value)return ElMessage.warning('请输入订单 ID');detail.value=(await api.get(`/finance/orders/${orderId.value}/detail`)).data}
async function saveLine(){if(!line.external_line_no)return ElMessage.warning('请填写外部行号');await api.post(`/finance/orders/${orderId.value}/lines`,line);lineDialog.value=false;await loadOrder()}
async function saveFee(){await api.post(`/finance/orders/${orderId.value}/fees`,fee);feeDialog.value=false;await loadOrder()}
async function saveSettlement(){if(!settle.platform||!settle.external_settlement_no)return ElMessage.warning('请填写平台和结算单号');await api.post('/finance/platform-settlements',settle);settleDialog.value=false;ElMessage.success('结算单已幂等保存');load()}
onMounted(load)
</script>
