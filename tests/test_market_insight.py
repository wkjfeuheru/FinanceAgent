"""市场洞察意图：边界、三模式实数渲染与降级。

``market_insight`` 只回答市场级问题，绝不输出个股结论、推荐或配置。
取数经 ``tools.marketdata`` 注入，测试不联网。
"""

from __future__ import annotations

import threading

import pytest
from langgraph.checkpoint.memory import MemorySaver

import finance_agent.agents.market_insight as market_insight_module
from finance_agent.agents.market_insight import MarketInsightAgent
from finance_agent.agents.supervisor import ManagerAgent
from finance_agent.contracts.adapters import normalize_dispatch_plan
from finance_agent.contracts.schema.enums import IntentKind
from finance_agent.orchestrator.orchestrator import AdvisorSystem


def test_market_insight_routes_to_its_own_expert():
    plan = normalize_dispatch_plan(
        [{"intent": "market_insight", "query": "今天大盘怎么样", "confidence": 0.99,
          "execution_mode": "market_overview", "evidence": "今天大盘怎么样"}],
        "今天大盘怎么样",
    )

    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.intent is IntentKind.MARKET_INSIGHT
    assert task.expert_name == "market_insight"


@pytest.fixture
def overview_data(monkeypatch):
    payload = {
        "as_of": "2026-09-11",
        "indices": [
            {"symbol": "sh000001", "name": "上证指数", "as_of": "2026-09-11",
             "close": 3888.11, "pct_chg": -1.18, "recent_closes": [3900.0, 3888.11]},
            {"symbol": "sh000300", "name": "沪深300", "as_of": "2026-09-11",
             "close": 4510.16, "pct_chg": -0.5, "recent_closes": [4530.0, 4510.16]},
        ],
        "breadth": {"advancing": 604, "declining": 4567, "limit_up": 40,
                    "limit_down": 21, "activity": 11.57, "as_of": "2026-09-11"},
        "limitations": [],
        "note": "",
    }
    monkeypatch.setattr(market_insight_module, "get_market_overview_data", lambda: payload)
    return payload


def test_overview_mode_renders_real_numbers(overview_data):
    state = MarketInsightAgent().invoke({
        "requirement": "今天大盘怎么样", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_overview"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "success"
    assert "上证指数" in result["content"]
    assert "3,888.11" in result["content"]
    assert "-1.18%" in result["content"]
    assert "上涨 604 家" in result["content"]
    assert state["market_insight"]["mode"] == "market_overview"
    # 硬边界：不得产出任何个股结论字段。
    assert "stock_analysis" not in state
    assert "analysis_results" not in state


def test_sentiment_mode_renders_breadth(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_market_sentiment_data", lambda: {
        "as_of": "2026-09-11",
        "breadth": {"advancing": 604, "declining": 4567, "limit_up": 40,
                    "limit_down": 21, "flat": 36, "suspended": 12, "activity": 11.57},
        "benchmark": {"name": "上证指数", "close": 3888.11, "pct_chg": -1.18},
        "limitations": [],
        "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "市场情绪如何", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_sentiment"}, "intent_results": {},
    })

    content = state["intent_results"]["market_insight"]["content"]
    assert "市场情绪" in content
    assert "偏弱" in content          # 下跌多于上涨
    assert "11.57%" in content
    assert state["market_insight"]["mode"] == "market_sentiment"


def test_capital_flow_mode_renders_channels_and_disclosure(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_northbound_data", lambda: {
        "as_of": "2026-09-11",
        "channels": [
            {"board": "沪股通", "direction": "northbound", "net_buy_yi": 5.2,
             "advancing": 203, "declining": 1425, "disclosed": True},
            {"board": "深股通", "direction": "northbound", "net_buy_yi": 12.5,
             "advancing": 231, "declining": 1633, "disclosed": True},
        ],
        "net_buy_yi_total": 17.7,
        "limitations": [],
        "note": "自2024-08起监管调整，北向实时净买额不再披露。",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "北向资金", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "capital_flow"}, "intent_results": {},
    })

    content = state["intent_results"]["market_insight"]["content"]
    assert "沪股通" in content and "5.20 亿元" in content
    assert "北向合计净买额：17.70 亿元" in content
    assert "不再披露" in content          # 数据边界必须披露
    assert state["market_insight"]["mode"] == "capital_flow"


def test_capital_flow_shows_undisclosed_instead_of_zero(monkeypatch):
    """未披露的通道不得渲染成 '0.00 亿元'，否则会被误读为零净买入。"""
    monkeypatch.setattr(market_insight_module, "get_northbound_data", lambda: {
        "as_of": "2026-09-11",
        "channels": [
            {"board": "沪股通", "direction": "northbound", "net_buy_yi": 0.0,
             "advancing": 203, "declining": 1425, "disclosed": False},
        ],
        "net_buy_yi_total": None,
        "limitations": [],
        "note": "自2024-08起监管调整，北向实时净买额不再披露。",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "北向资金", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "capital_flow"}, "intent_results": {},
    })

    content = state["intent_results"]["market_insight"]["content"]
    assert "未披露" in content
    assert "0.00 亿元" not in content


def test_partial_failures_are_disclosed_not_faked(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_market_overview_data", lambda: {
        "as_of": "2026-09-11",
        "indices": [{"symbol": "sh000001", "name": "上证指数", "close": 3888.11,
                     "pct_chg": -1.18}],
        "breadth": {},
        "limitations": ["market_breadth"],
        "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "今天大盘怎么样", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_overview"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "partial"
    assert "限制与提示" in result["content"]
    assert "market_breadth" in result["content"]


def test_all_data_missing_degrades_honestly(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_market_overview_data", lambda: {
        "as_of": "", "indices": [], "breadth": {}, "limitations": ["market_breadth"], "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "今天大盘怎么样", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_overview"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "degraded"
    assert "暂不可用" in result["content"]


def test_market_insight_agent_rejects_unknown_mode():
    state = MarketInsightAgent().invoke({
        "requirement": "外汇", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "fx_flow"}, "intent_results": {},
    })

    assert state["intent_results"]["market_insight"]["status"] == "degraded"
    assert "暂不支持" in state["intent_results"]["market_insight"]["content"]


def _make_system(monkeypatch, *, classifier_intents):
    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.manager._intent_classifier = type(
        "C", (), {"classify": lambda self, *a, **k: {
            "finance_related": True, "intents": classifier_intents,
        }},
    )()
    system.stock_agent = type("S", (), {"agent_name": "stock_analysis"})()
    system.market_insight_agent = MarketInsightAgent()
    system.allocation_agent = type("A", (), {"invoke": lambda self, s: s})()
    system.product_agent = type("P", (), {"invoke": lambda self, s: s})()
    system.casual_chat_agent = type("C", (), {"invoke": lambda self, s: s})()
    system.slot_extractor = type("Slots", (), {"extract": lambda self, s: s})()
    system._progress_context = type("Context", (), {})()
    system._progress_callbacks = {}
    system._progress_lock = threading.Lock()
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._workflow_lock = threading.RLock()
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = threading.Lock()
    system.audit = type("_NoopAudit", (), {"is_available": lambda self: False})()
    system._trace_agent = lambda *a, **k: None
    system._emit_progress = lambda *a, **k: None
    return system


def test_market_overview_end_to_end_routes_to_market_insight(monkeypatch, overview_data):
    """"今天大盘怎么样"走市场洞察，不触发股票取数，也不产出个股结论。"""
    system = _make_system(monkeypatch, classifier_intents=[{
        "intent": "market_insight", "query": "今天大盘怎么样", "confidence": 0.99,
        "execution_mode": "market_overview", "evidence": "今天大盘怎么样",
    }])
    graph = system._build_graph()
    result = graph.invoke(
        {"user_message": "今天大盘怎么样", "completed_experts": [], "intent_results": {}},
        config={"configurable": {"thread_id": "market-overview-e2e"}},
    )

    assert "上证指数" in result["agent_response"]
    assert "validation error" not in result["agent_response"]
    assert not result.get("stock_analysis")
    assert result["task_results"]["task-1"].expert_name == "market_insight"
