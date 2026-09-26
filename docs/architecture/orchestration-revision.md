# 编排层重构记录（根图扇出拓扑）

本文是这次编排层重构的**决策记录与遗留清单**：包含定案、实施范围、验收口径、
部署变更，以及明确"不做"的部分。之前的 `docs/orchestration-follow-up.md` 在工作区
被删除后，其待办随之失联；本文取代它，并改为"决定 + 证据 + 待办"三段式。

## 一、目标排序（先定的取舍基线）

1. **可靠性**：不卡住、可恢复、不重复烧钱；
2. **削复杂度**：删掉不可达能力与"名实不符"的代码；
3. **合规收紧**：让合规出口名实相符；
4. **能力扩展**：领域内多步依赖、真正可达的 replan。

硬约束：不改 `/api/chat` 既有字段名与 SSE 事件类型；不重写领域计算口径。
允许：改前端契约、DB 迁移、改造既有测试。

## 二、定案（22 项）

| # | 决定 |
|---|---|
| 1 | 停止真正生效：停止标记沿 `RunnableConfig` 下沉到专家**模型轮次边界** |
| 2 | 单领域纳入整轮墙钟上限；超时即时返回 `partial` 并保留已完成结论 |
| 3 | SSE 超时不再阻塞同会话：worker 在下一个轮次边界自行退出并释放会话锁 |
| 4 | 跨轮状态卫生：run-scoped 键收进单个 `run` 键，`classify` 整键 `Overwrite` |
| 5 | 架构守卫：顶层状态键与 `RunState` 键集必须与登记表一致 |
| 6 | 合规语义校验：复用 INTENT_MODEL，**只输出违规码**，不可用即 fail-closed |
| 7 | evidence 硬门禁：改写不得丢失原有数值 / 引用 |
| 8 | 契约：补齐真实投影（`user_profile`），不消费字段停写并标废弃 |
| 9 | 删掉 Planner 与 plan 子图，跨领域扇出提升为**根图一等公民** |
| 10 | 单一整轮墙钟上限，超时即时 partial（沿用/重命名原因码） |
| 11 | 缺参重跑拆成**按域 `Send` 扇出**（完成即落检查点） |
| 12 | FAQ 受信判定 = 复用 FAQ embeddings 的**句级向量相似度** |
| 13 | 句级豁免：受信句只审计，其余句照常改写 |
| 14 | 任一非受信句复检失败 → 整轮 `blocked`（fail-closed） |
| 15 | FAQ 原文经专用 state 键流入 `run_compliance(trusted_sources=…)` |
| 16 | `plan_execute.py` 整体退场，只保留 `PlanTask` 作领域任务描述契约 |
| 17 | replan 配置面代码 + 部署模板同步清理 |
| 18 | 进度事件细粒度、以领域为行（`routing/scope/domain:*/synthesize/compliance`） |
| 19 | 加确定性内核守卫（结论性措辞但未调 `evaluate_research` → 降级） |
| 20 | 追问总弹窗上限 2 次（首次 + 1 次重问，**确定性计数**） |
| 21 | 保留线程键 `v1`，**部署时停服清空 checkpoint 表**（见 persistence.md） |
| 22 | warning 分 `warnings`（提示）/ `degradations`（降级）两级 |

## 三、目标拓扑与关键机制

> 注：下图是本节这次修订的目标拓扑；后续第八节把领域决策节点改为 LLM Supervisor。

```text
START → classify ─┬─ conversation ─┐
                  ├─ clarify ──────┤
                  └─ scope_tasks ──┴─→ [Send(domain_worker × N)] → converge
                                                                   ├─ ask → [Send(domain_worker × M)] → converge ⟲
                                                                   ├─ synthesize → compliance
                                                                   └─ compliance → END
```

- **单领域与多领域同一条路径**：`scope_tasks` 为每域铺开自包含描述，`Send` 并行
  扇出；单领域只是扇出数为 1。任务标识统一为 `{run_id}:{domain}`。
- **扇出即检查点**：每个领域任务是独立 superstep。已完成的领域结论在崩溃后仍在
  检查点里（`tests/integration/test_root_fanout_graph.py` 有回归测试）；旧实现把
  整轮扇出放在 `plan` 节点的嵌套 `invoke` 里，节点返回前不落盘。
- **停止/截止注入**：`deadline_monotonic`（float，可序列化）随任务下发；宿主构造
  `() -> 原因码` 的可调用对象，经 `RunnableConfig.configurable["stop_check"]` 传给
  专家，由 `CooperativeStopMiddleware.before_model` 在**每次模型调用前**检查。
  可调用对象绝不进图状态（会被 checkpoint 序列化）。
- **每轮派生状态单键承载**：`run` 由 `classify` 用 `Overwrite` 重置，其余节点只写
  自己那几个键。历史上 `trusted_content` / `param_blocked` 都曾静默泄漏到下一轮。
- **追问是环但计数确定**：`converge` 判定缺参并写 `clarify_rounds+1`（在同一节点
  提交，`interrupt` 宿主重跑不会重复计数），`ask` 是唯一 `interrupt` 宿主；补答后
  **重置整轮截止**（用户在弹窗上停留的时间不属于计算预算）。
- **合规出口句级豁免**：回复分句后与命中的 FAQ 原文做余弦相似度比较，达阈值的
  句子只审计、不改写；其余句子照常确定性检查 + 逐句改写 + 复检。相似度不可计算
  时不放行任何豁免。

## 四、阶段交付

| 阶段 | 交付 | 验收 |
|---|---|---|
| 1 可靠性地基 | 根图重写、计划层删除、截止/停止下沉、进度事件、警告分级 | `tests/integration/test_root_fanout_graph.py`（18 项，含崩溃恢复与跨轮隔离） |
| 2 缺口补齐 | 确定性内核守卫、追问环、投影补齐、状态键架构守卫 | `tests/unit/test_stock_assemble_guard.py`、架构守卫测试 |
| 3 合规收紧 | 句级受信豁免 + 相似度、evidence 门禁、语义校验 fail-closed | `tests/integration/test_trusted_sentence_compliance.py`（14 项） |
| 4 清理与文档 | 配置面/绑定符号清理、evals 重写、文档与部署 runbook | 全量 `pytest` |

## 五、部署变更（必读）

重写根图拓扑的那一次部署必须停服并清空 LangGraph 的四张检查点表
（`checkpoints` / `checkpoint_blobs` / `checkpoint_writes` / `checkpoint_migrations`）。
对话历史与画像按 `customer_id` / `conversation_id` 存在业务表，不受影响。
详见 `docs/architecture/persistence.md` 的"Checkpoint 兼容性与部署"。

配置项重命名：`ORCHESTRATION_PLAN_TASKS` → `ORCHESTRATION_MAX_DOMAINS`，
`ORCHESTRATION_PLAN_DEADLINE` → `ORCHESTRATION_TURN_DEADLINE`，新增
`ORCHESTRATION_CLARIFY_ROUNDS`；`ORCHESTRATION_REPLANS` 删除。新增不变量
`TURN_TIMEOUT >= TURN_DEADLINE`（构造时校验）。

## 六、明确不做（本轮登记，未实施）

1. **领域内/跨领域依赖与多步计划**：`PlanTask.depends_on` 已删除；`PlanTask` 只作
   任务描述契约。要做需要重新引入受限 operation 枚举与依赖校验。
2. **分类置信度阈值 0.9 的校准**：需要先用 `evals/runners/intent_routing_eval.py`
   跑基线数据，再决定是否下调。
3. **"不支持主题/板块选股"的能力边界从正则搬到业务层声明**：涉及产品口径。
4. **FAQ 索引加文档版本 / 审核状态 / 审核人**：受信治理的上游，依赖运维流程。
5. **删除 `task_dispatch` 等 DB 列**：当前只停止写入有效内容（恒 `[]`），列保留。
6. **`DispatchPlan` / `Task` / `TaskKind` 契约清理**：仅剩仓储可选参数与契约测试使用。

## 七、已知遗留（先于本次重构存在，未在范围内处理）

- ~~`intent_routing_eval.py` 的 `n3` 口径冲突~~：随领域裁剪一并消失（该用例已改为
  `allocation_review`，与现行口径一致；加固后正确率 100%）。
- `tests/unit/test_faq_documents.py` 的 4 个 error 是沙箱临时目录限制（`tmp_path`
  无法创建），不是代码问题；同文件其余用例通过。
- 工作区残留空目录 `.pytest-tmp`（沙箱拒绝递归删除）。

## 八、后续修订：LLM Supervisor 领域决策

在第七节基础上的又一次修订：把「选哪些业务领域」从确定性 `scope_tasks` 交给 LLM。

- **形态**：新增 `graphs/llm_supervisor.py`，用 `create_agent` + `transfer_to_<domain>`
  handoff 工具（参考 `langgraph_supervisor` 的形式）。根图 `classify` 之后的分支由
  `scope_tasks` 改为 `supervisor` 节点。
- **为什么 handoff 工具不直接返回跨图 `Command`**：LangGraph 1.2 在"同一轮多个工具各返回
  `Command(graph=PARENT, goto=[Send(...)])`"时只保留最后一个分支，会静默丢成单领域。
  因此工具只作决策探针（记录 LLM 选择 + 候选集校验），由 `make_supervisor_node` 统一
  解析并一次性构造全部 `Send`，保证"LLM 决定 + 根图并行扇出"两者都成立。
- **权威边界（混合）**：`classify` 的意图推导给出候选领域为**硬上界**，LLM 只能在候选内
  取舍；越界 handoff 被拒，LLM 未选出任何有效领域时回退候选全集。`clarify` / 分类协议
  错误仍由 `classify` + `route` 硬门控。
- **不改写任务描述**：`task_rewrite`（含实体保真校验）仍是任务描述的权威；handoff 描述
  仅在确定性改写退化为原句时兜底。
- **领域裁剪**：本次同时删除 `market_insight` 整条纵向切片（`BusinessDomain` 四领域变三，
  领域权威 `DOMAIN_SPECS`、意图表、投影、前端 `market_insight` 分支、evals/e2e 同步清理）。
  对话路径仍为 4 条：stock / product / account + conversation。
- **回退开关**：`ORCHESTRATION_SUPERVISOR_MODE`（`llm` 默认 / `legacy` 回退确定性
  `scope_tasks`）。临时急停用，观察期后连同 `scope_tasks` 路径移除。
- **部署**：拓扑再次变更，沿用第五节要求——停服并清空四张 LangGraph 检查点表。
