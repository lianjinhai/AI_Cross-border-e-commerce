<template>
  <div>
    <div class="copilot-fab" title="AI 副驾驶" @click="open = !open">
      <el-icon :size="24"><ChatDotRound /></el-icon>
    </div>
    <el-drawer v-model="open" title="AI 副驾驶" size="440px" :append-to-body="true">
      <el-alert :title="AI_SESSION_PERSIST_NOTE" type="info" :closable="false" class="mb8" />
      <div ref="listRef" class="chat-list">
        <div v-for="(m, i) in messages" :key="i" class="chat-msg" :class="m.role">
          <div class="chat-bubble">
            <div class="chat-text">{{ m.content }}</div>
            <div v-if="m.actionVms?.length" class="chat-actions">
              <template v-for="vm in m.actionVms" :key="vm.key">
                <el-button
                  v-if="vm.status === 'ready'" size="small" type="primary" plain
                  @click="runAction(vm)"
                >{{ vm.label }}</el-button>
                <el-tooltip v-else :content="vm.reason" placement="top">
                  <el-tag size="small" :type="vm.status === 'waiting' ? 'info' : 'warning'">
                    {{ vm.status === 'waiting' ? `待接入 · ${vm.label}` : `未配置 · ${vm.label}` }}
                  </el-tag>
                </el-tooltip>
              </template>
            </div>
          </div>
        </div>
        <div v-if="loading" class="chat-msg ai"><div class="chat-bubble">思考中…</div></div>
      </div>
      <div class="suggest">
        <span v-if="ctxLabel" class="ctx-label">{{ ctxLabel }}</span>
        <el-tag
          v-for="s in suggestions" :key="s" size="small" class="sug-tag"
          @click="send(s)"
        >{{ s }}</el-tag>
      </div>
      <div class="chat-input">
        <el-input
          v-model="text" placeholder="对我说：帮我选品 / 重新定价 / 经营情况"
          :disabled="loading" @keyup.enter="send()"
        />
        <el-button type="primary" :disabled="!text.trim() || loading" @click="send()">发送</el-button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
/**
 * AI 副驾驶（UX-E #29，全局 FAB+抽屉；Workspace 外壳常显，工厂/控制台不装配）：
 * - 建议动作可执行（ACTION_META 命中 + 权限通过 → 确认对话框后跳转）；
 * - 不可执行项呈 WaitingExternal / NotConfigured 态（不造假入口）；
 * - 上下文感知：按当前路由 meta.domain 给建议问题并标注当前页面；
 * - 会话历史持久化后端无端点 → 仅标「待接入」，不放历史入口。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound } from '@element-plus/icons-vue'
import { ElMessageBox } from '../../shared/ui'
import { sendChat } from '../../api/domains/ai'
import { can } from '../../permissions/permissions'
import {
  AI_SESSION_PERSIST_NOTE, buildActionConfirm, contextLabel,
  contextualSuggestions, resolveCopilotActions,
} from './actions'

const open = ref(false)
const text = ref('')
const loading = ref(false)
const listRef = ref(null)

const route = useRoute()
const router = useRouter()

const suggestions = computed(() => contextualSuggestions(route.meta || {}))
const ctxLabel = computed(() => contextLabel(route.meta || {}))

const messages = ref([
  {
    role: 'ai',
    content: '您好！我是您的 AI 经营副驾驶。可以直接对我说：\n· 「帮我选品」— 输出机会商品 Top3\n'
      + '· 「看看市场趋势」— 刷新趋势解读\n· 「有什么风险」— 跑一轮经营巡检\n'
      + '· 「重新定价」— 全店动态定价\n· 「经营情况」— 近30天概况',
  },
])

/** 建议（AI 回复不再给出时补上当前页上下文提示，actions 为空则无动作条）。 */
async function send(preset) {
  const msg = (preset || text.value).trim()
  if (!msg || loading.value) return
  text.value = ''
  messages.value.push({ role: 'user', content: msg })
  loading.value = true
  await scrollBottom()
  try {
    const data = await sendChat(msg)
    messages.value.push({
      role: 'ai',
      content: data.reply || '（后端未返回回复内容）',
      actionVms: resolveCopilotActions(data.actions || [], { can }),
    })
  } catch (e) {
    messages.value.push({
      role: 'ai',
      content: `处理请求失败：${e?.response?.data?.detail || e?.message || '请稍后重试'}`,
    })
  } finally {
    loading.value = false
    await scrollBottom()
  }
}

/** 可执行动作：先确认对话框，再跳转到映射的真实页面。 */
async function runAction(vm) {
  try {
    await ElMessageBox.confirm(buildActionConfirm(vm), '执行 AI 建议动作', { type: 'info' })
  } catch {
    return // 用户取消
  }
  open.value = false
  router.push(vm.route)
}

async function scrollBottom() {
  await nextTick()
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
}

// 页面切换时补一条上下文分隔，让「上下文随页面变化」可见（不发请求）。
watch(() => route.fullPath, () => {
  if (!open.value || !route.meta?.title) return
  const last = messages.value.at(-1)
  if (last?.role === 'ai' && last.content === `已切换到「${route.meta.title}」。`) return
  messages.value.push({ role: 'ai', content: `已切换到「${route.meta.title}」。` })
})
</script>

<style scoped>
.copilot-fab {
  position: fixed;
  right: 28px;
  bottom: 32px;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--color-primary, #409eff);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.45);
  z-index: 2000;
  transition: transform 0.2s;
}
.copilot-fab:hover { transform: scale(1.08); }
.chat-list { height: calc(100% - 170px); overflow: auto; padding: 4px; }
.chat-msg { display: flex; margin-bottom: 10px; }
.chat-msg.user { justify-content: flex-end; }
.chat-bubble {
  max-width: 85%;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--color-fill-light, #f4f4f5);
  font-size: 13px;
  line-height: 1.6;
}
.chat-msg.user .chat-bubble { background: var(--color-primary-light, #d9ecff); }
.chat-text { white-space: pre-wrap; }
.chat-actions { margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap; }
.suggest { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.ctx-label { font-size: 12px; color: var(--color-text-secondary, #909399); }
.sug-tag { cursor: pointer; }
.chat-input { display: flex; gap: 8px; margin-top: 8px; }
.mb8 { margin-bottom: var(--space-2, 8px); }
</style>
