# LangGraph 官方文档知识库

来源: https://docs.langchain.com/oss/python/langgraph/

共 41 个文档，按模块分类。

## 入门

- [overview](overview.md) — LangGraph 概述与核心概念
- [quickstart](quickstart.md) — 快速入门
- [install](install.md) — 安装指南
- [thinking-in-langgraph](thinking-in-langgraph.md) — LangGraph 思维模型

## 核心概念

- [graph-api](graph-api.md) — Graph API (StateGraph, MessageGraph)
- [functional-api](functional-api.md) — Functional API (entrypoint)
- [application-structure](application-structure.md) — 应用结构设计
- [workflows-agents](workflows-agents.md) — 工作流 vs 智能体
- [pregel](pregel.md) — Pregel 运行时原理
- [choosing-apis](choosing-apis.md) — 如何选择 API 风格

## 持久化与状态

- [persistence](persistence.md) — 持久化执行
- [checkpointers](checkpointers.md) — 检查点保存器
- [stores](stores.md) — 持久化存储 (Store)
- [add-memory](add-memory.md) — 添加记忆

## 流式与事件

- [streaming](streaming.md) — 流式输出
- [event-streaming](event-streaming.md) — 事件流
- [frontend/overview](frontend/overview.md) — 前端集成概览
- [frontend/graph-execution](frontend/graph-execution.md) — 图执行前端
- [frontend/custom-stream-channels](frontend/custom-stream-channels.md) — 自定义流通道

## 人机协作

- [interrupts](interrupts.md) — 中断与人工介入
- [use-time-travel](use-time-travel.md) — 时间旅行调试

## 测试与容错

- [test](test.md) — 测试指南
- [fault-tolerance](fault-tolerance.md) — 容错处理
- [backward-compatibility](backward-compatibility.md) — 向后兼容

## 实战指南

- [use-graph-api](use-graph-api.md) — Graph API 实战
- [use-functional-api](use-functional-api.md) — Functional API 实战
- [use-subgraphs](use-subgraphs.md) — 子图使用
- [agentic-rag](agentic-rag.md) — Agentic RAG
- [sql-agent](sql-agent.md) — SQL Agent 示例

## UI 与部署

- [ui](ui.md) — UI 组件
- [deploy](deploy.md) — 部署指南
- [local-server](local-server.md) — 本地服务器
- [studio](studio.md) — LangGraph Studio
- [observability](observability.md) — 可观测性

## 错误处理

- [errors/GRAPH_RECURSION_LIMIT](errors/GRAPH_RECURSION_LIMIT.md)
- [errors/INVALID_CHAT_HISTORY](errors/INVALID_CHAT_HISTORY.md)
- [errors/INVALID_CONCURRENT_GRAPH_UPDATE](errors/INVALID_CONCURRENT_GRAPH_UPDATE.md)
- [errors/INVALID_GRAPH_NODE_RETURN_VALUE](errors/INVALID_GRAPH_NODE_RETURN_VALUE.md)
- [errors/MISSING_CHECKPOINTER](errors/MISSING_CHECKPOINTER.md)
- [errors/MULTIPLE_SUBGRAPHS](errors/MULTIPLE_SUBGRAPHS.md)

## 其他

- [case-studies](case-studies.md) — 案例研究
- [backward-compatibility](backward-compatibility.md) — 向后兼容
