<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Menu, SwitchButton, Setting } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ChatWindow from '@/components/ChatWindow.vue'
import ProfilePanel from '@/components/ProfilePanel.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'
import ThemeReviewQueue from '@/components/ThemeReviewQueue.vue'
import ThemeRegistryPanel from '@/components/ThemeRegistryPanel.vue'
import LoginView from '@/components/LoginView.vue'
import { getCurrentUser, getProfile, getConversationMessages, getConversations, logout, getStoredUser, saveUser } from '@/api/chat'
import type { ProfileResponse, HistoryMessage, UserInfo } from '@/types'

const currentUser = ref<UserInfo | null>(null)
const profile = ref<ProfileResponse | null>(null)
const profileLoading = ref(true)
const sidebarOpen = ref(false)
const adminOpen = ref(false)
const currentConversationId = ref('')

const chatRef = ref<InstanceType<typeof ChatWindow> | null>(null)

const customerId = computed(() => currentUser.value?.customer_id || '')
const displayName = computed(() => currentUser.value?.display_name || currentUser.value?.username || '')
const isLoggedIn = computed(() => !!currentUser.value)
const isAdmin = computed(() => currentUser.value?.is_admin === true)

/**
 * 从服务端刷新身份，使 localStorage 中的陈旧态（如缺少 is_admin）与后端一致。
 * 失败时保留本地登录态，仅视为非管理员。
 */
async function refreshIdentity() {
  if (!currentUser.value?.token) return
  try {
    const me = await getCurrentUser()
    currentUser.value = { ...currentUser.value, ...me }
    if (isAdmin.value === false && adminOpen.value) adminOpen.value = false
    saveUser(currentUser.value)
  } catch {
    // token 失效或网络异常：保持现有状态，不强制登出（后续请求会各自鉴权）。
  }
}

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
  await refreshIdentity()
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
  adminOpen.value = false
  ElMessage.success('已登出')
}

onMounted(() => {
  // 启动时检查 localStorage 中的登录态
  const stored = getStoredUser()
  if (stored && stored.token) {
    currentUser.value = stored
    refreshIdentity().then(() => loadProfile()).then(async () => {
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
        <button
          class="menu-toggle"
          aria-label="切换侧边栏"
          :aria-expanded="sidebarOpen"
          aria-controls="advisor-sidebar"
          @click="toggleSidebar"
        >
          <el-icon size="22"><Menu /></el-icon>
        </button>
        <div class="brand">
          <span class="brand-mark">¥</span>
          <div class="brand-copy">
            <h1 class="app-title">金融智能投顾系统</h1>
            <span class="brand-meta">FINANCE INTELLIGENCE / WORKSPACE</span>
          </div>
        </div>
        <div class="header-right">
          <span class="system-status"><i></i>系统在线</span>
          <el-tooltip v-if="isAdmin" content="管理后台" placement="bottom">
            <el-button
              class="admin-btn"
              circle
              size="small"
              @click="adminOpen = true"
            >
              <el-icon size="16"><Setting /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tag type="info" effect="plain">
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

    <!-- 管理后台（仅管理员；未打开时不挂载任何管理员组件，因此不会发起管理员请求） -->
    <el-drawer
      v-if="isAdmin"
      v-model="adminOpen"
      title="管理后台"
      direction="rtl"
      size="min(560px, 94vw)"
      append-to-body
    >
      <div class="admin-body">
        <ThemeReviewQueue v-if="adminOpen" />
        <ThemeRegistryPanel v-if="adminOpen" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--color-bg);
}

.app-header {
  background: rgba(247, 247, 245, 0.96);
  border-bottom: 1px solid var(--color-border);
  position: relative;
  z-index: 100;
  flex-shrink: 0;
}

.header-inner {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 24px;
  height: 64px;
  max-width: 100%;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 0;
  background: var(--color-primary);
  color: #fff;
  font-weight: 800;
  font-size: 18px;
}

.brand-copy { display: flex; flex-direction: column; line-height: 1.15; }
.brand-copy { min-width: 0; }
.brand-copy .app-title { margin: 0; color: var(--color-text); }
.brand-meta { margin-top: 4px; color: var(--color-text-secondary); font: 11px/1 var(--font-mono); letter-spacing: .1em; white-space: nowrap; }

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

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.header-right :deep(.el-tag) { max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-radius: 2px; }

.logout-btn {
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
}
.logout-btn:hover {
  background: rgba(183, 68, 50, 0.08);
  color: var(--color-danger);
  border-color: var(--color-danger);
}

.admin-btn {
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
}
.admin-btn:hover {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-color: var(--color-primary-light);
}

.admin-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.system-status { display: inline-flex; align-items: center; gap: 7px; border: 1px solid var(--color-border); padding: 5px 10px; color: var(--color-text-secondary); font: 10px/1 var(--font-mono); letter-spacing: .08em; }
.system-status i { width: 7px; height: 7px; background: var(--color-success); }

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
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--color-surface-alt);
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
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .brand-meta, .system-status { display: none; }
  .header-inner { padding: 0 12px; }
  .brand { flex: 1; }
  .brand-mark { flex-shrink: 0; }
  .header-right { gap: 6px; flex-shrink: 0; }
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

@media (max-width: 480px) {
  .header-right :deep(.el-tag) { display: none; }
  .brand-mark { width: 30px; height: 30px; }
}
</style>
