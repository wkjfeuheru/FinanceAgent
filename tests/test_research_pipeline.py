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


class CompleteGateway:
    """为并行隔离测试提供两只股票的独立快照。"""

    def get_security_data(self, stock_code: str) -> dict:
        score = 85 if stock_code == "600519" else 75
        return {
            "basic_info": {"code": stock_code, "name": f"测试{stock_code}"},
            "quote": {
                "code": stock_code,
                "price": 10.0,
                "date": "2026-09-10",
                "source": "fixture",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
            "history": {
                "adjustment": "forward",
                "data": [{"high": 10.5, "low": 9.5, "close": 10.0}] * 60,
            },
            "indicators": {
                "fundamental_score": score,
                "technical_score": score,
                "risk_score": 90,
                "suitability_score": 80,
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


def test_stock_agent_routes_theme_request_to_screener_and_keeps_pending_leads_separate():
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
