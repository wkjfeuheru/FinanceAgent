"""运行闭环契约与标识工具测试。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from finance_agent.api.schemas.chat import to_chat_response
from finance_agent.shared.contracts import (
    DispatchPlan,
    ExpertResult,
    ExpertStatus,
    IntentKind,
    RequestEnvelope,
    ResponseEnvelope,
    RunStatus,
    Task,
    TaskKind,
    TaskStatus,
)
from finance_agent.shared.identifiers import generate_identifiers


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
            intent=IntentKind.STOCK_ANALYSIS,
            expert_name="stock_analysis",
            requirement="分析600519",
            status=TaskStatus.SUCCESS,
        )],
        results=[ExpertResult(
            task_id="task-1",
            intent=IntentKind.STOCK_ANALYSIS,
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
        run_id=identifiers.run_id,
        trace_id=identifiers.trace_id,
        user_id=uuid4(),
        customer_id="CUST001",
        conversation_id=identifiers.conversation_id,
        message_id=identifiers.message_id,
        message="分析 600519",
    )
    plan = DispatchPlan(tasks=[Task(task_id="task-1", kind=TaskKind.STOCK_ANALYSIS)])
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
    # intent 由 expert_name 按 IntentKind 推导，不再依赖硬编码映射表。
    assert result.intent is IntentKind.STOCK_ANALYSIS
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
                expert_name="market_insight",
                status=ExpertStatus.SUCCESS,
                summary="市场洞察完成",
                result_data={"market_insight": {"mode": "market_overview", "status": "success"}},
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
    assert legacy.task_plan == ["stock_analysis", "market_insight", "product_analysis"]
    assert legacy.stock_data == {"code": "600519"}
    assert legacy.fundamental_analysis == {"pe": 20.5}
    assert legacy.technical_analysis == {"trend": "up"}
    assert legacy.analysis_results[0]["rule_version"] == "research_rules/v1"
    assert legacy.market_insight == {"mode": "market_overview", "status": "success"}
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
