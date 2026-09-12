"""市场洞察专家（market_insight）：只回答市场整体层面的问题。

**边界（硬约束）：** 本专家只负责市场级问题（大盘/指数/市场情绪/资金面），
绝不输出个股结论、个股评级、推荐、仓位或资产配置。任何涉及具体标的的请求
都应留在 ``stock_analysis`` 处理。

**当前能力：** 指数行情与市场宽度数据尚未接入任何 Provider，因此本轮对
``market_overview`` 返回结构化、诚实的降级说明，而不是给出编造或近似的大盘数据。
数据能力接入后，在本模块内替换为真实取数即可，路由与边界无需改动。
"""

from __future__ import annotations

from typing import Any, Dict

from finance_agent.agents.base import ProceduralAgent


# 当前唯一已实现的模式；sentiment / capital_flow 为预留空壳。
_SUPPORTED_MODES = {"market_overview"}

_UNAVAILABLE = (
    "市场概览数据尚未接入：系统目前没有指数行情与市场宽度数据源，"
    "因此暂无法给出大盘概览。您可以直接指定具体股票，我将为您做基本面与技术面分析。"
)


class MarketInsightAgent(ProceduralAgent):
    """市场洞察专家：市场级问题，不产出个股结论。"""

    agent_name = "market_insight"

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        mode = self._mode(state)
        if mode == "market_overview":
            content = _UNAVAILABLE
            status = "degraded"
        else:
            content = f"暂不支持的市场洞察模式：{mode}。"
            status = "degraded"

        intent = self._intent(state)
        intent_results = state.get("intent_results", {}) or {}
        intent_results[intent] = {"status": status, "content": content}
        state["intent_results"] = intent_results
        state["market_insight"] = {"mode": mode, "status": status}
        state["agent_response"] = content
        return state

    @staticmethod
    def _mode(state: Dict[str, Any]) -> str:
        """从任务上下文或意图槽位读取执行模式，缺省为 market_overview。"""
        context = state.get("task_context", {}) or {}
        mode = str(context.get("execution_mode", "")).strip()
        if not mode:
            slots = (state.get("intent_slots", {}) or {}).get("market_insight", {})
            if isinstance(slots, dict):
                mode = str(slots.get("execution_mode", "")).strip()
        return mode or "market_overview"

    @staticmethod
    def _intent(state: Dict[str, Any]) -> str:
        intent = str(state.get("current_task_intent", "")).strip()
        return intent or "market_insight"


__all__ = ["MarketInsightAgent"]
