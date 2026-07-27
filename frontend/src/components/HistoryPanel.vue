<script setup lang="ts">
import { ref } from 'vue'
import { ChatLineRound, Refresh, Plus, ArrowLeft, User, Headset, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createConversation, deleteConversation, getConversationMessages, getConversations } from '@/api/chat'
import type { Conversation, HistoryMessage } from '@/types'

const props = defineProps<{ customerId: string; activeConversationId: string }>()
const emit = defineEmits<{
  (e: 'new-conversation', conversationId: string): void
  (e: 'select-conversation', conversationId: string, messages: HistoryMessage[]): void
  (e: 'conversation-deleted', conversationId: string): void
}>()

const visible = ref(false)
const loading = ref(false)
const conversations = ref<Conversation[]>([])
const selected = ref<Conversation | null>(null)
const messages = ref<HistoryMessage[]>([])

function formatDate(value?: string): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

async function loadConversations() {
  loading.value = true
  try {
    conversations.value = (await getConversations(props.customerId)).conversations
  } catch {
    ElMessage.error('历史对话加载失败')
  } finally {
    loading.value = false
  }
}

async function openConversation(item: Conversation) {
  loading.value = true
  try {
    const result = await getConversationMessages(props.customerId, item.conversation_id)
    selected.value = item
    messages.value = result.messages
  } catch {
    ElMessage.error('对话内容加载失败')
  } finally {
    loading.value = false
  }
}

function useConversation() {
  if (!selected.value) return
  emit('select-conversation', selected.value.conversation_id, messages.value)
  visible.value = false
}

async function handleNewConversation() {
  loading.value = true
  try {
    const item = await createConversation(props.customerId)
    emit('new-conversation', item.conversation_id)
    selected.value = null
    messages.value = []
    visible.value = false
  } catch {
    ElMessage.error('新对话创建失败')
  } finally {
    loading.value = false
  }
}

async function handleDelete(item: Conversation) {
  try {
    await ElMessageBox.confirm(
      `确定删除“${item.title}”吗？该对话的全部消息将一并删除。`,
      '删除历史对话',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  loading.value = true
  try {
    await deleteConversation(props.customerId, item.conversation_id)
    conversations.value = conversations.value.filter(
      conversation => conversation.conversation_id !== item.conversation_id,
    )
    emit('conversation-deleted', item.conversation_id)
    ElMessage.success('历史对话已删除')
  } catch {
    ElMessage.error('历史对话删除失败')
  } finally {
    loading.value = false
  }
}

async function openHistory() {
  selected.value = null
  visible.value = true
  await loadConversations()
}
</script>

<template>
  <el-card class="history-panel" shadow="never">
    <button class="history-entry" type="button" @click="openHistory">
      <span class="entry-label"><el-icon><ChatLineRound /></el-icon>历史对话</span>
      <span class="entry-action">查看</span>
    </button>
  </el-card>

  <el-drawer v-model="visible" direction="rtl" size="min(520px, 92vw)" append-to-body>
    <template #header>
      <div class="drawer-header">
        <div class="drawer-title">
          <el-button v-if="selected" :icon="ArrowLeft" text circle @click="selected = null" />
          <el-icon v-else><ChatLineRound /></el-icon>
          <span>{{ selected?.title || '历史对话' }}</span>
        </div>
        <el-button v-if="!selected" :icon="Plus" type="primary" @click="handleNewConversation">
          新对话
        </el-button>
        <el-button v-else type="primary" @click="useConversation">继续此对话</el-button>
      </div>
    </template>

    <div v-loading="loading" class="drawer-body">
      <template v-if="!selected">
        <div class="list-tools">
          <span>共 {{ conversations.length }} 个对话</span>
          <el-button :icon="Refresh" text :loading="loading" @click="loadConversations">刷新</el-button>
        </div>
        <el-empty v-if="!loading && !conversations.length" description="暂无历史对话" />
        <div
          v-for="item in conversations"
          :key="item.conversation_id"
          class="conversation-item"
          :class="{ active: item.conversation_id === activeConversationId }"
          role="button"
          tabindex="0"
          @click="openConversation(item)"
          @keydown.enter="openConversation(item)"
        >
          <span class="conversation-main">
            <strong>{{ item.title }}</strong>
            <small>{{ item.message_count }} 条消息</small>
          </span>
          <span class="conversation-actions">
            <span class="view-link">查看</span>
            <el-button
              class="delete-button"
              :icon="Delete"
              text
              circle
              type="danger"
              aria-label="删除对话"
              @click.stop="handleDelete(item)"
            />
          </span>
        </div>
      </template>

      <template v-else>
        <el-empty v-if="!loading && !messages.length" description="该对话暂无消息" />
        <article v-for="(message, index) in messages" :key="index" class="history-message" :class="message.role">
          <div class="message-meta">
            <span><el-icon><User v-if="message.role === 'user'" /><Headset v-else /></el-icon>{{ message.role === 'user' ? '我' : '智能投顾' }}</span>
            <time>{{ formatDate(message.timestamp) }}</time>
          </div>
          <div class="message-content" v-text="message.content"></div>
        </article>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.history-panel { border: none; border-radius: var(--radius-md); box-shadow: var(--shadow-card); }
.history-panel :deep(.el-card__body) { padding: 0; }
.history-entry { width: 100%; padding: 15px 16px; border: 0; background: transparent; display: flex; justify-content: space-between; cursor: pointer; color: var(--color-text); }
.history-entry:hover { background: var(--color-primary-soft); }
.entry-label, .drawer-title, .message-meta span { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; }
.entry-label .el-icon, .drawer-title > .el-icon { color: var(--color-primary); }
.entry-action, .view-link { color: var(--color-primary-light); font-size: 13px; }
.drawer-header, .list-tools { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.drawer-title { min-width: 0; font-size: 17px; color: var(--color-text); }
.drawer-title span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drawer-body { min-height: 180px; display: flex; flex-direction: column; gap: 12px; }
.list-tools { color: var(--color-text-muted); font-size: 12px; }
.conversation-item { border: 1px solid var(--color-border); border-radius: 10px; background: var(--color-surface); padding: 13px 14px; display: flex; align-items: center; justify-content: space-between; text-align: left; cursor: pointer; }
.conversation-item:hover, .conversation-item.active { border-color: var(--color-primary-light); background: var(--color-primary-soft); }
.conversation-main { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.conversation-main strong { color: var(--color-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conversation-main small { color: var(--color-text-muted); }
.conversation-actions { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; }
.delete-button { opacity: 0.72; }
.delete-button:hover { opacity: 1; }
.history-message { padding: 12px 14px; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-assistant-bubble); }
.history-message.user { margin-left: 32px; background: var(--color-primary-soft); }
.history-message.assistant { margin-right: 32px; }
.message-meta { display: flex; justify-content: space-between; margin-bottom: 8px; color: var(--color-text-muted); font-size: 12px; }
.message-content { white-space: pre-wrap; overflow-wrap: anywhere; color: var(--color-text); line-height: 1.65; font-size: 14px; }
</style>
