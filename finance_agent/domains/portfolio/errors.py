"""模拟交易业务域的显式异常。

与 ``finance_agent.infrastructure.market_data.providers`` 的 ``ProviderError`` 家族同风格：每类失败
都有自己的类型，调用方（REST 路由 / 领域工具）据此映射状态码与安全文案，
而不是分辨裸 ``Exception`` 的字符串。
"""

from __future__ import annotations


def is_unique_violation(exc: BaseException) -> bool:
    """识别持久化适配器传入的唯一键冲突，不依赖基础设施包。"""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if str(getattr(current, "sqlstate", "") or "") == "23505":
            return True
        current = current.__cause__ or current.__context__
    text = str(exc).lower()
    return "duplicate" in text and "unique" in text


class PortfolioError(Exception):
    """模拟交易业务域的基础异常。"""

    #: 供路由与领域工具使用的稳定错误标识。
    code = "portfolio_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProductNotFoundError(PortfolioError):
    """商品不存在。"""

    code = "product_not_found"


class ProductOfflineError(PortfolioError):
    """商品已下架，不可申购。

    下架是软状态（``products.is_active=false``），历史成交与既有持仓都还在，
    因此赎回必须继续放行 —— 只挡买入，否则用户会被困在无法退出的持仓里。
    """

    code = "product_offline"


class PricingUnavailableError(PortfolioError):
    """商品没有可用于成交的净值。

    刻意不回退到 1.0 或跳过：用错误的价格成交会静默污染持仓成本与账户市值。
    """

    code = "pricing_unavailable"


class InsufficientFundsError(PortfolioError):
    """可用资金不足。"""

    code = "insufficient_funds"


class InsufficientSharesError(PortfolioError):
    """持仓份额不足。"""

    code = "insufficient_shares"


class InvalidAmountError(PortfolioError):
    """金额/份额入参非法。"""

    code = "invalid_amount"


class NoPositionError(PortfolioError):
    """该商品没有持仓。"""

    code = "no_position"


__all__ = [
    "InsufficientFundsError",
    "InsufficientSharesError",
    "InvalidAmountError",
    "NoPositionError",
    "PortfolioError",
    "PricingUnavailableError",
    "ProductNotFoundError",
    "ProductOfflineError",
    "is_unique_violation",
]
