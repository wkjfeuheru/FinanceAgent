# 架构总览

本文描述当前仓库中实际存在的模块边界；结构约束由 `tests/architecture/` 守卫。

## 模块分区

```
api/              HTTP/SSE 适配、请求与响应模型
application/      AdvisorSystem 门面、轮次协调、持久化、异步恢复与管理服务
orchestration/    LangGraph 工作流、专家、意图路由与运行时机制
bootstrap.py      应用依赖装配入口
domains/          FAQ、组合、产品和股票研究等业务能力
shared/           跨领域契约、标识符、序列化与纯函数
infrastructure/   PostgreSQL/市场数据适配器、外部模型适配器、设置与后台任务
safety/           唯一敏感词检测实现、输入策略与输出策略
```

仓库根部的 `migrations/` 保存按序执行的 PostgreSQL 结构变更；前端按
`frontend/src/features/<feature>/` 划分功能。经校验的设置和环境配置位于
`finance_agent/infrastructure/settings.py`；市场数据适配器位于
`finance_agent/infrastructure/market_data/`，模型适配器位于
`finance_agent/infrastructure/llm/`，后台量化任务位于
`finance_agent/infrastructure/jobs/quant_tasks.py`。

## 依赖方向

- API 通过 application 门面调用应用能力；API 不承载领域规则。
- 编排层负责工作流和适配，不复制领域计算；业务专家适配器竖切在
  `domains/<area>/expert/`。
- `domains/` 计算层只依赖 `shared/` 与标准业务库；不得导入
  `orchestration/`、`api/`、`infrastructure/` 或同包 `expert/`。
- `domains/*/expert/` 是 ReAct 专家适配器：允许 langchain 与
  `orchestration.experts.base`，以及必要的 infrastructure；确定性评估经
  `domains/research/evaluation.py`（`evaluate` / `project_analysis_results`）调用，
  已无 `ResearchPipeline` / `ProductResearchPipeline` / `NarrativeRenderer`。
- 领域身份与装配的唯一定义在 `domains/contracts.py` 与 `domains/registry.py`；
  编排层 re-export，不重复登记。
- 专家路径上工具只返回结构化数字，用户可见分析由模型撰写。
- `infrastructure/` 实现持久化与数据源适配器；仓储协议由领域模块定义时，依赖方向为
  `infrastructure → domains`。
- `infrastructure/jobs/` 承载后台任务；任务可以调用领域实现，但不得反向依赖编排层。

## 关键不变式

- 工作流在 `orchestration/graphs/` 按用例内聚状态、节点、边与投影。
- 名称匹配等跨域纯逻辑有唯一规范实现；编排侧只保留必要的兼容入口。
- PostgreSQL store 共用 `TransactionRunner`，迁移顺序集中声明在
  `infrastructure/persistence/postgres/migrations.py`，SQL 历史位于根目录 `migrations/`。
- 前端仅有一个 Axios 客户端；各功能的 API、类型、页面与专属组件位于 feature 内。
- 已发布迁移不可改写；结构变更追加到根目录 `migrations/`。

## 文档索引

- [orchestration.md](orchestration.md) —— 编排层与工作流
- [orchestration-revision.md](orchestration-revision.md) —— 根图扇出重构的决策记录、部署变更与遗留清单
- [persistence.md](persistence.md) —— PostgreSQL、异步任务与检查点
- [frontend.md](frontend.md) —— 前端结构
# API 组装与目录

FastAPI 应用由 `finance_agent.api.app:app` 组装，部署仍使用公开入口
`finance_agent.main:app`。各 REST 路由位于 `finance_agent.api.routers/`，对应
请求和响应模型位于 `finance_agent.api.schemas/`。前端入口路由与登录态放在
`frontend/src/app/`；共享 HTTP、错误和 SSE 传输位于 `frontend/src/api/`，具体
业务 API 与页面同处 `frontend/src/features/<feature>/`。
