"""异常不泄露与进度送达的回归护栏（面向 V2 领域图与编排入口）。"""

from __future__ import annotations

import threading

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestrator.domains.stock import StockDeps, invoke_stock
from finance_agent.orchestrator.orchestrator import AdvisorSystem


def _stock_context(message: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:stock_research",
            domain=BusinessDomain.STOCK_RESEARCH,
            goal=message,
            instruction=message,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=message,
    )


def test_stock_analysis_failure_does_not_leak_internal_exception():
    """分析内部异常只给固定文案，原始异常文本（含敏感细节）不得外泄。"""
    class Exploding:
        def get_security_data(self, code):
            raise RuntimeError("DB_PASSWORD=secret / internal detail")

        def build(self, request):
            raise RuntimeError("DB_PASSWORD=secret / internal detail")

    deps = StockDeps(pipeline=Exploding(), injected_pipeline=True)
    state = invoke_stock(deps, {
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
    state = invoke_stock(StockDeps(), {
        "requirement": "分析600519和600036",
        "current_task_intent": "stock_analysis",
        "resolved_stocks": [{"code": "600519"}, {"code": "600036"}],
        "intent_slots": {}, "user_profile": {}, "intent_results": {},
    })

    response = state["agent_response"]
    assert "validation error" not in response
    assert "单股分析必须且只能包含一只股票" not in response
    assert "暂不可用" in response


def test_emit_progress_routes_by_conversation_id_from_worker_thread():
    """专家进度在工作线程产生，必须按 conversation_id 送达主线程注册的回调。"""
    system = object.__new__(AdvisorSystem)
    system._progress_lock = threading.Lock()
    system._progress_callbacks = {}
    system._progress_context = threading.local()

    events: list[tuple[str, str]] = []
    system._progress_callbacks["conv-1"] = lambda stage, msg: events.append((stage, msg))

    def worker():
        system._emit_progress("stock_analysis", "正在执行", "conv-1")

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert events == [("stock_analysis", "正在执行")]


def test_emit_progress_absent_callback_does_not_raise():
    system = object.__new__(AdvisorSystem)
    system._progress_lock = threading.Lock()
    system._progress_callbacks = {}
    system._progress_context = threading.local()

    system._emit_progress("manager", "无回调", "conv-none")
