"""成交价格来源：把产品库的最新净值暴露为可注入的 ``NavSource``。

净值只从 ``finance.product_performance`` 的**最新一条**取；取不到就是取不到，
向上抛 ``PricingUnavailableError``，绝不用成本价或 1.0 顶替。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from finance_agent.portfolio.errors import PricingUnavailableError
from finance_agent.portfolio.fees import to_rate


@dataclass(frozen=True)
class NavQuote:
    """一个可用于成交的净值。"""

    product_code: str
    nav: float
    as_of: str = ""
    source: str = "product_performance"


@runtime_checkable
class NavSource(Protocol):
    """按商品代码提供最新净值。"""

    def latest_nav(self, product_code: str) -> NavQuote | None: ...


class ProductLibraryNavSource:
    """从 ``PostgresProductLibrary`` 读取最新净值的实现。"""

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
            # 非正净值不是"便宜"，是数据不可用；用它成交会把成本算成 0 或负数。
            return None
        return NavQuote(
            product_code=str(product_code),
            nav=nav,
            as_of=str(performance.get("as_of") or ""),
            source=str(performance.get("source") or "product_performance"),
        )


def require_nav(source: NavSource, product_code: str, product_name: str = "") -> NavQuote:
    """取净值，缺失时抛 ``PricingUnavailableError``。"""
    quote = source.latest_nav(product_code)
    if quote is None:
        label = f"{product_name}（{product_code}）" if product_name else product_code
        raise PricingUnavailableError(f"{label} 没有可用的最新净值，无法成交")
    return quote


def product_fee_rates(product: dict[str, Any]) -> tuple[float | None, float | None]:
    """从产品记录中解析 (申购费率, 赎回费率) 小数形式；未披露为 ``None``。"""
    basic = product.get("basic_info") or {}
    fee = product.get("fee") or {}
    subscription = fee.get("subscription_fee", basic.get("subscription_fee"))
    redemption = fee.get("redemption_fee", basic.get("redemption_fee"))
    return to_rate(subscription), to_rate(redemption)


__all__ = [
    "NavQuote",
    "NavSource",
    "ProductLibraryNavSource",
    "product_fee_rates",
    "require_nav",
]
