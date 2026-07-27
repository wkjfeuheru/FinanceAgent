# 可提取组件

## AppHeader
- Source: `frontend/src/App.vue`
- Category: layout
- Description: 品牌、用户标签、菜单按钮与登出入口组成的全局顶栏。
- Extractable props: `displayName`、`sidebarOpen`
- Hardcoded: ¥ 品牌标记、金融智能投顾系统标题、Element Plus 图标

## ChatWindow
- Source: `frontend/src/components/ChatWindow.vue`
- Category: layout
- Description: 对话工具栏、消息列表和输入区组成的主工作区。
- Extractable props: `loading`
- Hardcoded: 智能对话、在线/处理中标签、工具栏图标

## ProfilePanel
- Source: `frontend/src/components/ProfilePanel.vue`
- Category: basic
- Description: 展示风险、预算、关注股票、期限和投资目标的画像卡片。
- Extractable props: `loading`、`riskPreference`、`budgetAmount`
- Hardcoded: 字段标签、Element Plus 图标、状态色规则

## HistoryPanel
- Source: `frontend/src/components/HistoryPanel.vue`
- Category: basic
- Description: 新建对话、历史会话列表、当前态和删除操作。
- Extractable props: `activeConversationId`
- Hardcoded: 标题、操作图标、空状态文案

## MessageInput
- Source: `frontend/src/components/MessageInput.vue`
- Category: basic
- Description: 清空、自动增高文本框、发送按钮和键盘提示。
- Extractable props: `loading`
- Hardcoded: 输入提示、发送与清空图标

## AllocationChart
- Source: `frontend/src/components/AllocationChart.vue`
- Category: basic
- Description: 资产权重环形图及空状态。
- Extractable props: `weights`
- Hardcoded: 图例、调色板、资产配置标题
