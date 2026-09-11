"""无状态研究流水线与旧状态投影测试。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from finance_agent.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.research.pipeline import ResearchPipeline
from finance_agent.research.snapshot_builder import SnapshotBuilder
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.research.screener import ThemeScreener
from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_repository import InMemoryThemeRepository
from datetime import timedelta


def _closes(rate: float) -> list[float]:
    """生成 60 根等比收盘价，供确定性的技术面/风险面评分使用。"""
    return [round(10.0 * (1 + rate) ** index, 4) for index in range(60)]


# 夹具使用固定的数据日期与抓取时刻：新鲜度门禁是时间敏感的，用 now() 会让
# 测试结果随系统时钟漂移。
FIXTURE_DAY = "2026-08-28"
FIXTURE_FETCHED_AT = "2026-08-28T08:00:00+00:00"


class CompleteGateway:
    """为并行隔离测试提供两只股票的独立快照。

    只提供生产取数层真实可得的原始字段（财务指标 + 前复权 K 线），
    评分必须由 ``research.scoring`` 从这些原始字段推导。
    """

    def get_security_data(self, stock_code: str) -> dict:
        return {
            "basic_info": {"code": stock_code, "name": f"测试{stock_code}"},
            "quote": {
                "code": stock_code,
                "price": 12.6558,
                "date": FIXTURE_DAY,
                "adjustment": "raw",
                "source": "fixture",
                "fetched_at": FIXTURE_FETCHED_AT,
            },
            "history": {
                "adjustment": "forward",
                "as_of": FIXTURE_DAY,
                "source": "fixture",
                "fetched_at": FIXTURE_FETCHED_AT,
                "data": [
                    {"date": FIXTURE_DAY, "close": close, "high": close * 1.01, "low": close * 0.99}
                    for close in _closes(0.004)
                ],
            },
            "indicators": {
                "roe": 18.0 if stock_code == "600519" else 12.0,
                "revenue_yoy": 20.0,
                "netprofit_yoy": 20.0,
                "pe_ttm": 18.0,
                "pb": 2.0,
                "end_date": "2026-06-30",
                "ann_date": "2026-08-25",
                "source": "fixture",
                "fetched_at": FIXTURE_FETCHED_AT,
                "suitability_score": 80.0,
            },
        }


def _pipeline() -> ResearchPipeline:
    return ResearchPipeline(
        snapshot_builder=SnapshotBuilder(CompleteGateway()),
        rule_engine=RuleEngine.default(),
    )


def test_parallel_pipeline_calls_do_not_share_stock_data():
    """同一流水线实例并行处理不同股票时不得串数据。"""
    pipeline = _pipeline()
    requests = [
        AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"]),
        AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600036"]),
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(
            pool.map(lambda request: pipeline.analyze(request, user_profile={}), requests)
        )

    assert first.request.stock_codes == ["600519"]
    assert second.request.stock_codes == ["600036"]
    assert first.evidence_ids != second.evidence_ids


def test_pipeline_keeps_structured_action_separate_from_narrative():
    """报告文本不得替换确定性行动结论。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    result = _pipeline().analyze(request, user_profile={})

    assert result.action.value == "关注"
    assert result.report_mode == "template_fallback"
    assert result.rule_version == "research_rules/v1"
    assert result.personalization_status == "research_candidate"
    assert "关注" in result.narrative


class CriticalPipeline:
    def analyze(self, request, *, user_profile):
        from finance_agent.research.contracts import Action, AnalysisResult

        return AnalysisResult(
            request=request,
            action=Action.INSUFFICIENT_DATA,
            data_quality="critical_missing",
            rule_version="research_rules/v1",
            scores={"total": None},
            evidence_ids=["fact-critical"],
            narrative="关键数据缺失，无法完成研究。",
            report_mode="template_fallback",
        )


def test_stale_quote_is_reported_and_blocks_the_conclusion():
    """超过允许交易日龄的报价必须降级为“数据不足”并给出原因。"""
    class StaleQuoteGateway(CompleteGateway):
        def get_security_data(self, stock_code: str) -> dict:
            data = super().get_security_data(stock_code)
            data["quote"]["date"] = "2026-08-20"
            return data

    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])
    pipeline = ResearchPipeline(
        snapshot_builder=SnapshotBuilder(StaleQuoteGateway()),
        rule_engine=RuleEngine.default(),
    )

    result = pipeline.analyze(request, user_profile={})

    assert result.data_quality == "critical_missing"
    assert result.action.value == "数据不足"
    assert "stale_quote" in result.restrictions
    assert "最新报价超过允许的数据新鲜度" in result.narrative


def test_pipeline_facts_carry_replay_inputs_and_stable_ids():
    """证据必须包含完整重放输入，且同一输入的两次运行得到同一事实 ID。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])
    pipeline = _pipeline()

    _, first_facts = pipeline.analyze_with_facts(request, user_profile={})
    _, second_facts = pipeline.analyze_with_facts(request, user_profile={})

    payload = first_facts[0].payload
    assert payload["inputs"]["history"]["data"]
    assert payload["inputs"]["indicators"]["roe"] == 18.0
    assert payload["request"]["stock_codes"] == ["600519"]
    assert payload["evaluated_at"] == FIXTURE_FETCHED_AT
    assert payload["provenance"]["quote"]["price_basis"] == "raw"
    assert [fact.fact_id for fact in first_facts] == [fact.fact_id for fact in second_facts]


def test_stock_agent_projects_critical_result_as_degraded():
    agent = StockAnalysisAgent(pipeline=CriticalPipeline())
    state = {
        "requirement": "分析600519",
        "user_message": "分析600519",
        "resolved_stocks": [{"code": "600519"}],
        "intent_slots": {},
        "user_profile": {},
        "intent_results": {},
        "current_task_intent": "market_query",
    }

    result = agent.invoke(state)

    assert result["intent_results"]["market_query"]["status"] == "degraded"
    assert result["stock_analysis"]["600519"]["rating"] == "数据不足"
    assert result["analysis_results"][0]["rule_version"] == "research_rules/v1"


def test_stock_agent_publishes_pipeline_facts_for_audit():
    agent = StockAnalysisAgent(pipeline=_pipeline())
    state = {
        "requirement": "分析600519",
        "resolved_stocks": [{"code": "600519"}],
        "user_profile": {},
        "intent_results": {},
        "current_task_intent": "market_query",
    }

    result = agent.invoke(state)

    evidence_ids = result["analysis_results"][0]["evidence_ids"]
    assert evidence_ids
    assert [fact.fact_id for fact in result["facts"]] == evidence_ids


def _theme_repo(count: int) -> InMemoryThemeRepository:
    repo = InMemoryThemeRepository()
    for index in range(count):
        code = f"600{519 + index:03d}"
        lead = ThemeLead(
            theme_id="ai_compute", stock_code=code, industry=f"行业{index % 3}",
            source_name="fixture", source_class="official", source_uri=f"https://e/{code}",
            evidence_excerpt="公告", evidence_hash=code,
            discovered_at=datetime.now(timezone.utc),
        )
        repo.ingest_lead(lead)
        repo.review_lead(lead.id, reviewer_id="admin", decision="approve",
                         expires_at=datetime.now(timezone.utc) + timedelta(days=30), note="ok")
    return repo


class ThemeGateway(CompleteGateway):
    pass


def test_stock_agent_routes_theme_request_without_candidate_search(monkeypatch):
    """主题筛选不能先调用外部候选搜索。"""
    class CandidateSearch:
        called = False

        def invoke(self, _payload):
            self.called = True
            return []

    search = CandidateSearch()
    monkeypatch.setattr("finance_agent.agents.stock_analysis.search_candidates", search)
    repo = _theme_repo(5)
    lead = ThemeLead(
        theme_id="ai_compute", stock_code="601000", industry="行业0",
        source_name="provider", source_class="public_lead", source_uri="https://e/pending",
        evidence_excerpt="线索", evidence_hash="pending",
        discovered_at=datetime.now(timezone.utc),
    )
    repo.ingest_lead(lead)
    screener = ThemeScreener(repo, ThemeGateway())
    agent = StockAnalysisAgent(pipeline=_pipeline(), theme_screener=screener)

    result = agent.invoke({
        "requirement": "推荐人工智能主题股票",
        "resolved_stocks": [], "intent_slots": {}, "user_profile": {},
        "intent_results": {}, "current_task_intent": "stock_recommendation",
    })

    assert result["theme_screening"]["status"] == "complete"
    assert 3 <= len(result["theme_screening"]["candidates"]) <= 5
    assert result["theme_screening"]["pending_leads"]
    assert all("action" not in lead for lead in result["theme_screening"]["pending_leads"])
    assert result["theme_screening"]["personalization_status"] == "research_candidate"
    assert search.called is False


def test_stock_agent_reports_theme_coverage_shortage():
    agent = StockAnalysisAgent(
        pipeline=_pipeline(), theme_screener=ThemeScreener(_theme_repo(4), ThemeGateway())
    )
    result = agent.invoke({
        "requirement": "推荐人工智能主题股票", "resolved_stocks": [],
        "intent_slots": {}, "user_profile": {}, "intent_results": {},
        "current_task_intent": "stock_recommendation",
    })
    assert result["theme_screening"]["status"] == "insufficient_active_coverage"
    assert result["theme_screening"]["candidates"] == []


def test_stock_agent_returns_theme_clarification_for_unknown_theme():
    agent = StockAnalysisAgent(pipeline=_pipeline(), theme_screener=ThemeScreener(_theme_repo(5), ThemeGateway()))
    result = agent.invoke({
        "requirement": "推荐新能源主题股票", "resolved_stocks": [], "intent_slots": {},
        "user_profile": {}, "intent_results": {}, "current_task_intent": "stock_recommendation",
    })
    assert "主题" in result["clarification_question"]
    assert "股票研究暂不可用" not in result["agent_response"]
