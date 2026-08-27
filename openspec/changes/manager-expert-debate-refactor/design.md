## Context

当前 `finance_agent/core/orchestrator.py` 已经基于 LangGraph StateGraph 实现 6 节点委托式编排，`AdvisorState` 承载跨节点状态，`SharedWorkingMemory` 负责 Agent 间事实共享，DeepSeek 为唯一 LLM，SqliteSaver 提供 checkpoint。资产配置专家（`agents/asset_allocation.py`）目前为纯过程化 MPT 计算，无对抗视角。

## 系统整体架构

重构后系统采用"总管-专家"分层架构，LangGraph 承载主编排，各专业 Agent 使用独立上下文并通过 `AdvisorState` 显式传递数据（不再使用 `SharedWorkingMemory`）。

```
┌────────────────────────────────────────────────────────────────────────┐
│                          前端 (Vue 3 + Vite)                           │
│    ChatWindow · AllocationChart · ProfilePanel · HistoryPanel          │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ HTTP / SSE (handle_message / handle_message_stream)
┌───────────────────────────────▼────────────────────────────────────────┐
│                          API 层 (FastAPI)                              │
│    routes.py · schemas.py · sse.py                                     │
│    ─ 输入侧敏感词拦截 find_sensitive_word ─                             │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────────────┐
│            编排层 core/orchestrator.py · LangGraph StateGraph          │
│    AdvisorState（唯一显式数据通道） + SqliteSaver checkpoint            │
│                                                                        │
│    START → ManagerAgent（总管）                                        │
│              ├─ 意图识别  classify_intents                              │
│              ├─ 需求抽取  dispatch_tasks → task_dispatch               │
│              └─ 条件路由（意图 → 专家映射）                             │
│                    │                                                    │
│      ┌─────────────┬──────────────┬───────────────┐                    │
│      ▼             ▼              ▼               ▼                    │
│  StockAnalysis  AssetAllocation  ProductAnalysis  CasualChat            │
│   (股票分析)      (资产配置)       (产品解读)       (闲聊)               │
│                                │ 内部触发                                │
│                                ▼                                        │
│                 AutoGen 辩论（看多分析师 vs 看空分析师）                 │
│      │             │              │               │                    │
│      └─────────────┴──────────────┴───────────────┘                    │
│                        ▼ 独立上下文写回 AdvisorState                    │
│              ManagerAgent.synthesize_response（最终合成）              │
│                        → END                                            │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ 专家内部 tool calling（按需取数，独立上下文）
┌───────────────────────────────▼────────────────────────────────────────┐
│                        工具 / 数据层                                    │
│    tools/fundamental.py（@tool，封装 TushareMcpDataSource 取数能力）   │
│    data/tushare_mcp.py（Tushare MCP Server，统一数据源）                │
│    tools/product.py ──► data/product_library.py（SQLite 产品库）        │
│    finance_agent/debate/（AutoGen GroupChat 辩论子模块）                │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────────────┐
│                        存储 / 记忆层                                    │
│    SQLite finance_agent.db（对话/用户档案）                             │
│    Redis（对话级滑动窗口 + 摘要）                                        │
│    SqliteSaver（LangGraph checkpoint）                                  │
│    DeepSeek（唯一 LLM）                                                 │
└────────────────────────────────────────────────────────────────────────┘
```

### 分层职责

| 层 | 组件 | 职责 |
|----|------|------|
| 前端 | Vue 3 + Vite | 聊天交互、资产配置图、用户档案面板、历史会话 |
| API | FastAPI + SSE | 请求入口、流式进度、输入侧敏感词拦截 |
| 编排 | LangGraph StateGraph | 总管-专家图、条件路由、checkpoint、`AdvisorState` 数据通道 |
| 总管 | `ManagerAgent` | 意图识别、需求抽取、路由、最终合成（不做任务加工） |
| 专家 | StockAnalysis / AssetAllocation / ProductAnalysis / CasualChat | 独立上下文，内部规划 + 字段抽取 + tool calling 取数 + 执行 |
| 辩论 | `finance_agent/debate/`（AutoGen） | 资产配置专家的看多/看空对抗辩论子能力 |
| 工具/数据 | `tools/` + `data/` | 数据源获取、产品库查询、指标计算 |
| 存储/记忆 | SQLite + Redis + SqliteSaver | 持久化、对话记忆、checkpoint、DeepSeek LLM |

## Goals / Non-Goals

**Goals:**
- 将现有 Supervisor 语义显式升级为"总管"：总管在单一节点内只做意图识别与独立需求描述抽取，不做任务加工；产出轻量 `task_dispatch`（意图 -> 专家映射），路由由总管的 dispatch 驱动，而非散落在编排器内联函数。
- 移除独立的合规风控专家节点，由总管承担最终响应合成；保留 API 入口的输入侧敏感词拦截。
- 移除独立的画像（ProfileAgent）专家节点，各专业 Agent 在内部自行从用户消息中抽取自身所需字段（如股票分析抽取股票名称/代码、资产配置抽取风险偏好/投资金额/年限/最大回撤），不再由统一画像专家预抽取。
- 移除独立的数据获取专家节点，将 `data/` 层数据源封装为 LangChain `@tool`，由股票分析、资产配置、产品解读等专家通过内部 tool calling 自行获取数据。
- 新增产品解读专家与产品库（product library），支持单只产品深度透视、多产品对比评估与产品具体问题问答。
- 在资产配置专家内部引入 AutoGen 驱动的"看多/看空"辩论，看多方提出配置方案、看空方质疑方案、主 Agent 仲裁产出最终决策。
- 保持对外公共 API（`handle_message` / `handle_message_stream`）签名兼容，仅在响应体扩展字段。
- 移除 `SharedWorkingMemory` 共享工作内存，各专业 Agent 采用独立上下文、通过 `AdvisorState` 显式传递数据；复用现有 `get_model_for_agent`、checkpoint、SSE 进度回调等基础设施。

**Non-Goals:**
- 不替换 LangGraph 为 AutoGen 作为主编排框架；AutoGen 仅用于辩论子图内部。
- 不为其他专家（数据获取、股票分析、合规）引入辩论；辩论本期仅限资产配置。
- 不引入多 LLM 厂商；辩论也使用 DeepSeek。
- 不重构前端为全新界面；前端仅可选展示辩论摘要。
- 不改变现有数据源划分原则（统一使用 Tushare MCP Server 替代 BaoStock 与网页抓取）。

## Decisions

### 决策 1：总管由 SupervisorAgent 演进而来，只做意图识别、需求抽取、路由与最终合成

**选择**：将 `SupervisorAgent` 演进/重命名为 `ManagerAgent`，保留 `DeepSeekIntentClassifier` 与 `classify_intents`，新增 `dispatch_tasks(state)` 产出轻量 `task_dispatch`（仅含意图到专家的映射与独立需求描述），并新增 `synthesize_response(state)` 承担原合规专家的最终响应合成职责。总管只做意图识别、独立需求描述抽取、路由与最终合成，**不做任务加工**；任务规划与执行由各专业 Agent 内部自行完成。

**理由**：现有 Supervisor 已承担意图分类，演进可避免双轨并存与状态迁移成本；将"任务规划"下沉到专家内部，使总管保持轻量、可观测，避免总管与专家职责重叠；最终合成并入总管契合"总管汇总专家结果"的语义；重命名仅影响内部模块，对外公共 API 不变。

**备选**：新建 `ManagerAgent` 与 Supervisor 并存，逐步迁移。否决：两套调度入口会增加路由歧义与维护负担。

### 决策 2：移除合规风控专家节点，保留输入侧敏感词拦截

**选择**：删除 `ComplianceAgent` 作为独立图节点/专家；原合规专家的"最终响应合成"由总管 `synthesize_response` 承担；输出侧的敏感词扫描不再作为独立节点执行，`tools/compliance.py` 的 `check_sensitive_words` 降级为轻量工具，供总管在合成后可选调用；API 入口（`handle_message`）已有的 `find_sensitive_word` 输入侧拦截继续保留作为安全边界。

**理由**：合规专家与"最终合成"强耦合，本质是编排收尾逻辑而非独立专家；移除后图更贴合"总管-专家"语义。输入侧拦截已在 API 入口生效，可拦住绝大多数违规输入，保留它即可不丧失主要安全能力。

**备选**：保留合规专家仅做输出侧敏感词扫描。否决：会保留一个只做轻量扫描的节点，与"专家"语义不符，且与总管合成形成双重收尾。

**风险**：移除输出侧扫描后，LLM 生成的回复若偶发违规表述将不再被节点级扫描拦截。缓解：总管合成时可选择性调用 `check_sensitive_words` 做最终轻量校验；输入侧拦截 + DeepSeek 自身的安全策略构成主要防线；后续可按需在总管合成后恢复输出侧扫描而不改变编排结构。

### 决策 3：`task_dispatch` 为轻量意图到专家映射，任务规划下沉到专家内部

**选择**：`AdvisorState` 新增 `task_dispatch: List[Dict]`，每项仅包含 `{intent, expert, requirement}` 三个字段：`intent` 为意图类别，`expert` 为路由目标专家，`requirement` 为总管抽取的独立需求描述（原始用户意图的忠实转述，不加工）。总管不再规划子任务依赖、执行顺序或并行分组；这些规划由各专家 Agent 内部自行完成。条件路由函数读取 `task_dispatch` 决定路由目标。保留 `task_plan` 字段做向后兼容（取自 dispatch 的专家名列表）。

**理由**：总管只抽取"独立意图需求描述"，将完整上下文透传给专家，由专家内部做任务规划，避免总管与专家职责重叠、减少上游信息损耗；dispatch 仍使路由可观测、可测试；保留 `task_plan` 避免破坏既有测试与下游消费者。

**备选 A**：总管做精细任务拆分（含依赖、并行分组）。否决：总管加工需求会与专家内部规划重复，且上游信息损耗大，违背"总管只抽取不加工"的语义。
**备选 B**：仅用 `task_plan` 字符串列表承载一切。否决：缺少 `requirement` 描述，专家无法获知具体需求，路由与需求传递仍需散落处理。

### 决策 4：AutoGen 用于辩论子图，与 LangGraph 主图通过"调用-回传"桥接

**选择**：新建 `finance_agent/debate/` 模块，内部使用 AutoGen 的 `AssistantAgent` + `GroupChat` 实现看多/看空辩论；看多分析师根据约束条件提出配置方案（含权重与成长逻辑），看空分析师针对方案逐项质疑，多轮对抗后由资产配置专家仲裁产出最终配置权重。资产配置专家在 LangGraph 节点内同步调用辩论协调器 `run_debate(context) -> debate_result`，仲裁后将结论写入 `state["debate_result"]`。AutoGen 不感知 LangGraph，二者通过纯函数边界隔离。

**理由**：AutoGen 的 GroupChat 天然适配多 Agent 对抗辩论；通过纯函数桥接避免框架耦合，辩论模块可独立测试。DeepSeek 通过 AutoGen 的 `LLMConfig` 指向 DeepSeek OpenAI 兼容端点。

**备选 A**：用 LangGraph 子图实现辩论。否决：缺乏 AutoGen 的 GroupChat 编排便利与辩论语义抽象。
**备选 B**：用纯 LangChain chain 手搓多轮辩论。否决：需自行管理轮次与收敛，重复造轮子。

### 决策 5：辩论配置项纳入 config.py，与现有 Agent 温度策略一致

**选择**：`config.py` 新增 `DEBATE_MAX_ROUNDS`（默认 2）、`DEBATE_TIMEOUT`（默认 60s）、辩论 Agent 温度（看多 0.4 / 看空 0.4 / 聚合 0.1），统一通过 `get_model_for_agent` 复用 DeepSeek。

**理由**：集中配置便于调参与超时治理；复用 `get_model_for_agent` 保证 LLM 提供方一致。

### 决策 6：辩论结论通过 `allocation_result.debate` 对外暴露

**选择**：`allocation_result` 新增可选 `debate` 子字段，结构为 `{bull_arguments, bear_arguments, disagreements, convergences}`；`api/schemas.py` 响应体声明该字段为可选；前端缺失时不报错。

**理由**：向后兼容扩展；辩论结论可被前端消费，符合 spec 的可观测要求。

### 决策 7：数据获取下沉为 tool calling，移除独立数据获取专家

**选择**：删除 `data_fetch_batch` 编排节点与 `DataFetchAgent` 作为独立专家；将 `data/tushare_mcp.py`（Tushare MCP Server）的获取能力封装为 LangChain `@tool`，由股票分析、资产配置、产品解读等专家在自身 ReAct/过程化流程中按需调用。原 `data/baostock.py` 与 `data/market.py`（东方财富/新浪网页抓取）被 Tushare MCP 统一替代。候选搜索变为股票分析专家内部通过 `get_stock_basic`（按行业过滤）+ `get_daily_data`（涨跌幅排序）实现。

**理由**：数据获取本身无独立业务语义，单设节点徒增编排复杂度与状态传递；各专家最清楚自己需要哪些数据，内部 tool calling 更直接、更易并行。Tushare MCP 统一数据源后减少了对多个外部数据源的依赖，且提供了原 BaoStock 缺失的真实 PE/PB 估值数据与利润表数据。

**备选**：保留数据获取专家做统一数据预取。否决：不同专家数据需求差异大（股票分析需 K 线/财务、资产配置需历史价、产品解读需产品库），统一预取会取大量无用数据且耦合专家边界。

**风险**：多专家重复获取同一只股票数据。缓解：各专家独立上下文，通过 `AdvisorState` 显式传递已获取的数据（如 `stock_data`），专家调用工具前先查 state 中是否已有对应数据命中即跳过。

### 决策 8：产品解读专家与产品库

**选择**：新增 `agents/product_analysis.py`（产品解读专家，ReAct 模式，工具为产品库查询）与 `finance_agent/data/product_library.py`（产品库，SQLite 关系型数据库 + 访问层）；`tools/product.py` 将产品库查询封装为 `@tool`。产品库以基金为主，可复用现有 MCP `fund_basic_info` 数据源填充基金基础信息，并支持本地扩展持仓/业绩/费率等字段。产品库设计为可扩展产品类型（ETF 等）。

**产品库存储选型**：主存储采用关系型数据库（SQLite），结构化字段（代码/名称/类型/经理/费率/规模/净值/持仓/业绩/申赎规则）走 SQL 精确查询。**暂不引入 RAG**：非结构化文档（招募说明书、公告）的语义检索不在本次范围，待结构化数据落地后按需评估作为可选补充，且不作为结构化字段的存储。

**理由**：产品解读与股票分析是不同领域（产品 vs 标的），独立专家 + 独立数据源更清晰；产品库隔离外部行情依赖，保证产品问答的事实性与可扩展性。产品数据高度结构化且需精确数值查询/对比，关系型数据库天然匹配；RAG 的检索不确定性在金融数值场景不可接受，且会引入不必要的向量库与索引复杂度，暂不采用。

**风险**：产品库初期数据不完整。缓解：产品库缺失时专家明确说明"产品库暂无该数据"，不虚构；产品库可按需从 MCP `fund_basic_info` 等数据源批量补充。

### 决策 9：任务规划与执行下沉到各专业 Agent 内部

**选择**：总管将完整上下文（用户消息、`task_dispatch` 中的 `requirement`）透传给路由到的专业 Agent；各专家 Agent 内部自行完成"任务规划 -> 字段抽取 -> 工具调用/数据获取 -> 执行 -> 产出结果"的完整闭环，不再依赖总管提供的子任务依赖、执行顺序或并行分组。股票分析、资产配置、产品解读、闲聊均采用 ReAct 或过程化流程，在自身内部完成规划与执行。

**理由**：专家最了解自身领域所需的数据与步骤，内部规划能最大化利用专业上下文、减少上游加工带来的信息损耗；总管保持轻量，只负责意图识别、需求抽取、路由与最终合成，职责清晰不重叠。

**备选**：总管规划子任务后专家只做执行。否决：需求加工与专家内部规划重复，且总管无法精准预判专家内部所需步骤，易产生僵化任务计划。

**风险**：专家内部规划缺少统一约束，可能产生不可控的多步 tool calling。缓解：各专家内部规划受 ReAct 迭代上限与工具集约束，并通过 `checkpoint` 状态保证规划可收敛、可恢复。

### 决策 10：移除 SharedWorkingMemory，各专业 Agent 使用独立上下文

**选择**：删除 `finance_agent/core/shared_state.py` 中的 `SharedWorkingMemory`（发布/订阅、事实共享、假设确认、冲突仲裁）及其在编排器中的所有注入点（`publish_fact`、`query`、`shared_memory_snapshot`、`self.shared_memory`）。各专业 Agent（股票分析、资产配置、产品解读）使用**独立上下文**：输入只来自总管透传的 `AdvisorState` 字段与自身 tool calling 返回，输出写回 `AdvisorState` 的对应字段（`stock_data`、`stock_analysis`、`allocation_result`、`product_analysis`），Agent 之间不通过共享内存隐式交换事实。

**理由**：`SharedWorkingMemory` 的发布/订阅与冲突仲裁在当前"总管-专家"线性委托模型下引入隐式耦合与全局可变状态，使数据流难以追踪、checkpoint 恢复需额外重建共享内存副作用（如 `_publish_stock_entry` 的补偿逻辑）；移除后每个专家的上下文边界清晰、可单测，`AdvisorState` 成为唯一显式数据通道，符合"专家自治"语义。

**备选 A**：保留 `SharedWorkingMemory` 仅用于缓存去重。否决：为去重保留整套发布/订阅与冲突机制过重，去重可由 `AdvisorState` 数据字段命中判断替代。
**备选 B**：改用 Redis 做跨 Agent 共享缓存。否决：仍引入隐式共享通道，且与 `AdvisorState` 显式传递形成双轨，复杂度不降反升。

**风险**：移除后专家之间如需复用同一数据（如资产配置复用股票分析的历史价）需经 `AdvisorState` 显式传递，可能增加 state 字段。缓解：`stock_data`、`stock_analysis` 等字段已承载专家产出，资产配置专家通过 `AdvisorState` 读取所需历史价即可；仅保留必要的显式字段，避免膨胀。

### 决策 11：移除画像专家（ProfileAgent），字段抽取下沉到各专家内部

**选择**：删除 `finance_agent/agents/profile.py` 的 `ProfileAgent` 作为独立专家与编排节点；各专业 Agent 在内部自行从用户消息中抽取自身所需字段——股票分析专家抽取股票名称/代码，资产配置专家抽取风险偏好/投资金额/投资年限/关注标的，产品解读专家抽取产品名称/代码。`AdvisorState` 保留 `user_profile` 字段用于各专家写入抽取结果供总管合成时引用，但不再由统一画像专家预抽取与填充。

**理由**：不同专家所需的用户字段差异大（股票分析需标的代码、资产配置需风险偏好与预算、产品解读需产品代码），统一画像专家预抽取会取大量各专家用不上的字段，且抽取逻辑与专家领域知识脱耦；字段抽取下沉到专家内部后，每个专家只抽取自身需要的字段，抽取逻辑与领域知识内聚，更精准、更易维护。

**备选**：保留画像专家仅做通用字段抽取。否决：通用字段（如风险偏好）仅资产配置需要，股票分析/产品解读不需要，统一抽取仍会产生无用字段与耦合。

**风险**：多个专家可能各自抽取同一字段（如都从消息中抽取股票代码）。缓解：各专家只抽取自身所需字段，重叠极少（仅股票代码可能跨股票分析与资产配置）；资产配置可从 `AdvisorState.stock_analysis` 复用已识别的股票代码，避免重复抽取。

### 决策 12：数据源统一为 Tushare MCP Server，替代 BaoStock 与网页抓取

**选择**：将所有股票数据获取统一通过 `finance_agent/data/tushare_mcp.py` 的 `TushareMcpDataSource` 完成，替代原 `data/baostock.py`（BaoStock）与 `data/market.py`（东方财富/新浪网页抓取）。`tools/fundamental.py` 中的 `@tool` 函数改为调用 `TushareMcpDataSource` 对应接口。

**数据完整度评估：**

| 现有需求 | 原 data Source | Tushare MCP 接口 | 状态 |
|---------|---------------|-----------------|------|
| 日线K线（开高低收量） | `baostock.get_history` | `get_daily_data` | ✅ 已覆盖 |
| 股票基本信息（名称/行业） | `baostock.get_basic_info` | `get_stock_basic` | ✅ 已覆盖 |
| 财务指标（ROE/毛利率等） | `baostock.get_financial_indicators` | `get_fina_indicator` | ✅ 已覆盖 |
| 估值指标（PE/PB/市值） | baostock PE/PB 固定为0 | `get_daily_basic` | ✅ **改进** |
| 利润表数据 | 无 | `get_income` | ✅ **新增** |
| 交易日历 | 无 | `get_trade_cal` | ✅ **新增** |
| 最近交易日行情 | `baostock.get_realtime_quote` (T+1) | `get_daily_data` 取最近一天 | ✅ 已覆盖 |
| 板块成份股搜索 | 东方财富网页抓取 | `get_stock_basic` 按行业过滤 | ⚠️ **已替代**（逻辑不同但可用） |
| 行业/概念板块排行 | 东方财富/新浪网页抓取 | ❌ 缺失 | **需扩展** |
| 周/月K线 | `baostock.get_history(weekly)` | ❌ 仅日线 | **可本地重采样** |

**需扩展的接口（按优先级）：**
1. **行业板块排行**（中优先级）：用户问"最近哪些行业涨得好"时需要。可扩展 Tushare MCP 增加 `get_industry_daily`（行业板块日行情）或用 `get_stock_basic` + `get_daily_data` 本地聚合。
2. **概念板块搜索**（低优先级）：用户按概念搜索候选股票时需要。可扩展 Tushare MCP 增加同花顺概念板块接口 `ths_index` / `concept_detail`。
3. **周/月K线**（低优先级）：可从日线数据本地重采样生成，无需扩展 MCP。

**理由**：Tushare MCP 统一数据源减少了对 BaoStock + 东方财富 + 新浪三个独立数据源的维护负担；提供了原 BaoStock 缺失的真实 PE/PB 估值数据与利润表数据，提升基本面分析质量；MCP 协议天然适配 tool calling 模式。板块排行能力缺失可通过本地聚合或后续扩展 MCP 补齐，不阻塞核心流程。

**风险**：Tushare MCP Server 不可用（网络/配额）时全部数据获取中断。缓解：`TUSHARE_MCP_URL` 未配置时 `is_available()` 返回 false，各专家降级为"数据源不可用"提示；后续可增加本地缓存兜底。

## Risks / Trade-offs

- [AutoGen 与现有 LangChain/LangGraph 版本冲突] → Mitigation: 在隔离的 `debate/` 模块中引入 AutoGen，仅依赖其 `AssistantAgent`/`GroupChat`/`LLMConfig` 核心 API；先在 `requirements.txt` 锁定经过兼容验证的版本组合，并以 `python -m compileall` 与冒烟测试验证导入。
- [辩论增加资产配置端到端延迟] → Mitigation: 默认 2 轮、总超时 60s；超时降级为"辩论未执行"，保证主流程不被阻塞；进度回调推送"正在辩论"阶段事件。
- [辩论结论与 MPT 量化结果冲突时的决策边界模糊] -> Mitigation: 辩论由看多方提方案、看空方质疑、主 Agent 仲裁，不再依赖 MPT 作为唯一基准；仲裁时对未解决风险保守降权或标注，避免自动大幅反向调仓。
- [AutoGen 的 DeepSeek 接入需额外 LLMConfig 配置] → Mitigation: 在 `debate/` 模块内集中构建 LLMConfig，复用 `DEEPSEEK_API_KEY` 与既有 base_url，避免在多处重复配置。
- [`AdvisorState` 字段继续膨胀] -> Mitigation: `debate_result` 作为单一字段存储结构化结论；辩论内部临时状态不进入 AdvisorState，仅最终结论写入。
- [移除合规专家后丢失输出侧敏感词扫描] -> Mitigation: 总管合成后可选调用 `check_sensitive_words` 做最终轻量校验；输入侧 `find_sensitive_word` 拦截 + DeepSeek 安全策略构成主要防线；后续可在总管合成后恢复输出侧扫描而不改变编排结构。
- [移除数据获取专家后多专家重复取数] -> Mitigation: 各专家独立上下文、通过 `AdvisorState` 显式传递数据；专家调用工具前先查 state 中是否已有对应数据命中即跳过；工具内部对同一 run 内的请求做内存缓存。
- [产品库初期数据不完整影响问答质量] -> Mitigation: 产品库缺失时专家明确说明限制、不虚构；产品库可按需从 MCP `fund_basic_info` 等数据源批量补充；产品类型按基金先行、ETF 等后续迭代。

## Migration Plan

1. 新增 `debate/` 模块与 `ManagerAgent` 演进先以增量方式落地，`task_plan` 字段保留兼容；`task_dispatch` 采用轻量 `{intent, expert, requirement}` 结构，任务规划下沉到专家内部。
2. 移除合规专家节点：将 `compliance_handler` 的最终合成逻辑迁入 `ManagerAgent.synthesize_response`，编排图删除 `compliance` 节点，改为专家完成后进入总管合成节点。
3. 移除数据获取专家节点：将统一数据源 `data/tushare_mcp.py`（`TushareMcpDataSource`）获取能力封装为 `tools/fundamental.py` 中的 `@tool`，股票分析与资产配置专家改为内部 tool calling；删除 `data_fetch_batch` 节点与 `stock_data_entries` 等中间字段。
4. 新增产品库与产品解读专家：建 `data/product_library.py` SQLite 表与访问层、`tools/product.py` 查询工具、`agents/product_analysis.py` 专家；总管 `task_dispatch` 支持 `product_analysis` 专家路由。
5. `allocation_result.debate` 与 `product_analysis` 声明为可选字段，前端与下游先按"可能缺失"处理。
6. 通过 `python -m compileall -q finance_agent` 与现有测试适配后，再启用辩论默认开关（`DEBATE_ENABLED=true`），可配置为 `false` 回退到无辩论行为。
7. 回滚策略：将 `DEBATE_ENABLED` 置 `false` 即跳过辩论调用，`ManagerAgent` 路由退回读取 `task_plan`；合规专家与数据获取专家回滚需重新引入对应节点，建议作为独立后续变更评估。

## Open Questions

- 辩论轮次默认 2 轮是否足够覆盖 A 股典型多空分歧？可在实现后用真实样本回归调参，不阻塞当前任务拆分。
- 是否需要在 SSE 流中推送辩论的逐轮发言事件？本期仅推送"正在辩论"阶段事件，逐轮事件留待后续按前端需求再定。
