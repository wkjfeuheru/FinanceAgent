"""资产配置测算工具测试：纯函数口径、对角近似与降级路径。

全部为纯计算，不需要数据库与模型；收益/波动/回撤均为十进制小数。
"""

from __future__ import annotations

import math

import pytest

from finance_agent.middleware.content_filter import check_sensitive_words
from finance_agent.orchestrator.tools import allocation


# ── 权重工具 ─────────────────────────────────────────────────────


def test_normalize_weights_scales_to_one():
    assert allocation.normalize_weights([3.0, 1.0]) == pytest.approx([0.75, 0.25])


def test_normalize_weights_drops_negative_and_non_numeric():
    # 负值与非数按 0 计，但保持长度（位置语义不能丢）。
    assert allocation.normalize_weights([-1.0, 1.0, "x", 3.0]) == pytest.approx(
        [0.0, 0.25, 0.0, 0.75]
    )


def test_normalize_weights_all_invalid_falls_back_to_equal():
    assert allocation.normalize_weights([0.0, "x", None]) == pytest.approx([1 / 3, 1 / 3, 1 / 3])


def test_equal_weight():
    assert allocation.equal_weight(4) == pytest.approx([0.25] * 4)
    assert allocation.equal_weight(0) == []


def test_inverse_volatility_weights_favors_low_volatility():
    weights = allocation.inverse_volatility_weights([0.08, 0.32])
    assert weights == pytest.approx([0.8, 0.2])


def test_inverse_volatility_weights_skips_non_positive_volatility():
    weights = allocation.inverse_volatility_weights([0.2, 0.0, None])
    assert weights == pytest.approx([1.0, 0.0, 0.0])


def test_risk_budget_weights_without_budgets_equals_inverse_volatility():
    vols = [0.2, 0.1]
    assert allocation.risk_budget_weights(vols) == pytest.approx(
        allocation.inverse_volatility_weights(vols)
    )


def test_risk_budget_weights_scales_by_budget():
    # 预算 3:1，波动相同 → 权重 3:1
    assert allocation.risk_budget_weights([0.2, 0.2], [3.0, 1.0]) == pytest.approx([0.75, 0.25])


def test_constrained_weights_respects_cap():
    weights = allocation.constrained_weights([0.9, 0.05, 0.05], weight_min=0.1, weight_max=0.6)
    assert weights == pytest.approx([0.6, 0.2, 0.2])
    assert max(weights) <= 0.6 + 1e-9 and min(weights) >= 0.1 - 1e-9


def test_constrained_weights_infeasible_bounds_fall_back_to_normalized():
    # 上限 0.1 但 3 个资产下上限和 0.3 < 1 → 约束不可行，退回无约束归一。
    weights = allocation.constrained_weights([1.0, 1.0, 1.0], weight_max=0.1)
    assert weights == pytest.approx([1 / 3, 1 / 3, 1 / 3])


# ── 组合收益与风险 ───────────────────────────────────────────────


def test_portfolio_return_is_weighted_average():
    assert allocation.portfolio_return([0.5, 0.5], [0.10, 0.04]) == pytest.approx(0.07)


def test_portfolio_return_none_when_no_overlap():
    assert allocation.portfolio_return([0.5], [None]) is None


def test_portfolio_volatility_diagonal_approximation():
    # sqrt((0.5*0.2)^2 + (0.5*0.1)^2) = sqrt(0.0125)
    assert allocation.portfolio_volatility([0.5, 0.5], [0.2, 0.1]) == pytest.approx(
        math.sqrt(0.0125)
    )


def test_portfolio_volatility_full_formula_with_correlations():
    w = [0.5, 0.5]
    s = [0.2, 0.1]
    rho = [[1.0, 0.0], [0.0, 1.0]]
    # 相关为 0 时完整式应等于对角近似。
    assert allocation.portfolio_volatility(w, s, rho) == pytest.approx(
        allocation.portfolio_volatility(w, s)
    )
    # 完全正相关 (rho=1) 时 σ_p = Σ wᵢσᵢ = 0.15
    ones = [[1.0, 1.0], [1.0, 1.0]]
    assert allocation.portfolio_volatility(w, s, ones) == pytest.approx(0.15)


def test_portfolio_volatility_none_when_all_zero():
    assert allocation.portfolio_volatility([1.0], [0.0]) is None


def test_portfolio_sharpe_subtracts_risk_free():
    assert allocation.portfolio_sharpe(0.08, 0.2, 0.02) == pytest.approx(0.3)


def test_portfolio_sharpe_none_on_zero_volatility():
    assert allocation.portfolio_sharpe(0.08, 0.0, 0.02) is None


def test_portfolio_max_drawdown_is_weighted_magnitude():
    assert allocation.portfolio_max_drawdown([0.5, 0.5], [0.2, 0.1]) == pytest.approx(0.15)


def test_portfolio_max_drawdown_uses_absolute_value():
    # 传入负数（部分数据源以负值表示回撤）也按幅度计。
    assert allocation.portfolio_max_drawdown([1.0], [-0.25]) == pytest.approx(0.25)


def test_diversification_ratio_above_one_when_imperfect():
    ratio = allocation.diversification_ratio([0.5, 0.5], [0.2, 0.1])
    assert ratio is not None and ratio > 1.0


# ── 集中度与风险贡献 ─────────────────────────────────────────────


def test_concentration_metrics_equal_weight_two_assets():
    metrics = allocation.concentration_metrics([0.5, 0.5])
    assert metrics["hhi"] == pytest.approx(0.5)
    assert metrics["effective_n"] == pytest.approx(2.0)
    assert metrics["top1_weight"] == pytest.approx(0.5)
    assert metrics["top3_weight"] == pytest.approx(1.0)


def test_concentration_metrics_single_asset_is_max_concentrated():
    metrics = allocation.concentration_metrics([1.0])
    assert metrics["hhi"] == pytest.approx(1.0)
    assert metrics["effective_n"] == pytest.approx(1.0)
    assert metrics["position_count"] == 1


def test_concentration_metrics_empty():
    metrics = allocation.concentration_metrics([])
    assert metrics["position_count"] == 0 and metrics["hhi"] is None


def test_risk_contribution_sums_to_one_and_favors_high_vol():
    contrib = allocation.risk_contribution([0.5, 0.5], [0.2, 0.1])
    assert contrib is not None
    assert sum(contrib) == pytest.approx(1.0)
    assert contrib[0] > contrib[1]


# ── 参考区间 ─────────────────────────────────────────────────────


@pytest.mark.parametrize("preference,level", [
    ("保守", "R1"), ("稳健", "R2"), ("平衡", "R3"), ("积极", "R4"), ("激进", "R5"),
])
def test_reference_bands_maps_user_preference(preference, level):
    basis, bands = allocation.reference_bands(preference)
    assert basis == level
    assert bands is not None and set(bands) == {"低风险", "中风险", "高风险"}


def test_reference_bands_generic_when_missing():
    basis, bands = allocation.reference_bands("")
    assert basis == "generic"
    assert bands is None


def test_band_deviation_flags_above_and_below():
    bands = allocation.REFERENCE_BANDS["R1"]  # 低 0.70-0.90, 高 0.00-0.05
    rows = allocation.band_deviation({"低风险": 0.4, "中风险": 0.4, "高风险": 0.2}, bands)
    status = {row["tier"]: row["status"] for row in rows}
    assert status["低风险"] == "below"
    assert status["中风险"] == "above"
    assert status["高风险"] == "above"


def test_band_deviation_empty_without_bands():
    assert allocation.band_deviation({"低风险": 0.5}, None) == []


# ── 汇总入口 ─────────────────────────────────────────────────────


def _holdings():
    return [
        {"product_code": "110011", "product_name": "易方达中小盘混合", "market_value": 60000.0,
         "risk_level": "R3 中风险", "volatility": 0.162, "return_1y": 0.126, "max_drawdown": 0.187},
        {"product_code": "003003", "product_name": "华夏现金增利货币A", "market_value": 40000.0,
         "risk_level": "R1 低风险", "volatility": 0.002, "return_1y": 0.0195, "max_drawdown": 0.0},
    ]


def test_review_portfolio_uses_profile_and_reports_deviations():
    review = allocation.review_portfolio(
        _holdings(), {"cash_balance": 0.0, "total_assets": 100000.0},
        {"risk_preference": "稳健", "holding_period": "中期"},
    )
    assert review["profile_used"] is True
    assert review["risk_preference"] == "R2"
    assert review["tiers"]["低风险"] == pytest.approx(0.4)
    assert review["tiers"]["中风险"] == pytest.approx(0.6)
    assert review["deviations"], "提供了画像就应给出区间偏离"
    assert review["portfolio"]["volatility"] is not None
    assert review["portfolio"]["expected_return"] == pytest.approx(0.4 * 0.0195 + 0.6 * 0.126)
    assert review["reference_weights"]["labels"] == ["110011", "003003"]
    # 权重 0.4/0.6 → HHI 0.52，等效持仓数 1/0.52。
    assert review["concentration"]["hhi"] == pytest.approx(0.52)
    assert review["concentration"]["effective_n"] == pytest.approx(1.9231, abs=1e-4)


def test_review_portfolio_degrades_without_profile():
    review = allocation.review_portfolio(_holdings(), {"cash_balance": 100.0, "total_assets": 101.0})
    assert review["profile_used"] is False
    assert review["risk_preference"] is None
    assert review["deviations"] == []
    assert "profile_missing" in review["limitations"]
    # 缺画像仍要给出集中度与风险暴露。
    assert review["concentration"]["effective_n"] is not None
    assert review["portfolio"]["volatility"] is not None


def test_review_portfolio_marks_missing_volatility_as_partial():
    holdings = _holdings()
    holdings[1].pop("volatility")
    review = allocation.review_portfolio(holdings, {}, {})
    assert "partial_risk_metrics" in review["limitations"]
    # 风险指标只覆盖有波动率的一只，权重归一后为 1.0。
    assert review["portfolio"]["volatility"] == pytest.approx(0.162)


def test_review_portfolio_without_priced_holdings():
    review = allocation.review_portfolio(
        [{"product_code": "999999", "market_value": None}], {}, {},
    )
    assert review["position_count"] == 0
    assert review["limitations"] == ["no_priced_holdings"]
    assert review["unpriced"] == ["999999"]


def test_review_portfolio_unknown_risk_level_goes_to_unclassified():
    review = allocation.review_portfolio(
        [{"product_code": "X", "market_value": 100.0, "risk_level": "未披露", "volatility": 0.1}],
        {}, {},
    )
    assert review["tiers"][allocation.TIER_UNKNOWN] == pytest.approx(1.0)


def test_review_portfolio_cash_ratio():
    review = allocation.review_portfolio(
        _holdings(), {"cash_balance": 25000.0, "total_assets": 125000.0}, {},
    )
    assert review["cash_ratio"] == pytest.approx(0.2)


def test_review_portfolio_declares_zero_correlation_approximation():
    review = allocation.review_portfolio(_holdings(), {}, {})
    assert review["approximation"] == "zero_correlation"
    assert review["assumptions"]["zero_correlation"] is True


# ── 合规：措辞不得命中敏感词 ─────────────────────────────────────


def test_review_notes_do_not_use_banned_words():
    review = allocation.review_portfolio(
        _holdings(), {}, {"risk_preference": "平衡"},
    )
    joined = " ".join(review["notes"])
    assert check_sensitive_words(joined) == []
