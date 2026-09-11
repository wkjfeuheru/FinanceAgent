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
    """提供生产取数层真实可得的原始字段，评分由研究层自行推导。"""

    def get_security_data(self, code: str) -> dict:
        closes = [round(10.0 * 1.004 ** index, 4) for index in range(60)]
        fetched_at = "2026-08-28T08:00:00+00:00"
        return {
            "quote": {
                "source": "fixture", "price": closes[-1], "date": "2026-08-28",
                "adjustment": "raw", "fetched_at": fetched_at,
            },
            "history": {
                "adjustment": "forward",
                "source": "fixture",
                "fetched_at": fetched_at,
                "data": [{"date": "2026-08-28", "close": close} for close in closes],
            },
            "indicators": {
                "roe": 18.0,
                "revenue_yoy": 20.0,
                "netprofit_yoy": 20.0,
                "pe_ttm": 18.0,
                "pb": 2.0,
                "end_date": "2026-06-30",
                "ann_date": "2026-08-25",
                "source": "fixture",
                "fetched_at": fetched_at,
            },
        }


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


def test_screener_rejects_incomplete_rankings_after_data_quality_gate():
    """防止五只有效成员中仅两只可评分时仍声称给出了完整推荐。"""
    class SparseGateway(Gateway):
        def get_security_data(self, code: str) -> dict:
            if code in {"600519", "600520"}:
                return super().get_security_data(code)
            return {"quote": {"source": "fixture", "price": 10}}

    result = ThemeScreener(_repo(5), SparseGateway()).screen(_request(), profile={})

    assert result.status == "insufficient_eligible_coverage"
    assert result.ranked_candidates == []
