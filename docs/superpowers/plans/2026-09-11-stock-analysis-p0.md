# 股票研究 P0 修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使主题请求不再触发候选联网搜索，并使生产原始数据能生成确定性研究评分。

**Architecture:** `StockAnalysisAgent` 先解析请求，仅在非主题且未识别股票的推荐请求中发现候选。新增无状态评分转换器，由 `SnapshotBuilder` 调用，将原始财务指标和前复权 K 线转换为规则引擎现有的三项评分；规则引擎继续只做行动裁决。数据源适配器负责把厂商字段归一化为统一字段名，否则真实取数读不到 `close`/`roe`，评分仍然为空。

**Tech Stack:** Python 3.10+、Pydantic v2、pytest。

## Global Constraints

- 评分函数不得访问网络、调用模型或保存单次调用状态。
- 不采信 Provider 直接提供的 `fundamental_score`、`technical_score`、`risk_score`。
- 缺失可计算的原始数据时必须保留空评分，并通过既有规则输出“数据不足”。
- 不修改当前未提交的主题发现改动。

---

### Task 1: 主题路由先于候选发现

**Files:**
- Modify: `finance_agent/agents/stock_analysis.py`
- Modify: `tests/test_research_pipeline.py`

**Interfaces:**
- Consumes: `parse_analysis_request(message, resolved_stocks, intent_slots, user_profile)`。
- Produces: `AnalysisRequest`；主题请求绝不调用 `search_candidates.invoke`。

- [x] **Step 1: 写入失败测试**

在现有主题路由测试中替换联网行为为失败哨兵：

```python
def test_stock_agent_routes_theme_request_without_candidate_search(monkeypatch):
    class ForbiddenSearch:
        def invoke(self, _payload):
            raise AssertionError("主题请求不得搜索候选股票")

    monkeypatch.setattr("finance_agent.agents.stock_analysis.search_candidates", ForbiddenSearch())
    result = agent.invoke(theme_request_state)
    assert result["theme_screening"]["status"] == "complete"
```

- [x] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_research_pipeline.py::test_stock_agent_routes_theme_request_without_candidate_search`

预期：失败信息为“主题请求不得搜索候选股票”。

- [x] **Step 3: 实现最小路由调整**

将 `StockAnalysisAgent.invoke` 调整为先解析请求。仅当以下条件同时成立时才调用 `_resolve_candidate_codes`：

```python
request.kind.value != "theme_screening"
and not request.stock_codes
and state.get("current_task_intent") == "stock_recommendation"
```

发现候选代码后更新 `resolved_stocks`，并再次调用 `parse_analysis_request`，使其成为唯一的下游输入。

- [x] **Step 4: 验证通过**

运行：`python -m pytest -q tests/test_research_pipeline.py::test_stock_agent_routes_theme_request_without_candidate_search`

预期：通过，且测试不访问数据 Provider。

- [x] **Step 5: 提交**

```bash
git add finance_agent/agents/stock_analysis.py tests/test_research_pipeline.py
git commit -m "fix: bypass candidate lookup for theme research"
```

已提交为 `d0d2017`。

### Task 2: 原始数据确定性评分转换

**Files:**
- Create: `finance_agent/research/scoring.py`
- Modify: `finance_agent/research/snapshot_builder.py`
- Modify: `finance_agent/research/rule_engine.py`
- Modify: `tests/test_research_snapshot_builder.py`
- Modify: `tests/test_research_pipeline.py`
- Modify: `tests/test_theme_screener.py`

**Interfaces:**
- Produces: `build_scores(indicators: dict[str, Any], history: dict[str, Any]) -> tuple[dict[str, float | None], list[str]]`。
- `SnapshotBuilder` 将返回的 `fundamental_score`、`technical_score`、`risk_score` 和 `score_restrictions` 写入 `SecuritySnapshot.indicators`。
- `RuleEngine.evaluate` 将 `score_restrictions` 追加到 `DeterministicAssessment.restrictions`。

- [x] **Step 1: 写入失败测试**

新增包含原始 ROE、营收增长、净利润增长、PE、PB 及 60 根收盘价的网关夹具，并断言：

```python
snapshot, _ = SnapshotBuilder(RawMetricsGateway()).build(request)
scores = snapshot.securities[0].indicators
assert scores["fundamental_score"] is not None
assert scores["technical_score"] is not None
assert scores["risk_score"] is not None
assert RuleEngine.default().evaluate(snapshot, request).action.value != "数据不足"
```

另加缺失原始指标/收盘价测试，断言对应分数为 `None` 且限制项包含 `fundamental_metrics` 或 `price_history`。

- [x] **Step 2: 验证测试按预期失败**

运行：`python -m pytest -q tests/test_research_snapshot_builder.py -k raw_metrics`

预期：失败，因为快照尚未生成三项评分。

- [x] **Step 3: 实现纯评分转换器**

在 `scoring.py` 中实现以下明确规则：

```python
def build_scores(indicators: dict[str, Any], history: dict[str, Any]) -> tuple[dict[str, float | None], list[str]]:
    """从原始财务/估值/K 线构造研究评分及不可计算原因。"""
```

- 基本面：从别名 `roe|roe_wa|roe_dt`、`revenue_yoy|or_yoy`、`netprofit_yoy|profit_yoy`、`pe_ttm|pe`、`pb` 提取数值；各已识别指标分段映射至 0–100 后求均值。一个指标也可评分；没有任何指标则为 `None` 并记录 `fundamental_metrics`。
- 技术面：仅使用至少 60 个有效 `close`；以 MA20/MA60 趋势、20 日动量、20 日收益率标准差构成均分。无足够价格时为 `None` 并记录 `price_history`。
- 风险：用相同收盘价计算年化波动率和最大回撤，再以原始负增长或极高 PE 作为保守惩罚。无足够价格时为 `None` 并记录 `risk_history`。
- 显式删除或覆盖来自 Provider 的三项同名评分，确保所有评分均来自该函数。

- [x] **Step 4: 在快照与规则层接入**

在 `SnapshotBuilder._build_security` 调用 `build_scores` 并覆盖 `indicators` 中三项评分、添加 `score_restrictions`。在 `RuleEngine.evaluate` 将主证券的字符串限制项并入 `restrictions`，再用现有 `_decide_action` 处理评分为空的情形。

- [x] **Step 5: 更新既有测试夹具**

把研究流水线和主题筛选测试中仅提供预制评分的网关替换为同等原始财务字段与有效收盘价序列。保留期望行动结论，确保测试验证转换器而非绕过它。

- [x] **Step 6: 验证通过**

运行：

```bash
python -m pytest -q tests/test_research_snapshot_builder.py tests/test_research_rule_engine.py tests/test_research_pipeline.py tests/test_research_golden.py tests/test_theme_screener.py
```

预期：所有测试通过；主题测试无联网等待。

- [ ] **Step 7: 提交**

```bash
git add finance_agent/research/scoring.py finance_agent/research/snapshot_builder.py finance_agent/research/rule_engine.py tests/test_research_snapshot_builder.py tests/test_research_pipeline.py tests/test_theme_screener.py
git commit -m "fix: derive deterministic research scores from raw data"
```

**已入库说明（2026-09-12 更正）：** 本步骤所列批次已随互咬基线快照 `437235e` 一并入库
（清单本身已过期：`snapshot_builder.py` 依赖同批次新增的 `quality_gates.py`，按原清单提交会
得到无法导入的模块，详见下方"另注"）。复选框保持未勾选，作为历史记录。

### Task 3: 生产取数字段归一化（Task 2 验收后发现的真实阻断）

**背景：** Task 2 完成后评分转换器仍只在测试夹具中生效。默认数据源顺序为 `akshare,tushare_mcp,baostock`，而 AKShare 日线返回中文列（`日期/开盘/收盘/...`）、财务指标返回新浪中文指标名，BaoStock 用 `pctChg/volume/code_name`，Tushare 的 `trade_date` 为 `YYYYMMDD` 且 `get_daily` 拒绝 `adjustment="forward"`。工具层只认英文统一字段，因此真实请求的 K 线全是空值、财务全不命中；更严重的是 AKShare/BaoStock 不支持日估值接口，`get_stock_quote` 取估值抛错会连累整条行情，使快照直接判为 `critical_missing`。

**Files:**
- Create: `finance_agent/data/normalization.py`
- Modify: `finance_agent/data/akshare_provider.py`、`finance_agent/data/baostock_provider.py`、`finance_agent/data/tushare_mcp.py`
- Modify: `finance_agent/orchestrator/tools/stockdata.py`
- Create: `tests/test_data_normalization.py`

- [x] 适配器出口统一字段名与时间顺序：日线 `trade_date/open/high/low/close/vol/amount/change/pct_chg`，估值 `pe/pe_ttm/pb/ps/ps_ttm/total_mv/circ_mv`，财务 `end_date/ann_date/roe/or_yoy/netprofit_yoy`，基础信息 `ts_code/code/name/industry/list_date`；日期统一为 ISO `YYYY-MM-DD`，记录统一按时间升序（最后一行为最新）。
- [x] `get_stock_quote` 的估值取数改为 best-effort，并在行情取数成功后立即读取来源元数据（避免被失败的估值取数覆盖 `last_metadata`）。
- [x] 端到端回归：以中文列 DataFrame 桩驱动真实 `AkshareDataSource` → `fetch_stock_data` → `SnapshotBuilder` → `RuleEngine`，断言三项评分非空、质量状态非 `critical_missing`、行动结论不是“数据不足”。

**已知遗留（不在 P0 范围）：** ~~AKShare 仍不提供日估值接口，纯 AKShare 部署下基本面评分不含 PE/PB~~ —— **该结论已作废**。它引用的 `ak.stock_a_indicator_lg` 已从 AKShare 1.18.94 中删除，而 `ak.stock_value_em` 按股票代码提供日频 `PE(TTM)`/`PE(静)`/`市净率`/`市销率`/`总市值`/`流通市值`（实测 2111 行 × 13 列，起点 `max(2018-01-02, 上市日)`）。日估值、前复权取源与北交所代码等问题已由 `docs/superpowers/plans/2026-09-11-data-source-coverage-p0.md` 处理，事实核查见 `docs/superpowers/specs/2026-09-11-data-source-coverage-design.md`。`get_income` 仍返回厂商原生字段（研究路径未消费）。

**另注：** 本文件 Task 2 的 Step 7 提交清单（`:149`）已过期——`snapshot_builder.py` 现在依赖同批次新增的 `quality_gates.py`，按原清单提交会得到**无法导入**的模块。该批次已随互咬基线快照 `437235e` 一并入库，详见数据源覆盖计划中的说明。

## 验证汇总

- [x] 运行 `python -m pytest -q tests/test_research_contracts.py tests/test_research_request_parser.py tests/test_research_snapshot_builder.py tests/test_research_rule_engine.py tests/test_research_pipeline.py tests/test_research_golden.py tests/test_theme_screener.py tests/test_core_chain.py tests/test_slot_extraction.py`。
- [x] 运行 `python -m compileall -q finance_agent`（`__pycache__` 写入受沙箱限制时以导入校验代替）。
- [x] 全量 `python -m pytest -q`：147 passed。
