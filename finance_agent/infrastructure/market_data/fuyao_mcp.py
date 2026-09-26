"""同花顺 Fuyao MCP 远程数据源适配器。

通过 MCP 客户端协议（streamable HTTP）连接同花顺托管在
``https://fuyao.aicubes.cn/mcp`` 的四个 MCP Server，获取 A 股行情、估值、
财务、交易日历与指数数据：

- ``a-share``：个股行情/估值/财务/日历；
- ``a-share-index``：指数行情；
- ``meta``：代码/名称检索（本适配器暂未使用，保留端点常量）；
- ``fund``：基金数据（本适配器未使用）。

设计原则：

1. ``FuyaoMcpClient`` 封装 MCP 协议细节，对外暴露 ``list_tools`` / ``call_tool``；
2. ``FuyaoMcpDataSource`` 提供与 AKShare / BaoStock 适配器对齐的业务接口；
3. MCP 客户端是异步的，通过线程隔离的方式在同步代码中安全调用；
4. API Key 由 ``config.FUYAO_API_KEY`` 统一管理，不硬编码。

实测事实（2026-09-23，本机）：

- 已安装的 ``mcp`` 2.2.0 的 ``streamable_http_client`` **只 yield 2 元组**
  ``(read, write)``（旧版为 3 元组），因此这里按 2 元组解包；
- ``http_client`` 必须是 ``httpx2.AsyncClient``（MCP SDK 依赖 httpx2，非 httpx）；
- 响应信封为 ``{code, message, request_id, data}``，``code == 0`` 为成功；
- 财务指标工具声明的 ``outputSchema`` 把 ``value`` 标为 ``string``，但当期指标
  未披露时服务端会返回 ``null``，SDK 的结构化内容校验会因此抛错（服务端 schema
  缺陷）。这里在客户端侧跳过该校验，由适配器自行处理空值。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from finance_agent.infrastructure.settings import FUYAO_API_KEY, FUYAO_MCP_BASE_URL, FUYAO_MCP_TIMEOUT
from finance_agent.infrastructure.market_data.board_codes import canonical_index, ensure_current_code, market_of
from finance_agent.infrastructure.market_data.normalization import (
    normalize_daily_records,
    normalize_financial_records,
    normalize_index_daily_records,
    normalize_trade_cal_records,
    normalize_valuation_records,
)
from finance_agent.domains.research.reporting_periods import recent_report_periods
from finance_agent.infrastructure.market_data.providers import UnsupportedProviderCapability

logger = logging.getLogger(__name__)

# Fuyao 数据时间戳统一为 Asia/Shanghai（UTC+8，无夏令时），用固定偏移换算，
# 不依赖运行环境的 tzdata（Windows 上常缺失）。
_CHINA_TZ = timezone(timedelta(hours=8))
# 行情/指数历史窗口上限（服务端 >10 年返回 code=1003）。
_MAX_WINDOW_DAYS = 3650
# 未找到标的 / 数据未就绪：视为"该源没有这条数据"，返回空触发降级而非熔断。
_EMPTY_CODES = {3001, 3002}
# 复权口径 → Fuyao adjust 参数。
_ADJUST_MAP = {"raw": "none", "forward": "forward", "backward": "backward"}


def _run_async_safely(coro: Any) -> Any:
    """在同步上下文中安全运行异步协程。

    MCP 客户端基于 asyncio，但项目主体是同步代码。若当前线程已在事件循环中
    （如 FastAPI 异步路由），则在新线程中创建独立事件循环执行，避免嵌套循环报错。
    """
    try:
        asyncio.get_running_loop()
        result: list[Any] = []
        error: list[BaseException | None] = [None]

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            try:
                result.append(loop.run_until_complete(coro))
            except BaseException as exc:  # noqa: BLE001
                error[0] = exc
            finally:
                loop.close()

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()
        if error[0] is not None:
            raise error[0]
        return result[0] if result else None
    except RuntimeError:
        return asyncio.run(coro)


class FuyaoMcpError(RuntimeError):
    """同花顺 Fuyao MCP 数据源错误。"""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class _LenientClientSession(ClientSession):
    """跳过 tool 输出 schema 校验的客户端会话。

    服务端把财务指标 ``value`` 声明为 ``string``，但未披露时实际返回 ``null``，
    SDK 的结构化内容校验会因此抛 ``RuntimeError`` 而不是让业务层拿到数据。
    这里在客户端侧跳过校验：空值由适配器按缺失处理，既不误报故障也不丢数据。
    """

    async def validate_tool_result(self, name: str, result: Any) -> None:  # noqa: D102
        return None


class FuyaoMcpClient:
    """Fuyao MCP 底层客户端封装（多端点 + X-api-key 鉴权）。

    封装 streamable HTTP 连接管理、工具发现与工具调用，对外提供同步接口，
    屏蔽 MCP 协议与 asyncio 细节。
    """

    def __init__(
        self,
        base_url: str = FUYAO_MCP_BASE_URL,
        api_key: str = FUYAO_API_KEY,
        timeout: float = FUYAO_MCP_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _endpoint_url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    async def _session_call(
        self,
        endpoint: str,
        action: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """建立 MCP 连接并执行一次操作（list_tools 或 call_tool）。

        每次调用都新建连接：streamable HTTP 无状态，复用连接的收益有限且会
        增加跨线程状态管理复杂度。
        """
        headers = {"X-api-key": self.api_key} if self.api_key else {}
        async with httpx2.AsyncClient(headers=headers, timeout=self.timeout) as http_client:
            # mcp>=2.2 yield (read, write)；旧版 yield (read, write, get_session_id)。
            # 兼容两种元数，避免依赖 SDK 大版本。
            async with streamable_http_client(
                self._endpoint_url(endpoint), http_client=http_client,
            ) as streams:
                read, write = streams[0], streams[1]
                async with _LenientClientSession(read, write) as session:
                    await session.initialize()

                    if action == "list_tools":
                        result = await session.list_tools()
                        return [
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "input_schema": tool.inputSchema,
                            }
                            for tool in result.tools
                        ]

                    if action == "call_tool":
                        result = await session.call_tool(tool_name or "", arguments or {})
                        if result.is_error:
                            raise FuyaoMcpError(
                                f"Fuyao MCP 工具 {tool_name} 返回错误: {_content_text(result)}"
                            )
                        return self._unwrap(_content_text(result))

                    raise FuyaoMcpError(f"未知的 MCP 操作: {action}")

    @staticmethod
    def _unwrap(text: Any) -> Any:
        """解析 Fuyao 信封 ``{code, message, data}``。

        ``code == 0`` 返回 ``data``；标的不存在/数据未就绪返回 ``None``（交由
        ProviderManager 降级到下一个源）；其余业务错误抛出 ``FuyaoMcpError``。
        """
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
        if not isinstance(payload, dict) or "code" not in payload:
            return payload
        code = payload.get("code")
        if code == 0:
            return payload.get("data")
        if code in _EMPTY_CODES:
            logger.debug("Fuyao 空数据( code=%s )：%s", code, payload.get("message"))
            return None
        raise FuyaoMcpError(
            f"Fuyao 接口错误 code={code}: {payload.get('message')}", code=code,
        )

    def list_tools(self, endpoint: str) -> list[dict[str, Any]]:
        """列出指定端点暴露的所有 MCP 工具。"""
        return _run_async_safely(self._session_call(endpoint, "list_tools"))

    def call_tool(self, endpoint: str, name: str, **arguments: Any) -> Any:
        """调用指定端点的 MCP 工具并返回解析后的 ``data``。"""
        return _run_async_safely(
            self._session_call(endpoint, "call_tool", name, arguments)
        )


# ── 代码与时间格式转换 ────────────────────────────────────────

def _to_thscode(stock_code: str) -> str:
    """把纯数字/带市场前缀的 A 股代码转为 Fuyao ``thscode``（``600519.SH``）。"""
    code = ensure_current_code(stock_code)
    if "." in str(stock_code):
        # 已带交易所后缀（600519.SH / 000001.SZ），仅规范大小写。
        return str(stock_code).strip().upper()
    return f"{code}.{market_of(code).upper()}"


def _index_thscode(index_symbol: str) -> str:
    """把指数符号（``sh000001`` / ``上证指数``）转为 Fuyao ``thscode``。"""
    canonical = canonical_index(index_symbol)  # 形如 sh000001
    return f"{canonical[2:]}.{canonical[:2].upper()}"


def _to_ms(value: str) -> int:
    """把 ``YYYY-MM-DD`` 文本转为 Asia/Shanghai 当日 00:00 的毫秒时间戳。"""
    text = str(value).strip().replace("-", "")
    moment = datetime(int(text[:4]), int(text[4:6]), int(text[6:8]), tzinfo=_CHINA_TZ)
    return int(moment.timestamp() * 1000)


def _from_ms(value: Any) -> str | None:
    """把毫秒时间戳转为 ``YYYY-MM-DD`` 文本；不可解析返回 None。"""
    try:
        seconds = float(value) / 1000
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(seconds, tz=_CHINA_TZ).date().isoformat()


def _default_window(start_date: str, end_date: str) -> tuple[str, str]:
    """补齐缺省的行情窗口（默认近一年），并约束在服务端 10 年上限内。"""
    now = datetime.now(_CHINA_TZ)
    end = end_date or now.strftime("%Y-%m-%d")
    start = start_date or (now - timedelta(days=365)).strftime("%Y-%m-%d")
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    if (end_dt - start_dt).days > _MAX_WINDOW_DAYS:
        start_dt = end_dt - timedelta(days=_MAX_WINDOW_DAYS)
    return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")


def _content_text(result: Any) -> Any:
    """取 MCP 工具结果的首段文本内容。"""
    content = getattr(result, "content", None) or []
    if not content:
        return None
    return getattr(content[0], "text", None)


def _bars_to_daily(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 Fuyao 价格 K 线映射为统一日线字段并计算涨跌额/涨跌幅（升序）。"""
    rows: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: row.get("date_ms") or 0):
        if not isinstance(item, dict):
            continue
        rows.append({
            "trade_date": _from_ms(item.get("date_ms")),
            "open": item.get("open_price"),
            "high": item.get("high_price"),
            "low": item.get("low_price"),
            "close": item.get("close_price"),
            "vol": item.get("volume"),
            "amount": item.get("turnover"),
        })
    # Fuyao 不返回涨跌额/涨跌幅，由前收推导（首行无前收，留空）。
    prev_close: float | None = None
    for row in rows:
        close = row.get("close")
        try:
            close_value = float(close) if close is not None else None
        except (TypeError, ValueError):
            close_value = None
        if close_value is not None and prev_close:
            row["change"] = round(close_value - prev_close, 4)
            row["pct_chg"] = round((close_value / prev_close - 1) * 100, 4)
        if close_value is not None:
            prev_close = close_value
    return rows


class FuyaoMcpDataSource:
    """同花顺 Fuyao MCP 高层数据源适配器。

    提供统一股票数据接口（与 AKShare / BaoStock 适配器对齐），内部通过
    ``FuyaoMcpClient`` 调用远程 MCP 工具获取数据。

    能力边界（实测）：Fuyao 提供个股/指数行情、服务端**快照**估值、财务指标与
    利润表、交易日历；**不提供**日频估值历史、市场宽度、两融、北向持股与政策
    快讯，这些能力显式声明为不支持，交由降级链中的 AKShare 提供。
    基础信息（``get_stock_basic``）亦不在本源声明：Fuyao 代码表不含"行业"字段，
    而候选搜索依赖行业匹配，交由 AKShare 提供以避免静默丢失行业。
    """

    provider_name = "fuyao_mcp"

    def __init__(
        self,
        base_url: str = FUYAO_MCP_BASE_URL,
        api_key: str = FUYAO_API_KEY,
        timeout: float = FUYAO_MCP_TIMEOUT,
    ) -> None:
        self.client = FuyaoMcpClient(base_url, api_key, timeout)

    def is_available(self) -> bool:
        """返回 Fuyao MCP 是否已配置 API Key 与 Base URL。"""
        return bool(self.client.api_key and self.client.base_url)

    def discover_tools(self, endpoint: str = "a-share") -> list[dict[str, Any]]:
        """发现并返回指定端点暴露的所有工具（首次集成核对用）。"""
        return self.client.list_tools(endpoint)

    def _call(self, endpoint: str, name: str, **arguments: Any) -> Any:
        """调用工具并统一包装异常为 FuyaoMcpError。"""
        try:
            return self.client.call_tool(endpoint, name, **arguments)
        except FuyaoMcpError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider 边界统一处理第三方异常
            raise FuyaoMcpError(f"Fuyao MCP 工具 {name} 调用失败: {exc}") from exc

    # ── 行情与估值 ────────────────────────────────────────────

    def get_daily(
        self,
        stock_code: str,
        start_date: str = "",
        end_date: str = "",
        adjustment: str = "raw",
    ) -> Any:
        """获取 A 股日线行情（开高低收、成交量、成交额）。"""
        if adjustment not in _ADJUST_MAP:
            raise UnsupportedProviderCapability(f"Fuyao 不支持复权口径: {adjustment}")
        start, end = _default_window(start_date, end_date)
        data = self._call(
            "a-share", "get_a_share_prices_historical",
            thscode=_to_thscode(stock_code),
            interval="1d",
            start=_to_ms(start),
            end=_to_ms(end),
            adjust=_ADJUST_MAP[adjustment],
        )
        items = (data or {}).get("item") or []
        if not items:
            return []
        return normalize_daily_records(_bars_to_daily(items))

    def get_daily_basic(
        self, stock_code: str, start_date: str = "", end_date: str = "",
    ) -> Any:
        """获取估值快照（PE TTM / PB MRQ / PS TTM）。

        注意：Fuyao 只提供服务端**快照**，无日频估值历史。为满足统一契约，
        出口为单条记录并标注 ``trade_date`` 为服务端数据时间；若需要历史窗口，
        由降级链中的 AKShare ``stock_value_em`` 提供。
        """
        data = self._call(
            "a-share", "get_a_share_valuations_snapshot",
            thscodes=_to_thscode(stock_code),
        )
        items = (data or {}).get("item") or []
        if not items:
            return []
        item = items[0]
        as_of = _from_ms((data or {}).get("timestamp")) or datetime.now(_CHINA_TZ).date().isoformat()
        record = {
            "trade_date": as_of,
            "pe_ttm": item.get("pe_ttm"),
            "pe_lyr": item.get("pe_mrq"),
            "pb": item.get("pb_mrq"),
            "ps": item.get("ps_ttm"),
            "total_mv": item.get("total_mv"),
            "circ_mv": item.get("circ_mv"),
        }
        # 全空（未披露）视为无数据，触发降级。
        if all(record.get(key) is None for key in ("pe_ttm", "pe_lyr", "pb", "ps")):
            return []
        return normalize_valuation_records([record])

    # ── 财务 ──────────────────────────────────────────────────

    def _report_code(self, period: str) -> str:
        """把报告期 ``YYYYMMDD`` 转为 Fuyao ``report`` 参数 ``YYYY-Q``。"""
        quarter = {3: "1", 6: "2", 9: "3", 12: "4"}[int(period[4:6])]
        return f"{period[:4]}-{quarter}"

    def _ann_date_map(self, thscode: str) -> dict[str, str]:
        """从季度利润表构建 ``报告期ISO -> 披露日ISO`` 映射；失败返回空。"""
        try:
            data = self._call(
                "a-share", "get_a_share_financials_income_statements",
                thscode=thscode, period="quarterly", limit=8,
            )
        except Exception:  # noqa: BLE001 - 披露日补全失败不阻断指标返回
            return {}
        mapping: dict[str, str] = {}
        for item in (data or {}).get("item") or []:
            period_end = _from_ms(item.get("period_end_ms"))
            report_date = _from_ms(item.get("report_date_ms"))
            if period_end and report_date:
                mapping[period_end] = report_date
        return mapping

    def get_financial_indicator(self, stock_code: str) -> Any:
        """获取财务指标（ROE / 营收增速 / 净利润增速），按报告期升序。

        Fuyao 的指标接口按报告期查询（``report=YYYY-Q``），因此从最近报告期
        向前回退逐个尝试，取到即止；披露日尽力从季度利润表回填。
        """
        thscode = _to_thscode(stock_code)
        ann_map = self._ann_date_map(thscode)
        records: list[dict[str, Any]] = []
        for period in recent_report_periods(datetime.now(_CHINA_TZ).date(), count=4):
            data = self._call(
                "a-share", "get_a_share_financials_indicators",
                thscode=thscode, report=self._report_code(period),
            )
            if not data:
                continue
            values: dict[str, Any] = {}
            for ability in data.get("abilities") or []:
                for indicator in ability.get("indicators") or []:
                    index_id = indicator.get("index_id")
                    if index_id is not None:
                        values[index_id] = indicator.get("value")
            end_iso = _from_ms(_to_ms(f"{period[:4]}-{period[4:6]}-{period[6:]}"))
            record = {
                "end_date": end_iso,
                "roe": values.get("index_weighted_avg_roe"),
                "or_yoy": values.get("calculate_operating_income_yoy_growth_ratio"),
                "netprofit_yoy": values.get("calculate_parent_holder_net_profit_yoy_growth_ratio"),
            }
            ann_date = ann_map.get(end_iso or "")
            if ann_date:
                record["ann_date"] = ann_date
            records.append(record)
        if not records:
            return []
        # 升序：最近报告期在最后，与 AKShare 出口一致。
        records.reverse()
        return normalize_financial_records(records)

    def get_income(self, stock_code: str) -> Any:
        """获取利润表（年度，最近 4 期，按报告期升序）。

        Fuyao 按报告期**降序**返回，而工具层以最后一行为最新一期，因此这里
        显式升序，与日线/估值/财务指标的出口顺序保持一致。
        """
        data = self._call(
            "a-share", "get_a_share_financials_income_statements",
            thscode=_to_thscode(stock_code), period="annual", limit=4,
        )
        items = (data or {}).get("item") or []
        rows: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["period_end"] = _from_ms(item.get("period_end_ms"))
            row["report_date"] = _from_ms(item.get("report_date_ms"))
            rows.append(row)
        rows.sort(key=lambda row: str(row.get("period_end") or ""))
        return rows

    def get_trade_cal(self, start_date: str = "", end_date: str = "") -> Any:
        """获取交易日历（Fuyao 固定返回近一年，按日期升序）。"""
        data = self._call("a-share", "get_a_share_calendar_trading_days")
        items = (data or {}).get("item") or []
        rows = [
            {"cal_date": _from_ms(item.get("date_ms")), "is_open": True}
            for item in items
            if isinstance(item, dict) and item.get("date_ms") is not None
        ]
        start, end = start_date, end_date
        if start or end:
            rows = [
                row for row in rows
                if (not start or str(row["cal_date"]) >= start)
                and (not end or str(row["cal_date"]) <= end)
            ]
        if not rows:
            return []
        return normalize_trade_cal_records(rows)

    # ── 指数 ──────────────────────────────────────────────────

    def get_index_daily(
        self,
        index_symbol: str,
        start_date: str = "",
        end_date: str = "",
    ) -> Any:
        """获取指数日线（指数无复权口径）。"""
        start, end = _default_window(start_date, end_date)
        data = self._call(
            "a-share-index", "get_a_share_index_prices_historical",
            thscode=_index_thscode(index_symbol),
            interval="1d",
            start=_to_ms(start),
            end=_to_ms(end),
        )
        items = (data or {}).get("item") or []
        if not items:
            return []
        return normalize_index_daily_records(_bars_to_daily(items))

    # ── 本源未声明的能力（交由降级链中的 AKShare 提供）──────────

    def get_stock_basic(self, stock_code: str = "") -> Any:
        """Fuyao 代码表不含"行业"字段，基础信息交由 AKShare 提供。"""
        raise UnsupportedProviderCapability(
            "Fuyao 代码表不含行业字段，get_stock_basic 交由 AKShare 提供"
        )

    def get_market_breadth(self) -> Any:
        """Fuyao 不提供市场宽度快照。"""
        raise UnsupportedProviderCapability("Fuyao 不提供市场宽度接口")

    def get_margin_summary(self) -> Any:
        """Fuyao 不提供两市融资融券汇总。"""
        raise UnsupportedProviderCapability("Fuyao 不提供融资融券接口")

    def get_northbound_holdings(self) -> Any:
        """Fuyao 不提供北向持股市值。"""
        raise UnsupportedProviderCapability("Fuyao 不提供北向持股接口")

    def get_policy_news(self) -> Any:
        """Fuyao 不提供财经快讯/政策新闻。"""
        raise UnsupportedProviderCapability("Fuyao 不提供财经快讯接口")


__all__ = [
    "FuyaoMcpClient",
    "FuyaoMcpDataSource",
    "FuyaoMcpError",
]
