"""Agent 定义 —— 总管、股票分析、资产配置、产品分析和闲聊专家。"""

from finance_agent.agents.base import ProceduralAgent, ReActAgent, AgentProtocol
from finance_agent.agents.supervisor import ManagerAgent, SupervisorAgent
from finance_agent.agents.casual_chat import CasualChatAgent
from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.asset_allocation import AssetAllocationAgent
from finance_agent.agents.product_analysis import ProductAnalysisAgent

__all__ = [
    "AgentProtocol",
    "ProceduralAgent",
    "ReActAgent",
    "ManagerAgent",
    "SupervisorAgent",
    "CasualChatAgent",
    "StockAnalysisAgent",
    "AssetAllocationAgent",
    "ProductAnalysisAgent",
]
