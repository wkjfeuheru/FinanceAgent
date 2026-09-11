"""AKShare 股票数据适配器。

日线取数使用**新浪源** ``stock_zh_a_daily`` 作为主路径，东方财富的
``stock_zh_a_hist`` 仅作回退。原因是东财的 K 线接口在部分网络环境下会被按 URL
过滤：TCP 与 TLS 握手正常，但 ``/api/qt/stock/kline/get`` 拿到零字节并被关闭，
换 header、换参数、换 25 个镜像域名、换 :80/:443 全部无效，客户端无法修复；
而同一主机上的 ``/api/qt/stock/trends2/get`` 与 ``/api/qt/stock/clist/get`` 正常。

前复权口径：新浪源 ``adjust="qfq"`` 与 BaoStock 的 ``adjustflag=2`` 逐字节一致
（600519 在 2024-12-31 收盘均为 1435.70），而腾讯源同日为 1444.42。因此腾讯源
**不进降级链**——混入同一序列会让回测结果不可复现。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Callable

from finance_agent.data.board_codes import ensure_current_code, sina_symbol
from finance_agent.data.normalization import (
    normalize_basic_records,
    normalize_daily_records,
    normalize_financial_records,
)
from finance_agent.data.providers import ProviderUnavailableError, UnsupportedProviderCapability
from finance_agent.data.quote_cache import read as cache_read
from finance_agent.data.quote_cache import write as cache_write

# 新浪源的复权参数直接使用 ""/qfq/hfq，东财用同一组取值。
_ADJUST_MAP = {"raw": "", "forward": "qfq", "backward": "hfq"}
# 退避序列：首次立即尝试，之后两次重试。新浪源 docstring 自带"大量抓取容易封 IP"
# 警告，而筛选路径是按候选逐个取数的 N+1 模式，因此必须退避。
_RETRY_DELAYS = (0.5, 1.5)


def _sleep(seconds: float) -> None:
    """退避睡眠；测试替换为空实现以避免真实等待。"""
    time.sleep(seconds)


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
        if adjustment not in _ADJUST_MAP:
            raise UnsupportedProviderCapability(f"AKShare 不支持复权口径: {adjustment}")
        # 已废止的北交所代码在这里失败，不为一只注定失败的票打网络往返。
        code = ensure_current_code(stock_code)
        cache_key = ("akshare", code, adjustment, start_date, end_date)
        cached = cache_read("daily", cache_key)
        if cached:
            return cached

        now = datetime.now()
        window = (_date(start_date, now - timedelta(days=365)), _date(end_date, now))
        rows = self._fetch_sina(code, window, adjustment) or self._fetch_eastmoney(code, window, adjustment)
        if not rows:
            raise ProviderUnavailableError(f"AKShare 未取到 {code} 的日线行情")
        cache_write("daily", cache_key, rows)
        return rows

    def _fetch_sina(
        self, code: str, window: tuple[str, str], adjustment: str,
    ) -> list[dict[str, Any]]:
        """新浪源主路径；缺少该接口时直接返回空，交由回退路径处理。"""
        fetch = getattr(self.ak, "stock_zh_a_daily", None)
        if not callable(fetch):
            return []
        return self._with_retry(
            lambda: fetch(
                symbol=sina_symbol(code),
                start_date=window[0],
                end_date=window[1],
                adjust=_ADJUST_MAP[adjustment],
            ),
            label="stock_zh_a_daily",
        )

    def _fetch_eastmoney(
        self, code: str, window: tuple[str, str], adjustment: str,
    ) -> list[dict[str, Any]]:
        """东方财富源回退路径。"""
        fetch = getattr(self.ak, "stock_zh_a_hist", None)
        if not callable(fetch):
            return []
        return self._with_retry(
            lambda: fetch(
                symbol=code,
                period="daily",
                start_date=window[0],
                end_date=window[1],
                adjust=_ADJUST_MAP[adjustment],
            ),
            label="stock_zh_a_hist",
        )

    def _with_retry(self, fetch: Callable[[], Any], label: str) -> list[dict[str, Any]]:
        """带退避重试地抓取并归一化；全部失败时返回空列表交由上层降级。"""
        last: Exception | None = None
        for delay in (0.0, *_RETRY_DELAYS):
            if delay:
                _sleep(delay)
            try:
                # 厂商返回中文列或英文列，必须在适配器出口统一字段名，
                # 否则研究层读不到 close 而只能给出空评分。
                rows = normalize_daily_records(_records(fetch()))
                if rows:
                    return rows
                last = ProviderUnavailableError(f"{label} 返回空记录")
            except Exception as exc:  # provider 边界统一处理第三方异常
                last = exc
        if last is not None:
            import logging

            logging.getLogger(__name__).warning("AKShare %s 取数失败: %s", label, last)
        return []

    def get_stock_basic(self, stock_code: str = "") -> list[dict[str, Any]]:
        """获取 AKShare A 股股票列表或指定股票信息。"""
        frame = self.ak.stock_info_a_code_name()
        rows = _records(frame)
        if not stock_code:
            return normalize_basic_records(rows)
        code = str(stock_code).split(".")[0]
        filtered = [row for row in rows if str(row.get("code", row.get("代码", ""))) == code]
        return normalize_basic_records(filtered)

    def get_daily_basic(self, stock_code: str, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        """获取估值指标；AKShare 不保证所有版本提供统一估值接口。"""
        raise UnsupportedProviderCapability("AKShare 当前未提供统一日估值接口")

    def get_financial_indicator(self, stock_code: str) -> list[dict[str, Any]]:
        """获取 AKShare 财务指标。"""
        frame = self.ak.stock_financial_analysis_indicator(symbol=str(stock_code).split(".")[0])
        # 新浪源返回中文指标名（净资产收益率(%)/主营业务收入增长率(%)/...），
        # 统一为 roe/or_yoy/netprofit_yoy 后研究层才能生成基本面评分。
        return normalize_financial_records(_records(frame))

    def get_income(self, stock_code: str) -> list[dict[str, Any]]:
        """获取 AKShare 利润表。"""
        frame = self.ak.stock_profit_sheet_by_report_em(symbol=str(stock_code).split(".")[0])
        return _records(frame)

    def get_trade_cal(self, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        """获取交易日历；AKShare 适配器暂不声明该能力。"""
        raise UnsupportedProviderCapability("AKShare 当前未提供统一交易日历接口")
