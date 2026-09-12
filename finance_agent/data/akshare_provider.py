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

from finance_agent.data.board_codes import canonical_index, ensure_current_code, sina_symbol
from finance_agent.data.normalization import (
    normalize_basic_records,
    normalize_breadth_record,
    normalize_daily_records,
    normalize_financial_records,
    normalize_index_daily_records,
    normalize_margin_summary,
    normalize_northbound_holdings,
    normalize_valuation_records,
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


def _iso_bound(value: str) -> str:
    """把 ``YYYYMMDD`` 或 ``YYYY-MM-DD`` 统一为 ``YYYY-MM-DD``；空串返回空串。"""
    text = (value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _within_window(
    rows: list[dict[str, Any]], start_date: str, end_date: str,
) -> list[dict[str, Any]]:
    """按闭区间裁剪记录；日期已是 ISO 文本，可直接字典序比较。

    ``stock_value_em`` 没有日期参数、一次返回完整历史（起点为
    ``max(2018-01-02, 上市日)``），因此窗口只能在这里裁剪。
    """
    start = _iso_bound(start_date)
    end = _iso_bound(end_date)
    if not start and not end:
        return rows
    kept = []
    for row in rows:
        as_of = str(row.get("trade_date") or "")
        if start and as_of < start:
            continue
        if end and as_of > end:
            continue
        kept.append(row)
    return kept


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
        """获取日估值指标（PE(TTM)/PE(静)/PB/PS/总市值/流通市值）。

        ``stock_value_em`` 是 AKShare 1.18.94 中唯一按股票代码返回日频估值历史的
        接口：``stock_a_indicator_lg`` 已被删除，``stock_zh_a_hist`` 不含任何估值列。
        覆盖起点为 ``max(2018-01-02, 上市日)``，因此不做双源拼接。
        """
        code = ensure_current_code(stock_code)
        fetch = getattr(self.ak, "stock_value_em", None)
        if not callable(fetch):
            raise UnsupportedProviderCapability("AKShare 该版本未提供 stock_value_em 接口")
        cache_key = ("akshare", code, start_date, end_date)
        cached = cache_read("valuation", cache_key)
        if cached:
            return cached
        try:
            frame = fetch(symbol=code)
        except Exception as exc:
            # 取数失败必须与"不支持该能力"区分：否则 _call 会把可重试故障
            # 记成能力缺口，审计时看不出区别。
            raise ProviderUnavailableError(f"AKShare 取 {code} 估值失败: {exc}") from exc
        # 带括号的 PE 两列在这里显式映射，不进共享别名表：别名表是模糊匹配，
        # 把 PE(TTM) 与 PE(静) 一起放进去必然产生口径歧义。
        columns = {
            "数据日期": "trade_date",
            "PE(TTM)": "pe_ttm",
            "PE(静)": "pe_lyr",
            "市净率": "pb",
            "市销率": "ps_ttm",
            "总市值": "total_mv",
            "流通市值": "circ_mv",
        }
        mapped = [
            {columns.get(key, key): value for key, value in row.items()}
            for row in _records(frame)
        ]
        rows = _within_window(normalize_valuation_records(mapped), start_date, end_date)
        if not rows:
            raise ProviderUnavailableError(f"AKShare 未取到 {code} 的估值数据")
        cache_write("valuation", cache_key, rows)
        return rows

    def get_financial_indicator(self, stock_code: str) -> list[dict[str, Any]]:
        """获取 AKShare 财务指标。

        必须显式传 ``start_year``：该接口默认 ``start_year='1900'``，实测（2026-09-12）
        此时服务端返回 **0 行**，会让基本面评分静默退化为中性分。取近三年即可覆盖
        研究层所需的最近报告期与披露日。
        """
        fetch = getattr(self.ak, "stock_financial_analysis_indicator", None)
        if not callable(fetch):
            raise UnsupportedProviderCapability(
                "AKShare 该版本未提供 stock_financial_analysis_indicator 接口"
            )
        code = str(stock_code).split(".")[0]
        start_year = str(datetime.now().year - 2)
        try:
            frame = fetch(symbol=code, start_year=start_year)
        except TypeError:
            # 兼容旧版本签名（无 start_year 参数）。
            frame = fetch(symbol=code)
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

    def get_index_daily(
        self,
        index_symbol: str,
        start_date: str = "",
        end_date: str = "",
    ) -> list[dict[str, Any]]:
        """获取指数日线（新浪源 ``stock_zh_index_daily``）。

        实测 2026-09-12：上证/深证成指/创业板指/科创50/沪深300 均可取。
        东财 ``stock_zh_index_spot_em`` 在本网络环境被按 URL 过滤（与东财 K 线
        同因），因此只走新浪源。
        """
        symbol = canonical_index(index_symbol)
        cache_key = ("akshare", symbol, start_date, end_date)
        cached = cache_read("index_daily", cache_key)
        if cached:
            return cached
        fetch = getattr(self.ak, "stock_zh_index_daily", None)
        if not callable(fetch):
            raise UnsupportedProviderCapability("AKShare 该版本未提供 stock_zh_index_daily 接口")
        try:
            rows = normalize_index_daily_records(_records(fetch(symbol=symbol)))
        except Exception as exc:  # provider 边界统一处理第三方异常
            raise ProviderUnavailableError(f"AKShare 取指数 {symbol} 日线失败: {exc}") from exc
        start = _iso_bound(start_date)
        end = _iso_bound(end_date)
        if start or end:
            rows = [
                row for row in rows
                if (not start or str(row.get("trade_date", "")) >= start)
                and (not end or str(row.get("trade_date", "")) <= end)
            ]
        if not rows:
            raise ProviderUnavailableError(f"AKShare 未取到指数 {symbol} 的日线数据")
        cache_write("index_daily", cache_key, rows)
        return rows

    def get_market_breadth(self) -> dict[str, Any]:
        """获取市场宽度（乐咕 ``stock_market_activity_legu``：涨跌家数/涨跌停/活跃度）。

        实测 2026-09-12：返回两列宽表（项目/数值），统计日期为最近交易日 15:00。
        """
        fetch = getattr(self.ak, "stock_market_activity_legu", None)
        if not callable(fetch):
            raise UnsupportedProviderCapability("AKShare 该版本未提供 stock_market_activity_legu 接口")
        cache_key = ("akshare", "breadth")
        cached = cache_read("breadth", cache_key)
        if cached:
            return cached
        try:
            record = normalize_breadth_record(_records(fetch()))
        except Exception as exc:
            raise ProviderUnavailableError(f"AKShare 取市场宽度失败: {exc}") from exc
        if not record:
            raise ProviderUnavailableError("AKShare 市场宽度返回空数据")
        cache_write("breadth", cache_key, record)
        return record

    def get_margin_summary(self) -> dict[str, Any]:
        """获取两市融资融券汇总（日频，单位亿元）。

        实测 2026-09-12：``stock_margin_account_info`` 返回两市合计的日频序列
        （最近 2026-09-10，融资余额约 2.62 万亿元），带日期、单位统一为亿元。
        相比之下沪市 ``stock_margin_sse`` 不带日期时默认返回 2023 年旧数据，
        深市 ``stock_margin_szse`` 单位为亿元，两列口径与日期都不一致，因此这里
        只走合计接口。
        """
        fetch = getattr(self.ak, "stock_margin_account_info", None)
        if not callable(fetch):
            raise UnsupportedProviderCapability("AKShare 该版本未提供 stock_margin_account_info 接口")
        cache_key = ("akshare", "margin")
        cached = cache_read("margin", cache_key)
        if cached:
            return cached
        try:
            record = normalize_margin_summary(_records(fetch()))
        except Exception as exc:
            raise ProviderUnavailableError(f"AKShare 取两市融资融券失败: {exc}") from exc
        if not record:
            raise ProviderUnavailableError("AKShare 两市融资融券返回空数据")
        record["note"] = "两市合计，交易所日频披露。"
        cache_write("margin", cache_key, record)
        return record

    def get_northbound_holdings(self) -> dict[str, Any]:
        """获取北向持股市值最近季度点位（东财 ``stock_hsgt_hist_em``）。

        实测 2026-09-12：逐日资金流自 2024-08-16 起停更（监管披露调整），但
        ``持股市值`` 改为**季度**披露且近期仍有效（最近 2026-06-30 约 3.1 万亿元）。
        因此这里只返回最近一个有值的季度点位，并在 note 中标注披露频率与滞后。
        """
        fetch = getattr(self.ak, "stock_hsgt_hist_em", None)
        if not callable(fetch):
            raise UnsupportedProviderCapability("AKShare 该版本未提供 stock_hsgt_hist_em 接口")
        cache_key = ("akshare", "northbound_holdings")
        cached = cache_read("northbound_holdings", cache_key)
        if cached:
            return cached
        try:
            snapshot = normalize_northbound_holdings(_records(fetch(symbol="北向资金")))
        except Exception as exc:
            raise ProviderUnavailableError(f"AKShare 取北向持股市值失败: {exc}") from exc
        if not snapshot:
            raise ProviderUnavailableError("AKShare 北向持股市值返回空数据")
        record = {
            "as_of": snapshot.get("as_of", ""),
            "holdings_value_yuan": snapshot.get("holdings_value_yuan"),
            "note": "北向持股市值为季度披露（最近有效季度），非实时；逐日北向资金流自2024-08起停更。",
        }
        cache_write("northbound_holdings", cache_key, record)
        return record
