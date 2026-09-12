"""市场洞察意图：边界、诚实降级与审计归属。

``market_insight`` 只回答市场级问题，绝不输出个股结论、推荐或配置。
当前无指数/市场宽度数据源，因此 ``market_overview`` 必须是诚实的降级说明。
"""

from __future__ import annotations

import threading

from langgraph.checkpoint.memory import MemorySaver

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


def test_market_insight_agent_degrades_honestly_and_touches_no_stock_output():
    agent = MarketInsightAgent()
    state = agent.invoke({
        "requirement": "今天大盘怎么样", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_overview"},
        "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "degraded"
    assert "尚未接入" in result["content"]
    assert state["market_insight"]["mode"] == "market_overview"
    # 硬边界：不得产出任何个股结论字段。
    assert "stock_analysis" not in state
    assert "analysis_results" not in state


def test_market_insight_agent_rejects_unsupported_mode():
    agent = MarketInsightAgent()
    state = agent.invoke({
        "requirement": "北向资金", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "capital_flow"}, "intent_results": {},
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


def test_market_overview_end_to_end_routes_to_market_insight(monkeypatch):
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

    assert "尚未接入" in result["agent_response"]
    assert "validation error" not in result["agent_response"]
    assert not result.get("stock_analysis")
    assert "market_insight" in result["task_results"]["task-1"].expert_name
