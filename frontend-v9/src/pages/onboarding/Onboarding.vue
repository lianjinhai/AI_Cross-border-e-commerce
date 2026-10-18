<template>
  <div class="page onboarding">
    <PageHeader :title="stepTitle" subtitle="新手引导 · 三步完成经营起点" />

    <!-- 步骤条（step query 1/2/3） -->
    <el-steps :active="stepIndex" align-center class="onboarding__steps">
      <el-step title="资源起点" />
      <el-step title="连接店铺" />
      <el-step title="经营路径" />
    </el-steps>

    <!-- 环境标签常显（部署层注入） -->
    <DataQualityBanner v-if="envBanner" :tag="envBanner.tag" detail="本环境数据为演示/测试，请勿用于真实经营决策" />

    <el-card class="mb16" shadow="never">
      <!-- ── ONB-01 资源起点：三卡 + 补充经营条件 ── -->
      <template v-if="step === 1">
        <h3 class="onboarding__card-title">你的经营资源从哪开始？</h3>

        <!-- 诚实边界：按真实保存状态渲染（服务端成功保存 ≠ 会话草稿） -->
        <div class="onboarding__scope-note" :class="{ 'is-draft': !isServerSaved }">
          {{ scopeNoteText }}
        </div>

        <!-- 推荐事实不足时的琥珀色提示（missing-data note，使用 --v91-amber-surface） -->
        <div v-if="recommendationIsFallback" class="onboarding__amber-note">
          <b>未检测到店铺或商品数据</b>
          <span>推荐为通用兜底：{{ recommended.reason }}</span>
        </div>

        <div class="onboarding__cards">
          <div
            v-for="card in startCardsList"
            :key="card.id"
            class="start-card"
            :class="{ 'is-active': isActive(card.id) }"
            role="button"
            tabindex="0"
            @click="selectCard(card.id)"
            @keydown.enter.prevent="selectCard(card.id)"
            @keydown.space.prevent="selectCard(card.id)"
          >
            <div class="start-card__head">
              <span class="start-card__title">{{ card.title }}</span>
              <el-tag v-if="recommended.card === card.id" type="primary" size="small" effect="plain" class="start-card__badge">推荐</el-tag>
            </div>
            <div class="start-card__subtitle">{{ card.subtitle }}</div>
            <div class="start-card__mainline">主线 · {{ card.mainLine }}</div>
            <div class="start-card__actions" @click.stop>
              <el-button type="primary" size="small" @click="go(card.primaryPath)">{{ card.primaryLabel }}</el-button>
              <el-button
                v-if="card.secondaryPath"
                link type="primary" size="small"
                @click="go(card.secondaryPath)"
              >{{ card.secondaryLabel }} →</el-button>
            </div>
            <div v-if="card.secondaryNote" class="start-card__note">{{ card.secondaryNote }}</div>
          </div>
        </div>

        <!-- 补充经营条件（可稍后补，会话级，未上传服务器） -->
        <div class="onboarding__conditions">
          <div class="onboarding__conditions-header" @click="showConditions = !showConditions">
            <span class="onboarding__conditions-title">补充经营条件（可稍后补）</span>
            <el-button link type="primary" size="small">{{ showConditions ? '收起' : '展开' }}</el-button>
          </div>
          <!-- 保存状态说明（按真实状态渲染，绝不冒充已保存） -->
          <div class="onboarding__conditions-caption" :class="{ 'is-draft': !isServerSaved }">
            {{ scopeNoteText }}
          </div>
          <div v-show="showConditions" class="onboarding__conditions-body">
            <el-form label-width="84px" label-position="left" size="small">
              <el-form-item label="预算">
                <el-select v-model="budget" placeholder="选择或留空（按预算上限）" class="onboarding__cond-input" @change="saveBudget">
                  <el-option v-for="opt in BUDGET_OPTIONS" :key="opt.label" :label="opt.label" :value="opt.label" />
                </el-select>
              </el-form-item>
              <el-form-item label="目标市场">
                <el-input v-model="targetMarket" placeholder="如：美国 / 东南亚（可稍后补）" class="onboarding__cond-input" @change="saveTargetMarket" />
              </el-form-item>
              <el-form-item label="风险偏好">
                <el-radio-group v-model="risk" @change="saveRisk">
                  <el-radio value="低">低</el-radio>
                  <el-radio value="中">中</el-radio>
                  <el-radio value="高">高</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-form>
          </div>
        </div>

        <div class="onboarding__footer">
          <el-button type="primary" @click="next">下一步：连接店铺</el-button>
        </div>
      </template>

      <!-- ── ONB-02 连接店铺（接入 shops 真实端点） ── -->
      <template v-else-if="step === 2">
        <h3 class="onboarding__card-title">连接你的店铺与货源</h3>
        <SectionState :code="onb2Code" @retry="loadStep2" :error="onb2Error">
          <template v-if="onb2Code === 'ready'">
            <el-table :data="shopItems" size="small" max-height="280">
              <el-table-column prop="name" label="店铺" show-overflow-tooltip />
              <el-table-column label="类型" width="100">
                <template #default="{ row }">{{ row.type === 'source' ? '货源' : '销售' }}</template>
              </el-table-column>
              <el-table-column label="状态" width="110">
                <template #default="{ row }"><StatusBadge :status="row.status" /></template>
              </el-table-column>
            </el-table>
            <el-alert
              v-if="!shopItems.length"
              type="info" :closable="false"
              title="还没有店铺"
              description="前往店铺授权页连接你的第一个销售店铺。"
            />
          </template>
        </SectionState>
        <div class="onboarding__footer">
          <el-button @click="prev">上一步</el-button>
          <el-button link @click="skipToPath">稍后连接</el-button>
          <el-button type="primary" @click="next">下一步：经营路径</el-button>
        </div>
      </template>

      <!-- ── ONB-03 经营路径（静态清单 + 明示"引导清单（非 AI 自动规划）"，API_GAP §7#11） ── -->
      <template v-else>
        <h3 class="onboarding__card-title">你的经营路径</h3>
        <DataQualityBanner tag="MANUAL_UNVERIFIED" detail="引导清单（非 AI 自动规划），按顺序完成即可起步" />
        <el-alert type="success" :closable="false" class="mb12"
          title="零基础经营准备向导"
          description="想一步步把生意跑通？沿「研究商品方向 → 选择货源 → 查看成本/风险 → 准备销售渠道 → 建立商品销售准备」走，系统会替你记住当前商品对象，每步都有下一步，不会有死端。" />
        <el-button type="primary" class="mb16" @click="startJourney">按向导一步步准备 →</el-button>
        <el-card class="mb16" shadow="never">
          <ol class="onboarding__guide">
            <li v-for="(item, i) in pathItems" :key="i">
              <span>{{ item.label }}</span>
              <el-button v-if="item.path" link type="primary" size="small" @click="go(item.path)">前往</el-button>
            </li>
          </ol>
        </el-card>
        <div class="onboarding__footer">
          <el-button @click="prev">上一步</el-button>
          <el-button type="primary" @click="finish">完成引导，进入工作台</el-button>
        </div>
      </template>
    </el-card>
  </div>
</template>

<script setup>
/**
 * 新手引导三屏合一（蓝图 R1 ONB-01/02/03，P0）：/onboarding?step=1|2|3，step query 切屏。
 *
 * B2 重构（资源起点卡）：
 * - ONB-01 资源起点：三张卡（A 无商品无店铺 / B 有商品或工厂资源 / C 已有销售店铺），
 *   推荐卡由真实信号（fetchShops 销售店铺 + fetchProducts total）经
 *   shared/onboardingStart.js 推导；选择落地到 sessionStorage（persisted 恒 false，
 *   诚实契约见 onboardingProfile.js）。补充经营条件（预算/目标市场/风险偏好）同样会话级。
 * - ONB-02 连接店铺：接 shops 真实端点；零经验用户可「稍后连接」跳过，不强制连店。
 * - ONB-03 经营路径：静态清单 + 明示非 AI（API_GAP §7#11）；清单按所选资源起点卡重排。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '../../components/PageHeader.vue'
import SectionState from '../../components/SectionState.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import DataQualityBanner from '../../components/DataQualityBanner.vue'
import { fetchShops } from '../../api/domains/shops'
import { fetchProducts } from '../../api/domains/products'
import { envTag } from '../../shared/dataLabels'
import {
  loadSessionProfile,
  saveSessionProfile,
} from '../../shared/onboardingProfile'
import {
  START_CARDS,
  recommendedStartCard,
  buildStartSignals,
  pathItemsForCard,
} from '../../shared/onboardingStart'

const route = useRoute()
const router = useRouter()

const step = computed(() => {
  const raw = Number(route.query.step)
  return raw === 2 || raw === 3 ? raw : 1
})
const stepIndex = computed(() => step.value - 1)

const stepTitles = { 1: '资源起点', 2: '连接店铺', 3: '经营路径' }
const stepTitle = computed(() => `第 ${step.value} 步 · ${stepTitles[step.value]}`)

/** 部署环境常显标签（合同测试/演示，部署层注入 window.__ERP_ENV__）。 */
const envBanner = envTag()

// ── ONB-01 三张资源起点卡 ──
const startCardsList = Object.values(START_CARDS)
const selected = ref('')
const recommended = ref({ card: 'A', reason: '暂未获取到经营事实，建议从「研究商品方向」开始' })
const recommendationIsFallback = ref(false)

/** 卡片是否被选中或推荐（两者都用 tint-blue 强调，互不冲突）。 */
function isActive(id) {
  return selected.value === id || recommended.value.card === id
}

/** 选中卡：会话草稿立即生效，同时异步同步服务端（D63 权威事实）。 */
function selectCard(id) {
  selected.value = id
  saveSessionProfile({ direction: id })
  syncToServer({ direction: id })
}

// ── ONB-01 补充经营条件（服务端持久化 + 会话草稿双写） ──
// 预算按「上限」单选，数值 + 币种直连服务端 budget_amount/budget_currency（本位币 CNY）。
const BUDGET_OPTIONS = [
  { label: '¥10,000', amount: 10000, currency: 'CNY' },
  { label: '¥30,000', amount: 30000, currency: 'CNY' },
  { label: '¥100,000', amount: 100000, currency: 'CNY' },
  { label: '¥300,000', amount: 300000, currency: 'CNY' },
]
const showConditions = ref(false)
const budget = ref('')
const targetMarket = ref('')
const risk = ref('')

/**
 * 保存状态机（诚实渲染的唯一事实源）：
 *   'saving' → 请求在途；'saved' → 服务端已落库（重新登录可读回）；
 *   'draft'  → 仅会话草稿（未登录/接口失败），必须明示「未保存到服务器」。
 */
const saveState = ref('draft')
const isServerSaved = computed(() => saveState.value === 'saved')
const scopeNoteText = computed(() => {
  if (saveState.value === 'saving') return '正在保存到服务器…'
  if (saveState.value === 'saved') {
    return '已保存到服务器：同一账号重新登录或换设备仍可读回（仅本人与所在工作区可见）。'
  }
  return '未保存到服务器：以下选择仅当前浏览器会话有效（同一标签页刷新可恢复，关闭标签页后需重新选择）。'
})

/** 会话草稿 + 异步服务端同步；服务端失败时状态回落 draft，不阻塞交互。 */
async function syncToServer(profileFields) {
  saveState.value = 'saving'
  try {
    await saveBusinessProfile(serverPayloadFromProfile(profileFields))
    saveState.value = 'saved'
  } catch {
    saveState.value = 'draft'
  }
}

function saveBudget(label) {
  const opt = BUDGET_OPTIONS.find((o) => o.label === label)
  if (!label || !opt) {
    saveSessionProfile({ budget: '', budgetAmount: null, budgetCurrency: null })
    syncToServer({ budgetAmount: null, budgetCurrency: null })
    return
  }
  saveSessionProfile({ budget: opt.label, budgetAmount: opt.amount, budgetCurrency: opt.currency })
  syncToServer({ budgetAmount: opt.amount, budgetCurrency: opt.currency })
}
function saveTargetMarket(v) {
  const val = (v || '').trim()
  saveSessionProfile({ targetMarket: val })
  syncToServer({ targetMarket: val || null })
}
function saveRisk(v) {
  saveSessionProfile({ risk: v || '' })
  syncToServer({ risk: v || null })
}

// ── ONB-02 店铺接入态（接 shops 已接端点） ──
const shopItems = ref([])
const onb2Loading = ref(false)
const onb2Error = ref('')

const onb2Code = computed(() => {
  if (onb2Error.value) return 'ERROR'
  if (onb2Loading.value) return 'LOADING'
  if (!shopItems.value.length) return 'EMPTY_NEW'
  return 'ready'
})

async function loadStep2() {
  onb2Loading.value = true
  onb2Error.value = ''
  try {
    const data = await fetchShops()
    shopItems.value = Array.isArray(data?.items) ? data.items : []
  } catch (e) {
    const detail = e?.response?.data?.detail
    onb2Error.value = (detail && typeof detail === 'object' ? detail.message : detail) || e?.message || '加载失败'
  } finally {
    onb2Loading.value = false
  }
}

// ── ONB-03 经营路径（按所选卡重排；默认回退原 GENERIC 清单） ──
const pathItems = computed(() => pathItemsForCard(selected.value || 'A'))

// ── 导航 ──
function goToStep(n) {
  router.replace({ path: '/onboarding', query: { step: String(n) } })
}
function next() { goToStep(Math.min(3, step.value + 1)) }
function prev() { goToStep(Math.max(1, step.value - 1)) }
/** 稍后连接：零经验用户跳过连店，直接进入经营路径。 */
function skipToPath() { goToStep(3) }
function finish() { router.push('/app') }
function go(path) { if (path) router.push(path) }
/** 进入 J0 零基础经营准备向导（链路首步：研究商品方向）。 */
function startJourney() { router.push({ path: '/app/market/discovery', query: { journey: 'j0' } }) }

// ── 步骤 1：恢复画像（服务端优先，会话草稿兜底） + 用真实信号推导推荐卡 ──
async function loadStep1() {
  // 服务端是权威事实：能读回就按服务端恢复（重新登录一致性的 UI 体现）
  try {
    const dto = await fetchBusinessProfile()
    const serverProfile = profileFromServer(dto)
    if (serverProfile) {
      saveState.value = 'saved'
      if (serverProfile.direction) selected.value = serverProfile.direction
      budget.value = serverProfile.budget || ''
      targetMarket.value = serverProfile.targetMarket || ''
      risk.value = serverProfile.risk || ''
    }
  } catch {
    saveState.value = 'draft'
  }
  // 服务端读不到的字段回落会话草稿（未登录/离线时仍有可用体验）
  const profile = loadSessionProfile()
  if (!selected.value && profile?.direction) selected.value = profile.direction
  if (!budget.value) budget.value = profile?.budget || ''
  if (!targetMarket.value) targetMarket.value = profile?.targetMarket || ''
  if (!risk.value) risk.value = profile?.risk || ''

  let signals
  try {
    const [shopsData, productsData] = await Promise.all([
      fetchShops().catch(() => ({ items: [] })),
      fetchProducts({ page: 1 }).catch(() => ({ total: 0 })),
    ])
    signals = buildStartSignals({
      shopItems: shopsData?.items || [],
      productTotal: productsData?.total || 0,
    })
  } catch {
    signals = buildStartSignals({ shopItems: [], productTotal: 0 })
  }

  recommended.value = recommendedStartCard(signals)
  // 事实不足（无店铺无商品）→ 标记琥珀色兜底提示
  recommendationIsFallback.value = !signals.hasSalesShop && !signals.hasGoods
  // 尚未选择时默认跟随推荐，但仍以用户可改写的会话值为准
  if (!selected.value) {
    selected.value = recommended.value.card
    saveSessionProfile({ direction: recommended.value.card })
  }
}

onMounted(() => {
  // 任何入口都先恢复已保存的方向（会话缓存即时可用），随后异步向服务端核对：
  // 服务端有值则以服务端为准（重新登录一致），失败则保持会话草稿并如实标注。
  const profile = loadSessionProfile()
  if (profile?.direction) selected.value = profile.direction
  if (step.value === 1) loadStep1()
  if (step.value === 2) {
    restoreFromServer()
    loadStep2()
  }
  if (step.value === 3) restoreFromServer()
})
watch(step, (n) => {
  if (n === 1) loadStep1()
  if (n === 2 && !shopItems.value.length) loadStep2()
})
</script>

<style scoped>
.onboarding__steps { margin-bottom: 16px; }
.onboarding__card-title { margin: 0 0 12px; font-size: 15px; }
.onboarding__scope-note {
  margin-bottom: 12px;
  padding: 8px 12px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  background: var(--v91-tint-blue);
  border: 1px solid var(--v91-border);
  border-radius: 6px;
}
.onboarding__amber-note {
  margin-bottom: 12px;
  padding: 8px 12px;
  font-size: var(--font-size-xs);
  color: var(--color-text);
  background: var(--v91-amber-surface);
  border: 1px solid var(--v91-border);
  border-radius: 6px;
}
.onboarding__amber-note b { margin-right: 6px; }

.onboarding__cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--layout-content-gutter, 28px);
}
.start-card {
  border: 1px solid var(--v91-border);
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  background: #fff;
  transition: border-color .15s, background .15s;
}
.start-card.is-active {
  border: 2px solid var(--v91-tint-blue);
  background: var(--v91-tint-blue);
}
.start-card__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.start-card__title { font-size: var(--font-size-md); font-weight: 600; color: var(--color-text); }
.start-card__subtitle { margin: 4px 0 8px; font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.start-card__mainline { font-size: var(--font-size-sm); color: var(--color-text-regular); margin-bottom: 10px; }
.start-card__actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.start-card__note { margin-top: 8px; font-size: var(--font-size-xs); color: var(--color-text-secondary); }

.onboarding__conditions { margin-top: 20px; border-top: 1px dashed var(--v91-border); padding-top: 12px; }
.onboarding__conditions-header { display: flex; align-items: center; justify-content: space-between; cursor: pointer; }
.onboarding__conditions-title { font-size: var(--font-size-sm); font-weight: 600; color: var(--color-text); }
.onboarding__conditions-caption {
  margin: 6px 0 10px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  background: var(--v91-tint-blue);
  border-radius: 4px;
  padding: 6px 10px;
}
/* 草稿态（未保存到服务器）用琥珀色警示；已保存态保持平静的浅蓝 */
.onboarding__scope-note.is-draft,
.onboarding__conditions-caption.is-draft {
  background: var(--v91-amber-surface);
}
.onboarding__cond-input { max-width: 320px; }

.onboarding__guide { margin: 0; padding-left: 20px; }
.onboarding__guide li { margin: 6px 0; display: flex; justify-content: space-between; align-items: center; }
.onboarding__footer { margin-top: 12px; display: flex; justify-content: flex-end; gap: 8px; }
.mb12 { margin-bottom: 12px; }
</style>
