<template>
  <div class="auth-wizard">
    <el-steps :active="step" align-center finish-status="success">
      <el-step title="添加店铺" description="平台 / 角色 / 凭据" />
      <el-step title="平台授权" description="打开授权页登录授权" />
      <el-step title="回填授权码" description="粘贴授权完成码" />
    </el-steps>

    <!-- 第 1 步：添加店铺 -->
    <div v-if="step === 0" class="auth-wizard__body">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="平台" prop="platform">
          <el-select v-model="form.platform" placeholder="请选择平台" style="width:100%" @change="onPlatformChange">
            <el-option v-for="p in platformOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="店铺角色" prop="role">
          <el-radio-group v-model="form.role">
            <el-radio-button value="source">货源（搜品/一件代发）</el-radio-button>
            <el-radio-button value="sales">销售（上架/拉单）</el-radio-button>
          </el-radio-group>
          <div class="muted">货源店铺用于 1688 采集与代发下单；销售店铺用于商品上架与订单同步，两类不可混用</div>
        </el-form-item>
        <el-form-item label="店铺名">
          <el-input v-model="form.shop_name" placeholder="如：我的 Shopee 店" />
        </el-form-item>
        <ShopCommerceFields :model="form" />
        <el-form-item label="店铺ID/登录ID">
          <el-input v-model="form.shop_id" placeholder="平台店铺 ID 或登录账号" />
        </el-form-item>
        <el-form-item label="AppKey" prop="app_key">
          <el-input v-model="form.app_key" placeholder="平台开放平台 AppKey" />
        </el-form-item>
        <el-form-item label="AppSecret">
          <el-input v-model="form.app_secret" type="password" show-password placeholder="平台开放平台 AppSecret" />
        </el-form-item>
      </el-form>
      <div class="auth-wizard__nav">
        <el-button @click="$emit('cancel')">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createShop">保存并下一步</el-button>
      </div>
    </div>

    <!-- 第 2 步：发起授权 -->
    <div v-else-if="step === 1" class="auth-wizard__body">
      <el-alert type="info" :closable="false" show-icon
        title="点击下方按钮打开平台授权页，登录并完成授权后回到本页"
        :description="authorizeHint" />
      <div class="auth-wizard__nav">
        <el-button @click="step = 0">上一步</el-button>
        <el-button :loading="authorizing" @click="openAuthorize">打开授权页</el-button>
        <el-button type="primary" @click="step = 2">已完成授权，下一步</el-button>
      </div>
    </div>

    <!-- 第 3 步：粘贴授权码 -->
    <div v-else class="auth-wizard__body">
      <el-input v-model="authCode" type="textarea" :rows="4" placeholder="粘贴授权完成后平台返回的授权码" />
      <el-alert v-if="authError" type="error" :closable="false" show-icon class="auth-wizard__error"
        :title="authError" />
      <div class="auth-wizard__nav">
        <el-button @click="step = 1">上一步</el-button>
        <el-button type="primary" :loading="exchanging" :disabled="!authCode.trim()" @click="submitCode">提交授权码</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * 店铺授权向导（UX-C，517 行旧 Shops 页拆分件）：
 * 添加店铺 → 平台授权（authorize_url）→ 授权码兑换（exchange_code）三步；
 * 授权失败原因经 auth_message / 接口 detail 直出（验收：OAuth 徽标统一+失败原因可见）。
 */
import { computed, reactive, ref } from 'vue'
import { ElMessage } from '../../shared/ui'
import ShopCommerceFields from './ShopCommerceFields.vue'
import { shopCommerceFields } from '../../composables/shopCommerce'
import { createShop as apiCreateShop, fetchShops, authorize, exchangeCode } from '../../api/domains/shops'
import { shopStatusTag } from '../../composables/listingFlow'

const props = defineProps({
  platformOptions: { type: Array, default: () => [] }, // [{value,label}]，来自 /shops/platforms
})

const emit = defineEmits(['done', 'cancel'])

const step = ref(0)
const saving = ref(false)
const authorizing = ref(false)
const exchanging = ref(false)
const shop = ref(null)
const authCode = ref('')
const authError = ref('')

const form = reactive({ ...shopCommerceFields(), platform: '', role: '', shop_name: '', shop_id: '', app_key: '', app_secret: '' })
const formRef = ref()

const rules = {
  platform: [{ required: true, message: '请选择平台', trigger: 'change' }],
  app_key: [{ required: true, message: '请填写 AppKey', trigger: 'blur' }],
}

const authorizeHint = computed(() => shop.value
  ? `店铺「${shop.value.shop_name || `#${shop.value.id}`}」（${shopStatusTag(shop.value.status).text}）`
  : '')

function onPlatformChange(platform) {
  // 按平台推导默认角色：1688=货源，其余=销售（用户可手动改）
  form.role = platform === '1688' ? 'source' : 'sales'
}

async function createShop() {
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return
  if (!form.role) { ElMessage.warning('请选择店铺角色（货源/销售）'); return }
  saving.value = true
  try {
    const created = await apiCreateShop({ ...form })
    shop.value = created && created.id ? created : null
    if (!shop.value) {
      // 创建接口未回传实体时回查列表定位新店（同名 + 同 AppKey 优先）
      const data = await fetchShops()
      const list = data.items || []
      shop.value = list.find((s) => s.shop_name === form.shop_name && s.app_key === form.app_key) || null
    }
    ElMessage.success('店铺已添加')
    step.value = 1
    emit('done', { stage: 'created' })
  } finally {
    saving.value = false
  }
}

async function openAuthorize() {
  if (!shop.value) return
  authorizing.value = true
  try {
    const data = await authorize(shop.value.id)
    if (data.authorize_url) window.open(data.authorize_url, '_blank')
    ElMessage.info(data.manual_hint || '已打开授权页面，请登录并完成授权')
  } finally {
    authorizing.value = false
  }
}

async function submitCode() {
  const code = authCode.value.trim()
  if (!code) return
  exchanging.value = true
  authError.value = ''
  try {
    const data = await exchangeCode(shop.value.id, { code })
    ElMessage.success(`授权成功：${data.message}`)
    emit('done', { stage: 'authorized', shop: shop.value })
  } catch (err) {
    // 失败原因直出：authorize_message / detail.message（验收条目）
    authError.value = err?.response?.data?.detail?.message
      || (typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '')
      || err?.message || '授权码兑换失败，请核对后重试'
  } finally {
    exchanging.value = false
  }
}

/** 外部注入「刚创建的店铺」（父组件列表回查后调用），向导无需自行持有写状态。 */
function bindShop(created) {
  shop.value = created
  if (created) step.value = 1
}

defineExpose({ bindShop })
</script>

<style scoped>
.auth-wizard__body {
  margin-top: var(--space-4);
}
.auth-wizard__nav {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
.auth-wizard__error {
  margin-top: var(--space-2);
}
.muted {
  color: var(--color-text-secondary);
  font-size: 12px;
  margin-top: 4px;
}
</style>
