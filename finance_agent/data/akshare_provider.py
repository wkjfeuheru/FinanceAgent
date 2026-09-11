"""AKShare 股票数据适配器。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from finance_agent.data.providers import ProviderUnavailableError, UnsupportedProviderCapability


def _date(value: str, fallback: datetime) -> str:
    """将日期转换为 AKShare 所需的 YYYYMMDD 格式。"""
    return (value or fallback.strftime("%Y-%m-%d")).replace("-", "")


def _records(frame: Any) -> list[dict[str, Any]]:
    """将 DataFrame 或记录列表转换为字典列表。"""
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    if isinstance(frame, list):
        return [item for item in frame if isinstance(item, dict)]
    return []


class AkshareDataSource:
    """通过可选 AKShare 依赖提供统一股票数据接口。"""

    provider_name = "akshare"

    def __init__(self) -> None:
        try:
            import akshare as ak
        except ImportError as exc:
            raise ProviderUnavailableError("AKShare 未安装") from exc
        self.ak = ak

    def is_available(self) -> bool:
        """返回 AKShare 是否可导入。"""
        return self.ak is not None

    def get_daily(
        self,
        stock_code: str,
        start_date: str = "",
        end_date: str = "",
        adjustment: str = "raw",
    ) -> list[dict[str, Any]]:
        """获取 AKShare 日线行情并转换为统一记录。"""
        adjustment_map = {"raw": "", "forward": "qfq", "backward": "hfq"}
        if adjustment not in adjustment_map:
            raise UnsupportedProviderCapability(f"AKShare 不支持复权口径: {adjustment}")
        end = datetime.now()
        frame = self.ak.stock_zh_a_hist(
            symbol=str(stock_code).split(".")[0],
            period="daily",
            start_date=_date(start_date, end - timedelta(days=365)),
            end_date=_date(end_date, end),
            adjust=adjustment_map[adjustment],
        )
        return _records(frame)

    def get_stock_basic(self, stock_code: str = "") -> list[dict[str, Any]]:
        """获取 AKShare A 股股票列表或指定股票信息。"""
        frame = self.ak.stock_info_a_code_name()
        rows = _records(frame)
        if not stock_code:
            return rows
        code = str(stock_code).split(".")[0]
        return [row for row in rows if str(row.get("code", row.get("代码", ""))) == code]

    def get_daily_basic(self, stock_code: str, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        """获取估值指标；AKShare 不保证所有版本提供统一估值接口。"""
        raise UnsupportedProviderCapability("AKShare 当前未提供统一日估值接口")

    def get_financial_indicator(self, stock_code: str) -> list[dict[str, Any]]:
        """获取 AKShare 财务指标。"""
        frame = self.ak.stock_financial_analysis_indicator(symbol=str(stock_code).split(".")[0])
        return _records(frame)

    def get_income(self, stock_code: str) -> list[dict[str, Any]]:
        """获取 AKShare 利润表。"""
        frame = self.ak.stock_profit_sheet_by_report_em(symbol=str(stock_code).split(".")[0])
        return _records(frame)

    def get_trade_cal(self, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        """获取交易日历；AKShare 适配器暂不声明该能力。"""
        raise UnsupportedProviderCapability("AKShare 当前未提供统一交易日历接口")
