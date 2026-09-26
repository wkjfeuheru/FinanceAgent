# 前端结构

位置：`frontend/src/`

## 组成

- `app/`：应用路由、登录守卫与浏览器会话存储。
- `api/`：唯一 Axios 客户端、统一错误处理和 Fetch/ReadableStream SSE 传输。
- `features/<feature>/`：按 auth、chat、portfolio、research、admin 组织视图、
  专属组件、类型和 feature API；feature API 通过共享客户端发送 HTTP 请求。
- `shared/`：跨 feature 使用的展示格式与通用类型。

## 不变式

- 只允许一处 `axios.create`（由架构测试守卫）。
- SSE 只允许使用 `api/sse.ts` 中的共享传输。
- 身份只来自 Bearer token；前端不传 `customer_id` 参与鉴权。
- Feature 私有页面、组件和类型不回流到顶层 `views/`、`components/` 或统一类型大文件。
