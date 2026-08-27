"""Data infrastructure layer: BaoStock, EastMoney, Sina, and Tushare MCP data sources."""

from finance_agent.data.tushare_mcp import (
    TushareMcpClient,
    TushareMcpDataSource,
    TushareMcpError,
    get_datasource as get_tushare_datasource,
    is_available as is_tushare_available,
)

__all__ = [
    "TushareMcpClient",
    "TushareMcpDataSource",
    "TushareMcpError",
    "get_tushare_datasource",
    "is_tushare_available",
]
