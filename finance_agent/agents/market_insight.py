"""市场洞察专家（market_insight）：只回答市场整体层面的问题。

**边界（硬约束）：** 本专家只负责市场级问题（大盘/指数/市场情绪/资金面），
绝不输出个股结论、个股评级、推荐、仓位或资产配置。任何涉及具体标的的请求
都应留在 ``stock_analysis`` 处理。

**模式：**

- ``market_overview``：主要指数最新价与涨跌幅 + 市场宽度；
- ``market_sentiment``：涨跌家数/涨跌停/活跃度 + 上证指数涨跌作为参照；
- ``capital_flow``：北向资金各通道当日净买额（历史净流入因数据源披露变更停更）。

**数据边界：** 三项取数均 best-effort（见 ``tools/marketdata.py``），单项失败只在
"限制与提示"中列明，不伪造数值；整体无数据时给出诚实的降级说明。
渲染为确定性文本，不调用 LLM 生成数值。
"""

from __future__ import annotations

from typing import Any, Dict

from finance_agent.agents.base import ProceduralAgent
from finance_agent.orchestrator.tools.marketdata import (
    get_market_overview_data,
    get_market_sentiment_data,
    get_northbound_data,
)

_MODE_COLLECTOR_NAMES = {
    "market_overview": "get_market_overview_data",
    "market_sentiment": "get_market_sentiment_data",
    "capital_flow": "get_northbound_data",
}


def _collector_for(mode: str):
    """按模式解析取数函数；在调用时从模块命名空间查找，便于测试注入。"""
    name = _MODE_COLLECTOR_NAMES.get(mode)
    return globals().get(name) if name else None

_UNAVAILABLE = (
    "市场概览数据暂不可用：指数行情与市场宽度数据源当前均未取到数据。"
    "您可以直接指定具体股票，我将为您做基本面与技术面分析。"
)


def _pct(value: Any) -> str:
    """把涨跌幅格式化为带符号百分比。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:+.2f}%"


def _num(value: Any) -> str:
    """把数值格式化为紧凑字符串。"""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


class MarketInsightAgent(ProceduralAgent):
    """市场洞察专家：市场级问题，不产出个股结论。"""

    agent_name = "market_insight"

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        mode = self._mode(state)
        collector = _collector_for(mode)
        if collector is None:
            content = f"暂不支持的市场洞察模式：{mode}。目前支持大盘概览、市场情绪与北向资金。"
            return self._write(state, mode, content, "degraded")

        data = collector()
        limitations = list(data.get("limitations", []) or [])
        content = self._render(mode, data)
        if not content:
            return self._write(state, mode, _UNAVAILABLE, "degraded")

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
    def _render(mode: str, data: dict[str, Any]) -> str:
        """按模式渲染确定性文本；无有效内容时返回空串。"""
        if mode == "market_overview":
            return MarketInsightAgent._render_overview(data)
        if mode == "market_sentiment":
            return MarketInsightAgent._render_sentiment(data)
        if mode == "capital_flow":
            return MarketInsightAgent._render_capital_flow(data)
        return ""

    @staticmethod
    def _render_overview(data: dict[str, Any]) -> str:
        indices = data.get("indices") or []
        breadth = data.get("breadth") or {}
        as_of = str(data.get("as_of") or "").strip()
        if not indices and not breadth:
            return ""
        lines = ["### 大盘概览" + (f"（{as_of}）" if as_of else "")]
        if indices:
            lines.append("主要指数：")
            for item in indices:
                lines.append(
                    f"- {item.get('name', item.get('symbol'))}："
                    f"{_num(item.get('close'))}（{_pct(item.get('pct_chg'))}）"
                )
        if breadth:
            lines.append(
                f"市场宽度：上涨 {_num(breadth.get('advancing'))} 家，"
                f"下跌 {_num(breadth.get('declining'))} 家，"
                f"涨停 {_num(breadth.get('limit_up'))} 家，"
                f"跌停 {_num(breadth.get('limit_down'))} 家。"
            )
        return "\n".join(lines)

    @staticmethod
    def _render_sentiment(data: dict[str, Any]) -> str:
        breadth = data.get("breadth") or {}
        benchmark = data.get("benchmark") or {}
        as_of = str(data.get("as_of") or "").strip()
        if not breadth and not benchmark:
            return ""
        lines = ["### 市场情绪" + (f"（{as_of}）" if as_of else "")]
        if breadth:
            advancing = breadth.get("advancing") or 0
            declining = breadth.get("declining") or 0
            tone = "偏强" if advancing > declining else "偏弱" if declining > advancing else "均衡"
            lines.append(
                f"涨跌家数：上涨 {_num(advancing)} 家，下跌 {_num(declining)} 家，整体{tone}。"
            )
            lines.append(
                f"涨停 {_num(breadth.get('limit_up'))} 家，跌停 {_num(breadth.get('limit_down'))} 家，"
                f"平盘 {_num(breadth.get('flat'))} 家，停牌 {_num(breadth.get('suspended'))} 家。"
            )
            if breadth.get("activity") is not None:
                lines.append(f"市场活跃度：{_num(breadth.get('activity'))}%。")
        if benchmark:
            lines.append(
                f"参照 {benchmark.get('name', '上证指数')}："
                f"{_num(benchmark.get('close'))}（{_pct(benchmark.get('pct_chg'))}）。"
            )
        return "\n".join(lines)

    @staticmethod
    def _render_capital_flow(data: dict[str, Any]) -> str:
        channels = data.get("channels") or []
        as_of = str(data.get("as_of") or "").strip()
        if not channels:
            return ""
        lines = ["### 北向资金" + (f"（{as_of}）" if as_of else "")]
        for channel in channels:
            if channel.get("disclosed") is False:
                amount = "未披露"
            else:
                amount = f"{_num(channel.get('net_buy_yi'))} 亿元"
            lines.append(
                f"- {channel.get('board')}：当日成交净买额 {amount}"
                f"（成分上涨 {_num(channel.get('advancing'))} 家，"
                f"下跌 {_num(channel.get('declining'))} 家）"
            )
        total = data.get("net_buy_yi_total")
        if total is not None:
            lines.append(f"北向合计净买额：{_num(total)} 亿元。")
        note = str(data.get("note") or "").strip()
        if note:
            lines.append(f"数据说明：{note}")
        return "\n".join(lines)


__all__ = ["MarketInsightAgent"]
