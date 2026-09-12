"""Tushare MCP 远程数据源适配器。

通过 MCP 客户端协议（streamable HTTP）连接 Tushare 官方托管的 MCP Server，
获取 A 股行情、财务报表、指数等金融数据。

设计原则：
1. 底层 TushareMcpClient 封装 MCP 协议细节，对外暴露 list_tools / call_tool
2. 高层 TushareMcpDataSource 提供与 BaostockDataSource 对齐的业务接口
3. MCP 客户端是异步的，通过线程隔离的方式在同步代码中安全调用
4. URL 中的 token 由 config.TUSHARE_MCP_URL 统一管理，不硬编码
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from finance_agent.config import TUSHARE_MCP_TIMEOUT, TUSHARE_MCP_URL
from finance_agent.data.normalization import (
    normalize_basic_records,
    normalize_daily_records,
    normalize_financial_records,
    normalize_trade_cal_records,
    normalize_valuation_records,
)
from finance_agent.data.providers import UnsupportedProviderCapability

logger = logging.getLogger(__name__)


def _run_async_safely(coro: Any) -> Any:
    """在同步上下文中安全运行异步协程。

    MCP 客户端基于 asyncio，但项目主体是同步代码。
    若当前线程已在事件循环中（如 FastAPI 异步路由），
    则在新线程中创建独立事件循环执行，避免嵌套循环报错。
    """
    try:
        asyncio.get_running_loop()
        # 当前线程已有运行中的事件循环，需在新线程执行
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
        # 当前线程没有运行中的事件循环，直接执行
        return asyncio.run(coro)


class TushareMcpError(RuntimeError):
    """Tushare MCP 数据源错误。"""


class TushareMcpClient:
    """Tushare MCP 底层客户端封装。

    封装 streamable HTTP 连接管理、工具发现与工具调用，
    对外提供同步接口，屏蔽 MCP 协议与 asyncio 细节。
    """

    def __init__(self, url: str = TUSHARE_MCP_URL, timeout: float = TUSHARE_MCP_TIMEOUT):
        if not url:
            raise TushareMcpError(
                "TUSHARE_MCP_URL 未配置，请在 .env 中设置 "
                "TUSHARE_MCP_URL=https://api.tushare.pro/mcp/?token=YOUR_TOKEN"
            )
        self.url = url
        self.timeout = timeout

    async def _session_call(self, action: str, tool_name: str | None = None,
                            arguments: dict[str, Any] | None = None) -> Any:
        """建立 MCP 连接并执行一次操作（list_tools 或 call_tool）。

        每次调用都建立新连接，因为 streamable HTTP 是无状态协议，
        复用连接的收益有限且会增加状态管理复杂度。
        """
        # 通过自定义 httpx2 客户端控制超时
        async with httpx2.AsyncClient(timeout=self.timeout) as http_client:
            async with streamable_http_client(self.url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    if action == "list_tools":
                        result = await session.list_tools()
                        # 返回工具名称与描述的列表
                        return [
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "input_schema": tool.inputSchema,
                            }
                            for tool in result.tools
                        ]

                    if action == "call_tool":
                        result = await session.call_tool(tool_name, arguments or {})
                        # MCP 工具返回的 content 通常是 TextContent，text 字段为 JSON 字符串
                        if not result.content:
                            return None
                        text = result.content[0].text
                        try:
                            return json.loads(text)
                        except (json.JSONDecodeError, TypeError):
                            return text

                    raise TushareMcpError(f"未知的 MCP 操作: {action}")

    def list_tools(self) -> list[dict[str, Any]]:
        """列出 Tushare MCP Server 提供的所有工具。

        Returns:
            工具列表，每项包含 name / description / input_schema
        """
        return _run_async_safely(self._session_call("list_tools"))

    def call_tool(self, name: str, **arguments: Any) -> Any:
        """调用 Tushare MCP 工具并返回解析后的结果。

        Args:
            name: 工具名称，如 "get_daily_data"
            **arguments: 工具参数，如 ts_code="000001.SZ"

        Returns:
            工具返回的数据（已解析为 Python 对象）
        """
        return _run_async_safely(
            self._session_call("call_tool", name, arguments)
        )


# ── 股票代码格式转换 ──────────────────────────────────────────

def _to_ts_code(stock_code: str) -> str:
    """将纯数字 A 股代码转换为 Tushare 格式（带交易所后缀）。

    例如：600519 -> 600519.SH，000001 -> 000001.SZ
    """
    code = str(stock_code).strip()
    # 已是 tushare 格式则直接返回
    if "." in code:
        return code
    if code.startswith(("60", "68", "90")):
        return f"{code}.SH"
    if code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    if code.startswith(("43", "83", "87", "92")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _to_date(date_str: str) -> str:
    """将 YYYY-MM-DD 格式转为 Tushare 使用的 YYYYMMDD 格式。"""
    return str(date_str).replace("-", "")


class TushareMcpDataSource:
    """Tushare MCP 高层数据源适配器。

    提供统一股票数据接口（与 AKShare / BaoStock 适配器对齐），
    内部通过 TushareMcpClient 调用远程 MCP 工具获取数据。

    若不确定 Tushare MCP Server 暴露的工具名称，
    可先调用 discover_tools() 查看完整工具列表。
    """

    provider_name = "tushare_mcp"

    def is_available(self) -> bool:
        """返回 Tushare MCP 是否已配置。"""
        return bool(self.client.url)

    def __init__(self, url: str = TUSHARE_MCP_URL, timeout: float = TUSHARE_MCP_TIMEOUT):
        self.client = TushareMcpClient(url, timeout)

    def discover_tools(self) -> list[dict[str, Any]]:
        """发现并返回 Tushare MCP Server 提供的所有工具。

        首次集成时调用此方法，确认实际可用的工具名称与参数。
        """
        return self.client.list_tools()

    def _safe_call(self, name: str, **arguments: Any) -> Any:
        """调用工具并捕获异常，统一包装为 TushareMcpError。"""
        try:
            return self.client.call_tool(name, **arguments)
        except TushareMcpError:
            raise
        except Exception as exc:
            raise TushareMcpError(f"Tushare MCP 工具 {name} 调用失败: {exc}") from exc

    def get_daily(
        self,
        stock_code: str,
        start_date: str = "",
        end_date: str = "",
        adjustment: str = "raw",
    ) -> Any:
        """获取 A 股日线行情（开高低收、成交量等）。

        Args:
            stock_code: 股票代码，如 600519
            start_date: 开始日期 YYYY-MM-DD，默认最近一年
            end_date: 结束日期 YYYY-MM-DD，默认今天
        """
        from datetime import datetime, timedelta

        if adjustment != "raw":
            raise UnsupportedProviderCapability(
                "Tushare MCP 当前日线接口未声明复权口径"
            )

        ts_code = _to_ts_code(stock_code)
        end = end_date or datetime.now().strftime("%Y-%m-%d")
        start = start_date or (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        return normalize_daily_records(self._safe_call(
            "get_daily_data",
            ts_code=ts_code,
            start_date=_to_date(start),
            end_date=_to_date(end),
        ))

    def get_stock_basic(self, stock_code: str = "") -> Any:
        """获取 A 股基础信息（代码、名称、行业、上市日期等）。

        Args:
            stock_code: 股票代码；为空时返回全部股票列表
        """
        kwargs: dict[str, Any] = {}
        if stock_code:
            kwargs["ts_code"] = _to_ts_code(stock_code)
        return normalize_basic_records(self._safe_call("get_stock_basic", **kwargs))

    def get_daily_basic(self, stock_code: str, start_date: str = "",
                        end_date: str = "") -> Any:
        """获取每日估值指标（PE、PB、PS、总市值、流通市值等）。

        Args:
            stock_code: 股票代码
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
        """
        from datetime import datetime, timedelta

        ts_code = _to_ts_code(stock_code)
        end = end_date or datetime.now().strftime("%Y-%m-%d")
        start = start_date or (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        return normalize_valuation_records(self._safe_call(
            "get_daily_basic",
            ts_code=ts_code,
            start_date=_to_date(start),
            end_date=_to_date(end),
        ))

    def get_financial_indicator(self, stock_code: str) -> Any:
        """获取财务指标（ROE、毛利率、净利率等）。

        Args:
            stock_code: 股票代码
        """
        return normalize_financial_records(self._safe_call(
            "get_fina_indicator",
            ts_code=_to_ts_code(stock_code),
        ))

    def get_income(self, stock_code: str) -> Any:
        """获取利润表数据。

        Args:
            stock_code: 股票代码
        """
        return self._safe_call(
            "get_income",
            ts_code=_to_ts_code(stock_code),
        )

    def get_trade_cal(self, start_date: str = "", end_date: str = "") -> Any:
        """获取交易日历。

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
        """
        from datetime import datetime, timedelta

        end = end_date or datetime.now().strftime("%Y-%m-%d")
        start = start_date or (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        return normalize_trade_cal_records(self._safe_call(
            "get_trade_cal",
            start_date=_to_date(start),
            end_date=_to_date(end),
        ))

    def get_index_daily(
        self,
        index_symbol: str,
        start_date: str = "",
        end_date: str = "",
    ) -> Any:
        """Tushare MCP 指数日线路径未经验证（本仓库无可用 token），暂不声明。"""
        raise UnsupportedProviderCapability(
            "Tushare MCP 指数接口未在无 token 环境验证，暂不声明该能力"
        )

    def get_market_breadth(self) -> Any:
        """Tushare MCP 不提供市场宽度快照。"""
        raise UnsupportedProviderCapability("Tushare MCP 不提供市场宽度接口")

    def get_northbound_flow(self) -> Any:
        """Tushare MCP 北向资金路径未经验证（本仓库无可用 token），暂不声明。"""
        raise UnsupportedProviderCapability(
            "Tushare MCP 北向资金接口未在无 token 环境验证，暂不声明该能力"
        )

