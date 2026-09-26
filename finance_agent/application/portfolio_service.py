"""生产环境模拟交易服务的组合根。"""

from __future__ import annotations

from finance_agent.infrastructure.persistence.postgres.registry import (
    get_portfolio_store,
    get_product_library,
)
from typing import Any

from finance_agent.domains.portfolio.pricing import NavQuote
from finance_agent.domains.portfolio.service import PortfolioDeps, PortfolioService

_service: PortfolioService | None = None


class ProductLibraryNavSource:
    """将商品库最新净值适配为领域 NavSource。"""

    def __init__(self, library: Any) -> None:
        self._library = library

    def latest_nav(self, product_code: str) -> NavQuote | None:
        product = self._library.query_by_code(product_code)
        if product is None:
            return None
        performance = product.get("performance") or {}
        raw_nav = performance.get("nav")
        if raw_nav is None:
            return None
        try:
            nav = float(raw_nav)
        except (TypeError, ValueError):
            return None
        if nav <= 0:
            return None
        return NavQuote(
            product_code=str(product_code),
            nav=nav,
            as_of=str(performance.get("as_of") or ""),
            source=str(performance.get("source") or "product_performance"),
        )


def get_portfolio_service() -> PortfolioService:
    """返回注入 PostgreSQL 存储与产品库的单例服务。"""
    global _service
    if _service is None:
        library = get_product_library()
        _service = PortfolioService(PortfolioDeps(
            store=get_portfolio_store(),
            library=library,
            nav_source=ProductLibraryNavSource(library),
        ))
    return _service


__all__ = ["ProductLibraryNavSource", "get_portfolio_service"]
