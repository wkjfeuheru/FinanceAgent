"""BaoStock 股票数据适配器。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from finance_agent.data.normalization import (
    normalize_basic_records,
    normalize_daily_records,
    normalize_trade_cal_records,
)
from finance_agent.data.providers import ProviderUnavailableError, UnsupportedProviderCapability


def _date(value: str, fallback: datetime) -> str:
    """将日期转换为 BaoStock 所需的 YYYY-MM-DD 格式。"""
    return value or fallback.strftime("%Y-%m-%d")


def _code(value: str) -> str:
    """将纯数字代码转换为 BaoStock 格式。"""
    code = str(value).split(".")[0]
    if code.startswith(("60", "68")):
        return f"sh.{code}"
    return f"sz.{code}"


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
        now = datetime.now()
        self._login()
        try:
            result = self.bs.query_history_k_data_plus(
                _code(stock_code),
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
        self._login()
        try:
            result = self.bs.query_stock_basic(code=_code(stock_code)) if stock_code else self.bs.query_stock_basic()
            # BaoStock 用 code_name/ipoDate，需统一为 name/list_date。
            return normalize_basic_records(self._query(result))
        finally:
            self.bs.logout()

    def get_daily_basic(self, stock_code: str, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        """BaoStock 不提供与 Tushare 对齐的日估值接口。"""
        raise UnsupportedProviderCapability("BaoStock 不支持统一日估值接口")

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
