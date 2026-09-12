"""产品工具与 SSE 链路测试。"""

import asyncio
from uuid import uuid4

from finance_agent.agents.product_analysis import ProductAnalysisAgent
from finance_agent.api.sse import build_final_response_event
from finance_agent.contracts import ExpertResult, ExpertStatus, ResponseEnvelope
from finance_agent.orchestrator.orchestrator import AdvisorSystem


def test_product_agent_build_result_without_pipeline_output_is_empty_not_fabricated():
    """无流水线结果时构造兼容空结果，绝不从消息正则伪造产品代码。"""
    agent = ProductAnalysisAgent()
    result = agent._build_result({
        "user_message": "请比较110011和000001基金",
        "agent_response": "产品库暂无该产品数据",
    })

    assert result["type"] == "comparison"
    # 代码只能来自产品库解析；消息里的数字不得被当作已解析产品。
    assert result["product_codes"] == []
    assert result["products"] == []
    assert result["data_quality"] == "critical_missing"
    assert result["report"] == "产品库暂无该产品数据"


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
