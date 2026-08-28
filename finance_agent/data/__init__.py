"""Data infrastructure layer: Tushare MCP, product library, and user store."""

from finance_agent.data.auth import UserStore, get_user_store
from finance_agent.data.product_library import ProductLibrary
from finance_agent.data.tushare_mcp import (
    TushareMcpClient,
    TushareMcpDataSource,
    TushareMcpError,
    get_datasource as get_tushare_datasource,
    is_available as is_tushare_available,
)

__all__ = [
    "ProductLibrary",
    "TushareMcpClient",
    "TushareMcpDataSource",
    "TushareMcpError",
    "get_tushare_datasource",
    "is_tushare_available",
    "UserStore",
    "get_user_store",
]
