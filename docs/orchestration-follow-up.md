# LangGraph 编排层后续改进清单

更新时间：2026-09-22  
状态：架构跟踪文档；除“已完成”项外，实施前需再次确认。

## 当前已落地

- Supervisor Graph（原 Root Graph，已改名）统一执行分类、路由、领域执行与最终合规出口。
- **所有 LangGraph 节点函数收敛到 `orchestrator/nodes/`**：`supervisor.py`、`plan_execute.py`、
  `domain.py`、`conversation.py`、`compliance.py`；依赖经 `make_*` 工厂显式注入，宿主图模块只装配节点与边。
- **缺参追问（human-in-the-loop）已落地**：根图在 `classify` 与分发之间新增 `extract`、`validate`
  两个节点，缺必填参数时用 LangGraph `interrupt` 挂起，前端弹窗收集后在同一 `thread_id` 上
  `Command(resume=...)` 续跑。详见下节「缺参追问」。
- **用户画像已接入分析链路**：此前画像卡只被拼进 `memory_context` 却无人消费，`state["user_profile"]`
  恒为 `{}`、`profile_complete` 恒假、`personalization_status` 恒为 `research_candidate`。现在由
  `AdvisorSystem` 读取画像卡随输入注入根图，再经 `DomainTaskContext.user_profile` 透传到领域 handler。
- casual chat 与 FAQ 使用受限 ReAct，FAQ 工具白名单仅包含 `faq_search`，步数由 `RunBudgets.react_steps` 驱动。
- FAQ 以“问题 + 答案”为单个 embedding 单元存入 pgvector。
- 复合领域请求已实际调用编译后的 `Plan-and-Execute` LangGraph 子图，通过 `Send` 分发就绪任务。
- 股票领域已注入 `CeleryQuantGateway`；CPU 密集技术指标具备投递至 `finance.quant` 队列的入口。
- **统一 `RunBudgets`（config.ORCHESTRATION_* 的唯一投影）**：会话 ReAct 步数、计划任务数、重规划次数、
  合规改写次数与图递归上限都从它取值；`ExecutionProfile` 提供受校验的图配置契约。
- **领域 operation 注册表 `orchestrator/runtime/operations.py`**：四个领域的 operation 白名单、默认模式与
  mode 解析器集中登记；各领域 `build_X_domain_graph` 与 `AdvisorSystem._domain_runner` 复用同一份数据。
- **P0 异步量化任务闭环已打通**（见下）。
- Supervisor Graph 使用 PostgreSQL Checkpointer，并以 `user_id:session_id` 语义的 `thread_id` 隔离会话。
- 所有根图终态都经过合规节点；FAQ 命中内容目前是“审计但不改写”的受信内容例外。

## 缺参追问：参数抽取、入参校验与 human-in-the-loop（已完成）

### 为什么挂在根图

`interrupt` 需要 checkpointer，且恢复时**节点从函数开头重跑**（`rules/langgraph-guides/interrupts.md`）。
本仓库只有根 Supervisor 图挂了 `PostgresSaver`；领域子图以 `graph.invoke({"context": context})` 调用、
不传 config，编译时也未传 checkpointer。因此校验节点放根图；下沉到子图需改 4 张图，且与 `Send`
扇出的恢复语义冲突。

### 参数模型（唯一事实源 `orchestrator/routing/params.py`）

`PARAM_SPECS: dict[BusinessDomain, tuple[ParamSpec, ...]]` 登记每个领域的参数（必填/可选、控件类型、
可选项、是否可写长期画像）：

| 领域 | 必填 | 可选 |
|---|---|---|
| `stock_research` | `stock_target`（6 位代码，或可唯一确定的名称/主题） | `analysis_type`、`risk_preference`*、`holding_period`* |
| `product_research` | `product_reference`（产品代码或名称） | `risk_preference`*、`holding_period`* |
| `market_insight` | 无 | 无 |
| `account_portfolio` | 无 | 无 |

\* 标注为 `scope="profile"`：可随弹窗一并写入长期用户画像。

**只有股票与产品会触发追问**：市场洞察的数据采集器零入参（时间窗口读配置），账户问答只需会话里的
`customer_id`，二者都不消费用户偏好。「四类领域都接入」体现在统一的 `PARAM_SPECS` 登记表与统一的
`extract`/`validate` 节点，而非四套各自实现。

### 抽取策略

确定性优先：复用股票 6 位代码正则、主题注册表名称匹配、产品代码/名称抽取。**仅当必填项仍缺**时才调用
一次低温模型兜底（模型用 `config.get_intent_model()`，温度复用 `AGENT_TEMPERATURES["slot_extraction"]`）。

抽取失败或模型未配置时置 `extraction_available=False`，校验节点据此**放行**：不得把「没抽到」当作
「用户没说」，否则只给名称（由领域自行做名称→代码解析）的请求会被误拦。

抽取结果经既有的 `intent_slots` 通道流向领域（该通道此前有消费者、无生产者）：下游解析器按**意图名**
取嵌套槽位，因此 `intent_slots_for` 产出 `{"stock_analysis": {...}}` / `{"product_analysis": {...}}`
形状；必填的标的/产品则并入该领域子请求文本，由领域既有的确定性解析器处理。

### 图与节点

```text
START → classify → extract → validate → route ─┬─ conversation / clarify / single_domain / plan → compliance → END
                                               └─ validate_stop（追问/取消文案）──────────────────→ compliance → END
```

- `extract`：写 `extracted_params`。**与 `validate` 拆两个节点是硬要求**——`interrupt` 恢复会重跑整个
  节点，若把（可能含模型调用的）抽取与 `interrupt` 放同一节点，每次恢复都会重复付费调用模型。
- `validate`：算缺参；缺则 `interrupt({question, missing, fields})`。节点内不得用 `try/except` 包住
  `interrupt`（重跑语义要求异常不被吞掉）。恢复值经 `apply_answers` 合并后再校验一次；仍缺则显式
  收尾为 `partial`（单次询问，不重问）；取消哨兵 `__cancel__` 收尾为 `completed`。
- 是否启用 `interrupt` 由图是否有 checkpointer 决定：无 checkpointer 时 `validate` 退化为澄清式收尾，
  与本仓库 interrupt 之前的既有行为一致。

### 恢复、取消与响应

- `ChatRequest` 新增 `resume: bool`、`answers: dict`；`ChatResponse` 新增 `pending_input`、`interrupt_id`；
  `RunStatus` 新增非终态 `awaiting_input`。
- 服务端以隐式检测为主：调用前 `root.get_state(config)` 探测是否有挂起 `interrupt`。有挂起且
  `resume=True` + `answers` 非空 → `Command(resume=answers)`；有挂起但本轮是自由文本新消息 → 先用
  `Command(resume={"__cancel__": True})` 关掉挂起 run 再开新轮（避免新问题被误当成回答）。
- SSE **不新增事件类型**：追问随最终 `response` 事件的 `data` 下发，前端零改动即可消费。
- 前端 `ParamDialog.vue`（`el-dialog` + `el-form`）按 `pending_input.fields` 动态渲染：必填字段挂
  `el-rule` 必填校验，可选字段标注「可选」；提交 → `resume=true` + `answers`；取消 → `answers={__cancel__: true}`。
- 弹窗填写的 `risk_preference` / `holding_period` 经 `AgentMemoryContext.save_profile` 写入长期画像
  （`finance.user_profiles`），同时本轮立即生效。

### 合规口径（豁免登记）

追问是**服务端确定性模板**（`build_question` 只拼装登记字段的标签），不含任何分析结论，且挂在合规
出口之前的图内 `interrupt` 上。按照既有先例（middleware 的 `BLOCKED_RESPONSE` 在 `orchestrator.py`
提前返回、不过合规），此处登记为**合规豁免项**：追问文案不经过 `run_compliance`。真实分析结论仍然
全部经过合规出口。

### 验收标准（已满足）

- 缺必填标的的股票请求产生 `__interrupt__` 且携带表单字段；市场/账户永不挂起。
- `Command(resume={"stock_target": "600519"})` 后完成执行，领域 handler 收到该参数；`extract` 不重复调用。
- 取消哨兵收尾为 `completed` 且不执行领域；无 checkpointer 时退化为澄清式而非 interrupt。
- `handle_message` 返回 `awaiting_input` + `interrupt_id`；画像偏好写入且非法取值被丢弃。

## 命名迁移（本次）

`root` 系列已统一更名为 `supervisor`，语义与"Supervisor 多领域路由"一致：

- 模块：`orchestrator/`（旧 root_graph）→ `orchestrator/graphs/supervisor_graph.py`；
  `orchestrator/nodes/root.py` → `orchestrator/nodes/supervisor.py`；
  测试 `tests/test_root_graph_routing.py` → `tests/test_supervisor_graph_routing.py`。
- 符号：`build_root_graph` → `build_supervisor_graph`；`RootGraphDependencies` → `SupervisorDependencies`；
  `RootState` → `SupervisorState`；`project_root_state` → `project_supervisor_state`；
  `AdvisorSystem.root` → `AdvisorSystem.supervisor`；`_build_root` → `_build_supervisor`。

## 目标架构：统一 Planner–Executor 图，两类配置实例

后续不为 conversation、股票、市场、产品分别维护 ReAct 循环，也不把 Plan-and-Execute
实现为另一套控制流。统一提供一个深模块：`build_planner_executor_graph()`。调用方只
选择受校验配置；规划、执行、循环保护、汇合、可选重规划和安全退出都封装在图内。

```text
START
  → planner
  → executor
  → evaluate
      ├─ final               → END
      ├─ continue            → planner
      └─ replan（可选启用）  → replan → executor / evaluate
```

其中 `planner` 的语义由运行模式决定：ReAct 模式规划“下一步动作”，计划模式规划
“受限任务 DAG”；`executor` 同样通过配置选择单个工具、领域 operation 或一组
`Send` 任务。图的公共状态只输出 `messages`、`task_results`、`final_response`、
`warnings` 和合规需要的 evidence；工具观察、检索文档和中间评分保留在子图私有状态，
不向父图泄漏。

### 配置实例 A：`react`（无独立 replan 节点）

适用于 casual chat、FAQ、股票研究、市场洞察和产品研究的自适应工具链路。

- `planner` 每轮只输出 `tool` 或 `final`；工具必须属于该领域白名单。
- `executor` 每轮执行一个 operation，将验证后的 observation 写回私有状态。
- `evaluate` 在达到可靠结论时结束；否则回到 `planner`。这就是 ReAct 的
  “reason → act → observe”循环，不需要额外 `replan` 节点。
- 最大循环步数统一由 `RunBudgets.react_steps` 强制；协议错误、工具错误和耗尽预算都返回
  安全的部分结果或拒答。
- 通过 `domain` 与 `operation_registry` 配置实例化：例如 stock 仅允许
  `resolve/fetch/research/quant`，product 仅允许 `lookup/evaluate`；不创建专门 Agent 类。

### 配置实例 B：`plan_execute`（可选 `replan`）

适用于复合意图，或单领域中必须显式表达依赖的多步骤研究。

- `planner` 只能输出已注册 `operation` 的 `ExecutionPlan`；校验任务数、领域、输入输出
  引用、依赖关系、环和预算。
- `executor` 通过 `Send` 扇出所有就绪任务；每个任务可调用同一 Planner–Executor 图的
  领域配置实例，而不是旁路到另一套 Agent 实现。
- `evaluate` 汇合 `task_results`：全部完成则结束；仍有就绪任务继续 executor；仅在
  配置 `replan_enabled=True` 且结果无法满足依赖、缺少必要信息或任务失败时，才进入
  `replan`。
- `replan` 必须保留已完成 `task_id`，只允许补充或替换尚未开始的受限任务；最多两次。

### 配置接口

```python
planner_executor = build_planner_executor_graph(operation_registry).compile()

react_runtime = planner_executor.with_config({
    "configurable": {
        "mode": "react",
        "max_steps": 4,
        "replan_enabled": False,
        "operation_scope": "stock",  # 也可为 conversation / market / product
    }
})

plan_runtime = planner_executor.with_config({
    "configurable": {
        "mode": "plan_execute",
        "max_steps": 8,
        "replan_enabled": True,
        "max_replans": 2,
        "operation_scope": "cross_domain",
    }
})
```

配置不是任意字典：由 Pydantic `ExecutionProfile` 校验，禁止调用方传入工具函数、
自由领域名或超过全局上限的预算。根图只负责根据路由选择 `react_runtime` 或
`plan_runtime`，最终仍统一进入 compliance。`ExecutionProfile` 契约本次已落地
（`orchestrator/contracts.py`），`plan_execute` profile 已由 `AdvisorSystem` 从
`RunBudgets` 派生并注入计划路径。

### 迁移原则

1. 保留现有确定性研究、RAG、量化和产品规则实现，把它们注册为 `operation`，不重写业务口径。
2. 将当前 `select → execute` 领域子图迁入统一 `react` 配置，逐项替换，不并行保留两套循环。
3. 将当前 Plan 子图迁入统一 `plan_execute` 配置，`Send`、任务校验、汇合和可选重规划继续复用。
4. 量化 operation 只提交/读取异步任务；Celery worker 不导入 LangGraph。
5. 所有 profile 的终态都返回统一 `DomainOutcome` 或 `PlanRunResult`，由 Supervisor 合规出口处理。

## 优先级 P0：异步量化任务闭环（已完成）

### 本次实现

```text
Stock Domain
  → QuantGateway.submit(kind, payload, idempotency_key, customer_id, thread_id, run_id, task_id)
  → AsyncJobRef 持久化（finance.async_jobs，按 idempotency_key 幂等）
  → OperationResult.pending_jobs → DomainOutcome.pending_jobs（status=processing）
  → 结论快照落库（finance.pending_outcomes，按 job_id 一行）
  → Supervisor 响应返回真实 Celery job_id（pending_task_ids）
  → GET /api/runs/{job_id} 校验 customer_id
  → ResumeCoordinator 恢复原 thread_id / conversation_id，合并指标、重渲染并过合规
```

- `CeleryQuantGateway.submit()` 现接收 `customer_id/thread_id/run_id/task_id`，`AsyncJobRef.task_id`
  携带领域 task_id（job_id 仍是 Celery uuid5）。
- `compute_technical_via_gateway` 返回 `(indicators, pending, pending_jobs)`，并把
  `pending_jobs` 与 `pending_job_codes` 写入结论；`domains.base.execute_node` 映射进
  `DomainOutcome.pending_jobs`（该字段此前从未被写入）。
- **修复真实 bug**：`project_supervisor_state` 的 `pending_task_ids` 此前返回领域任务 id
  （`single:{run_id}:{domain}`），而 `GET /api/runs/{task_id}` 按 Celery `job_id` 查询，前端
  永远只会得到 not_found。现改为从 processing 结论的 `pending_jobs` 收集真实 `job_id`。
- 状态端点触发恢复：`AdvisorSystem.resolve_run_status` 在归属校验通过且任务完成后，
  经 `ResumeCoordinator.resume_job` 合并量化指标、移除 `awaiting_quant`、重算状态，
  对结论跑 `run_compliance`，并把最终答复写回原 `conversation_id`；快照按 job 收尾删除。
- 取消语义：`AdvisorSystem.request_stop` 标记停止的同时，经 `ResumeCoordinator.cancel`
  撤销该会话 queued/running 的量化任务；取消后迟到的成功结果被忽略，不触发恢复。

### 验收标准（已满足）

- 同一幂等键只产生一个 Celery 任务。
- 异步状态查询只能读取所属客户的任务（仓储按 customer_id 隔离）。
- worker 完成后，恢复原会话并继续渲染和合规，不重新执行已完成任务。
- 取消后忽略迟到结果；`pending_task_ids` 返回真实 `job_id`。

### 设计决策（已确认）

采用“状态端点触发恢复 + 可选定时扫描”：本次实现端点触发，`ResumeCoordinator.resume_ready`
保留为定时扫描的扩展点（不实现）。不在 Celery worker 内直接调用 LangGraph——worker
保持纯计算职责，编排状态仍由 Web/编排进程管理。

## 优先级 P1：收敛运行预算为单一配置源（已完成）

### 现状与缺口

配置文件声明了 ReAct 步数、计划任务数和重规划次数，但目前只有 Supervisor recursion limit 已稳定接线；
会话 ReAct、Plan 任务上限和重规划限制仍有默认值或模块常量并存。

### 本次实现

- `RunBudgets.from_config()` 读取 `config.ORCHESTRATION_*`，成为 5 项预算的唯一数值源；
  `le=` 上限放宽为全局硬天花板（默认值的 2 倍冗余），越过天花板在构造时被拒绝。
- `AdvisorSystem` 创建一次 `RunBudgets` 并注入会话 ReAct（`max_steps`）、计划路径
  （`plan_tasks`/`replans`）、合规（`compliance_rewrites`）与 Supervisor 递归上限（`graph_steps`）。
- `plan_execute.PLAN_TASK_LIMIT`/`REPLAN_LIMIT` 改为 config 的别名；`validate_execution_plan`
  与 `build_plan_execute_graph` 支持受限 `task_limit`。
- `run_compliance` 支持 `rewrite_budget`：为 0 时跳过改写、直接 fail-closed。
- `run_conversation`/`build_conversation_graph` 的 `max_steps` 默认改为 None→config 兜底。

### 验收标准（已满足）

- 环境变量变更能实际影响对应运行行为。
- 不存在两处独立的同类预算常量。
- 达到上限时输出安全的部分结果和机器可读 warning。

## 优先级 P1：领域 operation 注册表与 ReAct 边界（注册表已落地）

### 现状与缺口

股票、市场和产品子图目前是 `select → execute` 的确定性工作流，并非真正的工具循环 ReAct。
`domain_react` 这一名称容易造成误解，且为每个领域维护独立循环会使预算、恢复和防护逻辑分散。

### 本次实现

- 新增 `orchestrator/runtime/operations.py`：`OperationRegistry` 集中登记四个领域的 operation 工厂、
  默认模式与 mode 解析器；各领域 `build_X_domain_graph` 与 `AdvisorSystem._domain_runner`
  复用同一份数据，不再各自硬编码。
- operation 白名单是显式枚举（`operation_names`/`modes`），模型不能自由调用领域工具。

### 待办

所有领域仍各自维护 `select → execute` 图，尚未迁入统一 `react` profile。迁移时预算、
恢复与防护逻辑将随之集中。对外若要强调稳定性，可将执行模式名称由 `domain_react`
调整为 `domain_workflow`。

## 优先级 P1：统一图成为可独立恢复的嵌套子图（待办）

### 现状与缺口

Supervisor Graph 目前调用已编译的 Plan 子图，能够使用 `Send` 调度；但该调用发生在
`plan` 节点内部。因此 PostgreSQL Checkpointer 能保存 Supervisor 的前后 superstep，
不能保存每次工具执行、领域任务扇出、汇合和重规划后的中间状态。

### 改进方向

把 Planner–Executor 作为 Supervisor Graph 的嵌套子图节点，而不是在普通节点函数中调用
`.invoke()`。两者共享同一运行配置，使用不同的 checkpoint namespace。子图状态应显式包含：

- `thread_id`、`run_id`、`customer_id`、`conversation_id`（`DomainTaskContext` 已含 `run_id`）；
- 已完成 `task_results` 与待处理 `pending_jobs`（已随 P0 落地）；
- Planner 产生的 plan、重规划次数和停止/截止状态。

### 验收标准

- 在任一领域任务完成后终止进程，可从该任务后的 checkpoint 恢复。
- 恢复时不重新执行已成功的 `task_id`。
- 同一 `thread_id` 的不同 Run 不发生状态串扰。

## 优先级 P1：受限多步骤计划（待办）

### 现状与缺口

当前 Planner 强制每个领域只生成一个任务，并在规范化过程中移除领域内部依赖。因此它支持
跨领域并发，但不能表达“股票筛选 → 候选对比 → 产品匹配”这类受控多步骤链路。

### 改进方向

为 `PlanTask` 增加受限 `operation` 枚举、允许的输入输出引用与依赖校验。每种 operation
映射到统一 Planner–Executor 的领域配置，Planner 只能选择这些 operation，不能创建自由
文本工具调用。`replan` 只在该 profile 显式开启时可达。

### 验收标准

- 能表达领域内依赖和跨领域依赖。
- LLM 输出非法 operation、循环依赖或超预算时被验证器拒绝。
- 已完成 task 在重规划后不可重复执行。

## 优先级 P1：FAQ 受信内容治理与合规审计

### 现状与缺口

FAQ 命中内容进入合规节点，但以 `audit_only` 方式通过，不会被拦截或改写。此策略仅在 FAQ 已经过人工审核、可追溯和可回滚时才安全。

### 改进方向

- 为 FAQ 索引加入文档版本、审核状态、审核人和发布时间。
- 将 `faq_id`、chunk/索引版本、检索分数写入 Supervisor State 的证据与合规审计记录。
- 只有已发布且审核通过的 FAQ 才可标记为受信内容；其余命中仍走常规合规规则。

## 优先级 P2：Checkpoint 的工作流版本隔离

`thread_id` 应持续保持 `user_id:session_id` 主语义，不建议把部署版本拼进该字符串。应另设 `workflow_version` 或 checkpoint namespace：图拓扑、状态 schema 或工具协议升级时，拒绝恢复不兼容 checkpoint，或走显式迁移。

## 优先级 P2：顶层领域数量决策

最初目标是三个顶层研究领域：股票、市场、产品。当前实现还存在 `account_query → account_portfolio` 的第四领域。

需要在后续实施前明确二选一：

1. 账户查询移出 Supervisor，作为只读 API/查询能力；或
2. 正式将账户作为第四个顶层领域，并同步更新路由、文档和测试。

在未决定前，不应继续宣传 Supervisor 只有三个业务领域。

**已采取的路径**：按选项 2 落地——账户作为第四个顶层领域（`account_portfolio`），并在该领域内
新增 `allocation_review` 模式提供配置诊断与优化参考。该模式只读、确定性、不调 LLM，输出限于
"测算/参考/区间"口径，不输出买卖或调仓指令；组合波动率因无产品净值时序而采用对角（零相关）
近似，计算工具的 `correlations` 参数已预留，待净值时序就位即可切到完整口径。

## 测试与运维待办

- 本次相关回归已通过：编排核心定向集 153 项（Supervisor 路由、Plan 子图、四个领域图、
  Conversation/Compliance、契约、量化网关与闭环、profile/注册表）；Supervisor 接线、
  容错、韧性、端到端与 API 兼容 68 项。
- 新增测试：`tests/test_quant_closed_loop.py`（10 项）、`tests/test_execution_profile_and_registry.py`
  （15 项）；`tests/test_supervisor_graph_routing.py`（原 test_root_graph_routing.py）。
- 全量 `pytest -q`：702 passed / 19 skipped，无失败。慢用例（整体约 11 分钟）后续可建立
  `slow`/集成测试标记以便快速回归。
- `git diff --check` 当前报告 `tests/test_postgres_schema.py:143` 有尾部空行；该文件不属于本次改动，应在单独清理提交中处理。

## 推荐实施顺序

1. ~~确认统一 Planner–Executor 的 `ExecutionProfile` 契约与 operation 注册表。~~（已完成）
2. ~~异步量化任务闭环。~~（已完成）
3. 将统一图作为嵌套子图接入 checkpoint 恢复。
4. ~~统一 RunBudgets，并迁移 conversation、三个领域和 Plan。~~（预算与注册表已完成；
   领域仍各自维护 `select → execute` 图，待迁入统一 `react` profile）
5. 实施受限多步骤计划与可选 replan。
6. FAQ 治理、workflow version 与顶层领域收敛。
