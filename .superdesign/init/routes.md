# 页面与路由

项目没有 Vue Router。`frontend/src/main.ts` 直接挂载 `App.vue`，根路径 `/`
依据本地登录态渲染两个页面分支。

| URL | 页面状态 | 入口 | 布局 |
| --- | --- | --- | --- |
| `/` | 未登录 | `frontend/src/components/LoginView.vue` | 全屏渐变背景 + 居中登录卡 |
| `/` | 已登录 | `frontend/src/App.vue` | AppShell 顶栏 + ChatWindow + ProfilePanel/HistoryPanel |

```ts
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import './style.css'

const app = createApp(App)
app.use(ElementPlus)
app.mount('#app')
```
