"""Agent 定义 —— 总管、市场洞察、股票分析、产品分析和闲聊专家。"""

from finance_agent.agents.base import ProceduralAgent, AgentProtocol
from finance_agent.agents.supervisor import ManagerAgent
from finance_agent.agents.casual_chat import CasualChatAgent
from finance_agent.agents.market_insight import MarketInsightAgent
from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.product_analysis import ProductAnalysisAgent

__all__ = [
    "AgentProtocol",
    "ProceduralAgent",
    "ManagerAgent",
    "CasualChatAgent",
    "MarketInsightAgent",
    "StockAnalysisAgent",
    "ProductAnalysisAgent",
]
