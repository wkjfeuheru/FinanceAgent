<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Menu, SwitchButton } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ChatWindow from '@/components/ChatWindow.vue'
import ProfilePanel from '@/components/ProfilePanel.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'
import LoginView from '@/components/LoginView.vue'
import { getProfile, getConversationMessages, getConversations, logout, getStoredUser } from '@/api/chat'
import type { ProfileResponse, HistoryMessage, UserInfo } from '@/types'

const currentUser = ref<UserInfo | null>(null)
const profile = ref<ProfileResponse | null>(null)
const profileLoading = ref(true)
const sidebarOpen = ref(false)
const currentConversationId = ref('')

const chatRef = ref<InstanceType<typeof ChatWindow> | null>(null)

const customerId = computed(() => currentUser.value?.customer_id || '')
const displayName = computed(() => currentUser.value?.display_name || currentUser.value?.username || '')
const isLoggedIn = computed(() => !!currentUser.value)

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

/** 登录成功回调 */
async function handleLoggedIn(user: UserInfo) {
  currentUser.value = user
  await loadProfile()
  const history = await loadLatestConversation()
  if (chatRef.value && history.length) {
    chatRef.value.loadHistoryMessages(history)
  }
}

/** 登出 */
async function handleLogout() {
  try {
    await ElMessageBox.confirm(
      `确定要退出当前账号（${displayName.value}）吗？`,
      '登出确认',
      {
        confirmButtonText: '确定登出',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  await logout()
  currentUser.value = null
  profile.value = null
  currentConversationId.value = ''
  ElMessage.success('已登出')
}

onMounted(() => {
  // 启动时检查 localStorage 中的登录态
  const stored = getStoredUser()
  if (stored && stored.token) {
    currentUser.value = stored
    loadProfile().then(async () => {
      const history = await loadLatestConversation()
      if (chatRef.value && history.length) {
        chatRef.value.loadHistoryMessages(history)
      }
    })
  }
})
</script>

<template>
  <!-- 未登录：显示登录页 -->
  <LoginView v-if="!isLoggedIn" @logged-in="handleLoggedIn" />

  <!-- 已登录：显示主界面 -->
  <div v-else class="app-layout">
    <!-- 顶部导航 -->
    <header class="app-header">
      <div class="header-inner">
        <button class="menu-toggle" @click="toggleSidebar" aria-label="切换侧边栏">
          <el-icon size="22"><Menu /></el-icon>
        </button>
        <div class="brand">
          <span class="brand-mark">¥</span>
          <h1 class="app-title">金融智能投顾系统</h1>
        </div>
        <div class="header-right">
          <el-tag type="info" effect="dark" round>
            {{ displayName }}
          </el-tag>
          <el-tooltip content="登出" placement="bottom">
            <el-button
              class="logout-btn"
              circle
              size="small"
              @click="handleLogout"
            >
              <el-icon size="16"><SwitchButton /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </div>
    </header>

    <!-- 主体内容 -->
    <main class="app-main">
      <!-- 聊天区域 70% -->
      <section class="chat-area">
        <ChatWindow
          ref="chatRef"
          :customer-id="customerId"
          :conversation-id="currentConversationId"
          @conversation-updated="currentConversationId = $event"
          @profile-updated="loadProfile"
        />
      </section>

      <!-- 侧边栏 30% -->
      <aside class="sidebar-area" :class="{ open: sidebarOpen }">
        <div class="sidebar-backdrop" @click="toggleSidebar"></div>
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
.app-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.app-header {
  background: linear-gradient(90deg, #1e3a8a 0%, #1e40af 50%, #1e3a8a 100%);
  box-shadow: 0 2px 8px rgba(30, 58, 138, 0.25);
  position: relative;
  z-index: 100;
  flex-shrink: 0;
}

.header-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  height: 60px;
  max-width: 100%;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.15);
  color: #fbbf24;
  font-weight: 800;
  font-size: 18px;
  backdrop-filter: blur(4px);
}

.menu-toggle {
  display: none;
  background: transparent;
  border: none;
  color: #fff;
  cursor: pointer;
  padding: 6px;
  border-radius: 8px;
  align-items: center;
}
.menu-toggle:hover {
  background: rgba(255, 255, 255, 0.12);
}

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

.logout-btn {
  background: rgba(255, 255, 255, 0.15);
  border: none;
  color: #fff;
}
.logout-btn:hover {
  background: rgba(239, 68, 68, 0.6);
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
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sidebar-backdrop {
  display: none;
}

/* 响应式：移动端侧边栏变为抽屉 */
@media (max-width: 768px) {
  .menu-toggle {
    display: inline-flex;
  }
  .app-title {
    font-size: 16px;
  }
  .chat-area {
    flex: 1 1 100%;
    max-width: 100%;
    border-right: none;
  }
  .sidebar-area {
    position: fixed;
    top: 60px;
    right: 0;
    bottom: 0;
    width: 88%;
    max-width: 360px;
    z-index: 90;
    transform: translateX(100%);
    transition: transform 0.3s ease;
    background: var(--color-bg);
    box-shadow: -8px 0 24px rgba(15, 23, 42, 0.12);
  }
  .sidebar-area.open {
    transform: translateX(0);
  }
  .sidebar-backdrop {
    display: block;
    position: fixed;
    top: 60px;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(15, 23, 42, 0.4);
    z-index: -1;
  }
  .sidebar-area:not(.open) .sidebar-backdrop {
    display: none;
  }
}
</style>
