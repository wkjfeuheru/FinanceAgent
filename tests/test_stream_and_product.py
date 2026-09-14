"""产品工具与 SSE 链路测试。"""

import asyncio
from uuid import uuid4

from finance_agent.api.sse import build_final_response_event
from finance_agent.contracts import ExpertResult, ExpertStatus, ResponseEnvelope
from finance_agent.orchestrator.domains.product import ProductDomainDeps, build_product_domain_graph
from finance_agent.orchestrator.orchestrator import AdvisorSystem


def test_product_domain_without_pipeline_output_is_empty_not_fabricated():
    """无流水线结果时返回空数据，绝不从消息正则伪造产品代码。"""
    from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext, PlanTask

    class _EmptyPipeline:
        def analyze(self, request):
            from finance_agent.product_research.contracts import ProductResearchResult

            return ProductResearchResult(
                kind="comparison",
                product_codes=list(request.product_codes),
                assessments=[],
                report="产品库暂无该产品数据。",
                data_quality="critical_missing",
            )

    context = DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:product_research",
            domain=BusinessDomain.PRODUCT_RESEARCH,
            goal="请比较110011和000001基金",
            instruction="请比较110011和000001基金",
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message="请比较110011和000001基金",
    )
    graph = build_product_domain_graph(deps=ProductDomainDeps(pipeline=_EmptyPipeline()))

    outcome = graph.invoke({"context": context})["domain_outcome"]
    payload = outcome.structured_data["product_analysis"]

    assert payload["type"] == "comparison"
    assert payload["products"] == []
    assert payload["data_quality"] == "critical_missing"
    assert payload["report"] == "产品库暂无该产品数据。"


def test_final_sse_event_keeps_legacy_response_shape():
    """最终 SSE 事件应携带完整且可 JSON 序列化的旧响应。"""
    event = build_final_response_event(ResponseEnvelope(
        run_id=uuid4(),
        trace_id=uuid4(),
        conversation_id="conversation-test",
        message_id=uuid4(),
        response="测试回复",
        results=[ExpertResult(
            expert_name="product_analysis",
            status=ExpertStatus.SUCCESS,
            summary="产品分析完成",
            result_data={"report": "产品报告"},
        )],
    ))

    assert event["type"] == "response"
    assert event["content"] == "测试回复"
    assert event["data"]["conversation_id"] == "conversation-test"
    assert event["data"]["product_analysis"] == {"report": "产品报告"}


def test_stream_emits_stages_and_final_response(monkeypatch):
    """SSE 包装层应输出阶段事件、最终响应及完整数据。"""
    system = object.__new__(AdvisorSystem)

    def fake_handle(message, chat_history=None, customer_id="CUST001", progress_callback=None, conversation_id=""):
        if progress_callback:
            progress_callback("manager", "完成分派")
        return {
            "response": "测试回复",
            "task_plan": ["casual_chat"],
            "conversation_id": conversation_id or "generated",
        }

    monkeypatch.setattr(system, "handle_message", fake_handle)

    async def collect():
        return [
            item async for item in system.handle_message_stream(
                "你好", conversation_id="conversation-test",
            )
        ]

    events = asyncio.run(collect())

    assert events[0]["type"] == "stage"
    assert any(item.get("type") == "response" for item in events)
    response = next(item for item in events if item.get("type") == "response")
    assert response["content"] == "测试回复"
    assert response["data"]["task_plan"] == ["casual_chat"]
