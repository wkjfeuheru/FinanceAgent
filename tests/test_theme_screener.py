"""主题筛选覆盖门槛与行业分散化测试。"""

from datetime import datetime, timedelta, timezone

from finance_agent.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.research.screener import ThemeScreener
from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_repository import InMemoryThemeRepository


def _repo(count: int) -> InMemoryThemeRepository:
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


class Gateway:
    def get_security_data(self, code: str) -> dict:
        return {"quote": {"source": "fixture", "price": 10},
                "history": {"adjustment": "forward", "data": [{}] * 60},
                "indicators": {"fundamental_score": 80, "technical_score": 80, "risk_score": 90}}


def _request():
    return AnalysisRequest(kind=AnalysisKind.THEME_SCREENING, theme_id="ai_compute")


def test_screener_requires_five_active_members():
    result = ThemeScreener(_repo(4), Gateway()).screen(_request(), profile={})
    assert result.status == "insufficient_active_coverage"
    assert result.ranked_candidates == []


def test_screener_caps_fine_industry_at_two():
    result = ThemeScreener(_repo(6), Gateway()).screen(_request(), profile={})
    counts = {}
    for item in result.ranked_candidates:
        counts[item.industry] = counts.get(item.industry, 0) + 1
    assert max(counts.values()) <= 2
    assert result.personalization_status == "research_candidate"
