# 共享布局

## AppShell

- 来源：`frontend/src/App.vue`
- 描述：未登录时渲染 `LoginView`；登录后渲染顶部品牌栏，以及 70/30 的聊天与侧栏布局。移动端把侧栏改为右侧抽屉。

```vue
<template>
  <LoginView v-if="!isLoggedIn" @logged-in="handleLoggedIn" />
  <div v-else class="app-layout">
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
          <el-tag type="info" effect="dark" round>{{ displayName }}</el-tag>
          <el-tooltip content="登出" placement="bottom">
            <el-button class="logout-btn" circle size="small" @click="handleLogout">
              <el-icon size="16"><SwitchButton /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </div>
    </header>
    <main class="app-main">
      <section class="chat-area">
        <ChatWindow ref="chatRef" :customer-id="customerId"
          :conversation-id="currentConversationId"
          @conversation-updated="currentConversationId = $event"
          @profile-updated="loadProfile" />
      </section>
      <aside class="sidebar-area" :class="{ open: sidebarOpen }">
        <div class="sidebar-backdrop" @click="toggleSidebar"></div>
        <div class="sidebar-content">
          <ProfilePanel :profile="profile" :loading="profileLoading" />
          <HistoryPanel :customer-id="customerId"
            :active-conversation-id="currentConversationId"
            @new-conversation="handleNewConversation"
            @select-conversation="handleSelectConversation"
            @conversation-deleted="handleConversationDeleted" />
        </div>
      </aside>
    </main>
  </div>
</template>
```

关键布局样式：桌面端 header 高 60px，`.chat-area` 占 70%，`.sidebar-area` 占
30%；断点 768px，聊天区变为 100%，侧栏固定在右侧并以 translateX 抽屉显示。
完整脚本、模板和 scoped CSS 以 `frontend/src/App.vue` 为设计单一事实来源。
