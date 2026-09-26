"""BaoStock 股票数据适配器。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from finance_agent.infrastructure.market_data.board_codes import baostock_symbol, canonical_index
from finance_agent.infrastructure.market_data.normalization import (
    normalize_basic_records,
    normalize_daily_records,
    normalize_index_daily_records,
    normalize_trade_cal_records,
    normalize_valuation_records,
)
from finance_agent.infrastructure.market_data.providers import ProviderUnavailableError, UnsupportedProviderCapability
from finance_agent.infrastructure.market_data.quote_cache import read as cache_read
from finance_agent.infrastructure.market_data.quote_cache import write as cache_write

# 估值字段在 adjustflag=3/2/1 三种口径下数值完全相同（实测），因为它们是按
# 不复权价计算的，与复权口径无关。因此这里固定用 3（不复权），并与行情请求分离。
_VALUATION_FIELDS = "date,peTTM,pbMRQ,psTTM,pcfNcfTTM"
_VALUATION_KEYS = ("pe_ttm", "pb", "ps_ttm")


def _date(value: str, fallback: datetime) -> str:
    """将日期转换为 BaoStock 所需的 YYYY-MM-DD 格式。"""
    return value or fallback.strftime("%Y-%m-%d")


def _has_valuation(row: dict[str, Any]) -> bool:
    """判断该行是否含真实估值数值。

    BaoStock 在停牌或无数据的交易日会返回空串。若不过滤，``_latest_daily_record``
    取到的"最新一根"可能全是空值，估值看起来仍然缺失。
    """
    for key in _VALUATION_KEYS:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            float(value)
        except (TypeError, ValueError):
            continue
        return True
    return False


def _coerce_valuation(row: dict[str, Any]) -> dict[str, Any]:
    """把估值字段转成数值。

    BaoStock 的 socket 协议把所有字段返回为**字符串**（``"18.0"``），而 AKShare
    返回 float。同一能力在两个 provider 之间形状不一致会直接泄漏到报价契约里
    （``quote["pe"]`` 变成字符串），因此在适配器出口统一。
    """
    coerced = dict(row)
    for key in _VALUATION_KEYS:
        value = coerced.get(key)
        if value in (None, ""):
            continue
        try:
            coerced[key] = float(value)
        except (TypeError, ValueError):
            pass
    return coerced


class BaostockDataSource:
    """通过可选 BaoStock 依赖提供统一股票数据接口。"""

    provider_name = "baostock"

    def __init__(self) -> None:
        try:
            import baostock as bs
        except ImportError as exc:
            raise ProviderUnavailableError("BaoStock 未安装") from exc
        self.bs = bs

    def is_available(self) -> bool:
        """返回 BaoStock 是否可导入。"""
        return self.bs is not None

    def _query(self, result: Any) -> list[dict[str, Any]]:
        """将 BaoStock ResultSet 转换为记录列表并检查错误。"""
        if getattr(result, "error_code", "0") != "0":
            raise RuntimeError(getattr(result, "error_msg", "BaoStock 查询失败"))
        fields = list(getattr(result, "fields", []) or [])
        rows = []
        while result.next():
            rows.append(dict(zip(fields, result.get_row_data())))
        return rows

    def _login(self):
        """登录 BaoStock 并返回登录结果。"""
        result = self.bs.login()
        if getattr(result, "error_code", "0") != "0":
            raise RuntimeError(getattr(result, "error_msg", "BaoStock 登录失败"))
        return result

    def get_daily(
        self,
        stock_code: str,
        start_date: str = "",
        end_date: str = "",
        adjustment: str = "raw",
    ) -> list[dict[str, Any]]:
        """获取 BaoStock 日线行情。"""
        adjustment_map = {"raw": "3", "forward": "2", "backward": "1"}
        if adjustment not in adjustment_map:
            raise UnsupportedProviderCapability(f"BaoStock 不支持复权口径: {adjustment}")
        # 符号校验必须先于登录：北交所代码在这里就失败，不为一只注定失败的票打网络往返。
        symbol = baostock_symbol(stock_code)
        now = datetime.now()
        self._login()
        try:
            result = self.bs.query_history_k_data_plus(
                symbol,
                "date,open,high,low,close,volume,amount,pctChg",
                start_date=_date(start_date, now - timedelta(days=365)),
                end_date=_date(end_date, now),
                frequency="d",
                adjustflag=adjustment_map[adjustment],
            )
            # BaoStock 用 pctChg/volume，需统一为 pct_chg/vol 并校准日期升序。
            return normalize_daily_records(self._query(result))
        finally:
            self.bs.logout()

    def get_stock_basic(self, stock_code: str = "") -> list[dict[str, Any]]:
        """获取 BaoStock 股票基本信息。"""
        symbol = baostock_symbol(stock_code) if stock_code else ""
        self._login()
        try:
            result = self.bs.query_stock_basic(code=symbol) if symbol else self.bs.query_stock_basic()
            # BaoStock 用 code_name/ipoDate，需统一为 name/list_date。
            return normalize_basic_records(self._query(result))
        finally:
            self.bs.logout()

    def get_daily_basic(self, stock_code: str, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        """获取日估值指标（peTTM/pbMRQ/psTTM），免 token 的第二路估值来源。

        BaoStock 的估值字段可以与行情**在同一次请求**里返回，但这里只取估值，
        以保持与其它 provider 的能力边界一致。估值字段在三种复权口径下数值完全
        相同，故固定 ``adjustflag="3"``。

        注意 ``frequency`` 只能是 ``d``：周线/月线带估值字段会被服务端硬拒
        （``error_code=10004012``「周线指标参数传入错误:peTTM」）。
        """
        symbol = baostock_symbol(stock_code)
        now = datetime.now()
        cache_key = ("baostock", symbol, start_date, end_date)
        cached = cache_read("valuation", cache_key)
        if cached:
            return cached
        self._login()
        try:
            result = self.bs.query_history_k_data_plus(
                symbol,
                _VALUATION_FIELDS,
                start_date=_date(start_date, now - timedelta(days=365)),
                end_date=_date(end_date, now),
                frequency="d",
                adjustflag="3",
            )
            normalized = normalize_valuation_records(self._query(result))
        finally:
            self.bs.logout()
        rows = [_coerce_valuation(row) for row in normalized if _has_valuation(row)]
        if not rows:
            raise ProviderUnavailableError(f"BaoStock 未取到 {symbol} 的估值数据")
        cache_write("valuation", cache_key, rows)
        return rows

    def get_financial_indicator(self, stock_code: str) -> list[dict[str, Any]]:
        """获取 BaoStock 财务指标。"""
        raise UnsupportedProviderCapability("BaoStock 财务指标接口需要报告期参数")

    def get_income(self, stock_code: str) -> list[dict[str, Any]]:
        """BaoStock 当前不声明统一利润表接口。"""
        raise UnsupportedProviderCapability("BaoStock 不支持统一利润表接口")

    def get_trade_cal(self, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        """获取 BaoStock 交易日历。"""
        self._login()
        try:
            result = self.bs.query_trade_dates(start_date=start_date, end_date=end_date)
            # BaoStock 用 calendar_date/is_trading_day，需统一为 cal_date/is_open。
            return normalize_trade_cal_records(self._query(result))
        finally:
            self.bs.logout()

    def get_index_daily(
        self,
        index_symbol: str,
        start_date: str = "",
        end_date: str = "",
    ) -> list[dict[str, Any]]:
        """获取指数日线（免 token 的指数第二来源，实测 2026-09-12 可用）。"""
        symbol = canonical_index(index_symbol)
        # canonical_index 出口是 sh000001；BaoStock 用 sh.000001。
        baostock_symbol_form = f"{symbol[:2]}.{symbol[2:]}"
        now = datetime.now()
        cache_key = ("baostock", symbol, start_date, end_date)
        cached = cache_read("index_daily", cache_key)
        if cached:
            return cached
        self._login()
        try:
            result = self.bs.query_history_k_data_plus(
                baostock_symbol_form,
                "date,open,high,low,close,volume,amount,pctChg",
                start_date=_date(start_date, now - timedelta(days=365)),
                end_date=_date(end_date, now),
                frequency="d",
            )
            rows = normalize_index_daily_records(self._query(result))
        finally:
            self.bs.logout()
        if not rows:
            raise ProviderUnavailableError(f"BaoStock 未取到指数 {symbol} 的日线数据")
        cache_write("index_daily", cache_key, rows)
        return rows

    def get_market_breadth(self) -> Any:
        """BaoStock 不提供市场宽度快照。"""
        raise UnsupportedProviderCapability("BaoStock 不提供市场宽度接口")

    def get_margin_summary(self) -> Any:
        """BaoStock 不提供融资融券汇总。"""
        raise UnsupportedProviderCapability("BaoStock 不提供融资融券接口")

    def get_northbound_holdings(self) -> Any:
        """BaoStock 不提供北向持股数据。"""
        raise UnsupportedProviderCapability("BaoStock 不提供北向持股接口")

    def get_policy_news(self) -> Any:
        """BaoStock 不提供财经快讯/政策新闻。"""
        raise UnsupportedProviderCapability("BaoStock 不提供财经快讯接口")
