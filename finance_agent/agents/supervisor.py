"""监督者 Agent。

职责：根据用户当前问题选择需要执行的子 Agent，并给出执行顺序。

不处理具体业务，仅做编排决策。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.config import get_model_for_agent, safe_parse_json


_SUPERVISOR_PROMPT = """你是金融投顾系统的任务规划器。

## 职责
1. 直接判断回答当前问题需要执行哪些子 Agent
2. 判断缺失的必要信息（风险偏好、预算、股票代码、持有时间）
3. 按依赖关系输出执行顺序

## 用户画像询问规则
- 只有用户明确要求投资建议、买卖判断、选股推荐、资产配置、仓位或组合优化时，
  才能把 risk_preference、budget_amount、holding_period 放入 missing_info。
- 基本面分析、财务分析、公司对比、行情或指标查询、新闻解读等研究型请求，
  missing_info 必须为空，且不执行 asset_allocation。

## 可用的子Agent
- slot_extraction: 提取关键槽位（风险偏好、预算、持有时间、股票身份）
- data_fetch: 从 BaoStock 获取股票行情和财务指标
- fundamental_analysis: 基本面分析（盈利能力、成长性、估值、财务健康）
- asset_allocation: 资产配置建议（MPT均值-方差优化）
- compliance: 合规风控审查

## 输出格式
返回JSON：
{{
  "missing_info": ["缺失的关键信息，如 stock_codes/budget/holding_period"],
  "task_plan": ["需要执行的子Agent序列"],
  "reason": "分析原因"
}}

## 示例
用户输入："我想投资10万元，关注贵州茅台(600519)和招商银行(600036)，持有3个月"
输出：{{"missing_info": ["risk_preference"], "task_plan": ["slot_extraction", "data_fetch", "fundamental_analysis", "asset_allocation", "compliance"], "reason": "需要先提取参数、获取数据、分析基本面，再进行组合优化与合规审查"}}

用户输入："推荐几只AI行业股票"
输出：{{"missing_info": ["risk_preference", "budget_amount", "holding_period"], "task_plan": ["slot_extraction", "data_fetch", "fundamental_analysis", "compliance"], "reason": "建立AI研究候选池后获取数据并比较基本面"}}
"""


_INVESTMENT_ADVICE_MARKERS = (
    "推荐", "选股", "筛选", "候选", "值得投资", "投资建议",
    "买入", "卖出", "能买吗", "能不能买", "该不该买", "怎么买",
    "资产配置", "组合配置", "配置方案", "如何配置", "怎么配置", "配置比例",
    "各配多少", "哪种方案", "哪个方案", "仓位", "分配资金", "分配下资金",
    "投多少钱", "持有多久", "组合优化", "最大夏普", "最小方差",
    "构建组合", "组组合", "建组合", "怎么组合", "如何组合", "组合一下",
    "配一下", "配置一下", "调整组合", "调整权重", "调整下权重", "权重", "怎么配", "如何配",
    "优化组合", "优化下组合",
)


def needs_investment_profile(message: str) -> bool:
    """仅对明确涉及投资决策或配置的请求收集风险、资金和期限。"""
    normalized = (message or "").strip().lower()
    if any(marker in normalized for marker in _INVESTMENT_ADVICE_MARKERS):
        return True
    # 组合构建/配置追问：用户已看过股票分析，想让系统组合
    return bool(re.search(
        r"(?:帮|给|为)(?:我|我们).{0,6}(?:构建|组成|搭配|组合|配置|分配|调整)",
        normalized,
    ))


def needs_asset_allocation(message: str) -> bool:
    """确定性识别组合配置意图，避免监督模型漏掉 AssetAllocationAgent。"""
    normalized = (message or "").strip().lower()
    direct_markers = (
        "资产配置", "组合配置", "配置方案", "配置比例", "各配多少",
        "哪种方案", "哪个方案", "仓位分配", "分配资金", "组合优化",
        "最大夏普", "最小方差",
        "构建组合", "组组合", "建组合", "组合一下",
        "配一下", "配置一下", "调整组合", "调整权重", "调整下权重",
        "权重分配", "怎么组合", "如何组合", "怎样组合", "怎么配", "如何配",
        "分配下", "资金分配", "配比", "配置权重", "组合权重",
        # 含"权重"的追问几乎总是组合配置意图
        "权重",
    )
    if any(marker in normalized for marker in direct_markers):
        return True
    # 正则兜底：
    # 1. "组合/股票/标的 + 如何/怎么/怎样/应该如何 + 配置"
    if re.search(r"(?:组合|股票|标的).{0,12}(?:如何|怎么|怎样|应该如何)?配置", normalized):
        return True
    # 2. "帮/给/为我 + 构建/组成/搭配/组合/配置/分配/调整 组合"
    if re.search(r"(?:帮|给|为)(?:我|我们).{0,6}(?:构建|组成|搭配|组合|配置|分配|调整|优化)", normalized):
        return True
    # 3. "组合/配置/分配/调整/优化 + 一下/权重/比例"
    if re.search(r"(?:组合|配置|分配|调整|优化)(?:一下|权重|比例)", normalized):
        return True
    return False


class SupervisorAgent(BaseFinanceAgent):
    """监督者 Agent —— 根据问题生成最小必要任务计划。"""

    agent_name: str = "supervisor"

    def __init__(self, shared_memory=None):
        super().__init__(shared_memory=shared_memory)
        self._planning_chain = None

    def _get_tools(self) -> list:
        return []

    def _get_system_prompt(self) -> str:
        return _SUPERVISOR_PROMPT

    @property
    def planning_chain(self):
        """独立的任务规划链。"""
        if self._planning_chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", _SUPERVISOR_PROMPT),
                ("human", "对话上下文：\n{context}\n\n当前用户输入：{message}\n\n请选择需要执行的子 Agent："),
            ])
            self._planning_chain = prompt | get_model_for_agent("supervisor") | StrOutputParser()
        return self._planning_chain

    def plan_tasks(
        self,
        message: str,
        context: str = "",
    ) -> Dict[str, Any]:
        """根据当前问题选择并排列需要执行的子 Agent。

        Args:
            message: 用户输入
            context: 对话上下文

        Returns:
            {"missing_info": list, "task_plan": list, "reason": str}
        """
        if needs_asset_allocation(message):
            return {
                "missing_info": ["risk_preference", "budget_amount", "holding_period"],
                "task_plan": [
                    "slot_extraction", "data_fetch", "fundamental_analysis",
                    "asset_allocation", "compliance",
                ],
                "reason": "用户明确要求多标的组合配置，需获取行情与历史数据后执行资产配置优化",
            }

        screening_words = ("推荐", "选股", "筛选", "候选", "值得投资")
        if any(word in message for word in screening_words):
            return {
                "missing_info": ["risk_preference", "budget_amount", "holding_period"],
                "task_plan": ["slot_extraction", "data_fetch", "fundamental_analysis", "compliance"],
                "reason": "当前消息需要先搜索相关行业或主题的A股候选，再获取数据并分析",
            }

        if any(word in message for word in ("基本面", "财务分析", "公司分析")):
            return {
                "missing_info": [],
                "task_plan": ["slot_extraction", "data_fetch", "fundamental_analysis", "compliance"],
                "reason": "基本面问题需要提取股票、获取财务数据、执行基本面分析和敏感词检查",
            }

        try:
            result = self.planning_chain.invoke({
                "context": context or "无上下文",
                "message": message,
            })
            parsed = safe_parse_json(result, {
                "missing_info": [],
                "task_plan": ["slot_extraction", "data_fetch", "fundamental_analysis", "asset_allocation", "compliance"],
                "reason": "任务计划解析失败，使用完整分析流程",
            })
        except Exception:
            parsed = {
                "missing_info": [],
                "task_plan": ["slot_extraction", "data_fetch", "fundamental_analysis", "asset_allocation", "compliance"],
                "reason": "任务规划异常，使用完整分析流程",
            }

        if not parsed.get("task_plan"):
            parsed["task_plan"] = ["slot_extraction", "data_fetch", "fundamental_analysis", "asset_allocation", "compliance"]

        allowed = ["slot_extraction", "data_fetch", "fundamental_analysis", "asset_allocation", "compliance"]
        requested = {step for step in parsed["task_plan"] if step in allowed}
        if needs_asset_allocation(message):
            requested.add("asset_allocation")
        # 自动补齐数据依赖，但不添加与问题无关的下游 Agent。
        if "asset_allocation" in requested:
            requested.update({"slot_extraction", "data_fetch", "fundamental_analysis"})
        elif "fundamental_analysis" in requested:
            requested.update({"slot_extraction", "data_fetch"})
        elif "data_fetch" in requested:
            requested.add("slot_extraction")
        requested.add("compliance")
        parsed["task_plan"] = [step for step in allowed if step in requested]

        # LLM 只能规划研究流程，不能擅自向纯研究请求索取投资画像。
        if not needs_investment_profile(message):
            parsed["missing_info"] = []
            parsed["task_plan"] = [
                step for step in parsed["task_plan"] if step != "asset_allocation"
            ]

        return parsed

    def handle(
        self,
        message: str,
        compressed_context: str = "",
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """监督者不直接回复用户，返回任务计划。"""
        result = self.plan_tasks(message, compressed_context or memory_context)
        return f"任务计划：{' → '.join(result['task_plan'])}\n原因：{result.get('reason', '')}"
