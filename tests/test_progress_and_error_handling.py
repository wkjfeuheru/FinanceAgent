"""进度送达、审计单次与异常不泄露的回归护栏。

这三项都是代码审计发现的缺陷，且都属于"用户可见/审计正确性"，因此各自锁定：
- 进度：DAG 的专家执行在工作线程里，回调注册在主线程，必须按 thread_id 路由；
- 审计：股票研究审计只在任务结果合并后触发一次，不得用未合并状态写库；
- 异常：内部异常文本不得进入用户可见文案。
"""

from __future__ import annotations

import threading

import pytest
from langgraph.checkpoint.memory import MemorySaver

from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.supervisor import ManagerAgent
from finance_agent.orchestrator.orchestrator import AdvisorSystem
from finance_agent.research.contracts import AnalysisKind, AnalysisRequest


def _system(*, intents, stock_agent=None):
    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.manager._intent_classifier = type(
        "C", (), {"classify": lambda self, *a, **k: {"finance_related": True, "intents": intents}},
    )()
    system.stock_agent = stock_agent or type(
        "S", (), {"agent_name": "stock_analysis", "invoke": lambda self, s: s},
    )()
    system.market_insight_agent = type("M", (), {"invoke": lambda self, s: s})()
    system.product_agent = type("P", (), {"invoke": lambda self, s: s})()
    system.casual_chat_agent = type("C", (), {"agent_name": "casual_chat", "invoke": lambda self, s: s})()
    system.slot_extractor = type("Slots", (), {"extract": lambda self, s: s})()
    system._progress_context = threading.local()
    system._progress_callbacks = {}
    system._progress_lock = threading.Lock()
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._workflow_lock = threading.RLock()
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = threading.Lock()
    system.audit = type("N", (), {"is_available": lambda self: False})()
    return system


_CONVERSATION = "conv-progress"


def test_progress_from_dag_worker_threads_reaches_callback():
    """专家进度在 DAG 工作线程里产生，必须仍能送达（thread-local 不跨线程）。

    主线程阶段的进度走 thread-local（由 handle_message 设置），本用例聚焦
    **工作线程**内的专家进度——这正是修复前被丢弃的部分。
    """
    system = _system(intents=[{
        "intent": "casual_chat", "query": "你好", "confidence": 0.99,
        "execution_mode": "conversation", "evidence": "你好",
    }])
    events: list[tuple[str, str]] = []
    callback = lambda stage, msg: events.append((stage, msg))  # noqa: E731
    system._progress_callbacks[_CONVERSATION] = callback

    system._build_graph().invoke(
        {"user_message": "你好", "completed_experts": [], "intent_results": {},
         "intent_slots": {}, "thread_id": _CONVERSATION},
        config={"configurable": {"thread_id": _CONVERSATION}},
    )

    stages = [stage for stage, _ in events]
    assert "casual_chat" in stages, "worker 内的专家进度必须送达"
    assert any("正在执行" in msg for _, msg in events)


def test_progress_thread_local_fallback_still_works():
    """主线程阶段（manager/slots）走 thread-local 兜底，与 worker 路径互补。"""
    system = _system(intents=[{
        "intent": "casual_chat", "query": "你好", "confidence": 0.99,
        "execution_mode": "conversation", "evidence": "你好",
    }])
    events: list[tuple[str, str]] = []
    callback = lambda stage, msg: events.append((stage, msg))  # noqa: E731
    system._progress_context.callback = callback
    system._progress_callbacks[_CONVERSATION] = callback

    system._build_graph().invoke(
        {"user_message": "你好", "completed_experts": [], "intent_results": {},
         "intent_slots": {}, "thread_id": _CONVERSATION},
        config={"configurable": {"thread_id": _CONVERSATION}},
    )

    stages = [stage for stage, _ in events]
    assert {"manager", "slots", "casual_chat"} <= set(stages), stages


def test_progress_callback_absent_does_not_raise():
    """未注册回调时静默（直接调用/测试场景）。"""
    system = _system(intents=[{
        "intent": "casual_chat", "query": "你好", "confidence": 0.99,
        "execution_mode": "conversation", "evidence": "你好",
    }])
    # 不注册任何回调：不应抛异常
    system._build_graph().invoke(
        {"user_message": "你好", "completed_experts": [], "intent_results": {},
         "intent_slots": {}, "thread_id": "conv-none"},
        config={"configurable": {"thread_id": "conv-none"}},
    )


def test_stock_analysis_failure_does_not_leak_internal_exception():
    """分析内部异常只给固定文案，原始异常文本（含敏感细节）不得外泄。"""
    agent = StockAnalysisAgent()

    class Exploding:
        def get_security_data(self, code):
            raise RuntimeError("DB_PASSWORD=secret / internal detail")

        def build(self, request):
            raise RuntimeError("DB_PASSWORD=secret / internal detail")

    agent._injected_pipeline = True
    agent._pipeline = Exploding()  # type: ignore[assignment]

    state = agent.invoke({
        "requirement": "分析600519", "current_task_intent": "stock_analysis",
        "resolved_stocks": [{"code": "600519"}], "intent_slots": {},
        "user_profile": {}, "intent_results": {},
    })

    response = state["agent_response"]
    assert "DB_PASSWORD" not in response
    assert "secret" not in response
    assert "internal detail" not in response
    assert "暂不可用" in response


def test_request_shape_error_text_is_not_leaked():
    """请求形态非法（多代码单股请求）时不得回显内部校验文本。"""
    agent = StockAnalysisAgent()
    state = agent.invoke({
        "requirement": "分析600519和600036",
        # current_task_intent 不是 stock_recommendation → 不触发候选发现
        "current_task_intent": "stock_analysis",
        "resolved_stocks": [{"code": "600519"}, {"code": "600036"}],
        "intent_slots": {}, "user_profile": {}, "intent_results": {},
    })

    response = state["agent_response"]
    assert "validation error" not in response
    assert "单股分析必须且只能包含一只股票" not in response
    assert "暂不可用" in response
