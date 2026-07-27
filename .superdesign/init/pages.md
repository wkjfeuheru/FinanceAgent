# 页面依赖树

## `/` 未登录页

入口：`frontend/src/App.vue` 的 `!isLoggedIn` 分支

- `frontend/src/App.vue`
  - `frontend/src/components/LoginView.vue`
    - `frontend/src/api/chat.ts`
    - `frontend/src/types/index.ts`
    - `@element-plus/icons-vue`
- `frontend/src/style.css`

## `/` 已登录投顾工作台

入口：`frontend/src/App.vue` 的 `v-else` 分支

- `frontend/src/App.vue`
  - `frontend/src/components/ChatWindow.vue`
    - `frontend/src/components/MessageList.vue`
      - `frontend/src/types/index.ts`
      - `@element-plus/icons-vue`
    - `frontend/src/components/MessageInput.vue`
      - `@element-plus/icons-vue`
    - `frontend/src/api/chat.ts`
    - `frontend/src/types/index.ts`
  - `frontend/src/components/ProfilePanel.vue`
    - `frontend/src/types/index.ts`
    - `@element-plus/icons-vue`
  - `frontend/src/components/HistoryPanel.vue`
    - `frontend/src/api/chat.ts`
    - `frontend/src/types/index.ts`
    - `@element-plus/icons-vue`
  - `frontend/src/components/LoginView.vue`
  - `frontend/src/api/chat.ts`
  - `frontend/src/types/index.ts`
- `frontend/src/style.css`

`AllocationChart.vue` 当前未由主工作台直接导入，可作为后续配置结果视觉扩展参考。
