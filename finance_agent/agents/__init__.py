"""Agent 定义 —— 监督者、画像抽取、数据获取、股票分析、资产配置、合规风控。"""

from finance_agent.agents.base import ProceduralAgent, ReActAgent, AgentProtocol
from finance_agent.agents.supervisor import SupervisorAgent
from finance_agent.agents.profile import ProfileAgent
from finance_agent.agents.data_fetch import DataFetchAgent
from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.asset_allocation import AssetAllocationAgent
from finance_agent.agents.compliance import ComplianceAgent

__all__ = [
    "AgentProtocol",
    "ProceduralAgent",
    "ReActAgent",
    "SupervisorAgent",
    "ProfileAgent",
    "DataFetchAgent",
    "StockAnalysisAgent",
    "AssetAllocationAgent",
    "ComplianceAgent",
]
