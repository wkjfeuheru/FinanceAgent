"""消除静默兜底的回归护栏。

三处兜底都可能产出**错结论而非"数据不足"**，因此各自锁定为显式行为：
- 适配度缺值不得默认 50.0（凭空造分、可能改变结论）；
- 逐标的证据无匹配时不得退回整轮事实（污染归属与重放）；
- 评估时点只能取墙钟时必须显式披露不可重放。
"""

from __future__ import annotations

import pytest

from finance_agent.contracts import FactSnapshot
from finance_agent.research.contracts import (
    AnalysisKind,
    AnalysisRequest,
    DataQuality,
    MarketDataSnapshot,
    QuoteSnapshot,
    SecuritySnapshot,
)
from finance_agent.research.pipeline import ResearchPipeline
from finance_agent.research.rule_engine import RuleEngine, load_rules
from finance_agent.research.snapshot_builder import SnapshotBuilder
from datetime import datetime, timezone


def _snapshot(*, indicators: dict, profile_complete: bool = True) -> MarketDataSnapshot:
    request = AnalysisRequest(
        kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"],
        profile_complete=profile_complete,
    )
    quality = DataQuality()
    return MarketDataSnapshot(
        request=request, quality=quality,
        securities=[SecuritySnapshot(
            code="600519",
            quote=QuoteSnapshot(source="fixture", fetched_at=datetime.now(timezone.utc),
                                as_of="2026-09-10", price=10.0),
            history={"adjustment": "forward", "data": [{}] * 60},
            indicators=indicators, quality=quality,
        )],
    )


# ── 兜底 1：适配度不再默认 50 ──────────────────────────────────────────────────

def test_suitability_missing_is_excluded_not_defaulted():
    """画像完整但无 suitability_score 时，不得注入中性 50 分。"""
    snapshot = _snapshot(indicators={
        "fundamental_score": 80, "technical_score": 80, "risk_score": 90,
    })

    assessment = RuleEngine.default().evaluate(snapshot, snapshot.request)

    assert assessment.scores.suitability is None
    # 只按实际可算的三项加权：权重 0.45/0.25/0.20，和为 0.90。
    expected = round((80 * 0.45 + 80 * 0.25 + 90 * 0.20) / 0.90, 2)
    assert assessment.scores.total == expected
    # 若仍默认 50，总分会被拉低——显式断言排除该行为。
    polluted = round((80 * 0.45 + 80 * 0.25 + 90 * 0.20 + 50 * 0.10) / 1.00, 2)
    assert assessment.scores.total != polluted


def test_suitability_present_is_included():
    """确有适配度指标时应计入加权。"""
    snapshot = _snapshot(indicators={
        "fundamental_score": 80, "technical_score": 80, "risk_score": 90,
        "suitability_score": 70.0,
    })

    assessment = RuleEngine.default().evaluate(snapshot, snapshot.request)

    assert assessment.scores.suitability == 70.0
    assert assessment.scores.total == round(
        (80 * 0.45 + 80 * 0.25 + 90 * 0.20 + 70 * 0.10) / 1.00, 2,
    )


def test_suitability_not_scored_without_complete_profile():
    """画像不完整时适配度恒为 None（个性化未启用）。"""
    snapshot = _snapshot(
        indicators={"fundamental_score": 80, "technical_score": 80, "risk_score": 90,
                    "suitability_score": 70.0},
        profile_complete=False,
    )

    assessment = RuleEngine.default().evaluate(snapshot, snapshot.request)

    assert assessment.scores.suitability is None


def test_v1_2_rules_file_declares_its_version():
    rules = load_rules("research_rules/v1.2")
    assert rules["version"] == "research_rules/v1.2"


# ── 兜底 2：证据不得张冠李戴 ───────────────────────────────────────────────────

def test_evidence_never_falls_back_to_other_securities():
    """某标的没有自己的事实时，证据必须为空，绝不引用其他标的的事实。"""
    from finance_agent.research.contracts import SecuritySnapshot as SS

    security = SS(
        code="600519",
        quote=QuoteSnapshot(source="fixture", as_of="2026-09-10", price=10.0),
        history={"adjustment": "forward", "data": [{}] * 60},
        indicators={}, quality=DataQuality(),
    )
    others = [
        FactSnapshot(fact_id="f-600036", domain="stock_research_snapshot", source="fixture",
                     fetched_at=datetime.now(timezone.utc), payload={"code": "600036"}),
        FactSnapshot(fact_id="f-000858", domain="stock_research_snapshot", source="fixture",
                     fetched_at=datetime.now(timezone.utc), payload={"code": "000858"}),
    ]

    owned = ResearchPipeline._evidence_for(security, others)

    assert owned == [], "无匹配事实时不得退回整轮事实"

    mine = FactSnapshot(fact_id="f-600519", domain="stock_research_snapshot", source="fixture",
                        fetched_at=datetime.now(timezone.utc), payload={"code": "600519"})
    assert ResearchPipeline._evidence_for(security, [*others, mine]) == [mine]


# ── 兜底 3：评估时点不可重放必须披露 ───────────────────────────────────────────

class _NoTimestampGateway:
    """所有数据项都缺 fetched_at，触发墙钟回退。"""

    def get_security_data(self, code: str) -> dict:
        return {
            "basic_info": {"code": code},
            "quote": {"code": code, "price": 10.0, "date": "2026-09-10", "adjustment": "raw",
                      "source": "fixture"},          # 无 fetched_at
            "history": {"adjustment": "forward", "source": "fixture",
                        "data": [{"date": "2026-09-10", "close": 10.0}] * 60},  # 无 fetched_at
            "indicators": {"roe": 15.0, "source": "fixture"},  # 无 fetched_at
        }


def test_wallclock_evaluated_at_is_disclosed_as_unreplayable():
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    snapshot, facts = SnapshotBuilder(_NoTimestampGateway()).build(request)

    assert facts[0].payload["evaluated_at_source"] == "wallclock"
    assert "evaluated_at_unavailable" in snapshot.quality.warnings


def test_fetched_at_evaluated_at_is_marked_replayable():
    """有 fetched_at 时必须标记来源为 fetch（可确定性重放）。"""
    fetched = "2026-08-28T08:00:00+00:00"

    class _Gateway:
        def get_security_data(self, code: str) -> dict:
            return {
                "basic_info": {"code": code},
                "quote": {"code": code, "price": 10.0, "date": "2026-09-10",
                          "adjustment": "raw", "source": "fixture", "fetched_at": fetched},
                "history": {"adjustment": "forward", "source": "fixture", "fetched_at": fetched,
                            "data": [{"date": "2026-09-10", "close": 10.0}] * 60},
                "indicators": {"roe": 15.0, "source": "fixture", "fetched_at": fetched},
            }

    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])
    snapshot, facts = SnapshotBuilder(_Gateway()).build(request)

    assert facts[0].payload["evaluated_at_source"] == "fetch"
    assert "evaluated_at_unavailable" not in snapshot.quality.warnings
