"""统一股票数据 Provider 契约与异常。"""

from __future__ import annotations

from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Provider 未配置、依赖缺失或请求失败时使用的统一异常。"""


class ProviderUnavailableError(ProviderError):
    """Provider 当前不可用。"""


class ProviderTimeoutError(ProviderError):
    """Provider 调用超过统一守门超时（底层请求自身未设超时）。

    与 ``ProviderUnavailableError`` 区分：前者是"这次太久，可能仍在跑"，
    后者是"所有源都试过且都失败了"，审计时意义不同。
    """


class StockDataProvider(Protocol):
    """所有股票数据适配器必须实现的同步业务接口。"""

    provider_name: str

    def is_available(self) -> bool:
        """返回 provider 是否已配置且依赖可用。"""
        ...

    def get_daily(
        self,
        stock_code: str,
        start_date: str = "",
        end_date: str = "",
        adjustment: str = "raw",
    ) -> Any:
        """获取日线行情。"""
        ...

    def get_stock_basic(self, stock_code: str = "") -> Any:
        """获取股票基础信息。"""
        ...

    def get_daily_basic(self, stock_code: str, start_date: str = "", end_date: str = "") -> Any:
        """获取估值指标。"""
        ...

    def get_financial_indicator(self, stock_code: str) -> Any:
        """获取财务指标。"""
        ...

    def get_income(self, stock_code: str) -> Any:
        """获取利润表。"""
        ...

    def get_trade_cal(self, start_date: str = "", end_date: str = "") -> Any:
        """获取交易日历。"""
        ...

    def get_index_daily(
        self,
        index_symbol: str,
        start_date: str = "",
        end_date: str = "",
    ) -> Any:
        """获取指数日线行情（指数符号须带市场前缀，如 ``sh000001``）。"""
        ...

    def get_market_breadth(self) -> Any:
        """获取市场宽度（涨跌家数/涨跌停/活跃度，最近交易日快照）。"""
        ...

    def get_margin_summary(self) -> Any:
        """获取两市融资融券汇总（日频；金额单位：亿元）。"""
        ...

    def get_northbound_holdings(self) -> Any:
        """获取北向持股市值（季度披露；金额单位：亿元）。"""
        ...

    def get_policy_news(self) -> Any:
        """获取近期财经快讯（政策新闻候选；按时间倒序）。

        出口为统一记录列表：``datetime/title/content/source``。时间窗口与条数
        上限由调用方（工具层）截断，provider 只负责取回原始快讯。
        """
        ...


class UnsupportedProviderCapability(ProviderError):
    """Provider 不支持请求的能力。"""
