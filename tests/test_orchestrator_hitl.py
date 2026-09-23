"""编排层 HITL：handle_message 的 awaiting_input / resume / 取消 / 画像落库。"""

from __future__ import annotations

import threading

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from finance_agent.orchestrator.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestrator.memory import UserProfileCard
from finance_agent.orchestrator.orchestrator import AdvisorSystem
from finance_agent.orchestrator.params import ExtractedParams
from finance_agent.orchestrator.supervisor_graph import SupervisorDependencies, build_supervisor_graph


class _FakeClassifier:
    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [{"intent": "stock_analysis", "query": message, "confidence": 0.99}],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }


class _FakeExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, message, history="", *, domains):
        self.calls += 1
        return ExtractedParams(values={}, warnings=[])


class _FakeMemory:
    """最小记忆层：上下文读取 + 画像读写（记录写入以供断言）。"""

    def __init__(self) -> None:
        self.window_size = 10
        self.saved: list[dict] = []

    def load_context(self, customer_id, conversation_id, fallback):
        return {"profile": {}, "context_text": "", "sliding_window": []}

    def append_window_message(self, *args, **kwargs):
        return None

    def update_profile_from_result(self, *args, **kwargs):
        return None

    def get_profile(self, customer_id):
        return UserProfileCard(customer_id=customer_id.upper())

    def save_profile(self, profile):
        from dataclasses import asdict

        self.saved.append(asdict(profile))
        return True


class _Runner:
    def __init__(self) -> None:
        self.contexts = []

    def __call__(self, context):
        self.contexts.append(context)
        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="分析完成。",
        )


def _system(monkeypatch, *, runner=None, extractor=None) -> AdvisorSystem:
    system = object.__new__(AdvisorSystem)
    system._ensure_runtime_state()
    system.budgets = type("B", (), {"graph_steps": 32, "replans": 0, "react_steps": 4, "plan_tasks": 8, "compliance_rewrites": 1})()
    system.memory = _FakeMemory()
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
            classifier=_FakeClassifier(),
            domain_runner=runner or _Runner(),
            param_extractor=extractor or _FakeExtractor(),
        ),
        checkpointer=InMemorySaver(),
    )
    monkeypatch.setattr(
        "finance_agent.orchestrator.orchestrator.get_database",
        lambda: type("DB", (), {"append_conversation_message": lambda *a, **k: None})(),
    )
    return system


def test_missing_target_returns_awaiting_input(monkeypatch):
    system = _system(monkeypatch)

    result = system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")

    assert result["run_status"] == "awaiting_input"
    assert result["interrupt_id"], "必须下发 interrupt_id 供前端显式回传"
    assert result["pending_input"]["fields"][0]["name"] == "stock_target"
    assert "股票标的" in result["response"]
    assert result["conversation_id"] == "conv-1"


def test_resume_with_answers_completes_and_runs_domain(monkeypatch):
    runner = _Runner()
    system = _system(monkeypatch, runner=runner)

    system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")
    result = system.handle_message(
        "股票标的：600519", customer_id="CUST1", conversation_id="conv-1",
        resume=True, answers={"stock_target": "600519"},
    )

    assert result["run_status"] == "completed"
    assert not result.get("pending_input")
    assert runner.contexts[0].params["stock_target"] == "600519"


def test_free_text_new_message_cancels_pending_and_starts_fresh(monkeypatch):
    """挂起期间用户直接发新问题：放弃挂起 run 并开新轮，不得被当成回答。"""
    runner = _Runner()
    system = _system(monkeypatch, runner=runner)

    system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")
    # 不带 resume/answers 的自由文本：应关掉挂起 run 并重新开始（仍是 awaiting_input）。
    result = system.handle_message("算了，今天大盘怎么样", customer_id="CUST1", conversation_id="conv-1")

    assert result["run_status"] == "awaiting_input", "新问题同样缺少必填标的"
    assert runner.contexts == [], "被放弃的挂起 run 不得执行领域"


def test_answers_profile_fields_are_persisted(monkeypatch):
    system = _system(monkeypatch)

    system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")
    system.handle_message(
        "600519，偏稳健长期", customer_id="CUST1", conversation_id="conv-1",
        resume=True,
        answers={"stock_target": "600519", "risk_preference": "稳健", "holding_period": "长期"},
    )

    assert system.memory.saved, "弹窗填写的偏好必须写入长期画像"
    saved = system.memory.saved[-1]
    assert saved["risk_preference"] == "稳健"
    assert saved["holding_period"] == "长期"


def test_invalid_profile_answer_is_not_persisted(monkeypatch):
    system = _system(monkeypatch)

    system.handle_message("分析贵州茅台", customer_id="CUST1", conversation_id="conv-1")
    system.handle_message(
        "600519", customer_id="CUST1", conversation_id="conv-1",
        resume=True, answers={"stock_target": "600519", "risk_preference": "随便说说"},
    )

    assert system.memory.saved == [], "非法偏好取值不得写入画像"


def test_stream_yields_final_response_event_for_awaiting_input(monkeypatch):
    """SSE 追问随最终 response 事件下发，前端零新增事件类型即可消费。"""
    import asyncio

    system = _system(monkeypatch)

    async def drain():
        return [
            event async for event in system.handle_message_stream(
                "分析贵州茅台", customer_id="CUST1", conversation_id="conv-1",
            )
        ]

    events = asyncio.run(drain())
    final = events[-1]

    assert final["type"] == "response"
    assert final["data"]["run_status"] == "awaiting_input"
    assert final["data"]["pending_input"]["fields"][0]["name"] == "stock_target"
