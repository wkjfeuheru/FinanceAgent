"""Agent 定义 —— 监督者、画像抽取、数据获取、基本面分析、资产配置、合规风控。"""

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.agents.supervisor import SupervisorAgent
from finance_agent.agents.profile_extraction import ProfileExtractionAgent
from finance_agent.agents.data_fetch import DataFetchAgent
from finance_agent.agents.fundamental_analysis import FundamentalAnalysisAgent
from finance_agent.agents.asset_allocation import AssetAllocationAgent
from finance_agent.agents.compliance import ComplianceAgent

__all__ = [
    "BaseFinanceAgent",
    "SupervisorAgent",
    "ProfileExtractionAgent",
    "DataFetchAgent",
    "FundamentalAnalysisAgent",
    "AssetAllocationAgent",
    "ComplianceAgent",
]
