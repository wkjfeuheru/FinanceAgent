"""版本化确定性评分与风险优先决策测试。"""

from datetime import datetime, timezone

from finance_agent.research.contracts import (
    AnalysisKind,
    AnalysisRequest,
    DataQuality,
    MarketDataSnapshot,
    QuoteSnapshot,
    SecuritySnapshot,
)
from finance_agent.research.rule_engine import RuleEngine


def _snapshot(*, quality: DataQuality, indicators: dict) -> MarketDataSnapshot:
    request = AnalysisRequest(
        kind=AnalysisKind.SINGLE_STOCK,
        stock_codes=["600519"],
        profile_complete=True,
    )
    return MarketDataSnapshot(
        request=request,
        quality=quality,
        securities=[
            SecuritySnapshot(
                code="600519",
                quote=QuoteSnapshot(
                    source="fixture",
                    fetched_at=datetime.now(timezone.utc),
                    as_of="2026-09-10",
                    price=10.0,
                ),
                history={"adjustment": "forward", "data": [{}] * 60},
                indicators=indicators,
                quality=quality,
            )
        ],
    )


def test_rule_version_is_in_assessment():
    """评估结果必须携带可重放的规则版本。"""
    snapshot = _snapshot(
        quality=DataQuality(),
        indicators={"fundamental_score": 80, "technical_score": 80, "risk_score": 90},
    )

    assessment = RuleEngine.default().evaluate(snapshot, snapshot.request)

    assert assessment.rule_version == "research_rules/v1"


def test_good_fundamentals_and_bearish_technicals_are_wait():
    """基本面和技术面冲突时，不得以加权总分直接输出关注。"""
    snapshot = _snapshot(
        quality=DataQuality(),
        indicators={"fundamental_score": 85, "technical_score": 30, "risk_score": 90},
    )

    assessment = RuleEngine.default().evaluate(snapshot, snapshot.request)

    assert assessment.action.value == "观望"
    assert assessment.scores.fundamental_technical_conflict is True


def test_missing_profile_is_research_candidate_not_personal_advice():
    """未补齐画像时不得产生个性化适配评分。"""
    request = AnalysisRequest(
        kind=AnalysisKind.SINGLE_STOCK,
        stock_codes=["600519"],
        profile_complete=False,
    )
    snapshot = _snapshot(
        quality=DataQuality(),
        indicators={"fundamental_score": 80, "technical_score": 80, "risk_score": 90},
    ).model_copy(update={"request": request})

    assessment = RuleEngine.default().evaluate(snapshot, request)

    assert assessment.personalization_status == "research_candidate"
    assert assessment.scores.suitability is None


def test_critical_data_overrides_high_scores():
    """关键数据缺失优先于任何高分，不得给出关注。"""
    quality = DataQuality(status="critical_missing", missing_critical=["adjusted_history"])
    snapshot = _snapshot(
        quality=quality,
        indicators={"fundamental_score": 100, "technical_score": 100, "risk_score": 100},
    )

    assessment = RuleEngine.default().evaluate(snapshot, snapshot.request)

    assert assessment.action.value == "数据不足"


def test_rule_gate_rejects_history_shorter_than_configured_minimum():
    """日线长度门禁必须由版本化规则配置决定。"""
    snapshot = _snapshot(
        quality=DataQuality(),
        indicators={"fundamental_score": 100, "technical_score": 100, "risk_score": 100},
    )
    short_security = snapshot.securities[0].model_copy(
        update={"history": {"adjustment": "forward", "data": [{}] * 59}}
    )
    snapshot = snapshot.model_copy(update={"securities": [short_security]})

    assessment = RuleEngine.default().evaluate(snapshot, snapshot.request)

    assert assessment.action.value == "数据不足"
    assert "minimum_history_bars" in assessment.restrictions
