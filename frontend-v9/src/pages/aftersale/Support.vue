<template>
  <div class="page">
    <PageHeader title="智能客服" subtitle="会话按状态分组 · AI 建议可编辑后发送 · 关闭后不可再回复">
      <template #actions>
        <el-button v-if="writable" type="primary" @click="newDialog = true">新建会话</el-button>
      </template>
    </PageHeader>

    <el-row :gutter="16">
      <el-col :span="8">
        <!-- 会话按状态分组 -->
        <FormSection title="会话列表" description="处理中在前，已关闭置底">
          <div v-loading="loading" class="conv-list">
            <template v-for="group in grouped" :key="group.key">
              <div class="conv-group">{{ group.label }}（{{ group.items.length }}）</div>
              <div
                v-for="c in group.items" :key="c.id"
                class="conv-item" :class="{ active: current.id === c.id, closed: c.status === 'closed' }"
                @click="open(c)"
              >
                <div class="conv-item__row">
                  <b>{{ c.buyer_name }}</b>
                  <el-tag size="small">{{ c.platform }}</el-tag>
                </div>
                <div class="conv-item__last">{{ c.last_message || '（无消息）' }}</div>
                <div class="conv-item__time">{{ c.last_message_at }}</div>
              </div>
            </template>
            <EmptyState v-if="!conversations.length && !loading" reason="NO_DATA" hint="暂无会话" />
          </div>
        </FormSection>
      </el-col>
      <el-col :span="16">
        <FormSection :title="current.buyer_name ? `${current.buyer_name}（${current.platform}）` : '消息'">
          <div ref="msgList" class="msg-list">
            <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
              <div class="msg-bubble">
                {{ m.content }}
                <div class="msg-meta">
                  <el-tag v-if="m.intent && m.intent !== 'other'" size="small" type="info">{{ m.intent }}</el-tag>
                  <span v-if="m.auto"> · AI自动</span> · {{ m.created_at }}
                </div>
              </div>
            </div>
            <EmptyState v-if="!messages.length && current.id" reason="NO_DATA" hint="暂无消息" />
            <EmptyState v-if="!current.id" reason="NO_MATCH" hint="左侧选择一个会话" />
          </div>
          <div class="reply-bar">
            <el-input
              v-model="replyText" placeholder="输入回复内容（可先引用 AI 建议再编辑）…"
              :disabled="!current.id || closed" @keyup.enter="send"
            />
            <el-button
              :disabled="!current.id" :loading="aiLoading" @click="aiSuggest"
            >
              AI 建议
            </el-button>
            <el-button type="primary" :disabled="!current.id || closed || !replyText" @click="send">
              发送
            </el-button>
            <el-button v-if="writable && current.id && !closed" @click="closeConv">关闭会话</el-button>
          </div>
          <el-alert
            v-if="closed" type="info" :closable="false" class="mt8"
            title="会话已关闭，不可再回复"
          />
          <el-alert
            v-if="aiHint" type="info" :closable="false" class="mt8"
            :title="aiHint" description="AI 建议已真实落库为 AI 消息（后端无仅草稿端点）；已引用到输入框，可编辑后作为人工回复发送。"
          />
        </FormSection>
      </el-col>
    </el-row>

    <el-dialog v-model="newDialog" title="新建客服会话" width="480px">
      <el-form label-width="90px">
        <el-form-item label="平台">
          <el-select v-model="form.platform">
            <el-option v-for="p in PLATFORMS" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="买家名"><el-input v-model="form.buyer_name" /></el-form-item>
        <el-form-item label="首条消息">
          <el-input v-model="form.content" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newDialog = false">取消</el-button>
        <el-button type="primary" @click="createConv">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from '../../shared/ui'
import PageHeader from '../../components/PageHeader.vue'
import FormSection from '../../components/FormSection.vue'
import EmptyState from '../../components/EmptyState.vue'
import { can } from '../../permissions/permissions'
import {
  fetchConversations, fetchConversation, createConversation, reply,
  requestAutoReply, closeConversation,
} from '../../api/domains/support'

const PLATFORMS = ['tiktok', 'shopee', 'amazon', 'ebay', 'walmart', 'lazada', 'aliexpress', 'temu', 'shopify', 'mercadolibre', 'shein']

const writable = can('order:write')

const conversations = ref([])
const messages = ref([])
const current = ref({})
const loading = ref(false)
const aiLoading = ref(false)
const aiHint = ref('')
const replyText = ref('')
const msgList = ref(null)
const newDialog = ref(false)
const form = reactive({ platform: 'shopee', buyer_name: '', content: '' })

const closed = computed(() => current.value.status === 'closed')

/** 会话状态分组：处理中（open）在前，已关闭（closed）置底。 */
const grouped = computed(() => [
  { key: 'open', label: '处理中', items: conversations.value.filter((c) => c.status !== 'closed') },
  { key: 'closed', label: '已关闭', items: conversations.value.filter((c) => c.status === 'closed') },
])

async function loadConv() {
  loading.value = true
  try {
    const data = await fetchConversations({})
    conversations.value = data.items || []
  } finally {
    loading.value = false
  }
}

async function open(c) {
  current.value = c
  aiHint.value = ''
  const data = await fetchConversation(c.id)
  messages.value = data.messages || []
  await nextTick()
  if (msgList.value) msgList.value.scrollTop = msgList.value.scrollHeight
}

async function send() {
  if (!replyText.value.trim() || closed.value) return
  await reply(current.value.id, replyText.value)
  replyText.value = ''
  await open(current.value)
  loadConv()
}

/**
 * AI 建议：后端 auto_reply 为真实落库端点（无仅草稿端点），调用即产生一条
 * AI 消息；回执文本引用到输入框，客服可编辑后作为人工回复发送（验收 #19-①）。
 */
async function aiSuggest() {
  aiLoading.value = true
  try {
    const data = await requestAutoReply(current.value.id)
    aiHint.value = `AI 已按意图「${data.intent || 'other'}」给出建议`
    replyText.value = data.reply || ''
    await open(current.value)
  } finally {
    aiLoading.value = false
  }
}

async function closeConv() {
  await closeConversation(current.value.id)
  ElMessage.success('会话已关闭')
  loadConv()
}

async function createConv() {
  if (!form.buyer_name || !form.content) return ElMessage.warning('请填写买家名和首条消息')
  await createConversation(form)
  ElMessage.success('会话已创建')
  newDialog.value = false
  Object.assign(form, { platform: 'shopee', buyer_name: '', content: '' })
  loadConv()
}

onMounted(loadConv)
</script>

<style scoped>
.conv-list {
  max-height: 560px;
  overflow: auto;
}
.conv-group {
  margin: var(--space-2) 0 var(--space-1);
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}
.conv-item {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  margin-bottom: 6px;
  border: 1px solid transparent;
}
.conv-item:hover {
  background: var(--color-bg);
}
.conv-item.active {
  background: var(--color-primary-bg);
  border-color: var(--color-border-light);
}
.conv-item.closed {
  opacity: 0.65;
}
.conv-item__row {
  display: flex;
  justify-content: space-between;
}
.conv-item__last {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-item__time {
  color: var(--color-text-disabled);
  font-size: var(--font-size-xs);
  margin-top: 2px;
}
.msg-list {
  height: 420px;
  overflow: auto;
  padding: 8px;
}
.msg {
  display: flex;
  margin-bottom: 10px;
}
.msg.buyer {
  justify-content: flex-start;
}
.msg.agent, .msg.operator {
  justify-content: flex-end;
}
.msg-bubble {
  max-width: 70%;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  background: var(--color-info-bg);
  font-size: var(--font-size-sm);
}
.msg.agent .msg-bubble, .msg.operator .msg-bubble {
  background: var(--color-primary-bg);
}
.msg-meta {
  color: var(--color-text-disabled);
  font-size: var(--font-size-xs);
  margin-top: 4px;
}
.reply-bar {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
.mt8 {
  margin-top: var(--space-2);
}
</style>
