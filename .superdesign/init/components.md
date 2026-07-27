# 共享 UI 组件

项目没有自建 Button、Input、Card 等基础组件库；基础控件统一来自 Element Plus。
本地 `frontend/src/components/` 均为业务级组件，完整源码在设计时直接作为
`--context-file` 传入，不在此重复，以免上下文膨胀。

## 业务组件索引

- `frontend/src/components/ChatWindow.vue`：聊天工作区容器。
- `frontend/src/components/MessageList.vue`：消息气泡、进度步骤及配置摘要。
- `frontend/src/components/MessageInput.vue`：自适应文本输入与发送操作。
- `frontend/src/components/ProfilePanel.vue`：风险、预算、股票和投资目标画像卡。
- `frontend/src/components/HistoryPanel.vue`：会话历史、新建及删除操作。
- `frontend/src/components/LoginView.vue`：登录/注册双态页面。
- `frontend/src/components/AllocationChart.vue`：ECharts 资产配置环形图。

## 外部基础组件

Element Plus 提供 `el-button`、`el-card`、`el-tag`、`el-avatar`、`el-empty`、
`el-form`、`el-input`、`el-tooltip`、`el-skeleton` 和 `el-icon`。图标来自
`@element-plus/icons-vue`，设计应保持这些图标的语义，不替换成 emoji。
