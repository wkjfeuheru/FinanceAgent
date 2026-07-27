# 金融投顾前端视觉焕新实施计划

> **供代理执行者使用：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，逐任务执行本计划。步骤使用复选框（`- [ ]`）跟踪。

**目标：** 使用 Superdesign 为现有 Vue 金融投顾生成可比较的全新视觉方案，并在用户选稿后把选定方案实现到登录页和投顾工作台。

**架构：** 先以现有页面源码生成忠实还原稿，再以 `.superdesign/design-system.md` 为硬约束分支两个设计方向。用户选稿后，仅修改 Vue 模板与样式层，保留所有状态、事件、API 和响应式行为。

**技术栈：** Vue 3、TypeScript、Vite、Element Plus、Superdesign CLI、CSS。

## 全局约束

- 所有用户可见说明使用中文。
- 不改变前后端公开 API、登录流程、聊天流式事件和组件事件名称。
- 使用真实 Element Plus 图标，不使用 emoji。
- 使用 Paper `#F7F7F5`、Forest `#1A3C2B` 和设计系统内限定的强调色。
- 不引入新字体依赖、UI 框架或运行时依赖。
- 保留 768px 侧栏抽屉和 480px 登录页响应式行为。

---

### Task 1：建立 Superdesign 画布并生成方案

**文件：**
- 读取：`.superdesign/design-system.md`
- 读取：`.superdesign/init/pages.md`
- 读取：`frontend/src/App.vue`
- 读取：`frontend/src/style.css`
- 读取：`frontend/src/components/*.vue`
- 临时创建：`.superdesign/tmp/*.html`
- 修改：`.gitignore`

**接口：**
- 输入：当前 Vue UI 源码和已确认的 Technical Minimalist 设计系统。
- 输出：一个 Superdesign 项目、一个当前界面还原稿、两个分支设计稿及画布 URL。

- [ ] **Step 1：准备临时目录和忽略规则**

用 `apply_patch` 向 `.gitignore` 添加：

```gitignore
.superdesign/tmp/
```

创建 `.superdesign/tmp/`，读取 Superdesign `COMPONENTS.md`，将 AppHeader 和 ChatWindow 转换为 Petite-Vue HTML 临时组件。

- [ ] **Step 2：创建项目并注册布局组件**

运行：

```powershell
npx --yes @superdesign/cli@latest create-project --title "FinanceAgent 前端视觉焕新"
npx --yes @superdesign/cli@latest list-components --project-id $projectId
npx --yes @superdesign/cli@latest create-component --project-id $projectId --name "AppHeader" --html-file .superdesign/tmp/app-header.html --description "金融投顾全局顶栏"
npx --yes @superdesign/cli@latest create-component --project-id $projectId --name "ChatWindow" --html-file .superdesign/tmp/chat-window.html --description "投顾聊天主工作区"
```

其中 `$projectId` 必须使用 `create-project` 返回的真实 ID。

- [ ] **Step 3：生成当前界面还原稿**

运行单个忠实还原提示，不包含任何美化方向：

```powershell
npx --yes @superdesign/cli@latest create-design-draft --project-id $projectId --title "当前投顾工作台" -p "像素级忠实还原当前已登录投顾工作台。严格匹配源码中的顶部栏、70/30 对话与侧栏布局、消息列表、输入区、用户画像和历史会话。使用提供的源码作为唯一事实来源，不做任何美化或结构改动。" --context-file .superdesign/design-system.md --context-file frontend/src/style.css --context-file frontend/src/App.vue --context-file frontend/src/components/ChatWindow.vue --context-file frontend/src/components/MessageList.vue --context-file frontend/src/components/MessageInput.vue --context-file frontend/src/components/ProfilePanel.vue --context-file frontend/src/components/HistoryPanel.vue
```

- [ ] **Step 4：从还原稿生成两个分支**

使用 `iterate-design-draft --mode branch`，分别生成“现代机构投顾”和“数据化智能终端”。两个提示都必须包含：只使用设计系统定义的字体、颜色、间距和组件风格；保留现有功能与 70/30 信息结构；不得添加新导航或业务模块。

- [ ] **Step 5：用户选稿检查点**

展示 CLI 返回的真实 canvas 和 preview 链接。调用 `get-design --draft-id ... --json` 阅读两个分支，说明差异并等待用户选择；用户选择前不得修改 Vue 源码。

### Task 2：实现选定的全新设计系统与页面骨架

**文件：**
- 修改：`frontend/src/style.css`
- 修改：`frontend/src/App.vue`
- 修改：`frontend/src/components/LoginView.vue`

**接口：**
- 输入：用户选定的 Superdesign draft。
- 输出：全局 Technical Minimalist tokens、登录页和工作台 shell；现有 props、emits 和方法保持不变。

- [ ] **Step 1：记录构建基线**

运行：`npm run build`

预期：成功；允许保留既有 chunk-size 警告。

- [ ] **Step 2：实现全局 tokens**

将 `frontend/src/style.css` 的变量更新为设计系统值：Paper、Forest、Ink、Grid、Coral、Mint、Gold；移除全局厚重阴影，增加等宽 metadata 字体栈和清晰 focus-visible 样式。

- [ ] **Step 3：实现 AppShell**

保持 `LoginView v-if`、ChatWindow/ProfilePanel/HistoryPanel props 与 emits 不变。重写 header、主区网格和移动端抽屉样式，使其匹配选定 draft。

- [ ] **Step 4：实现登录页**

保持登录/注册切换、校验和提交逻辑不变。模板调整为桌面双栏信任区 + 表单区，移动端单栏；使用 CSS 结构图形，不新增图片资源。

- [ ] **Step 5：验证并提交**

运行：`npm run build`

提交：

```powershell
git add frontend/src/style.css frontend/src/App.vue frontend/src/components/LoginView.vue
git commit -m "feat: refresh finance advisor app shell"
```

### Task 3：实现聊天、进度和侧栏视觉

**文件：**
- 修改：`frontend/src/components/ChatWindow.vue`
- 修改：`frontend/src/components/MessageList.vue`
- 修改：`frontend/src/components/MessageInput.vue`
- 修改：`frontend/src/components/ProfilePanel.vue`
- 修改：`frontend/src/components/HistoryPanel.vue`
- 修改：`frontend/src/components/AllocationChart.vue`

**接口：**
- 输入：现有组件 props、emits 和 API 数据。
- 输出：与选定 draft 一致的消息、输入、状态、画像、历史和配置图视觉；逻辑接口不变。

- [ ] **Step 1：重构聊天视觉**

保留消息循环、loading/progressSteps 分支和配置指标绑定。将圆润气泡改为细线结构化消息块，强化角色、时间、分析步骤和状态标识。

- [ ] **Step 2：重构输入区**

保留 Enter、Shift+Enter、清空和发送行为。实现固定底部的技术表单式输入，保证移动端按钮触控尺寸不少于 40px。

- [ ] **Step 3：重构画像与历史面板**

保留全部数据与操作。使用扁平分区、等宽股票标签和明确的活跃会话状态；删除操作仅在 hover/focus 时突出。

- [ ] **Step 4：统一配置图样式**

将 ECharts 调色板改为 Forest/Mint/Gold/Coral 系列，保留数据计算、tooltip 和空状态。

- [ ] **Step 5：完整验证**

运行：

```powershell
npm run build
Set-Location ..
.\.venv\Scripts\python.exe -m pytest -q
```

检查桌面、768px 和 480px；检查登录、空对话、正常消息、分析进度、配置摘要和侧栏抽屉。

- [ ] **Step 6：提交**

```powershell
git add frontend/src/components
git commit -m "feat: redesign advisor workspace components"
```
