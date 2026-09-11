"""运行闭环契约、状态和标识工具测试。"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from finance_agent.api.schemas import to_chat_response
from finance_agent.contracts import (
    DispatchPlan,
    ExpertResult,
    ExpertStatus,
    FactSnapshot,
    IntentKind,
    PreparedContext,
    RequestEnvelope,
    ResponseEnvelope,
    RunStatus,
    Task,
    TaskKind,
    TaskStatus,
    generate_identifiers,
    propagate_identifiers,
    transition_run_status,
)


def test_task_contract_preserves_distinct_same_expert_intents():
    from finance_agent.contracts.adapters import normalize_dispatch_plan

    plan = normalize_dispatch_plan([
        {
            "intent": "market_query",
            "query": "分析贵州茅台",
            "confidence": 0.99,
            "execution_mode": "security_analysis",
        },
        {
            "intent": "stock_recommendation",
            "query": "推荐几只AI股票",
            "confidence": 0.98,
            "execution_mode": "candidate_search",
        },
    ], "分析贵州茅台，并推荐几只AI股票")

    assert [task.task_id for task in plan.tasks] == ["task-1", "task-2"]
    assert [task.intent for task in plan.tasks] == [
        IntentKind.MARKET_QUERY,
        IntentKind.STOCK_RECOMMENDATION,
    ]
    assert [task.expert_name for task in plan.tasks] == [
        "stock_analysis", "stock_analysis",
    ]
    assert all(task.status is TaskStatus.PENDING for task in plan.tasks)


def test_response_envelope_exposes_run_status_tasks_results_and_warnings():
    response = ResponseEnvelope(
        run_id=uuid4(),
        trace_id=uuid4(),
        conversation_id="conversation-1",
        message_id=uuid4(),
        response="部分完成",
        run_status=RunStatus.PARTIAL,
        tasks=[Task(
            task_id="task-1",
            intent=IntentKind.MARKET_QUERY,
            expert_name="stock_analysis",
            requirement="分析600519",
            execution_mode="security_analysis",
            status=TaskStatus.SUCCESS,
        )],
        results=[ExpertResult(
            task_id="task-1",
            intent=IntentKind.MARKET_QUERY,
            expert_name="stock_analysis",
            status=ExpertStatus.SUCCESS,
            summary="完成",
        )],
        warnings=["另一个任务失败"],
    )

    payload = response.model_dump(mode="json")
    assert payload["run_status"] == "partial"
    assert payload["tasks"][0]["task_id"] == "task-1"
    assert payload["results"][0]["task_id"] == "task-1"
    assert payload["warnings"] == ["另一个任务失败"]


def test_contracts_serialize_to_json_schema_and_json():
    """核心契约应能生成 JSON Schema 并完成嵌套 JSON 序列化。"""
    identifiers = generate_identifiers("conversation-1")
    request = RequestEnvelope(
        **propagate_identifiers(identifiers),
        user_id=uuid4(),
        customer_id="CUST001",
        message="分析 600519",
    )
    plan = DispatchPlan(tasks=[Task(task_id="task-1", kind=TaskKind.STOCK_ANALYSIS)])
    prepared = PreparedContext(
        facts=[FactSnapshot(
            fact_id="fact-1",
            domain="market",
            source="fixture",
            fetched_at=datetime.now(timezone.utc),
            valid_until=datetime.now(timezone.utc),
            payload={"code": "600519"},
        )]
    )
    result = ExpertResult(
        expert_name="stock_analysis",
        status=ExpertStatus.SUCCESS,
        summary="已完成分析",
        fact_ids=["fact-1"],
        result_data={"code": "600519"},
    )
    response = ResponseEnvelope(
        run_id=identifiers.run_id,
        trace_id=identifiers.trace_id,
        conversation_id=identifiers.conversation_id,
        message_id=uuid4(),
        response="分析完成",
        results=[result],
    )

    assert {"run_id", "trace_id", "message_id"} <= set(request.model_json_schema()["properties"])
    assert plan.model_dump(mode="json")["tasks"][0]["kind"] == "stock_analysis"
    assert prepared.model_dump(mode="json")["facts"][0]["fact_id"] == "fact-1"
    assert '"expert_name":"stock_analysis"' in response.model_dump_json()


def test_response_envelope_maps_to_legacy_chat_response():
    """新响应包应映射为前端既有的 ChatResponse 字段。"""
    response = ResponseEnvelope(
        run_id=uuid4(),
        trace_id=uuid4(),
        conversation_id="conversation-1",
        message_id=uuid4(),
        response="综合分析完成",
        results=[
            ExpertResult(
                expert_name="stock_analysis",
                status=ExpertStatus.SUCCESS,
                summary="股票分析完成",
                result_data={
                    "stock_data": {"code": "600519"},
                    "fundamental_analysis": {"pe": 20.5},
                    "technical_analysis": {"trend": "up"},
                    "analysis_results": [{"rule_version": "research_rules/v1"}],
                },
            ),
            ExpertResult(
                expert_name="asset_allocation",
                status=ExpertStatus.SUCCESS,
                summary="配置完成",
                result_data={"weights": {"stock": 0.6}, "debate": {"summary": "风险可控"}},
            ),
            ExpertResult(
                expert_name="product_analysis",
                status=ExpertStatus.SUCCESS,
                summary="产品分析完成",
                result_data={"report": "适合稳健投资者"},
            ),
        ],
    )

    legacy = to_chat_response(response)

    assert legacy.response == "综合分析完成"
    assert legacy.task_plan == ["stock_analysis", "asset_allocation", "product_analysis"]
    assert legacy.stock_data == {"code": "600519"}
    assert legacy.fundamental_analysis == {"pe": 20.5}
    assert legacy.technical_analysis == {"trend": "up"}
    assert legacy.analysis_results[0]["rule_version"] == "research_rules/v1"
    assert legacy.allocation_result.weights == {"stock": 0.6}
    assert legacy.debate_result == {"summary": "风险可控"}
    assert legacy.product_analysis == {"report": "适合稳健投资者"}


def test_contracts_reject_unknown_fields():
    """契约边界不得静默接受拼写错误或未声明字段。"""
    with pytest.raises(ValidationError):
        RequestEnvelope(
            run_id=uuid4(),
            trace_id=uuid4(),
            user_id=uuid4(),
            customer_id="CUST001",
            conversation_id="conversation-1",
            message_id=uuid4(),
            message="你好",
            unexpected="invalid",
        )


def test_terminal_run_status_cannot_be_overwritten():
    """运行进入终态后只能重复写入同一终态。"""
    assert transition_run_status(RunStatus.RUNNING, RunStatus.COMPLETED) == RunStatus.COMPLETED
    assert transition_run_status(RunStatus.COMPLETED, RunStatus.COMPLETED) == RunStatus.COMPLETED
    with pytest.raises(ValueError):
        transition_run_status(RunStatus.COMPLETED, RunStatus.RUNNING)


def test_identifiers_are_propagated_from_request_to_expert_result():
    """同一请求的运行和 trace 标识应可关联到专家结果 metadata。"""
    identifiers = generate_identifiers("conversation-1")
    propagated = propagate_identifiers(identifiers)
    result = ExpertResult(
        expert_name="product_analysis",
        status=ExpertStatus.DEGRADED,
        summary="产品数据暂不可用",
        degradation_reason="source_timeout",
    )
    expert_metadata = {**propagated, "expert_name": result.expert_name}

    assert expert_metadata["trace_id"] == str(identifiers.trace_id)
    assert expert_metadata["run_id"] == str(identifiers.run_id)
    assert expert_metadata["conversation_id"] == identifiers.conversation_id
    assert expert_metadata["message_id"] == str(identifiers.message_id)
