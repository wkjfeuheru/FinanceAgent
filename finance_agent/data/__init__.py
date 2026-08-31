"""Data infrastructure layer: Tushare MCP and PostgreSQL stores."""

from finance_agent.data.auth import get_user_store
from finance_agent.data.product_library import get_product_library
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
    "get_product_library",
    "get_user_store",
]
