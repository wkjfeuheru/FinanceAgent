# 编排层

位置：`finance_agent/orchestration/`

## 组成

| 模块 | 职责 |
|------|------|
| `graphs/supervisor.py` | 根图：分类 → 会话/澄清/领域扇出 → 缺参追问 → 汇合 → 合规出口；含响应投影 |
| `graphs/conversation.py` | casual chat 与 FAQ 的受限 ReAct 子图 |
| `graphs/compliance.py` | 统一合规出口（确定性规则 + 一次受约束改写 + 复检） |
| `experts/` | 共享 ReAct 外壳（`base.py` / `registry.py`）；业务壳与工具在 `domains/*/expert/` |
| `routing/` | 意图分类（`intent.py`）与任务改写（`task_rewrite.py`） |
| `contracts.py` | 编排流程契约：`DomainTaskContext`、`DomainOutcome`、`PlanTask` 与运行级原因码 |
| `budgets.py` | 受校验的整轮运行预算 `RunBudgets` 与硬上限 |
| `needs_input.py` | 缺参字段登记处、弹窗表单构造/合并与答案应用 |

## 根图拓扑

```text
START → classify ─┬─ conversation ─┐
                  ├─ clarify ──────┤
                  └─ scope_tasks ──┴─→ [Send(domain_worker × N)] → converge
                                                                   ├─ ask → [Send(domain_worker × M)] → converge ⟲
                                                                   ├─ synthesize → compliance
                                                                   └─ compliance → END
```

- **单领域与多领域是同一条路径**：`scope_tasks` 为每个业务领域铺开一条自包含任务
  描述，`Send` 并行扇出；单领域只是扇出数为 1。截止时间、停止语义、崩溃恢复对两种
  场景因此完全一致（历史上单领域走独立分支，既没有墙钟上限也没有检查点）。
- **扇出即检查点**：每个领域任务是根图的独立 superstep，随根 checkpointer 落库，
  已完成领域的结论在崩溃后仍然存在（旧实现在 `plan` 节点函数里同步 `invoke` 一个
  未挂 checkpointer 的子图，节点返回前不落盘，任何异常都要整轮重跑）。
- **缺参追问是环**：`converge` 判定缺参并记一次确定性计数，`ask` 是唯一的
  `interrupt` 宿主；拿到答案后按域 `Send` 重跑，回到 `converge`。弹窗总次数由
  `RunBudgets.clarify_rounds` 封顶。
- **每轮派生状态收在单个 `run` 键**，由 `classify` 用 `Overwrite` 整键重置；
  扇出结果走带 reducer 的 `task_results`。跨轮残留从"新增键必须记得登记"变成
  结构上不可能。

## 领域登记

领域身份（枚举 + 稳定顺序）与装配信息（system prompt 路径、工具白名单工厂）的
**唯一定义**在 `domains/contracts.py` 与 `domains/registry.py`：

- `domains/contracts.py::BusinessDomain` / `DOMAIN_ORDER`；
- `domains/registry.py::DOMAIN_SPECS`（`DomainSpec`）。

编排层只复用：`orchestration/contracts.py` re-export 枚举，`supervisor._DOMAIN_ORDER`
直接引用 `DOMAIN_ORDER`，`experts/registry.py::EXPERT_SPECS` 从 `DOMAIN_SPECS` 派生。
新增一个业务领域只需在 domain 侧登记一处，不再逐文件补齐顺序/提示词/工具四份表。
意图词汇（intent → domain）属路由概念，仍留在 `routing/intent.py`。

## 不变式

- 编排图的规范包是 `graphs/`；不得导入已退役的 `nodes/` 路径（架构测试守卫）。
- **跨领域扇出只由根图的 `Send` 表达**，不得再出现"节点内同步 invoke 一个计划子图"
  的第二条执行路径（`graphs/plan_execute.py` 已整体退场，架构测试守卫其不回归）。
- 领域计算包（`domains/` 中 `expert/` 以外）不反向导入编排层。
- 专家适配器在 `domains/*/expert/`：工具只取数/算数，分析文案由 ReAct 模型写。
- 专家工具不得直接 import 确定性内核（`rule_engine` / `snapshot_builder` /
  `scoring`），只能经 `domains/research/evaluation.py` 调用（架构测试守卫）。
- `orchestration/experts/` 只保留 `base.py`、`registry.py` 与包入口。
- 运行预算只来自 `RunBudgets.from_config()`，各模块不自带默认值；可调用对象
  （停止/截止查询）只经 `RunnableConfig` 下发，绝不放进会被序列化的图状态。
- 告警分两级：`run.warnings` 只披露，`run.degradations` 才改变 `run_status`。
- 配置不变量：`ORCHESTRATION_TURN_TIMEOUT >= ORCHESTRATION_TURN_DEADLINE`
  （等待上限短于执行上限会让用户先看到超时而执行仍在继续）。

## 参考文档

- LangGraph Guides: https://docs.langchain.com/oss/python/langgraph/
- LangGraph API: https://reference.langchain.com/python/
