# 确定性股票分析实施计划

> **供智能代理执行：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项实施本计划。所有步骤使用复选框（`- [ ]`）跟踪。

**目标：** 用确定性、可审计的单股分析与股票比较流水线替换有状态的 ReAct 股票专家；迁移期间保持当前聊天 API 兼容。

**架构：** 不可变的 `AnalysisRequest` 驱动无状态流水线：标准化市场数据快照、执行质量门禁、运行版本化规则，并输出带证据的结构化 `AnalysisResult`。LLM 仅作为可选的文字报告层；兼容适配器负责把新结果投影到旧状态字段。

**技术栈：** Python 3.10+、Pydantic v2、PostgreSQL/psycopg、pytest；LangChain 仅用于可选的报告生成。

## 全局约束

- 默认分析周期为 1–3 个月，使用前复权日线；最新原始报价必须单独标记。
- 基本面优先使用 TTM，并辅以最新季报；每个数据值都必须带来源、报告期、披露日期和 `as_of`。
- 请求类型为 `single_stock`、`comparison`、`theme_screening`；本计划实现前两类，并为第三类提供共享契约。
- 行动结论只能是 `关注`、`观望`、`规避`、`数据不足`。股票专家不得输出目标价、止损价、仓位或资产配置。
- 关键数据缺失和风险门禁优先于评分。不得再用 50 分表示数据缺失。
- 所有规则阈值必须存放在版本化配置文件中；每个结果必须包含 `rule_version` 和证据 ID。
- 在主题推荐治理迁移完成前，保留 `stock_analysis` 和 `technical_analysis` 旧字段投影。

---

## 文件结构

- 新建：`finance_agent/research/__init__.py`——研究领域导出。
- 新建：`finance_agent/research/contracts.py`——请求、快照、质量、证据、评分、行动和结果模型。
- 新建：`finance_agent/research/request_parser.py`——把槽位、消息和状态确定性转换为 `AnalysisRequest`。
- 新建：`finance_agent/research/snapshot_builder.py`——标准化 Provider 数据、溯源、新鲜度和 `FactSnapshot`。
- 新建：`finance_agent/research/rules/v1.json`——已审核的评分阈值与权重。
- 新建：`finance_agent/research/rule_engine.py`——纯评分函数和行动决策函数。
- 新建：`finance_agent/research/pipeline.py`——无状态的请求到结果编排。
- 新建：`finance_agent/research/narrative.py`、`finance_agent/research/legacy_adapter.py`——安全文字输出与旧契约投影。
- 修改：`finance_agent/agents/stock_analysis.py`、`finance_agent/orchestrator/orchestrator.py`、`finance_agent/orchestrator/state.py`、`finance_agent/api/schemas.py`。
- 新建测试：`tests/test_research_contracts.py`、`tests/test_research_request_parser.py`、`tests/test_research_snapshot_builder.py`、`tests/test_research_rule_engine.py`、`tests/test_research_pipeline.py`，以及 `tests/fixtures/research/` 下的固定数据。

### 任务 1：不可变研究契约与请求解析器

**文件：**

- 新建：`finance_agent/research/contracts.py`
- 新建：`finance_agent/research/request_parser.py`
- 测试：`tests/test_research_contracts.py`
- 测试：`tests/test_research_request_parser.py`

**接口：**

- 产出 `parse_analysis_request(message: str, *, resolved_stocks: list[dict], intent_slots: dict, user_profile: dict) -> AnalysisRequest`。
- 产出包含 `request`、`action`、`scores`、`evidence`、`data_quality`、`rule_version`、`narrative` 的 `AnalysisResult`。

- [ ] **步骤 1：编写失败的契约测试**

~~~python
import pytest
from finance_agent.research.contracts import Action, AnalysisKind, AnalysisRequest, AnalysisResult


def test_request_deduplicates_codes_and_requires_kind_shape():
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519", "600519"])
    assert request.stock_codes == ["600519"]
    with pytest.raises(ValueError):
        AnalysisRequest(kind=AnalysisKind.COMPARISON, stock_codes=["600519"])


def test_watch_cannot_be_emitted_with_critical_data_missing():
    with pytest.raises(ValueError, match="critical data"):
        AnalysisResult(action=Action.WATCH, data_quality="critical_missing")
~~~

- [ ] **步骤 2：运行测试并确认导入失败**

运行：`pytest tests/test_research_contracts.py -v`

预期：失败，因为 `finance_agent.research` 尚不存在。

- [ ] **步骤 3：实现封闭的 Pydantic 契约**

~~~python
class AnalysisKind(str, Enum):
    SINGLE_STOCK = "single_stock"
    COMPARISON = "comparison"
    THEME_SCREENING = "theme_screening"


class Action(str, Enum):
    WATCH = "关注"
    WAIT = "观望"
    AVOID = "规避"
    INSUFFICIENT_DATA = "数据不足"


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: AnalysisKind
    stock_codes: list[str] = Field(default_factory=list)
    theme_id: str | None = None
    horizon: Literal["short", "medium", "long"] = "medium"
    indicators: list[str] = Field(default_factory=list)
    profile_complete: bool = False
~~~

添加验证器：保持股票代码顺序、去重合法六位代码；单股请求必须有一只股票，比较请求至少两只，主题筛选必须提供 `theme_id`。

- [ ] **步骤 4：编写解析优先级测试**

~~~python
def test_slots_win_over_message_regex_for_comparison_and_indicators():
    request = parse_analysis_request(
        "比较茅台和招行的MACD",
        resolved_stocks=[{"code": "600519"}, {"code": "600036"}],
        intent_slots={"market_query": {"indicators": ["MACD"]}},
        user_profile={},
    )
    assert request.kind.value == "comparison"
    assert request.stock_codes == ["600519", "600036"]
    assert request.indicators == ["MACD"]
~~~

- [ ] **步骤 5：实现确定性解析**

解析优先级为：槽位 → 已解析股票 → 六位代码正则。通过 `finance_agent.orchestrator.tools.technical.INDICATOR_NAMES` 统一指标别名。只有明确出现比较语义且至少存在两个代码时才判定为比较请求。仅当 `risk_preference` 和 `holding_period` 都非空时设置 `profile_complete`。此模块不得调用模型或数据源。

- [ ] **步骤 6：验证并提交**

运行：`pytest tests/test_research_contracts.py tests/test_research_request_parser.py -v`

预期：全部通过。

~~~bash
git add finance_agent/research tests/test_research_contracts.py tests/test_research_request_parser.py
git commit -m "feat: add deterministic research contracts"
~~~

### 任务 2：可审计市场快照与质量门禁

**文件：**

- 新建：`finance_agent/research/snapshot_builder.py`
- 修改：`finance_agent/orchestrator/tools/stockdata.py`
- 测试：`tests/test_research_snapshot_builder.py`
- 测试：`tests/test_stockdata.py`

**接口：**

- 消费 `AnalysisRequest` 和现有股票数据工具之上的强类型网关。
- 产出 `(MarketDataSnapshot, list[FactSnapshot])`，质量状态为 `complete`、`warning` 或 `critical_missing`。

- [ ] **步骤 1：编写关键数据缺失测试**

~~~python
def test_missing_forward_adjusted_history_is_critical():
    snapshot, facts = builder_with_raw_history.build(single_stock_request("600519"))
    assert snapshot.quality.status == "critical_missing"
    assert "adjusted_history" in snapshot.quality.missing_critical
    assert facts[0].payload["quality_status"] == "critical_missing"
~~~

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_research_snapshot_builder.py::test_missing_forward_adjusted_history_is_critical -v`

预期：失败，因为快照构建器尚不存在。

- [ ] **步骤 3：扩展数据工具的溯源契约**

给 `get_stock_history` 增加 `adjustment: str = "forward"`，返回 `adjustment`、`as_of`、`source`、`fetched_at`、`quality_status`。若 Provider 无法保证请求的复权口径，返回结构化的关键质量缺失；禁止把原始价格冒充为复权价格。

- [ ] **步骤 4：实现快照构建**

~~~python
class SnapshotBuilder:
    def build(self, request: AnalysisRequest) -> tuple[MarketDataSnapshot, list[FactSnapshot]]:
        securities = [self._build_security(code, request) for code in request.stock_codes]
        quality = combine_quality([security.quality for security in securities])
        return MarketDataSnapshot(request=request, securities=securities, quality=quality), self._facts(securities)
~~~

每种数据只获取一次；逐项保留 Provider 与回退来源；股票比较时拒绝混用报告期；按照最近有效交易日判断报价新鲜度。Provider 异常只能在该边界转换为强类型质量原因，不能静默吞掉。

- [ ] **步骤 5：测试已批准的等价数据源回退**

~~~python
def test_equivalent_fallback_is_visible_in_fact_evidence():
    snapshot, facts = builder_with_approved_fallback.build(single_stock_request("600519"))
    assert snapshot.securities[0].quote.source == "baostock"
    assert snapshot.securities[0].quote.fallback_from == "tushare_mcp"
    assert any(f.payload.get("fallback_from") == "tushare_mcp" for f in facts)
~~~

- [ ] **步骤 6：验证并提交**

运行：`pytest tests/test_research_snapshot_builder.py tests/test_stockdata.py -v`

预期：全部通过。

~~~bash
git add finance_agent/research/snapshot_builder.py finance_agent/orchestrator/tools/stockdata.py tests
git commit -m "feat: add auditable stock data snapshots"
~~~

### 任务 3：版本化规则与风险优先决策

**文件：**

- 新建：`finance_agent/research/rules/v1.json`
- 新建：`finance_agent/research/rule_engine.py`
- 测试：`tests/test_research_rule_engine.py`

**接口：**

- `RuleEngine.evaluate(snapshot: MarketDataSnapshot, request: AnalysisRequest) -> DeterministicAssessment` 对固定输入必须是纯函数。
- 评估结果包含分项分数、数据限制、行动结论、个性化状态和 `research_rules/v1`。

- [ ] **步骤 1：编写规则配置和失败测试**

~~~json
{
  "version": "research_rules/v1",
  "weights": {"fundamental": 0.45, "technical": 0.25, "risk": 0.20, "suitability": 0.10},
  "hard_gates": {"minimum_history_bars": 60, "maximum_data_age_trading_days": 1},
  "actions": {"watch_minimum_score": 70, "avoid_maximum_score": 40}
}
~~~

~~~python
def test_rule_version_is_in_assessment():
    assert engine.evaluate(complete_snapshot, profiled_request).rule_version == "research_rules/v1"
~~~

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_research_rule_engine.py::test_rule_version_is_in_assessment -v`

预期：失败，因为 `RuleEngine` 尚不存在。

- [ ] **步骤 3：实现分项函数和行动矩阵**

分别实现 `score_fundamental`、`score_technical`、`score_risk`、`score_suitability`。基本面和估值评分必须有同业基准事实，否则产生关键数据限制；缺少必填画像时，适配结果只能是 `research_candidate`。

~~~python
def decide_action(quality: DataQuality, risk: RiskAssessment, scores: ScoreBreakdown) -> Action:
    if quality.is_critical:
        return Action.INSUFFICIENT_DATA
    if risk.hard_gate_failed:
        return Action.AVOID
    if scores.fundamental_technical_conflict:
        return Action.WAIT
    if scores.total >= rules.watch_minimum_score and risk.is_clear:
        return Action.WATCH
    return Action.AVOID if scores.total <= rules.avoid_maximum_score else Action.WAIT
~~~

- [ ] **步骤 4：测试信号冲突与画像缺失**

~~~python
def test_good_fundamentals_and_bearish_technicals_are_wait():
    assert engine.evaluate(conflicted_snapshot, profiled_request).action.value == "观望"


def test_missing_profile_is_research_candidate_not_personal_advice():
    result = engine.evaluate(complete_snapshot, request_without_profile)
    assert result.personalization_status == "research_candidate"
~~~

- [ ] **步骤 5：验证并提交**

运行：`pytest tests/test_research_rule_engine.py -v`

预期：全部通过。

~~~bash
git add finance_agent/research/rules finance_agent/research/rule_engine.py tests/test_research_rule_engine.py
git commit -m "feat: add versioned stock research rules"
~~~

### 任务 4：无状态流水线与兼容迁移

**文件：**

- 新建：`finance_agent/research/pipeline.py`
- 新建：`finance_agent/research/narrative.py`
- 新建：`finance_agent/research/legacy_adapter.py`
- 修改：`finance_agent/agents/stock_analysis.py`
- 修改：`finance_agent/orchestrator/state.py`
- 修改：`finance_agent/orchestrator/orchestrator.py`
- 修改：`finance_agent/api/schemas.py`
- 测试：`tests/test_research_pipeline.py`
- 修改测试：`tests/test_core_chain.py`、`tests/test_contracts.py`

**接口：**

- `ResearchPipeline.analyze(request, *, user_profile) -> AnalysisResult` 不得拥有单次调用相关的可变实例状态。
- `project_legacy(result) -> dict[str, Any]` 保留现有响应字段并暴露 `analysis_results`。

- [ ] **步骤 1：编写并行隔离失败测试**

~~~python
def test_parallel_pipeline_calls_do_not_share_stock_data():
    first, second = run_in_parallel(
        lambda: pipeline.analyze(single_stock_request("600519"), user_profile={}),
        lambda: pipeline.analyze(single_stock_request("600036"), user_profile={}),
    )
    assert first.request.stock_codes == ["600519"]
    assert second.request.stock_codes == ["600036"]
~~~

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_research_pipeline.py::test_parallel_pipeline_calls_do_not_share_stock_data -v`

预期：失败，因为流水线尚不存在。

- [ ] **步骤 3：实现流水线与安全报告回退**

~~~python
class ResearchPipeline:
    def analyze(self, request: AnalysisRequest, *, user_profile: dict[str, Any]) -> AnalysisResult:
        snapshot, facts = self._snapshot_builder.build(request)
        assessment = self._rule_engine.evaluate(snapshot, request)
        result = AnalysisResult.from_assessment(request, snapshot, assessment, facts)
        return result.model_copy(update={"narrative": self._narrative.render(result)})
~~~

可选 LLM 输出只能包含 summary、advantages、risks、limitations，并必须经过 Pydantic 校验。超时或输出无效时，用固定模板渲染并标记 `report_mode="template_fallback"`；报告层不得修改评分和行动结论。

- [ ] **步骤 4：用薄状态适配器替换 ReAct 实现**

让 `StockAnalysisAgent` 实现 `AgentProtocol`，不再继承 `ReActAgent`。删除 `_current_stock_data`、工具构建、内部基本面 LLM 链、直接 `self.agent.invoke`、关键词兜底和默认 50 分。新实现负责解析状态、执行注入的流水线、追加事实、设置 `analysis_results`、投影旧字段，并如实设置 `success` 或 `degraded`。

- [ ] **步骤 5：测试兼容性和真实状态**

~~~python
def test_critical_data_is_degraded_not_success():
    state = StockAnalysisAgent(pipeline=critical_pipeline).invoke(request_state)
    assert state["intent_results"]["market_query"]["status"] == "degraded"
    assert state["stock_analysis"]["600519"]["rating"] == "数据不足"


def test_legacy_response_and_new_result_coexist():
    response = to_chat_response(response_envelope)
    assert response.stock_analysis["600519"]["code"] == "600519"
    assert response.analysis_results[0]["rule_version"] == "research_rules/v1"
~~~

- [ ] **步骤 6：验证并提交**

运行：`pytest tests/test_research_pipeline.py tests/test_core_chain.py tests/test_contracts.py -v`

预期：全部通过。

~~~bash
git add finance_agent/research finance_agent/agents/stock_analysis.py finance_agent/orchestrator finance_agent/api tests
git commit -m "refactor: replace react stock agent with research pipeline"
~~~

### 任务 5：黄金样本与审计验证

**文件：**

- 新建：`tests/fixtures/research/complete_600519.json`
- 新建：`tests/fixtures/research/conflicted_600519.json`
- 新建：`tests/test_research_golden.py`
- 修改：`finance_agent/orchestrator/orchestrator.py`
- 修改：`tests/test_postgres_audit.py`

**接口：**

- 现有 `ExpertResult.result_data` 保存 `analysis_results`、规则版本和引用的事实 ID。

- [ ] **步骤 1：编写可重放性与审计失败测试**

~~~python
def test_conflicted_fixture_is_wait_not_watch():
    result = pipeline.analyze(load_fixture("conflicted_600519.json"), user_profile=profile)
    assert result.action.value == "观望"


def test_audit_payload_contains_rule_version_and_fact_ids():
    result = make_research_expert_result()
    repository.upsert_expert_result("run-id", "trace-id", result)
    assert "research_rules/v1" in repository.connection.calls[-1].params
~~~

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_research_golden.py tests/test_postgres_audit.py -v`

预期：失败，直到结构化结果被写入现有审计载荷。

- [ ] **步骤 3：通过任务结果构造传递事实**

扩展 `_make_task_result` 和状态合并，让 `analysis_results` 与准确的 `fact_ids` 进入 `ExpertResult.result_data`。本阶段不得创建第二套竞争性的审计通道。

- [ ] **步骤 4：运行完整后端验证并提交**

运行：`pytest -q`

预期：全部通过；测试只使用固定数据和 Fake，不依赖实时 Provider 或 LLM。

~~~bash
git add finance_agent/orchestrator/orchestrator.py tests
git commit -m "test: add reproducible stock research audit fixtures"
~~~

## 自检

- 覆盖：请求类型、无 LLM 控制流、前复权数据、TTM/季报溯源、数据门禁、版本化评分、风险优先行动、画像约束、报告回退、并发安全、API 兼容和审计重放均已映射到任务 1–5。
- 类型一致性：先定义 `AnalysisRequest`，再定义快照；先定义快照，再定义规则引擎；先定义 `AnalysisResult`，再供流水线、适配器、API 和审计使用。
- 自动化测试使用 Fake 和固定样本，不依赖在线 Provider 或模型。

## 执行交接

计划保存在 `docs/superpowers/plans/2026-09-10-deterministic-stock-analysis.md`。

执行方式：

1. **子代理驱动（推荐）**——每个任务使用新的子代理，任务间进行审核。
2. **当前会话执行**——使用 `executing-plans` 分阶段执行，并设置审核检查点。

