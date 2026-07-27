"""LangChain 工具 —— 股票数据获取与 MPT 资产配置计算。"""

from finance_agent.tools.stock_data import (
    get_stock_basic_info,
    get_stock_realtime_quote,
    get_financial_indicators,
    get_stock_history,
)
from finance_agent.tools.allocation import calculate_stock_metrics, optimize_portfolio
from finance_agent.tools.auth import UserStore, get_user_store
from finance_agent.tools.compliance import check_sensitive_words
from finance_agent.tools.qianfan_search import QianfanSearchError, QianfanStockSearch
from finance_agent.tools.baostock import BaostockDataSource, get_datasource
from finance_agent.tools.finance_slots import (
    FinanceSlotsExtractor,
    create_extract_finance_slots_tool,
    extract_investment_goal,
)

__all__ = [
    "get_stock_basic_info",
    "get_stock_realtime_quote",
    "get_financial_indicators",
    "get_stock_history",
    "calculate_stock_metrics",
    "optimize_portfolio",
    "UserStore",
    "get_user_store",
    "check_sensitive_words",
    "QianfanSearchError",
    "QianfanStockSearch",
    "BaostockDataSource",
    "get_datasource",
    "FinanceSlotsExtractor",
    "create_extract_finance_slots_tool",
    "extract_investment_goal",
]
