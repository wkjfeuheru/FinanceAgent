# 产品解读专家（ProductAnalysisAgent）详细设计

## 1. 概述

| 属性 | 值 |
|------|-----|
| 模块路径 | `finance_agent/agents/product_analysis.py`（新增） |
| 基类 | `ReActAgent`（LangGraph create_agent + tool calling） |
| agent_name | `product_analysis` |
| 温度 | `0.2`（低温保证数据解读准确） |
| 模型 | `deepseek:deepseek-v4-pro` |
| max_reasoning_steps | `6` |
| per_invoke_timeout | `60.0s` |
| 中间件 | `model_retry`、`content_filter` |

### 职责

- 从用户消息中**自行抽取**产品名称/代码（基金代码如 005827、基金简称如"易方达蓝筹精选"）
- 通过内部 tool calling **查询产品库**获取产品基础信息、持仓、业绩、费率等数据
- 对单只产品进行**深度透视**（概况、投资策略、业绩表现、风险特征）
- 对多只产品进行**对比评估**（收益、风险、费率、规模横向对比）
- 回答用户关于产品的**具体问题**（持仓、基金经理、费率、申赎规则等）
- 将结果写入 `AdvisorState.product_analysis`

---

## 2. 内部工作流

```
用户消息 + requirement + AdvisorState 上下文
          │
          ▼
   ┌──────────────────────┐
   │  1. 字段抽取          │  从用户消息识别产品名称/代码
   │  （LLM + 正则）       │  支持"易方达蓝筹精选" -> 005827
   │                      │  支持"对比基金A和基金B" -> 多产品
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  2. 任务规划          │  根据用户意图决定操作类型：
   │  （ReAct 决策）       │  - 深度透视 -> query_product -> 生成报告
   │                      │  - 对比评估 -> query_product * N -> 对比表
   │                      │  - 具体问题 -> query_product -> 针对性回答
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  3. tool calling      │  调用产品库查询工具获取数据：
   │  查询产品库           │  query_product(code) / list_products()
   │                      │  返回结构化产品数据
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  4. 分析与报告生成    │  - 深度透视：四维报告（概况/策略/业绩/风险）
   │  （LLM 生成）         │  - 对比评估：多维度对比表 + 适用场景建议
   │                      │  - 具体问题：基于数据的事实性回答
   └──────────┬───────────┘
              │
              ▼
   写入 AdvisorState.product_analysis
```

---

## 3. 提示词模板

### 3.1 System Prompt（ReAct 主 prompt）

```
你是金融产品解读专家，专注于对基金、ETF等金融产品进行深度分析和对比评估。

## 可用工具
- `query_product`: 按产品代码或名称查询产品库，返回产品的基础信息、持仓、业绩、费率等结构化数据。
  适用场景：获取单只产品的详细数据进行深度透视或回答具体问题。
  示例：query_product(product_code="005827")

- `list_products`: 列出产品库中的产品列表，支持按类型筛选。
  适用场景：用户未指定具体产品但想了解某类产品概况。
  示例：list_products(product_type="fund")

## 决策规则
1. 用户要求"深度分析/深度透视/全面了解"某只产品
   -> 调用 query_product 获取数据后生成四维透视报告
2. 用户要求"对比/比较"多只产品
   -> 逐只调用 query_product 获取数据后生成对比表
3. 用户询问产品的具体问题（持仓/费率/经理/申赎规则等）
   -> 调用 query_product 获取数据后针对性回答
4. 用户未指定具体产品但询问某类产品
   -> 调用 list_products 获取列表后概述
5. 产品库无该产品数据 -> 明确说明"产品库暂无该产品数据"，不虚构

## 输出规则
- 深度透视报告须包含：产品概况、投资策略、业绩表现、风险特征四个部分
- 对比评估须按收益、风险、费率、规模等维度横向对比，给出差异说明与适用场景建议
- 回答具体问题时基于产品库数据如实回答，不编造
- 数据缺失时明确指出限制
- 使用正式、专业的书面中文
```

### 3.2 深度透视报告生成 Prompt（tool 返回后 LLM 生成）

```
你是金融产品分析专家，请基于以下产品数据生成深度透视报告。

## 产品数据
{product_data_json}

## 报告结构
### 产品概况
- 产品名称、代码、类型、成立日期、规模
- 基金经理、管理时长
- 基金公司

### 投资策略
- 投资目标与策略描述
- 资产配置概况（股/债/现金比例）
- 前十大持仓及集中度

### 业绩表现
- 近期净值与涨跌幅
- 分阶段收益率（近1月/3月/6月/1年/3年）
- 与同类平均/基准对比
- 最大回撤与波动率

### 风险特征
- 风险等级评定
- 波动率与下行风险
- 适合的投资者类型

## 规则
- 基于提供的数据进行分析，不要编造
- 数据缺失时明确指出
- 使用正式、专业的书面中文
```

### 3.3 对比评估报告生成 Prompt

```
你是金融产品分析专家，请基于以下多只产品数据进行对比评估。

## 产品数据
{products_data_json}

## 报告结构
### 对比总览表
| 维度 | 产品A | 产品B | ... |
|------|-------|-------|-----|
| 类型 |       |       |     |
| 规模 |       |       |     |
| 近1年收益 |   |       |     |
| 最大回撤 |   |       |     |
| 费率 |       |       |     |
| 夏普比率 |   |       |     |

### 差异说明
- 逐维度说明关键差异

### 适用场景建议
- 各产品适合的投资者类型与投资目标

## 规则
- 对比维度须包含收益、风险、费率、规模
- 基于数据客观对比，不编造
- 使用正式、专业的书面中文
```

### 3.4 ReAct 输入上下文模板

```
## 当前用户问题
{user_message}

## 需求描述
{requirement}

## 近期对话摘要
{memory_context}

请根据用户问题，判断需要执行哪种产品分析操作，然后调用对应工具获取数据。
```

---

## 4. JSON Schema 数据流

### 4.1 输入（从 AdvisorState 读取）

```json
{
  "user_message": "帮我深度分析一下易方达蓝筹精选这只基金",
  "requirement": "深度分析易方达蓝筹精选",
  "chat_history": [...],
  "memory_context": "..."
}
```

### 4.2 输出（写入 AdvisorState.product_analysis）

**深度透视结果：**
```json
{
  "type": "deep_dive",
  "product_code": "005827",
  "product_name": "易方达蓝筹精选混合",
  "report": "## 产品概况\n...",
  "data": {
    "basic_info": {
      "code": "005827",
      "name": "易方达蓝筹精选混合",
      "type": "混合型基金",
      "establish_date": "2018-09-05",
      "scale": 410.52,
      "manager": "张坤",
      "company": "易方达基金"
    },
    "holdings": {
      "top10": [
        {"name": "贵州茅台", "weight": 9.85},
        {"name": "腾讯控股", "weight": 8.72}
      ],
      "concentration": 65.3
    },
    "performance": {
      "nav": 2.5847,
      "recent_return": {"1m": 2.3, "3m": 5.6, "6m": 8.2, "1y": 12.5, "3y": 45.3},
      "max_drawdown": -32.5,
      "volatility": 22.8
    },
    "fee": {
      "management_fee": 1.5,
      "custody_fee": 0.25,
      "subscription_fee": 1.5,
      "redemption_fee": "持有<7天1.5%, >2年0"
    }
  }
}
```

**对比评估结果：**
```json
{
  "type": "comparison",
  "products": ["005827", "163406"],
  "report": "## 对比总览表\n...",
  "comparison_table": {
    "dimensions": ["类型", "规模", "近1年收益", "最大回撤", "费率", "夏普比率"],
    "data": {
      "005827": {"类型": "混合型", "规模": "410.52亿", ...},
      "163406": {"类型": "混合型", "规模": "280.15亿", ...}
    }
  },
  "differences": ["费率差异：005827管理费1.5% vs 163406管理费1.2%"],
  "recommendations": {
    "005827": "适合追求长期成长、能承受较大回撤的投资者",
    "163406": "适合追求稳健收益、风险偏好较低的投资者"
  }
}
```

---

## 5. Tools 清单

### 5.1 产品库查询 Tools

| 工具名 | 描述 | 参数 | 返回 |
|--------|------|------|------|
| `query_product` | 按代码/名称查询产品库 | `product_code: str` 或 `product_name: str` | `{basic_info, holdings, performance, fee}` JSON |
| `list_products` | 列出产品库产品 | `product_type: str = "fund"` | `[{code, name, type, scale}]` JSON |

### 5.2 产品库数据结构（SQLite 表）

**products 表（产品基础信息）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| code | TEXT PK | 产品代码（如 005827） |
| name | TEXT | 产品名称 |
| type | TEXT | 类型（fund/etf） |
| establish_date | TEXT | 成立日期 |
| scale | REAL | 规模（亿元） |
| manager | TEXT | 基金经理 |
| company | TEXT | 基金公司 |
| management_fee | REAL | 管理费率（%） |
| custody_fee | REAL | 托管费率（%） |
| subscription_fee | REAL | 申购费率（%） |
| redemption_fee | TEXT | 赎回费率描述 |
| risk_level | TEXT | 风险等级 |
| investment_target | TEXT | 投资目标 |
| investment_strategy | TEXT | 投资策略 |

**product_holdings 表（持仓）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| product_code | TEXT FK | 产品代码 |
| stock_name | TEXT | 持仓股票名称 |
| stock_code | TEXT | 持仓股票代码 |
| weight | REAL | 持仓权重（%） |
| rank | INTEGER | 持仓排名 |
| report_date | TEXT | 报告日期 |

**product_performance 表（业绩）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| product_code | TEXT FK | 产品代码 |
| nav | REAL | 最新净值 |
| return_1m | REAL | 近1月收益率（%） |
| return_3m | REAL | 近3月收益率（%） |
| return_6m | REAL | 近6月收益率（%） |
| return_1y | REAL | 近1年收益率（%） |
| return_3y | REAL | 近3年收益率（%） |
| max_drawdown | REAL | 最大回撤（%） |
| volatility | REAL | 波动率（%） |
| sharpe_ratio | REAL | 夏普比率 |
| update_date | TEXT | 更新日期 |

### 5.3 产品库访问层 API

```python
# finance_agent/data/product_library.py
class ProductLibrary:
    """产品库 SQLite 访问层。"""

    def __init__(self, db_path: str = PRODUCT_LIBRARY_DB_PATH):
        """初始化产品库连接。"""

    def query_by_code(self, code: str) -> dict | None:
        """按产品代码查询，返回基础信息+持仓+业绩。"""

    def query_by_name(self, name: str) -> dict | None:
        """按产品名称模糊查询。"""

    def list_products(self, product_type: str = "fund") -> list[dict]:
        """列出指定类型的产品列表。"""

    def upsert_product(self, data: dict) -> bool:
        """写入或更新产品数据。"""

    def upsert_holdings(self, code: str, holdings: list[dict]) -> bool:
        """写入或更新持仓数据。"""

    def upsert_performance(self, code: str, perf: dict) -> bool:
        """写入或更新业绩数据。"""
```

---

## 6. 错误处理与降级

| 场景 | 处理 |
|------|------|
| 产品库无该产品 | 明确说明"产品库暂无该产品数据"，不虚构内容 |
| 产品库连接失败 | 返回"产品库暂时不可用，请稍后重试" |
| 持仓/业绩数据缺失 | 在报告中明确指出"暂无持仓/业绩数据"，仅展示已有字段 |
| 对比时部分产品缺失 | 对缺失产品标注"产品库暂无数据"，仅对比有数据的产品 |
| ReAct 超时 | 降级为直接基于已获取数据生成报告 |
| 产品代码无法识别 | 提示"未识别到产品代码，请提供基金代码（如005827）" |
