"""市场洞察专家（market_insight）：只回答市场整体层面的问题。

**边界（硬约束）：** 本专家只负责市场级问题（大盘/指数/市场情绪/资金面/政策事件），
绝不输出个股结论、个股评级、推荐、仓位或资产配置。任何涉及具体标的的请求
都应留在 ``stock_analysis`` 处理。

**模式：**

- ``market_overview``：主要指数最新价、涨跌幅、成交额、近 5/20 日区间涨跌 + 市场宽度；
- ``market_sentiment``：涨跌家数/涨跌停/活跃度 + 上证指数涨跌作为参照；
- ``capital_flow``：两市融资融券日频（含日环比）+ 北向持股市值（季度披露）；
- ``policy_impact``：近 N 天政策类新闻的确定性筛选 + 定性影响解读。

**数据边界：** 各模式取数均 best-effort（见 ``tools/marketdata.py``），单项失败只在
"限制与提示"中列明，不伪造数值；整体无数据时给出按模式区分的诚实降级说明。
前三类模式渲染为确定性文本，不调用 LLM 生成数值；``policy_impact`` 的事件筛选
是确定性的，影响解读由 LLM 基于筛选出的事件生成（失败时回退纯事件清单，不伪造）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from finance_agent.agents.base import ProceduralAgent
from finance_agent.middleware import check_sensitive_words
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

# 各模式整体不可用时的降级说明（按模式区分，避免资金面/政策模式误报"指数与宽度"）。
_UNAVAILABLE_BY_MODE = {
    "market_overview": (
        "市场概览数据暂不可用：指数行情与市场宽度数据源当前均未取到数据。"
        "您可以直接指定具体股票，我将为您做基本面与技术面分析。"
    ),
    "market_sentiment": (
        "市场情绪数据暂不可用：市场宽度与参照指数数据源当前均未取到数据。"
        "您可以直接指定具体股票，我将为您做基本面与技术面分析。"
    ),
    "capital_flow": (
        "资金面数据暂不可用：融资融券与北向持股市值数据源当前均未取到数据。"
        "您可以直接指定具体股票，我将为您做基本面与技术面分析。"
    ),
    "policy_impact": (
        "政策事件数据暂不可用：财经快讯数据源当前未取到数据。"
        "您可以直接指定具体股票，我将为您做基本面与技术面分析。"
    ),
}
_UNAVAILABLE_DEFAULT = (
    "市场洞察数据暂不可用：相关数据源当前均未取到数据。"
    "您可以直接指定具体股票，我将为您做基本面与技术面分析。"
)

# 政策事件定性解读的提示词：只基于给定事件，不引入外部知识、不涉个股与仓位。
_POLICY_PROMPT = """你是金融市场观察者，只做**市场层面**的定性影响解读，不涉个股、评级、推荐或仓位。

## 硬约束
1. 只依据下方提供的事件列表解读，**不得引入列表之外的事件或数据**，不得编造事件。
2. **不得输出任何个股名称、代码、评级、推荐、买卖或仓位建议**；只做市场/行业层面的方向性判断。
3. 区分"已证实的事件"与"市场预期/传闻"，不要把预期当作既成事实。
4. 每一条方向性判断都要绑定具体事件依据；无依据时不臆测。
5. 必须包含不确定性说明（政策落地节奏、传导时滞、市场预期差等）。

## 事件列表（近 {window_days} 天，已按关键词确定性筛选，时间倒序）
{events}
截止日期：{as_of}

## 输出要求
用简体中文，控制在 4-6 句，分点列出对各政策领域（货币/财政/监管/产业/地产/对外开放）
可能的市场影响方向，最后一句给出总体不确定性提示。不要复述事件全文。"""


def _collector_for(mode: str):
    """按模式解析取数函数；在调用时从模块命名空间查找，便于测试注入。"""
    name = _MODE_COLLECTOR_NAMES.get(mode)
    return globals().get(name) if name else None


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


def _yi(value: Any) -> str:
    """把人民币元换算为亿元并格式化；不可解析返回占位。"""
    try:
        return f"{float(value) / 1e8:,.2f}"
    except (TypeError, ValueError):
        return "-"


class PolicyImpactInterpreter:
    """基于筛选出的政策事件生成定性影响解读；异常由上层回退纯清单。"""

    def __init__(self, model: Any = None) -> None:
        self._model = model
        self._chain = None

    @property
    def model(self) -> Any:
        if self._model is None:
            from finance_agent.config import get_model_for_agent

            self._model = get_model_for_agent("market_insight")
        return self._model

    @property
    def chain(self) -> Any:
        if self._chain is None:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate

            prompt = ChatPromptTemplate.from_messages([("system", _POLICY_PROMPT)])
            self._chain = prompt | self.model | StrOutputParser()
        return self._chain

    def interpret(self, events: List[Dict[str, Any]], as_of: str, window_days: int) -> str:
        """调用 LLM 生成解读；空输出或命中敏感词视为失败，由调用方回退。"""
        text = str(self.chain.invoke({
            "events": json.dumps(events, ensure_ascii=False),
            "as_of": as_of or "未知",
            "window_days": window_days,
        }) or "").strip()
        if not text:
            raise ValueError("政策解读返回空内容")
        hits = check_sensitive_words(text)
        if hits:
            raise ValueError(f"政策解读命中敏感词: {hits}")
        return text


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
        content = self._render(mode, data, limitations)
        if not content:
            return self._write(state, mode, self._unavailable_for(mode), "degraded")

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
        return _UNAVAILABLE_BY_MODE.get(mode, _UNAVAILABLE_DEFAULT)

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

    def _render(self, mode: str, data: dict[str, Any], limitations: List[str]) -> str:
        """按模式渲染；无有效内容时返回空串。"""
        if mode == "market_overview":
            return self._render_overview(data)
        if mode == "market_sentiment":
            return self._render_sentiment(data)
        if mode == "capital_flow":
            return self._render_capital_flow(data)
        if mode == "policy_impact":
            return self._render_policy_impact(data, limitations)
        return ""

    @staticmethod
    def _append_note(lines: List[str], data: dict[str, Any]) -> None:
        """三个快照模式统一在末尾渲染数据说明（此前仅资金面渲染）。"""
        note = str(data.get("note") or "").strip()
        if note:
            lines.append(f"数据说明：{note}")

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
                base = (
                    f"- {item.get('name', item.get('symbol'))}："
                    f"{_num(item.get('close'))}（{_pct(item.get('pct_chg'))}）"
                )
                amount = item.get("amount")
                if amount is not None:
                    base += f"，成交额 {_yi(amount)} 亿元"
                ranges = []
                if item.get("pct_5d") is not None:
                    ranges.append(f"近5日 {_pct(item.get('pct_5d'))}")
                if item.get("pct_20d") is not None:
                    ranges.append(f"近20日 {_pct(item.get('pct_20d'))}")
                if ranges:
                    base += "（" + "，".join(ranges) + "）"
                lines.append(base)
        if breadth:
            lines.append(
                f"市场宽度：上涨 {_num(breadth.get('advancing'))} 家，"
                f"下跌 {_num(breadth.get('declining'))} 家，"
                f"涨停 {_num(breadth.get('limit_up'))} 家，"
                f"跌停 {_num(breadth.get('limit_down'))} 家。"
            )
        MarketInsightAgent._append_note(lines, data)
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
            line = (
                f"参照 {benchmark.get('name', '上证指数')}："
                f"{_num(benchmark.get('close'))}（{_pct(benchmark.get('pct_chg'))}）"
            )
            if benchmark.get("pct_5d") is not None:
                line += f"，近5日 {_pct(benchmark.get('pct_5d'))}"
            line += "。"
            lines.append(line)
        MarketInsightAgent._append_note(lines, data)
        return "\n".join(lines)

    @staticmethod
    def _render_capital_flow(data: dict[str, Any]) -> str:
        margin = data.get("margin") or {}
        holdings = data.get("northbound_holdings") or {}
        as_of = str(data.get("as_of") or "").strip()
        if not margin and not holdings:
            return ""
        lines = ["### 资金面" + (f"（{as_of}）" if as_of else "")]
        if margin:
            line = (
                f"融资融券（两市合计，{margin.get('as_of', '-')}）："
                f"融资余额 {_num(margin.get('financing_balance_yi'))} 亿元，"
                f"融券余额 {_num(margin.get('securities_lending_balance_yi'))} 亿元，"
                f"两融余额 {_num(margin.get('total_balance_yi'))} 亿元，"
                f"当日融资买入额 {_num(margin.get('financing_buy_yi'))} 亿元"
            )
            chg = margin.get("financing_balance_chg_yi")
            if chg is not None:
                line += f"，融资余额较上日 {float(chg):+,.2f} 亿元"
            line += "。"
            lines.append(line)
        if holdings.get("holdings_value_yuan") is not None:
            lines.append(
                f"北向持股市值（{holdings.get('as_of', '季度')}，季度披露）："
                f"{_yi(holdings.get('holdings_value_yuan'))} 亿元。"
            )
        MarketInsightAgent._append_note(lines, data)
        return "\n".join(lines)

    def _render_policy_impact(
        self, data: dict[str, Any], limitations: List[str],
    ) -> str:
        """渲染政策事件：确定性事件清单 + LLM 定性解读（失败回退清单）。"""
        events = data.get("events") or []
        as_of = str(data.get("as_of") or "").strip()
        window_days = int(data.get("window_days", 3) or 3)
        if not events:
            # 取数源整体失败：返回空串，交由 invoke 用按模式的降级文案，
            # 不能声称"未筛选出事件"（那是取数成功才成立的结论）。
            if "policy_news" in limitations:
                return ""
            # 取数成功但无命中：诚实空态，不硬凑。
            return (
                f"### 政策事件影响\n近 {window_days} 天财经快讯中未筛选出政策类事件，"
                "暂无确定性影响解读。"
            )
        lines = ["### 政策事件影响" + (f"（{as_of}）" if as_of else "")]
        summary = data.get("categories_summary") or {}
        if summary:
            lines.append(
                "筛选出政策事件 " + "、".join(
                    f"{category} {count} 条" for category, count in summary.items()
                ) + "。"
            )
        lines.append("近期政策事件：")
        for item in events[:10]:
            stamp = str(item.get("datetime") or "").strip()
            prefix = f"{stamp} " if stamp else ""
            lines.append(f"- {prefix}[{item.get('category', '')}] {item.get('title', '')}")

        interpretation = ""
        try:
            interpretation = self._interpreter.interpret(events, as_of, window_days)
        except Exception:  # noqa: BLE001 - LLM 不可用时回退纯清单，不伪造
            if "policy_interpretation" not in limitations:
                limitations.append("policy_interpretation")
        if interpretation:
            lines.append("")
            lines.append("影响解读：")
            lines.append(interpretation)
        else:
            lines.append("")
            lines.append("影响解读暂不可用，以上为确定性筛选出的政策事件清单。")
        MarketInsightAgent._append_note(lines, data)
        return "\n".join(lines)


__all__ = ["MarketInsightAgent", "PolicyImpactInterpreter"]
