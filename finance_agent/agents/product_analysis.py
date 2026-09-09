"""金融产品解读专家。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from langchain_core.messages import ToolMessage

from finance_agent.agents.base import ReActAgent
from finance_agent.config import safe_parse_json
from finance_agent.orchestrator.tools.database import list_products, query_product


_PRODUCT_ANALYSIS_PROMPT = """你是金融产品解读专家，专注于基金、ETF等金融产品的事实性分析。

你必须先通过 query_product 或 list_products 查询产品库，再基于工具返回的数据回答。
用户要求深度分析时，输出产品概况、投资策略、业绩表现、风险特征四部分；
用户要求比较时，按收益、风险、费率、规模横向比较并说明适用场景；
用户询问持仓、经理、费率或申赎规则时，只回答产品库中已有事实。
产品库没有数据时，明确说明“产品库暂无该产品数据”；数据字段缺失时明确说明暂无该数据，绝不编造。
使用正式、专业的中文。"""


class ProductAnalysisAgent(ReActAgent):
    """通过产品库工具完成单产品解读、多产品比较和具体问答。"""

    agent_name = "product_analysis"
    max_reasoning_steps = 6
    per_invoke_timeout = 60.0

    def _get_tools(self) -> list:
        """返回产品库查询工具，供 ReAct 模型自主规划调用。"""
        return [query_product, list_products]

    def _get_system_prompt(self) -> str:
        """返回产品解读专家的系统提示词。"""
        return _PRODUCT_ANALYSIS_PROMPT

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行产品解读，并将文本结果和结构化产品数据写回状态。"""
        result = super().invoke(state)
        state["product_analysis"] = self._build_result(state)
        response = str(state.get("agent_response", "")).strip()
        state.setdefault("intent_results", {})["product_analysis"] = {
            "status": "success" if response else "degraded",
            "content": response,
        }
        return result

    def _build_result(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """从最近一次 ReAct 消息中提取产品数据并判定分析类型。"""
        message = str(state.get("user_message", ""))
        response = str(state.get("agent_response", ""))
        if any(word in message for word in ("对比", "比较", "哪个好", "区别")):
            result_type = "comparison"
        elif any(word in message for word in ("深度", "全面", "透视", "分析")):
            result_type = "deep_dive"
        else:
            result_type = "question"

        products: list[dict[str, Any]] = []
        if self._agent is not None:
            try:
                thread_id = state.get("thread_id", "default")
                snapshot = self.agent.get_state({"configurable": {"thread_id": thread_id}})
                messages = snapshot.values.get("messages", []) if snapshot else []
                for item in messages:
                    if isinstance(item, ToolMessage) and item.name == "query_product":
                        data = safe_parse_json(str(item.content), {})
                        if isinstance(data, dict) and "error" not in data:
                            products.append(data)
            except Exception:
                products = []

        codes = re.findall(r"(?<!\d)\d{6}(?!\d)", message)
        if not products and codes:
            products = [{"basic_info": {"code": code}} for code in dict.fromkeys(codes)]
        return {
            "type": result_type,
            "product_codes": [item.get("basic_info", {}).get("code", "") for item in products],
            "products": products,
            "report": response,
        }


__all__ = ["ProductAnalysisAgent"]
