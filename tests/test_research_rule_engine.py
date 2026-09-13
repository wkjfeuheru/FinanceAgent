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

    assert assessment.rule_version == "research_rules/v1.2"


def test_previous_rule_version_still_loads_for_replay():
    """新版本必须**新增**而非替换：审计记录里的旧版本要一直能精确重放。

    v1.1 的规则内容与 v1 相同，区别在评分口径——补上 PE/PB 之后基本面分数由
    5 项而非 3 项平均而成，同样输入会得到不同分数。若直接改写 v1，同一个
    ``(theme_id, stock_code, rule_version, as_of)`` 键上的 upsert 会覆盖掉
    旧口径的历史快照。
    """
    from finance_agent.research.rule_engine import CURRENT_RULES_VERSION, load_rules

    legacy = load_rules("research_rules/v1")
    current = load_rules()

    assert legacy["version"] == "research_rules/v1"
    assert current["version"] == CURRENT_RULES_VERSION
    assert CURRENT_RULES_VERSION != "research_rules/v1"
    # 规则内容完全相同，只有版本标识不同——这正是"口径变了、规则没变"的形态。
    assert {k: v for k, v in legacy.items() if k != "version"} == {
        k: v for k, v in current.items() if k != "version"
    }


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


# ── analysis_type 收窄：按选定维度加权，风险始终纳入 ────────────────────────────

def _request_with(analysis_type: str) -> AnalysisRequest:
    return AnalysisRequest(
        kind=AnalysisKind.SINGLE_STOCK,
        stock_codes=["600519"],
        analysis_type=analysis_type,
        profile_complete=False,
    )


def test_analysis_type_both_matches_full_weighting():
    """默认 both 与收窄前的加权结果完全一致（0.45+0.25+0.20=0.90）。"""
    snapshot = _snapshot(
        quality=DataQuality(),
        indicators={"fundamental_score": 80, "technical_score": 60, "risk_score": 90},
    )

    assessment = RuleEngine.default().evaluate(snapshot, _request_with("both"))

    assert assessment.scores.total == round((80 * 0.45 + 60 * 0.25 + 90 * 0.20) / 0.90, 2)


def test_analysis_type_technical_excludes_fundamental_from_total():
    """technical 模式：基本面不参与加权，分母为 0.25+0.20。"""
    snapshot = _snapshot(
        quality=DataQuality(),
        indicators={"fundamental_score": 10, "technical_score": 60, "risk_score": 90},
    )

    assessment = RuleEngine.default().evaluate(snapshot, _request_with("technical"))

    assert assessment.scores.fundamental is None
    assert assessment.scores.technical == 60.0
    assert assessment.scores.total == round((60 * 0.25 + 90 * 0.20) / 0.45, 2)


def test_analysis_type_fundamental_excludes_technical_from_total():
    """fundamental 模式：技术面不参与加权，分母为 0.45+0.20。"""
    snapshot = _snapshot(
        quality=DataQuality(),
        indicators={"fundamental_score": 80, "technical_score": 10, "risk_score": 90},
    )

    assessment = RuleEngine.default().evaluate(snapshot, _request_with("fundamental"))

    assert assessment.scores.technical is None
    assert assessment.scores.fundamental == 80.0
    assert assessment.scores.total == round((80 * 0.45 + 90 * 0.20) / 0.65, 2)


def test_scoped_dimension_missing_data_still_yields_insufficient():
    """护栏：被选定维度却取不到数据时必须仍判数据不足，不得静默降级。"""
    snapshot = _snapshot(
        quality=DataQuality(),
        indicators={"fundamental_score": None, "technical_score": 60, "risk_score": 90},
    )

    assessment = RuleEngine.default().evaluate(snapshot, _request_with("fundamental"))

    assert assessment.scores.total is None
    assert assessment.action.value == "数据不足"


def test_excluded_dimension_limitations_are_filtered_out():
    """被用户排除的维度不报其缺失限制码，避免制造噪音。"""
    snapshot = _snapshot(
        quality=DataQuality(),
        indicators={
            "fundamental_score": None,
            "technical_score": 60,
            "risk_score": 90,
            "score_restrictions": ["fundamental_metrics", "fundamental_missing:pe_ttm"],
        },
    )

    assessment = RuleEngine.default().evaluate(snapshot, _request_with("technical"))

    assert not any(r.startswith("fundamental") for r in assessment.restrictions)
