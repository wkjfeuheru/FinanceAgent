"""LangChain 工具 —— 按 Agent 边界划分，每个文件服务一个 Agent。"""

# Tushare MCP 行情与基本面工具
from finance_agent.orchestrator.tools.tushare import (
    get_stock_basic_info,
    get_stock_quote,
    get_stock_realtime_quote,
    get_stock_history,
    get_financial_indicators,
    get_valuation_indicators,
    get_income_statement,
    search_candidates,
)

# 业务数据库只读工具
from finance_agent.orchestrator.tools.database import (
    query_user_profile,
    list_user_conversations,
    get_user_conversation_messages,
)

# StockAnalysisAgent 工具
from finance_agent.orchestrator.tools.technical import (
    INDICATOR_NAMES,
    calc_boll,
    calc_kdj,
    calc_ma,
    calc_macd,
    calc_rsi,
    calc_wr,
    compute_all_indicators,
)

# AssetAllocationAgent 工具
from finance_agent.orchestrator.tools.allocation import calculate_stock_metrics, optimize_portfolio

# ProductAnalysisAgent 工具
from finance_agent.orchestrator.tools.product import query_product, list_products

__all__ = [
    "get_stock_basic_info",
    "get_stock_quote",
    "get_stock_realtime_quote",
    "get_financial_indicators",
    "get_stock_history",
    "get_valuation_indicators",
    "get_income_statement",
    "search_candidates",
    "query_user_profile",
    "list_user_conversations",
    "get_user_conversation_messages",
    "calculate_stock_metrics",
    "optimize_portfolio",
    "query_product",
    "list_products",
    "compute_all_indicators",
    "INDICATOR_NAMES",
    "calc_macd",
    "calc_kdj",
    "calc_rsi",
    "calc_boll",
    "calc_ma",
    "calc_wr",
]
