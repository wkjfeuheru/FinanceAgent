<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Menu } from '@element-plus/icons-vue'
import ChatWindow from '@/components/ChatWindow.vue'
import ProfilePanel from '@/components/ProfilePanel.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'
import { getProfile, getConversationMessages, getConversations } from '@/api/chat'
import type { ProfileResponse, HistoryMessage, UserInfo } from '@/types'

// 名称供 App.vue 的 <keep-alive include> 匹配：切页不丢当前会话与草稿。
defineOptions({ name: 'ChatView' })

const props = defineProps<{ currentUser: UserInfo }>()

const profile = ref<ProfileResponse | null>(null)
const profileLoading = ref(true)
const sidebarOpen = ref(false)
const currentConversationId = ref('')

const chatRef = ref<InstanceType<typeof ChatWindow> | null>(null)

const customerId = computed(() => props.currentUser?.customer_id || '')

async function loadProfile() {
  if (!customerId.value) return
  profileLoading.value = true
  try {
    profile.value = await getProfile(customerId.value)
  } catch {
    profile.value = null
  } finally {
    profileLoading.value = false
  }
}

async function loadLatestConversation(): Promise<HistoryMessage[]> {
  if (!customerId.value) return []
  try {
    const list = await getConversations(customerId.value)
    const latest = list.conversations[0]
    if (!latest) return []
    currentConversationId.value = latest.conversation_id
    return (await getConversationMessages(customerId.value, latest.conversation_id)).messages
  } catch {
    return []
  }
}

function handleNewConversation(conversationId: string) {
  currentConversationId.value = conversationId
  chatRef.value?.startNewConversation()
}

function handleSelectConversation(conversationId: string, messages: HistoryMessage[]) {
  currentConversationId.value = conversationId
  chatRef.value?.loadHistoryMessages(messages)
}

function handleConversationDeleted(conversationId: string) {
  if (currentConversationId.value !== conversationId) return
  currentConversationId.value = ''
  chatRef.value?.startNewConversation()
}

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
}

/** 供父组件在登录后触发首屏加载。 */
async function initialize() {
  await loadProfile()
  const history = await loadLatestConversation()
  if (chatRef.value && history.length) {
    chatRef.value.loadHistoryMessages(history)
  }
}

defineExpose({ initialize })

onMounted(() => {
  if (customerId.value) initialize()
})
</script>

<template>
  <div class="chat-layout">
    <main class="app-main">
      <!-- 聊天区域 70% -->
      <section class="chat-area">
        <button
          class="menu-toggle"
          aria-label="切换侧边栏"
          :aria-expanded="sidebarOpen"
          aria-controls="advisor-sidebar"
          @click="toggleSidebar"
        >
          <el-icon size="22"><Menu /></el-icon>
        </button>
        <ChatWindow
          ref="chatRef"
          :customer-id="customerId"
          :conversation-id="currentConversationId"
          @conversation-updated="currentConversationId = $event"
          @profile-updated="loadProfile"
        />
      </section>

      <!-- 侧边栏 30% -->
      <div class="sidebar-backdrop" :class="{ open: sidebarOpen }" @click="toggleSidebar"></div>
      <aside id="advisor-sidebar" class="sidebar-area" :class="{ open: sidebarOpen }">
        <div class="sidebar-content">
          <ProfilePanel :profile="profile" :loading="profileLoading" />
          <HistoryPanel
            :customer-id="customerId"
            :active-conversation-id="currentConversationId"
            @new-conversation="handleNewConversation"
            @select-conversation="handleSelectConversation"
            @conversation-deleted="handleConversationDeleted"
          />
        </div>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg);
}

.app-main {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}

.chat-area {
  flex: 0 0 70%;
  max-width: 70%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--color-border);
  position: relative;
}

.sidebar-area {
  flex: 0 0 30%;
  max-width: 30%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--color-surface-alt);
}

.sidebar-backdrop {
  display: none;
}

.menu-toggle {
  display: none;
  background: transparent;
  border: none;
  color: var(--color-text);
  cursor: pointer;
  padding: 6px;
  border-radius: 2px;
  align-items: center;
}
.menu-toggle:hover {
  background: var(--color-primary-soft);
}

/* 响应式：移动端侧边栏变为抽屉 */
@media (max-width: 768px) {
  .menu-toggle {
    display: inline-flex;
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 5;
  }
  .chat-area {
    flex: 1 1 100%;
    max-width: 100%;
    border-right: none;
  }
  .sidebar-area {
    position: fixed;
    top: 64px;
    right: 0;
    bottom: 0;
    width: 88%;
    max-width: 360px;
    z-index: 90;
    transform: translateX(100%);
    transition: transform 0.3s ease;
    background: var(--color-bg);
    box-shadow: -12px 0 32px rgba(26, 60, 43, 0.12);
  }
  .sidebar-area.open {
    transform: translateX(0);
  }
  .sidebar-backdrop {
    display: none;
    position: fixed;
    top: 64px;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(15, 23, 42, 0.4);
    z-index: 89;
  }
  .sidebar-backdrop.open {
    display: block;
  }
}
</style>
