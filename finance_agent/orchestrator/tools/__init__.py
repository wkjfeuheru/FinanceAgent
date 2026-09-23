"""LangChain 工具 —— 按业务域分组提供模型可调用工具。"""

# 股票行情与基本面工具（由统一 Provider Manager 路由到 AKShare/Tushare/BaoStock）
from finance_agent.orchestrator.tools.stockdata import (
    get_financial_indicators,
    get_income_statement,
    get_stock_basic_info,
    get_stock_history,
    get_stock_quote,
    get_valuation_indicators,
    search_candidates,
)

# 业务数据库只读工具（用户画像/会话 + 产品库）
from finance_agent.orchestrator.tools.database import (
    get_user_conversation_messages,
    list_products,
    list_user_conversations,
    query_product,
    query_user_profile,
)

# StockAnalysisAgent 技术指标工具
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

# 资产配置测算工具（纯函数：组合收益/波动率/集中度/参考权重）
from finance_agent.orchestrator.tools.allocation import (
    concentration_metrics,
    portfolio_return,
    portfolio_sharpe,
    portfolio_volatility,
    reference_bands,
    review_portfolio,
    risk_contribution,
)

__all__ = [
    "get_stock_basic_info",
    "get_stock_quote",
    "get_financial_indicators",
    "get_stock_history",
    "get_valuation_indicators",
    "get_income_statement",
    "search_candidates",
    "query_user_profile",
    "list_user_conversations",
    "get_user_conversation_messages",
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
    "concentration_metrics",
    "portfolio_return",
    "portfolio_sharpe",
    "portfolio_volatility",
    "reference_bands",
    "review_portfolio",
    "risk_contribution",
]
