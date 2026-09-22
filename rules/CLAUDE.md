# 项目配置

## LangGraph 项目开发规范

当涉及 LangGraph 相关开发时，必须遵循以下流程：

项目包含两份官方文档知识库：

- **`langgraph-guides/`**（42 篇教程）：概念讲解、最佳实践、实战指南
- **`langgraph-api-docs/`**（542 页 API 参考）：完整类/函数/类型签名

1. **先查 Guides**：在 `langgraph-guides/` 搜索概念和用法，理解正确的模式。
2. **再查 API**：在 `langgraph-api-docs/` 确认具体方法签名和参数。
3. **按官方规范实现**：严格遵循文档中的 API 签名和代码示例风格。

### 教程索引（`langgraph-guides/`）

| 需求场景 | 查阅文档 |
|----------|----------|
| 新建图/Agent | `graph-api.md`, `quickstart.md` |
| 函数式 API | `functional-api.md`, `use-functional-api.md` |
| 持久化/Checkpoint | `persistence.md`, `checkpointers.md` |
| 流式输出 | `streaming.md`, `event-streaming.md` |
| 人机协作/中断 | `interrupts.md` |
| 记忆系统 | `add-memory.md`, `stores.md` |
| 子图/嵌套 | `use-subgraphs.md` |
| 容错/重试 | `fault-tolerance.md` |
| 测试 | `test.md` |
| 部署 | `deploy.md`, `local-server.md` |
| RAG Agent | `agentic-rag.md` |
| SQL Agent | `sql-agent.md` |
| 前端集成 | `frontend/overview.md` |
| 常见错误 | `errors/*.md` |

### 技术栈约束

- 使用 `langgraph` 最新版本（>= 1.0）
- 状态定义优先使用 `TypedDict` + `Annotated` reducer
- 使用 `StateGraph` 构建图，`START`/`END` 作为入口/出口
- 持久化使用 `InMemorySaver`（开发）/ `AsyncPostgresSaver`（生产）
- 流式使用 `graph.stream()` / `graph.astream()`
- 工具定义使用 `langgraph.prebuilt.ToolNode`
