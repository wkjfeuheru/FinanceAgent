"""逐标的 Send 扇出：并行取数、逐只结论、依赖与最小 reducer 合并。"""

from __future__ import annotations

import threading

from langgraph.checkpoint.memory import MemorySaver

from finance_agent.agents.supervisor import ManagerAgent
from finance_agent.orchestrator.orchestrator import AdvisorSystem
from finance_agent.orchestrator.state import dedupe_concat, merge_dict


def _make_system(*, stock_agent, classifier_intents, monkeypatch, fetch):
    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.manager._intent_classifier = type(
        "C", (), {"classify": lambda self, *a, **k: {
            "finance_related": True, "intents": classifier_intents,
        }},
    )()
    system.stock_agent = stock_agent
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
    monkeypatch.setattr(
        "finance_agent.orchestrator.orchestrator.fetch_stock_data", fetch,
    )
    return system


def _stock_agent(run_request, *, seen):
    class FakeStock:
        agent_name = "stock_analysis"

        def plan(self, state):
            return {"kind": "fanout", "request": run_request}

        def run_resolved(self, state, request):
            seen.append(list(request.stock_codes))
            codes = request.stock_codes
            state["intent_results"] = {
                "stock_recommendation": {"status": "success", "content": "推荐完成"},
            }
            state["agent_response"] = "推荐完成"
            state["stock_analysis"] = {code: {"code": code} for code in codes}
            state["analysis_results"] = [
                {"request": {"stock_codes": [code]}, "action": "关注"} for code in codes
            ]
            return state

        def _failed(self, state, error):
            state["agent_response"] = error.get("content", "")
            state["intent_results"] = {
                "stock_recommendation": {"status": "degraded", "content": error.get("content", "")},
            }
            return state

        def invoke(self, state):
            return state

    return FakeStock()


def test_multi_candidate_fanout_yields_per_security_conclusions(monkeypatch):
    """3 只候选并行取数，聚合后一次分析，逐只结论且不丢 task_results。"""
    seen: list[list[str]] = []
    run_request = {
        "kind": "comparison", "stock_codes": ["600519", "600036", "000858"],
        "indicators": [], "profile_complete": False, "horizon": "medium",
    }
    fetched: list[str] = []

    def fetch(codes):
        fetched.extend(codes)
        return {code: {"basic_info": {"code": code}} for code in codes}

    system = _make_system(
        stock_agent=_stock_agent(run_request, seen=seen),
        classifier_intents=[{
            "intent": "stock_recommendation", "query": "推荐几只消费龙头",
            "confidence": 0.99, "execution_mode": "candidate_search", "evidence": "推荐几只消费龙头",
        }],
        monkeypatch=monkeypatch, fetch=fetch,
    )
    graph = system._build_graph()
    result = graph.invoke(
        {"user_message": "推荐几只消费龙头", "completed_experts": [], "intent_results": {}},
        config={"configurable": {"thread_id": "fanout-candidates"}},
    )

    assert sorted(fetched) == ["000858", "600036", "600519"]
    assert seen == [["600519", "600036", "000858"]]
    assert set(result["stock_data"]) == {"600519", "600036", "000858"}
    assert set(result["task_results"]) == {"task-1"}
    assert result["run_status"].value == "completed"


def test_all_fetch_failures_degrade_without_crashing(monkeypatch):
    """全部取数失败时降级为可读文案，不抛异常、不产出结论。"""
    seen: list[list[str]] = []
    run_request = {
        "kind": "comparison", "stock_codes": ["600519", "600036"],
        "indicators": [], "profile_complete": False, "horizon": "medium",
    }

    def fetch(_codes):
        raise RuntimeError("provider down")

    system = _make_system(
        stock_agent=_stock_agent(run_request, seen=seen),
        classifier_intents=[{
            "intent": "stock_recommendation", "query": "推荐两只",
            "confidence": 0.99, "execution_mode": "candidate_search", "evidence": "推荐两只",
        }],
        monkeypatch=monkeypatch, fetch=fetch,
    )
    graph = system._build_graph()
    result = graph.invoke(
        {"user_message": "推荐两只", "completed_experts": [], "intent_results": {}},
        config={"configurable": {"thread_id": "fanout-fail"}},
    )

    assert seen == []
    assert "数据获取失败" in result["agent_response"]
    assert not result.get("stock_analysis")


def test_reducers_merge_dicts_and_dedupe_lists():
    """最小 reducer：映射按 key 合并，列表按身份去重。"""
    assert merge_dict({"a": {"x": 1}}, {"a": {"y": 2}, "b": 3}) == {"a": {"x": 1, "y": 2}, "b": 3}
    assert dedupe_concat([{"fact_id": "f1"}, {"fact_id": "f2"}], [{"fact_id": "f1"}]) == [
        {"fact_id": "f1"}, {"fact_id": "f2"},
    ]
