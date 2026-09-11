"""任务上下文裁剪与事实引用测试。"""

from datetime import datetime, timezone

from finance_agent.contracts import FactSnapshot, IntentKind, Task
from finance_agent.orchestrator.context_builder import (
    build_intent_context,
    build_synthesis_context,
    build_task_context,
)


def test_task_context_keeps_current_requirement_and_relevant_slots():
    task = Task(
        task_id="task-1",
        intent=IntentKind.MARKET_QUERY,
        expert_name="stock_analysis",
        requirement="分析600519",
        execution_mode="security_analysis",
    )
    state = {
        "user_message": "分析600519并给我配置建议",
        "memory_context": "很长的历史摘要",
        "intent_slots": {"market_query": {"stock_codes": ["600519"]}},
        "facts": [FactSnapshot(
            fact_id="fact-1", domain="market", source="fixture",
            fetched_at=datetime.now(timezone.utc), payload={"code": "600519"},
        )],
    }

    context = build_task_context(state, task, max_chars=300)

    assert context["requirement"] == "分析600519"
    assert context["slots"]["stock_codes"] == ["600519"]
    assert context["fact_ids"] == ["fact-1"]
    assert "很长的历史摘要" not in str(context)


def test_synthesis_context_contains_status_and_warnings_without_raw_history():
    task = Task(
        task_id="task-1", intent=IntentKind.MARKET_QUERY,
        expert_name="stock_analysis", requirement="分析", execution_mode="security_analysis",
    )
    state = {"user_message": "分析", "memory_context": "原始历史"}
    result = {
        "task_id": "task-1", "intent": "market_query", "expert_name": "stock_analysis",
        "status": "failed", "summary": "数据不可用", "error_code": "provider_error",
    }

    context = build_synthesis_context(state, [task], [result], max_chars=500)

    assert context["tasks"][0]["task_id"] == "task-1"
    assert context["results"][0]["error_code"] == "provider_error"
    assert "原始历史" not in str(context)


def test_task_context_strips_audit_only_fact_payload():
    """完整 K 线等重证据字段只供审计重放，不得进入专家上下文。"""
    task = Task(
        task_id="task-1",
        intent=IntentKind.MARKET_QUERY,
        expert_name="stock_analysis",
        requirement="分析600519",
        execution_mode="security_analysis",
    )
    state = {
        "user_message": "分析600519",
        "facts": [FactSnapshot(
            fact_id="stock_snapshot:600519:abc", domain="market", source="fixture",
            fetched_at=datetime.now(timezone.utc),
            payload={
                "code": "600519",
                "quality_status": "complete",
                "inputs": {"history": {"data": [{"close": 10.0}] * 500}},
                "provenance": {"quote": {"source": "fixture"}},
            },
        )],
    }

    context = build_task_context(state, task)

    payload = context["facts"][0]["payload"]
    assert "inputs" not in payload
    assert payload["quality_status"] == "complete"
    assert context["fact_ids"] == ["stock_snapshot:600519:abc"]


def test_intent_context_prioritizes_current_message():
    context = build_intent_context({
        "user_message": "分析600519",
        "memory_context": "history",
        "pending_clarifications": {"q1": "请确认标的"},
    })
    assert context["current_message"] == "分析600519"
    assert context["pending_clarifications"]["q1"] == "请确认标的"
