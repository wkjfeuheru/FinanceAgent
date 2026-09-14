"""市场洞察专家（market_insight）：只回答市场整体层面的问题。

**边界（硬约束）：** 本专家只负责市场级问题（大盘/指数/市场情绪/资金面/政策事件），
绝不输出个股结论、个股评级、推荐、仓位或资产配置。任何涉及具体标的的请求
都应留在 ``stock_analysis`` 处理。

**模式：**

- ``market_overview``：主要指数最新价、涨跌幅、成交额、近 5/20 日区间涨跌 + 市场宽度；
- ``market_sentiment``：涨跌家数/涨跌停/活跃度 + 上证指数涨跌作为参照；
- ``capital_flow``：两市融资融券日频（含日环比）+ 北向持股市值（季度披露）；
- ``policy_impact``：近 N 天政策类新闻的确定性筛选 + 定性影响解读。

确定性渲染与领域子图位于 ``finance_agent.orchestrator.domains.market``；本模块
保留取数注入点（模块全局）与旧编排兼容的薄 Agent。
"""

from __future__ import annotations

from typing import Any, Dict

from finance_agent.agents.base import ProceduralAgent
from finance_agent.orchestrator.domains.market import (
    PolicyImpactInterpreter,
    render,
    unavailable_for,
)
from finance_agent.orchestrator.tools.marketdata import (
    get_capital_flow_data,
    get_market_overview_data,
    get_market_sentiment_data,
    get_policy_events_data,
)

_MODE_COLLECTOR_NAMES = {
    "market_overview": "get_market_overview_data",
    "market_sentiment": "get_market_sentiment_data",
    "capital_flow": "get_capital_flow_data",
    "policy_impact": "get_policy_events_data",
}


def _collector_for(mode: str):
    """按模式解析取数函数；在调用时从模块命名空间查找，便于测试注入。"""
    name = _MODE_COLLECTOR_NAMES.get(mode)
    return globals().get(name) if name else None


class MarketInsightAgent(ProceduralAgent):
    """市场洞察专家：市场级问题，不产出个股结论。"""

    agent_name = "market_insight"

    def __init__(self, interpreter: PolicyImpactInterpreter | None = None, **_: Any) -> None:
        self._interpreter = interpreter or PolicyImpactInterpreter()

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        mode = self._mode(state)
        collector = _collector_for(mode)
        if collector is None:
            content = (
                f"暂不支持的市场洞察模式：{mode}。"
                "目前支持大盘概览、市场情绪、资金面与政策事件影响。"
            )
            return self._write(state, mode, content, "degraded")

        data = collector()
        limitations = list(data.get("limitations", []) or [])
        content = render(mode, data, limitations, self._interpreter)
        if not content:
            return self._write(state, mode, unavailable_for(mode), "degraded")

        if limitations:
            content += "\n\n限制与提示：" + "、".join(limitations) + "。"
        status = "partial" if limitations else "success"
        return self._write(state, mode, content, status, data=data)

    def _write(
        self, state: Dict[str, Any], mode: str, content: str, status: str,
        *, data: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        intent = str(state.get("current_task_intent", "")).strip() or "market_insight"
        intent_results = state.get("intent_results", {}) or {}
        intent_results[intent] = {"status": status, "content": content}
        state["intent_results"] = intent_results
        state["market_insight"] = {"mode": mode, "status": status, **(data or {})}
        state["agent_response"] = content
        return state

    @staticmethod
    def _unavailable_for(mode: str) -> str:
        return unavailable_for(mode)

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


__all__ = ["MarketInsightAgent", "PolicyImpactInterpreter"]
