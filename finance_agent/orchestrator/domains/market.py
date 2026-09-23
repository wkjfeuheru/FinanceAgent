"""市场洞察的确定性渲染与领域子图（设计 §6.4）。

市场节点只调用既有四个采集器与 ``PolicyImpactInterpreter``（仅用于受限的政策
解释）。渲染为确定性文本，不调用 LLM 生成数值。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping

from finance_agent.middleware import check_sensitive_words
from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext
from finance_agent.orchestrator.domains.base import (
    DomainOperation,
    OperationResult,
    build_domain_graph,
    context_text,
    keyword_mode,
)
from finance_agent.orchestrator.tools.marketdata import (
    get_capital_flow_data,
    get_market_overview_data,
    get_market_sentiment_data,
    get_policy_events_data,
)

# 模式 → 采集器函数对象**直接绑定**：重命名采集器或写错模式键都会在导入期暴露，
# 不再经 ``globals()`` 按函数名字符串间接解析（IDE/类型检查无法追踪那种写法）。
MODE_COLLECTORS: Dict[str, Callable[[], Dict[str, Any]]] = {
    "market_overview": get_market_overview_data,
    "market_sentiment": get_market_sentiment_data,
    "capital_flow": get_capital_flow_data,
    "policy_impact": get_policy_events_data,
}

# 各模式整体不可用时的降级说明（按模式区分，避免资金面/政策模式误报“指数与宽度”）。
UNAVAILABLE_BY_MODE = {
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
UNAVAILABLE_DEFAULT = (
    "市场洞察数据暂不可用：相关数据源当前均未取到数据。"
    "您可以直接指定具体股票，我将为您做基本面与技术面分析。"
)

# 政策事件定性解读的提示词：只基于给定事件，不引入外部知识、不涉个股与仓位。
POLICY_PROMPT = """你是金融市场观察者，只做**市场层面**的定性影响解读，不涉个股、评级、推荐或仓位。

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

_MARKET_MODE_KEYWORDS = {
    "market_sentiment": ("情绪", "sentiment", "涨跌家数", "活跃"),
    "capital_flow": ("资金", "融资", "融券", "北向", "capital", "margin"),
    "policy_impact": ("政策", "policy", "事件", "监管", "财政", "货币"),
}


def collector_for(
    mode: str,
    registry: Mapping[str, Callable[[], dict[str, Any]]] | None = None,
) -> Callable[[], dict[str, Any]] | None:
    """按模式解析取数函数；测试可传 ``registry`` 显式覆盖默认绑定表。"""
    return (registry if registry is not None else MODE_COLLECTORS).get(mode)


def pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:+.2f}%"


def num(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def yi(value: Any) -> str:
    try:
        return f"{float(value) / 1e8:,.2f}"
    except (TypeError, ValueError):
        return "-"


def append_note(lines: List[str], data: dict[str, Any]) -> None:
    note = str(data.get("note") or "").strip()
    if note:
        lines.append(f"数据说明：{note}")


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

            prompt = ChatPromptTemplate.from_messages([("system", POLICY_PROMPT)])
            self._chain = prompt | self.model | StrOutputParser()
        return self._chain

    def interpret(self, events: List[Dict[str, Any]], as_of: str, window_days: int) -> str:
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


def render_overview(data: dict[str, Any]) -> str:
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
                f"{num(item.get('close'))}（{pct(item.get('pct_chg'))}）"
            )
            amount = item.get("amount")
            if amount is not None:
                base += f"，成交额 {yi(amount)} 亿元"
            ranges = []
            if item.get("pct_5d") is not None:
                ranges.append(f"近5日 {pct(item.get('pct_5d'))}")
            if item.get("pct_20d") is not None:
                ranges.append(f"近20日 {pct(item.get('pct_20d'))}")
            if ranges:
                base += "（" + "，".join(ranges) + "）"
            lines.append(base)
    if breadth:
        lines.append(
            f"市场宽度：上涨 {num(breadth.get('advancing'))} 家，"
            f"下跌 {num(breadth.get('declining'))} 家，"
            f"涨停 {num(breadth.get('limit_up'))} 家，"
            f"跌停 {num(breadth.get('limit_down'))} 家。"
        )
    append_note(lines, data)
    return "\n".join(lines)


def render_sentiment(data: dict[str, Any]) -> str:
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
            f"涨跌家数：上涨 {num(advancing)} 家，下跌 {num(declining)} 家，整体{tone}。"
        )
        lines.append(
            f"涨停 {num(breadth.get('limit_up'))} 家，跌停 {num(breadth.get('limit_down'))} 家，"
            f"平盘 {num(breadth.get('flat'))} 家，停牌 {num(breadth.get('suspended'))} 家。"
        )
        if breadth.get("activity") is not None:
            lines.append(f"市场活跃度：{num(breadth.get('activity'))}%。")
    if benchmark:
        line = (
            f"参照 {benchmark.get('name', '上证指数')}："
            f"{num(benchmark.get('close'))}（{pct(benchmark.get('pct_chg'))}）"
        )
        if benchmark.get("pct_5d") is not None:
            line += f"，近5日 {pct(benchmark.get('pct_5d'))}"
        line += "。"
        lines.append(line)
    append_note(lines, data)
    return "\n".join(lines)


def render_capital_flow(data: dict[str, Any]) -> str:
    margin = data.get("margin") or {}
    holdings = data.get("northbound_holdings") or {}
    as_of = str(data.get("as_of") or "").strip()
    if not margin and not holdings:
        return ""
    lines = ["### 资金面" + (f"（{as_of}）" if as_of else "")]
    if margin:
        line = (
            f"融资融券（两市合计，{margin.get('as_of', '-')}）："
            f"融资余额 {num(margin.get('financing_balance_yi'))} 亿元，"
            f"融券余额 {num(margin.get('securities_lending_balance_yi'))} 亿元，"
            f"两融余额 {num(margin.get('total_balance_yi'))} 亿元，"
            f"当日融资买入额 {num(margin.get('financing_buy_yi'))} 亿元"
        )
        chg = margin.get("financing_balance_chg_yi")
        if chg is not None:
            line += f"，融资余额较上日 {float(chg):+,.2f} 亿元"
        line += "。"
        lines.append(line)
    if holdings.get("holdings_value_yuan") is not None:
        lines.append(
            f"北向持股市值（{holdings.get('as_of', '季度')}，季度披露）："
            f"{yi(holdings.get('holdings_value_yuan'))} 亿元。"
        )
    append_note(lines, data)
    return "\n".join(lines)


def render_policy_impact(
    data: dict[str, Any],
    limitations: List[str],
    interpreter: PolicyImpactInterpreter,
) -> str:
    """渲染政策事件：确定性事件清单 + LLM 定性解读（失败回退清单）。"""
    events = data.get("events") or []
    as_of = str(data.get("as_of") or "").strip()
    window_days = int(data.get("window_days", 3) or 3)
    if not events:
        if "policy_news" in limitations:
            return ""
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
        interpretation = interpreter.interpret(events, as_of, window_days)
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
    append_note(lines, data)
    return "\n".join(lines)


def render(mode: str, data: dict[str, Any], limitations: List[str], interpreter: PolicyImpactInterpreter) -> str:
    if mode == "market_overview":
        return render_overview(data)
    if mode == "market_sentiment":
        return render_sentiment(data)
    if mode == "capital_flow":
        return render_capital_flow(data)
    if mode == "policy_impact":
        return render_policy_impact(data, limitations, interpreter)
    return ""


def unavailable_for(mode: str) -> str:
    return UNAVAILABLE_BY_MODE.get(mode, UNAVAILABLE_DEFAULT)


def run_market_mode(mode: str, *, interpreter: PolicyImpactInterpreter, collector=None) -> OperationResult:
    """执行单个市场模式的确定性取数与渲染，返回统一结果。"""
    collect = collector or collector_for(mode)
    if collect is None:
        return OperationResult(
            structured_data={"mode": mode, "status": "degraded"},
            summary=f"暂不支持的市场洞察模式：{mode}。目前支持大盘概览、市场情绪、资金面与政策事件影响。",
            status="partial",
            limitations=[f"unsupported_mode:{mode}"],
        )

    data = collect()
    limitations = list(data.get("limitations", []) or [])
    content = render(mode, data, limitations, interpreter)
    if not content:
        return OperationResult(
            structured_data={"mode": mode, "status": "degraded"},
            summary=unavailable_for(mode),
            status="partial",
            limitations=limitations + ["no_data"],
        )

    if limitations:
        content += "\n\n限制与提示：" + "、".join(limitations) + "。"
    status = "partial" if limitations else "success"
    payload = {"mode": mode, "status": status, **data}
    return OperationResult(
        structured_data={"market_insight": payload},
        summary=content,
        status=status,
        limitations=limitations,
    )


def _resolve_market_mode(context: DomainTaskContext) -> str:
    return keyword_mode(context_text(context), _MARKET_MODE_KEYWORDS, "market_overview")


def default_market_operations(
    interpreter: PolicyImpactInterpreter | None = None,
) -> list[DomainOperation]:
    """四个市场采集器注册为白名单操作；操作名沿用采集器函数名（tool_trace 既有口径）。"""
    shared_interpreter = interpreter or PolicyImpactInterpreter()
    return [
        DomainOperation(
            name=MODE_COLLECTORS[mode].__name__,
            modes=frozenset({mode}),
            handler=(lambda mode: lambda ctx: run_market_mode(mode, interpreter=shared_interpreter))(mode),
        )
        for mode in MODE_COLLECTORS
    ]


def build_market_domain_graph(operations=None, *, interpreter: PolicyImpactInterpreter | None = None):
    """编译市场领域子图；白名单来自 operation 注册表（唯一事实源）。

    ``operations=[]`` 是合法输入（白名单为空，任何模式都安全失败），
    因此必须用 ``is None`` 判缺省，不能 truthy 判断。
    """
    from finance_agent.orchestrator.runtime.operations import default_operation_registry

    registry = default_operation_registry()
    return build_domain_graph(
        BusinessDomain.MARKET_INSIGHT,
        default_market_operations(interpreter) if operations is None else operations,
        default_mode=registry.spec(BusinessDomain.MARKET_INSIGHT).default_mode,
        mode_resolver=registry.spec(BusinessDomain.MARKET_INSIGHT).mode_resolver,
    )


__all__ = [
    "PolicyImpactInterpreter",
    "build_market_domain_graph",
    "collector_for",
    "default_market_operations",
    "render",
    "render_capital_flow",
    "render_overview",
    "render_policy_impact",
    "render_sentiment",
    "run_market_mode",
    "unavailable_for",
]
