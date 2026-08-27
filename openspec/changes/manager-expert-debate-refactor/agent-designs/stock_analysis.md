# 股票分析专家（StockAnalysisAgent）详细设计

## 1. 概述

| 属性 | 值 |
|------|-----|
| 模块路径 | `finance_agent/agents/stock_analysis.py` |
| 基类 | `ReActAgent`（LangGraph create_agent + tool calling） |
| agent_name | `stock_analysis` |
| 温度 | `0.3`（适度温度保证分析深度与决策灵活性） |
| 模型 | `deepseek:deepseek-v4-pro` |
| max_reasoning_steps | `6` |
| per_invoke_timeout | `60.0s` |
| 中间件 | `model_retry`、`content_filter` |

### 职责

- 从用户消息中**自行抽取**股票名称/代码
- 通过内部 tool calling **自行获取**行情、财务、K线、新闻等数据
- 基于财务指标进行基本面分析（盈利能力、成长性、估值水平、财务健康）
- 基于K线数据计算技术指标（MACD/KDJ/RSI/BOLL/MA/WR）并解读走势
- 支持候选股票搜索（两阶段 tool calling：板块成份股 -> 逐只基本面）
- 将分析结果写入 `AdvisorState.stock_analysis`

---

## 2. 内部工作流

```
用户消息 + requirement + AdvisorState 上下文
          │
          ▼
   ┌──────────────────────┐
   │  1. 字段抽取          │  从用户消息识别股票名称/代码
   │  （LLM 或正则）       │  支持"贵州茅台"-> 600519 等中文简称
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  2. 任务规划          │  根据用户需求决定分析维度：
   │  （ReAct 决策）       │  - 基本面 -> analyze_fundamentals
   │                      │  - 技术面 -> analyze_technicals
   │                      │  - 全面分析 -> 两者都调用
   │                      │  - 候选搜索 -> search_candidates -> 逐只分析
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  3. tool calling 取数 │  按需调用 @tool 获取数据：
   │  + 分析执行           │  get_stock_quote / get_stock_history
   │                      │  get_financial_indicators / get_stock_basic_info
   │                      │  get_valuation_indicators / get_income_statement
   │                      │  analyze_fundamentals / analyze_technicals
   │                      │  search_candidates
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  4. 结果组装          │  合并分析结果
   │                      │  补全 name/indicators/quote 等展示字段
   └──────────┬───────────┘
              │
              ▼
   写入 AdvisorState.stock_analysis
```

---

## 3. 提示词模板

### 3.1 System Prompt（ReAct 主 prompt）

```
你是股票综合分析专家，拥有基本面分析和技术面分析两种专业能力。

## 可用工具
- `analyze_fundamentals`: 基于财务指标（ROE/PE/PB/利润增速/负债率等）分析基本面。
  适用场景：估值判断、盈利能力评估、财务健康检查、成长性分析。

- `analyze_technicals`: 基于K线数据计算技术指标（MACD/KDJ/RSI/BOLL/MA/WR）并解读走势。
  适用场景：买卖信号、趋势判断、超买超卖、支撑压力位。
  可通过 indicators 参数指定需要的指标，
  如 `analyze_technicals(stock_code="600519", indicators=["MACD","KDJ"])`。

## 决策规则
1. 用户明确提到"基本面/估值/财务/盈利/ROE/PE/PB/负债率"等关键词
   -> 只调用 `analyze_fundamentals`
2. 用户明确提到"技术面/走势/形态/K线/趋势/买卖信号/超买/超卖"或
   具体指标名（MACD/KDJ/RSI/布林/BOLL/均线/MA/WR/威廉）
   -> 只调用 `analyze_technicals`。
   若用户指定了具体指标，通过 indicators 参数传入
3. 用户说"全面分析/综合分析/整体评估"或同时提及两方面关键词
   -> 调用两个工具
4. 若用户指定的指标在技术面工具不覆盖范围内，只计算能支持的指标并如实说明
5. 无法从对话判断意图 -> 不要调用任何工具，追问
   "请问您需要基本面分析（估值、盈利能力等）还是技术面分析（MACD、KDJ等指标走势）？"

## 输出规则
- 只输出用户关心的分析维度，严格对应用户提问范围
- 用户只问技术面 -> 回复只含技术面，不要夹杂基本面内容；反之同理
- 用户指定了具体指标 -> 只输出这些指标的结果和解读，不要把全部指标堆砌上去
- 数据缺失时明确指出限制，不编造数据
- 使用正式、专业的书面中文
```

### 3.2 基本面分析链 Prompt（tool 内部 LLM 调用）

```
你是金融基本面分析专家。

## 身份
你负责分析A股上市公司的基本面情况，为投资决策提供依据。

## 分析维度

### 1. 盈利能力
- ROE（净资产收益率）：>15% 优秀，10-15% 良好，<10% 一般
- 净利率：反映盈利转化效率
- 毛利率：反映产品竞争力

### 2. 成长性
- 营收增长率：>20% 高成长，10-20% 稳健，<10% 低成长
- 净利润增长率：判断成长持续性

### 3. 估值水平
- PE（市盈率）：与行业均值对比
- PB（市净率）：判断是否高估/低估

### 4. 财务健康
- 资产负债率：<50% 健康，50-70% 中性，>70% 风险较高
- 流动比率/速动比率：>2 流动性好

## 输出格式
返回JSON：
{{
  "code": "股票代码",
  "name": "股票名称",
  "profitability": {{"score": 0-100, "analysis": "..."}},
  "growth": {{"score": 0-100, "analysis": "..."}},
  "valuation": {{"score": 0-100, "analysis": "..."}},
  "financial_health": {{"score": 0-100, "analysis": "..."}},
  "overall_score": 0-100,
  "rating": "推荐/中性/谨慎",
  "advantages": ["优势1", "优势2"],
  "risks": ["风险1", "风险2"],
  "summary": "一句话总结"
}}

## 规则
- 基于提供的财务指标数据进行分析，不要编造数据
- 如果数据缺失，明确指出
- 评级标准：overall_score >= 75 推荐，60-75 中性，<60 谨慎
- 语言要求：使用正式、专业的书面中文。不得使用口语化或网络用语表述。
```

Human 模板：
```
股票财务数据：
{financial_data}

请进行基本面分析：
```

### 3.3 ReAct 输入上下文模板（user 消息）

```
## 当前用户问题
{user_message}

## 近期对话摘要
{memory_context（截断到3000字符）}

## 可用数据
- 财务指标：{就绪/缺失}
- K线历史：{就绪/缺失}

请根据用户问题和对话上下文，判断需要执行哪种分析，然后调用对应工具。如无法判断意图请直接追问。
```

---

## 4. JSON Schema 数据流

### 4.1 输入（从 AdvisorState 读取）

```json
{
  "user_message": "分析贵州茅台基本面",
  "requirement": "分析贵州茅台基本面",
  "stock_data": {
    "600519": {
      "quote": {"code": "600519", "price": 1689.5, "change_pct": 1.23},
      "indicators": {"roe": 30.5, "pe": 28.5, "pb": 9.8},
      "basic_info": {"code": "600519", "name": "贵州茅台", "industry": "白酒"},
      "history": {"code": "600519", "data": [{"date": "...", "close": ...}]}
    }
  },
  "chat_history": [...],
  "memory_context": "..."
}
```

### 4.2 输出（写入 AdvisorState.stock_analysis）

```json
{
  "600519": {
    "code": "600519",
    "name": "贵州茅台",
    "overall_score": 85,
    "rating": "推荐",
    "summary": "盈利能力突出，ROE达30.5%，估值处于合理区间",
    "profitability": {"score": 90, "analysis": "ROE 30.5%，盈利能力优秀"},
    "growth": {"score": 75, "analysis": "净利润增速稳健"},
    "valuation": {"score": 70, "analysis": "PE 28.5，高于行业均值"},
    "financial_health": {"score": 85, "analysis": "资产负债率低，流动性好"},
    "advantages": ["盈利能力突出", "财务结构稳健"],
    "risks": ["估值偏高", "增速放缓"],
    "indicators": {"roe": 30.5, "pe": 28.5, "pb": 9.8},
    "quote": {"code": "600519", "price": 1689.5, "change_pct": 1.23},
    "technical_analysis": {
      "overall_score": 50,
      "trend": "多头",
      "signals": ["MACD金叉", "KDJ超卖回升"],
      "indicators": {"MACD": {...}, "KDJ": {...}},
      "summary": "MACD金叉，短期趋势偏多",
      "risks": ["RSI接近超买区"]
    },
    "search_candidate": {}
  }
}
```

---

## 5. Tools 清单

### 5.1 数据获取 Tools（统一使用 Tushare MCP Server）

数据源统一使用 `finance_agent/data/tushare_mcp.py` 的 `TushareMcpDataSource`，替代原 BaoStock 与东方财富/新浪网页抓取。

| 工具名 | 描述 | 参数 | 返回 | Tushare MCP 对应接口 |
|--------|------|------|------|---------------------|
| `get_stock_quote` | 获取最近交易日行情 | `stock_code: str` | `{code, price, change_pct, pe, pb, total_market_cap, ...}` | `get_daily_data`（取最近一天）+ `get_daily_basic`（PE/PB/市值） |
| `get_stock_history` | 获取历史K线数据 | `stock_code: str, start_date: str="", end_date: str=""` | `{code, count, data: [{date, open, close, high, low, volume, change_pct}]}` | `get_daily_data` |
| `get_financial_indicators` | 获取财务指标 | `stock_code: str` | `{code, roe, net_profit_margin, gross_margin, debt_ratio, ...}` | `get_fina_indicator` |
| `get_stock_basic_info` | 获取基本信息 | `stock_code: str` | `{code, name, industry, listing_date, ...}` | `get_stock_basic` |
| `get_valuation_indicators` | 获取估值指标 | `stock_code: str` | `{code, pe, pb, ps, total_market_cap, circ_market_cap, ...}` | `get_daily_basic` |
| `get_income_statement` | 获取利润表 | `stock_code: str` | `{code, revenue, net_profit, operating_profit, ...}` | `get_income`（**新增能力**） |
| `search_candidates` | 搜索候选股票 | `user_query: str, max_results: int=5` | `[{code, name, industry, reason}]` | `get_stock_basic`（按行业过滤）+ `get_daily_data`（取近期涨跌幅排序） |

### 5.2 分析 Tools（保留现有，本地计算）

| 工具名 | 描述 | 参数 | 返回 |
|--------|------|------|------|
| `analyze_fundamentals` | 基本面分析 | `stock_code: str` | JSON（评分/评级/优势/风险） |
| `analyze_technicals` | 技术面分析 | `stock_code: str, indicators: list[str]=None` | JSON（指标结果/信号/趋势） |

### 5.3 候选搜索两阶段 tool calling

```
阶段1: search_candidates(user_query="最近AI行业有什么值得投资的股票")
  -> TushareMcpDataSource.get_stock_basic() 获取全部股票列表
  -> 按行业关键词过滤（如"人工智能"/"半导体"）
  -> get_daily_data 获取候选股票近期涨跌幅排序
  -> 返回 top N 候选: [{code, name, industry, reason}]

阶段2: 对每只候选股票并行调用
  analyze_fundamentals(stock_code="002415")
  get_stock_quote(stock_code="002415")
  -> 汇总为候选分析报告
```

### 5.4 数据源说明

- **统一数据源**：所有股票数据通过 `TushareMcpDataSource` 获取，不再依赖 BaoStock 与东方财富/新浪网页抓取
- **估值指标改进**：原 BaoStock 的 PE/PB 固定为 0，Tushare MCP 的 `get_daily_basic` 提供真实 PE/PB/PS/市值数据
- **利润表新增**：`get_income` 提供利润表数据，可用于更深入的基本面分析
- **交易日历新增**：`get_trade_cal` 可用于判断交易日、过滤非交易日数据

---

## 6. 错误处理与降级

| 场景 | 处理 |
|------|------|
| ReAct 超时（60s） | 降级为 `_fallback_analyze`：直接执行基本面分析链 |
| 工具调用数据缺失 | 返回 `{"rating": "未知", "overall_score": 50, "summary": "无财务数据"}` |
| 股票代码无法识别 | 在回复中明确说明"未识别到股票代码，请提供A股代码" |
| 技术指标数据不足（<30条K线） | 返回错误说明数据不足 |
| RecursionError（推理步数超限） | 返回"分析暂时不可用：推理步数超限" |
| 工具循环调用检测 | `_check_tool_call_health` 检测连续3次相同调用/交替循环，停止重复调用 |
