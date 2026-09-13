"""模板报告渲染测试：必须披露真实限制项，而不是评分字段名。"""

from __future__ import annotations

from finance_agent.research.contracts import Action, AnalysisResult
from finance_agent.research.narrative import NarrativeRenderer


def _result(**overrides) -> AnalysisResult:
    payload = {
        "action": Action.WAIT,
        "data_quality": "warning",
        "rule_version": "research_rules/v1",
        "scores": {
            "fundamental": 80.0, "technical": 48.33, "risk": 65.0,
            "suitability": None, "total": 69.08,
        },
        "restrictions": ["stale_quote", "custom_reason"],
    }
    payload.update(overrides)
    return AnalysisResult(**payload)


def test_narrative_lists_real_limitations_and_scores():
    text, mode = NarrativeRenderer().render(_result())

    assert mode == "template_fallback"
    assert "确定性研究结论：观望。" in text
    assert "数据质量：warning。" in text
    assert "评分：基本面 80.0、技术面 48.3、风险 65.0、综合 69.1。" in text
    assert "限制与提示：最新报价超过允许的数据新鲜度；custom_reason。" in text


def test_narrative_never_presents_score_names_as_limitations():
    """模板曾把 scores 的键当作限制项输出，必须不再出现。"""
    text, _ = NarrativeRenderer().render(_result())

    limitations = text.split("限制与提示：", 1)[1]
    assert "fundamental" not in limitations
    assert "technical" not in limitations
    assert "total" not in limitations


def test_narrative_reports_no_limitations_when_absent():
    text, _ = NarrativeRenderer().render(_result(restrictions=[]))

    assert "限制与提示：无。" in text


def test_narrative_states_uncomputable_scores_instead_of_zero():
    result = _result(
        action=Action.INSUFFICIENT_DATA,
        data_quality="critical_missing",
        scores={"fundamental": None, "technical": None, "risk": None, "total": None},
        restrictions=["price_history", "fundamental_metrics"],
    )

    text, _ = NarrativeRenderer().render(result)

    assert "评分：不可计算。" in text
    assert "缺少足够的历史收盘价；缺少可用的财务或估值指标。" in text


def test_narrative_deduplicates_reasons_and_keeps_unknown_codes():
    text, _ = NarrativeRenderer().render(
        _result(restrictions=["stale_quote", "stale_quote", "unknown_reason"])
    )

    limitations = text.split("限制与提示：", 1)[1]
    assert limitations.count("最新报价超过允许的数据新鲜度") == 1
    assert "unknown_reason" in limitations


def test_narrative_announces_narrowed_dimension():
    """收窄维度时必须标注口径，避免用户误读为完整评级。"""
    from finance_agent.research.contracts import AnalysisKind, AnalysisRequest

    narrow = _result(request=AnalysisRequest(
        kind=AnalysisKind.SINGLE_STOCK,
        stock_codes=["600519"],
        analysis_type="technical",
    ))

    text, _ = NarrativeRenderer().render(narrow)

    assert "分析维度：技术面（风险始终纳入）。" in text


def test_narrative_omits_dimension_notice_for_both():
    """默认 both 不插入维度句，保持既有报告文本不变。"""
    text, _ = NarrativeRenderer().render(_result())

    assert "分析维度" not in text
