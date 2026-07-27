<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { User, Headset, Loading } from '@element-plus/icons-vue'
import type { ChatMessage } from '@/types'

const props = defineProps<{
  messages: ChatMessage[]
  loading: boolean
}>()

const listRef = ref<HTMLDivElement | null>(null)

function scrollToBottom() {
  nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

watch(
  () => props.messages.length,
  () => scrollToBottom(),
  { flush: 'post' },
)
// 监听最后一条消息内容变化（流式更新滚动）
watch(
  () => props.messages.at(-1)?.content,
  () => scrollToBottom(),
  { flush: 'post' },
)

function formatTime(ts?: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const isEmpty = computed(
  () => props.messages.length === 0 && !props.loading,
)
</script>

<template>
  <div class="message-list" ref="listRef">
    <el-empty v-if="isEmpty" description="暂无对话，开始向投顾提问吧" :image-size="120">
      <template #description>
        <p class="empty-tip">暂无对话，开始向投顾提问吧</p>
        <p class="empty-sub">例如：帮我分析xxx股票的基本面，或制定稳健的资产配置方案</p>
      </template>
    </el-empty>

    <template v-else>
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        class="message-item"
        :class="msg.role"
      >
        <el-avatar
          :size="36"
          :icon="msg.role === 'user' ? User : Headset"
          class="avatar"
          :class="msg.role === 'user' ? 'avatar-user' : 'avatar-assistant'"
        />
        <div class="bubble-wrap">
          <div class="meta">
            <span class="role-name">
              {{ msg.role === 'user' ? '我' : '智能投顾' }}
            </span>
            <span class="time">{{ formatTime(msg.timestamp) }}</span>
          </div>
          <div class="bubble markdown-body">
            <div v-if="msg.loading && !msg.content && msg.progressSteps?.length" class="progress-panel">
              <div class="progress-title">正在分析</div>
              <div
                v-for="step in msg.progressSteps"
                :key="step.stage"
                class="progress-step"
                :class="step.status"
              >
                <span class="progress-marker">
                  <span v-if="step.status === 'completed'">✓</span>
                  <el-icon v-else class="spin"><Loading /></el-icon>
                </span>
                <span>{{ step.message }}</span>
              </div>
            </div>
            <template v-else-if="msg.loading && !msg.content">
              <span class="typing">
                <el-icon class="typing-dot"><Loading /></el-icon>
                正在分析...
              </span>
            </template>
            <template v-else>
              <div v-if="msg.stage && msg.loading" class="stage-tip">
                <el-icon class="spin"><Loading /></el-icon>
                <span>{{ msg.stage }}</span>
              </div>
              <div v-text="msg.content"></div>
            </template>
          </div>
          <!-- 附加数据卡片 -->
          <div
            v-if="msg.data?.allocation_result && Object.keys(msg.data.allocation_result).length"
            class="extra-data"
          >
            <div
              v-if="msg.data.allocation_result && Object.keys(msg.data.allocation_result).length"
              class="alloc-summary"
            >
              <span class="alloc-item">
                预期收益：<b>{{ (msg.data.allocation_result.expected_return * 100).toFixed(2) }}%</b>
              </span>
              <span class="alloc-item">
                预期波动：<b>{{ (msg.data.allocation_result.expected_volatility * 100).toFixed(2) }}%</b>
              </span>
              <span class="alloc-item">
                夏普比率：<b>{{ msg.data.allocation_result.sharpe_ratio.toFixed(2) }}</b>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 全局加载占位（首次进入无消息时） -->
      <div v-if="loading && messages.length === 0" class="message-item assistant">
        <el-avatar :size="36" :icon="Headset" class="avatar avatar-assistant" />
        <div class="bubble-wrap">
          <div class="meta"><span class="role-name">智能投顾</span></div>
          <div class="bubble">
            <span class="typing">
              <el-icon class="typing-dot"><Loading /></el-icon>
              正在分析...
            </span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 28px clamp(18px, 4vw, 48px);
  display: flex;
  flex-direction: column;
  gap: 24px;
  scroll-behavior: smooth;
}

.message-item {
  display: flex;
  gap: 10px;
  max-width: 100%;
  align-items: flex-start;
}
.message-item.user {
  flex-direction: row-reverse;
}

.avatar {
  flex-shrink: 0;
}
.avatar-user {
  background: var(--color-primary);
  color: #fff;
}
.avatar-assistant {
  background: var(--color-primary);
  color: #fff;
}

.bubble-wrap {
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 78%;
}
.message-item.user .bubble-wrap {
  align-items: flex-end;
}

.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}
.message-item.user .meta {
  flex-direction: row-reverse;
}

.role-name {
  font-weight: 600;
  color: var(--color-text-secondary);
}

.bubble {
  padding: 14px 16px;
  border-radius: 0;
  background: var(--color-assistant-bubble);
  color: var(--color-text);
  box-shadow: none;
  border: 1px solid var(--color-border);
  word-break: break-word;
  white-space: pre-wrap;
}
.message-item.user .bubble {
  background: var(--color-user-bubble);
  color: #fff;
  border-color: var(--color-primary);
}
.message-item.assistant .bubble {
  border-left: 3px solid var(--color-primary);
}

.typing {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-secondary);
  font-size: 14px;
}
.progress-panel {
  min-width: 260px;
  border-left: 1px solid var(--color-border);
  padding-left: 14px;
}
.progress-title {
  font-weight: 700;
  margin-bottom: 8px;
}
.progress-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.progress-step.active {
  color: var(--color-primary);
}
.progress-step.completed {
  color: var(--color-success);
}
.progress-marker {
  width: 18px;
  display: inline-flex;
  justify-content: center;
  flex-shrink: 0;
}
.progress-marker > span { font-family: var(--font-mono); }
.typing-dot {
  animation: pulse 1.2s ease-in-out infinite;
}

.stage-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-primary-light);
  background: var(--color-primary-soft);
  padding: 4px 10px;
  border-radius: 0;
  border: 1px solid var(--color-border);
  margin-bottom: 8px;
  width: fit-content;
}
.spin {
  animation: spin 1s linear infinite;
}

.extra-data {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 0;
  font-size: 12px;
  color: var(--color-text-secondary);
  width: fit-content;
  max-width: 100%;
}
.message-item.user .extra-data {
  display: none;
}

.extra-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.task-plan {
  margin-top: 6px;
}
.plan-title {
  font-weight: 600;
  margin-bottom: 2px;
  color: var(--color-text);
}
.task-plan ol {
  margin: 0;
  padding-left: 18px;
}
.task-plan li {
  margin: 2px 0;
}

.alloc-summary {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
}
.alloc-item {
  color: var(--color-text-secondary);
}
.alloc-item b {
  color: var(--color-primary);
  font-family: var(--font-mono);
}

.empty-tip {
  color: var(--color-text-secondary);
  font-size: 14px;
  margin: 0;
}
.empty-sub {
  color: var(--color-text-muted);
  font-size: 12px;
  margin: 4px 0 0;
}

@keyframes pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .message-list {
    padding: 14px 12px;
  }
  .bubble-wrap {
    max-width: 85%;
  }
}
</style>
