<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { Promotion, Delete } from '@element-plus/icons-vue'

const props = defineProps<{
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'send', text: string): void
  (e: 'clear'): void
}>()

const text = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 140) + 'px'
}

function handleInput() {
  autoResize()
}

function handleSend() {
  const value = text.value.trim()
  if (!value || props.loading) return
  emit('send', value)
  text.value = ''
  nextTick(() => autoResize())
}

function handleEnter(e: KeyboardEvent) {
  if (e.shiftKey) return
  e.preventDefault()
  handleSend()
}

function handleClear() {
  emit('clear')
}
</script>

<template>
  <div class="message-input">
    <div class="input-row">
      <el-button
        :icon="Delete"
        circle
        class="clear-btn"
        @click="handleClear"
        :disabled="loading"
        title="清空对话"
      />
      <div class="textarea-wrap">
        <textarea
          ref="textareaRef"
          v-model="text"
          class="custom-textarea"
          rows="1"
          placeholder="请输入您的投资问题"
          @input="handleInput"
          @keydown.enter="handleEnter"
          :disabled="loading"
        ></textarea>
      </div>
      <el-button
        type="primary"
        :icon="Promotion"
        :loading="loading"
        @click="handleSend"
        :disabled="!text.trim()"
        class="send-btn"
      >
        发送
      </el-button>
    </div>
    <div class="hint">按 Enter 发送，Shift + Enter 换行</div>
  </div>
</template>

<style scoped>
.message-input {
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
  padding: 16px 20px 12px;
  flex-shrink: 0;
}

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}

.textarea-wrap {
  flex: 1;
  min-width: 0;
}

.custom-textarea {
  width: 100%;
  resize: none;
  border: 1px solid var(--color-border);
  border-radius: 2px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.6;
  font-family: inherit;
  color: var(--color-text);
  background: var(--color-surface);
  transition: border-color 0.2s, box-shadow 0.2s;
  outline: none;
  max-height: 140px;
  overflow-y: auto;
}
.custom-textarea:focus {
  border-color: var(--color-primary-light);
  box-shadow: 0 0 0 2px rgba(26, 60, 43, 0.1);
  background: #fff;
}
.custom-textarea:disabled {
  background: #f1f5f9;
  cursor: not-allowed;
}

.send-btn {
  height: 42px;
  padding: 0 20px;
  font-weight: 600;
  border-radius: 2px;
}

.clear-btn {
  height: 42px;
  width: 42px;
  flex-shrink: 0;
  border-radius: 2px;
}

.hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
  text-align: right;
  font-family: var(--font-mono);
}

@media (max-width: 768px) {
  .message-input {
    padding: 10px 12px;
  }
  .send-btn {
    padding: 0 14px;
  }
  .send-btn :deep(span:not(.el-icon)) {
    display: none;
  }
}
</style>
