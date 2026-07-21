<script setup lang="ts">
import { ref, reactive, nextTick } from 'vue'
import { ChatDotRound } from '@element-plus/icons-vue'
import MessageList from './MessageList.vue'
import MessageInput from './MessageInput.vue'
import { chatStream } from '@/api/chat'
import type { ChatMessage, ChatRequest, HistoryMessage } from '@/types'

const props = defineProps<{
  customerId: string
  conversationId: string
}>()

const emit = defineEmits<{
  (e: 'allocation-update', weights: Record<string, number>): void
  (e: 'profile-updated'): void
  (e: 'conversation-updated', conversationId: string): void
}>()

const messages = ref<ChatMessage[]>([])
const loading = ref(false)

function now(): string {
  return new Date().toISOString()
}

/** 从历史记录加载消息 */
function loadHistoryMessages(history: HistoryMessage[]) {
  messages.value = history.map((m) => ({
    role: (m.role === 'user' ? 'user' : 'assistant') as 'user' | 'assistant',
    content: m.content,
    timestamp: m.timestamp || now(),
  }))
  nextTick(() => {
    const el = document.querySelector('.message-list')
    if (el) el.scrollTop = el.scrollHeight
  })
}

/** 构建发送给后端的对话历史 */
function buildHistory(): Array<{ role: string; content: string }> {
  return messages.value
    .filter((m) => !m.loading && m.content)
    .slice(-10)
    .map((m) => ({ role: m.role, content: m.content }))
}

/** 处理发送 */
async function handleSend(text: string) {
  // 追加用户消息
  messages.value.push({
    role: 'user',
    content: text,
    timestamp: now(),
  })

  // 追加占位助手消息
  const placeholder = reactive<ChatMessage>({
    role: 'assistant',
    content: '',
    timestamp: now(),
    loading: true,
    stage: '',
    progressSteps: [],
  })
  messages.value.push(placeholder)

  loading.value = true

  const req: ChatRequest = {
    message: text,
    customer_id: props.customerId,
    chat_history: buildHistory().filter((h) => h.content !== text),
    conversation_id: props.conversationId,
  }

  try {
    await chatStream(req, {
      onStage(event) {
        placeholder.stage = event.message || event.stage
        const steps = placeholder.progressSteps || (placeholder.progressSteps = [])
        const previous = steps.at(-1)
        if (previous && previous.stage !== event.stage) previous.status = 'completed'
        const existing = steps.find((step) => step.stage === event.stage)
        if (existing) {
          existing.message = event.message || event.stage
          existing.status = 'active'
        } else {
          steps.push({
            stage: event.stage,
            message: event.message || event.stage,
            status: 'active',
          })
        }
      },
      onResponse(event) {
        placeholder.content = event.content
        placeholder.data = event.data
        placeholder.loading = false
        placeholder.progressSteps = []
        if (event.data?.conversation_id) {
          emit('conversation-updated', event.data.conversation_id)
        }
        const weights = event.data?.allocation_result?.weights
        if (weights && Object.keys(weights).length) {
          emit('allocation-update', weights)
        }
        if (event.data?.user_profile && Object.keys(event.data.user_profile).length) {
          emit('profile-updated')
        }
      },
      onError(errMsg) {
        placeholder.content = `抱歉，处理过程中出现错误：${errMsg}`
        placeholder.loading = false
        placeholder.progressSteps = []
      },
    })
  } catch (error: any) {
    placeholder.content = `抱歉，处理过程中出现错误：${error?.message || '未知错误'}`
  } finally {
    placeholder.loading = false
    loading.value = false
  }
}

/** 清空对话 */
function handleClear() {
  messages.value = []
}

function startNewConversation() {
  messages.value = []
}

defineExpose({ loadHistoryMessages, startNewConversation })
</script>

<template>
  <div class="chat-window">
    <div class="chat-toolbar">
      <div class="toolbar-left">
        <el-icon color="#1e3a8a" size="18"><ChatDotRound /></el-icon>
        <span class="toolbar-title">智能对话</span>
      </div>
      <div class="toolbar-right">
        <span class="status-dot" :class="{ active: !loading }"></span>
        <span class="status-text">{{ loading ? '处理中' : '在线' }}</span>
      </div>
    </div>

    <MessageList :messages="messages" :loading="loading" />

    <MessageInput :loading="loading" @send="handleSend" @clear="handleClear" />
  </div>
</template>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--color-bg);
  min-height: 0;
}

.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toolbar-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #cbd5e1;
  transition: background 0.3s;
}
.status-dot.active {
  background: var(--color-success);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.15);
}
</style>
