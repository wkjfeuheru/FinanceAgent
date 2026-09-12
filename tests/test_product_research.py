"""确定性产品研究流水线测试。"""

from __future__ import annotations

from finance_agent.product_research.contracts import ProductResearchRequest
from finance_agent.product_research.pipeline import ProductResearchPipeline
from finance_agent.product_research.resolver import ProductReferenceResolver


def _product(
    code: str,
    *,
    name: str = "示例基金",
    risk_level: str = "R2",
    holding_period: str = "long",
    performance_freshness: str = "fresh",
) -> dict:
    return {
        "basic_info": {
            "code": code,
            "name": name,
            "risk_level": risk_level,
            "recommended_holding_period": holding_period,
            "scale": 100.0,
        },
        "fee": {
            "management_fee": 0.01,
            "custody_fee": 0.001,
            "subscription_fee": 0.0,
            "redemption_fee": "0",
        },
        "holdings": {
            "top10": [{"stock_name": "示例股票", "weight": 10.0}],
            "concentration": 10.0,
            "as_of": "2026-09-01",
            "freshness": "fresh",
        },
        "performance": {
            "return_1y": 0.12,
            "max_drawdown": 0.08,
            "volatility": 0.10,
            "as_of": "2026-01-01",
            "freshness": performance_freshness,
        },
    }


class _Gateway:
    def __init__(self, products: list[dict], candidates: dict[str, list[dict]] | None = None):
        self.products = {item["basic_info"]["code"]: item for item in products}
        self.candidates = candidates or {}

    def query_by_codes(self, codes: list[str]) -> list[dict]:
        return [self.products[code] for code in codes if code in self.products]

    def search_by_name(self, name: str) -> list[dict]:
        return list(self.candidates.get(name, []))


def test_name_resolution_returns_ambiguity_instead_of_first_match():
    resolver = ProductReferenceResolver(_Gateway([], {
        "示例基金": [
            {"code": "P001", "name": "示例基金A"},
            {"code": "P002", "name": "示例基金B"},
        ],
    }))

    resolved, ambiguous = resolver.resolve([], ["示例基金"])

    assert resolved == []
    assert ambiguous == ["示例基金"]


def test_stale_performance_is_visible_but_not_usable_for_comparison():
    products = [_product("P001"), _product("P002", name="另一基金", performance_freshness="stale")]
    result = ProductResearchPipeline(_Gateway(products)).analyze(
        ProductResearchRequest(kind="comparison", product_codes=["P001", "P002"])
    )

    second = result.assessments[1]
    assert second.evidences["performance"].freshness == "stale"
    assert second.usable_for_comparison is False
    assert "陈旧" in result.report


def test_stale_holdings_disclose_as_of_without_becoming_a_conclusion():
    product = _product("P001")
    product["holdings"]["freshness"] = "stale"
    product["holdings"]["as_of"] = "2025-01-01"

    result = ProductResearchPipeline(_Gateway([product])).analyze(
        ProductResearchRequest(kind="single", product_codes=["P001"])
    )

    assert "holdings 数据陈旧（截至 2025-01-01）" in result.report
    assert "不得据此生成结论" in result.report


def test_missing_profile_is_research_candidate_without_personal_match_claim():
    result = ProductResearchPipeline(_Gateway([_product("P001")])).analyze(
        ProductResearchRequest(kind="single", product_codes=["P001"])
    )

    assert result.personalization_status == "research_candidate"
    assert "匹配" not in result.report


def test_unknown_source_risk_level_is_data_insufficient():
    result = ProductResearchPipeline(_Gateway([_product("P001", risk_level="未披露")])).analyze(
        ProductResearchRequest(
            kind="single",
            product_codes=["P001"],
            profile={"risk_preference": "稳健", "holding_period": "long"},
        )
    )

    assert result.assessments[0].risk_level is None
    assert result.data_quality != "complete"


def test_complete_profile_reports_risk_and_holding_period_match():
    result = ProductResearchPipeline(_Gateway([_product("P001")])).analyze(
        ProductResearchRequest(
            kind="single",
            product_codes=["P001"],
            profile={"risk_preference": "稳健", "holding_period": "long"},
        )
    )

    assessment = result.assessments[0]
    assert result.personalization_status == "personalized"
    assert assessment.suitability_status == "matched"
    assert "匹配" in result.report


def test_invalid_profile_values_do_not_count_as_personalization():
    result = ProductResearchPipeline(_Gateway([_product("P001")])).analyze(
        ProductResearchRequest(
            kind="single",
            product_codes=["P001"],
            profile={"risk_preference": "未知偏好", "holding_period": "很久"},
        )
    )

    assert result.personalization_status == "research_candidate"
    assert result.assessments[0].suitability_status == "not_evaluated"


def test_product_risk_label_is_normalized_from_source_without_numeric_derivation():
    result = ProductResearchPipeline(_Gateway([_product("P001", risk_level="稳健")])).analyze(
        ProductResearchRequest(
            kind="single",
            product_codes=["P001"],
            profile={"risk_preference": "稳健", "holding_period": "long"},
        )
    )

    assert result.assessments[0].risk_level == "R2"
    assert result.assessments[0].suitability_status == "matched"


def test_risk_normalization_accepts_r_level_with_human_label():
    result = ProductResearchPipeline(_Gateway([_product("P001", risk_level="R2 中低风险")])).analyze(
        ProductResearchRequest(
            kind="single",
            product_codes=["P001"],
            profile={"risk_preference": "R2 中低风险", "holding_period": "long"},
        )
    )

    assert result.assessments[0].risk_level == "R2"
    assert result.assessments[0].suitability_status == "matched"


def test_missing_critical_product_fields_degrade_result_even_without_personalization():
    product = _product("P001")
    product["basic_info"]["recommended_holding_period"] = ""
    product["performance"]["return_1y"] = None

    result = ProductResearchPipeline(_Gateway([product])).analyze(
        ProductResearchRequest(kind="comparison", product_codes=["P001"])
    )

    assert result.data_quality == "warning"
    assert "performance.return_1y" in result.assessments[0].missing_fields
    assert "recommended_holding_period" in result.assessments[0].missing_fields
    assert result.assessments[0].usable_for_comparison is False


def test_missing_product_is_not_replaced_by_placeholder_snapshot():
    result = ProductResearchPipeline(_Gateway([])).analyze(
        ProductResearchRequest(kind="single", product_codes=["P404"])
    )

    assert result.assessments == []
    assert result.product_codes == []
    assert result.data_quality == "critical_missing"
    assert "产品库暂无该产品数据" in result.report
