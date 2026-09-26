<script setup lang="ts">
import { ref, reactive, nextTick } from 'vue'
import { ChatDotRound } from '@element-plus/icons-vue'
import MessageList from './MessageList.vue'
import MessageInput from './MessageInput.vue'
import ParamDialog from './ParamDialog.vue'
import { chatStream, getRunStatus, stopChat } from '@/features/chat/api'
import type {
  ChatMessage,
  ChatRequest,
  ChatResponse,
  HistoryMessage,
  PendingInput,
} from '@/features/chat/types'

const props = defineProps<{
  customerId: string
  conversationId: string
}>()

const emit = defineEmits<{
  (e: 'profile-updated'): void
  (e: 'conversation-updated', conversationId: string): void
}>()

const messages = ref<ChatMessage[]>([])
const loading = ref(false)
const pendingInput = ref<PendingInput | null>(null)
const streamAbort = ref<AbortController | null>(null)
const userStopped = ref(false)

const PROCESSING_STATUSES = new Set(['processing', 'queued', 'running'])

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function waitForQuantJobs(
  ids: string[],
  signal: AbortSignal,
): Promise<{ response: string; conversation_id?: string; warnings?: string[] } | null> {
  const unique = [...new Set(ids.filter(Boolean))]
  if (!unique.length) return null
  const deadline = Date.now() + 180000
  while (Date.now() < deadline) {
    if (signal.aborted) return null
    let results: Awaited<ReturnType<typeof getRunStatus>>[]
    try {
      results = await Promise.all(unique.map((id) => getRunStatus(id)))
    } catch {
      await sleep(2000)
      continue
    }
    const ready = results.find((item) => item.run_status === 'completed' && item.response)
    if (ready) {
      return {
        response: ready.response || '',
        conversation_id: ready.conversation_id,
        warnings: ready.warnings || [],
      }
    }
    const stillGoing = results.some(
      (item) => PROCESSING_STATUSES.has(item.run_status)
        || (item.run_status === 'completed' && !item.response),
    )
    if (!stillGoing) return null
    await sleep(2000)
  }
  return null
}

function now(): string {
  return new Date().toISOString()
}

/** 从历史记录加载消息 */
function loadHistoryMessages(history: HistoryMessage[]) {
  messages.value = history.map((m) => ({
    role: (m.role === 'user' ? 'user' : 'assistant') as 'user' | 'assistant',
    content: m.content,
    timestamp: m.timestamp || now(),
    // 历史里保存的是**图表最小载荷**（analysis_results / technical_analysis），
    // 不是完整的 ChatResponse；只填这几个键即可让图表复原，
    // 其余字段留空（结论卡片等依赖当轮响应的块不会渲染）。
    data: m.metadata ? ({ ...m.metadata } as ChatResponse) : undefined,
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

/** 把弹窗答案渲染成用户气泡文本（后端只收到结构化 answers，此处仅为可读）。 */
function renderAnswers(pending: PendingInput, answers: Record<string, any>): string {
  const labels = new Map(pending.fields.map((f) => [f.name, f.label]))
  const parts = Object.entries(answers).map(([name, value]) => `${labels.get(name) || name}：${value}`)
  return parts.length ? parts.join('，') : '（已跳过）'
}

/** 发起一轮对话（新建消息气泡 + 流式接收 + 追问处理）。 */
async function runTurn(req: ChatRequest) {
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
  userStopped.value = false
  streamAbort.value = new AbortController()
  const signal = streamAbort.value.signal
  let streamFailed = false

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
      onDelta(event) {
        placeholder.content = (placeholder.content || '') + (event.content || '')
        placeholder.stage = ''
        const steps = placeholder.progressSteps || []
        if (steps.length) steps[steps.length - 1].status = 'completed'
      },
      onResponse(event) {
        placeholder.content = event.content
        placeholder.data = event.data
        if (event.data?.conversation_id) {
          emit('conversation-updated', event.data.conversation_id)
        }
        if (event.data?.user_profile && Object.keys(event.data.user_profile).length) {
          emit('profile-updated')
        }
        pendingInput.value = event.data?.pending_input || null
      },
      onError(errMsg) {
        streamFailed = true
        placeholder.content = `抱歉，处理过程中出现错误：${errMsg}`
        placeholder.loading = false
        placeholder.progressSteps = []
      },
    }, signal)

    const pendingIds = placeholder.data?.pending_task_ids || []
    const runStatus = placeholder.data?.run_status || ''
    if (
      !streamFailed
      && !userStopped.value
      && !signal.aborted
      && (pendingIds.length > 0 || PROCESSING_STATUSES.has(runStatus))
    ) {
      placeholder.stage = '正在计算技术指标…'
      placeholder.loading = true
      const recovered = await waitForQuantJobs(
        pendingIds.length ? pendingIds : [placeholder.data?.task_id || ''],
        signal,
      )
      if (recovered?.response) {
        placeholder.content = recovered.response
        if (placeholder.data) {
          placeholder.data = {
            ...placeholder.data,
            response: recovered.response,
            run_status: 'completed',
            pending_task_ids: [],
            warnings: recovered.warnings || placeholder.data.warnings,
            conversation_id: recovered.conversation_id || placeholder.data.conversation_id,
          }
        }
        if (recovered.conversation_id) {
          emit('conversation-updated', recovered.conversation_id)
        }
      } else if (!userStopped.value && pendingIds.length) {
        placeholder.content = placeholder.content
          || '技术指标仍在计算。请稍后刷新会话查看完整结论。'
      }
    }
  } catch (error: any) {
    placeholder.content = `抱歉，处理过程中出现错误：${error?.message || '未知错误'}`
  } finally {
    placeholder.loading = false
    placeholder.progressSteps = []
    loading.value = false
    streamAbort.value = null
  }
}

/** 处理发送 */
async function handleSend(text: string) {
  messages.value.push({
    role: 'user',
    content: text,
    timestamp: now(),
  })
  pendingInput.value = null
  await runTurn({
    message: text,
    customer_id: props.customerId,
    chat_history: buildHistory().filter((h) => h.content !== text),
    conversation_id: props.conversationId,
  })
}

async function handleStop() {
  userStopped.value = true
  streamAbort.value?.abort('user-stop')
  const conversationId = props.conversationId
    || messages.value.find((item) => item.data?.conversation_id)?.data?.conversation_id
    || ''
  if (!conversationId) return
  try {
    await stopChat(conversationId)
  } catch {
    // 停止是尽力而为：本地已中断流，后端失败不阻断 UI。
  }
}

/** 弹窗提交：把答案作为对缺参追问的恢复值续跑同一轮。 */
async function handleParamSubmit(answers: Record<string, any>) {
  const pending = pendingInput.value
  if (!pending) return
  messages.value.push({
    role: 'user',
    content: renderAnswers(pending, answers),
    timestamp: now(),
  })
  pendingInput.value = null
  await runTurn({
    message: pending.question,
    customer_id: props.customerId,
    chat_history: buildHistory(),
    conversation_id: props.conversationId,
    resume: true,
    answers,
  })
}

/** 弹窗取消：通知后端放弃挂起 run，避免下一轮被误当作回答。 */
async function handleParamCancel() {
  const pending = pendingInput.value
  if (!pending) return
  pendingInput.value = null
  messages.value.push({
    role: 'user',
    content: '（已取消本次补充）',
    timestamp: now(),
  })
  await runTurn({
    message: pending.question,
    customer_id: props.customerId,
    chat_history: buildHistory(),
    conversation_id: props.conversationId,
    resume: true,
    answers: { __cancel__: true },
  })
}

/** 清空对话 */
function handleClear() {
  messages.value = []
  pendingInput.value = null
}

function startNewConversation() {
  messages.value = []
  pendingInput.value = null
}

defineExpose({ loadHistoryMessages, startNewConversation })
</script>

<template>
  <div class="chat-window">
    <div class="chat-toolbar">
      <div class="toolbar-left">
        <span class="toolbar-index">01</span>
        <el-icon color="#1a3c2b" size="18"><ChatDotRound /></el-icon>
        <div class="toolbar-copy"><span class="toolbar-title">智能对话</span><small>ADVISOR SESSION</small></div>
      </div>
      <div class="toolbar-right">
        <span class="status-dot" :class="{ active: !loading }"></span>
        <span class="status-text">{{ loading ? '处理中' : '在线' }}</span>
      </div>
    </div>

    <MessageList :messages="messages" :loading="loading" />

    <MessageInput :loading="loading" @send="handleSend" @clear="handleClear" @stop="handleStop" />

    <ParamDialog
      :pending="pendingInput"
      @submit="handleParamSubmit"
      @cancel="handleParamCancel"
    />
  </div>
</template>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: rgba(247, 247, 245, .72);
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
.toolbar-index { color: var(--color-text-muted); font: 10px/1 var(--font-mono); }
.toolbar-copy { display: flex; flex-direction: column; gap: 3px; }
.toolbar-copy small { color: var(--color-text-secondary); font: 11px/1 var(--font-mono); letter-spacing: .08em; }
.toolbar-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--color-border);
  padding: 5px 10px;
  font: 10px/1 var(--font-mono);
  letter-spacing: .08em;
  color: var(--color-text-secondary);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 0;
  background: #cbd5e1;
  transition: background 0.3s;
}
.status-dot.active {
  background: var(--color-success);
}
</style>
