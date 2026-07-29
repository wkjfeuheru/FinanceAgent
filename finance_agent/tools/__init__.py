"""LangChain 工具 —— 按 Agent 边界划分，每个文件服务一个 Agent。"""

# DataFetchAgent 工具
from finance_agent.tools.fundamental import (
    get_stock_basic_info,
    get_stock_realtime_quote,
    get_financial_indicators,
    get_stock_history,
)
from finance_agent.tools.web_search import WebSearchError, MarketSearch

# StockAnalysisAgent 工具
from finance_agent.tools.technical import (
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
from finance_agent.tools.allocation import calculate_stock_metrics, optimize_portfolio

# ComplianceAgent 工具
from finance_agent.tools.compliance import check_sensitive_words

# Auth（API 层使用）
from finance_agent.tools.auth import UserStore, get_user_store

# 注：BaostockDataSource 和 MarketData 已迁移至 finance_agent.data/
# 注：FinanceSlotsExtractor 将在后续任务中迁移至 agents/profile.py

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
    "WebSearchError",
    "MarketSearch",
    "compute_all_indicators",
    "INDICATOR_NAMES",
    "calc_macd",
    "calc_kdj",
    "calc_rsi",
    "calc_boll",
    "calc_ma",
    "calc_wr",
]
