"""市场洞察采集工具：返回并写入结构化 JSON，不渲染中文模板。"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from finance_agent.orchestration.experts.base import sink_of
from finance_agent.domains.market.expert.collectors import (
    get_capital_flow_data,
    get_market_overview_data,
    get_market_sentiment_data,
    get_policy_events_data,
)

MODE_COLLECTORS: Dict[str, Callable[[], Dict[str, Any]]] = {
    "market_overview": get_market_overview_data,
    "market_sentiment": get_market_sentiment_data,
    "capital_flow": get_capital_flow_data,
    "policy_impact": get_policy_events_data,
}

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


def unavailable_for(mode: str) -> str:
    return UNAVAILABLE_BY_MODE.get(mode, UNAVAILABLE_DEFAULT)


def merge_market_payloads(existing: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """把新模式结果并入 ``market_insight``。

    单模式保持既有形状（``{mode, status, ...data}``）。多模式时收拢为
    ``{mode: "multi", status, items: [...]}``，首个模式的字段仍平铺在顶层，
    以兼容前端既有的单模式渲染路径。
    """
    if not isinstance(existing, dict) or not existing:
        return dict(incoming)
    if existing.get("mode") == incoming.get("mode"):
        return dict(incoming)
    items = list(existing.get("items") or [existing])
    items.append(dict(incoming))
    statuses = {str(item.get("status") or "success") for item in items}
    status = "success" if statuses == {"success"} else "partial"
    merged = dict(items[0])
    merged.update({"mode": "multi", "status": status, "items": items})
    return merged


def _payload_present(mode: str, data: dict[str, Any]) -> bool:
    if mode == "market_overview":
        return bool(data.get("indices") or data.get("breadth"))
    if mode == "market_sentiment":
        return bool(data.get("breadth") or data.get("benchmark"))
    if mode == "capital_flow":
        return bool(data.get("margin") or data.get("northbound_holdings"))
    if mode == "policy_impact":
        limitations = list(data.get("limitations") or [])
        if "policy_news" in limitations:
            return False
        return True
    return False


def _run_mode(sink: Any, mode: str) -> dict[str, Any]:
    collect = MODE_COLLECTORS.get(mode)
    if collect is None:
        sink.limit(f"unsupported_mode:{mode}")
        return {"error": f"暂不支持的市场洞察模式：{mode}"}
    try:
        data = collect()
    except Exception:  # noqa: BLE001
        sink.limit(f"{mode}_failed")
        return {"error": unavailable_for(mode)}

    limitations = list(data.get("limitations") or [])
    if not _payload_present(mode, data):
        for code in limitations:
            sink.limit(code)
        sink.limit("no_data")
        return {"error": unavailable_for(mode)}

    for code in limitations:
        sink.limit(code)

    status = "partial" if limitations else "success"
    payload = {"mode": mode, "status": status, **data}
    existing = sink.structured.get("market_insight")
    sink.record(mode, payload={
        "market_insight": merge_market_payloads(existing, payload),
    })
    return payload


@tool
def get_market_overview(config: RunnableConfig) -> str:
    """获取大盘概览：主要指数点位与涨跌幅、成交额、市场涨跌家数。"""
    sink = sink_of(config)
    if sink is None:
        return json.dumps({"error": "no_sink"}, ensure_ascii=False)
    return json.dumps(_run_mode(sink, "market_overview"), ensure_ascii=False, default=str)


@tool
def get_market_sentiment(config: RunnableConfig) -> str:
    """获取市场情绪：涨跌家数、涨停跌停家数、市场活跃度与参照指数。"""
    sink = sink_of(config)
    if sink is None:
        return json.dumps({"error": "no_sink"}, ensure_ascii=False)
    return json.dumps(_run_mode(sink, "market_sentiment"), ensure_ascii=False, default=str)


@tool
def get_capital_flow(config: RunnableConfig) -> str:
    """获取资金面：融资融券余额及其日变化、北向持股市值（季度披露）。"""
    sink = sink_of(config)
    if sink is None:
        return json.dumps({"error": "no_sink"}, ensure_ascii=False)
    return json.dumps(_run_mode(sink, "capital_flow"), ensure_ascii=False, default=str)


@tool
def get_policy_impact(config: RunnableConfig) -> str:
    """获取近期政策事件清单（结构化 JSON，不含现成解读文案）。"""
    sink = sink_of(config)
    if sink is None:
        return json.dumps({"error": "no_sink"}, ensure_ascii=False)
    return json.dumps(_run_mode(sink, "policy_impact"), ensure_ascii=False, default=str)


__all__ = [
    "MODE_COLLECTORS",
    "get_capital_flow",
    "get_market_overview",
    "get_market_sentiment",
    "get_policy_impact",
    "merge_market_payloads",
    "unavailable_for",
]
