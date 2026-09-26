"""产品名称解析（``ProductReferenceResolver``）测试。

确定性产品研究管线（``ProductResearchPipeline``）已删除；产品专家改用 ReAct 工具
（``product_tools``）取数、由模型写评估，因此管线级的字段/报告断言不再适用。
本文件保留解析器契约：歧义不猜测、简称与近似兜底。
"""

from __future__ import annotations

from finance_agent.domains.products.resolver import ProductReferenceResolver


def _product(
    code: str,
    *,
    name: str = "示例基金",
    risk_level: str = "R2",
    holding_period: str = "long",
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
            "freshness": "fresh",
        },
    }


class _Gateway:
    def __init__(self, products: list[dict], candidates: dict[str, list[dict]] | None = None,
                 active_names: list[dict] | None = None):
        self.products = {item["basic_info"]["code"]: item for item in products}
        self.candidates = candidates or {}
        self.active_names = active_names

    def query_by_codes(self, codes: list[str]) -> list[dict]:
        return [self.products[code] for code in codes if code in self.products]

    def search_by_name(self, name: str) -> list[dict]:
        return list(self.candidates.get(name, []))

    def list_active_names(self) -> list[dict]:
        return list(self.active_names or [])


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


def test_name_resolution_falls_back_to_abbreviation_when_like_misses():
    """LIKE 查不到时用简称匹配兜底："易方达中小盘"应命中"易方达中小盘混合"。"""
    resolver = ProductReferenceResolver(_Gateway(
        [_product("110011", name="易方达中小盘混合")],
        candidates={},
        active_names=[{"code": "110011", "name": "易方达中小盘混合"}],
    ))

    resolved, ambiguous = resolver.resolve([], ["易方达中小盘"])

    assert [(item.code, item.name) for item in resolved] == [("110011", "易方达中小盘混合")]
    assert ambiguous == []


def test_name_resolution_falls_back_to_typo_match():
    """错一字的名称（同长度、公共块 ≥2）经近似兜底仍可解析。"""
    resolver = ProductReferenceResolver(_Gateway(
        [_product("000001", name="华夏成长混合")],
        candidates={},
        active_names=[{"code": "000001", "name": "华夏成长混合"}],
    ))

    resolved, ambiguous = resolver.resolve([], ["华夏诚长混合"])

    assert [item.code for item in resolved] == ["000001"]
    assert ambiguous == []


def test_abbreviation_matching_multiple_products_is_ambiguous():
    """简称同时命中多个产品时不得猜测，记为歧义交由上层澄清。"""
    resolver = ProductReferenceResolver(_Gateway(
        [_product("P001", name="华夏成长混合A"), _product("P002", name="华夏成长混合C")],
        candidates={},
        active_names=[
            {"code": "P001", "name": "华夏成长混合A"},
            {"code": "P002", "name": "华夏成长混合C"},
        ],
    ))

    resolved, ambiguous = resolver.resolve([], ["华夏成长混合"])

    assert resolved == []
    assert ambiguous == ["华夏成长混合"]
