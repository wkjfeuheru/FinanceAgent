"""端到端：复合请求经 Plan-and-Execute 再到合规出口，不依赖外部服务。"""

from __future__ import annotations

import threading

from finance_agent.orchestrator.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestrator.orchestrator import AdvisorSystem
from finance_agent.orchestrator.supervisor_graph import SupervisorDependencies, build_supervisor_graph


class _FakeClassifier:
    def __init__(self, intents):
        self._intents = intents

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [
                {"intent": intent, "query": message, "confidence": 0.99}
                for intent in self._intents
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }


def _domain_runner(context):
    if context.task.domain is BusinessDomain.STOCK_RESEARCH:
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="贵州茅台分析完成。",
            structured_data={"stock_analysis": {"600519": {"rating": "关注"}}},
        )
    return DomainOutcome(
        task_id=context.task.task_id,
        domain=context.task.domain,
        status="success",
        summary="建议稳健型基金。",
        structured_data={"product_analysis": {"recommended": ["基金A"]}},
    )


def _v2_system(monkeypatch, intents):
    system = object.__new__(AdvisorSystem)
    system._workflow_lock = threading.RLock()
    system._stop_lock = threading.Lock()
    system._stop_requests = {}
    system._active_runs = {}
    system._progress_lock = threading.Lock()
    system._progress_callbacks = {}
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._progress_context = type("Ctx", (), {"callback": None})()
    system.memory = type("M", (), {
        "window_size": 10,
        "load_context": lambda self, c, conv, fb: {
            "profile": {}, "context_text": "", "sliding_window": [],
        },
        "append_window_message": lambda *a, **k: None,
        "update_profile_from_result": lambda *a, **k: None,
    })()
    system.audit = type("A", (), {
        "create_run": lambda *a, **k: None,
        "complete_run": lambda *a, **k: None,
        "is_available": lambda self: False,
    })()
    system.get_checkpoint_conversation_messages = lambda *a, **k: []
    system._emit_progress = lambda *a, **k: None
    system._trace_agent = lambda *a, **k: None
    system.supervisor = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(intents),
            conversation_runner=lambda state: {"final_response": "你好。", "status": "success"},
            domain_runner=_domain_runner,
        )
    )
    monkeypatch.setattr(
        "finance_agent.orchestrator.orchestrator.get_database",
        lambda: type("DB", (), {"append_conversation_message": lambda *a, **k: None})(),
    )
    return system


def test_composite_request_uses_plan_then_compliance(monkeypatch):
    system = _v2_system(monkeypatch, ["stock_analysis", "product_analysis"])

    result = system.handle_message("分析贵州茅台并比较合适的基金产品", customer_id="CUST1")

    assert result["run_status"] in {"completed", "partial", "processing"}
    assert result["compliance_result"]["action"] in {"passed", "rewritten", "blocked"}
    assert result["stock_analysis"]
    assert result["product_analysis"]


def test_compliant_output_passes_compliance(monkeypatch):
    system = _v2_system(monkeypatch, ["stock_analysis"])

    result = system.handle_message("分析贵州茅台", customer_id="CUST1")

    assert result["compliance_result"]["action"] in {"passed", "rewritten"}
    assert result["stock_analysis"]


def test_violating_output_is_rewritten_or_blocked_not_shown_raw(monkeypatch):
    """违规草稿绝不以原样展示：要么被改写，要么被拦截。"""
    system = _v2_system(monkeypatch, ["stock_analysis"])

    def violating_runner(context):
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="该股稳赚不赔，必涨。",
        )

    system.supervisor = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(["stock_analysis"]),
            domain_runner=violating_runner,
        )
    )
    result = system.handle_message("分析贵州茅台", customer_id="CUST1")

    assert result["compliance_result"]["action"] in {"rewritten", "blocked"}
    assert "稳赚不赔" not in result["response"]
