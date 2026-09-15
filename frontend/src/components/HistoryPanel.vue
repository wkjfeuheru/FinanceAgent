<script setup lang="ts">
import { ref, watch } from 'vue'
import { ChatLineRound, Refresh, Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createConversation, deleteConversation, getConversationMessages, getConversations } from '@/api/chat'
import type { Conversation, HistoryMessage } from '@/types'

const props = defineProps<{ customerId: string; activeConversationId: string }>()
const emit = defineEmits<{
  (e: 'new-conversation', conversationId: string): void
  (e: 'select-conversation', conversationId: string, messages: HistoryMessage[]): void
  (e: 'conversation-deleted', conversationId: string): void
}>()

const loading = ref(false)
const conversations = ref<Conversation[]>([])

function formatDate(value?: string): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function titleOf(item: Conversation): string {
  return item.title?.trim() || '未命名对话'
}

async function loadConversations() {
  if (!props.customerId) return
  loading.value = true
  try {
    conversations.value = (await getConversations(props.customerId)).conversations
  } catch {
    ElMessage.error('历史对话加载失败')
  } finally {
    loading.value = false
  }
}

async function handleNewConversation() {
  if (!props.customerId) return
  loading.value = true
  try {
    const item = await createConversation(props.customerId)
    conversations.value = [item, ...conversations.value]
    emit('new-conversation', item.conversation_id)
  } catch {
    ElMessage.error('新对话创建失败')
  } finally {
    loading.value = false
  }
}

/** 选中会话：拉取消息并交给对话区展示；列表中高亮当前会话。 */
async function openConversation(item: Conversation) {
  if (item.conversation_id === props.activeConversationId) return
  loading.value = true
  try {
    const result = await getConversationMessages(props.customerId, item.conversation_id)
    emit('select-conversation', item.conversation_id, result.messages)
  } catch {
    ElMessage.error('对话内容加载失败')
  } finally {
    loading.value = false
  }
}

async function handleDelete(item: Conversation) {
  try {
    await ElMessageBox.confirm(
      `确定删除“${titleOf(item)}”吗？该对话的全部消息将一并删除。`,
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

// 首条消息发送后 App 会更新 activeConversationId：此时列表需要刷出标题与消息数。
// 仅在 id 变化时刷新，避免每次渲染都请求。
watch(() => props.activeConversationId, (next, prev) => {
  if (next && next !== prev) loadConversations()
})

// 客户切换（登录/切换账号）时重新加载。
watch(() => props.customerId, (next) => {
  if (next) loadConversations()
  else conversations.value = []
}, { immediate: true })
</script>

<template>
  <el-card class="history-panel" shadow="never" v-loading="loading">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">会话</p>
        <h2><el-icon><ChatLineRound /></el-icon>历史对话</h2>
      </div>
      <span class="conversation-count">{{ conversations.length }}</span>
    </div>

    <div class="panel-tools">
      <el-button type="primary" size="small" :icon="Plus" @click="handleNewConversation">新建对话</el-button>
      <el-button size="small" text :icon="Refresh" :loading="loading" @click="loadConversations">刷新</el-button>
    </div>

    <el-empty
      v-if="!loading && !conversations.length"
      :image-size="48"
      description="暂无历史对话，点击“新建对话”开始"
    />

    <ul v-else class="conversation-list">
      <li
        v-for="item in conversations"
        :key="item.conversation_id"
        class="conversation-item"
        :class="{ active: item.conversation_id === activeConversationId }"
      >
        <button
          type="button"
          class="conversation-main"
          :aria-current="item.conversation_id === activeConversationId"
          @click="openConversation(item)"
        >
          <strong>{{ titleOf(item) }}</strong>
          <small>{{ item.message_count }} 条消息 · {{ formatDate(item.updated_at) }}</small>
        </button>
        <el-button
          class="delete-button"
          :icon="Delete"
          text
          circle
          type="danger"
          aria-label="删除对话"
          @click.stop="handleDelete(item)"
        />
      </li>
    </ul>
  </el-card>
</template>

<style scoped>
.history-panel { border: 1px solid var(--color-border); border-radius: 0; box-shadow: none; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.eyebrow { margin: 0 0 5px; color: var(--color-text-muted); font: 10px/1 var(--font-mono); letter-spacing: .08em; }
.panel-heading h2 { margin: 0; display: inline-flex; align-items: center; gap: 8px; color: var(--color-text); font-size: 15px; }
.panel-heading h2 .el-icon { color: var(--color-primary); }
.conversation-count { display: grid; place-items: center; min-width: 24px; height: 24px; background: var(--color-primary-soft); color: var(--color-primary); font: 12px/1 var(--font-mono); }
.panel-tools { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 12px 0; }
.conversation-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; max-height: 340px; overflow-y: auto; }
.conversation-item { display: flex; align-items: center; gap: 6px; border: 1px solid var(--color-border); background: var(--color-surface); padding: 8px 10px; }
.conversation-item:hover, .conversation-item.active { border-color: var(--color-primary-light); background: var(--color-primary-soft); }
.conversation-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; border: 0; background: transparent; padding: 0; text-align: left; cursor: pointer; color: var(--color-text); }
.conversation-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.conversation-main small { color: var(--color-text-muted); font-size: 11px; }
.delete-button { flex-shrink: 0; opacity: 0; transition: opacity .16s ease; }
.conversation-item:hover .delete-button, .delete-button:focus-visible { opacity: 1; }

@media (hover: none), (max-width: 768px) {
  .delete-button { opacity: 1; }
}
</style>
