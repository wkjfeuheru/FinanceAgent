# 股票分析 Agent 技术面扩展设计

**日期**: 2026-07-28
**状态**: 已完成并合入 main 分支（28 commits, 69/69 测试通过）

---

## 一、目标

将现有 `FundamentalAnalysisAgent` 改造为 `StockAnalysisAgent`，使其能根据用户输入自动决策执行**基本面分析**、**技术面分析**或**两者兼有**。当模型无法判断用户意图时（置信度不足），主动追问澄清。

## 二、核心决策

| 决策项 | 选择 |
|--------|------|
| Agent 架构 | 改造现有 `FundamentalAnalysisAgent` 为 `StockAnalysisAgent` |
| 工具决策机制 | Agent 内 ReAct（`create_react_agent` + `bind_tools`） |
| 技术指标计算 | 基于 `get_stock_history` K线数据纯 Python 自算，零外部依赖 |
| 技术指标范围 | MACD, KDJ, RSI, BOLL, MA(5/10/20/60), WR(10/6) |
| 上下文注入 | 近期对话摘要 + 当前问题 + 可用数据描述 |
| 追问机制 | ReAct 推理判断意图模糊时，不调工具，直接追问 |
| 按需输出 | 用户指定指标则只输出指定指标，答非所问不可接受 |

## 三、文件变更

### 3.1 新增文件

- `finance_agent/tools/technical_indicators.py` — 技术指标计算模块（纯 Python）

### 3.2 修改文件

- `finance_agent/agents/stock_analysis.py` — 重构：`FundamentalAnalysisAgent` → `StockAnalysisAgent`
- `finance_agent/agents/__init__.py` — 更新导出符号
- `finance_agent/core/orchestrator.py` — 更新 Agent 引用和导入
- `finance_agent/tools/__init__.py` — 导出新技术指标模块

### 3.2 实施中额外修改的文件（偏离计划）

- `finance_agent/core/memory.py` — Bug fix: 用户画像读写从 checkpoint 迁移到 `finance_agent.db` 的 SQLite 持久化，恢复丢失的历史数据；删除废弃的 `_profile_thread_id` 辅助函数
- `finance_agent/agents/fundamental_analysis.py` — 已删除，被 `stock_analysis.py` 替代
- `tests/` — 将 `fundamental_agent` 引用更新为 `stock_agent`
- `README.md` — 新增技术面分析功能描述，更新工作流图

### 3.3 最终提交统计

- **29 commits** on main, **69/69 tests** passing, working tree clean
- 新增文件: `technical_indicators.py` (520行), `stock_analysis.py` (562行)
- 修改文件: `orchestrator.py`, `__init__.py` (agents+tools), `memory.py`, `config.py`, `README.md`
- 删除文件: `fundamental_analysis.py`
- 不变文件: `supervisor.py`, `data_fetch.py`, `shared_state.py`

- `finance_agent/agents/supervisor.py` — 未新增意图，未修改分类逻辑
- `finance_agent/agents/data_fetch.py` — K线数据已通过 `get_stock_history` 获取，无需修改
- `finance_agent/core/shared_state.py` — 未修改

## 四、架构设计

### 4.1 Agent 结构

```
StockAnalysisAgent (extends BaseFinanceAgent)
├── agent_name = "stock_analysis"
├── _get_tools() → [analyze_fundamentals, analyze_technicals]
├── _get_system_prompt() → 返回综合分析系统提示词（含决策规则）
├── analyze_fundamentals(code)      ← 复用现有逻辑，改为 tool 包装
├── analyze_technicals(code, indicators?)  ← 新增，K线→指标→LLM解读
├── handle_single_stock(code)       ← 扩展，通过 ReAct 同时支持两种分析
└── handle()                        ← 保持兼容
```

### 4.2 工具定义

```python
@tool
def analyze_fundamentals(stock_code: str) -> str:
    """基本面分析。读取共享内存中的 financial_indicator_{code}
    和 stock_basic_info_{code}，由 LLM 生成结构化分析结果。"""

@tool
def analyze_technicals(
    stock_code: str,
    indicators: list[str] | None = None,
) -> str:
    """技术面分析。读取共享内存中的 stock_history_{code}，
    计算指定技术指标（MACD/KDJ/RSI/BOLL/MA/WR），
    由 LLM 生成结构化分析结果。
    
    indicators=None 表示计算全部默认指标；
    传入列表如 ["MACD","KDJ"] 则只计算指定指标。"""
```

### 4.3 数据流

```
用户输入 → Supervisor(intent → task_plan 含 fundamental_analysis)
  → data_fetch_batch: get_stock_history + get_financial_indicators
  → fundamental_batch → StockAnalysisAgent.handle_single_stock(code)
    → ReAct Agent 收到上下文:
      {
        "conversation_summary": "用户之前问过MACD金叉...",
        "current_question": "全面分析茅台",
        "available_data": "财务指标 + K线(最近一年日线) 均已就绪"
      }
    → ReAct 推理:
      情况A: 用户明确基本面 → tool_call: analyze_fundamentals("600519")
      情况B: 用户明确技术面 → tool_call: analyze_technicals("600519", ["MACD","KDJ"])
      情况C: 两者都要     → tool_call: 两个都调
      情况D: 意图模糊     → 不调工具，追问"您需要基本面还是技术面分析？"
    → 汇总 tool 结果 → 返回 dict
  → compliance → final_snapshot → 用户
```

## 五、技术指标计算模块

`finance_agent/tools/technical_indicators.py`

### 5.1 函数签名

```python
def calc_ma(close: list[float], periods: list[int] = [5, 10, 20, 60]) -> dict
def calc_macd(close: list[float], fast=12, slow=26, signal=9) -> dict
def calc_kdj(high, low, close, n=9, m1=3, m2=3) -> dict
def calc_rsi(close: list[float], periods: list[int] = [6, 12, 24]) -> dict
def calc_boll(close: list[float], period=20, std=2) -> dict
def calc_wr(high, low, close, periods: list[int] = [10, 6]) -> dict
```

### 5.2 返回结构

每个函数返回 dict，包含原始值和关键判断：

```python
# 以 MACD 为例
{
    "name": "MACD",
    "params": {"fast": 12, "slow": 26, "signal": 9},
    "latest": {"DIF": 0.52, "DEA": 0.38, "histogram": 0.28},
    "signal": "金叉" | "死叉" | None,  # 最近一次交叉方向
    "divergence": "顶背离" | "底背离" | None,  # 简化判断
    "trend": "多头" | "空头" | "震荡",
    "values": {  # 最近5个交易日的值
        "2026-07-22": {"DIF": 0.41, "DEA": 0.35, "histogram": 0.12},
        # ...
    }
}
```

### 5.3 指标计算逻辑

| 指标 | 核心公式 | 关键判断 |
|------|---------|---------|
| MA | SMA = sum(close[-n:]) / n | 价格与各均线位置关系 |
| MACD | DIF=EMA12-EMA26, DEA=EMA(DIF,9), 柱=2*(DIF-DEA) | DIF上穿DEA→金叉；下穿→死叉 |
| KDJ | RSV→K→D→J, J=3*K-2*D | K>80超买, K<20超卖; K上穿D金叉 |
| RSI | RS=avg_gain/avg_loss, RSI=100-100/(1+RS) | >80超买, <20超卖 |
| BOLL | MID=MA20, UPPER/LOWER=MID±2*σ | 价格触及上/下轨, 带宽变化 |
| WR | WR=(HIGHn-CLOSE)/(HIGHn-LOWn)*-100 | >-20超买, <-80超卖 |

## 六、ReAct Agent 系统提示词

```markdown
你是股票综合分析专家，拥有基本面分析和技术面分析两种专业能力。

## 可用工具
- `analyze_fundamentals`: 基于财务指标（ROE/PE/PB/利润增速/负债率等）分析基本面。适用场景：估值判断、盈利能力评估、财务健康检查、成长性分析。

- `analyze_technicals`: 基于K线数据计算技术指标（MACD/KDJ/RSI/BOLL/MA/WR）并解读走势。适用场景：买卖信号、趋势判断、超买超卖、支撑压力位。可通过 indicators 参数指定需要的指标，如 `analyze_technicals(stock_code="600519", indicators=["MACD","KDJ"])`。

## 决策规则
1. 用户明确提到"基本面/估值/财务/盈利/ROE/PE/PB/负债率"等关键词 → 只调用 `analyze_fundamentals`
2. 用户明确提到"技术面/走势/形态/K线/趋势/买卖信号/超买/超卖"或具体指标名（MACD/KDJ/RSI/布林/BOLL/均线/MA/WR/威廉） → 只调用 `analyze_technicals`。若用户指定了具体指标，通过 indicators 参数传入
3. 用户说"全面分析/综合分析/整体评估"或同时提到两方面关键词 → 调用两个工具
4. 若用户指定的指标在技术面工具不覆盖范围内，只计算能支持的指标并如实说明。
5. 无法从对话判断意图 → 不要调用任何工具，追问"请问您需要基本面分析（估值、盈利能力等）还是技术面分析（MACD、KDJ等指标走势）？"

## 输出规则
- 只输出用户关心的分析维度，严格对应用户提问范围
- 用户只问技术面 → 回复只含技术面，不要夹杂基本面内容；反之同理
- 用户指定了具体指标 → 只输出这些指标的结果和解读，不要把全部指标堆砌上去
- 数据缺失时明确指出限制，不编造数据
- 使用正式、专业的书面中文
```

## 七、handle_single_stock 重构

将现有直接调用 `self.analyze()` 的方式改为通过 ReAct Agent 执行：

```python
def handle_single_stock(self, code: str) -> dict:
    """分析单只股票，写入共享内存。通过 ReAct Agent 自主决策
    执行基本面分析、技术面分析或两者。"""
    
    # 1. 构建上下文
    indicators = self.shared_memory.query(f"financial_indicator_{code}", {})
    basic_info = self.shared_memory.query(f"stock_basic_info_{code}", {})
    history = self.shared_memory.query(f"stock_history_{code}", {})
    
    # 2. 构建消息
    context = self._build_analysis_context(code, indicators, basic_info, history)
    
    # 3. ReAct Agent 执行（带 checkpoint）
    result = self.agent.invoke({"messages": [{"role": "user", "content": context}]})
    
    # 4. 解析结果并写入共享内存
    ...
```

`_build_analysis_context` 负责把**近期对话摘要 + 当前用户问题 + 可用数据描述**打包为一条消息注入 ReAct Agent。

`handle_single_stock` 签名扩展为：

```python
def handle_single_stock(
    self, code: str,
    user_message: str = "",
    memory_context: str = "",
    chat_history: list[dict] | None = None,
) -> dict:
```

其中 `user_message` 和 `memory_context`（含对话摘要）从 `fundamental_batch_handler` 中 `state` 传入。这两个字段可选且默认空，保持向后兼容。

返回结果扩展为：

```python
{
    "code": str,
    "rating": str,
    "summary": str,
    "overall_score": float,
    # 基本面字段（原有）
    "profitability": {...}, "growth": {...}, "valuation": {...}, ...
    # 技术面字段（新增，仅当调用了技术面工具时存在）
    "technical_analysis": {
        "overall_score": float,
        "trend": "上升/下降/震荡",
        "signals": ["MACD金叉", "KDJ超卖", ...],
        "indicators": {
            "MACD": {...}, "KDJ": {...}, ...  # 仅含实际计算的指标
        },
        "summary": "技术面总结",
        "risks": ["顶背离风险", ...]
    }
}
```

## 八、Orchestrator 适配

修改点：

```python
# 导入变更
from finance_agent.agents.stock_analysis import StockAnalysisAgent  # was FundamentalAnalysisAgent

# 实例化变更
self.stock_agent = StockAnalysisAgent(
    shared_memory=self.shared_memory, checkpointer=self.checkpointer,
)

# fundamental_batch_handler 中引用变更
entry = self.stock_agent.handle_single_stock(code)

# _build_fundamental_summary 可保留（技术面结果附加到分析 dict 中，报告生成时合并）
```

在 `AdvisorState` 中新增可选字段：
```python
stock_analysis: Dict[str, Any]         # 股票综合分析结果（改名自 fundamental_analysis）
technical_analysis: Dict[str, Any]     # 技术面分析结果
```

在 `handle_message_locked` 返回中将 `"fundamental_analysis"` 更名为 `"stock_analysis"`。

## 九、错误处理

| 场景 | 处理方式 |
|------|---------|
| K线数据缺失 | `analyze_technicals` 返回 `{"error": "无K线数据，无法进行技术面分析"}` |
| BaoStock 获取失败 | 与现有 `handle_single_stock` 相同的错误标记机制 |
| 技术指标计算异常 | catch 后返回 `{"error": "指标计算失败: ..."}` |
| ReAct Agent 执行超时 | 降级为仅基本面分析（兼容旧行为） |


## 十、兼容性

- 原有只问基本面的用户请求，行为不变（ReAct 会自然只调 `analyze_fundamentals`）
- `handle()` 方法签名保持不变
- 共享内存中新增 `technical_analysis_{code}` fact，但下游 Agent 可选读取
- 现有 checkpoint 数据格式兼容
- `handle_message_locked` 返回中 `fundamental_analysis` 更名为 `stock_analysis`
- 用户画像读写从 checkpoint 迁移到 `finance_agent.db` 的 SQLite 持久化
