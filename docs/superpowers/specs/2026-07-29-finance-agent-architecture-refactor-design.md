# FinanceAgent 全面架构重构 —— 设计文档

**日期**: 2026-07-29
**状态**: 待审查
**版本**: 1.0

---

## 1. 动机与目标

### 现状问题

| 问题 | 说明 |
|------|------|
| orchestrator 1711 行巨石 | 图构建、节点处理、格式化、内存管理、响应合成全部混在一起 |
| Agent 职责模糊 | Supervisor 同时做意图分类、工具决策、闲聊生成；Slot Extraction 散落在 tools/ 中 |
| 双重调用模式不一致 | DataFetch 有 ReAct 工具定义但过程化绕过；StockAnalysis 用 ReAct；Compliance 不调 LLM |
| State 字段膨胀 | AdvisorState 35+ 字段，大量只在一两个节点使用 |
| 业务逻辑散落 | 摘要格式化、技术指标格式化、最终重写都在 orchestrator 而非对应 Agent |
| 工具目录未按 Agent 边界划分 | tools/ 内多个文件混用，finance_slots.py 理应属于 Agent 却在工具层 |
| 数据获取入口分散 | 市场搜索在 stock_resolution，BaoStock 在 data_fetch_batch，缺乏统一管理 |

### 设计目标

1. **Agent 职责单一** — 每个 Agent 有一个清晰的职责边界，不越界
2. **编排器极简化** — orchestrator 只定义图和路由，节点 = 一行委托
3. **接口统一** — 所有 Agent 暴露统一 `invoke(state) -> state` 接口
4. **函数调用一致** — 需要推理的用 ReAct，确定性的用过程化，不再混用
5. **工具按 Agent 划分** — 每个工具文件只服务一个 Agent
6. **保留现有架构约束** — LangGraph + SharedWorkingMemory + DeepSeek + 现有数据源 + SSE 流式

---

## 2. Agent 职责与文件组织

### 2.1 六个 Agent

```
┌─────────────────────────────────────────────────────────────┐
│  Agent                  调用模式     附属工具              │
├─────────────────────────────────────────────────────────────┤
│  SupervisorAgent        过程化      无（HTTP API 调用）    │
│  ProfileAgent           过程化      无（LLM chain 内部）   │
│  DataFetchAgent         过程化      fundamental / web_search│
│  StockAnalysisAgent     ReAct       technical              │
│  AssetAllocationAgent   过程化      allocation             │
│  ComplianceAgent        过程化      compliance             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 各 Agent 详细职责

#### SupervisorAgent
- 通过 DeepSeek HTTP API 做多意图分类
- 从意图 + execution_mode 确定性地映射为 task_plan
- 处理 casual_chat 子意图的闲聊回复
- 移除 `decide_slot_tool_calls()`（ProfileAgent 始终执行）

#### ProfileAgent（从 `tools/finance_slots.py` 的 `FinanceSlotsExtractor` 提升）
- 从用户输入抽取结构化投资画像（risk_preference, budget_amount, stock_codes, holding_period, investment_goal）
- 识别股票身份（code, name, industry）
- 提取板块/行业关键词（sector_keywords），服务于东方财富板块搜索
- 正则快速路径 + LLM 语义回退（保留现有两级策略）

#### DataFetchAgent
- 统一数据获取入口，根据 execution_mode 决定数据源和策略
- `security_analysis` → BaoStock（行情/财务/历史K线，通过 `tools/fundamental.py` 的 `@tool` 函数）
- `market_overview` → 东方财富 push2 接口（板块排行，通过 `data/market.py`）
- `candidate_search` → 东方财富板块成份股 → 再调 BaoStock 获取每只数据（通过 `data/market.py` + `tools/fundamental.py`）
- 每只股票独立超时保护（90s），工具调用级超时（25s）
- 通过 LangGraph `@task` fan-out 按股票并行

#### StockAnalysisAgent
- ReAct Agent 自主决策：基本面分析 / 技术面分析 / 两者
- 工具: `analyze_fundamentals`（从 shared_memory 读财务指标，调 LLM chain）+ `analyze_technicals`（读 K 线数据，调 `tools/technical.py` 计算指标）
- 确定性兜底：用户消息包含技术面关键词但 ReAct 未调工具 → 直接计算
- 降级回退：ReAct 执行失败 → 自动降级为仅基本面分析
- 负责自身结果的格式化输出（`format_analysis_report()`）

#### AssetAllocationAgent
- MPT 组合优化：计算收益率/波动率/夏普比率/相关性矩阵/最优权重
- 前置条件校验：stock_codes（≥2）、risk_preference、budget_amount、holding_period
- 缺失字段引导语生成
- 优化目标根据风险等级 + 持有期限确定性选择（最小方差 / 最大夏普）

#### ComplianceAgent
- 确定性敏感词扫描（`tools/compliance.py` 的 `check_sensitive_words`）
- LLM 最终响应合成（从 orchestrator 的 `_synthesize_response` 移入，保留线程超时控制）
- 多意图结果组合（从 orchestrator 的 `_compose_intent_draft` 移入）
- 附加风险提示

---

## 3. Graph 节点与路由

### 3.1 节点图（7 个节点，从 13 个大幅简化）

```
START
  │
  ▼
supervisor  ──→ 仅闲聊 ──→ compliance ──→ END
  │                              ▲
  │ (有业务意图)                  │
  ▼                              │
profile                           │
  │                              │
  ▼                              │
data_fetch_batch                  │
  │ (@task × N 按股票并行)        │
  ├── market_overview ───────────┘
  │
  ▼
stock_analysis_batch
  │ (@task × N 按股票并行，ReAct)
  │
  ├── 不含 asset_allocation ──→ compliance
  │
  ▼
asset_allocation ──→ compliance ──→ END
```

### 3.2 条件路由

| 路由点 | 条件 | 目标 |
|--------|------|------|
| supervisor | 仅 casual_chat，无业务意图 | compliance |
| supervisor | 有业务意图 | profile |
| profile | task_plan 含 data_fetch | data_fetch_batch |
| profile | task_plan 不含 data_fetch | compliance |
| data_fetch_batch | market_overview 模式 | compliance |
| data_fetch_batch | task_plan 含 fundamental_analysis | stock_analysis_batch |
| data_fetch_batch | task_plan 不含 fundamental_analysis 且不含 asset_allocation | compliance |
| data_fetch_batch | task_plan 含 asset_allocation（跳过分析） | asset_allocation |
| stock_analysis_batch | task_plan 含 asset_allocation 且 resolved_stocks ≥2 | asset_allocation |
| stock_analysis_batch | 否则 | compliance |

### 3.3 orchestrator 简化示例

```python
class AdvisorSystem:
    def __init__(self):
        self.shared_memory = SharedWorkingMemory()
        self.checkpointer = get_checkpoint_saver()
        self.memory = AgentMemoryContext(store=RedisMemoryStore(), checkpointer=self.checkpointer)

        self.supervisor = SupervisorAgent(shared_memory=self.shared_memory)
        self.profile_agent = ProfileAgent(shared_memory=self.shared_memory)
        self.data_fetch_agent = DataFetchAgent(shared_memory=self.shared_memory)
        self.stock_agent = StockAnalysisAgent(shared_memory=self.shared_memory, checkpointer=self.checkpointer)
        self.allocation_agent = AssetAllocationAgent(shared_memory=self.shared_memory)
        self.compliance_agent = ComplianceAgent(shared_memory=self.shared_memory)

        self.graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        graph = StateGraph(AdvisorState)

        # 7 个节点 = 7 行委托
        graph.add_node("supervisor",           self.supervisor.invoke)
        graph.add_node("profile",              self.profile_agent.invoke)
        # batch 节点：内部用 LangGraph @task fan-out 按股票并行
        graph.add_node("data_fetch_batch",     self._data_fetch_batch_handler)
        graph.add_node("stock_analysis_batch", self._stock_analysis_batch_handler)
        graph.add_node("asset_allocation",     self.allocation_agent.invoke)
        graph.add_node("compliance",           self.compliance_agent.invoke)

    def _data_fetch_batch_handler(self, state: AdvisorState) -> AdvisorState:
        """@task fan-out：每只股票并行获取数据"""
        codes = state.get("resolved_stocks", [])
        futures = [self._fetch_one_stock_task(code, state) for code in codes]
        entries = [f.result() for f in futures]
        state["stock_data"] = self.data_fetch_agent.aggregate(entries)
        return state

    def _stock_analysis_batch_handler(self, state: AdvisorState) -> AdvisorState:
        """@task fan-out：每只股票并行 ReAct 分析"""
        codes = list(state.get("stock_data", {}).keys())
        futures = [self._analyze_one_stock_task(code, state) for code in codes]
        entries = [f.result() for f in futures]
        state["stock_analysis"] = self.stock_agent.aggregate(entries, state)
        return state

        # 路由
        graph.add_edge(START, "supervisor")
        graph.add_conditional_edges("supervisor", self._route_after_supervisor, {
            "profile": "profile",
            "compliance": "compliance",
        })
        graph.add_edge("profile", "data_fetch_batch")
        graph.add_conditional_edges("data_fetch_batch", self._route_after_data_fetch, {
            "stock_analysis_batch": "stock_analysis_batch",
            "asset_allocation": "asset_allocation",
            "compliance": "compliance",
        })
        graph.add_conditional_edges("stock_analysis_batch", self._route_after_analysis, {
            "asset_allocation": "asset_allocation",
            "compliance": "compliance",
        })
        graph.add_edge("asset_allocation", "compliance")
        graph.add_edge("compliance", END)

        return graph.compile(checkpointer=self.checkpointer)
```

---

## 4. Agent 统一接口

```python
class AgentProtocol:
    """所有 Agent 的标准接口。

    编排器不需要知道 Agent 内部是 ReAct、过程化还是 LLM chain，
    统一通过 invoke(state) -> state 调用。
    """
    agent_name: str

    def invoke(self, state: AdvisorState) -> AdvisorState:
        """接收完整 State，修改后返回"""
        raise NotImplementedError


class ProceduralAgent(AgentProtocol):
    """过程化 Agent：确定性调用或 LLM chain，不经过 ReAct 工具循环"""
    shared_memory: SharedWorkingMemory | None

    def invoke(self, state: AdvisorState) -> AdvisorState:
        ...


class ReActAgent(AgentProtocol):
    """ReAct Agent：使用 create_agent，模型自主决定 tool calling"""
    shared_memory: SharedWorkingMemory | None

    def __init__(self, ...):
        self._agent: CompiledStateGraph | None = None  # 懒初始化

    def _get_tools(self) -> list: ...
    def _get_system_prompt(self) -> str: ...

    def invoke(self, state: AdvisorState) -> AdvisorState:
        ...
```

### Agent 类型分布

| Agent | 基类 | 推理模式 |
|-------|------|---------|
| SupervisorAgent | ProceduralAgent | HTTP API 调用 DeepSeek 分类 |
| ProfileAgent | ProceduralAgent | 正则优先 + LLM chain 回退 |
| DataFetchAgent | ProceduralAgent | 确定性数据获取（带超时保护） |
| StockAnalysisAgent | ReActAgent | ReAct tool calling 自主决策 |
| AssetAllocationAgent | ProceduralAgent | 确定性数值计算 + LLM 报告 |
| ComplianceAgent | ProceduralAgent | 确定性扫描 + LLM 重写合成 |

### 4.1 ReAct Agent 安全保障机制

所有 ReAct Agent（当前只有 StockAnalysisAgent，未来可能新增）必须通过
以下机制防止无限循环、工具滥用和静默失败。

#### 4.1.1 最大推理步数

```python
class ReActAgent(AgentProtocol):
    max_reasoning_steps: int = 10        # 模型+工具调用的最大轮次
    max_tool_calls_per_step: int = 2     # 单次推理最多发起的工具调用数
    per_invoke_timeout: float = 90.0     # 单次 invoke 总超时（秒）

    def invoke(self, state: AdvisorState) -> AdvisorState:
        try:
            result = self._agent.invoke(
                {"messages": messages},
                config={
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": self.max_reasoning_steps * 2 + 3,
                },
            )
        except RecursionError:
            # LangGraph 超过 recursion_limit 时抛出
            return self._fallback(state, "推理步数超限")
        except Exception as exc:
            return self._fallback(state, str(exc))
```

`recursion_limit` 计算公式：每步推理 + 每步工具调用各算一个节点，
因此 `max_reasoning_steps * 2 + 3` 给足余量（3 是初始输入 + 最终输出 + 缓冲）。

#### 4.1.2 工具重复调用检测

在 `invoke()` 内部追踪每次 tool_call，检测以下异常模式：

| 异常模式 | 检测方式 | 处理 |
|---------|---------|------|
| **相同参数重复调用** | `(tool_name, frozenset(args.items()))` 哈希，相同哈希出现 ≥3 次 | 终止循环，返回已有结果 |
| **无效循环** | 最近 4 次 tool_call 形成了 A→B→A→B 的交替模式 | 终止循环，降级到确定性兜底 |
| **无进展循环** | 连续 3 次模型推理都输出了 `(tool_name, args)` 完全相同的 tool_call | 终止循环，标记为 "tool_loop_detected" |

```python
class ReActAgent(AgentProtocol):
    def _check_tool_call_health(
        self, tool_calls: list[dict], call_history: list[dict]
    ) -> str | None:
        """返回 None 表示正常；返回字符串表示异常原因。"""

        # 1. 相同参数重复调用检测
        recent = call_history[-6:]  # 最近 6 次
        for tc in tool_calls:
            sig = (tc["name"], frozenset(tc.get("args", {}).items()))
            count = sum(
                1 for h in recent
                if (h["name"], frozenset(h.get("args", {}).items())) == sig
            )
            if count >= 3:
                return f"工具 {tc['name']} 以相同参数被重复调用 {count} 次"

        # 2. 无效交替循环检测 (A→B→A→B)
        if len(recent) >= 4:
            last4 = [(h["name"], frozenset(h.get("args", {}).items())) for h in recent[-4:]]
            if last4[0] == last4[2] and last4[1] == last4[3] and last4[0] != last4[1]:
                return "检测到工具交替循环调用"

        # 3. 无进展检测
        if len(recent) >= 3:
            last3 = [(h["name"], frozenset(h.get("args", {}).items())) for h in recent[-3:]]
            if len(set(last3)) == 1:
                return "连续 3 次工具调用完全相同，无进展"

        return None
```

#### 4.1.3 降级策略

当 ReAct Agent 触发任何安全上限时，按以下优先级降级：

| Agent | 降级路径 |
|-------|---------|
| StockAnalysisAgent | 跳过 ReAct → 确定性调 `analyze_fundamentals` + `_direct_technical_analysis`（仅当用户消息触发关键词时） → 返回结构化结果并标记 `fallback_reason` |
| 未来新增 ReAct Agent | 必须实现 `_fallback(state, reason)` 方法，返回有效的默认 State |

降级结果中必须记录 `fallback_reason` 字段，便于日志和监控：

```python
entry["fallback_reason"] = f"ReAct 安全上限触发: {reason}"
entry["status"] = "degraded"
```

#### 4.1.4 超时保护

```python
def invoke(self, state: AdvisorState) -> AdvisorState:
    import signal  # 仅 Unix；Windows 用 threading + Event
    import threading

    result_container: list = []
    error_container: list[Exception | None] = [None]
    done = threading.Event()

    def _run():
        try:
            result_container.append(self._invoke_internal(state))
        except Exception as exc:
            error_container[0] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_run, daemon=True, name=f"react-{self.agent_name}")
    thread.start()
    if not done.wait(timeout=self.per_invoke_timeout):
        return self._fallback(state, f"ReAct invoke 超时（{self.per_invoke_timeout}s）")

    if error_container[0] is not None:
        return self._fallback(state, str(error_container[0]))
    return result_container[0]
```

#### 4.1.5 ReActAgent 完整配置

```python
class ReActAgent(AgentProtocol):
    # ── 可覆盖的配置 ──
    max_reasoning_steps: int = 10
    max_tool_calls_per_step: int = 2
    per_invoke_timeout: float = 90.0      # invoke 总超时
    tool_call_same_param_limit: int = 3    # 相同参数最多重复次数
    tool_call_history_window: int = 6      # 回溯窗口大小

    # ── 必须实现的方法 ──
    def _get_tools(self) -> list: ...
    def _get_system_prompt(self) -> str: ...
    def _fallback(self, state: AdvisorState, reason: str) -> AdvisorState: ...

    # ── 框架提供的方法 ──
    def invoke(self, state: AdvisorState) -> AdvisorState: ...        # 带安全检测
    def _invoke_internal(self, state: AdvisorState) -> AdvisorState: ...  # 实际 ReAct 执行
    def _check_tool_call_health(self, tool_calls, history) -> str | None: ...
```

#### 4.1.6 StockAnalysisAgent 专属配置

```python
class StockAnalysisAgent(ReActAgent):
    agent_name = "stock_analysis"
    max_reasoning_steps = 6               # 最多 3 轮推理 + 3 次工具调用
    per_invoke_timeout = 60.0             # 单只股票分析 60s
```

6 步足够覆盖"判断意图(1) → 调工具1(2) → 判断是否还要调工具2(3) → 调工具2(4) → 合成结果(5)"的最长路径。

---

## 5. AdvisorState 精简

```
重构前（~35 字段）                    重构后（~20 字段）
─────────────────                    ─────────────────
保留:                                 移除:
  user_message                          slot_tool_calls
  chat_history                          slot_tool_called
  customer_id                           slot_tool_source
  task_plan                             slot_tool_error
  user_profile                          stock_data_entries
  resolved_stocks                       stock_analysis_entries
  candidate_stocks                      intent_clarification_state
  stock_data                            intent_clarification_response
  stock_analysis                        stock_search_error
  technical_analysis                    stock_resolution_error
  allocation_result                     explicit_user_stock_codes
  agent_response                        finance_related
  compliance_result                     intent_stocks
  memory_context                        business_state
  shared_memory_snapshot
  thread_id
  run_id
  detected_intents       ← 多节点共享
  intent_results         ← 多节点共享
  sector_keywords        ← 新增
```

移除的字段说明：
- `slot_tool_*` 系列：ProfileAgent 始终执行，不需要工具决策环节
- `stock_data_entries` / `stock_analysis_entries`：batch handler 内部临时变量
- `intent_clarification_state` / `intent_clarification_response`：SupervisorAgent 内部管理
- `stock_search_error` / `stock_resolution_error`：DataFetchAgent 内部处理，错误写入 `intent_results`
- `explicit_user_stock_codes`：合并入 `resolved_stocks` 的 source 标记
- `finance_related`：仅 supervisor 节点使用，路由后不再需要
- `intent_stocks`：按意图分组的股票列表，ProfileAgent 输出后写入 `intent_results`
- `uncertain_intents`：SupervisorAgent 内部管理，通过 `agent_response` 传达反问
- `business_state`：AssetAllocationAgent 前置校验内部使用

---

## 6. 文件组织总览

```
finance_agent/
├── agents/
│   ├── __init__.py
│   ├── base.py                # AgentProtocol / ProceduralAgent / ReActAgent
│   ├── supervisor.py          # DeepSeekIntentClassifier + SupervisorAgent
│   ├── profile.py             # ProfileAgent（finance_slots 逻辑内迁）
│   ├── data_fetch.py          # DataFetchAgent（BaoStock + MarketSearch 统一入口）
│   ├── stock_analysis.py      # StockAnalysisAgent（ReAct 基本面 + 技术面）
│   ├── asset_allocation.py    # AssetAllocationAgent（MPT + 前置校验）
│   └── compliance.py          # ComplianceAgent（敏感词 + 最终合成）
│
├── core/
│   ├── __init__.py
│   ├── orchestrator.py        # ~300行，图定义 + 路由 + 公共 API
│   ├── state.py               # AdvisorState 定义
│   ├── shared_state.py        # SharedWorkingMemory（保留）
│   ├── memory.py              # AgentMemoryContext（保留）
│   └── database.py            # SQLiteStore（保留）
│
├── data/                      # 🆕 数据源基础设施（不依赖 LangChain）
│   ├── __init__.py
│   ├── baostock.py            # BaostockDataSource（从 tools/ 迁入）
│   └── market.py              # EastMoneyMarketData + SinaMarketData（从 tools/ 迁入）
│
├── tools/                     # LangChain @tool 装饰函数，每个文件服务一个 Agent
│   ├── __init__.py
│   ├── fundamental.py         # DataFetchAgent — get_stock_basic_info/quote/indicators/history
│   ├── web_search.py          # DataFetchAgent — MarketSearch 门面
│   ├── technical.py           # StockAnalysisAgent — compute_all_indicators, calc_macd/kdj/...
│   ├── allocation.py          # AssetAllocationAgent — calculate_stock_metrics, optimize_portfolio
│   └── compliance.py          # ComplianceAgent — check_sensitive_words, SENSITIVE_WORDS
│
├── api/                       # 不变
├── middleware/                # 不变
├── config.py                  # 不变
└── main.py                    # 不变
```

---

## 7. 关键设计决策

### 7.1 为什么 market_overview 直接到 compliance 而不经过 stock_analysis

`market_overview` 的返回结果已经是格式化后的板块排行 Markdown，不涉及具体股票分析。DataFetchAgent 获取板块排行数据后直接生成报告文本存入 `agent_response`，后续无需 StockAnalysis 介入。

### 7.2 为什么 candidate_search 需要两阶段

1. **先搜板块成份股**（东方财富）→ 得到股票列表和板块归属
2. **再调 BaoStock** → 获取每只成份股的行情/财务/K 线数据
3. **然后进入 StockAnalysis** → 对候选池做分析对比

两步之间有自然依赖（需要先知道股票代码才能获取数据），不能合并。

### 7.3 为什么 ProfileAgent 不用 ReAct

ProfileAgent 的逻辑是固定的两级策略（正则 → 正则失败则 LLM），没有需要模型自主决策的多步工具调用。使用 ProceduralAgent 避免不必要的 ReAct 推理开销。

### 7.4 为什么 StockAnalysis 是唯一 ReAct Agent

StockAnalysis 需要根据用户问题动态决定"调用基本面工具/技术面工具/两者/追问"，这是典型的 ReAct 适用场景。其他 Agent 要么是确定性计算（MPT、敏感词扫描），要么是固定顺序的数据获取，过程化更高效。

ReAct Agent 的安全保障（详见 4.1 节）：
- 最大 6 步推理上限（覆盖最长路径：判断 → 调工具1 → 判断 → 调工具2 → 合成）
- 相同参数重复调用 ≥3 次 → 终止
- A→B→A→B 交替循环 → 终止
- 连续 3 次无进展 → 终止
- 单只股票 60s 总超时
- 触发上限 → 自动降级到确定性兜底（基本面 + 技术面直接计算）
- 降级结果标记 `fallback_reason` 和 `status: "degraded"`

### 7.5 为什么 data/ 和 tools/ 分层

- `data/` — 与 LangChain 无关的纯数据源封装，可被任何模块直接引用
- `tools/` — LangChain `@tool` 装饰的函数，专门供 Agent（ReAct 或过程化）调用

这样工具层不关心数据从哪来（BaoStock 还是东方财富），数据层不关心谁在调用它。

---

## 8. 测试策略

### 单元测试

| 目标 | 测试内容 |
|------|---------|
| SupervisorAgent | 意图分类正确性（DeepSeek mock）、task_plan 映射 |
| ProfileAgent | 正则提取、LLM 回退、板块关键词识别 |
| DataFetchAgent | execution_mode 路由、BaoStock mock、MarketSearch mock |
| StockAnalysisAgent | ReAct 工具调用、确定性兜底、降级回退 |
| AssetAllocationAgent | MPT 计算正确性、前置校验、引导语生成 |
| ComplianceAgent | 敏感词扫描、响应合成、多意图组合 |

### 集成测试

| 测试 | 内容 |
|------|------|
| market_overview 路径 | supervisor → profile → data_fetch → compliance |
| security_analysis 路径 | supervisor → profile → data_fetch → stock_analysis → compliance |
| candidate_search 路径 | supervisor → profile → data_fetch → stock_analysis → compliance |
| 多意图路径 | casual_chat + market_query 并行，结果合并 |
| asset_allocation 前置条件 | 字段缺失 → 引导追问，补充后继续 |
| 意图澄清 | 低置信度 → 反问用户 → 解析回复 |

### 回归测试

- 所有现有 `tests/test_*.py` 适配新架构后通过
- SSE 流式接口行为不变
- API 接口签名兼容（或明确记录变化）

---

## 9. 实现计划概览

实现计划由 `writing-plans` skill 生成详细步骤。以下为宏观阶段：

| 阶段 | 内容 |
|------|------|
| Phase 1: 基础设施 | 创建 `AgentProtocol` 基类、精简 `AdvisorState`、迁移 `data/` 层 |
| Phase 2: Agent 重构 | 逐个重构 6 个 Agent，每个 Agent 完成 self-contained |
| Phase 3: Orchestrator | 重写 `_build_graph()` 为 7 节点委托模式 |
| Phase 4: 连接 | Agent 间 State 传递、shared_memory 发布/查询验证 |
| Phase 5: 测试 | 单元测试 + 集成测试 + 回归 |
| Phase 6: 清理 | 删除冗余代码、更新 `tools/__init__.py`、更新 README |

---

## 10. 约束与不变项

- LangGraph StateGraph + checkpoint（SqliteSaver）必须保留
- SharedWorkingMemory 作为 Agent 间通信机制必须保留
- 现有数据源必须保留：BaoStock、东方财富 push2、新浪财经行业接口
- SSE 流式接口和进度回调必须保留
- DeepSeek API 作为唯一 LLM 提供方不变
- Python 3.10+ 不变
